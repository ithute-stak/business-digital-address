from __future__ import annotations

import hashlib
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings, get_settings
from app.db import SessionLocal
from app.ithute import MailSendResult
from app.models import Business, MessageAttachment, MessageDelivery, OfficialMessage
from app.server import app


client = TestClient(app)


def _business_and_message() -> tuple[uuid.UUID, uuid.UUID]:
    suffix = uuid.uuid4().hex[:10].upper()
    tin = f"RETRY-TIN-{suffix}"
    created = client.post(
        "/api/v1/businesses",
        json={
            "registration_number": f"RETRY-REG-{suffix}",
            "tin": tin,
            "legal_name": f"Attachment Retry {suffix}",
        },
    )
    assert created.status_code == 201, created.text
    business_id = uuid.UUID(created.json()["id"])

    agency_code = f"retry-{suffix.lower()}"
    agency = client.post(
        "/api/v1/dev/agencies",
        json={"code": agency_code, "name": "RSL Attachment Retry"},
    )
    assert agency.status_code == 201, agency.text

    delivered = client.post(
        "/api/v1/dev/official-messages",
        json={
            "tin": tin,
            "agency_code": agency_code,
            "external_message_id": f"RETRY-MSG-{suffix}",
            "subject": "Attachment retry test",
            "body_text": "The retained PDF must be present on retry.",
            "classification": "official",
        },
    )
    assert delivered.status_code == 201, delivered.text
    return business_id, uuid.UUID(delivered.json()["id"])


def test_failed_attachment_delivery_retry_reuses_retained_attachment_and_delivery_reference(monkeypatch) -> None:
    business_id, message_id = _business_and_message()
    content = b"%PDF-1.4 retained attachment retry test"
    digest = hashlib.sha256(content).hexdigest()

    with SessionLocal() as db:
        business = db.get(Business, business_id)
        assert business is not None and business.official_address is not None
        business.official_address.platform_binding_id = str(uuid.uuid4())
        business.official_address.platform_mailbox_id = str(uuid.uuid4())
        business.official_address.mailbox_status = "active"

        db.add(
            MessageAttachment(
                message_id=message_id,
                filename="notice.pdf",
                content_type="application/pdf",
                size_bytes=len(content),
                sha256_hex=digest,
                content=content,
            )
        )
        delivery = MessageDelivery(
            message_id=message_id,
            channel="external_forward",
            target="business@example.com",
            status="failed",
            last_error="temporary provider failure",
        )
        db.add(delivery)
        db.commit()
        db.refresh(delivery)
        delivery_id = delivery.id

    calls: list[dict] = []

    def fake_send(client_instance, **kwargs):
        calls.append(kwargs)
        assert kwargs["external_reference"] == f"message-delivery:{delivery_id}"
        assert kwargs["recipient"] == "business@example.com"
        assert len(kwargs["attachments"]) == 1
        attachment = kwargs["attachments"][0]
        assert attachment.filename == "notice.pdf"
        assert attachment.content == content
        assert attachment.sha256_hex == digest
        return MailSendResult(
            delivery_id=str(uuid.uuid4()),
            status="queued",
            provider_message_id="<attachment-retry@example>",
            error=None,
        )

    monkeypatch.setattr("app.retry_api.send_official_copy_with_attachments", fake_send)
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="development",
        ithute_service_client_secret="x" * 32,
        enable_real_mail_forwarding=True,
    )
    try:
        response = client.post(
            f"/api/v1/businesses/{business_id}/messages/{message_id}/deliveries/{delivery_id}/retry"
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "submitted"
        assert response.json()["last_error"] is None
        assert len(calls) == 1

        with SessionLocal() as db:
            stored = db.get(MessageDelivery, delivery_id)
            assert stored is not None
            assert stored.status == "submitted"
            assert stored.provider_reference == "<attachment-retry@example>"
            message = db.scalar(select(OfficialMessage).where(OfficialMessage.id == message_id))
            assert message is not None
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_retry_route_is_exposed_once() -> None:
    path = "/api/v1/businesses/{business_id}/messages/{message_id}/deliveries/{delivery_id}/retry"
    matches = [
        route
        for route in app.routes
        if getattr(route, "path", None) == path and "POST" in (getattr(route, "methods", set()) or set())
    ]
    assert len(matches) == 1
