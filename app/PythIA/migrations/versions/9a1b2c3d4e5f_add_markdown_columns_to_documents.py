"""
Autora: Lydia Blanco Ruiz
Script de migración de Alembic para evolucionar el esquema de la base de datos.
"""

"""add markdown columns to documents

Revision ID: 9a1b2c3d4e5f
Revises: 4d7a6b3c2e11
Create Date: 2026-03-28 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9a1b2c3d4e5f"
down_revision = "4d7a6b3c2e11"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("markdown_path", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("markdown_updated_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("markdown_source_hash", sa.String(length=100), nullable=True))


def downgrade():
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_column("markdown_source_hash")
        batch_op.drop_column("markdown_updated_at")
        batch_op.drop_column("markdown_path")
