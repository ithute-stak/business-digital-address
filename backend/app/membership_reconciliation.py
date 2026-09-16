from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .ithute import IthutePlatformClient, IthutePlatformError
from .models import BusinessMember
from .security import UserPrincipal
from .services import create_business_audit


_ALLOWED_PENDING_STATUSES = {"invited"}
_ROLE_PRIORITY = {"member": 1, "admin": 2, "owner": 3}


def _expected_external_references(member: BusinessMember) -> set[str]:
    return {
        f"business-owner:{member.id}",
        f"business-member:{member.id}",
        f"trade-owner:{member.business_id}:{member.id}",
    }


def reconcile_activated_memberships(
    db: Session,
    principal: UserPrincipal,
    *,
    settings: Settings | None = None,
    raise_on_platform_error: bool = False,
) -> int:
    """Link BDA invitations to the exact Ithute subject that consumed them.

    No contact matching is performed. A local member is activated only when:
    - BDA stored the invitation ID returned by Ithute Auth;
    - Ithute reports that invitation as activated for the current signed-in sub;
    - the invitation external reference matches the local member record; and
    - the local member is still unresolved.
    """

    config = settings or get_settings()
    if not config.ithute_service_client_secret:
        if raise_on_platform_error:
            raise IthutePlatformError("Ithute managed service credential is not configured")
        return 0

    try:
        invitations = IthutePlatformClient(config).activated_invitations_for_subject(
            user_sub=principal.sub
        )
    except IthutePlatformError:
        if raise_on_platform_error:
            raise
        return 0

    by_id = {
        str(item["id"]): item
        for item in invitations
        if item.get("activated_sub") == principal.sub
    }
    if not by_id:
        return 0

    members = list(
        db.scalars(
            select(BusinessMember).where(
                BusinessMember.invitation_id.in_(tuple(by_id)),
                BusinessMember.auth_user_sub.is_(None),
                BusinessMember.status.in_(tuple(_ALLOWED_PENDING_STATUSES)),
            )
        )
    )

    activated = 0
    changed = False
    for member in members:
        invitation = by_id.get(str(member.invitation_id))
        if invitation is None:
            continue
        if invitation.get("activated_sub") != principal.sub:
            continue
        if invitation.get("external_reference") not in _expected_external_references(member):
            continue

        existing = db.scalar(
            select(BusinessMember).where(
                BusinessMember.business_id == member.business_id,
                BusinessMember.auth_user_sub == principal.sub,
                BusinessMember.status == "active",
                BusinessMember.id != member.id,
            )
        )
        if existing is not None:
            invited_member_id = str(member.id)
            invitation_id = member.invitation_id
            previous_role = existing.role
            if _ROLE_PRIORITY.get(member.role, 0) > _ROLE_PRIORITY.get(existing.role, 0):
                existing.role = member.role
            create_business_audit(
                db,
                business_id=member.business_id,
                action="member.invitation.linked_existing",
                actor_id=principal.sub,
                details={
                    "member_id": invited_member_id,
                    "existing_member_id": str(existing.id),
                    "invitation_id": invitation_id,
                    "previous_role": previous_role,
                    "effective_role": existing.role,
                },
            )
            db.delete(member)
            changed = True
            continue

        member.auth_user_sub = principal.sub
        member.status = "active"
        create_business_audit(
            db,
            business_id=member.business_id,
            action="member.invitation.activated",
            actor_id=principal.sub,
            details={
                "member_id": str(member.id),
                "invitation_id": member.invitation_id,
                "role": member.role,
            },
        )
        activated += 1
        changed = True

    if changed:
        db.commit()
    return activated
