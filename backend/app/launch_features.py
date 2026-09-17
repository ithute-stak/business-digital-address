from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .config import Settings, get_settings
from .db import get_db
from .integration_api import _agency_for_service, _forward_pending_official_copies
from .launch_schemas import (
    AcknowledgementResponse,
    AdminOperationsResponse,
    AttachmentCreate,
    AttachmentResponse,
    DeliveryStatusResponse,
    InboxMessageResponse,
    InboxPageResponse,
    InboxStateResponse,
    InboxStateUpdate,
    MemberRoleUpdate,
    OfficialReceiptResponse,
    ReceiptBusiness,
)
from .models import (
    Agency,
    AuditEvent,
    Business,
    BusinessMember,
    ExternalEmail,
    MessageAcknowledgement,
    MessageAttachment,
    MessageDelivery,
    MessageUserState,
    OfficialAddress,
    OfficialMessage,
    utcnow,
)
from .security import UserPrincipal, require_user
from .service_security import ServicePrincipal, require_service_scope
from .services import create_business_audit


router = APIRouter(tags=["correspondence-suite"])
Db = Annotated[Session, Depends(get_db)]
Principal = Annotated[UserPrincipal, Depends(require_user)]
MessagePrincipal = Annotated[ServicePrincipal, Depends(require_service_scope("official-message.send"))]

_MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
_ALLOWED_ATTACHMENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _member(db: Session, business_id: uuid.UUID, principal: UserPrincipal) -> BusinessMember:
    member = db.scalar(
        select(BusinessMember).where(
            BusinessMember.business_id == business_id,
            BusinessMember.auth_user_sub == principal.sub,
            BusinessMember.status == "active",
        )
    )
    if member is None:
        raise HTTPException(status_code=404, detail="business not found")
    return member


def _require_manager(db: Session, business_id: uuid.UUID, principal: UserPrincipal) -> BusinessMember:
    member = _member(db, business_id, principal)
    if member.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="owner or admin role required")
    return member


def _require_owner(db: Session, business_id: uuid.UUID, principal: UserPrincipal) -> BusinessMember:
    member = _member(db, business_id, principal)
    if member.role != "owner":
        raise HTTPException(status_code=403, detail="owner role required")
    return member


def _business(db: Session, business_id: uuid.UUID, principal: UserPrincipal) -> Business:
    _member(db, business_id, principal)
    business = db.scalar(
        select(Business)
        .options(selectinload(Business.official_address), selectinload(Business.members))
        .where(Business.id == business_id)
    )
    if business is None:
        raise HTTPException(status_code=404, detail="business not found")
    return business


def _message(db: Session, business_id: uuid.UUID, message_id: uuid.UUID) -> OfficialMessage:
    message = db.scalar(
        select(OfficialMessage)
        .options(
            selectinload(OfficialMessage.agency),
            selectinload(OfficialMessage.deliveries),
            selectinload(OfficialMessage.attachments),
            selectinload(OfficialMessage.acknowledgements),
        )
        .where(OfficialMessage.id == message_id, OfficialMessage.business_id == business_id)
    )
    if message is None:
        raise HTTPException(status_code=404, detail="official message not found")
    return message


def _state(db: Session, message_id: uuid.UUID, principal: UserPrincipal) -> MessageUserState | None:
    return db.scalar(
        select(MessageUserState).where(
            MessageUserState.message_id == message_id,
            MessageUserState.auth_user_sub == principal.sub,
        )
    )


def _state_response(state_row: MessageUserState | None) -> InboxStateResponse:
    if state_row is None:
        return InboxStateResponse()
    return InboxStateResponse(
        is_read=state_row.is_read,
        starred=state_row.starred,
        archived=state_row.archived,
        read_at=state_row.read_at,
    )


