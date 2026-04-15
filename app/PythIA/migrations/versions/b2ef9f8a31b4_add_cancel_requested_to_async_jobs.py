"""
Autora: Lydia Blanco Ruiz
Script de migración de Alembic para evolucionar el esquema de la base de datos.
"""

"""add cancel requested to async jobs

Revision ID: b2ef9f8a31b4
Revises: 6d897e4a9c21
Create Date: 2026-03-11 17:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b2ef9f8a31b4"
down_revision = "6d897e4a9c21"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vector_update_state", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.create_index(batch_op.f("ix_vector_update_state_cancel_requested"), ["cancel_requested"], unique=False)

    with op.batch_alter_table("web_scraping_sate", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.create_index(batch_op.f("ix_web_scraping_sate_cancel_requested"), ["cancel_requested"], unique=False)

    with op.batch_alter_table("vector_update_state", schema=None) as batch_op:
        batch_op.alter_column("cancel_requested", server_default=None)

    with op.batch_alter_table("web_scraping_sate", schema=None) as batch_op:
        batch_op.alter_column("cancel_requested", server_default=None)


def downgrade():
    with op.batch_alter_table("web_scraping_sate", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_web_scraping_sate_cancel_requested"))
        batch_op.drop_column("cancel_requested")

    with op.batch_alter_table("vector_update_state", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_vector_update_state_cancel_requested"))
        batch_op.drop_column("cancel_requested")
