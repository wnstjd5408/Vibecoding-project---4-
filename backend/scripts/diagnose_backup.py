"""Print only fixed diagnostic codes; never print URLs, log excerpts or exceptions."""

import argparse
import os
import re
from pathlib import Path
from urllib.parse import urlsplit


def check_url(value: str) -> str:
    if not value:
        return "DB_URL_MISSING"
    if value != value.strip() or any(char in value for char in "\r\n\t"):
        return "DB_URL_WHITESPACE"
    if "YOUR-PASSWORD" in value or "YOUR_PASSWORD" in value:
        return "DB_PASSWORD_PLACEHOLDER"
    try:
        url = urlsplit(value)
        if url.scheme not in ("postgres", "postgresql") or not url.hostname:
            return "DB_URL_INVALID"
        if not url.username or not url.password:
            return "DB_PASSWORD_MISSING"
        if url.fragment or "@" in url.password or re.search(r"%(?![0-9a-fA-F]{2})", url.password):
            return "DB_URL_ENCODING_INVALID"
        if not url.hostname.endswith(".pooler.supabase.com") or url.port != 5432:
            return "DB_SESSION_POOLER_REQUIRED"
        if url.path != "/postgres":
            return "DB_NAME_UNEXPECTED"
    except ValueError:
        return "DB_URL_INVALID"
    return "DB_URL_FORMAT_OK"


RULES = (
    ("IMAGE_NETWORK_FAILED", ("failed to resolve reference", "tls handshake timeout", "net/http: request canceled")),
    ("DB_AUTH_FAILED", ("password authentication failed", "sasl authentication failed", "wrong password")),
    ("DB_USER_OR_PROJECT_INVALID", ("tenant or user not found", "role does not exist")),
    ("DB_PERMISSION_DENIED", ("permission denied", "must be superuser")),
    ("DB_DNS_FAILED", ("could not translate host name", "no such host", "name or service not known")),
    ("DB_CONNECTION_TIMEOUT", ("connection timed out", "i/o timeout", "timeout expired")),
    ("DB_CONNECTION_REFUSED", ("connection refused", "network is unreachable")),
    ("DB_TLS_FAILED", ("certificate verify failed", "ssl error", "tls handshake")),
    ("DB_VERSION_MISMATCH", ("server version mismatch",)),
    ("DOCKER_UNAVAILABLE", ("cannot connect to the docker daemon", "is the docker daemon running")),
    ("IMAGE_RATE_LIMITED", ("toomanyrequests", "too many requests", "pull rate limit")),
    ("IMAGE_MANIFEST_MISSING", ("manifest unknown", "no matching manifest")),
    ("IMAGE_ACCESS_DENIED", ("pull access denied", "unauthorized: authentication required")),
    ("DUMP_TOOL_MISSING", ("pg_dump: not found", "pg_dumpall: not found", "executable file not found")),
    ("DB_CONNECTION_CLOSED", ("server closed the connection", "unexpected eof", "connection reset by peer")),
    ("DB_SSL_REQUIRED", ("ssl connection is required", "no pg_hba.conf entry")),
    ("CLI_ARGUMENT_INVALID", ("unknown flag", "unknown command", "unrecognized arguments")),
    ("DB_URL_INVALID", ("invalid connection string", "invalid percent-encoded token", "failed to parse connection string")),
    ("DB_AUTH_MISSING", ("no password supplied",)),
    ("DB_CONNECTION_LIMIT", ("too many clients", "remaining connection slots", "max client connections", "maxclientsinsessionmode")),
    ("DB_POOLER_UNAVAILABLE", ("unable to check out a connection", "pool checkout timeout", "database is not accepting connections")),
    ("DB_TLS_NEGOTIATION_FAILED", ("server does not support ssl", "ssl connection has been closed unexpectedly", "root certificate file")),
    ("CONTAINER_START_FAILED", ("oci runtime", "failed to create task", "exec format error", "invalid reference format")),
    ("CLI_RUNTIME_FAILED", ("segmentation fault", "illegal instruction", "bun has crashed", "glibc_", "cannot find module")),
    ("SHELL_SCRIPT_FAILED", ("syntax error", "unbound variable", "sed: bad", "sed: -e expression")),
    ("CLI_CONFIG_INVALID", ("failed to parse config", "invalid config", "failed to decode config")),
    ("NPM_EXEC_FAILED", ("npm error", "npm err!",)),
)

SQLSTATES = {
    "28P01": "DB_AUTH_FAILED", "28000": "DB_AUTH_FAILED",
    "42501": "DB_PERMISSION_DENIED", "3D000": "DB_NAME_INVALID",
    "53300": "DB_CONNECTION_LIMIT", "57P03": "DB_POOLER_UNAVAILABLE",
}


def classify_log(content: str) -> str:
    # Connection options/user input are not evidence of an error. In particular,
    # a valid sslmode=require URL must not turn unrelated failures into TLS errors.
    content = re.sub(r"postgres(?:ql)?://\S+", "", content, flags=re.IGNORECASE)
    for state in re.findall(r"(?:ERROR|FATAL):\s+([A-Z0-9]{5}):", content):
        if state in SQLSTATES:
            return SQLSTATES[state]
    lowered = content.lower()
    for code, markers in RULES:
        if any(marker in lowered for marker in markers):
            return code
    for marker, code in (
        ("pg_dumpall:", "PG_DUMPALL_FAILED"),
        ("psql:", "PSQL_FAILED"),
        ("error response from daemon", "DOCKER_DAEMON_FAILED"),
        ("error running container", "CONTAINER_COMMAND_FAILED"),
    ):
        if marker in lowered:
            return code
    return "DUMP_FAILURE_UNCLASSIFIED"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path)
    args = parser.parse_args(argv)
    if args.log is None:
        code = check_url(os.environ.get("SUPABASE_DB_URL", ""))
        print(f"Backup diagnostic: {code}")
        return 0 if code == "DB_URL_FORMAT_OK" else 1
    try:
        code = classify_log(args.log.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        code = "DIAGNOSTIC_LOG_UNREADABLE"
    print(f"Backup diagnostic: {code}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
