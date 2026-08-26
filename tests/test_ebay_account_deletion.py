"""Marketplace Account Deletion webhook, signatures, and deletion engine."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterator
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.ebay_webhooks import get_db as ebay_get_db
from app.api.routes.ops import get_db as ops_get_db
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db_session, reset_engine
from app.main import create_app
from app.models.enums import SourceStatus
from app.models.orm import AuditEvent, EbayDeletionNotification, Listing, RawListing, Source
from app.privacy.ebay_challenge import challenge_response, token_is_valid
from app.privacy.ebay_deletion import DeletionIdentities, EbayUserDeletionService
from app.privacy.ebay_minimise import minimise_normalized_listing
from app.privacy.ebay_signature import EbayPublicKey, decode_signature_header
from app.privacy.identifiers import identifier_hash
from app.sources.base import NormalizedListing


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ARG001
    return "JSON"


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):  # noqa: ARG001
    return "CHAR(36)"


ENDPOINT = "https://arie.example.test/webhooks/ebay/account-deletion"
TOKEN = "a" * 32
TOPIC = "MARKETPLACE_ACCOUNT_DELETION"
ROUTE = "/webhooks/ebay/account-deletion"


@pytest.fixture()
def engine():
    import app.models.orm  # noqa: F401

    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine) -> Iterator[Session]:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as sess:
        yield sess


@pytest.fixture()
def client(engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("EBAY_NOTIFICATION_VERIFICATION_TOKEN", TOKEN)
    monkeypatch.setenv("EBAY_NOTIFICATION_ENDPOINT_URL", ENDPOINT)
    monkeypatch.setenv("EBAY_CLIENT_ID", "PRD-test-id")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "PRD-test-secret")
    monkeypatch.setenv("EBAY_ENV", "production")
    get_settings.cache_clear()
    fresh = get_settings()
    monkeypatch.setattr("app.core.config.settings", fresh)
    monkeypatch.setattr("app.api.routes.ebay_webhooks.settings", fresh)
    reset_engine()

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _override() -> Iterator[Session]:
        sess = factory()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    application = create_app()
    application.dependency_overrides[get_db_session] = _override
    application.dependency_overrides[ebay_get_db] = _override
    application.dependency_overrides[ops_get_db] = _override
    with TestClient(application) as test_client:
        yield test_client
    application.dependency_overrides.clear()
    get_settings.cache_clear()


def _ec_keypair():
    key = ec.generate_private_key(ec.SECP256R1())
    pem = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
        .replace("\n", "")
    )
    return key, pem


def _sign(private_key, body: bytes) -> str:
    sig = private_key.sign(body, ec.ECDSA(hashes.SHA1()))
    payload = json.dumps(
        {"kid": "test-kid", "signature": base64.b64encode(sig).decode()},
        separators=(",", ":"),
    )
    return base64.b64encode(payload.encode()).decode()


def _notice(*, username: str = "seller_alpha", notification_id: str = "nid-1") -> dict:
    return {
        "metadata": {"topic": TOPIC, "schemaVersion": "1.0", "deprecated": False},
        "notification": {
            "notificationId": notification_id,
            "eventDate": "2026-08-23T12:00:00.000Z",
            "publishDate": "2026-08-23T12:00:00.000Z",
            "publishAttemptCount": 1,
            "data": {
                "username": username,
                "userId": "uid-9",
                "eiasToken": "eias-9",
            },
        },
    }


def _identities(username: str, notification_id: str = "nid-direct") -> DeletionIdentities:
    return DeletionIdentities(
        username=username,
        user_id="uid-9",
        eias_token="eias-9",
        topic=TOPIC,
        notification_id=notification_id,
        schema_version="1.0",
        event_date="2026-08-23T12:00:00.000Z",
        publish_date="2026-08-23T12:00:00.000Z",
        publish_attempt_count=1,
    )


def _seed_source(session: Session) -> Source:
    existing = session.get(Source, "ebay_browse")
    if existing:
        return existing
    source = Source(
        id="ebay_browse",
        display_name="eBay Browse",
        country="IE",
        kind="acquisition",
        official_api=True,
        access_method="oauth_client_credentials",
        credentials_required=True,
    )
    session.add(source)
    session.flush()
    return source


def _seed_seller(session: Session, username: str = "seller_alpha", external_id: str = "item-1") -> Listing:
    _seed_source(session)
    now = datetime.now(timezone.utc)
    listing = Listing(
        source_id="ebay_browse",
        external_id=external_id,
        title="Camera",
        url=f"https://www.ebay.co.uk/itm/{external_id}",
        currency="GBP",
        asking_price=Decimal("100.00"),
        seller=None,
        seller_location="Manchester",
        first_seen_at=now,
        last_seen_at=now,
        observed_at=now,
        fingerprint=f"fp-{external_id}",
        extras={
            "seller_username_hash": identifier_hash(username),
            "seller_user_id_hash": identifier_hash("uid-9"),
            "seller_eias_hash": identifier_hash("eias-9"),
            "seller_feedback_score": 12,
            "seller_feedback_percentage": 99.5,
            "seller_present": True,
        },
    )
    session.add(listing)
    session.flush()
    session.add(
        RawListing(
            source_id="ebay_browse",
            external_id=external_id,
            fetched_at=now,
            payload={"itemId": external_id, "title": "Camera", "seller": {"username": username}},
            content_hash=hashlib.sha256(external_id.encode()).hexdigest(),
        )
    )
    session.add(
        AuditEvent(
            actor="system",
            action="ingest",
            entity_type="listing",
            entity_id=str(listing.id),
            payload={"seller": username, "item": external_id},
        )
    )
    session.commit()
    return listing


def test_token_rules() -> None:
    assert token_is_valid("a" * 32)
    assert not token_is_valid("short")
    assert not token_is_valid("x" * 81)


def test_challenge_matches_ebay_hash() -> None:
    expected = hashlib.sha256(("abc" + TOKEN + ENDPOINT).encode()).hexdigest()
    assert challenge_response("abc", TOKEN, ENDPOINT) == expected


def test_watch_events_on_challenge(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "events.jsonl"
    monkeypatch.setenv("EBAY_NOTIFICATION_WATCH_LOG", str(log))
    response = client.get(ROUTE, params={"challenge_code": "abc"})
    assert response.status_code == 200
    assert response.json()["challengeResponse"] == challenge_response("abc", TOKEN, ENDPOINT)
    events = [json.loads(line)["event"] for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert events == [
        "EBAY_CHALLENGE_RECEIVED",
        "EBAY_CHALLENGE_RESPONDED_200",
        "EBAY_NOTIFICATION_ENDPOINT_VERIFIED",
    ]
    assert TOKEN not in log.read_text(encoding="utf-8")
    unsigned = client.post(ROUTE, content=b"{}")
    assert unsigned.status_code == 412


def test_unsigned_post_412_when_db_unavailable(client: TestClient) -> None:
    from app.api.routes.ebay_webhooks import get_db as ebay_get_db

    def _none():
        yield None

    client.app.dependency_overrides[ebay_get_db] = _none
    try:
        assert client.post(ROUTE, content=b"{}").status_code == 412
    finally:
        client.app.dependency_overrides.pop(ebay_get_db, None)


def test_get_challenge_camel_case(client: TestClient) -> None:
    response = client.get(ROUTE, params={"challengeCode": "xyz"})
    assert response.status_code == 200
    assert "challengeResponse" in response.json()


def test_get_challenge_missing_code(client: TestClient) -> None:
    assert client.get(ROUTE).status_code == 400


def test_health_does_not_claim_subscription(client: TestClient) -> None:
    response = client.get("/health/ebay-notifications")
    assert response.status_code == 200
    body = response.json()
    assert body["ebay_subscription_active"] is False
    assert body["verification_token_configured"] is True
    assert body["ready_for_ebay_challenge"] is True


def test_valid_notification_anonymises_and_acks(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    listing = _seed_seller(session)
    private_key, pem = _ec_keypair()
    body = json.dumps(_notice(), separators=(",", ":")).encode()
    header = _sign(private_key, body)

    async def _key(_kid: str):
        return EbayPublicKey(kid="test-kid", pem=pem, algorithm="ECDSA", digest="SHA1")

    monkeypatch.setattr("app.api.routes.ebay_webhooks.fetch_public_key", _key)
    response = client.post(
        ROUTE,
        content=body,
        headers={"X-EBAY-SIGNATURE": header, "Content-Type": "application/json"},
    )
    assert response.status_code == 204
    session.expire_all()
    stored = session.get(Listing, listing.id)
    assert stored is not None
    assert stored.seller is None
    extras = stored.extras or {}
    assert not extras.get("seller_username_hash")
    raw = session.scalars(select(RawListing)).first()
    assert raw is not None
    assert "seller_alpha" not in json.dumps(raw.payload)
    notice = session.scalars(select(EbayDeletionNotification)).first()
    assert notice is not None
    assert notice.processed_at is not None
    assert notice.username_hash == identifier_hash("seller_alpha")


def test_invalid_signature_does_not_delete(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    listing = _seed_seller(session)
    _private_key, pem = _ec_keypair()
    body = json.dumps(_notice(), separators=(",", ":")).encode()
    other = ec.generate_private_key(ec.SECP256R1())
    bad_header = _sign(other, body)

    async def _key(_kid: str):
        return EbayPublicKey(kid="test-kid", pem=pem, algorithm="ECDSA", digest="SHA1")

    monkeypatch.setattr("app.api.routes.ebay_webhooks.fetch_public_key", _key)
    response = client.post(
        ROUTE,
        content=body,
        headers={"X-EBAY-SIGNATURE": bad_header, "Content-Type": "application/json"},
    )
    assert response.status_code == 412
    session.expire_all()
    assert session.get(Listing, listing.id) is not None
    assert (session.get(Listing, listing.id).extras or {}).get("seller_username_hash") == identifier_hash(
        "seller_alpha"
    )
    assert session.scalars(select(EbayDeletionNotification)).first() is None


def test_tampered_body_rejected(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_seller(session)
    private_key, pem = _ec_keypair()
    body = json.dumps(_notice(), separators=(",", ":")).encode()
    header = _sign(private_key, body)
    tampered = body.replace(b"seller_alpha", b"seller_omega")

    async def _key(_kid: str):
        return EbayPublicKey(kid="test-kid", pem=pem, algorithm="ECDSA", digest="SHA1")

    monkeypatch.setattr("app.api.routes.ebay_webhooks.fetch_public_key", _key)
    response = client.post(
        ROUTE,
        content=tampered,
        headers={"X-EBAY-SIGNATURE": header, "Content-Type": "application/json"},
    )
    assert response.status_code == 412
    session.expire_all()
    listing = session.scalars(select(Listing)).first()
    assert listing is not None
    assert (listing.extras or {}).get("seller_username_hash") == identifier_hash("seller_alpha")


def test_malformed_signature_header(client: TestClient) -> None:
    response = client.post(
        ROUTE,
        content=b"{}",
        headers={"X-EBAY-SIGNATURE": "not-valid", "Content-Type": "application/json"},
    )
    assert response.status_code == 412


def test_duplicate_notification_idempotent(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_seller(session)
    private_key, pem = _ec_keypair()
    body = json.dumps(_notice(), separators=(",", ":")).encode()
    header = _sign(private_key, body)

    async def _key(_kid: str):
        return EbayPublicKey(kid="test-kid", pem=pem, algorithm="ECDSA", digest="SHA1")

    monkeypatch.setattr("app.api.routes.ebay_webhooks.fetch_public_key", _key)
    headers = {"X-EBAY-SIGNATURE": header, "Content-Type": "application/json"}
    assert client.post(ROUTE, content=body, headers=headers).status_code == 204
    assert client.post(ROUTE, content=body, headers=headers).status_code == 204
    session.expire_all()
    rows = list(session.scalars(select(EbayDeletionNotification)))
    assert len(rows) == 1


def test_unknown_user_still_204(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_source(session)
    session.commit()
    private_key, pem = _ec_keypair()
    body = json.dumps(_notice(username="nobody"), separators=(",", ":")).encode()
    header = _sign(private_key, body)

    async def _key(_kid: str):
        return EbayPublicKey(kid="test-kid", pem=pem, algorithm="ECDSA", digest="SHA1")

    monkeypatch.setattr("app.api.routes.ebay_webhooks.fetch_public_key", _key)
    response = client.post(
        ROUTE,
        content=body,
        headers={"X-EBAY-SIGNATURE": header, "Content-Type": "application/json"},
    )
    assert response.status_code == 204
    session.expire_all()
    notice = session.scalars(select(EbayDeletionNotification)).first()
    assert notice is not None


def test_key_fetch_failure_is_500(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    private_key, _pem = _ec_keypair()
    body = json.dumps(_notice(), separators=(",", ":")).encode()
    header = _sign(private_key, body)

    async def _fail(_kid: str):
        from app.privacy.ebay_signature import SignatureError

        raise SignatureError("public key fetch failed")

    monkeypatch.setattr("app.api.routes.ebay_webhooks.fetch_public_key", _fail)
    response = client.post(
        ROUTE,
        content=body,
        headers={"X-EBAY-SIGNATURE": header, "Content-Type": "application/json"},
    )
    assert response.status_code == 500


def test_minimise_strips_username() -> None:
    listing = NormalizedListing(
        source_id="ebay_browse",
        external_id="1",
        title="x",
        url="https://www.ebay.co.uk/itm/1",
        seller="VisibleName",
        extras={"seller_feedback_score": 3},
        raw={"seller": {"username": "VisibleName", "userId": "u1"}},
    )
    out = minimise_normalized_listing(listing)
    assert out.seller is None
    assert out.extras["seller_username_hash"] == identifier_hash("VisibleName")
    assert "VisibleName" not in json.dumps(out.raw)


def test_decode_signature_header() -> None:
    inner = base64.b64encode(json.dumps({"kid": "k", "signature": "s"}).encode()).decode()
    parsed = decode_signature_header(inner)
    assert parsed["kid"] == "k"
    assert parsed["signature"] == "s"


def test_deletion_multiple_listings(session: Session) -> None:
    for i in range(3):
        _seed_seller(session, username="multi", external_id=f"item-{i}")
    result = EbayUserDeletionService().process(session, _identities("multi", "nid-multi"))
    session.commit()
    assert result.records_anonymised.get("listings") == 3
    for listing in session.scalars(select(Listing)).all():
        assert listing.seller is None
        extras = listing.extras or {}
        assert not extras.get("seller_username_hash")


def test_audit_privacy_no_username(session: Session) -> None:
    _seed_seller(session)
    EbayUserDeletionService().process(session, _identities("seller_alpha", "nid-audit"))
    session.commit()
    remaining = session.scalars(select(AuditEvent)).all()
    blob = json.dumps([row.payload for row in remaining])
    assert "seller_alpha" not in blob


def test_production_oauth_status_exists() -> None:
    assert SourceStatus.PRODUCTION_KEYSET_DISABLED_COMPLIANCE.value == (
        "PRODUCTION_KEYSET_DISABLED_COMPLIANCE"
    )
    assert SourceStatus.BLOCKED_CREDENTIALS.value == "BLOCKED_CREDENTIALS"
    assert (
        SourceStatus.PRODUCTION_KEYSET_DISABLED_COMPLIANCE
        is not SourceStatus.BLOCKED_CREDENTIALS
    )
