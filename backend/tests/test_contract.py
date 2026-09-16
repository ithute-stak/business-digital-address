from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import Settings
from app.ithute import IthutePlatformClient
from app.main import app
from app.security import require_user
from app.services import OFFICIAL_LOCAL_PART_PREFIX, official_address_for, official_local_part


ROOT = Path(__file__).parents[1]


def test_official_address_is_stable_not_tin_based_and_namespace_scoped() -> None:
    assert OFFICIAL_LOCAL_PART_PREFIX == "bda-"
    assert official_local_part("2026/ABC-001") == "bda-2026abc001"
    local, address = official_address_for("2026/ABC-001", "ITHUTE.CO.LS.")
    assert local == "bda-2026abc001"
    assert address == "bda-2026abc001@ithute.co.ls"

    long_a = official_local_part("A" * 80)
    long_b = official_local_part("A" * 79 + "B")
    assert len(long_a) <= 64
    assert long_a.startswith("bda-")
    assert long_a != long_b


def test_platform_endpoints_match_ithute_contract() -> None:
    settings = Settings()
    assert settings.ithute_token_url.endswith("/v1/auth/service-token")
    assert settings.ithute_invite_url.endswith("/v1/platform/identity-invitations")
    assert settings.ithute_mail_base_url.endswith("/api/v1/platform/mail")
    assert settings.ithute_service_client_id == "business-digital-address"
    assert settings.portal_base_url == "https://business.ithute.co.ls"
    assert settings.official_domain == "ithute.co.ls"


def test_alembic_revisions_are_safe_platform_config_is_seeded_and_pending_addresses_migrate() -> None:
    core = (ROOT / "alembic" / "versions" / "0001_bda_core.py").read_text(encoding="utf-8")
    config = (ROOT / "alembic" / "versions" / "0002_platform_config.py").read_text(encoding="utf-8")
    namespace = (ROOT / "alembic" / "versions" / "0003_reserved_mail_namespace.py").read_text(encoding="utf-8")
    assert 'revision = "0001_bda_core"' in core
    assert 'revision = "0002_platform_config"' in config
    assert 'revision = "0003_reserved_mail_namespace"' in namespace
    assert 'down_revision = "0002_platform_config"' in namespace
    assert len("0001_bda_core") <= 32
    assert len("0002_platform_config") <= 32
    assert len("0003_reserved_mail_namespace") <= 32
    assert '"platform_binding_id"' in core
    assert '"platform_mailbox_id"' in core
    assert 'portal="https://business.ithute.co.ls"' in config
    assert 'domain="ithute.co.ls"' in config
    assert '_RESERVED_PREFIX = "bda-"' in namespace
    assert "oa.platform_binding_id IS NULL" in namespace
    assert "oa.platform_mailbox_id IS NULL" in namespace
    assert "oa.provisioned_at IS NULL" in namespace


def test_ithute_client_requests_scoped_managed_tokens(monkeypatch) -> None:
    calls: list[dict] = []

    class Response:
        def __init__(self, payload: dict, status_code: int = 200):
            self._payload = payload
            self.status_code = status_code
            self.is_success = 200 <= status_code < 300

        def json(self):
            return self._payload

    def fake_post(url, *, json, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers})
        if url.endswith("/v1/auth/service-token"):
            return Response({"access_token": "signed-token", "expires_in": 300, "scope": json["scope"]})
        if url.endswith("/v1/platform/identity-invitations"):
            return Response({"id": str(uuid.uuid4()), "delivery_status": "sent"}, 201)
        if url.endswith("/mailboxes"):
            return Response(
                {
                    "binding_id": str(uuid.uuid4()),
                    "mailbox_id": str(uuid.uuid4()),
                    "address": "bda-123@ithute.co.ls",
                    "status": "active",
                },
                201,
            )
        raise AssertionError(url)

    monkeypatch.setattr("app.ithute.httpx.post", fake_post)
    settings = Settings(ithute_service_client_secret="x" * 32)
    client = IthutePlatformClient(settings)
    client.invite_identity(
        external_reference="business-owner:1",
        display_name="Owner",
        preferred_channel="phone",
        email=None,
        phone="+26662000000",
    )
    client.provision_mailbox(
        external_reference="business:1",
        domain_name="ithute.co.ls",
        local_part="bda-123",
        display_name="Example Business",
    )

    token_requests = [call["json"] for call in calls if call["url"].endswith("/v1/auth/service-token")]
    assert token_requests[0]["audience"] == "ithute-auth"
    assert token_requests[0]["scope"] == "identity.invite"
    assert token_requests[1]["audience"] == "ithute-mail"
    assert token_requests[1]["scope"] == "mailbox.create"


def test_first_local_vertical_flow() -> None:
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:10].upper()
    registration = f"REG-{suffix}"
    tin = f"TIN-{suffix}"

    created = client.post(
        "/api/v1/businesses",
        json={
            "registration_number": registration,
            "tin": tin,
            "legal_name": "Foundation Test Business",
        },
    )
    assert created.status_code == 201, created.text
    business = created.json()
    business_id = business["id"]
    assert business["tin"] == tin
    assert business["official_address"]["local_part"].startswith("bda-")
    assert business["official_address"]["address"].endswith("@ithute.co.ls")
    assert business["official_address"]["mailbox_status"] == "pending"

    external = client.post(
        f"/api/v1/businesses/{business_id}/external-emails",
        json={"email": f"accounts-{suffix.lower()}@example.com", "forward_official_mail": True},
    )
    assert external.status_code == 201, external.text
    external_data = external.json()
    assert external_data["status"] == "pending"
    assert external_data["verification_code"]

    verified = client.post(
        f"/api/v1/businesses/{business_id}/external-emails/{external_data['id']}/verify",
        json={"code": external_data["verification_code"]},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "verified"

    agency_code = f"rsl-{suffix.lower()}"
    agency = client.post("/api/v1/dev/agencies", json={"code": agency_code, "name": "RSL Simulator"})
    assert agency.status_code == 201, agency.text

    message = client.post(
        "/api/v1/dev/official-messages",
        json={
            "tin": tin,
            "agency_code": agency_code,
            "external_message_id": f"MSG-{suffix}",
            "subject": "Official test communication",
            "body_text": "This message validates the retained official inbox path.",
        },
    )
    assert message.status_code == 201, message.text
    deliveries = message.json()["deliveries"]
    assert any(row["channel"] == "official_inbox" and row["status"] == "delivered" for row in deliveries)
    assert any(row["channel"] == "external_forward" and row["status"] == "pending_provider" for row in deliveries)

    inbox = client.get(f"/api/v1/businesses/{business_id}/messages")
    assert inbox.status_code == 200, inbox.text
    assert inbox.json()[0]["subject"] == "Official test communication"


def test_auth_cannot_be_disabled_in_production() -> None:
    settings = Settings(environment="production", auth_required=False)
    with pytest.raises(HTTPException) as exc:
        require_user(credentials=None, settings=settings)
    assert exc.value.status_code == 503
