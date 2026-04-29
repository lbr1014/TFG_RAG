"""
Add country code to users.

Revision ID: 5e4f3a2b1c0d
Revises: 2b7c9e1f4a20
Create Date: 2026-04-20
"""

from alembic import op
import sqlalchemy as sa


revision = "5e4f3a2b1c0d"
down_revision = "2b7c9e1f4a20"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("country_code", sa.String(length=2), server_default="ES", nullable=False))
        batch_op.create_index(batch_op.f("ix_users_country_code"), ["country_code"], unique=False)


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_country_code"))
        batch_op.drop_column("country_code")
