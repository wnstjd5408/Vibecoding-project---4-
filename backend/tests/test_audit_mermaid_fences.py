"""MEG-170: synthetic Notion/PostgREST data only; never contact real services."""

import json
import logging
import re
from unittest.mock import Mock

import httpx
import pytest

from scripts import audit_mermaid_fences as audit
from scripts.import_notion import ImportFailure
from scripts.notion_content import convert

PAGE = "00000000-0000-4000-8000-000000000001"


def block(n, kind, text="", language=None, children=False):
    data = {"rich_text": [{"plain_text": text}]}
    if language is not None:
        data["language"] = language
    return {"id": f"00000000-0000-4000-8000-{n:012d}", "type": kind, kind: data, "has_children": children}


def code(n, text, language):
    return block(n, "code", text, language)


def tree_notion(tree):
    notion = Mock()
    notion.children.side_effect = lambda block_id: tree[block_id]
    return notion


def stored_and_blocks(tree):
    notion = tree_notion(tree)
    return convert(notion, PAGE).markdown, audit.notion_code_blocks(notion, PAGE)


MERMAID = "graph TD\n  A-->B"


def test_top_level_mermaid_is_marked_and_other_languages_are_untouched():
    tree = {PAGE: [block(2, "paragraph", "intro"), code(3, MERMAID, "mermaid"), code(4, "print(1)", "python")]}
    body, blocks = stored_and_blocks(tree)
    result = audit.audit_note(body, blocks)
    assert result["status"] == "ok"
    assert [(c["line"], c["before"], c["after"]) for c in result["changes"]] == [(3, "```", "```mermaid")]
    assert result["new_body"] == body.replace("```\ngraph", "```mermaid\ngraph", 1)
    assert result["new_body"].count("```mermaid") == 1


@pytest.mark.parametrize("wrapper", ["toggle", "bulleted_list_item", "quote", "callout", "column"])
def test_nested_mermaid_inside_containers_matches_convert_output(wrapper):
    tree = {PAGE: [block(10, wrapper, "w", children=True)], "00000000-0000-4000-8000-000000000010": [
        code(21, "a\n\n    indented\nb", "plain text"), code(22, MERMAID, "mermaid")]}
    body, blocks = stored_and_blocks(tree)
    result = audit.audit_note(body, blocks)
    assert result["status"] == "ok", (wrapper, result)
    assert len(result["changes"]) == 1 and result["changes"][0]["block_index"] == 1
    # Only the opening fence line changed.
    old, new = body.split("\n"), result["new_body"].split("\n")
    assert [i for i, (a, b) in enumerate(zip(old, new)) if a != b] == [result["changes"][0]["line"] - 1]
    assert new[result["changes"][0]["line"] - 1].endswith("```mermaid")


def test_deeply_nested_toggle_in_list():
    ids = {k: f"00000000-0000-4000-8000-{k:012d}" for k in (10, 11)}
    tree = {PAGE: [block(10, "toggle", "t", children=True)],
            ids[10]: [block(11, "bulleted_list_item", "b", children=True)],
            ids[11]: [code(12, MERMAID, "mermaid")]}
    body, blocks = stored_and_blocks(tree)
    result = audit.audit_note(body, blocks)
    assert result["status"] == "ok" and len(result["changes"]) == 1


def test_fence_longer_than_three_when_code_contains_backticks():
    text = "graph TD\n  A[\"```\"]-->B"
    tree = {PAGE: [code(2, text, "mermaid")]}
    body, blocks = stored_and_blocks(tree)
    assert body.startswith("````\n")
    result = audit.audit_note(body, blocks)
    assert result["status"] == "ok"
    assert result["new_body"].startswith("````mermaid\n")


def test_edited_stored_text_is_excluded_not_changed():
    tree = {PAGE: [code(2, MERMAID, "mermaid")]}
    body, blocks = stored_and_blocks(tree)
    result = audit.audit_note(body.replace("A-->B", "A-->C"), blocks)
    assert result["status"] == "content_mismatch" and result["changes"] == [] and result["new_body"] is None


def test_count_mismatch_is_excluded():
    tree = {PAGE: [code(2, MERMAID, "mermaid"), code(3, "x", "python")]}
    body, blocks = stored_and_blocks(tree)
    only_first = body.split("\n\n```")[0]
    assert audit.audit_note(only_first, blocks)["status"] == "count_mismatch"


def test_existing_other_language_conflicts_and_already_marked_is_idempotent():
    tree = {PAGE: [code(2, MERMAID, "mermaid")]}
    body, blocks = stored_and_blocks(tree)
    conflict = audit.audit_note(body.replace("```\n", "```python\n", 1), blocks)
    assert conflict["status"] == "info_conflict" and conflict["new_body"] is None
    first = audit.audit_note(body, blocks)["new_body"]
    again = audit.audit_note(first, blocks)
    assert again["status"] == "already_marked" and again["already_marked"] == 1 and again["new_body"] is None


