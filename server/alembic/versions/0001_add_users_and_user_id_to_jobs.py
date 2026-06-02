"""add users table and user_id to jobs

Revision ID: 0001_add_users
Revises:
Create Date: 2025-05-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_add_users"
down_revision = "e2f4a6b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("email", sa.String(), nullable=False, unique=True, index=True),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.add_column("jobs", sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True, index=True))


def downgrade() -> None:
    op.drop_column("jobs", "user_id")
    op.drop_table("users")