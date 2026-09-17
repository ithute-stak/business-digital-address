"""add correspondence suite tables

Revision ID: 0004_correspondence_suite
Revises: 0003_reserved_mail_namespace
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_correspondence_suite"
down_revision = "0003_reserved_mail_namespace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_attachments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=240), nullable=False),
        sa.Column("content_type", sa.String(length=160), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256_hex", sa.String(length=64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["official_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "sha256_hex", name="uq_message_attachment_hash"),
    )
    op.create_index("ix_message_attachments_message_id", "message_attachments", ["message_id"], unique=False)
    op.create_index("ix_message_attachments_sha256_hex", "message_attachments", ["sha256_hex"], unique=False)

    op.create_table(
        "message_acknowledgements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column("actor_sub", sa.String(length=64), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["member_id"], ["business_members.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["official_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "member_id", name="uq_message_member_ack"),
    )
    op.create_index("ix_message_acknowledgements_message_id", "message_acknowledgements", ["message_id"], unique=False)
    op.create_index("ix_message_acknowledgements_member_id", "message_acknowledgements", ["member_id"], unique=False)
    op.create_index("ix_message_acknowledgements_actor_sub", "message_acknowledgements", ["actor_sub"], unique=False)

    op.create_table(
        "message_user_states",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("auth_user_sub", sa.String(length=64), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("starred", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["official_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "auth_user_sub", name="uq_message_user_state"),
    )
    op.create_index("ix_message_user_states_message_id", "message_user_states", ["message_id"], unique=False)
    op.create_index("ix_message_user_states_auth_user_sub", "message_user_states", ["auth_user_sub"], unique=False)
    op.create_index("ix_message_user_states_is_read", "message_user_states", ["is_read"], unique=False)
    op.create_index("ix_message_user_states_starred", "message_user_states", ["starred"], unique=False)
    op.create_index("ix_message_user_states_archived", "message_user_states", ["archived"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_message_user_states_archived", table_name="message_user_states")
    op.drop_index("ix_message_user_states_starred", table_name="message_user_states")
    op.drop_index("ix_message_user_states_is_read", table_name="message_user_states")
    op.drop_index("ix_message_user_states_auth_user_sub", table_name="message_user_states")
    op.drop_index("ix_message_user_states_message_id", table_name="message_user_states")
    op.drop_table("message_user_states")

    op.drop_index("ix_message_acknowledgements_actor_sub", table_name="message_acknowledgements")
    op.drop_index("ix_message_acknowledgements_member_id", table_name="message_acknowledgements")
    op.drop_index("ix_message_acknowledgements_message_id", table_name="message_acknowledgements")
    op.drop_table("message_acknowledgements")

    op.drop_index("ix_message_attachments_sha256_hex", table_name="message_attachments")
    op.drop_index("ix_message_attachments_message_id", table_name="message_attachments")
    op.drop_table("message_attachments")
