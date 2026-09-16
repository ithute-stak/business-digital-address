from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .config import Settings, get_settings
from .db import get_db
from .integration_schemas import (
    AgencyOfficialMessageRequest,
    AgencyOfficialMessageResponse,
    TradeBusinessRegistrationRequest,
    TradeBusinessRegistrationResponse,
)
from .ithute import IthutePlatformClient, IthutePlatformError
from .models import (
    Agency,
    Business,
    BusinessMember,
    MessageDelivery,
    OfficialMessage,
    utcnow,
)
from .platform_config import get_platform_configuration
from .schemas import BusinessResponse, OfficialMessageResponse, OwnerInvite
from .service_security import ServicePrincipal, require_service_scope
from .services import (
    business_external_reference,
    create_business_audit,
    ensure_official_address,
    normalize_identifier,
)


router = APIRouter(prefix="/api/v1/integrations", tags=["service-integrations"])
Db = Annotated[Session, Depends(get_db)]
TradePrincipal = Annotated[ServicePrincipal, Depends(require_service_scope("business.register"))]
MessagePrincipal = Annotated[ServicePrincipal, Depends(require_service_scope("official-message.send"))]


def _business_query():
    return select(Business).options(
        selectinload(Business.official_address),
        selectinload(Business.members),
        selectinload(Business.external_emails),
    )


def _message_query():
    return select(OfficialMessage).options(selectinload(OfficialMessage.deliveries))


def _owner_status(business: Business) -> str | None:
    invited = [member for member in business.members if member.auth_user_sub is None]
    if not invited:
        return None
    invited.sort(key=lambda member: member.created_at, reverse=True)
    return invited[0].status


def _invite_owner(
    db: Session,
    *,
    business: Business,
    member: BusinessMember,
    owner: OwnerInvite,
    actor_client_id: str,
    config: Settings,
) -> None:
    if not config.ithute_service_client_secret:
        member.status = "pending_platform"
        create_business_audit(
            db,
            business_id=business.id,
            action="owner.invitation.deferred",
            actor_id=actor_client_id,
            actor_type="service",
            details={"reason": "Business Digital Address Ithute service credential is not configured"},
        )
        db.commit()
        return

    try:
        result = IthutePlatformClient(config).invite_identity(
            external_reference=f"trade-owner:{business.id}:{member.id}",
            display_name=owner.display_name,
            preferred_channel=owner.preferred_channel,
            email=str(owner.email) if owner.email else None,
            phone=owner.phone,
        )
    except IthutePlatformError as exc:
        member.status = "invite_failed"
        create_business_audit(
            db,
            business_id=business.id,
            action="owner.invitation.failed",
            actor_id=actor_client_id,
            actor_type="service",
            details={"error": str(exc)},
        )
    else:
        member.invitation_id = str(result["id"])
        member.status = "invited"
        create_business_audit(
            db,
            business_id=business.id,
            action="owner.invitation.created",
            actor_id=actor_client_id,
            actor_type="service",
            details={
                "invitation_id": member.invitation_id,
                "delivery_status": result.get("delivery_status"),
                "existing_identity": result.get("existing_identity"),
            },
        )
    db.commit()