def _inbox_message(message: OfficialMessage, state_row: MessageUserState | None) -> InboxMessageResponse:
    return InboxMessageResponse(
        id=message.id,
        external_message_id=message.external_message_id,
        agency_code=message.agency.code,
        agency_name=message.agency.name,
        subject=message.subject,
        body_text=message.body_text,
        classification=message.classification,
        status=message.status,
        received_at=message.received_at,
        state=_state_response(state_row),
        attachments=[AttachmentResponse.model_validate(item) for item in message.attachments],
        acknowledgements=[AcknowledgementResponse.model_validate(item) for item in message.acknowledgements],
        deliveries=[DeliveryStatusResponse.model_validate(item) for item in message.deliveries],
    )


@router.get("/api/v1/businesses/{business_id}/inbox", response_model=InboxPageResponse)
def list_inbox(
    business_id: uuid.UUID,
    db: Db,
    principal: Principal,
    q: str | None = Query(default=None, max_length=160),
    agency: str | None = Query(default=None, max_length=64),
    classification: str | None = Query(default=None, max_length=32),
    unread_only: bool = False,
    starred_only: bool = False,
    archived: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> InboxPageResponse:
    _member(db, business_id, principal)
    stmt = (
        select(OfficialMessage)
        .join(Agency, Agency.id == OfficialMessage.agency_id)
        .options(
            selectinload(OfficialMessage.agency),
            selectinload(OfficialMessage.deliveries),
            selectinload(OfficialMessage.attachments),
            selectinload(OfficialMessage.acknowledgements),
        )
        .where(OfficialMessage.business_id == business_id)
        .order_by(OfficialMessage.received_at.desc())
    )
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                OfficialMessage.subject.ilike(pattern),
                OfficialMessage.body_text.ilike(pattern),
                OfficialMessage.external_message_id.ilike(pattern),
                Agency.name.ilike(pattern),
                Agency.code.ilike(pattern),
            )
        )
    if agency and agency.strip():
        stmt = stmt.where(Agency.code == agency.strip().lower())
    if classification and classification.strip():
        stmt = stmt.where(OfficialMessage.classification == classification.strip().lower())

    messages = list(db.scalars(stmt).unique())
    state_rows = list(
        db.scalars(
            select(MessageUserState).where(
                MessageUserState.auth_user_sub == principal.sub,
                MessageUserState.message_id.in_([item.id for item in messages] or [uuid.uuid4()]),
            )
        )
    )
    states = {item.message_id: item for item in state_rows}

    visible: list[OfficialMessage] = []
    for message in messages:
        state_row = states.get(message.id)
        if bool(state_row and state_row.archived) != archived:
            continue
        if unread_only and bool(state_row and state_row.is_read):
            continue
        if starred_only and not bool(state_row and state_row.starred):
            continue
        visible.append(message)

    total = len(visible)
    unread = sum(1 for message in visible if not bool(states.get(message.id) and states[message.id].is_read))
    starred = sum(1 for message in visible if bool(states.get(message.id) and states[message.id].starred))
    page = visible[offset : offset + limit]
    return InboxPageResponse(
        items=[_inbox_message(message, states.get(message.id)) for message in page],
        total=total,
        unread=unread,
        starred=starred,
        limit=limit,
        offset=offset,
    )


@router.patch("/api/v1/businesses/{business_id}/messages/{message_id}/state", response_model=InboxStateResponse)
def update_message_state(
    payload: InboxStateUpdate,
    business_id: uuid.UUID,
    message_id: uuid.UUID,
    db: Db,
    principal: Principal,
) -> InboxStateResponse:
    _member(db, business_id, principal)
    _message(db, business_id, message_id)
    row = _state(db, message_id, principal)
    if row is None:
        row = MessageUserState(message_id=message_id, auth_user_sub=principal.sub)
        db.add(row)
    if payload.is_read is not None:
        row.is_read = payload.is_read
        row.read_at = utcnow() if payload.is_read else None
    if payload.starred is not None:
        row.starred = payload.starred
    if payload.archived is not None:
        row.archived = payload.archived
    db.commit()
    db.refresh(row)
    return _state_response(row)


