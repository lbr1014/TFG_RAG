"""Make Lydia admin

Revision ID: 7b8a876a95ae
Revises: d99fa0431d49
Create Date: 2026-01-12 12:44:40.040330

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7b8a876a95ae'
down_revision = 'd99fa0431d49'
branch_labels = None
depends_on = None


def upgrade():
    # Crear usuario admin 
    op.execute("""
    INSERT INTO users (nombre, email, password_hash, last_login, is_admin)
    SELECT
        'Admin',
        'admin@gmail.com',
        'scrypt:32768:8:1$pl74Bt5pwnEUvxuX$3037992e1373b196b4e42fe4b56aea5410ef7c2602dc57a0686fd2d7b741c476f512441b39c4680c566c47b93205be9a6ebefd4db9341bdd07a9078547aa958f',
        NULL,
        TRUE
    WHERE NOT EXISTS (
        SELECT 1 FROM users WHERE email = 'admin@gmail.com'
    );
    """)

    # Si ya existía, assegurar que sea admin
    op.execute("""
    UPDATE users
    SET is_admin = True
    WHERE email = 'admin@gmail.com';
    """)


def downgrade():
    pass
