"""Activation automation: token handling, watch events, hosting, Notification API."""

from __future__ import annotations

import json
from pathlib import Path

from app.cli import main
from app.privacy.ebay_activation import detect_hosting, probe_notification_api, prove_public_endpoint
from app.privacy.ebay_challenge import (
    read_verification_token,
    token_is_valid,
    write_endpoint_to_env,
    write_token_to_env,
)
from app.privacy.ebay_watch import record_watch_event, watch_log_path
from app.sold.ebay_owner_oauth import consent_status, start_consent


def test_write_token_does_not_include_token_value(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    result = write_token_to_env(env)
    dumped = json.dumps(result)
    token = read_verification_token(env)
    assert token_is_valid(token)
    assert token not in dumped
    assert "token_configured" in dumped
    assert result["token_length"] == len(token)
    text = env.read_text(encoding="utf-8")
    assert "EBAY_NOTIFICATION_VERIFICATION_TOKEN=" in text
    assert token in text


def test_show_token_prints_only_when_requested(tmp_path: Path, monkeypatch, capsys) -> None:
    env = tmp_path / ".env"
    write_token_to_env(env)
    token = read_verification_token(env)
    monkeypatch.chdir(tmp_path)
    rc = main(["ebay-notification-show-token"])
    out = capsys.readouterr()
    assert rc == 0
    assert out.out.strip() == token
    rc2 = main(["ebay-notification-token"])
    out2 = capsys.readouterr()
    assert rc2 == 0
    assert token not in out2.out
    assert "token_configured" in out2.out


def test_set_endpoint_appends_path(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    result = write_endpoint_to_env("https://arie.example.test", env)
    assert result["action"] == "written"
    assert result["endpoint_url"] == "https://arie.example.test/webhooks/ebay/account-deletion"
    exact = write_endpoint_to_env(
        "https://arie.example.test/webhooks/ebay/account-deletion", env
    )
    assert exact["endpoint_url"] == "https://arie.example.test/webhooks/ebay/account-deletion"
    rejected = write_endpoint_to_env("http://insecure.example/webhooks/ebay/account-deletion", env)
    assert rejected["action"] == "rejected"


def test_watch_event_log(tmp_path, monkeypatch) -> None:
    log = tmp_path / "events.jsonl"
    monkeypatch.setenv("EBAY_NOTIFICATION_WATCH_LOG", str(log))
    from app.privacy.ebay_watch import record_watch_event

    record_watch_event("EBAY_CHALLENGE_RECEIVED", endpoint_host="example.test")
    assert "EBAY_CHALLENGE_RECEIVED" in log.read_text(encoding="utf-8")


def test_hosting_detect_no_public_url() -> None:
    info = detect_hosting()
    assert info["ngrok_forbidden"] is True
    assert "dockerfile" in info["files"]
    assert info["files"]["dockerfile"] is True
    assert info["files"]["fly_toml"] is False


def test_public_proof_blocked_without_https(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("EBAY_NOTIFICATION_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("EBAY_NOTIFICATION_VERIFICATION_TOKEN", raising=False)
    proof = prove_public_endpoint()
    assert proof["public"] is False
    assert proof["secrets_included"] is False
    assert proof["blocked_reason"] in {
        "verification_token_not_configured",
        "no_public_https_endpoint",
    }


def test_notification_api_probe_without_credentials(monkeypatch) -> None:
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)
    from app.core.config import get_settings

    get_settings.cache_clear()
    import asyncio

    result = asyncio.run(probe_notification_api())
    assert result["attempted"] is True
    assert result["destination_created"] is False
    assert result["portal_only_bootstrap"] is True
    assert result["secrets_included"] is False
    dumped = json.dumps(result)
    assert "client_secret" not in dumped.lower() or result.get("oauth_error")


def test_owner_oauth_requires_runame() -> None:
    status = consent_status()
    assert status["refresh_token_configured"] is False
    started = start_consent()
    assert started["ok"] is False
    assert started["url"] is None


def test_gitignore_excludes_env() -> None:
    text = Path(".gitignore").read_text(encoding="utf-8")
    assert ".env" in text.splitlines()
    assert "artifacts/runtime/" in text


def test_record_watch_event_strips_forbidden(tmp_path: Path, monkeypatch) -> None:
    log = tmp_path / "events.jsonl"
    monkeypatch.setenv("EBAY_NOTIFICATION_WATCH_LOG", str(log))
    record_watch_event("EBAY_CHALLENGE_RECEIVED", token="SECRETTOKEN", endpoint_host="example.test")
    blob = log.read_text(encoding="utf-8")
    assert "SECRETTOKEN" not in blob
    assert "example.test" in blob
    assert watch_log_path() == log
