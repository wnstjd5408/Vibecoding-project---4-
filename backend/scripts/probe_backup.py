"""Read-only probes after a dump failure. Output fixed codes, never subprocess output."""

import os
import subprocess
import socket
import ssl
import struct
from pathlib import Path
from uuid import uuid4
from urllib.parse import parse_qsl, unquote, urlsplit

try:
    from .diagnose_backup import classify_log
except ImportError:
    from diagnose_backup import classify_log


IMAGE = "public.ecr.aws/supabase/postgres:17.11.0.004"
SUPABASE_CA = Path(__file__).resolve().parent / "certs" / "supabase-prod-ca-2021.crt"
QUERY_ENV = {
    "sslmode": "PGSSLMODE",
    "channel_binding": "PGCHANNELBINDING",
}


def tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    # The managed pooler uses Supabase's CA, which is not a public OS trust root.
    # Keep certificate verification and hostname validation enabled.
    context.load_verify_locations(cafile=str(SUPABASE_CA))
    return context


def connection_env(value: str) -> dict[str, str]:
    url = urlsplit(value)
    options = dict(parse_qsl(url.query, strict_parsing=True))
    # Do not silently test a different connection when unsupported options are used.
    if set(options) - QUERY_ENV.keys():
        raise ValueError("unsupported connection options")
    if not url.hostname or not url.username or not url.password:
        raise ValueError("incomplete connection")
    return {
        "PGHOST": url.hostname,
        "PGPORT": str(url.port or 5432),
        "PGUSER": unquote(url.username),
        "PGPASSWORD": unquote(url.password),
        "PGDATABASE": unquote(url.path.lstrip("/")),
        "PGCONNECT_TIMEOUT": "10",
        **{QUERY_ENV[key]: value for key, value in options.items()},
    }


def probe_tls(pg_env: dict[str, str]) -> None:
    """PostgreSQL SSLRequest and verified TLS only; never send user/password."""
    try:
        with socket.create_connection((pg_env["PGHOST"], int(pg_env["PGPORT"])), timeout=10) as conn:
            conn.sendall(struct.pack("!II", 8, 80877103))
            response = conn.recv(1)
            if response == b"S":
                with tls_context().wrap_socket(conn, server_hostname=pg_env["PGHOST"]):
                    code = "OK"
            elif response == b"N":
                code = "TLS_NOT_SUPPORTED"
            else:
                code = "TLS_UNEXPECTED_RESPONSE"
    except ssl.SSLCertVerificationError:
        code = "TLS_CERTIFICATE_FAILED"
    except ssl.SSLError:
        code = "TLS_HANDSHAKE_FAILED"
    except socket.gaierror:
        code = "NETWORK_DNS_FAILED"
    except TimeoutError:
        code = "NETWORK_TIMEOUT"
    except OSError:
        code = "NETWORK_CONNECT_FAILED"
    print(f"Backup probe TLS: {code}")


def probe(stage: str, command: list[str], pg_env: dict[str, str]) -> bool:
    container = f"backup-probe-{uuid4().hex}"
    args = ["docker", "run", "--rm", "--pull=never", "--network=host", "--name", container]
    for key in pg_env:
        # Values, including passwords, are inherited only through the environment.
        args.extend(["--env", key])
    args.extend(["--entrypoint", command[0], IMAGE, *command[1:]])
    try:
        result = subprocess.run(
            args, env={**os.environ, **pg_env}, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, timeout=30, check=False,
        )
    except subprocess.TimeoutExpired:
        code = "PROBE_TIMEOUT"
        # Killing the docker client alone can leave its container running.
        try:
            subprocess.run(
                ["docker", "rm", "--force", container],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=10, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    except OSError:
        code = "PROBE_PROCESS_UNAVAILABLE"
    else:
        code = "OK" if result.returncode == 0 else classify_log(
            result.stderr.decode("utf-8", errors="replace")
        )
    print(f"Backup probe {stage}: {code}")
    return code == "OK"


def main() -> int:
    if not probe("CONTAINER_TOOL", ["pg_dumpall", "--version"], {}):
        return 1
    try:
        pg_env = connection_env(os.environ.get("SUPABASE_DB_URL", ""))
    except ValueError:
        print("Backup probe CONNECTION: PROBE_URL_UNSUPPORTED")
        return 1
    # This uses runner roots plus Supabase's CA; psql uses the image's libpq policy.
    # Always run psql too; a TLS probe alone cannot diagnose the password or pooler.
    probe_tls(pg_env)
    if not probe("CONNECTION", [
        "psql", "-X", "--no-password", "--set=ON_ERROR_STOP=1",
        "--set=VERBOSITY=verbose", "--command=BEGIN READ ONLY; SELECT 1; ROLLBACK;",
    ], pg_env):
        return 1
    if not probe("ROLES", [
        "pg_dumpall", "--no-password", "--roles-only", "--role=postgres",
        "--quote-all-identifiers", "--no-role-passwords", "--no-comments",
    ], pg_env):
        return 1
    print("Backup diagnostic: CLI_DUMP_PATH_FAILED")
    return 0


if __name__ == "__main__":
    try:
        result = main()
    except Exception:
        # Exception strings/tracebacks may contain argv, URLs, stderr or passwords.
        print("Backup diagnostic: PROBE_INTERNAL_ERROR")
        result = 1
    raise SystemExit(result)
