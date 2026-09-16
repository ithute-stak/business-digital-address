"""move unprovisioned official addresses into the reserved BDA mail namespace

Revision ID: 0003_reserved_mail_namespace
Revises: 0002_platform_config
"""

from __future__ import annotations

import hashlib
import re

from alembic import op
import sqlalchemy as sa


revision = "0003_reserved_mail_namespace"
down_revision = "0002_platform_config"
branch_labels = None
depends_on = None


_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_RESERVED_PREFIX = "bda-"
_MAX_LOCAL_PART_LENGTH = 64


def _compact_registration(registration_number: str) -> str:
    compact = _NON_ALNUM.sub("", registration_number.strip().lower())
    if not compact:
        raise ValueError("registration number cannot produce an official address")
    return compact


def _reserved_local_part(registration_number: str) -> str:
    compact = _compact_registration(registration_number)
    readable_limit = _MAX_LOCAL_PART_LENGTH - len(_RESERVED_PREFIX)
    if len(compact) <= readable_limit:
        return f"{_RESERVED_PREFIX}{compact}"
    digest = hashlib.sha256(compact.encode("utf-8")).hexdigest()[:12]
    readable_limit -= len(digest)
    return f"{_RESERVED_PREFIX}{compact[:readable_limit]}{digest}"


def _legacy_local_part(registration_number: str) -> str:
    compact = _compact_registration(registration_number)
    if len(compact) <= 63:
        return f"b{compact}"
    digest = hashlib.sha256(compact.encode("utf-8")).hexdigest()[:12]
    return f"b{compact[:48]}{digest}"


def _rewrite_unprovisioned(local_part_factory) -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT oa.id, b.registration_number, oa.domain
            FROM official_addresses AS oa
            JOIN businesses AS b ON b.id = oa.business_id
            WHERE oa.platform_binding_id IS NULL
              AND oa.platform_mailbox_id IS NULL
              AND oa.provisioned_at IS NULL
            """
        )
    ).mappings().all()

    for row in rows:
        local_part = local_part_factory(str(row["registration_number"]))
        domain = str(row["domain"]).strip().lower().rstrip(".")
        bind.execute(
            sa.text(
                """
                UPDATE official_addresses
                SET local_part = :local_part,
                    address = :address
                WHERE id = :id
                """
            ),
            {
                "id": row["id"],
                "local_part": local_part,
                "address": f"{local_part}@{domain}",
            },
        )


def upgrade() -> None:
    # Already-provisioned addresses are deliberately immutable. Only records that
    # have never been bound to Platform Mail are moved into the new namespace.
    _rewrite_unprovisioned(_reserved_local_part)


def downgrade() -> None:
    # Preserve the same safety property on rollback: never rename a mailbox that
    # may already exist in Ithute Mail.
    _rewrite_unprovisioned(_legacy_local_part)
