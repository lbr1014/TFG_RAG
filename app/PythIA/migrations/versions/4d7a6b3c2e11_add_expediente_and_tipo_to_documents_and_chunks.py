"""add expediente and tipo_documento to documents and chunks

Revision ID: 4d7a6b3c2e11
Revises: e4a1c0d9f321
Create Date: 2026-03-27 19:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4d7a6b3c2e11"
down_revision = "e4a1c0d9f321"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("numero_expediente", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("tipo_documento", sa.String(length=30), nullable=True))
        batch_op.create_index(batch_op.f("ix_documents_numero_expediente"), ["numero_expediente"], unique=False)
        batch_op.create_index(batch_op.f("ix_documents_tipo_documento"), ["tipo_documento"], unique=False)

    with op.batch_alter_table("chunks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("numero_expediente", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("tipo_documento", sa.String(length=30), nullable=True))
        batch_op.create_index(batch_op.f("ix_chunks_numero_expediente"), ["numero_expediente"], unique=False)
        batch_op.create_index(batch_op.f("ix_chunks_tipo_documento"), ["tipo_documento"], unique=False)


def downgrade():
    with op.batch_alter_table("chunks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_chunks_tipo_documento"))
        batch_op.drop_index(batch_op.f("ix_chunks_numero_expediente"))
        batch_op.drop_column("tipo_documento")
        batch_op.drop_column("numero_expediente")

    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_documents_tipo_documento"))
        batch_op.drop_index(batch_op.f("ix_documents_numero_expediente"))
        batch_op.drop_column("tipo_documento")
        batch_op.drop_column("numero_expediente")
