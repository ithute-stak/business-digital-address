"""create Business Digital Address core schema

Revision ID: 0001_bda_core
Revises:
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_bda_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "businesses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("registration_number", sa.String(length=80), nullable=False),
        sa.Column("tin", sa.String(length=80), nullable=False),
        sa.Column("legal_name", sa.String(length=200), nullable=False),
        sa.Column("trading_name", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("registration_number"),
        sa.UniqueConstraint("tin"),
    )
    op.create_index("ix_businesses_registration_number", "businesses", ["registration_number"])
    op.create_index("ix_businesses_tin", "businesses", ["tin"])
    op.create_index("ix_businesses_legal_name", "businesses", ["legal_name"])
    op.create_index("ix_businesses_status", "businesses", ["status"])

    op.create_table(
        "agencies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_agencies_code", "agencies", ["code"], unique=True)

    op.create_table(
        "official_addresses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("local_part", sa.String(length=80), nullable=False),
        sa.Column("domain", sa.String(length=253), nullable=False),
        sa.Column("address", sa.String(length=320), nullable=False),
        sa.Column("mailbox_status", sa.String(length=32), nullable=False),
        sa.Column("friendly_alias", sa.String(length=320), nullable=True),
        sa.Column("provisioned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("address"),
        sa.UniqueConstraint("business_id"),
        sa.UniqueConstraint("friendly_alias"),
        sa.UniqueConstraint("local_part"),
    )
    op.create_index("ix_official_addresses_address", "official_addresses", ["address"], unique=True)
    op.create_index("ix_official_addresses_business_id", "official_addresses", ["business_id"], unique=True)
    op.create_index("ix_official_addresses_mailbox_status", "official_addresses", ["mailbox_status"])

    op.create_table(
        "business_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("auth_user_sub", sa.String(length=64), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("invitation_id", sa.String(length=120), nullable=True),
        sa.Column("invited_email", sa.String(length=320), nullable=True),
        sa.Column("invited_phone", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "auth_user_sub", name="uq_business_member_sub"),
    )
    op.create_index("ix_business_members_business_id", "business_members", ["business_id"])
    op.create_index("ix_business_members_auth_user_sub", "business_members", ["auth_user_sub"])
    op.create_index("ix_business_members_status", "business_members", ["status"])
    op.create_index("ix_business_members_invitation_id", "business_members", ["invitation_id"])

    op.create_table(
        "external_emails",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("verification_hash", sa.String(length=64), nullable=True),
        sa.Column("verification_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("forward_official_mail", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "email", name="uq_business_external_email"),
    )
    op.create_index("ix_external_emails_business_id", "external_emails", ["business_id"])
    op.create_index("ix_external_emails_email", "external_emails", ["email"])
    op.create_index("ix_external_emails_status", "external_emails", ["status"])

    op.create_table(
        "official_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("external_message_id", sa.String(length=160), nullable=False),
        sa.Column("subject", sa.String(length=240), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agency_id", "external_message_id", name="uq_agency_external_message"),
    )
    op.create_index("ix_official_messages_business_id", "official_messages", ["business_id"])
    op.create_index("ix_official_messages_agency_id", "official_messages", ["agency_id"])
    op.create_index("ix_official_messages_status", "official_messages", ["status"])

    op.create_table(
        "message_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_reference", sa.String(length=255), nullable=True),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["official_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_message_deliveries_message_id", "message_deliveries", ["message_id"])
    op.create_index("ix_message_deliveries_status", "message_deliveries", ["status"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=160), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_actor_id", "audit_events", ["actor_id"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_business_id", "audit_events", ["business_id"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("message_deliveries")
    op.drop_table("official_messages")
    op.drop_table("external_emails")
    op.drop_table("business_members")
    op.drop_table("official_addresses")
    op.drop_table("agencies")
    op.drop_table("businesses")
