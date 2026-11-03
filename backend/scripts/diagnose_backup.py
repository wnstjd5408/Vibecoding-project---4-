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
    "28P01": "DB_AUTH_FAILED", "28000": "DB_AUTH_POLICY_FAILED",
    "42501": "DB_PERMISSION_DENIED", "3D000": "DB_NAME_INVALID",
    "53300": "DB_CONNECTION_LIMIT", "57P03": "DB_POOLER_UNAVAILABLE",
}

# Supavisor sends these fixed public identifiers in its PostgreSQL error message.
# Match them before generic password text: an auth_query error is pooler-side,
# not proof that the user's supplied password is wrong.
# https://github.com/supabase/supavisor/tree/main/lib/supavisor/errors
POOLER_CODES = {
    "EAUTHQUERY": "DB_POOLER_AUTH_LOOKUP_FAILED",
    "EAUTHSECRETS": "DB_POOLER_AUTH_LOOKUP_FAILED",
    "ECIRCUITBREAKER": "DB_POOLER_CIRCUIT_OPEN",
    "EWRONGPASSWORD": "DB_AUTH_FAILED",
    "ESSLREQUIRED": "DB_SSL_REQUIRED",
    "ESSLHANDSHAKE": "DB_TLS_NEGOTIATION_FAILED",
    "EADDRNOTALLOWED": "DB_NETWORK_RESTRICTED",
    "EBANNED": "DB_POOLER_TENANT_BANNED",
    "EMAXCONN": "DB_CONNECTION_LIMIT",
    "EMAXCONNSESSION": "DB_CONNECTION_LIMIT",
    "ESTARTUPMESSAGE": "DB_STARTUP_OPTIONS_REJECTED",
}

CONNECTION_RULES = (
    ("DB_POOLER_AUTH_BLOCKED", ("too many authentication failures",)),
    ("DB_POOLER_AUTH_LOOKUP_FAILED", (
        "authentication query failed", "auth_query connection failed",
        "failed to retrieve database credentials", "authentication query returned wrong format",
        "auth_query secret check timed out", "no auth_query configured",
        "unsupported or invalid secret format", "failed to parse scram secret",
        "failed to retrieve authentication secrets",
    )),
    ("DB_POOLER_UPSTREAM_UNAVAILABLE", (
        "too many failed attempts to connect to the database",
        "unable to establish connection to upstream database", "connection to database not available",
    )),
    ("DB_POOLER_CIRCUIT_OPEN", ("circuit breaker open",)),
    ("DB_NETWORK_RESTRICTED", ("address not in tenant allow_list", "ip address is banned")),
    ("DB_TLS_CERTIFICATE_FAILED", (
        "does not match host name", "unable to get local issuer certificate",
        "self-signed certificate", "certificate has expired",
    )),
    ("DB_TLS_NEGOTIATION_FAILED", ("ssl handshake failed", "received invalid response to ssl negotiation")),
    ("DB_STARTUP_OPTIONS_REJECTED", ("unsupported startup parameter", "unrecognized configuration parameter")),
    ("DB_AUTH_PROTOCOL_FAILED", (
        "scram authentication requires", "channel binding required",
        "server did not offer scram-sha-256-plus", "authentication method 10 not supported",
        "server signature is incorrect", "malformed scram message",
    )),
)


def classify_log(content: str) -> str:
    # Connection options/user input are not evidence of an error. In particular,
    # a valid sslmode=require URL must not turn unrelated failures into TLS errors.
    content = re.sub(r"postgres(?:ql)?://\S+", "", content, flags=re.IGNORECASE)
    lowered = content.lower()
    for code, markers in CONNECTION_RULES:
        if any(marker in lowered for marker in markers):
            return code
    for provider_code in re.findall(r"\((E[A-Z]+)\)", content):
        if provider_code in POOLER_CODES:
            return POOLER_CODES[provider_code]
    for state in re.findall(r"(?:ERROR|FATAL):\s+([A-Z0-9]{5}):", content):
        if state in SQLSTATES:
            return SQLSTATES[state]
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
