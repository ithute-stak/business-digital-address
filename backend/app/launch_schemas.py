from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AttachmentCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=240)
    content_type: str = Field(min_length=3, max_length=160)
    content_base64: str = Field(min_length=4)


class AttachmentResponse(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    sha256_hex: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AcknowledgementResponse(BaseModel):
    id: uuid.UUID
    member_id: uuid.UUID
    actor_sub: str
    acknowledged_at: datetime

    model_config = {"from_attributes": True}


class InboxStateResponse(BaseModel):
    is_read: bool = False
    starred: bool = False
    archived: bool = False
    read_at: datetime | None = None


class InboxStateUpdate(BaseModel):
    is_read: bool | None = None
    starred: bool | None = None
    archived: bool | None = None


class DeliveryStatusResponse(BaseModel):
    id: uuid.UUID
    channel: str
    target: str
    status: str
    provider_reference: str | None
    last_error: str | None
    delivered_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class InboxMessageResponse(BaseModel):
    id: uuid.UUID
    external_message_id: str
    agency_code: str
    agency_name: str
    subject: str
    body_text: str
    classification: str
    status: str
    received_at: datetime
    state: InboxStateResponse
    attachments: list[AttachmentResponse] = Field(default_factory=list)
    acknowledgements: list[AcknowledgementResponse] = Field(default_factory=list)
    deliveries: list[DeliveryStatusResponse] = Field(default_factory=list)


class InboxPageResponse(BaseModel):
    items: list[InboxMessageResponse]
    total: int
    unread: int
    starred: int
    limit: int
    offset: int


class MemberRoleUpdate(BaseModel):
    role: Literal["owner", "admin", "viewer", "member"]


class ReceiptBusiness(BaseModel):
    legal_name: str
    trading_name: str | None
    registration_number: str
    tin: str
    official_address: str | None


class OfficialReceiptResponse(BaseModel):
    receipt_id: str
    message_id: uuid.UUID
    external_message_id: str
    agency_code: str
    agency_name: str
    subject: str
    classification: str
    received_at: datetime
    business: ReceiptBusiness
    deliveries: list[DeliveryStatusResponse]
    acknowledgements: list[AcknowledgementResponse]
    attachment_count: int
    generated_at: datetime


class AdminOperationsResponse(BaseModel):
    businesses: int
    active_official_addresses: int
    pending_mailboxes: int
    official_messages: int
    messages_last_24h: int
    verified_forwarding_addresses: int
    forwarding_failures: int
    active_agencies: int
    acknowledgements: int
    attachments: int
    recent_failures: list[dict[str, object]] = Field(default_factory=list)
    recent_audit: list[dict[str, object]] = Field(default_factory=list)