def test_unterminated_fence_is_a_parse_error():
    result = audit.audit_note("```\ngraph", [{"id": "x", "language": "mermaid", "text": "graph"}])
    assert result["status"] == "parse_error"


def test_notes_without_mermaid_report_nothing():
    tree = {PAGE: [code(2, "x", "python")]}
    body, blocks = stored_and_blocks(tree)
    assert audit.audit_note(body, blocks)["status"] == "no_mermaid"


def test_dollar_quoting_survives_hostile_text_and_sql_is_guarded():
    hostile = 'graph TD\n  A["$mfa$ $mfa_x$ $$ $mfa_do0123456789$"]-->B'
    body = "```\n" + hostile + "\n```"
    items = [{"note_id": 7, "original": body, "updated": body.replace("```\n", "```mermaid\n", 1)}]
    sql = audit.guarded_updates(items, "original", "updated", "t")
    assert sql.startswith("-- t") and "begin;" in sql and sql.rstrip().endswith("commit;")
    assert "where id = 7 and body_markdown = " in sql and "raise exception" in sql
    tags = {t for t in re.findall(r"\$mfa_(?:do)?[0-9a-f]{10}\$", sql) if t not in hostile}
    assert len(tags) == 3  # new body, old body, and the outer DO delimiter
    for tag in tags:
        assert tag not in hostile
    # The statement must have exactly one DO block: no hostile text may open or close it.
    outer = re.search(r"^do (\$mfa_do[0-9a-f]{10}\$) begin", sql, re.M)[1]
    assert sql.count(outer) == 2


def make_source(rows):
    def handler(request):
        assert request.method == "GET"
        params = request.url.params
        offset, limit = int(params["offset"]), int(params["limit"])
        return httpx.Response(200, json=rows[offset:offset + limit])
    return audit.ReadOnlyNotes(httpx.Client(transport=httpx.MockTransport(handler)), "https://example.supabase.co", "sb_secret_x")


def test_audit_end_to_end_and_package(tmp_path):
    ids = {"a": PAGE, "b": "00000000-0000-4000-8000-0000000000b1", "c": "00000000-0000-4000-8000-0000000000c1",
           "d": "00000000-0000-4000-8000-0000000000d1"}
    trees = {
        "a": {ids["a"]: [code(2, MERMAID, "mermaid"), code(3, "x = 1", "python")]},
        "b": {ids["b"]: [code(2, "only python", "python")]},
        "c": {ids["c"]: [code(2, MERMAID, "mermaid")]},
        "d": {ids["d"]: [code(2, MERMAID, "mermaid")]},
    }
    bodies = {k: convert(tree_notion(t), ids[k]).markdown for k, t in trees.items()}
    bodies["c"] = bodies["c"].replace("A-->B", "A-->Z")  # edited after import
    rows = [{"id": n, "notion_page_id": ids[k], "revision": 1, "updated_at": "2026-11-01T00:00:00Z",
             "body_markdown": bodies[k]} for n, k in enumerate("abcd", start=1)]
    rows.append({"id": 9, "notion_page_id": ids["a"], "revision": 1, "updated_at": "x", "body_markdown": "no fences"})
    all_trees = {}
    for t in trees.values():
        all_trees.update(t)
    notion = tree_notion(all_trees)
    notion.children.side_effect = lambda block_id: all_trees[block_id] if block_id != ids["d"] else (_ for _ in ()).throw(
        ImportFailure("notion_http"))
    counts, report, changed = audit.audit(make_source(rows), notion)
    assert counts["notes_scanned"] == 5
    assert counts["notes_to_change"] == 1 and counts["blocks_to_change"] == 1
    assert counts["excluded"] == {"content_mismatch": 1, "count_mismatch": 1}  # note 9 lost its code blocks
    assert counts["notion_unreadable"] == 1
    assert [c["note_id"] for c in changed] == [1]

    audit.write_package(tmp_path, counts, report, changed)
    assert (tmp_path / "backup" / "note-1.original.md").read_text(encoding="utf-8") == bodies["a"]
    assert "```mermaid" in (tmp_path / "apply.sql").read_text(encoding="utf-8")
    restore = (tmp_path / "restore.sql").read_text(encoding="utf-8")
    assert "where id = 1" in restore
    saved = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert "graph TD" not in json.dumps(saved)  # report carries positions, never note text


def test_package_is_refused_inside_any_git_checkout_or_worktree(tmp_path):
    (tmp_path / "checkout").mkdir()
    (tmp_path / "checkout" / ".git").mkdir()  # main checkout
    (tmp_path / "worktree").mkdir()
    (tmp_path / "worktree" / ".git").write_text("gitdir: elsewhere")  # worktree: .git is a file
    for root in ("checkout", "worktree"):
        with pytest.raises(ImportFailure, match="out_dir_in_repo"):
            audit.write_package(tmp_path / root / "sub" / "audit-out", {}, [], [])
        assert not (tmp_path / root / "sub").exists()


