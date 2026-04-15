"""
Autora: Lydia Blanco Ruiz
Script de migración de Alembic para evolucionar el esquema de la base de datos.
"""

"""create markdown conversion state

Revision ID: e4a1c0d9f321
Revises: b2ef9f8a31b4
Create Date: 2026-03-12 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e4a1c0d9f321"
down_revision = "b2ef9f8a31b4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "markdown_conversion_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(length=255), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    with op.batch_alter_table("markdown_conversion_state", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_markdown_conversion_state_cancel_requested"), ["cancel_requested"], unique=False)
        batch_op.create_index(batch_op.f("ix_markdown_conversion_state_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_markdown_conversion_state_finished_at"), ["finished_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_markdown_conversion_state_started_at"), ["started_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_markdown_conversion_state_status"), ["status"], unique=False)

    with op.batch_alter_table("markdown_conversion_state", schema=None) as batch_op:
        batch_op.alter_column("cancel_requested", server_default=None)


def downgrade():
    with op.batch_alter_table("markdown_conversion_state", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_markdown_conversion_state_status"))
        batch_op.drop_index(batch_op.f("ix_markdown_conversion_state_started_at"))
        batch_op.drop_index(batch_op.f("ix_markdown_conversion_state_finished_at"))
        batch_op.drop_index(batch_op.f("ix_markdown_conversion_state_created_at"))
        batch_op.drop_index(batch_op.f("ix_markdown_conversion_state_cancel_requested"))

    op.drop_table("markdown_conversion_state")
