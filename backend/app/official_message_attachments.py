from __future__ import annotations

import base64
import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .attachment_mail import send_official_copy_with_attachments
from .config import Settings, get_settings
from .db import get_db
from .integration_api import _agency_for_service, _business_query
from .ithute import IthutePlatformClient, IthutePlatformError
from .launch_schemas import AttachmentCreate
from .models import Business, MessageAttachment, MessageDelivery, OfficialMessage, utcnow
from .schemas import OfficialMessageResponse
from .service_security import ServicePrincipal, require_service_scope
from .services import create_business_audit, normalize_identifier

router = APIRouter(prefix="/api/v1/integrations", tags=["service-integrations"])
Db = Annotated[Session, Depends(get_db)]
MessagePrincipal = Annotated[ServicePrincipal, Depends(require_service_scope("official-message.send"))]

_ALLOWED = {
    "application/pdf", "image/jpeg", "image/png", "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

class AgencyMessageAttachmentsRequest(BaseModel):
    tin: str = Field(min_length=1, max_length=80)
    external_message_id: str = Field(min_length=1, max_length=160)
    subject: str = Field(min_length=1, max_length=240)
    body_text: str = Field(min_length=1, max_length=100000)
    classification: str = Field(default="official", min_length=1, max_length=32)
    attachments: list[AttachmentCreate] = Field(min_length=1, max_length=10)

class AgencyMessageAttachmentsResponse(BaseModel):
    message: OfficialMessageResponse
    delivery_status: str
    attachment_count: int


def _decode(items: list[AttachmentCreate]) -> list[tuple[str, str, bytes, str]]:
    decoded = []
    total = 0
    for item in items:
        filename = item.filename.strip()
        if not filename or filename in {".", ".."} or any(x in filename for x in ("/", "\\", "\r", "\n")):
            raise HTTPException(status_code=422, detail="attachment filename is invalid")
        content_type = item.content_type.strip().lower()
        if content_type not in _ALLOWED:
            raise HTTPException(status_code=422, detail="attachment content type is not allowed")
        try:
            content = base64.b64decode(item.content_base64, validate=True)
        except Exception as exc:
            raise HTTPException(status_code=422, detail="attachment content is not valid base64") from exc
        if not content:
            raise HTTPException(status_code=422, detail="attachment cannot be empty")
        if len(content) > 5 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="attachment exceeds 5 MB limit")
        total += len(content)
        if total > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="attachments exceed 10 MB total limit")
        decoded.append((filename, content_type, content, hashlib.sha256(content).hexdigest()))
    return decoded


def _query():
    return select(OfficialMessage).options(selectinload(OfficialMessage.deliveries), selectinload(OfficialMessage.attachments))


def _forward(db: Session, business: Business, message: OfficialMessage, agency_name: str, actor: str, config: Settings) -> None:
    if not config.enable_real_mail_forwarding:
        return
    pending = [d for d in message.deliveries if d.channel == "external_forward" and d.status == "pending_provider"]
    if not pending:
        return
    official = business.official_address
    if not config.ithute_service_client_secret or official is None or not official.platform_binding_id or official.mailbox_status != "active":
        reason = "official Ithute mailbox or managed credential is not active"
        for delivery in pending:
            delivery.last_error = reason
        db.commit()
        return
    text = (
        "This is a forwarded copy of an official communication retained in your Business Digital Address official inbox.\n\n"
        f"Agency: {agency_name}\nOfficial reference: {message.external_message_id}\n"
        f"Official inbox address: {official.address}\nAttachments: {len(message.attachments)}\n\n{message.body_text}"
    )
    client = IthutePlatformClient(config)
    for delivery in pending:
        try:
            result = send_official_copy_with_attachments(
                client, binding_id=official.platform_binding_id,
                external_reference=f"message-delivery:{delivery.id}", recipient=delivery.target,
                subject=message.subject, text=text, attachments=list(message.attachments),
            )
        except IthutePlatformError as exc:
            delivery.last_error = str(exc)[:255]
            continue
        delivery.provider_reference = result.provider_message_id or result.delivery_id
        delivery.last_error = result.error[:255] if result.error else None
        if result.status == "failed":
            delivery.status = "failed"
        elif result.status == "delivered":
            delivery.status = "delivered"; delivery.delivered_at = utcnow()
        elif result.status == "queued":
            delivery.status = "submitted"
        else:
            delivery.status = "pending_provider"
    create_business_audit(db, business_id=business.id, action="official_message.attachments.forwarded", actor_id=actor, actor_type="service", details={"message_id": str(message.id), "attachment_count": len(message.attachments)})
    db.commit()


@router.post("/agencies/messages-with-attachments", response_model=AgencyMessageAttachmentsResponse, status_code=201)
def deliver_message_with_attachments(payload: AgencyMessageAttachmentsRequest, db: Db, principal: MessagePrincipal, config: Settings = Depends(get_settings)) -> AgencyMessageAttachmentsResponse:
    agency = _agency_for_service(db, principal, config)
    business = db.scalar(_business_query().where(Business.tin == normalize_identifier(payload.tin)))
    if business is None or business.official_address is None:
        raise HTTPException(status_code=404, detail="business/TIN not found")
    decoded = _decode(payload.attachments)
    existing = db.scalar(_query().where(OfficialMessage.agency_id == agency.id, OfficialMessage.external_message_id == payload.external_message_id))
    manifest = sorted((a, b, len(c), d) for a, b, c, d in decoded)
    if existing is not None:
        existing_manifest = sorted((a.filename, a.content_type, a.size_bytes, a.sha256_hex) for a in existing.attachments)
        same = existing.business_id == business.id and existing.subject == payload.subject and existing.body_text == payload.body_text and existing.classification == payload.classification and existing_manifest == manifest
        if not same:
            raise HTTPException(status_code=409, detail="external message ID was already used for different content")
        _forward(db, business, existing, agency.name, principal.client_id, config)
        return AgencyMessageAttachmentsResponse(message=OfficialMessageResponse.model_validate(existing), delivery_status="existing", attachment_count=len(existing.attachments))

    message = OfficialMessage(business_id=business.id, agency_id=agency.id, external_message_id=payload.external_message_id, subject=payload.subject, body_text=payload.body_text, classification=payload.classification, status="stored")
    db.add(message); db.flush()
    for filename, content_type, content, digest in decoded:
        db.add(MessageAttachment(message_id=message.id, filename=filename, content_type=content_type, size_bytes=len(content), sha256_hex=digest, content=content))
    db.add(MessageDelivery(message_id=message.id, channel="official_inbox", target=business.official_address.address, status="delivered", delivered_at=utcnow()))
    for external in business.external_emails:
        if external.status == "verified" and external.forward_official_mail:
            db.add(MessageDelivery(message_id=message.id, channel="external_forward", target=external.email, status="pending_provider"))
    create_business_audit(db, business_id=business.id, action="official_message.stored", actor_id=principal.client_id, actor_type="service", details={"agency": agency.code, "external_message_id": payload.external_message_id, "attachment_count": len(decoded), "attachment_sha256": [d for _, _, _, d in decoded]})
    db.commit()
    stored = db.scalar(_query().where(OfficialMessage.id == message.id)) or message
    _forward(db, business, stored, agency.name, principal.client_id, config)
    return AgencyMessageAttachmentsResponse(message=OfficialMessageResponse.model_validate(stored), delivery_status="stored", attachment_count=len(stored.attachments))
