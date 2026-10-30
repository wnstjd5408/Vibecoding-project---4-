import subprocess
from urllib.parse import quote, urlunsplit

import pytest

from scripts import probe_backup
from scripts.diagnose_backup import classify_log


@pytest.fixture
def private_url(monkeypatch):
    monkeypatch.setattr(probe_backup, "probe_tls", lambda env: None)
    sentinel = "TEST_ONLY_" + "DO_NOT_PRINT"
    url = urlunsplit(("postgresql", f"test-user:{quote(sentinel)}@example.invalid:5432", "/postgres", "sslmode=require", ""))
    monkeypatch.setenv("SUPABASE_DB_URL", url)
    return url, sentinel


def test_success_uses_environment_and_discards_results(private_url, monkeypatch, capsys):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        assert private_url[0] not in repr(args)
        assert private_url[1] not in repr(args)
        assert kwargs["stdout"] == subprocess.DEVNULL
        assert kwargs["stderr"] == subprocess.PIPE
        assert kwargs["timeout"] == 30
        return subprocess.CompletedProcess(args, 0, stderr=b"")

    monkeypatch.setattr(subprocess, "run", run)
    assert probe_backup.main() == 0
    assert len(calls) == 3
    assert calls[1][1]["env"]["PGPASSWORD"] == private_url[1]
    assert calls[1][1]["env"]["PGSSLMODE"] == "require"
    assert "PGOPTIONS" not in calls[1][0]
    assert "--command=BEGIN READ ONLY; SELECT 1; ROLLBACK;" in calls[1][0]
    assert "--no-role-passwords" in calls[2][0]
    assert capsys.readouterr().out == (
        "Backup probe CONTAINER_TOOL: OK\nBackup probe CONNECTION: OK\n"
        "Backup probe ROLES: OK\nBackup diagnostic: CLI_DUMP_PATH_FAILED\n"
    )


@pytest.mark.parametrize("failed_stage,code,error", [
    (0, "CONTAINER_START_FAILED", "OCI runtime error"),
    (1, "DB_AUTH_FAILED", "FATAL: 28P01: untrusted message"),
    (2, "DB_PERMISSION_DENIED", "permission denied"),
])
def test_failure_stops_and_never_prints_private_error(private_url, monkeypatch, capsys, failed_stage, code, error):
    calls = []

    def run(args, **kwargs):
        index = len(calls)
        calls.append(args)
        stderr = f"{private_url[0]}\n{error}\n::error::INJECTED\x1b[31m".encode()
        return subprocess.CompletedProcess(args, int(index == failed_stage), stderr=stderr)

    monkeypatch.setattr(subprocess, "run", run)
    assert probe_backup.main() == 1
    assert len(calls) == failed_stage + 1
    captured = capsys.readouterr()
    assert captured.out.endswith(f": {code}\n")
    assert private_url[1] not in captured.out + captured.err
    assert "INJECTED" not in captured.out + captured.err


def test_timeout_removes_only_its_container(monkeypatch, capsys):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(args, 30, stderr=b"PRIVATE")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", run)
    assert not probe_backup.probe("CONNECTION", ["psql"], {})
    name = calls[0][calls[0].index("--name") + 1]
    assert calls[1] == ["docker", "rm", "--force", name]
    assert capsys.readouterr().out == "Backup probe CONNECTION: PROBE_TIMEOUT\n"


def test_unknown_options_are_not_silently_ignored(private_url):
    with pytest.raises(ValueError):
        probe_backup.connection_env(private_url[0] + "&service=unexpected")


@pytest.mark.parametrize("message,code", [
    ("FATAL: 53300: private text", "DB_CONNECTION_LIMIT"),
    ("FATAL: 3D000: private text", "DB_NAME_INVALID"),
    ("pg_dumpall: unexpected private text", "PG_DUMPALL_FAILED"),
    ("FATAL: ABCDE: secret text", "DUMP_FAILURE_UNCLASSIFIED"),
])
def test_known_sqlstates_and_tool_failures(message, code):
    assert classify_log(message) == code
