from __future__ import annotations

from pydantic import BaseModel, Field

from .schemas import BusinessResponse, OfficialMessageResponse, OwnerInvite


class TradeBusinessRegistrationRequest(BaseModel):
    source_reference: str = Field(min_length=1, max_length=160)
    registration_number: str = Field(min_length=1, max_length=80)
    tin: str = Field(min_length=1, max_length=80)
    legal_name: str = Field(min_length=2, max_length=200)
    trading_name: str | None = Field(default=None, max_length=200)
    owner: OwnerInvite | None = None


class TradeBusinessRegistrationResponse(BaseModel):
    business: BusinessResponse
    registration_status: str
    owner_invitation_status: str | None = None


class AgencyOfficialMessageRequest(BaseModel):
    tin: str = Field(min_length=1, max_length=80)
    external_message_id: str = Field(min_length=1, max_length=160)
    subject: str = Field(min_length=1, max_length=240)
    body_text: str = Field(min_length=1, max_length=100000)
    classification: str = Field(default="official", min_length=1, max_length=32)


class AgencyOfficialMessageResponse(BaseModel):
    message: OfficialMessageResponse
    delivery_status: str
