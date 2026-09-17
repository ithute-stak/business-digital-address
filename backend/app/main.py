from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .config import Settings, get_settings
from .db import get_db
from .ithute import IthutePlatformClient, IthutePlatformError
from .mail_forwarding import send_verification_email, sync_inbound_forwarding
from .models import (
    Agency,
    Business,
    BusinessMember,
    ExternalEmail,
    MessageDelivery,
    OfficialMessage,
    utcnow,
)
from .platform_config import get_platform_configuration
from .schemas import (
    AgencyCreate,
    AgencyResponse,
    BusinessCreate,
    BusinessResponse,
    ExternalEmailCreate,
    ExternalEmailResponse,
    ExternalEmailVerify,
    OfficialMessageCreate,
    OfficialMessageResponse,
    OwnerInvite,
)
from .security import UserPrincipal, require_user
from .services import (
    business_external_reference,
    create_business_audit,
    create_verification_code,
    ensure_official_address,
    normalize_identifier,
    verify_code,
)


settings = get_settings()
app = FastAPI(title="Business Digital Address", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Db = Annotated[Session, Depends(get_db)]
Principal = Annotated[UserPrincipal, Depends(require_user)]


def _business_query():
    return select(Business).options(
        selectinload(Business.official_address),
        selectinload(Business.members),
        selectinload(Business.external_emails),
    )


def _business_for_user(db: Session, business_id: uuid.UUID, principal: UserPrincipal) -> Business:
    business = db.scalar(
        _business_query()
        .join(BusinessMember, BusinessMember.business_id == Business.id)
        .where(
            Business.id == business_id,
            BusinessMember.auth_user_sub == principal.sub,
            BusinessMember.status == "active",
        )
    )
    if business is None:
        raise HTTPException(status_code=404, detail="business not found")
    return business


def _apply_owner_invitation(db: Session, business: Business, member: BusinessMember, owner: OwnerInvite) -> None:
    config = get_settings()
    if not config.ithute_service_client_secret:
        member.status = "pending_platform"
        create_business_audit(
            db,
            business_id=business.id,
            action="owner.invitation.deferred",
            actor_id=config.ithute_service_client_id,
            actor_type="service",
            details={"reason": "Ithute service credential is not configured"},
        )
        db.commit()
        return
    try:
        result = IthutePlatformClient(config).invite_identity(
            external_reference=f"business-owner:{member.id}",
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
            actor_id=config.ithute_service_client_id,
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
            actor_id=config.ithute_service_client_id,
            actor_type="service",
            details={"invitation_id": member.invitation_id, "delivery_status": result.get("delivery_status")},
        )
    db.commit()


def _provision_official_mailbox(db: Session, business: Business) -> None:
    config = get_settings()
    platform_config = get_platform_configuration(db, config)
    official = business.official_address or ensure_official_address(
        business,
        domain=platform_config.official_email_domain,
    )
    if official.platform_binding_id and official.mailbox_status == "active":
        return
    if not config.ithute_service_client_secret:
        raise HTTPException(status_code=503, detail="Ithute managed service credential is not configured")
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
            actor_id=config.ithute_service_client_id,
            actor_type="service",
            details={"address": official.address, "error": str(exc)},
        )
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    official.platform_binding_id = result.binding_id
    official.platform_mailbox_id = result.mailbox_id
    official.address = result.address
    official.mailbox_status = result.status
    official.provisioned_at = utcnow()
    create_business_audit(
        db,
        business_id=business.id,
        action="official_address.provisioned",
        actor_id=config.ithute_service_client_id,
        actor_type="service",
        details={"address": result.address, "binding_id": result.binding_id},
    )
    db.commit()


@app.get("/health/live", tags=["system"])
def liveness() -> dict[str, str]:
    return {"status": "ok", "service": "business-digital-address"}


@app.get("/health/ready", tags=["system"])
def readiness(db: Db) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ready", "service": "business-digital-address"}


