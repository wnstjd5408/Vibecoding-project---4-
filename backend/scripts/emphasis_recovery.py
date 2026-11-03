"""Read-only survey and reviewed SQL packages. Never executes remote writes.

See docs/emphasis-recovery.md. All bodies/plans/backups belong outside git.
"""
import argparse
import base64
from collections import Counter
import difflib
import hashlib
import json
import os
import re
from pathlib import Path

import httpx
from markdown_it import MarkdownIt

from app.glossary_spans import code_mask
from scripts.audit_mermaid_fences import ReadOnlyNotes, check_out_dir
from scripts.notion_content import emphasize


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def candidates(body):
    """Conservative single-run candidates. Discovery is NOT intent approval.

    Never globally substitute Markdown. Ambiguous/token-bearing lines are
    reported for manual review; only a single isolated simple run is eligible.
    """
    mask = code_mask(body)
    result = []
    offset = 0
    for line in body.splitlines(keepends=True):
        if "*" in line:
            entry = {"start": offset, "end": offset + len(line), "reason": "ambiguous", "eligible": False}
            matches = list(re.finditer(r"(?<![\\*])(\*{1,3})([^*\r\n]+?)\1(?!\*)", line))
            if any(mask[offset:offset + len(line)]) or line.startswith(("    ", "\t")):
                entry["reason"] = "code"
            elif any(c in line for c in "[]<>`\\_~!") or re.search(r"(?:https?://|note-image:)", line):
                entry["reason"] = "protected_token"
            elif len(matches) == 1 and line.count("*") == 2 * len(matches[0][1]):
                match = matches[0]
                raw, marker = match[2], match[1]
                if raw != raw.strip() and raw.strip() and all(c.isalnum() or c.isspace() or ord(c) > 127 for c in raw):
                    before = match[0]
                    after = emphasize(raw, marker)
                    proposed = line[:match.start()] + after + line[match.end():]
                    tokens = MarkdownIt().parseInline(proposed)[0].children
                    required = {1: {"em_open"}, 2: {"strong_open"}, 3: {"em_open", "strong_open"}}[len(marker)]
                    if not required <= {token.type for token in tokens}:
                        entry["reason"] = "unparseable_boundary"
                    elif proposed.startswith(("    ", "\t")):
                        entry["reason"] = "would_create_code_block"
                    else:
                        entry.update(start=offset + match.start(), end=offset + match.end(),
                                     before=before, after=after, reason="needs_intent_review", eligible=True)
                elif raw == raw.strip():
                    entry["reason"] = "normal_emphasis"
            result.append(entry)
        offset += len(line)
    return result


def read_notes(source):
    """Keyset pagination continues until EMPTY, even if the server caps pages."""
    last = 0
    while True:
        response = source.http.get(source.url + "/rest/v1/notes", headers={"apikey": source.key}, params={
            "select": "id,revision,updated_at,body_markdown", "id": f"gt.{last}",
            "order": "id.asc", "limit": "200"})
        if response.status_code != 200:
            raise ValueError("source_http")
        rows = response.json()
        if not isinstance(rows, list):
            raise ValueError("source_shape")
        if not rows:
            return
        for row in rows:
            if type(row["id"]) is not int or row["id"] <= last:
                raise ValueError("source_order")
            last = row["id"]
            yield row


def survey(rows):
    notes, seen = [], set()
    for row in rows:
        note_id, revision, body = row["id"], row["revision"], row["body_markdown"]
        if type(note_id) is not int or note_id <= 0 or note_id in seen or type(revision) is not int or revision < 1:
            raise ValueError("invalid_note")
        if not isinstance(body, str) or len(body) > 200000 or "\x00" in body:
            raise ValueError("invalid_body")
        seen.add(note_id)
        entries = candidates(body)
        for entry in entries:
            entry["candidate_id"] = digest(canonical([note_id, revision, digest(body), entry]))
        notes.append({"id": note_id, "revision": revision, "body": body,
                      "sha256": digest(body), "candidates": entries})
    return {"version": 1, "notes": notes}


def reviewed_changes(plan, approved):
    if not isinstance(approved, list) or any(not isinstance(value, str) for value in approved):
        raise ValueError("invalid_approval_list")
    # Re-derive every candidate; edited plans cannot smuggle arbitrary changes.
    regenerated = survey({"id": n["id"], "revision": n["revision"], "body_markdown": n["body"]} for n in plan["notes"])
    if plan != regenerated or len(approved) != len(set(approved)):
        raise ValueError("invalid_plan")
    allowed = {c["candidate_id"] for n in plan["notes"] for c in n["candidates"] if c["eligible"]}
    if not set(approved) <= allowed:
        raise ValueError("unreviewable_candidate")
    changes = []
    for note in plan["notes"]:
        selected = [c for c in note["candidates"] if c["candidate_id"] in approved]
        if not selected:
            continue
        after = note["body"]
        for c in reversed(selected):
            after = after[:c["start"]] + c["after"] + after[c["end"]:]
        changes.append({"id": note["id"], "revision": note["revision"], "before": note["body"], "after": after})
    return changes


