"""Read-only audit: find stored notes whose Notion `mermaid` code blocks lost their language mark.

MEG-170. The Notion importer (notion_content.convert) writes every code block as a bare
fence, so a block that Notion marks as `mermaid` is stored without the `mermaid` info string.
This tool never writes to Supabase or Notion. It reads stored notes (GET only), re-reads the
Notion originals, and writes a review package to --out-dir:

  report.json      per-note decisions and line positions (no note text)
  apply.sql        guarded UPDATEs a human runs on STG/PRD (not run by this tool)
  restore.sql      guarded UPDATEs that put the original bodies back
  backup/          original body_markdown of every changed note (restricted data)

Run (backend/, one environment at a time; the target comes from the URL/key you export):
  MERMAID_AUDIT_SUPABASE_URL      https://<project>.supabase.co
  MERMAID_AUDIT_SUPABASE_SECRET_KEY  secret key of that project (read via GET only)
  NOTION_IMPORT_TOKEN             the importer's Notion integration token
  uv run python -m scripts.audit_mermaid_fences --out-dir <folder outside the repo>
stdout is counts only. Re-run after apply.sql: "notes_to_change" should be 0 (idempotent).

A fence is changed only when ALL code blocks of the note line up with the stored fences
(same count, same text) and the stored opening fence has no language yet. Anything else is
listed as excluded with a reason and left for a human.
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from scripts.import_notion import ImportFailure, Notion
from scripts.notion_content import canonical_id, plain

PAGE_SIZE = 200
BODY_LIMIT = 200000  # notes_body_markdown_length_check

# Must match the traversal in notion_content.convert (kinds whose children are walked).
CONTAINERS = {"paragraph", "heading_1", "heading_2", "heading_3", "heading_4",
              "bulleted_list_item", "numbered_list_item", "to_do",
              "toggle", "quote", "callout", "column", "column_list"}

OPEN_FENCE = re.compile(r"^(?P<lead>\s*(?:[-*+]\s+)*)(?P<fence>`{3,})(?P<info>[^`\n]*)$")
CLOSE_FENCE = re.compile(r"^(?P<fence>`{3,})\s*$")


# ---------------------------------------------------------------------------
# Notion side: code blocks in the same order convert() emits them
# ---------------------------------------------------------------------------

def notion_code_blocks(notion, page_id):
    blocks, visited = [], set()

    def walk(parent, depth=0):
        if depth > 32 or parent in visited:
            raise ValueError("block_limit")
        visited.add(parent)
        for block in notion.children(parent):
            if block.get("archived") or block.get("in_trash"):
                continue
            kind = block["type"]
            data = block.get(kind, {})
            if kind == "code":
                blocks.append({"id": canonical_id(block["id"]),
                               "language": data.get("language") or "",
                               "text": plain(data.get("rich_text", []))})
            elif kind in CONTAINERS and block.get("has_children"):
                walk(canonical_id(block["id"]), depth + 1)

    walk(page_id)
    return blocks


# ---------------------------------------------------------------------------
# Stored side: fenced blocks in body_markdown
# ---------------------------------------------------------------------------

def stored_fences(markdown):
    """Return (fences, lines). Each fence: line index, lead, fence, info, content. None if malformed."""
    lines = markdown.split("\n")
    fences, i = [], 0
    while i < len(lines):
        match = OPEN_FENCE.match(lines[i])
        if not match:
            i += 1
            continue
        lead, fence = match["lead"], match["fence"]
        width = len(lead)
        content, j = [], i + 1
        while j < len(lines):
            # Undo the list indentation (at most `width` leading blanks), keep the code's own indent.
            stripped = re.sub(rf"^[ \t]{{0,{width}}}", "", lines[j])
            closing = CLOSE_FENCE.match(stripped)
            if closing and len(closing["fence"]) >= len(fence):
                break
            content.append(stripped)
            j += 1
        else:
            return None, lines
        fences.append({"line": i, "lead": lead, "fence": fence, "info": match["info"].strip(),
                       "content": "\n".join(content)})
        i = j + 1
    return fences, lines


# ---------------------------------------------------------------------------
# Decision for one note
# ---------------------------------------------------------------------------

def audit_note(body, blocks):
    """Decide fence changes for one note. Never guesses: any doubt means excluded."""
    result = {"status": "ok", "changes": [], "already_marked": 0, "new_body": None}
    mermaid = [b for b in blocks if b["language"].lower() == "mermaid"]
    if not mermaid:
        result["status"] = "no_mermaid"
        return result
    fences, lines = stored_fences(body)
    if fences is None:
        result["status"] = "parse_error"
        return result
    if len(fences) != len(blocks):
        result["status"] = "count_mismatch"
        result["detail"] = {"stored_fences": len(fences), "notion_code_blocks": len(blocks)}
        return result
    for index, (fence, block) in enumerate(zip(fences, blocks)):
        if fence["content"] != block["text"]:
            result["status"] = "content_mismatch"
            result["detail"] = {"block_index": index, "line": fence["line"] + 1}
            return result
    new_lines = list(lines)
    for index, (fence, block) in enumerate(zip(fences, blocks)):
        if block["language"].lower() != "mermaid":
            continue
        if fence["info"].lower() == "mermaid":
            result["already_marked"] += 1
        elif fence["info"]:
            result["status"] = "info_conflict"
            result["detail"] = {"block_index": index, "line": fence["line"] + 1,
                                "stored_info_length": len(fence["info"])}  # never echo hand-edited text
            result["changes"] = []
            return result
        else:
            before = lines[fence["line"]]
            after = before + "mermaid"
            new_lines[fence["line"]] = after
            result["changes"].append({"block_index": index, "notion_block_id": block["id"],
                                      "line": fence["line"] + 1, "before": before, "after": after})
    if not result["changes"]:
        result["status"] = "already_marked"
        return result
    result["new_body"] = "\n".join(new_lines)
    if len(result["new_body"]) > BODY_LIMIT:  # notes_body_markdown_length_check would roll the whole apply back
        result.update(status="length_limit", detail={"new_length": len(result["new_body"])}, changes=[], new_body=None)
        return result
    # Safety: only the listed opening lines may differ.
    changed = {n for n, (a, b) in enumerate(zip(lines, new_lines)) if a != b}
    if changed != {c["line"] - 1 for c in result["changes"]} or len(lines) != len(new_lines):
        raise ValueError("unexpected_diff")
    return result


# ---------------------------------------------------------------------------
# SQL drafts (a human runs them; this tool only writes the files)
# ---------------------------------------------------------------------------

def dollar_quote(text, taken):
    """Wrap text in a dollar-quote whose tag appears in neither the text nor any tag already used."""
    n = 0
    while True:
        tag = "$mfa_" + hashlib.sha256(f"{n}:{text}".encode()).hexdigest()[:10] + "$"
        if tag not in text and tag not in taken:
            taken.add(tag)
            return f"{tag}{text}{tag}"
        n += 1


def guarded_updates(items, source_key, target_key, title):
    """items: dicts with note_id, <source_key>, <target_key> bodies."""
    out = [f"-- {title}", "-- Run once per environment, in one transaction. Fails (and changes nothing) if a note",
           "-- was edited after the audit. The notes_bump_revision trigger raises revision by 1 per UPDATE.",
           "begin;"]
    for item in items:
        taken = set()
        new = dollar_quote(item[target_key], taken)
        old = dollar_quote(item[source_key], taken)
        # The outer DO delimiter must not occur inside either body or inside the other tags.
        both = item[target_key] + item[source_key]
        n = 0
        while True:
            outer = "$mfa_do" + hashlib.sha256(f"{n}:{both}".encode()).hexdigest()[:10] + "$"
            if outer not in both and outer not in taken:
                break
            n += 1
        note_id = int(item["note_id"])
        out.append("\n".join([
            f"do {outer} begin",
            f"  update public.notes set body_markdown = {new}",
            f"   where id = {note_id} and body_markdown = {old};",
            f"  if not found then raise exception 'note {note_id} changed since audit'; end if;",
            f"end {outer};"]))
    out.append("commit;")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# I/O: read-only Supabase client, Notion reader, package writer
# ---------------------------------------------------------------------------

class ReadOnlyNotes:
    """GET-only PostgREST reader for public.notes."""

    def __init__(self, http, url, key):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
            raise ImportFailure("source_url")
        self.http, self.url, self.key = http, url.rstrip("/"), key

    def notes(self):
        offset = 0
        while True:
            response = self.http.get(self.url + "/rest/v1/notes", headers={"apikey": self.key}, params={
                "select": "id,notion_page_id,revision,updated_at,body_markdown",
                "notion_page_id": "not.is.null", "order": "id.asc",
                "limit": str(PAGE_SIZE), "offset": str(offset)})
            if response.status_code != 200:
                raise ImportFailure("source_http")
            rows = response.json()
            yield from rows
            if len(rows) < PAGE_SIZE:
                return
            offset += PAGE_SIZE


class NotionReader(Notion):
    """Reuses the importer's request/children logic; needs only a token."""

    def __init__(self, http, token):
        self.http, self.token = http, token