@app.post("/api/v1/businesses", response_model=BusinessResponse, status_code=201)
def create_business(payload: BusinessCreate, db: Db, principal: Principal) -> Business:
    registration_number = normalize_identifier(payload.registration_number)
    tin = normalize_identifier(payload.tin)
    business = Business(
        registration_number=registration_number,
        tin=tin,
        legal_name=payload.legal_name.strip(),
        trading_name=payload.trading_name.strip() if payload.trading_name else None,
    )
    db.add(business)
    try:
        db.flush()
        platform_config = get_platform_configuration(db)
        ensure_official_address(business, domain=platform_config.official_email_domain)
        db.add(
            BusinessMember(
                business_id=business.id,
                auth_user_sub=principal.sub,
                role="owner",
                status="active",
                invited_email=principal.email,
            )
        )
        invited_member = None
        if payload.owner:
            invited_member = BusinessMember(
                business_id=business.id,
                role="owner",
                status="pending_platform",
                invited_email=str(payload.owner.email) if payload.owner.email else None,
                invited_phone=payload.owner.phone,
            )
            db.add(invited_member)
        create_business_audit(
            db,
            business_id=business.id,
            action="business.created",
            actor_id=principal.sub,
            details={"registration_number": registration_number, "tin": tin},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="registration number, TIN or official address already exists") from exc

    business = db.scalar(_business_query().where(Business.id == business.id))
    assert business is not None
    if payload.owner and invited_member is not None:
        _apply_owner_invitation(db, business, invited_member, payload.owner)
    if get_settings().enable_real_mail_provisioning:
        try:
            _provision_official_mailbox(db, business)
        except HTTPException:
            pass
    return db.scalar(_business_query().where(Business.id == business.id)) or business


@app.get("/api/v1/businesses", response_model=list[BusinessResponse])
def list_businesses(db: Db, principal: Principal) -> list[Business]:
    return list(
        db.scalars(
            _business_query()
            .join(BusinessMember, BusinessMember.business_id == Business.id)
            .where(BusinessMember.auth_user_sub == principal.sub, BusinessMember.status == "active")
            .order_by(Business.legal_name)
        ).unique()
    )


@app.get("/api/v1/businesses/{business_id}", response_model=BusinessResponse)
def get_business(business_id: uuid.UUID, db: Db, principal: Principal) -> Business:
    return _business_for_user(db, business_id, principal)


@app.get("/api/v1/businesses/by-tin/{tin}", response_model=BusinessResponse)
def get_own_business_by_tin(tin: str, db: Db, principal: Principal) -> Business:
    business = db.scalar(
        _business_query()
        .join(BusinessMember, BusinessMember.business_id == Business.id)
        .where(
            Business.tin == normalize_identifier(tin),
            BusinessMember.auth_user_sub == principal.sub,
            BusinessMember.status == "active",
        )
    )
    if business is None:
        raise HTTPException(status_code=404, detail="business not found")
    return business


@app.post("/api/v1/businesses/{business_id}/official-address/provision", response_model=BusinessResponse)
def provision_official_address(business_id: uuid.UUID, db: Db, principal: Principal) -> Business:
    business = _business_for_user(db, business_id, principal)
    _provision_official_mailbox(db, business)
    return db.scalar(_business_query().where(Business.id == business.id)) or business


@app.post("/api/v1/businesses/{business_id}/external-emails", response_model=ExternalEmailResponse, status_code=201)
def add_external_email(payload: ExternalEmailCreate, business_id: uuid.UUID, db: Db, principal: Principal) -> ExternalEmailResponse:
    business = _business_for_user(db, business_id, principal)
    config = get_settings()
    code, digest, expires_at = create_verification_code(ttl_minutes=config.external_email_verification_ttl_minutes)
    item = ExternalEmail(
        business_id=business_id,
        email=str(payload.email).strip().lower(),
        status="pending",
        verification_hash=digest,
        verification_expires_at=expires_at,
        forward_official_mail=payload.forward_official_mail,
    )
    db.add(item)
    create_business_audit(
        db,
        business_id=business_id,
        action="external_email.verification.started",
        actor_id=principal.sub,
        details={"email": item.email},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="external email is already registered for this business") from exc
    db.refresh(item)

    if config.environment.lower() == "production":
        try:
            send_verification_email(db, business, item, code)
        except IthutePlatformError as exc:
            create_business_audit(
                db,
                business_id=business_id,
                action="external_email.verification.delivery_failed",
                actor_id=config.ithute_service_client_id,
                actor_type="service",
                details={"email": item.email, "error": str(exc)},
            )
            db.commit()
            raise HTTPException(status_code=502, detail="verification email could not be delivered") from exc

    return ExternalEmailResponse(
        id=item.id,
        email=item.email,
        status=item.status,
        forward_official_mail=item.forward_official_mail,
        verified_at=item.verified_at,
        verification_code=code if config.environment.lower() != "production" else None,
    )