@router.post(
    "/api/v1/businesses/{business_id}/messages/{message_id}/acknowledgements",
    response_model=AcknowledgementResponse,
    status_code=201,
)
def acknowledge_message(
    business_id: uuid.UUID,
    message_id: uuid.UUID,
    db: Db,
    principal: Principal,
) -> MessageAcknowledgement:
    member = _member(db, business_id, principal)
    _message(db, business_id, message_id)
    existing = db.scalar(
        select(MessageAcknowledgement).where(
            MessageAcknowledgement.message_id == message_id,
            MessageAcknowledgement.member_id == member.id,
        )
    )
    if existing is not None:
        return existing
    row = MessageAcknowledgement(message_id=message_id, member_id=member.id, actor_sub=principal.sub)
    db.add(row)
    create_business_audit(
        db,
        business_id=business_id,
        action="official_message.acknowledged",
        actor_id=principal.sub,
        details={"message_id": str(message_id), "member_id": str(member.id)},
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(MessageAcknowledgement).where(
                MessageAcknowledgement.message_id == message_id,
                MessageAcknowledgement.member_id == member.id,
            )
        )
        if existing is None:
            raise
        return existing
    db.refresh(row)
    return row


@router.get("/api/v1/businesses/{business_id}/messages/{message_id}/receipt", response_model=OfficialReceiptResponse)
def get_official_receipt(
    business_id: uuid.UUID,
    message_id: uuid.UUID,
    db: Db,
    principal: Principal,
) -> OfficialReceiptResponse:
    business = _business(db, business_id, principal)
    message = _message(db, business_id, message_id)
    official = business.official_address.address if business.official_address else None
    fingerprint = hashlib.sha256(f"{message.id}:{message.received_at.isoformat()}".encode()).hexdigest()[:20].upper()
    return OfficialReceiptResponse(
        receipt_id=f"BDA-{fingerprint}",
        message_id=message.id,
        external_message_id=message.external_message_id,
        agency_code=message.agency.code,
        agency_name=message.agency.name,
        subject=message.subject,
        classification=message.classification,
        received_at=message.received_at,
        business=ReceiptBusiness(
            legal_name=business.legal_name,
            trading_name=business.trading_name,
            registration_number=business.registration_number,
            tin=business.tin,
            official_address=official,
        ),
        deliveries=[DeliveryStatusResponse.model_validate(item) for item in message.deliveries],
        acknowledgements=[AcknowledgementResponse.model_validate(item) for item in message.acknowledgements],
        attachment_count=len(message.attachments),
        generated_at=utcnow(),
    )


@router.post(
    "/api/v1/businesses/{business_id}/messages/{message_id}/deliveries/{delivery_id}/retry",
    response_model=DeliveryStatusResponse,
)
def retry_delivery(
    business_id: uuid.UUID,
    message_id: uuid.UUID,
    delivery_id: uuid.UUID,
    db: Db,
    principal: Principal,
    config: Settings = Depends(get_settings),
) -> MessageDelivery:
    _require_manager(db, business_id, principal)
    business = db.scalar(
        select(Business)
        .options(selectinload(Business.official_address), selectinload(Business.external_emails))
        .where(Business.id == business_id)
    )
    message = _message(db, business_id, message_id)
    delivery = db.get(MessageDelivery, delivery_id)
    if delivery is None or delivery.message_id != message_id:
        raise HTTPException(status_code=404, detail="delivery not found")
    if delivery.channel != "external_forward":
        raise HTTPException(status_code=409, detail="only external forwarding deliveries can be retried")
    if delivery.status not in {"failed", "pending_provider"}:
        raise HTTPException(status_code=409, detail="delivery is not retryable")
    if business is None:
        raise HTTPException(status_code=404, detail="business not found")

    delivery.status = "pending_provider"
    delivery.last_error = None
    db.commit()
    _forward_pending_official_copies(
        db,
        business=business,
        agency=message.agency,
        message=message,
        actor_client_id=config.ithute_service_client_id,
        config=config,
    )
    create_business_audit(
        db,
        business_id=business_id,
        action="official_message.forward.retry_requested",
        actor_id=principal.sub,
        details={"message_id": str(message_id), "delivery_id": str(delivery_id)},
    )
    db.commit()
    db.refresh(delivery)
    return delivery