def audit(source, notion):
    counts = {"notes_scanned": 0, "notes_with_bare_fence": 0, "notes_with_mermaid": 0,
              "notes_to_change": 0, "blocks_to_change": 0, "blocks_already_marked": 0,
              "excluded": {}, "notion_unreadable": 0}
    report, changed = [], []
    for row in source.notes():
        counts["notes_scanned"] += 1
        body = row["body_markdown"]
        fences, _ = stored_fences(body)
        if fences is not None and not any(f["info"] == "" for f in fences):
            continue  # every stored fence already has a language; nothing to recover
        counts["notes_with_bare_fence"] += 1
        try:
            blocks = notion_code_blocks(notion, canonical_id(row["notion_page_id"]))
        except Exception:
            counts["notion_unreadable"] += 1
            report.append({"note_id": row["id"], "status": "notion_unreadable"})
            continue
        decision = audit_note(body, blocks)
        if decision["status"] == "no_mermaid":
            continue
        counts["notes_with_mermaid"] += 1
        counts["blocks_already_marked"] += decision["already_marked"]
        entry = {"note_id": row["id"], "notion_page_id": row["notion_page_id"], "revision": row["revision"],
                 "updated_at": row["updated_at"], "status": decision["status"],
                 "detail": decision.get("detail"), "changes": decision["changes"]}
        report.append(entry)
        if decision["new_body"] is not None:
            counts["notes_to_change"] += 1
            counts["blocks_to_change"] += len(decision["changes"])
            changed.append({"note_id": row["id"], "original": body, "updated": decision["new_body"]})
        elif decision["status"] != "already_marked":
            counts["excluded"][decision["status"]] = counts["excluded"].get(decision["status"], 0) + 1
    return counts, report, changed


