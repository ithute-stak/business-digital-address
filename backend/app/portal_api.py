from __future__ import annotations

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .db import get_db
from .ithute import IthutePlatformClient, IthutePlatformError
from .mail_forwarding import sync_inbound_forwarding
from .models import AuditEvent, Business, BusinessMember, ExternalEmail, OfficialMessage
from .portal_schemas import (
    ExternalEmailUpdate,
    MemberInviteRequest,
    PortalAuditResponse,
    PortalExternalEmailResponse,
    PortalMemberResponse,
    PortalMessageResponse,
    PortalSnapshot,
    PortalSummary,
)
from .schemas import BusinessResponse, DeliveryResponse
from .security import UserPrincipal, require_user
from .services import create_business_audit


router = APIRouter(prefix="/api/v1", tags=["business-portal"])
Db = Annotated[Session, Depends(get_db)]
Principal = Annotated[UserPrincipal, Depends(require_user)]


def _business_query():
    return select(Business).options(
        selectinload(Business.official_address),
        selectinload(Business.members),
        selectinload(Business.external_emails),
    )


def _current_member(db: Session, business_id: uuid.UUID, principal: UserPrincipal) -> BusinessMember:
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


def _business_for_user(db: Session, business_id: uuid.UUID, principal: UserPrincipal) -> Business:
    _current_member(db, business_id, principal)
    business = db.scalars(_business_query().where(Business.id == business_id)).unique().first()
    if business is None:
        raise HTTPException(status_code=404, detail="business not found")
    return business


def _require_manager(db: Session, business_id: uuid.UUID, principal: UserPrincipal) -> BusinessMember:
    member = _current_member(db, business_id, principal)
    if member.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="owner or admin role required")
    return member


def _messages(db: Session, business_id: uuid.UUID) -> list[OfficialMessage]:
    return list(
        db.scalars(
            select(OfficialMessage)
            .options(selectinload(OfficialMessage.agency), selectinload(OfficialMessage.deliveries))
            .where(OfficialMessage.business_id == business_id)
            .order_by(OfficialMessage.received_at.desc())
        )
    )


def _audit(db: Session, business_id: uuid.UUID, limit: int = 100) -> list[AuditEvent]:
    return list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.business_id == business_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        )
    )


def _message_response(message: OfficialMessage) -> PortalMessageResponse:
    return PortalMessageResponse(
        id=message.id,
        external_message_id=message.external_message_id,
        agency_code=message.agency.code,
        agency_name=message.agency.name,
        subject=message.subject,
        body_text=message.body_text,
        classification=message.classification,
        status=message.status,
        received_at=message.received_at,
        deliveries=[DeliveryResponse.model_validate(item) for item in message.deliveries],
    )


def _audit_response(event: AuditEvent) -> PortalAuditResponse:
    try:
        details = json.loads(event.details_json or "{}")
    except json.JSONDecodeError:
        details = {"raw": event.details_json}
    if not isinstance(details, dict):
        details = {"value": details}
    return PortalAuditResponse(
        id=event.id,
        actor_type=event.actor_type,
        actor_id=event.actor_id,
        action=event.action,
        details=details,
        created_at=event.created_at,
    )


def _snapshot(db: Session, business: Business) -> PortalSnapshot:
    messages = _messages(db, business.id)
    audit = _audit(db, business.id)
    members = sorted(business.members, key=lambda item: item.created_at)
    external = sorted(business.external_emails, key=lambda item: item.created_at)
    pending_actions = 0
    if business.official_address is None or business.official_address.mailbox_status != "active":
        pending_actions += 1
    pending_actions += sum(1 for member in members if member.status != "active")
    pending_actions += sum(1 for item in external if item.status != "verified")
    pending_actions += sum(
        1
        for message in messages
        for delivery in message.deliveries
        if delivery.status in {"pending", "pending_provider", "failed"}
    )
    return PortalSnapshot(
        business=BusinessResponse.model_validate(business),
        summary=PortalSummary(
            official_messages=len(messages),
            authorised_members=sum(1 for member in members if member.status == "active"),
            verified_external_emails=sum(1 for item in external if item.status == "verified"),
            pending_actions=pending_actions,
        ),
        members=[PortalMemberResponse.model_validate(member) for member in members],
        external_emails=[PortalExternalEmailResponse.model_validate(item) for item in external],
        messages=[_message_response(message) for message in messages],
        audit=[_audit_response(event) for event in audit],
    )


@router.get("/businesses/{business_id}/portal", response_model=PortalSnapshot)
def get_portal_snapshot(business_id: uuid.UUID, db: Db, principal: Principal) -> PortalSnapshot:
    business = _business_for_user(db, business_id, principal)
    return _snapshot(db, business)


@router.get("/businesses/{business_id}/members", response_model=list[PortalMemberResponse])
def list_members(business_id: uuid.UUID, db: Db, principal: Principal) -> list[BusinessMember]:
    business = _business_for_user(db, business_id, principal)
    return sorted(business.members, key=lambda item: item.created_at)