@app.post("/api/v1/businesses/{business_id}/external-emails/{email_id}/verify", response_model=ExternalEmailResponse)
def verify_external_email(
    payload: ExternalEmailVerify,
    business_id: uuid.UUID,
    email_id: uuid.UUID,
    db: Db,
    principal: Principal,
) -> ExternalEmail:
    business = _business_for_user(db, business_id, principal)
    item = db.get(ExternalEmail, email_id)
    if item is None or item.business_id != business_id:
        raise HTTPException(status_code=404, detail="external email not found")
    if item.verification_expires_at is None or item.verification_expires_at <= utcnow():
        raise HTTPException(status_code=410, detail="verification code has expired")
    if not verify_code(payload.code, item.verification_hash):
        raise HTTPException(status_code=400, detail="invalid verification code")
    item.status = "verified"
    item.verified_at = utcnow()
    item.verification_hash = None
    item.verification_expires_at = None
    create_business_audit(
        db,
        business_id=business_id,
        action="external_email.verified",
        actor_id=principal.sub,
        details={"email": item.email},
    )
    db.commit()
    db.refresh(item)

    if item.forward_official_mail:
        try:
            sync_inbound_forwarding(
                db,
                business,
                actor_id=get_settings().ithute_service_client_id,
                strict=get_settings().environment.lower() == "production",
            )
        except IthutePlatformError as exc:
            create_business_audit(
                db,
                business_id=business_id,
                action="external_email.forwarding.sync_failed",
                actor_id=get_settings().ithute_service_client_id,
                actor_type="service",
                details={"email": item.email, "error": str(exc)},
            )
            db.commit()
            if get_settings().environment.lower() == "production":
                raise HTTPException(status_code=502, detail="email verified but inbound forwarding could not be activated") from exc
    return item


@app.get("/api/v1/businesses/{business_id}/messages", response_model=list[OfficialMessageResponse])
def list_official_messages(business_id: uuid.UUID, db: Db, principal: Principal) -> list[OfficialMessage]:
    _business_for_user(db, business_id, principal)
    return list(
        db.scalars(
            select(OfficialMessage)
            .options(selectinload(OfficialMessage.deliveries))
            .where(OfficialMessage.business_id == business_id)
            .order_by(OfficialMessage.received_at.desc())
        )
    )


def _development_only(config: Settings) -> None:
    if config.environment.lower() == "production":
        raise HTTPException(status_code=404, detail="not found")


@app.post("/api/v1/dev/agencies", response_model=AgencyResponse, status_code=201)
def create_demo_agency(payload: AgencyCreate, db: Db, principal: Principal, config: Settings = Depends(get_settings)) -> Agency:
    _development_only(config)
    agency = Agency(code=payload.code.strip().lower(), name=payload.name.strip())
    db.add(agency)
    create_business_audit(db, business_id=None, action="dev.agency.created", actor_id=principal.sub, details={"code": agency.code})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="agency code already exists") from exc
    db.refresh(agency)
    return agency


@app.post("/api/v1/dev/official-messages", response_model=OfficialMessageResponse, status_code=201)
def create_demo_official_message(
    payload: OfficialMessageCreate,
    db: Db,
    principal: Principal,
    config: Settings = Depends(get_settings),
) -> OfficialMessage:
    _development_only(config)
    business = db.scalar(_business_query().where(Business.tin == normalize_identifier(payload.tin)))
    if business is None or business.official_address is None:
        raise HTTPException(status_code=404, detail="business/TIN not found")
    agency = db.scalar(select(Agency).where(Agency.code == payload.agency_code.strip().lower(), Agency.status == "active"))
    if agency is None:
        raise HTTPException(status_code=404, detail="agency not found")
    existing = db.scalar(
        select(OfficialMessage)
        .options(selectinload(OfficialMessage.deliveries))
        .where(OfficialMessage.agency_id == agency.id, OfficialMessage.external_message_id == payload.external_message_id)
    )
    if existing is not None:
        return existing

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
        actor_id=principal.sub,
        details={"agency": agency.code, "external_message_id": payload.external_message_id},
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(OfficialMessage)
            .options(selectinload(OfficialMessage.deliveries))
            .where(OfficialMessage.agency_id == agency.id, OfficialMessage.external_message_id == payload.external_message_id)
        )
        if existing is None:
            raise
        return existing
    return db.scalar(
        select(OfficialMessage).options(selectinload(OfficialMessage.deliveries)).where(OfficialMessage.id == message.id)
    ) or message