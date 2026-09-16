from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    registration_number: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    tin: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    legal_name: Mapped[str] = mapped_column(String(200), index=True)
    trading_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    official_address: Mapped[OfficialAddress | None] = relationship(back_populates="business", uselist=False, cascade="all, delete-orphan")
    members: Mapped[list[BusinessMember]] = relationship(back_populates="business", cascade="all, delete-orphan")
    external_emails: Mapped[list[ExternalEmail]] = relationship(back_populates="business", cascade="all, delete-orphan")
    messages: Mapped[list[OfficialMessage]] = relationship(back_populates="business", cascade="all, delete-orphan")


class OfficialAddress(Base):
    __tablename__ = "official_addresses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), unique=True, index=True)
    local_part: Mapped[str] = mapped_column(String(80), unique=True)
    domain: Mapped[str] = mapped_column(String(253))
    address: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    mailbox_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    platform_binding_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    platform_mailbox_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    friendly_alias: Mapped[str | None] = mapped_column(String(320), unique=True, nullable=True)
    provisioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    business: Mapped[Business] = relationship(back_populates="official_address")


class BusinessMember(Base):
    __tablename__ = "business_members"
    __table_args__ = (
        UniqueConstraint("business_id", "auth_user_sub", name="uq_business_member_sub"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    auth_user_sub: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(32), default="owner")
    status: Mapped[str] = mapped_column(String(32), default="invited", index=True)
    invitation_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    invited_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    invited_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    business: Mapped[Business] = relationship(back_populates="members")


class ExternalEmail(Base):
    __tablename__ = "external_emails"
    __table_args__ = (
        UniqueConstraint("business_id", "email", name="uq_business_external_email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    verification_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verification_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    forward_official_mail: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    business: Mapped[Business] = relationship(back_populates="external_emails")


class Agency(Base):
    __tablename__ = "agencies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    messages: Mapped[list[OfficialMessage]] = relationship(back_populates="agency")


class OfficialMessage(Base):
    __tablename__ = "official_messages"
    __table_args__ = (
        UniqueConstraint("agency_id", "external_message_id", name="uq_agency_external_message"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    agency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agencies.id", ondelete="RESTRICT"), index=True)
    external_message_id: Mapped[str] = mapped_column(String(160))
    subject: Mapped[str] = mapped_column(String(240))
    body_text: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(String(32), default="official")
    status: Mapped[str] = mapped_column(String(32), default="stored", index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    business: Mapped[Business] = relationship(back_populates="messages")
    agency: Mapped[Agency] = relationship(back_populates="messages")
    deliveries: Mapped[list[MessageDelivery]] = relationship(back_populates="message", cascade="all, delete-orphan")


class MessageDelivery(Base):
    __tablename__ = "message_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("official_messages.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    message: Mapped[OfficialMessage] = relationship(back_populates="deliveries")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    actor_type: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str] = mapped_column(String(160), index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    business_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("businesses.id", ondelete="SET NULL"), nullable=True, index=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