def check_out_dir(out_dir):
    """Refuse any folder inside a git checkout or worktree, or one that already has content."""
    out_dir = Path(out_dir).resolve()
    for folder in (out_dir, *out_dir.parents):
        if (folder / ".git").exists():
            raise ImportFailure("out_dir_in_repo")  # bodies are restricted data; keep them out of git
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ImportFailure("out_dir_not_empty")  # stale backups would not match the new SQL
    return out_dir


def write_package(out_dir, counts, report, changed):
    out_dir = check_out_dir(out_dir)
    (out_dir / "backup").mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps({"counts": counts, "notes": report}, ensure_ascii=False, indent=2), encoding="utf-8")
    for item in changed:
        (out_dir / "backup" / f"note-{int(item['note_id'])}.original.md").write_text(
            item["original"], encoding="utf-8", newline="")
    (out_dir / "apply.sql").write_text(guarded_updates(
        changed, "original", "updated", "MEG-170 apply: add mermaid language to confirmed code fences"),
        encoding="utf-8", newline="\n")
    (out_dir / "restore.sql").write_text(guarded_updates(
        changed, "updated", "original", "MEG-170 restore: put original bodies back (only if apply.sql was run)"),
        encoding="utf-8", newline="\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", required=True, help="restricted folder OUTSIDE this repository")
    args = parser.parse_args(argv)
    logging.disable(logging.CRITICAL)  # library debug logs must not expose keys or note text
    fatal = None
    try:
        check_out_dir(args.out_dir)  # fail before any network call
        env = os.environ
        with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as http:
            source = ReadOnlyNotes(http, env["MERMAID_AUDIT_SUPABASE_URL"], env["MERMAID_AUDIT_SUPABASE_SECRET_KEY"])
            notion = NotionReader(http, env["NOTION_IMPORT_TOKEN"])
            counts, report, changed = audit(source, notion)
        write_package(args.out_dir, counts, report, changed)
        print(json.dumps(counts, sort_keys=True))
        if counts["notion_unreadable"]:
            # A bad token or missing page access must not look like "nothing to fix".
            fatal = "notion_unreadable"
    except (Exception, KeyboardInterrupt) as error:
        fatal = type(error).__name__ if not isinstance(error, ImportFailure) else str(error)
    if fatal:
        print(json.dumps({"fatal_error": fatal}))
    return 1 if fatal else 0


if __name__ == "__main__":
    sys.exit(main())
