"""
Autora: Lydia Blanco Ruiz
Script de migración de Alembic para evolucionar el esquema de la base de datos.
"""

"""add markdown content to documents

Revision ID: 9c6d8f7a1b2c
Revises: e4a1c0d9f321
Create Date: 2026-03-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9c6d8f7a1b2c"
down_revision = "e4a1c0d9f321"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("markdown_content", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_column("markdown_content")
