import pytest

from scripts.diagnose_backup import RULES, check_url, main


@pytest.mark.parametrize("url,code", [
    ("", "DB_URL_MISSING"),
    (" postgres://user:secret@host/db", "DB_URL_WHITESPACE"),
    ("https://example.test", "DB_URL_INVALID"),
    ("postgres://user@aws-0.pooler.supabase.com:5432/postgres", "DB_PASSWORD_MISSING"),
    ("postgres://user:[YOUR-PASSWORD]@aws-0.pooler.supabase.com:5432/postgres", "DB_PASSWORD_PLACEHOLDER"),
    ("postgres://user:p@ss@aws-0.pooler.supabase.com:5432/postgres", "DB_URL_ENCODING_INVALID"),
    ("postgres://user:p%zz@aws-0.pooler.supabase.com:5432/postgres", "DB_URL_ENCODING_INVALID"),
    ("postgres://user:secret@aws-0.pooler.supabase.com:6543/postgres", "DB_SESSION_POOLER_REQUIRED"),
    ("postgres://user:secret@db.example.test:5432/postgres", "DB_SESSION_POOLER_REQUIRED"),
    ("postgres://user:secret@aws-0.pooler.supabase.com:5432/wrong", "DB_NAME_UNEXPECTED"),
    ("postgresql://postgres.example:p%40ss@aws-0.pooler.supabase.com:5432/postgres", "DB_URL_FORMAT_OK"),
])
def test_preflight(url, code, monkeypatch, capsys):
    monkeypatch.setenv("SUPABASE_DB_URL", url)
    assert main([]) == (0 if code == "DB_URL_FORMAT_OK" else 1)
    captured = capsys.readouterr()
    assert captured.out == f"Backup diagnostic: {code}\n"
    assert captured.err == ""


@pytest.mark.parametrize("code,markers", RULES)
def test_log_outputs_only_fixed_code(tmp_path, capsys, code, markers):
    log = tmp_path / "private.log"
    for marker in markers:
        log.write_text(f"postgres://private-user:private-password@private-host/db\n{marker}\n"
                       "sb_secret_PRIVATE\n::warning::INJECTED\x1b[31m", encoding="utf-8")
        assert main(["--log", str(log)]) == 0
        captured = capsys.readouterr()
        assert captured.out == f"Backup diagnostic: {code}\n"
        assert captured.err == ""


def test_unknown_error_and_missing_log_never_echo_input(tmp_path, capsys):
    log = tmp_path / "private-password.log"
    assert main(["--log", str(log)]) == 0
    assert capsys.readouterr().out == "Backup diagnostic: DIAGNOSTIC_LOG_UNREADABLE\n"
    log.write_bytes(b"private-password\xff\n::error::untrusted")
    assert main(["--log", str(log)]) == 0
    assert capsys.readouterr().out == "Backup diagnostic: DUMP_FAILURE_UNCLASSIFIED\n"
