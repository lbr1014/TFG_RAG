"""
Autora: Lydia Blanco Ruiz
Script de migracion de Alembic para guardar si una consulta RAG se respondio con CPU o GPU.
"""

"""add execution device to consultas

Revision ID: 8d2e5f6a7b90
Revises: 5e4f3a2b1c0d
Create Date: 2026-04-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8d2e5f6a7b90"
down_revision = "5e4f3a2b1c0d"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("consultas", schema=None) as batch_op:
        batch_op.add_column(sa.Column("execution_device", sa.String(length=10), nullable=True))


def downgrade():
    with op.batch_alter_table("consultas", schema=None) as batch_op:
        batch_op.drop_column("execution_device")
