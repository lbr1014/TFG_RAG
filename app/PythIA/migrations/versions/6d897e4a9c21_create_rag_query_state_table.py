"""
Autora: Lydia Blanco Ruiz
Script de migración de Alembic para evolucionar el esquema de la base de datos.
"""

"""create rag query state table

Revision ID: 6d897e4a9c21
Revises: f3b1b7c9d2aa
Create Date: 2026-03-11 17:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6d897e4a9c21"
down_revision = "f3b1b7c9d2aa"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rag_query_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("message", sa.String(length=255), nullable=True),
        sa.Column("result_payload", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    with op.batch_alter_table("rag_query_state", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_rag_query_state_cancel_requested"), ["cancel_requested"], unique=False)
        batch_op.create_index(batch_op.f("ix_rag_query_state_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_rag_query_state_finished_at"), ["finished_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_rag_query_state_started_at"), ["started_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_rag_query_state_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_rag_query_state_user_id"), ["user_id"], unique=False)


def downgrade():
    with op.batch_alter_table("rag_query_state", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_rag_query_state_user_id"))
        batch_op.drop_index(batch_op.f("ix_rag_query_state_status"))
        batch_op.drop_index(batch_op.f("ix_rag_query_state_started_at"))
        batch_op.drop_index(batch_op.f("ix_rag_query_state_finished_at"))
        batch_op.drop_index(batch_op.f("ix_rag_query_state_created_at"))
        batch_op.drop_index(batch_op.f("ix_rag_query_state_cancel_requested"))

    op.drop_table("rag_query_state")
