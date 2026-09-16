from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, model_validator


class OwnerInvite(BaseModel):
    display_name: str = Field(min_length=1, max_length=160)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    preferred_channel: Literal["phone", "email"] = "phone"

    @model_validator(mode="after")
    def delivery_target(self) -> "OwnerInvite":
        if self.preferred_channel == "phone" and not self.phone:
            raise ValueError("phone is required when preferred_channel is phone")
        if self.preferred_channel == "email" and not self.email:
            raise ValueError("email is required when preferred_channel is email")
        return self


class BusinessCreate(BaseModel):
    registration_number: str = Field(min_length=1, max_length=80)
    tin: str = Field(min_length=1, max_length=80)
    legal_name: str = Field(min_length=2, max_length=200)
    trading_name: str | None = Field(default=None, max_length=200)
    owner: OwnerInvite | None = None


class OfficialAddressResponse(BaseModel):
    address: str
    local_part: str
    domain: str
    mailbox_status: str
    friendly_alias: str | None = None

    model_config = {"from_attributes": True}


class BusinessResponse(BaseModel):
    id: uuid.UUID
    registration_number: str
    tin: str
    legal_name: str
    trading_name: str | None
    status: str
    official_address: OfficialAddressResponse | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ExternalEmailCreate(BaseModel):
    email: EmailStr
    forward_official_mail: bool = True


class ExternalEmailVerify(BaseModel):
    code: str = Field(min_length=6, max_length=16)


class ExternalEmailResponse(BaseModel):
    id: uuid.UUID
    email: str
    status: str
    forward_official_mail: bool
    verified_at: datetime | None

    model_config = {"from_attributes": True}


class AgencyCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")
    name: str = Field(min_length=2, max_length=200)


class AgencyResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    status: str

    model_config = {"from_attributes": True}


class OfficialMessageCreate(BaseModel):
    tin: str = Field(min_length=1, max_length=80)
    agency_code: str = Field(min_length=2, max_length=64)
    external_message_id: str = Field(min_length=1, max_length=160)
    subject: str = Field(min_length=1, max_length=240)
    body_text: str = Field(min_length=1, max_length=100000)
    classification: str = Field(default="official", max_length=32)


class DeliveryResponse(BaseModel):
    channel: str
    target: str
    status: str
    last_error: str | None

    model_config = {"from_attributes": True}


class OfficialMessageResponse(BaseModel):
    id: uuid.UUID
    business_id: uuid.UUID
    external_message_id: str
    subject: str
    classification: str
    status: str
    received_at: datetime
    deliveries: list[DeliveryResponse] = []

    model_config = {"from_attributes": True}