def _maybe_provision_official_mailbox(
    db: Session,
    *,
    business: Business,
    actor_client_id: str,
    config: Settings,
) -> None:
    if not config.enable_real_mail_provisioning:
        return
    official = business.official_address
    if official is None or (official.platform_binding_id and official.mailbox_status == "active"):
        return
    if not config.ithute_service_client_secret:
        create_business_audit(
            db,
            business_id=business.id,
            action="official_address.provision.deferred",
            actor_id=actor_client_id,
            actor_type="service",
            details={"reason": "Business Digital Address Ithute service credential is not configured"},
        )
        db.commit()
        return

    official.mailbox_status = "provisioning"
    db.commit()
    try:
        result = IthutePlatformClient(config).provision_mailbox(
            external_reference=business_external_reference(business),
            domain_name=official.domain,
            local_part=official.local_part,
            display_name=business.legal_name,
        )
    except IthutePlatformError as exc:
        official.mailbox_status = "provision_failed"
        create_business_audit(
            db,
            business_id=business.id,
            action="official_address.provision.failed",
            actor_id=actor_client_id,
            actor_type="service",
            details={"address": official.address, "error": str(exc)},
        )
    else:
        official.platform_binding_id = result.binding_id
        official.platform_mailbox_id = result.mailbox_id
        official.address = result.address
        official.mailbox_status = result.status
        official.provisioned_at = utcnow()
        create_business_audit(
            db,
            business_id=business.id,
            action="official_address.provisioned",
            actor_id=actor_client_id,
            actor_type="service",
            details={"address": result.address, "binding_id": result.binding_id},
        )
    db.commit()


def _forward_pending_official_copies(
    db: Session,
    *,
    business: Business,
    agency: Agency,
    message: OfficialMessage,
    actor_client_id: str,
    config: Settings,
) -> None:
    """Best-effort forward after the official inbox copy is already committed."""

    if not config.enable_real_mail_forwarding:
        return

    pending = [
        delivery
        for delivery in message.deliveries
        if delivery.channel == "external_forward" and delivery.status == "pending_provider"
    ]
    if not pending:
        return

    official = business.official_address
    deferred_reason: str | None = None
    if not config.ithute_service_client_secret:
        deferred_reason = "Business Digital Address Ithute service credential is not configured"
    elif official is None or not official.platform_binding_id or official.mailbox_status != "active":
        deferred_reason = "official Ithute mailbox is not active"

    if deferred_reason:
        for delivery in pending:
            delivery.last_error = deferred_reason
        create_business_audit(
            db,
            business_id=business.id,
            action="official_message.forward.deferred",
            actor_id=actor_client_id,
            actor_type="service",
            details={"message_id": str(message.id), "reason": deferred_reason, "pending": len(pending)},
        )
        db.commit()
        return

    forward_text = (
        "This is a forwarded copy of an official communication retained in your "
        "Business Digital Address official inbox.\n\n"
        f"Agency: {agency.name}\n"
        f"Official reference: {message.external_message_id}\n"
        f"Official inbox address: {official.address}\n\n"
        f"{message.body_text}"
    )
    client = IthutePlatformClient(config)
    for delivery in pending:
        try:
            result = client.send_official_copy(
                binding_id=official.platform_binding_id,
                external_reference=f"message-delivery:{delivery.id}",
                recipient=delivery.target,
                subject=message.subject,
                text=forward_text,
            )
        except IthutePlatformError as exc:
            # Keep this retryable. The Ithute-side external reference is
            # idempotent, so replaying the agency message later cannot blindly
            # create a duplicate if the first HTTP response was lost.
            delivery.last_error = str(exc)[:255]
            create_business_audit(
                db,
                business_id=business.id,
                action="official_message.forward.deferred",
                actor_id=actor_client_id,
                actor_type="service",
                details={"delivery_id": str(delivery.id), "target": delivery.target, "error": str(exc)},
            )
            continue

        delivery.provider_reference = result.provider_message_id or result.delivery_id
        delivery.last_error = result.error[:255] if result.error else None
        if result.status == "failed":
            delivery.status = "failed"
            action = "official_message.forward.failed"
        elif result.status == "delivered":
            delivery.status = "delivered"
            delivery.delivered_at = utcnow()
            action = "official_message.forward.delivered"
        elif result.status == "queued":
            delivery.status = "submitted"
            action = "official_message.forward.submitted"
        else:
            # `submitting` can be returned when Ithute has a durable idempotency
            # reservation but the final SMTP result is not yet known. Do not
            # claim delivery or submit another copy.
            delivery.status = "pending_provider"
            action = "official_message.forward.pending"

        create_business_audit(
            db,
            business_id=business.id,
            action=action,
            actor_id=actor_client_id,
            actor_type="service",
            details={
                "delivery_id": str(delivery.id),
                "target": delivery.target,
                "platform_delivery_id": result.delivery_id,
                "provider_message_id": result.provider_message_id,
                "platform_status": result.status,
            },
        )
    db.commit()