@router.patch("/api/v1/businesses/{business_id}/members/{member_id}/role")
def update_member_role(
    payload: MemberRoleUpdate,
    business_id: uuid.UUID,
    member_id: uuid.UUID,
    db: Db,
    principal: Principal,
) -> dict[str, object]:
    _require_owner(db, business_id, principal)
    target = db.get(BusinessMember, member_id)
    if target is None or target.business_id != business_id:
        raise HTTPException(status_code=404, detail="member not found")
    if target.role == "owner" and payload.role != "owner" and target.status == "active":
        owners = db.scalar(
            select(func.count(BusinessMember.id)).where(
                BusinessMember.business_id == business_id,
                BusinessMember.role == "owner",
                BusinessMember.status == "active",
            )
        ) or 0
        if int(owners) <= 1:
            raise HTTPException(status_code=409, detail="business must retain at least one active owner")
    previous = target.role
    target.role = payload.role
    create_business_audit(
        db,
        business_id=business_id,
        action="member.role.updated",
        actor_id=principal.sub,
        details={"member_id": str(target.id), "previous_role": previous, "role": target.role},
    )
    db.commit()
    return {"id": target.id, "role": target.role, "status": target.status}


@router.post(
    "/api/v1/integrations/agencies/messages/{external_message_id}/attachments",
    response_model=AttachmentResponse,
    status_code=201,
)
def add_agency_attachment(
    external_message_id: str,
    payload: AttachmentCreate,
    db: Db,
    principal: MessagePrincipal,
    config: Settings = Depends(get_settings),
) -> MessageAttachment:
    agency = _agency_for_service(db, principal, config)
    message = db.scalar(
        select(OfficialMessage).where(
            OfficialMessage.agency_id == agency.id,
            OfficialMessage.external_message_id == external_message_id,
        )
    )
    if message is None:
        raise HTTPException(status_code=404, detail="official message not found for this agency")

    filename = payload.filename.strip()
    if not filename or any(value in filename for value in ("/", "\\", "\r", "\n")):
        raise HTTPException(status_code=422, detail="attachment filename is invalid")
    content_type = payload.content_type.strip().lower()
    if content_type not in _ALLOWED_ATTACHMENT_TYPES:
        raise HTTPException(status_code=422, detail="attachment content type is not allowed")
    try:
        content = base64.b64decode(payload.content_base64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="attachment content is not valid base64") from exc
    if not content:
        raise HTTPException(status_code=422, detail="attachment cannot be empty")
    if len(content) > _MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="attachment exceeds 5 MB limit")

    digest = hashlib.sha256(content).hexdigest()
    existing = db.scalar(
        select(MessageAttachment).where(
            MessageAttachment.message_id == message.id,
            MessageAttachment.sha256_hex == digest,
        )
    )
    if existing is not None:
        return existing

    attachment = MessageAttachment(
        message_id=message.id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(content),
        sha256_hex=digest,
        content=content,
    )
    db.add(attachment)
    create_business_audit(
        db,
        business_id=message.business_id,
        action="official_message.attachment.stored",
        actor_id=principal.client_id,
        actor_type="service",
        details={
            "message_id": str(message.id),
            "filename": filename,
            "content_type": content_type,
            "size_bytes": len(content),
            "sha256": digest,
        },
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(MessageAttachment).where(
                MessageAttachment.message_id == message.id,
                MessageAttachment.sha256_hex == digest,
            )
        )
        if existing is None:
            raise
        return existing
    db.refresh(attachment)
    return attachment


