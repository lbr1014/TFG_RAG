"""
Autora: Lydia Blanco Ruiz
Script de migración de Alembic para evolucionar el esquema de la base de datos.
"""

"""add rag_evaluation_state

Revision ID: f3a8c9d2e1b4
Revises: e2c1a4b7d9f1
Create Date: 2026-05-28 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = "f3a8c9d2e1b4"
down_revision = "e2c1a4b7d9f1"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "rag_evaluation_state" in inspector.get_table_names():
        return

    op.create_table(
        "rag_evaluation_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued", index=True),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.String(length=255), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("output_dir", sa.String(length=512), nullable=True),
        sa.Column("results_json_path", sa.String(length=512), nullable=True),
        sa.Column("row_results_json_path", sa.String(length=512), nullable=True),
        sa.Column("config_json_path", sa.String(length=512), nullable=True),
        sa.Column("ares_questions_json_path", sa.String(length=512), nullable=True),
        sa.Column("ares_dataset_json_path", sa.String(length=512), nullable=True),
        sa.Column("ares_dataset_tsv_path", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Postgres: evitar fallos si se reintenta tras un arranque interrumpido.
    op.execute("CREATE INDEX IF NOT EXISTS ix_rag_evaluation_state_status ON rag_evaluation_state (status)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rag_evaluation_state_cancel_requested ON rag_evaluation_state (cancel_requested)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_rag_evaluation_state_created_at ON rag_evaluation_state (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_rag_evaluation_state_started_at ON rag_evaluation_state (started_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_rag_evaluation_state_finished_at ON rag_evaluation_state (finished_at)")


def downgrade():
    op.drop_index(op.f("ix_rag_evaluation_state_finished_at"), table_name="rag_evaluation_state")
    op.drop_index(op.f("ix_rag_evaluation_state_started_at"), table_name="rag_evaluation_state")
    op.drop_index(op.f("ix_rag_evaluation_state_created_at"), table_name="rag_evaluation_state")
    op.drop_index(op.f("ix_rag_evaluation_state_cancel_requested"), table_name="rag_evaluation_state")
    op.drop_index(op.f("ix_rag_evaluation_state_status"), table_name="rag_evaluation_state")
    op.drop_table("rag_evaluation_state")
