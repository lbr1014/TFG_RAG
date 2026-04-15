"""
Autora: Lydia Blanco Ruiz
Script de migración de Alembic para evolucionar el esquema de la base de datos.
"""

"""drop markdown file metadata from documents

Revision ID: a7d9e4c2b1f0
Revises: c4f2b7a9d1e0
Create Date: 2026-04-09 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a7d9e4c2b1f0"
down_revision = "c4f2b7a9d1e0"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_column("markdown_source_hash")
        batch_op.drop_column("markdown_updated_at")
        batch_op.drop_column("markdown_path")


def downgrade():
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("markdown_path", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("markdown_updated_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("markdown_source_hash", sa.String(length=100), nullable=True))