@router.post("/businesses/{business_id}/members", response_model=PortalMemberResponse, status_code=201)
def invite_member(
    payload: MemberInviteRequest,
    business_id: uuid.UUID,
    db: Db,
    principal: Principal,
) -> BusinessMember:
    _require_manager(db, business_id, principal)
    business = _business_for_user(db, business_id, principal)
    email = str(payload.email).strip().lower() if payload.email else None
    phone = payload.phone.strip() if payload.phone else None
    if email:
        existing = db.scalar(
            select(BusinessMember).where(
                BusinessMember.business_id == business_id,
                BusinessMember.invited_email == email,
                BusinessMember.status.in_(["pending_platform", "invited", "active"]),
            )
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="this email is already associated with the business")
    if phone:
        existing = db.scalar(
            select(BusinessMember).where(
                BusinessMember.business_id == business_id,
                BusinessMember.invited_phone == phone,
                BusinessMember.status.in_(["pending_platform", "invited", "active"]),
            )
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="this phone is already associated with the business")

    member = BusinessMember(
        business_id=business_id,
        role=payload.role,
        status="pending_platform",
        invited_email=email,
        invited_phone=phone,
    )
    db.add(member)
    db.flush()
    create_business_audit(
        db,
        business_id=business_id,
        action="member.invitation.started",
        actor_id=principal.sub,
        details={"member_id": str(member.id), "role": payload.role, "channel": payload.preferred_channel},
    )
    db.commit()
    db.refresh(member)

    config = get_settings()
    if not config.ithute_service_client_secret:
        return member
    try:
        result = IthutePlatformClient(config).invite_identity(
            external_reference=f"business-member:{member.id}",
            display_name=payload.display_name.strip(),
            preferred_channel=payload.preferred_channel,
            email=email,
            phone=phone,
        )
    except IthutePlatformError as exc:
        member.status = "invite_failed"
        create_business_audit(
            db,
            business_id=business_id,
            action="member.invitation.failed",
            actor_id=config.ithute_service_client_id,
            actor_type="service",
            details={"member_id": str(member.id), "error": str(exc)},
        )
    else:
        member.status = "invited"
        member.invitation_id = str(result["id"])
        create_business_audit(
            db,
            business_id=business_id,
            action="member.invitation.created",
            actor_id=config.ithute_service_client_id,
            actor_type="service",
            details={"member_id": str(member.id), "invitation_id": member.invitation_id},
        )
    db.commit()
    db.refresh(member)
    return member


@router.get("/businesses/{business_id}/external-emails", response_model=list[PortalExternalEmailResponse])
def list_external_emails(business_id: uuid.UUID, db: Db, principal: Principal) -> list[ExternalEmail]:
    business = _business_for_user(db, business_id, principal)
    return sorted(business.external_emails, key=lambda item: item.created_at)


@router.patch(
    "/businesses/{business_id}/external-emails/{email_id}",
    response_model=PortalExternalEmailResponse,
)
def update_external_email(
    payload: ExternalEmailUpdate,
    business_id: uuid.UUID,
    email_id: uuid.UUID,
    db: Db,
    principal: Principal,
) -> ExternalEmail:
    _require_manager(db, business_id, principal)
    business = _business_for_user(db, business_id, principal)
    item = db.get(ExternalEmail, email_id)
    if item is None or item.business_id != business_id:
        raise HTTPException(status_code=404, detail="external email not found")
    if payload.forward_official_mail and item.status != "verified":
        raise HTTPException(status_code=409, detail="external email must be verified before forwarding can be enabled")

    previous = item.forward_official_mail
    item.forward_official_mail = payload.forward_official_mail
    create_business_audit(
        db,
        business_id=business_id,
        action="external_email.forwarding.updated",
        actor_id=principal.sub,
        details={"email": item.email, "enabled": item.forward_official_mail, "mode": "all-inbound-copy"},
    )
    db.commit()
    db.refresh(item)

    config = get_settings()
    try:
        sync_inbound_forwarding(
            db,
            business,
            actor_id=principal.sub,
            strict=config.environment.lower() == "production",
        )
    except IthutePlatformError as exc:
        item.forward_official_mail = previous
        db.commit()
        create_business_audit(
            db,
            business_id=business_id,
            action="external_email.forwarding.sync_failed",
            actor_id=config.ithute_service_client_id,
            actor_type="service",
            details={"email": item.email, "error": str(exc)},
        )
        db.commit()
        if config.environment.lower() == "production":
            raise HTTPException(status_code=502, detail="inbound forwarding could not be synchronized") from exc
    db.refresh(item)
    return item


@router.delete("/businesses/{business_id}/external-emails/{email_id}", status_code=204)
def delete_external_email(
    business_id: uuid.UUID,
    email_id: uuid.UUID,
    db: Db,
    principal: Principal,
) -> Response:
    _require_manager(db, business_id, principal)
    business = _business_for_user(db, business_id, principal)
    item = db.get(ExternalEmail, email_id)
    if item is None or item.business_id != business_id:
        raise HTTPException(status_code=404, detail="external email not found")
    email = item.email

    if item.forward_official_mail:
        item.forward_official_mail = False
        db.commit()
        config = get_settings()
        try:
            sync_inbound_forwarding(
                db,
                business,
                actor_id=principal.sub,
                strict=config.environment.lower() == "production",
            )
        except IthutePlatformError as exc:
            item.forward_official_mail = True
            db.commit()
            if config.environment.lower() == "production":
                raise HTTPException(status_code=502, detail="forwarding could not be removed safely") from exc

    db.delete(item)
    create_business_audit(
        db,
        business_id=business_id,
        action="external_email.removed",
        actor_id=principal.sub,
        details={"email": email},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/businesses/{business_id}/audit", response_model=list[PortalAuditResponse])
def list_audit(business_id: uuid.UUID, db: Db, principal: Principal) -> list[PortalAuditResponse]:
    _business_for_user(db, business_id, principal)
    return [_audit_response(event) for event in _audit(db, business_id)]