from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, model_validator

from .schemas import BusinessResponse, DeliveryResponse


class PortalSummary(BaseModel):
    official_messages: int
    authorised_members: int
    verified_external_emails: int
    pending_actions: int


class PortalMemberResponse(BaseModel):
    id: uuid.UUID
    auth_user_sub: str | None
    role: str
    status: str
    invited_email: str | None
    invited_phone: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MemberInviteRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=160)
    role: Literal["owner", "admin", "member"] = "member"
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    preferred_channel: Literal["phone", "email"] = "email"

    @model_validator(mode="after")
    def validate_target(self) -> "MemberInviteRequest":
        if self.preferred_channel == "email" and not self.email:
            raise ValueError("email is required when preferred_channel is email")
        if self.preferred_channel == "phone" and not self.phone:
            raise ValueError("phone is required when preferred_channel is phone")
        return self


class PortalExternalEmailResponse(BaseModel):
    id: uuid.UUID
    email: str
    status: str
    forward_official_mail: bool
    verified_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ExternalEmailUpdate(BaseModel):
    forward_official_mail: bool


class PortalMessageResponse(BaseModel):
    id: uuid.UUID
    external_message_id: str
    agency_code: str
    agency_name: str
    subject: str
    body_text: str
    classification: str
    status: str
    received_at: datetime
    deliveries: list[DeliveryResponse] = Field(default_factory=list)


class PortalAuditResponse(BaseModel):
    id: uuid.UUID
    actor_type: str
    actor_id: str
    action: str
    details: dict[str, object]
    created_at: datetime


class PortalSnapshot(BaseModel):
    business: BusinessResponse
    summary: PortalSummary
    members: list[PortalMemberResponse]
    external_emails: list[PortalExternalEmailResponse]
    messages: list[PortalMessageResponse]
    audit: list[PortalAuditResponse]
