"""add supplier product aliases
Revision ID: e2f4a6b8c9d0
Revises: d1e2f3a4b5c6
Create Date: 2026-05-23 13:30:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e2f4a6b8c9d0"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def index_exists(table_name: str, index_name: str) -> bool:
    if not table_exists(table_name):
        return False

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = inspector.get_indexes(table_name)
    return any(index["name"] == index_name for index in indexes)


def unique_constraint_exists(table_name: str, constraint_name: str) -> bool:
    if not table_exists(table_name):
        return False

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    constraints = inspector.get_unique_constraints(table_name)
    return any(constraint["name"] == constraint_name for constraint in constraints)


def upgrade() -> None:
    if not table_exists("supplier_product_aliases"):
        op.create_table(
            "supplier_product_aliases",
            sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
            sa.Column("supplier_id", postgresql.UUID(as_uuid=False), nullable=True),
            sa.Column("supplier_key", sa.String(length=300), nullable=False),
            sa.Column("supplier_name", sa.String(length=500), nullable=True),
            sa.Column("external_ref", sa.String(length=200), nullable=False),
            sa.Column("external_ref_normalized", sa.String(length=200), nullable=False),
            sa.Column("internal_ref", sa.String(length=200), nullable=False),
            sa.Column("internal_ref_normalized", sa.String(length=200), nullable=False),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("source_job_id", postgresql.UUID(as_uuid=False), nullable=True),
            sa.Column("source_line", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("approved_by", sa.String(length=255), nullable=False),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("notes", sa.String(length=2000), nullable=True),
            sa.Column("usage_count", sa.Integer(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["source_job_id"], ["jobs.id"]),
            sa.ForeignKeyConstraint(["supplier_id"], ["supplier_profiles.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "supplier_key",
                "external_ref_normalized",
                name="uq_supplier_product_alias_external",
            ),
        )
    elif not unique_constraint_exists(
        "supplier_product_aliases",
        "uq_supplier_product_alias_external",
    ):
        op.create_unique_constraint(
            "uq_supplier_product_alias_external",
            "supplier_product_aliases",
            ["supplier_key", "external_ref_normalized"],
        )

    if not index_exists("supplier_product_aliases", "ix_supplier_product_aliases_supplier_id"):
        op.create_index(
            "ix_supplier_product_aliases_supplier_id",
            "supplier_product_aliases",
            ["supplier_id"],
        )
    if not index_exists("supplier_product_aliases", "ix_supplier_product_aliases_supplier_key"):
        op.create_index(
            "ix_supplier_product_aliases_supplier_key",
            "supplier_product_aliases",
            ["supplier_key"],
        )
    if not index_exists(
        "supplier_product_aliases",
        "ix_supplier_product_aliases_external_ref_normalized",
    ):
        op.create_index(
            "ix_supplier_product_aliases_external_ref_normalized",
            "supplier_product_aliases",
            ["external_ref_normalized"],
        )
    if not index_exists(
        "supplier_product_aliases",
        "ix_supplier_product_aliases_internal_ref_normalized",
    ):
        op.create_index(
            "ix_supplier_product_aliases_internal_ref_normalized",
            "supplier_product_aliases",
            ["internal_ref_normalized"],
        )
    if not index_exists("supplier_product_aliases", "ix_supplier_product_aliases_source_job_id"):
        op.create_index(
            "ix_supplier_product_aliases_source_job_id",
            "supplier_product_aliases",
            ["source_job_id"],
        )


def downgrade() -> None:
    if index_exists("supplier_product_aliases", "ix_supplier_product_aliases_source_job_id"):
        op.drop_index("ix_supplier_product_aliases_source_job_id", table_name="supplier_product_aliases")
    if index_exists("supplier_product_aliases", "ix_supplier_product_aliases_internal_ref_normalized"):
        op.drop_index("ix_supplier_product_aliases_internal_ref_normalized", table_name="supplier_product_aliases")
    if index_exists("supplier_product_aliases", "ix_supplier_product_aliases_external_ref_normalized"):
        op.drop_index("ix_supplier_product_aliases_external_ref_normalized", table_name="supplier_product_aliases")
    if index_exists("supplier_product_aliases", "ix_supplier_product_aliases_supplier_key"):
        op.drop_index("ix_supplier_product_aliases_supplier_key", table_name="supplier_product_aliases")
    if index_exists("supplier_product_aliases", "ix_supplier_product_aliases_supplier_id"):
        op.drop_index("ix_supplier_product_aliases_supplier_id", table_name="supplier_product_aliases")
    if table_exists("supplier_product_aliases"):
        op.drop_table("supplier_product_aliases")
