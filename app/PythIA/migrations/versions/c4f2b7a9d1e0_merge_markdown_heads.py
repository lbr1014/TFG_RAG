"""
Autora: Lydia Blanco Ruiz
Script de migración de Alembic para evolucionar el esquema de la base de datos.
"""

"""merge markdown migration heads

Revision ID: c4f2b7a9d1e0
Revises: 9a1b2c3d4e5f, 9c6d8f7a1b2c
Create Date: 2026-04-03 13:10:00.000000

"""
# revision identifiers, used by Alembic.
revision = "c4f2b7a9d1e0"
down_revision = ("9a1b2c3d4e5f", "9c6d8f7a1b2c")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
