from __future__ import annotations

from sqlalchemy.orm import Session

from .config import get_settings
from .ithute import IthutePlatformClient, IthutePlatformError
from .models import Business, ExternalEmail
from .services import create_business_audit


def preferred_forwarding_email(business: Business) -> ExternalEmail | None:
    candidates = [
        item
        for item in business.external_emails
        if item.status == "verified" and item.forward_official_mail
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.verified_at or item.created_at, item.created_at))


def sync_inbound_forwarding(
    db: Session,
    business: Business,
    *,
    actor_id: str,
    strict: bool,
) -> bool:
    """Synchronize the business's verified destination into Ithute Platform Mail.

    The BDA database remains the policy source. Ithute Mail owns the actual
    recipient-copy runtime rule. In production callers use ``strict=True`` so
    an enabled forwarding policy cannot be reported as active when the managed
    platform credential, mailbox binding, or runtime is unavailable.
    """

    config = get_settings()
    target = preferred_forwarding_email(business)
    official = business.official_address

    if not config.enable_real_mail_forwarding:
        if strict and target is not None:
            raise IthutePlatformError("real external mail forwarding is disabled")
        return False
    if not config.ithute_service_client_secret:
        if strict and target is not None:
            raise IthutePlatformError("Ithute managed service credential is not configured")
        return False
    if official is None or not official.platform_binding_id or official.mailbox_status != "active":
        if strict and target is not None:
            raise IthutePlatformError("official Ithute mailbox must be active before inbound forwarding can be enabled")
        return False

    client = IthutePlatformClient(config)
    if target is None:
        result = client.disable_inbound_forwarding(binding_id=official.platform_binding_id)
        destination = None
    else:
        result = client.configure_inbound_forwarding(
            binding_id=official.platform_binding_id,
            destination=target.email,
        )
        destination = target.email

    create_business_audit(
        db,
        business_id=business.id,
        action="official_address.inbound_forwarding.synced",
        actor_id=actor_id,
        actor_type="service" if actor_id == config.ithute_service_client_id else "user",
        details={
            "address": official.address,
            "destination": destination,
            "active": result.active,
            "runtime_synced": result.runtime_synced,
        },
    )
    db.commit()
    return result.runtime_synced


def send_verification_email(db: Session, business: Business, item: ExternalEmail, code: str) -> None:
    """Deliver a verification code from the business's platform-managed mailbox."""

    config = get_settings()
    official = business.official_address
    if not config.enable_real_mail_forwarding:
        raise IthutePlatformError("real external mail forwarding is disabled")
    if official is None or not official.platform_binding_id or official.mailbox_status != "active":
        raise IthutePlatformError("official Ithute mailbox must be active before external email verification")

    result = IthutePlatformClient(config).send_official_copy(
        binding_id=official.platform_binding_id,
        external_reference=f"external-email-verification:{item.id}:{(item.verification_hash or '')[:16]}",
        recipient=item.email,
        subject="Verify your Business Digital Address forwarding email",
        text=(
            f"Your Business Digital Address verification code is {code}.\n\n"
            "Enter this code in the BDA portal to allow copies of mail received by your official "
            f"address {official.address} to be sent to {item.email}.\n\n"
            "If you did not request this, you can ignore this message."
        ),
    )
    create_business_audit(
        db,
        business_id=business.id,
        action="external_email.verification.sent",
        actor_id=config.ithute_service_client_id,
        actor_type="service",
        details={
            "email": item.email,
            "delivery_id": result.delivery_id,
            "provider_status": result.status,
        },
    )
    db.commit()
