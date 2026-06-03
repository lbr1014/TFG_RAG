"""
Autora: Lydia Blanco Ruiz
Script de migracion de Alembic para evolucionar el esquema de la base de datos.
"""

"""add profile image to users

Revision ID: cc3d4e5f6a70
Revises: 8d2e5f6a7b90
Create Date: 2026-05-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "cc3d4e5f6a70"
down_revision = "8d2e5f6a7b90"
branch_labels = None
depends_on = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, "users", "profile_image"):
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.add_column(sa.Column("profile_image", sa.String(length=255), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_column(inspector, "users", "profile_image"):
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.drop_column("profile_image")
