from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .models import AuditEvent, Business, OfficialAddress, utcnow


_NON_ALNUM = re.compile(r"[^a-z0-9]+")
OFFICIAL_LOCAL_PART_PREFIX = "bda-"
_MAX_EMAIL_LOCAL_PART_LENGTH = 64


def normalize_identifier(value: str) -> str:
    return value.strip().upper()


def official_local_part(registration_number: str) -> str:
    """Return the stable local part reserved to Business Digital Address.

    Ithute Platform Mail grants BDA only the ``bda-`` namespace on the shared
    temporary ``ithute.co.ls`` domain. Keeping the prefix product-owned and
    non-configurable prevents a BDA runtime setting from escaping that grant.
    """

    compact = _NON_ALNUM.sub("", registration_number.strip().lower())
    if not compact:
        raise ValueError("registration number cannot produce an official address")

    readable_limit = _MAX_EMAIL_LOCAL_PART_LENGTH - len(OFFICIAL_LOCAL_PART_PREFIX)
    if len(compact) <= readable_limit:
        return f"{OFFICIAL_LOCAL_PART_PREFIX}{compact}"

    # Preserve readability for long registration identifiers while avoiding the
    # collision risk of simply truncating two identifiers with the same prefix.
    digest = hashlib.sha256(compact.encode("utf-8")).hexdigest()[:12]
    readable_limit -= len(digest)
    return f"{OFFICIAL_LOCAL_PART_PREFIX}{compact[:readable_limit]}{digest}"


def official_address_for(registration_number: str, domain: str) -> tuple[str, str]:
    local_part = official_local_part(registration_number)
    normalized_domain = domain.strip().lower().rstrip(".")
    if not normalized_domain or "." not in normalized_domain:
        raise ValueError("official domain must be fully qualified")
    return local_part, f"{local_part}@{normalized_domain}"


def create_business_audit(
    db: Session,
    *,
    business_id: uuid.UUID | None,
    action: str,
    actor_id: str,
    actor_type: str = "user",
    details: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            business_id=business_id,
            details_json=json.dumps(details or {}, separators=(",", ":"), default=str),
        )
    )


def create_verification_code(*, ttl_minutes: int) -> tuple[str, str, datetime]:
    code = f"{secrets.randbelow(1_000_000):06d}"
    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
    expires_at = utcnow() + timedelta(minutes=ttl_minutes)
    return code, digest, expires_at


def verify_code(code: str, expected_hash: str | None) -> bool:
    if not expected_hash:
        return False
    digest = hashlib.sha256(code.strip().encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, expected_hash)


def business_external_reference(business: Business) -> str:
    return f"business:{business.id}"


def ensure_official_address(business: Business, *, domain: str) -> OfficialAddress:
    if business.official_address is not None:
        return business.official_address
    local_part, address = official_address_for(business.registration_number, domain)
    item = OfficialAddress(
        business_id=business.id,
        local_part=local_part,
        domain=domain.strip().lower().rstrip("."),
        address=address,
        mailbox_status="pending",
    )
    business.official_address = item
    return item
