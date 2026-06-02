"""Harden word_dictionary: add verified + supplier_id columns; add word_source LLM_SUGGESTED

Revision ID: c9f1a2b3d4e5
Revises: b2e4f38a9d1c
Create Date: 2026-05-15 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "c9f1a2b3d4e5"
down_revision: Union[str, None] = "b2e4f38a9d1c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def column_exists(table_name: str, column_name: str) -> bool:
    if not table_exists(table_name):
        return False

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = inspector.get_columns(table_name)
    return any(column["name"] == column_name for column in columns)


def index_exists(table_name: str, index_name: str) -> bool:
    if not table_exists(table_name):
        return False

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = inspector.get_indexes(table_name)
    return any(index["name"] == index_name for index in indexes)


def upgrade() -> None:
    # ── 1. Add `verified` column to word_dictionary ───────────────────────────
    # Default True so existing rows (MANUAL seed) remain trusted.
    if not column_exists("word_dictionary", "verified"):
        op.add_column(
            "word_dictionary",
            sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        )
    else:
        op.execute("UPDATE word_dictionary SET verified = true WHERE verified IS NULL")
        op.alter_column(
            "word_dictionary",
            "verified",
            existing_type=sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        )

    # ── 2. Add `supplier_id` column (nullable — null = global term) ───────────
    if not column_exists("word_dictionary", "supplier_id"):
        op.add_column(
            "word_dictionary",
            sa.Column("supplier_id", sa.String(36), nullable=True),
        )
    if not index_exists("word_dictionary", "ix_word_dictionary_supplier_id"):
        op.create_index("ix_word_dictionary_supplier_id", "word_dictionary", ["supplier_id"])

    # ── 3. Add LLM_SUGGESTED to the word_source enum ─────────────────────────
    # PostgreSQL requires ALTER TYPE … ADD VALUE for enum extension.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE word_source ADD VALUE IF NOT EXISTS 'LLM_SUGGESTED'")

    # ── 4. Mark existing GPT entries as unverified with capped weight ─────────
    op.execute("""
        UPDATE word_dictionary
        SET verified = false,
            weight   = LEAST(weight, 0.75)
        WHERE source = 'GPT'
    """)

    # ── 5. Create supplier_profile_candidates table ───────────────────────────
    if not table_exists("supplier_profile_candidates"):
        op.create_table(
            "supplier_profile_candidates",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("supplier_id", sa.String(36), nullable=True, index=True),
            sa.Column(
                "candidate_type",
                sa.Enum(
                    "ref_pattern", "column_layout", "ocr_correction", "product_term",
                    name="candidate_type_enum",
                    create_type=True,
                ),
                nullable=False,
            ),
            sa.Column("candidate_value", sa.String(500), nullable=False),
            sa.Column("evidence_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("0.5")),
            sa.Column(
                "first_seen",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
            sa.Column(
                "last_seen",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                onupdate=sa.func.now(),
            ),
            sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
    if not index_exists("supplier_profile_candidates", "ix_spc_supplier_type_value"):
        op.create_index(
            "ix_spc_supplier_type_value",
            "supplier_profile_candidates",
            ["supplier_id", "candidate_type", "candidate_value"],
        )


def downgrade() -> None:
    op.drop_table("supplier_profile_candidates")
    op.drop_index("ix_word_dictionary_supplier_id", table_name="word_dictionary")
    op.drop_column("word_dictionary", "supplier_id")
    op.drop_column("word_dictionary", "verified")
    # Note: PostgreSQL does not support removing enum values — manual rollback needed
    # for the LLM_SUGGESTED value if required.