@router.post("/trade/businesses", response_model=TradeBusinessRegistrationResponse, status_code=201)
def register_business_from_trade(
    payload: TradeBusinessRegistrationRequest,
    db: Db,
    principal: TradePrincipal,
    config: Settings = Depends(get_settings),
) -> TradeBusinessRegistrationResponse:
    registration_number = normalize_identifier(payload.registration_number)
    tin = normalize_identifier(payload.tin)
    legal_name = payload.legal_name.strip()
    trading_name = payload.trading_name.strip() if payload.trading_name else None

    existing = db.scalar(
        _business_query().where(
            or_(Business.registration_number == registration_number, Business.tin == tin)
        )
    )
    if existing is not None:
        if existing.registration_number != registration_number or existing.tin != tin:
            raise HTTPException(status_code=409, detail="registration number or TIN is already bound to another business")
        if existing.legal_name != legal_name or (existing.trading_name or None) != trading_name:
            raise HTTPException(status_code=409, detail="replayed registration data differs from the existing business")
        return TradeBusinessRegistrationResponse(
            business=BusinessResponse.model_validate(existing),
            registration_status="existing",
            owner_invitation_status=_owner_status(existing),
        )

    business = Business(
        registration_number=registration_number,
        tin=tin,
        legal_name=legal_name,
        trading_name=trading_name,
    )
    db.add(business)
    invited_member: BusinessMember | None = None
    try:
        db.flush()
        runtime = get_platform_configuration(db)
        ensure_official_address(business, domain=runtime.official_email_domain)
        if payload.owner is not None:
            invited_member = BusinessMember(
                business_id=business.id,
                role="owner",
                status="pending_platform",
                invited_email=str(payload.owner.email) if payload.owner.email else None,
                invited_phone=payload.owner.phone,
            )
            db.add(invited_member)
            db.flush()
        create_business_audit(
            db,
            business_id=business.id,
            action="trade.business.registered",
            actor_id=principal.client_id,
            actor_type="service",
            details={
                "source_reference": payload.source_reference,
                "registration_number": registration_number,
                "tin": tin,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        race = db.scalar(
            _business_query().where(
                Business.registration_number == registration_number,
                Business.tin == tin,
            )
        )
        if race is None:
            raise HTTPException(status_code=409, detail="business registration conflicts with an existing record") from exc
        return TradeBusinessRegistrationResponse(
            business=BusinessResponse.model_validate(race),
            registration_status="existing",
            owner_invitation_status=_owner_status(race),
        )

    business = db.scalar(_business_query().where(Business.id == business.id)) or business
    if payload.owner is not None and invited_member is not None:
        _invite_owner(
            db,
            business=business,
            member=invited_member,
            owner=payload.owner,
            actor_client_id=principal.client_id,
            config=config,
        )
        business = db.scalar(_business_query().where(Business.id == business.id)) or business

    _maybe_provision_official_mailbox(
        db,
        business=business,
        actor_client_id=principal.client_id,
        config=config,
    )
    business = db.scalar(_business_query().where(Business.id == business.id)) or business
    return TradeBusinessRegistrationResponse(
        business=BusinessResponse.model_validate(business),
        registration_status="created",
        owner_invitation_status=_owner_status(business),
    )


def _agency_for_service(db: Session, principal: ServicePrincipal, config: Settings) -> Agency:
    binding = config.agency_service_bindings.get(principal.client_id)
    if binding is None:
        raise HTTPException(status_code=403, detail="service identity is not bound to an agency")

    agency = db.scalar(select(Agency).where(Agency.code == binding["code"]))
    if agency is None:
        agency = Agency(code=binding["code"], name=binding["name"], status="active")
        db.add(agency)
        create_business_audit(
            db,
            business_id=None,
            action="agency.bound",
            actor_id=principal.client_id,
            actor_type="service",
            details={"agency_code": agency.code, "agency_name": agency.name},
        )
        db.commit()
        db.refresh(agency)
    if agency.status != "active":
        raise HTTPException(status_code=403, detail="agency is not active")
    return agency


@router.post("/agencies/messages", response_model=AgencyOfficialMessageResponse, status_code=201)
def deliver_official_message(
    payload: AgencyOfficialMessageRequest,
    db: Db,
    principal: MessagePrincipal,
    config: Settings = Depends(get_settings),
) -> AgencyOfficialMessageResponse:
    agency = _agency_for_service(db, principal, config)
    tin = normalize_identifier(payload.tin)
    business = db.scalar(_business_query().where(Business.tin == tin))
    if business is None or business.official_address is None:
        raise HTTPException(status_code=404, detail="business/TIN not found")

    existing = db.scalar(
        _message_query().where(
            OfficialMessage.agency_id == agency.id,
            OfficialMessage.external_message_id == payload.external_message_id,
        )
    )
    if existing is not None:
        same_payload = (
            existing.business_id == business.id
            and existing.subject == payload.subject
            and existing.body_text == payload.body_text
            and existing.classification == payload.classification
        )
        if not same_payload:
            raise HTTPException(status_code=409, detail="external message ID was already used for different content")
        _forward_pending_official_copies(
            db,
            business=business,
            agency=agency,
            message=existing,
            actor_client_id=principal.client_id,
            config=config,
        )
        return AgencyOfficialMessageResponse(
            message=OfficialMessageResponse.model_validate(existing),
            delivery_status="existing",
        )

    message = OfficialMessage(
        business_id=business.id,
        agency_id=agency.id,
        external_message_id=payload.external_message_id,
        subject=payload.subject,
        body_text=payload.body_text,
        classification=payload.classification,
        status="stored",
    )
    db.add(message)
    db.flush()
    db.add(
        MessageDelivery(
            message_id=message.id,
            channel="official_inbox",
            target=business.official_address.address,
            status="delivered",
            delivered_at=utcnow(),
        )
    )
    for external in business.external_emails:
        if external.status == "verified" and external.forward_official_mail:
            db.add(
                MessageDelivery(
                    message_id=message.id,
                    channel="external_forward",
                    target=external.email,
                    status="pending_provider",
                )
            )
    create_business_audit(
        db,
        business_id=business.id,
        action="official_message.stored",
        actor_id=principal.client_id,
        actor_type="service",
        details={
            "agency": agency.code,
            "external_message_id": payload.external_message_id,
            "tin": tin,
        },
    )
    try:
        # Commit retention before any optional forwarding call. A provider failure
        # can never roll back or invalidate the official inbox copy.
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        race = db.scalar(
            _message_query().where(
                OfficialMessage.agency_id == agency.id,
                OfficialMessage.external_message_id == payload.external_message_id,
            )
        )
        if race is None:
            raise
        same_payload = (
            race.business_id == business.id
            and race.subject == payload.subject
            and race.body_text == payload.body_text
            and race.classification == payload.classification
        )
        if not same_payload:
            raise HTTPException(status_code=409, detail="external message ID was already used for different content") from exc
        _forward_pending_official_copies(
            db,
            business=business,
            agency=agency,
            message=race,
            actor_client_id=principal.client_id,
            config=config,
        )
        return AgencyOfficialMessageResponse(
            message=OfficialMessageResponse.model_validate(race),
            delivery_status="existing",
        )

    stored = db.scalar(_message_query().where(OfficialMessage.id == message.id)) or message
    _forward_pending_official_copies(
        db,
        business=business,
        agency=agency,
        message=stored,
        actor_client_id=principal.client_id,
        config=config,
    )
    return AgencyOfficialMessageResponse(
        message=OfficialMessageResponse.model_validate(stored),
        delivery_status="stored",
    )
