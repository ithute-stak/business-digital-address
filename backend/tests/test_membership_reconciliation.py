from __future__ import annotations

import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db import Base
from app.membership_reconciliation import reconcile_activated_memberships
from app.models import AuditEvent, Business, BusinessMember
from app.security import UserPrincipal


def _db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _pending_member(db: Session) -> tuple[Business, BusinessMember]:
    suffix = uuid.uuid4().hex[:10].upper()
    business = Business(
        registration_number=f"REG-{suffix}",
        tin=f"TIN-{suffix}",
        legal_name=f"Reconciliation Test {suffix}",
    )
    db.add(business)
    db.flush()
    member = BusinessMember(
        business_id=business.id,
        role="owner",
        status="invited",
        invitation_id=str(uuid.uuid4()),
        invited_email=f"owner-{suffix.lower()}@example.com",
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return business, member


def _settings() -> Settings:
    return Settings(ithute_service_client_secret="x" * 48)


def test_reconciliation_activates_only_the_exact_ithute_subject(monkeypatch) -> None:
    db = _db()
    business, member = _pending_member(db)
    sub = str(uuid.uuid4())

    def activated(self, *, user_sub: str):
        assert user_sub == sub
        return [
            {
                "id": member.invitation_id,
                "external_reference": f"trade-owner:{business.id}:{member.id}",
                "activated_sub": sub,
            }
        ]

    monkeypatch.setattr(
        "app.membership_reconciliation.IthutePlatformClient.activated_invitations_for_subject",
        activated,
    )
    principal = UserPrincipal(sub=sub, email="owner@example.com")

    assert reconcile_activated_memberships(db, principal, settings=_settings()) == 1
    db.refresh(member)
    assert member.auth_user_sub == sub
    assert member.status == "active"
    assert db.scalar(
        select(AuditEvent).where(
            AuditEvent.business_id == business.id,
            AuditEvent.action == "member.invitation.activated",
            AuditEvent.actor_id == sub,
        )
    ) is not None

    # Replaying the same trusted Auth result cannot create another activation.
    assert reconcile_activated_memberships(db, principal, settings=_settings()) == 0


def test_reconciliation_rejects_wrong_subject_and_wrong_external_reference(monkeypatch) -> None:
    db = _db()
    business, member = _pending_member(db)
    sub = str(uuid.uuid4())

    def wrong_sub(self, *, user_sub: str):
        return [
            {
                "id": member.invitation_id,
                "external_reference": f"trade-owner:{business.id}:{member.id}",
                "activated_sub": str(uuid.uuid4()),
            }
        ]

    monkeypatch.setattr(
        "app.membership_reconciliation.IthutePlatformClient.activated_invitations_for_subject",
        wrong_sub,
    )
    principal = UserPrincipal(sub=sub)
    assert reconcile_activated_memberships(db, principal, settings=_settings()) == 0
    db.refresh(member)
    assert member.auth_user_sub is None
    assert member.status == "invited"

    def wrong_reference(self, *, user_sub: str):
        return [
            {
                "id": member.invitation_id,
                "external_reference": "business-member:not-this-member",
                "activated_sub": sub,
            }
        ]

    monkeypatch.setattr(
        "app.membership_reconciliation.IthutePlatformClient.activated_invitations_for_subject",
        wrong_reference,
    )
    assert reconcile_activated_memberships(db, principal, settings=_settings()) == 0
    db.refresh(member)
    assert member.auth_user_sub is None
    assert member.status == "invited"


def test_reconciliation_does_not_duplicate_an_existing_business_membership(monkeypatch) -> None:
    db = _db()
    business, invited = _pending_member(db)
    sub = str(uuid.uuid4())
    existing = BusinessMember(
        business_id=business.id,
        auth_user_sub=sub,
        role="member",
        status="active",
    )
    db.add(existing)
    db.commit()

    def activated(self, *, user_sub: str):
        return [
            {
                "id": invited.invitation_id,
                "external_reference": f"business-member:{invited.id}",
                "activated_sub": sub,
            }
        ]

    monkeypatch.setattr(
        "app.membership_reconciliation.IthutePlatformClient.activated_invitations_for_subject",
        activated,
    )
    assert reconcile_activated_memberships(
        db,
        UserPrincipal(sub=sub),
        settings=_settings(),
    ) == 0
    db.refresh(invited)
    assert invited.auth_user_sub is None
    assert invited.status == "linked_existing"
    assert db.scalar(
        select(AuditEvent).where(
            AuditEvent.business_id == business.id,
            AuditEvent.action == "member.invitation.linked_existing",
            AuditEvent.actor_id == sub,
        )
    ) is not None
