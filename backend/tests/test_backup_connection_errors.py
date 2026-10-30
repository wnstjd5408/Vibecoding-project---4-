import socket
import ssl
import struct
from unittest.mock import MagicMock

import pytest

from scripts.diagnose_backup import classify_log
from scripts.probe_backup import probe_tls


# Representative server/client errors, not just a copy of classification rules.
@pytest.mark.parametrize("error,code", [
    ('FATAL: password authentication failed for user "redacted"', "DB_AUTH_FAILED"),
    ('FATAL: (EAUTHQUERY) authentication query failed: password authentication failed', "DB_POOLER_AUTH_LOOKUP_FAILED"),
    ('FATAL: Circuit breaker open: Failed to retrieve database credentials', "DB_POOLER_AUTH_LOOKUP_FAILED"),
    ('FATAL: (ECIRCUITBREAKER) too many authentication failures, new connections are temporarily blocked', "DB_POOLER_AUTH_BLOCKED"),
    ('FATAL: (ECIRCUITBREAKER) too many failed attempts to connect to the database, new connections are temporarily blocked', "DB_POOLER_UPSTREAM_UNAVAILABLE"),
    ('FATAL: (ESSLHANDSHAKE) SSL handshake failed: redacted', "DB_TLS_NEGOTIATION_FAILED"),
    ('FATAL: (EADDRNOTALLOWED) address not in tenant allow_list: redacted', "DB_NETWORK_RESTRICTED"),
    ('FATAL: (EBANNED) tenant is banned: redacted', "DB_POOLER_TENANT_BANNED"),
    ('FATAL: (EMAXCONNSESSION) max clients reached in session mode', "DB_CONNECTION_LIMIT"),
    ('server certificate for "redacted" does not match host name "redacted"', "DB_TLS_CERTIFICATE_FAILED"),
    ('FATAL: unsupported startup parameter: options', "DB_STARTUP_OPTIONS_REJECTED"),
    ('FATAL: 28000: redacted', "DB_AUTH_POLICY_FAILED"),
    ('psql: error: unknown future error', "PSQL_FAILED"),
])
def test_connection_classification(error, code):
    assert classify_log(error) == code


def test_tls_sends_only_ssl_request_and_checks_hostname(monkeypatch, capsys):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.recv.return_value = b"S"
    connect = MagicMock(return_value=conn)
    context = MagicMock()
    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(ssl, "create_default_context", lambda: context)
    probe_tls({"PGHOST": "example.invalid", "PGPORT": "5432", "PGPASSWORD": "PRIVATE_SENTINEL"})
    conn.sendall.assert_called_once_with(struct.pack("!II", 8, 80877103))
    context.wrap_socket.assert_called_once_with(conn, server_hostname="example.invalid")
    assert capsys.readouterr().out == "Backup probe TLS: OK\n"


@pytest.mark.parametrize("error,code", [
    (ssl.SSLCertVerificationError("PRIVATE_SENTINEL"), "TLS_CERTIFICATE_FAILED"),
    (ssl.SSLError("PRIVATE_SENTINEL"), "TLS_HANDSHAKE_FAILED"),
    (socket.gaierror("PRIVATE_SENTINEL"), "NETWORK_DNS_FAILED"),
    (TimeoutError("PRIVATE_SENTINEL"), "NETWORK_TIMEOUT"),
    (OSError("PRIVATE_SENTINEL"), "NETWORK_CONNECT_FAILED"),
])
def test_tls_errors_never_echo_details(monkeypatch, capsys, error, code):
    monkeypatch.setattr(socket, "create_connection", MagicMock(side_effect=error))
    probe_tls({"PGHOST": "example.invalid", "PGPORT": "5432"})
    captured = capsys.readouterr()
    assert captured.out == f"Backup probe TLS: {code}\n"
    assert captured.err == ""
