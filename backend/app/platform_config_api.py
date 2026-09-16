from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .platform_config import (
    get_platform_configuration,
    normalize_email_domain,
    normalize_portal_base_url,
)
from .security import UserPrincipal, require_user
from .services import create_business_audit


router = APIRouter(prefix="/api/v1/platform/config", tags=["platform-configuration"])
Db = Annotated[Session, Depends(get_db)]
Principal = Annotated[UserPrincipal, Depends(require_user)]


class PlatformConfigurationResponse(BaseModel):
    portal_base_url: str
    official_email_domain: str

    model_config = {"from_attributes": True}


class PlatformConfigurationUpdate(BaseModel):
    portal_base_url: str | None = Field(default=None, min_length=8, max_length=255)
    official_email_domain: str | None = Field(default=None, min_length=3, max_length=253)


@router.get("", response_model=PlatformConfigurationResponse)
def read_platform_configuration(db: Db) -> PlatformConfigurationResponse:
    """Return non-secret runtime addressing configuration."""

    return PlatformConfigurationResponse.model_validate(get_platform_configuration(db))


@router.patch("", response_model=PlatformConfigurationResponse)
def update_platform_configuration(
    payload: PlatformConfigurationUpdate,
    db: Db,
    principal: Principal,
) -> PlatformConfigurationResponse:
    if not principal.is_platform_admin:
        raise HTTPException(status_code=403, detail="Ithute platform administrator required")
    if payload.portal_base_url is None and payload.official_email_domain is None:
        raise HTTPException(status_code=400, detail="at least one configuration value is required")

    settings = get_settings()
    row = get_platform_configuration(db)
    before = {
        "portal_base_url": row.portal_base_url,
        "official_email_domain": row.official_email_domain,
    }

    try:
        if payload.portal_base_url is not None:
            row.portal_base_url = normalize_portal_base_url(
                payload.portal_base_url,
                production=settings.environment.lower() == "production",
            )
        if payload.official_email_domain is not None:
            row.official_email_domain = normalize_email_domain(payload.official_email_domain)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    row.updated_by = principal.sub
    create_business_audit(
        db,
        business_id=None,
        action="platform.configuration.updated",
        actor_id=principal.sub,
        details={
            "before": before,
            "after": {
                "portal_base_url": row.portal_base_url,
                "official_email_domain": row.official_email_domain,
            },
            "note": "existing official addresses are not rewritten automatically",
        },
    )
    db.commit()
    db.refresh(row)
    return PlatformConfigurationResponse.model_validate(row)
