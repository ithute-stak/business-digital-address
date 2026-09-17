from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .attachment_mail import send_official_copy_with_attachments
from .config import Settings, get_settings
from .db import get_db
from .integration_api import _forward_pending_official_copies
from .ithute import IthutePlatformClient, IthutePlatformError
from .launch_schemas import DeliveryStatusResponse
from .models import Business, BusinessMember, MessageDelivery, OfficialMessage, utcnow
from .security import UserPrincipal, require_user
from .services import create_business_audit


router = APIRouter(tags=["correspondence-suite"])
Db = Annotated[Session, Depends(get_db)]
Principal = Annotated[UserPrincipal, Depends(require_user)]


def _require_manager(db: Session, business_id: uuid.UUID, principal: UserPrincipal) -> BusinessMember:
    member = db.scalar(
        select(BusinessMember).where(
            BusinessMember.business_id == business_id,
            BusinessMember.auth_user_sub == principal.sub,
            BusinessMember.status == "active",
        )
    )
    if member is None:
        raise HTTPException(status_code=404, detail="business not found")
    if member.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="owner or admin role required")
    return member


def _attachment_forward_text(message: OfficialMessage, business: Business) -> str:
    official = business.official_address
    return (
        "This is a forwarded copy of an official communication retained in your "
        "Business Digital Address official inbox.\n\n"
        f"Agency: {message.agency.name}\n"
        f"Official reference: {message.external_message_id}\n"
        f"Official inbox address: {official.address if official else 'unavailable'}\n"
        f"Attachments: {len(message.attachments)}\n\n"
        f"{message.body_text}"
    )


def _retry_attachment_delivery(
    db: Session,
    *,
    business: Business,
    message: OfficialMessage,
    delivery: MessageDelivery,
    config: Settings,
) -> None:
    """Retry exactly one attachment-bearing delivery using its original idempotency key."""

    if not config.enable_real_mail_forwarding:
        delivery.last_error = "real external mail forwarding is disabled"
        return

    official = business.official_address
    if not config.ithute_service_client_secret:
        delivery.last_error = "Business Digital Address Ithute service credential is not configured"
        return
    if official is None or not official.platform_binding_id or official.mailbox_status != "active":
        delivery.last_error = "official Ithute mailbox is not active"
        return

    try:
        result = send_official_copy_with_attachments(
            IthutePlatformClient(config),
            binding_id=official.platform_binding_id,
            external_reference=f"message-delivery:{delivery.id}",
            recipient=delivery.target,
            subject=message.subject,
            text=_attachment_forward_text(message, business),
            attachments=list(message.attachments),
        )
    except IthutePlatformError as exc:
        # Keep the same external reference and the delivery retryable. Never
        # generate a new provider key merely because the previous response was
        # lost: doing so could create duplicate official correspondence.
        delivery.last_error = str(exc)[:255]
        return

    delivery.provider_reference = result.provider_message_id or result.delivery_id
    delivery.last_error = result.error[:255] if result.error else None
    if result.status == "failed":
        delivery.status = "failed"
    elif result.status == "delivered":
        delivery.status = "delivered"
        delivery.delivered_at = utcnow()
    elif result.status == "queued":
        delivery.status = "submitted"
    else:
        delivery.status = "pending_provider"


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
    if business is None:
        raise HTTPException(status_code=404, detail="business not found")

    message = db.scalar(
        select(OfficialMessage)
        .options(
            selectinload(OfficialMessage.agency),
            selectinload(OfficialMessage.deliveries),
            selectinload(OfficialMessage.attachments),
        )
        .where(OfficialMessage.id == message_id, OfficialMessage.business_id == business_id)
    )
    if message is None:
        raise HTTPException(status_code=404, detail="official message not found")

    delivery = db.get(MessageDelivery, delivery_id)
    if delivery is None or delivery.message_id != message_id:
        raise HTTPException(status_code=404, detail="delivery not found")
    if delivery.channel != "external_forward":
        raise HTTPException(status_code=409, detail="only external forwarding deliveries can be retried")
    if delivery.status not in {"failed", "pending_provider"}:
        raise HTTPException(status_code=409, detail="delivery is not retryable")

    delivery.status = "pending_provider"
    delivery.last_error = None
    db.commit()

    if message.attachments:
        _retry_attachment_delivery(
            db,
            business=business,
            message=message,
            delivery=delivery,
            config=config,
        )
    else:
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
        details={
            "message_id": str(message_id),
            "delivery_id": str(delivery_id),
            "attachment_count": len(message.attachments),
        },
    )
    db.commit()
    db.refresh(delivery)
    return delivery