def test_package_is_refused_in_a_non_empty_folder(tmp_path):
    (tmp_path / "backup").mkdir()
    (tmp_path / "backup" / "note-1.original.md").write_text("stale")
    with pytest.raises(ImportFailure, match="out_dir_not_empty"):
        audit.write_package(tmp_path, {}, [], [])


def test_source_url_must_be_plain_https():
    for bad in ("http://x.supabase.co", "https://u:p@x.supabase.co", "https://x.supabase.co/rest?a=1"):
        with pytest.raises(ImportFailure):
            audit.ReadOnlyNotes(Mock(), bad, "k")


@pytest.fixture
def restore_logging():
    yield
    logging.disable(logging.NOTSET)  # main() silences logging process-wide; do not leak into other tests


def test_main_prints_counts_only_and_fails_closed(monkeypatch, capsys, tmp_path, restore_logging):
    for name in ("MERMAID_AUDIT_SUPABASE_URL", "MERMAID_AUDIT_SUPABASE_SECRET_KEY", "NOTION_IMPORT_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    assert audit.main(["--out-dir", str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().out) == {"fatal_error": "KeyError"}


def test_main_exits_nonzero_when_notion_pages_are_unreadable(monkeypatch, capsys, tmp_path, restore_logging):
    row = {"id": 1, "notion_page_id": PAGE, "revision": 1, "updated_at": "x",
           "body_markdown": "```\ngraph\n```"}
    notion = Mock()
    notion.children.side_effect = ImportFailure("notion_http")
    monkeypatch.setattr(audit, "NotionReader", lambda http, token: notion)
    source = make_source([row])  # build before patching: make_source uses the real ReadOnlyNotes
    monkeypatch.setattr(audit, "ReadOnlyNotes", lambda http, url, key: source)
    for name, value in (("MERMAID_AUDIT_SUPABASE_URL", "u"), ("MERMAID_AUDIT_SUPABASE_SECRET_KEY", "k"),
                        ("NOTION_IMPORT_TOKEN", "t")):
        monkeypatch.setenv(name, value)
    assert audit.main(["--out-dir", str(tmp_path / "out")]) == 1
    output = capsys.readouterr().out
    assert '"notion_unreadable": 1' in output and '"fatal_error": "notion_unreadable"' in output


def test_main_checks_out_dir_before_any_network_call(monkeypatch, capsys, tmp_path, restore_logging):
    (tmp_path / ".git").mkdir()
    called = Mock()
    monkeypatch.setattr(audit, "ReadOnlyNotes", called)
    assert audit.main(["--out-dir", str(tmp_path / "out")]) == 1
    assert '"fatal_error": "out_dir_in_repo"' in capsys.readouterr().out
    called.assert_not_called()


def test_note_that_would_exceed_the_body_limit_is_excluded():
    tree = {PAGE: [code(2, MERMAID, "mermaid")]}
    body, blocks = stored_and_blocks(tree)
    padded = body + "\n\n" + "x" * (audit.BODY_LIMIT - len(body) - 2 - 3)  # 3 chars short of the limit after +7
    result = audit.audit_note(padded, blocks)
    assert result["status"] == "length_limit" and result["new_body"] is None and result["changes"] == []


def test_info_conflict_report_never_echoes_stored_text():
    tree = {PAGE: [code(2, MERMAID, "mermaid")]}
    body, blocks = stored_and_blocks(tree)
    result = audit.audit_note(body.replace("```\n", "```secret-note-text\n", 1), blocks)
    assert result["status"] == "info_conflict"
    assert "secret-note-text" not in json.dumps(result["detail"]) and result["detail"]["stored_info_length"] == 16


def run_audit(body, tree):
    row = {"id": 1, "notion_page_id": PAGE, "revision": 1, "updated_at": "x", "body_markdown": body}
    notion = tree_notion(tree)
    return audit.audit(make_source([row]), notion), notion


def test_stored_note_with_other_language_is_reported_not_skipped():
    # Notion says mermaid, but the stored only code block already carries `python`.
    tree = {PAGE: [code(2, MERMAID, "mermaid")]}
    (counts, report, changed), notion = run_audit("```python\n" + MERMAID + "\n```", tree)
    assert notion.children.called
    assert counts["excluded"] == {"info_conflict": 1} and counts["notes_to_change"] == 0 and changed == []
    assert [r["status"] for r in report] == ["info_conflict"]


def test_stored_note_that_lost_its_code_blocks_is_reported_not_skipped():
    tree = {PAGE: [code(2, MERMAID, "mermaid")]}
    (counts, report, changed), notion = run_audit("just text, no fences", tree)
    assert counts["excluded"] == {"count_mismatch": 1} and changed == []
    assert [r["status"] for r in report] == ["count_mismatch"]


def test_note_whose_fences_are_all_marked_needs_no_notion_call():
    tree = {PAGE: [code(2, MERMAID, "mermaid")]}
    (counts, report, changed), notion = run_audit("```mermaid\n" + MERMAID + "\n```", tree)
    assert not notion.children.called and report == [] and changed == []