@router.get("/api/v1/businesses/{business_id}/messages/{message_id}/attachments/{attachment_id}")
def download_attachment(
    business_id: uuid.UUID,
    message_id: uuid.UUID,
    attachment_id: uuid.UUID,
    db: Db,
    principal: Principal,
) -> Response:
    _member(db, business_id, principal)
    _message(db, business_id, message_id)
    attachment = db.get(MessageAttachment, attachment_id)
    if attachment is None or attachment.message_id != message_id:
        raise HTTPException(status_code=404, detail="attachment not found")
    safe_name = attachment.filename.replace('"', "'")
    return Response(
        content=attachment.content,
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "X-Content-SHA256": attachment.sha256_hex,
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/api/v1/admin/operations", response_model=AdminOperationsResponse)
def admin_operations(db: Db, principal: Principal) -> AdminOperationsResponse:
    if not principal.is_platform_admin:
        raise HTTPException(status_code=403, detail="platform administrator required")
    cutoff = utcnow() - timedelta(hours=24)
    businesses = int(db.scalar(select(func.count(Business.id))) or 0)
    active_addresses = int(
        db.scalar(select(func.count(OfficialAddress.id)).where(OfficialAddress.mailbox_status == "active")) or 0
    )
    pending_mailboxes = int(
        db.scalar(select(func.count(OfficialAddress.id)).where(OfficialAddress.mailbox_status != "active")) or 0
    )
    messages = int(db.scalar(select(func.count(OfficialMessage.id))) or 0)
    messages_24h = int(
        db.scalar(select(func.count(OfficialMessage.id)).where(OfficialMessage.received_at >= cutoff)) or 0
    )
    verified_forwarding = int(
        db.scalar(
            select(func.count(ExternalEmail.id)).where(
                ExternalEmail.status == "verified",
                ExternalEmail.forward_official_mail.is_(True),
            )
        ) or 0
    )
    failures = int(
        db.scalar(
            select(func.count(MessageDelivery.id)).where(
                MessageDelivery.channel == "external_forward",
                MessageDelivery.status == "failed",
            )
        ) or 0
    )
    agencies = int(db.scalar(select(func.count(Agency.id)).where(Agency.status == "active")) or 0)
    acknowledgements = int(db.scalar(select(func.count(MessageAcknowledgement.id))) or 0)
    attachments = int(db.scalar(select(func.count(MessageAttachment.id))) or 0)

    recent_failure_rows = list(
        db.scalars(
            select(MessageDelivery)
            .where(MessageDelivery.channel == "external_forward", MessageDelivery.status == "failed")
            .order_by(MessageDelivery.created_at.desc())
            .limit(10)
        )
    )
    recent_audit_rows = list(db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(20)))
    recent_audit: list[dict[str, object]] = []
    for event in recent_audit_rows:
        try:
            details = json.loads(event.details_json or "{}")
        except json.JSONDecodeError:
            details = {"raw": event.details_json}
        recent_audit.append(
            {
                "id": str(event.id),
                "action": event.action,
                "actor_type": event.actor_type,
                "actor_id": event.actor_id,
                "business_id": str(event.business_id) if event.business_id else None,
                "details": details,
                "created_at": event.created_at.isoformat(),
            }
        )
    return AdminOperationsResponse(
        businesses=businesses,
        active_official_addresses=active_addresses,
        pending_mailboxes=pending_mailboxes,
        official_messages=messages,
        messages_last_24h=messages_24h,
        verified_forwarding_addresses=verified_forwarding,
        forwarding_failures=failures,
        active_agencies=agencies,
        acknowledgements=acknowledgements,
        attachments=attachments,
        recent_failures=[
            {
                "delivery_id": str(item.id),
                "message_id": str(item.message_id),
                "target": item.target,
                "error": item.last_error,
                "created_at": item.created_at.isoformat(),
            }
            for item in recent_failure_rows
        ],
        recent_audit=recent_audit,
    )