def sql_text(text):
    # Base64 has no quotes, backslashes or dollar delimiters.
    return "convert_from(decode('" + base64.b64encode(text.encode()).decode() + "','base64'),'UTF8')"


def sql_package(changes, run_id, rollback=False):
    if not re.fullmatch(r"[a-f0-9]{64}", run_id):
        raise ValueError("run_id")
    out = ["\\set ON_ERROR_STOP on", "begin;", "set local lock_timeout = '5s';", "set local statement_timeout = '60s';"]
    for change in sorted(changes, key=lambda c: c["id"]):
        note_id, rev = change["id"], change["revision"]
        before, after = change["before"], change["after"]
        if rollback:
            before, after, rev = after, before, rev + 1
        status = "restored" if rollback else "applied"
        out.append(f"""do $recovery$
declare n public.notes%rowtype; old_updated timestamptz;
begin
  select * into n from public.notes where id = {note_id} for update;
  if not found then raise exception 'run {run_id} note {note_id}: missing'; end if;
  if n.revision = {rev + 1} and n.body_markdown = {sql_text(after)} then
    raise notice 'run {run_id} note {note_id}: already_{status}';
  elsif n.revision = {rev} and n.body_markdown = {sql_text(before)}
    and encode(sha256(convert_to(n.body_markdown, 'UTF8')), 'hex') = '{digest(before)}' then
    old_updated := n.updated_at;
    update public.notes set body_markdown = {sql_text(after)} where id = {note_id} returning * into n;
    if n.revision <> {rev + 1} or n.updated_at is not distinct from old_updated then
      raise exception 'run {run_id} note {note_id}: trigger_contract';
    end if;
    perform public.ai_invalidate_explanations({note_id}, null, null);
    raise notice 'run {run_id} note {note_id}: {status}';
  else
    raise exception 'run {run_id} note {note_id}: conflict';
  end if;
end $recovery$;""")
    out += ["commit;", f"\\echo run {run_id} committed"]
    return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--snapshot", help="Offline JSON rows instead of read-only GET")
    parser.add_argument("--plan", help="Previously reviewed plan.json")
    parser.add_argument("--approved", help="JSON list of individually accepted candidate IDs")
    parser.add_argument("--approve-plan-sha256", help="Explicit approval of exact plan bytes")
    args = parser.parse_args()
    out = check_out_dir(args.out_dir)
    if args.plan:
        if args.snapshot or not args.approved or not args.approve_plan_sha256:
            raise ValueError("approval_required")
        data = Path(args.plan).read_text(encoding="utf-8")
        if digest(data) != args.approve_plan_sha256:
            raise ValueError("approval_hash")
        plan = json.loads(data)
        approved = json.loads(Path(args.approved).read_text(encoding="utf-8"))
        changes = reviewed_changes(plan, approved)
        if not changes:
            raise ValueError("no_approved_changes")
        run_id = digest(canonical([plan, approved]))
        out.mkdir(parents=True, exist_ok=True)
        (out / "backup.json").write_text(canonical(changes), encoding="utf-8")
        (out / "apply.sql").write_text(sql_package(changes, run_id), encoding="utf-8")
        (out / "rollback.sql").write_text(sql_package(changes, run_id, True), encoding="utf-8")
        print(json.dumps({"run_id": run_id, "notes": len(changes), "executed": False}))
    else:
        if args.approved or args.approve_plan_sha256:
            raise ValueError("plan_required")
        if args.snapshot:
            plan = survey(json.loads(Path(args.snapshot).read_text(encoding="utf-8")))
        else:
            with httpx.Client(timeout=30, follow_redirects=False) as client:
                source = ReadOnlyNotes(client, os.environ["EMPHASIS_AUDIT_URL"], os.environ["EMPHASIS_AUDIT_SECRET_KEY"])
                plan = survey(read_notes(source))
        data = canonical(plan)
        out.mkdir(parents=True, exist_ok=True)
        (out / "plan.json").write_text(data, encoding="utf-8")
        report = []
        for note in plan["notes"]:
            for c in note["candidates"]:
                report.append({"note_id": note["id"], "revision": note["revision"], **c,
                    "diff": list(difflib.unified_diff(c.get("before", "").splitlines(), c.get("after", "").splitlines(), lineterm=""))})
        (out / "report.json").write_text(canonical(report), encoding="utf-8")
        print(json.dumps({"notes": len(plan["notes"]), "candidates": len(report), "automatic": 0,
                          "reasons": dict(Counter(c["reason"] for c in report)),
                          "reviewable": sum(c["eligible"] for c in report),
                          "excluded_or_ambiguous": sum(not c["eligible"] for c in report), "plan_sha256": digest(data)}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, httpx.HTTPError):
        # Never print raw HTTP exceptions, bodies, keys or private paths.
        raise SystemExit("emphasis_recovery_failed; check input, approval and restricted output directory") from None
