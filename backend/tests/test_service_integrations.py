from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app.config import Settings
from app.server import app
from app.service_security import ManagedServiceVerifier, require_service_scope


client = TestClient(app)


def _trade_payload() -> dict:
    suffix = uuid.uuid4().hex[:10].upper()
    return {
        "source_reference": f"TRADE-{suffix}",
        "registration_number": f"REG-{suffix}",
        "tin": f"TIN-{suffix}",
        "legal_name": f"Trade Registered Business {suffix}",
        "trading_name": f"Trade {suffix}",
        "owner": {
            "display_name": "Business Owner",
            "email": f"owner-{suffix.lower()}@example.com",
            "preferred_channel": "email",
        },
    }


def test_trade_registration_requires_the_trade_scope_and_is_idempotent() -> None:
    payload = _trade_payload()

    missing = client.post("/api/v1/integrations/trade/businesses", json=payload)
    assert missing.status_code == 401, missing.text

    wrong = client.post(
        "/api/v1/integrations/trade/businesses",
        json=payload,
        headers={"X-BDA-Dev-Service": "rsl-simulator"},
    )
    assert wrong.status_code == 403, wrong.text

    created = client.post(
        "/api/v1/integrations/trade/businesses",
        json=payload,
        headers={"X-BDA-Dev-Service": "trade-simulator"},
    )
    assert created.status_code == 201, created.text
    first = created.json()
    assert first["registration_status"] == "created"
    assert first["owner_invitation_status"] == "pending_platform"
    assert first["business"]["tin"] == payload["tin"]
    assert first["business"]["official_address"]["address"].endswith("@ithute.co.ls")

    replay = client.post(
        "/api/v1/integrations/trade/businesses",
        json=payload,
        headers={"X-BDA-Dev-Service": "trade-simulator"},
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["registration_status"] == "existing"
    assert replay.json()["business"]["id"] == first["business"]["id"]

    changed = dict(payload)
    changed["legal_name"] = "Conflicting Legal Name"
    conflict = client.post(
        "/api/v1/integrations/trade/businesses",
        json=changed,
        headers={"X-BDA-Dev-Service": "trade-simulator"},
    )
    assert conflict.status_code == 409, conflict.text


def test_rsl_service_delivers_to_tin_without_accepting_an_agency_identity() -> None:
    payload = _trade_payload()
    registered = client.post(
        "/api/v1/integrations/trade/businesses",
        json=payload,
        headers={"X-BDA-Dev-Service": "trade-simulator"},
    )
    assert registered.status_code == 201, registered.text
    business = registered.json()["business"]

    message_payload = {
        "tin": payload["tin"],
        "external_message_id": f"RSL-{uuid.uuid4().hex}",
        "subject": "Official tax communication",
        "body_text": "This is an official simulator message retained in the business inbox.",
        "classification": "official",
    }

    wrong = client.post(
        "/api/v1/integrations/agencies/messages",
        json=message_payload,
        headers={"X-BDA-Dev-Service": "trade-simulator"},
    )
    assert wrong.status_code == 403, wrong.text

    delivered = client.post(
        "/api/v1/integrations/agencies/messages",
        json=message_payload,
        headers={"X-BDA-Dev-Service": "rsl-simulator"},
    )
    assert delivered.status_code == 201, delivered.text
    result = delivered.json()
    assert result["delivery_status"] == "stored"
    assert result["message"]["business_id"] == business["id"]
    assert any(
        row["channel"] == "official_inbox"
        and row["status"] == "delivered"
        and row["target"].endswith("@ithute.co.ls")
        for row in result["message"]["deliveries"]
    )

    replay = client.post(
        "/api/v1/integrations/agencies/messages",
        json=message_payload,
        headers={"X-BDA-Dev-Service": "rsl-simulator"},
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["delivery_status"] == "existing"
    assert replay.json()["message"]["id"] == result["message"]["id"]

    changed = dict(message_payload)
    changed["body_text"] = "Different content with the same agency message ID."
    conflict = client.post(
        "/api/v1/integrations/agencies/messages",
        json=changed,
        headers={"X-BDA-Dev-Service": "rsl-simulator"},
    )
    assert conflict.status_code == 409, conflict.text


def test_development_service_header_is_rejected_in_production() -> None:
    dependency = require_service_scope("business.register")
    with pytest.raises(HTTPException) as exc:
        dependency(
            credentials=None,
            dev_service="trade-simulator",
            settings=Settings(environment="production"),
        )
    assert exc.value.status_code == 401


def test_managed_service_verifier_rejects_legacy_tokens_and_accepts_managed_tokens() -> None:
    settings = Settings(
        auth_issuer="https://auth.ithute.co.ls",
        auth_audience="business-digital-address",
    )
    verifier = ManagedServiceVerifier(settings)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    class FakeJwks:
        def get_signing_key_from_jwt(self, token: str):
            return SimpleNamespace(key=public_key)

    verifier.jwks = FakeJwks()
    now = datetime.now(timezone.utc)
    base_claims = {
        "iss": "https://auth.ithute.co.ls",
        "sub": "service:trade-simulator",
        "aud": "business-digital-address",
        "azp": "trade-simulator",
        "scope": "business.register",
        "token_use": "service",
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }

    legacy = jwt.encode(base_claims, private_key, algorithm="RS256", headers={"kid": "test"})
    with pytest.raises(HTTPException) as exc:
        verifier.verify(legacy)
    assert exc.value.status_code == 401

    managed_claims = dict(base_claims, service_auth="managed")
    managed = jwt.encode(managed_claims, private_key, algorithm="RS256", headers={"kid": "test"})
    principal = verifier.verify(managed)
    assert principal.client_id == "trade-simulator"
    assert principal.managed is True
    assert principal.scopes == frozenset({"business.register"})


def test_bearer_token_never_falls_back_to_development_identity(monkeypatch) -> None:
    dependency = require_service_scope("business.register")

    class BrokenVerifier:
        def verify(self, token: str):
            raise HTTPException(status_code=401, detail="invalid service token")

    monkeypatch.setattr("app.service_security.managed_service_verifier", lambda: BrokenVerifier())
    with pytest.raises(HTTPException) as exc:
        dependency(
            credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad-token"),
            dev_service="trade-simulator",
            settings=Settings(environment="development"),
        )
    assert exc.value.status_code == 401
