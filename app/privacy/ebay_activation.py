"""Activation helpers: hosting probe, public proof, Notification API bootstrap.

Does not print verification tokens. Does not create paid cloud accounts.
"""

from __future__ import annotations

import json
import os
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.privacy.ebay_challenge import (
    challenge_response,
    read_endpoint_url,
    read_verification_token,
    token_is_valid,
    write_token_to_env,
)
from app.privacy.ebay_health import notification_health
from app.sources.ebay import TOKEN_URL

logger = get_logger("arie.privacy.ebay_activation")

PORTAL_KEYS_URL = "https://developer.ebay.com/my/keys"
TOPIC = "MARKETPLACE_ACCOUNT_DELETION"
NOTIFICATION_SCOPE = "https://api.ebay.com/oauth/api_scope/commerce.notification.subscription"
DEPLOY_ENV_KEYS = (
    "FLY_API_TOKEN",
    "RENDER_API_KEY",
    "RAILWAY_TOKEN",
    "HEROKU_API_KEY",
    "CLOUDFLARE_API_TOKEN",
)

STATUS_ACTIVATED = "EBAY_COMPLIANCE_FULLY_ACTIVATED"
STATUS_PORTAL = "EBAY_COMPLIANCE_READY_FOR_ONE_OWNER_PORTAL_ACTION"
STATUS_BLOCKED = "EBAY_COMPLIANCE_BLOCKED_EXTERNAL"


def detect_hosting() -> dict[str, Any]:
    """Inspect repo + environment for an existing public HTTPS deployment."""
    current = get_settings()
    endpoint = read_endpoint_url() or (current.ebay_notification_endpoint_url or "").strip()
    deploy_keys_present = [key for key in DEPLOY_ENV_KEYS if os.environ.get(key)]
    files = {
        "dockerfile": Path("Dockerfile").exists(),
        "docker_compose": Path("docker-compose.yml").exists(),
        "fly_toml": Path("fly.toml").exists(),
        "render_yaml": Path("render.yaml").exists() or Path("render.yml").exists(),
        "procfile": Path("Procfile").exists(),
        "caddyfile": Path("Caddyfile").exists(),
        "nginx_conf": Path("nginx.conf").exists() or Path("nginx/nginx.conf").exists(),
        "github_workflows": Path(".github/workflows").exists(),
    }
    public = _is_public_https(endpoint)
    return {
        "endpoint_url": endpoint or None,
        "endpoint_public_https": public,
        "deploy_credential_names_present": deploy_keys_present,
        "files": files,
        "cursor_agent_url_is_not_webhook": True,
        "ngrok_forbidden": True,
        "can_auto_deploy": bool(deploy_keys_present) and files["dockerfile"],
        "note": (
            "Public HTTPS endpoint URL is configured."
            if public
            else (
                "No EBAY_NOTIFICATION_ENDPOINT_URL yet. If ARIE is already live on "
                "Render, set it to https://<service>.onrender.com/webhooks/ebay/account-deletion."
            )
        ),
    }


def _is_public_https(url: str) -> bool:
    if not url.startswith("https://"):
        return False
    host = (urlparse(url).hostname or "").lower()
    if not host or host in {"localhost", "127.0.0.1", "::1"}:
        return False
    if host.endswith(".local") or host.endswith(".internal"):
        return False
    return True


