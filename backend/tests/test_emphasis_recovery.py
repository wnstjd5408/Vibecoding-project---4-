import copy
import json
import sys
from types import SimpleNamespace

import httpx
import pytest

from scripts.emphasis_recovery import digest, main, read_notes, reviewed_changes, survey, sql_package


def plan(body="😀 **한글용어 **(Example)"):
    return survey([{"id": 1, "revision": 3, "body_markdown": body}])


def accept(p):
    return [c["candidate_id"] for n in p["notes"] for c in n["candidates"] if c["eligible"]]


def test_review_required_and_only_selected_locations_change():
    p = plan("**한글 **\n\n*기울임 *\n\n```mermaid\ngraph LR; A-->B\n```")
    assert reviewed_changes(p, []) == []
    ids = accept(p)
    assert len(ids) == 2
    change = reviewed_changes(p, ids[:1])[0]
    assert change["after"] == "**한글** \n\n*기울임 *\n\n```mermaid\ngraph LR; A-->B\n```"


@pytest.mark.parametrize("body", ["**정상**", "`**코드 **`", "```\n**코드 **\n```", "    **코드 **",
    "[**링크 **](https://example.test)", "![**그림 **](note-image:abc)", "\\**별표 **",
    "**A* **", "2 * 3", "**첫 ** **둘 **", "** **", "https://example.test/**경로 **"])
def test_protected_or_ambiguous_is_never_eligible(body):
    assert accept(plan(body)) == []


@pytest.mark.parametrize("body,expected", [("** 용어 **", " **용어** "), ("*용어\t*", "*용어*\t"), ("***한글😀 ***", "***한글😀*** ")])
def test_simple_approved_rules(body, expected):
    p = plan(body)
    assert reviewed_changes(p, accept(p))[0]["after"] == expected


def test_tamper_unknown_duplicate_and_drift():
    p = plan()
    bad = copy.deepcopy(p)
    bad["notes"][0]["candidates"][0]["after"] = "arbitrary"
    with pytest.raises(ValueError):
        reviewed_changes(bad, accept(p))
    with pytest.raises(ValueError):
        reviewed_changes(p, ["unknown"])
    with pytest.raises(ValueError):
        reviewed_changes(p, accept(p) * 2)
    changed = plan("Mermaid changed\n" + p["notes"][0]["body"])
    with pytest.raises(ValueError):
        reviewed_changes(changed, accept(p))


def test_keyset_handles_short_server_pages_and_only_get():
    calls = []
    def handle(request):
        assert request.method == "GET"
        last = int(request.url.params["id"].split(".")[1])
        calls.append(last)
        return httpx.Response(200, json=[] if last == 3 else [{"id": last + 1, "revision": 1, "body_markdown": "**용어 **"}])
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        source = SimpleNamespace(http=client, url="https://example.test", key="synthetic")
        assert len(survey(read_notes(source))["notes"]) == 3
    assert calls == [0, 1, 2, 3]


def test_sql_body_cannot_escape_delimiters():
    p = plan("$recovery$ ' \\ \n**용어 **")
    changes = reviewed_changes(p, accept(p))
    sql = sql_package(changes, digest("synthetic"))
    assert "perform public.ai_invalidate_explanations" in sql
    assert "for update" in sql
    assert "already_applied" in sql
    assert "$recovery$ '" not in sql
    assert "sha256" in sql


def test_cli_requires_exact_review_and_keeps_artifacts_restricted(tmp_path, monkeypatch, capsys):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps([{"id": 1, "revision": 1, "body_markdown": "**용어 **"}]), encoding="utf-8")
    dry = tmp_path / "survey"
    monkeypatch.setattr(sys, "argv", ["tool", "--snapshot", str(snapshot), "--out-dir", str(dry)])
    main()
    counts = json.loads(capsys.readouterr().out)
    assert counts["notes"] == counts["reviewable"] == 1
    assert not (dry / "apply.sql").exists()
    p = json.loads((dry / "plan.json").read_text(encoding="utf-8"))
    approved = tmp_path / "approved.json"
    approved.write_text(json.dumps(accept(p)), encoding="utf-8")
    output = tmp_path / "package"
    argv = ["tool", "--plan", str(dry / "plan.json"), "--approved", str(approved),
            "--approve-plan-sha256", "bad", "--out-dir", str(output)]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(ValueError, match="approval_hash"):
        main()
    assert not output.exists()
    argv[6] = counts["plan_sha256"]
    main()
    assert json.loads(capsys.readouterr().out)["executed"] is False
    assert {f.name for f in output.iterdir()} == {"backup.json", "apply.sql", "rollback.sql"}
    assert json.loads((output / "backup.json").read_text(encoding="utf-8"))[0]["before"] == "**용어 **"
