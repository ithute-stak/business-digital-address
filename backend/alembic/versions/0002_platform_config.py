"""add database-backed platform configuration

Revision ID: 0002_platform_config
Revises: 0001_bda_core
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_platform_config"
down_revision = "0001_bda_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_configuration",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portal_base_url", sa.String(length=255), nullable=False),
        sa.Column("official_email_domain", sa.String(length=253), nullable=False),
        sa.Column("updated_by", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id = 1", name="ck_platform_configuration_singleton"),
    )
    op.execute(
        sa.text(
            "INSERT INTO platform_configuration "
            "(id, portal_base_url, official_email_domain, updated_by) "
            "VALUES (1, :portal, :domain, :actor)"
        ).bindparams(
            portal="https://business.ithute.co.ls",
            domain="ithute.co.ls",
            actor="migration:0002_platform_config",
        )
    )


def downgrade() -> None:
    op.drop_table("platform_configuration")