def prove_public_endpoint(url: str | None = None) -> dict[str, Any]:
    """Call the webhook from this process over the network. Never include the token."""
    get_settings.cache_clear()
    current = get_settings()
    endpoint = (url or read_endpoint_url() or current.ebay_notification_endpoint_url or "").strip()
    token = read_verification_token() or (current.ebay_notification_verification_token or "")
    artifact: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "endpoint_url": endpoint or None,
        "token_configured": token_is_valid(token),
        "token_length": len(token) if token else 0,
        "secrets_included": False,
        "public": False,
        "https_certificate_valid": None,
        "get_status": None,
        "post_unsigned_status": None,
        "health_status": None,
        "challenge_match": False,
        "redirect": False,
        "auth_blocked": False,
        "latency_ms": None,
        "hostname_matches_config": False,
        "blocked_reason": None,
    }
    if not token_is_valid(token):
        artifact["blocked_reason"] = "verification_token_not_configured"
        return artifact
    if not endpoint.startswith("https://"):
        artifact["blocked_reason"] = "no_public_https_endpoint"
        return artifact
    parsed = urlparse(endpoint)
    artifact["hostname"] = parsed.hostname
    artifact["hostname_matches_config"] = True
    if not _is_public_https(endpoint):
        artifact["blocked_reason"] = "endpoint_is_not_public"
        return artifact

    challenge_code = "arie-public-proof"
    expected = challenge_response(challenge_code, token, endpoint)
    get_url = f"{endpoint}?challenge_code={challenge_code}"
    try:
        started = time.perf_counter()
        with httpx.Client(timeout=20.0, follow_redirects=False, verify=True) as client:
            get_response = client.get(get_url)
            artifact["latency_ms"] = int((time.perf_counter() - started) * 1000)
            artifact["https_certificate_valid"] = True
            artifact["get_status"] = get_response.status_code
            artifact["redirect"] = get_response.status_code in {301, 302, 303, 307, 308}
            artifact["auth_blocked"] = get_response.status_code in {401, 403}
            www = get_response.headers.get("www-authenticate")
            if www:
                artifact["auth_blocked"] = True
            body = None
            try:
                body = get_response.json()
            except ValueError:
                artifact["get_body_is_json"] = False
            if isinstance(body, dict):
                if body.get("error"):
                    artifact["get_error"] = str(body.get("error"))
                actual = str(body.get("challengeResponse") or "")
                artifact["challenge_response_length"] = len(actual)
                artifact["challenge_match"] = (
                    get_response.status_code == 200 and actual == expected and len(actual) == 64
                )
            health = client.get(f"{parsed.scheme}://{parsed.netloc}/health/ebay-notifications")
            artifact["health_status"] = health.status_code
            if health.status_code == 200:
                try:
                    health_body = health.json()
                    artifact["health"] = {
                        "ready": health_body.get("ready"),
                        "ebay_subscription_active": health_body.get("ebay_subscription_active"),
                        "endpoint_https": health_body.get("endpoint_https"),
                        "verification_token_valid": health_body.get("verification_token_valid"),
                    }
                except ValueError:
                    artifact["health"] = {"ready": False}
            post = client.post(endpoint, content=b"{}", headers={"Content-Type": "application/json"})
            artifact["post_unsigned_status"] = post.status_code
            artifact["post_unsigned_expected_412"] = post.status_code == 412
    except ssl.SSLError as exc:
        artifact["https_certificate_valid"] = False
        artifact["blocked_reason"] = f"tls_error:{type(exc).__name__}"
        return artifact
    except httpx.HTTPError as exc:
        artifact["blocked_reason"] = f"http_error:{type(exc).__name__}"
        return artifact

    artifact["public"] = bool(
        artifact.get("https_certificate_valid")
        and artifact.get("get_status") == 200
        and artifact.get("challenge_match")
        and not artifact.get("redirect")
        and not artifact.get("auth_blocked")
        and artifact.get("post_unsigned_status") == 412
    )
    if not artifact["public"] and not artifact.get("blocked_reason"):
        artifact["blocked_reason"] = "public_challenge_mismatch_or_unreachable"
    return artifact


