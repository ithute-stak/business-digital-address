from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings, get_settings
from app.db import SessionLocal
from app.ithute import MailSendResult
from app.models import Business, BusinessMember, MessageAttachment, MessageDelivery, OfficialMessage
from app.server import app


client = TestClient(app)


def _register() -> tuple[dict, str]:
    suffix = uuid.uuid4().hex[:10].upper()
    payload = {
        "source_reference": f"TRADE-ATT-{suffix}",
        "registration_number": f"REG-ATT-{suffix}",
        "tin": f"TIN-ATT-{suffix}",
        "legal_name": f"Attachment Business {suffix}",
        "owner": {
            "display_name": "Business Owner",
            "email": f"owner-{suffix.lower()}@example.com",
            "preferred_channel": "email",
        },
    }
    response = client.post(
        "/api/v1/integrations/trade/businesses",
        json=payload,
        headers={"X-BDA-Dev-Service": "trade-simulator"},
    )
    assert response.status_code == 201, response.text
    return response.json()["business"], payload["tin"]


def _message_payload(tin: str, reference: str) -> dict:
    content = b"%PDF-1.4 BDA official test document"
    return {
        "tin": tin,
        "external_message_id": reference,
        "subject": "Official tax notice with attachment",
        "body_text": "The attached PDF is part of this official communication.",
        "classification": "official",
        "attachments": [
            {
                "filename": "tax-notice.pdf",
                "content_type": "application/pdf",
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
        ],
    }


def test_agency_message_retains_attachment_and_is_idempotent() -> None:
    business, tin = _register()
    reference = f"RSL-ATT-{uuid.uuid4().hex}"
    payload = _message_payload(tin, reference)

    created = client.post(
        "/api/v1/integrations/agencies/messages-with-attachments",
        json=payload,
        headers={"X-BDA-Dev-Service": "rsl-simulator"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["delivery_status"] == "stored"
    assert created.json()["attachment_count"] == 1

    message_id = uuid.UUID(created.json()["message"]["id"])
    with SessionLocal() as db:
        attachment = db.scalar(select(MessageAttachment).where(MessageAttachment.message_id == message_id))
        assert attachment is not None
        assert attachment.filename == "tax-notice.pdf"
        assert attachment.content_type == "application/pdf"
        assert attachment.content.startswith(b"%PDF-1.4")
        official = db.scalar(
            select(MessageDelivery).where(
                MessageDelivery.message_id == message_id,
                MessageDelivery.channel == "official_inbox",
            )
        )
        assert official is not None and official.status == "delivered"

    replay = client.post(
        "/api/v1/integrations/agencies/messages-with-attachments",
        json=payload,
        headers={"X-BDA-Dev-Service": "rsl-simulator"},
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["delivery_status"] == "existing"
    assert replay.json()["message"]["id"] == created.json()["message"]["id"]

    changed = _message_payload(tin, reference)
    changed["attachments"][0]["content_base64"] = base64.b64encode(b"different PDF").decode("ascii")
    conflict = client.post(
        "/api/v1/integrations/agencies/messages-with-attachments",
        json=changed,
        headers={"X-BDA-Dev-Service": "rsl-simulator"},
    )
    assert conflict.status_code == 409, conflict.text


def test_attachment_forwarding_occurs_only_after_retention(monkeypatch) -> None:
    business, tin = _register()
    business_id = uuid.UUID(business["id"])
    with SessionLocal() as db:
        member = db.scalar(select(BusinessMember).where(BusinessMember.business_id == business_id))
        assert member is not None
        member.auth_user_sub = "development-user"
        member.status = "active"
        db.commit()

    external = client.post(
        f"/api/v1/businesses/{business_id}/external-emails",
        json={"email": f"attachments-{uuid.uuid4().hex[:8]}@example.com", "forward_official_mail": True},
    )
    assert external.status_code == 201, external.text
    verified = client.post(
        f"/api/v1/businesses/{business_id}/external-emails/{external.json()['id']}/verify",
        json={"code": external.json()["verification_code"]},
    )
    assert verified.status_code == 200, verified.text

    binding_id = str(uuid.uuid4())
    with SessionLocal() as db:
        row = db.get(Business, business_id)
        assert row is not None and row.official_address is not None
        row.official_address.platform_binding_id = binding_id
        row.official_address.platform_mailbox_id = str(uuid.uuid4())
        row.official_address.mailbox_status = "active"
        row.official_address.provisioned_at = datetime.now(timezone.utc)
        db.commit()

    reference = f"RSL-ATT-FWD-{uuid.uuid4().hex}"
    calls: list[dict] = []

    def fake_send(client_instance, **kwargs):
        with SessionLocal() as verification_db:
            stored = verification_db.scalar(select(OfficialMessage).where(OfficialMessage.external_message_id == reference))
            assert stored is not None
            attachment = verification_db.scalar(select(MessageAttachment).where(MessageAttachment.message_id == stored.id))
            assert attachment is not None
            official = verification_db.scalar(
                select(MessageDelivery).where(
                    MessageDelivery.message_id == stored.id,
                    MessageDelivery.channel == "official_inbox",
                )
            )
            assert official is not None and official.status == "delivered"
        calls.append(kwargs)
        return MailSendResult(
            delivery_id=str(uuid.uuid4()),
            status="queued",
            provider_message_id="<attachment-queued@example>",
            error=None,
        )

    monkeypatch.setattr("app.official_message_attachments.send_official_copy_with_attachments", fake_send)
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="development",
        ithute_service_client_secret="x" * 32,
        enable_real_mail_forwarding=True,
    )
    try:
        response = client.post(
            "/api/v1/integrations/agencies/messages-with-attachments",
            json=_message_payload(tin, reference),
            headers={"X-BDA-Dev-Service": "rsl-simulator"},
        )
        assert response.status_code == 201, response.text
        assert len(calls) == 1
        assert calls[0]["binding_id"] == binding_id
        assert len(calls[0]["attachments"]) == 1
        assert calls[0]["attachments"][0].filename == "tax-notice.pdf"
        rows = response.json()["message"]["deliveries"]
        assert any(item["channel"] == "external_forward" and item["status"] == "submitted" for item in rows)
    finally:
        app.dependency_overrides.pop(get_settings, None)
