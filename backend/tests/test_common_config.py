import pytest
from fastapi import FastAPI

from app.common import install_common_layer
from app.config import ConfigError, allowed_origins


def test_default_is_the_local_dev_origin(monkeypatch):
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)

    assert allowed_origins() == frozenset({"http://localhost:5173"})


def test_values_are_split_trimmed_and_normalized(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", " HTTPS://App.Example.com/ , http://localhost:5173 ")

    assert allowed_origins() == frozenset({"https://app.example.com", "http://localhost:5173"})


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "https://*.example.com",
        "ftp://app.example.com",
        "app.example.com",
        "https://app.example.com/path",
        "https://app.example.com?x=1",
        "https://app.example.com, *",
        "null",
    ],
)
def test_invalid_entries_are_rejected(monkeypatch, value):
    monkeypatch.setenv("ALLOWED_ORIGINS", value)

    with pytest.raises(ConfigError) as info:
        allowed_origins()

    assert value not in str(info.value)


def test_ports_and_ipv6_hosts_are_accepted(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://127.0.0.1:3000,http://[::1]:5173")

    assert allowed_origins() == frozenset({"http://127.0.0.1:3000", "http://[::1]:5173"})


def test_production_requires_an_explicit_value(monkeypatch):
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    monkeypatch.setenv("VERCEL_ENV", "production")

    with pytest.raises(ConfigError):
        allowed_origins()


def test_production_with_a_value_is_fine(monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://app.example.com")

    assert allowed_origins() == frozenset({"https://app.example.com"})


def test_preview_deployments_may_use_the_default(monkeypatch):
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    monkeypatch.setenv("VERCEL_ENV", "preview")

    assert allowed_origins() == frozenset({"http://localhost:5173"})


def test_app_does_not_start_with_a_bad_value(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")

    with pytest.raises(ConfigError):
        install_common_layer(FastAPI())