async def probe_notification_api() -> dict[str, Any]:
    """Try official Notification API destination/subscription. Never log secrets.

    Marketplace Account Deletion bootstrap is documented as a Developer Portal
    form. The API is attempted only with existing client-credentials. A disabled
    Production keyset typically returns 401 invalid_client — that is portal-only,
    not a cue to regenerate keys.
    """
    get_settings.cache_clear()
    current = get_settings()
    result: dict[str, Any] = {
        "attempted": True,
        "portal_only_bootstrap": True,
        "oauth_http_status": None,
        "oauth_error": None,
        "destination_created": False,
        "subscription_created": False,
        "topic": TOPIC,
        "docs": [
            "https://developer.ebay.com/marketplace-account-deletion",
            "https://developer.ebay.com/api-docs/commerce/notification/overview.html",
        ],
        "secrets_included": False,
    }
    if not current.ebay_client_id or not current.ebay_client_secret:
        result["oauth_error"] = "client_credentials_missing_in_this_environment"
        result["note"] = (
            "This environment has no EBAY_CLIENT_ID/SECRET injected. Previous "
            "production-proof artifacts recorded Production OAuth 401 invalid_client "
            "with keys present. Do not regenerate keys."
        )
        return result

    env = current.ebay_api_env
    token_url = TOKEN_URL[env]
    api_root = "https://api.ebay.com" if env == "production" else "https://api.sandbox.ebay.com"
    basic = httpx.BasicAuth(current.ebay_client_id, current.ebay_client_secret)
    async with httpx.AsyncClient(timeout=20.0) as client:
        oauth = await client.post(
            token_url,
            auth=basic,
            data={"grant_type": "client_credentials", "scope": NOTIFICATION_SCOPE},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        result["oauth_http_status"] = oauth.status_code
        if oauth.status_code != 200:
            body = oauth.text[:240].replace("\n", " ")
            result["oauth_error"] = body
            result["portal_only_bootstrap"] = True
            result["note"] = (
                "Notification API OAuth was rejected. Marketplace Account Deletion "
                "must be configured in the eBay Developer Portal before the Production "
                "keyset can be used. Do not bypass login/MFA. Do not regenerate keys."
            )
            return result
        access = (oauth.json() or {}).get("access_token")
        if not access:
            result["oauth_error"] = "oauth_200_missing_access_token"
            return result
        result["portal_only_bootstrap"] = False
        headers = {"Authorization": f"Bearer {access}", "Content-Type": "application/json"}
        topic = await client.get(f"{api_root}/commerce/notification/v1/topic/{TOPIC}", headers=headers)
        result["topic_http_status"] = topic.status_code
        endpoint = read_endpoint_url() or current.ebay_notification_endpoint_url
        token = read_verification_token() or current.ebay_notification_verification_token
        if not (_is_public_https(endpoint) and token_is_valid(token)):
            result["note"] = (
                "OAuth succeeded but destination was not created: public HTTPS endpoint "
                "and verification token are required so eBay can complete the challenge."
            )
            return result
        proof = prove_public_endpoint(endpoint)
        if not proof.get("public"):
            result["note"] = "OAuth succeeded but public challenge proof failed; destination not created."
            result["public_proof_ok"] = False
            return result
        destination = await client.post(
            f"{api_root}/commerce/notification/v1/destination",
            headers=headers,
            json={
                "name": "ARIE_MARKETPLACE_ACCOUNT_DELETION",
                "status": "ENABLED",
                "deliveryConfig": {"endpoint": endpoint, "verificationToken": token},
            },
        )
        result["destination_http_status"] = destination.status_code
        location = destination.headers.get("Location") or destination.headers.get("location")
        destination_id = None
        if location:
            destination_id = location.rstrip("/").split("/")[-1]
        if destination.status_code in {201, 204} and destination_id:
            result["destination_created"] = True
            sub = await client.post(
                f"{api_root}/commerce/notification/v1/subscription",
                headers=headers,
                json={
                    "topicId": TOPIC,
                    "destinationId": destination_id,
                    "status": "ENABLED",
                },
            )
            result["subscription_http_status"] = sub.status_code
            result["subscription_created"] = sub.status_code in {201, 204}
        elif destination.status_code == 409:
            result["note"] = "Destination already exists (409). Treat portal/API as configured."
        else:
            result["note"] = (
                f"createDestination HTTP {destination.status_code}. "
                "Fall back to the Developer Portal form."
            )
            result["portal_only_bootstrap"] = True
    return result


def write_owner_portal_sheet(*, endpoint: str | None, status: str) -> Path:
    """Shortest owner-facing paste sheet. Does not include the token value."""
    Path("artifacts").mkdir(exist_ok=True)
    endpoint_line = endpoint or (
        "NOT SET — deploy ARIE on a persistent HTTPS host, then: "
        "make ebay-notification-set-endpoint URL=https://<host>/webhooks/ebay/account-deletion"
    )
    email = (
        os.environ.get("EBAY_NOTIFICATION_OPERATOR_EMAIL")
        or (get_settings().alert_email_to if hasattr(get_settings(), "alert_email_to") else "")
        or "walshe.ben@gmail.com"
    )
    lines = [
        "ENDPOINT URL:",
        endpoint_line,
        "",
        "VERIFICATION TOKEN:",
        "make ebay-notification-show-token",
        "",
        "TOPIC:",
        TOPIC,
        "",
        "OPERATOR EMAIL:",
        email,
        "",
    ]
    if endpoint and "onrender.com" in endpoint:
        lines.extend(
            [
                "RENDER ENVIRONMENT (same token and URL the app uses to hash the challenge):",
                "1. Auction-system → Environment → Add:",
                f"   EBAY_NOTIFICATION_ENDPOINT_URL={endpoint}",
                "   EBAY_NOTIFICATION_VERIFICATION_TOKEN=<paste `make ebay-notification-show-token`>",
                "2. Save. Wait until the service is Live.",
                "",
            ]
        )
    lines.extend(
        [
            "EBAY PORTAL:",
            f"1. Open {PORTAL_KEYS_URL} and sign in (MFA if asked).",
            "2. Open the Production application whose keyset is disabled.",
            "3. Alerts & Notifications → Marketplace Account Deletion.",
            "4. Paste Endpoint URL (exact string above).",
            "5. Paste token from `make ebay-notification-show-token`.",
            "6. Enter operator email.",
            "7. Save. Leave `make ebay-notification-watch` running to see:",
            "   EBAY_CHALLENGE_RECEIVED",
            "   EBAY_CHALLENGE_RESPONDED_200",
            "   EBAY_NOTIFICATION_ENDPOINT_VERIFIED",
            "8. Do not tick the 'we do not persist eBay user data' exemption.",
            "",
            f"AUTOMATION_STATUS: {status}",
        ]
    )
    text = "\n".join(lines)
    path = Path("artifacts/ebay_owner_portal_action.txt")
    path.write_text(text + "\n", encoding="utf-8")
    Path("docs/ebay/OWNER_PORTAL_ACTION.md").write_text(
        "# eBay portal — only remaining owner action\n\n```\n" + text + "\n```\n",
        encoding="utf-8",
    )
    return path


async def run_activation() -> dict[str, Any]:
    """Do everything that does not require a new paid account, domain, or ToS."""
    token_result = write_token_to_env()
    get_settings.cache_clear()
    hosting = detect_hosting()
    health = notification_health(None)
    api = await probe_notification_api()
    endpoint = read_endpoint_url() or get_settings().ebay_notification_endpoint_url
    proof = prove_public_endpoint(endpoint or None)
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/ebay_notification_public_proof.json").write_text(
        json.dumps(proof, indent=2, default=str), encoding="utf-8"
    )

    production = await _ebay_production_snapshot()
    oauth_ok = bool(production.get("oauth_ok"))
    browse_ok = bool(production.get("browse_ok"))

    if oauth_ok and browse_ok and proof.get("public"):
        status = STATUS_ACTIVATED
    elif proof.get("public") and not api.get("subscription_created"):
        status = STATUS_PORTAL
    else:
        status = STATUS_BLOCKED

    write_owner_portal_sheet(endpoint=endpoint or None, status=status)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "automation_status": status,
        "token": {
            "configured": bool(token_result.get("token_configured")),
            "length": token_result.get("token_length"),
            "valid": token_result.get("token_valid"),
            "action": token_result.get("action"),
            "show_command": "make ebay-notification-show-token",
        },
        "hosting": hosting,
        "health": {
            "ready": health.get("ready"),
            "ready_for_ebay_challenge": health.get("ready_for_ebay_challenge"),
            "endpoint_https": health.get("endpoint_https"),
            "verification_token_valid": health.get("verification_token_valid"),
            "verification_token_length": health.get("verification_token_length"),
            "ebay_subscription_active": health.get("ebay_subscription_active"),
            "database": health.get("database"),
        },
        "notification_api": api,
        "public_proof": {
            "public": proof.get("public"),
            "endpoint_url": proof.get("endpoint_url"),
            "blocked_reason": proof.get("blocked_reason"),
            "get_status": proof.get("get_status"),
            "challenge_match": proof.get("challenge_match"),
        },
        "production": production,
        "owner_portal_sheet": "artifacts/ebay_owner_portal_action.txt",
        "secrets_included": False,
    }
    Path("artifacts/ebay_compliance_activation.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    return payload


async def await_production_activation(*, attempts: int = 8, delay_seconds: float = 15.0) -> dict[str, Any]:
    """Poll Production OAuth/Browse for a short bound after portal Save."""
    last: dict[str, Any] = {}
    for index in range(attempts):
        last = await _ebay_production_snapshot()
        last["attempt"] = index + 1
        if last.get("oauth_ok") and last.get("browse_ok"):
            last["activated"] = True
            return last
        if index + 1 < attempts:
            time.sleep(delay_seconds)
    last["activated"] = False
    return last


async def _ebay_production_snapshot() -> dict[str, Any]:
    from app.sources.ebay import EbayBrowseAdapter

    adapter = EbayBrowseAdapter()
    proof = await adapter.healthcheck()
    oauth = (proof.proof or {}).get("oauth") or {}
    return {
        "health_status": proof.status.value,
        "health_ok": proof.ok,
        "http_status": proof.http_status,
        "records": proof.records,
        "oauth_ok": bool(oauth.get("ok")),
        "oauth_http_status": oauth.get("http_status"),
        "browse_ok": bool(proof.ok and proof.http_status == 200),
        "sandbox_used": (proof.proof or {}).get("sandbox_used"),
        "sample_urls": (proof.proof or {}).get("sample_urls"),
        "detail": proof.detail,
    }
