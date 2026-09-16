from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .db import get_db
from .ithute import IthutePlatformError
from .membership_reconciliation import reconcile_activated_memberships
from .models import Business, BusinessMember
from .schemas import BusinessResponse
from .security import UserPrincipal, require_user


router = APIRouter(prefix="/api/v1", tags=["business-memberships"])
Db = Annotated[Session, Depends(get_db)]
Principal = Annotated[UserPrincipal, Depends(require_user)]


def _business_query():
    return select(Business).options(
        selectinload(Business.official_address),
        selectinload(Business.members),
        selectinload(Business.external_emails),
    )


@router.post("/memberships/reconcile")
def reconcile_memberships(db: Db, principal: Principal) -> dict[str, int]:
    try:
        activated = reconcile_activated_memberships(
            db,
            principal,
            raise_on_platform_error=True,
        )
    except IthutePlatformError as exc:
        raise HTTPException(status_code=502, detail="Ithute identity reconciliation is temporarily unavailable") from exc
    return {"activated_memberships": activated}


@router.get("/businesses", response_model=list[BusinessResponse])
def list_businesses_with_reconciliation(db: Db, principal: Principal) -> list[Business]:
    # This is the normal landing request after sign-in. Reconcile first so a
    # freshly activated Trade/portal invitation appears immediately. Platform
    # lookup failures fail closed and do not disrupt already-active memberships.
    reconcile_activated_memberships(db, principal)
    return list(
        db.scalars(
            _business_query()
            .join(BusinessMember, BusinessMember.business_id == Business.id)
            .where(
                BusinessMember.auth_user_sub == principal.sub,
                BusinessMember.status == "active",
            )
            .order_by(Business.legal_name)
        ).unique()
    )
