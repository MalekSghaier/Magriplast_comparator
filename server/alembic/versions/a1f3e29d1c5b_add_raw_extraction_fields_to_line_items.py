"""add raw extraction fields to line_items

Revision ID: a1f3e29d1c5b
Revises:
Create Date: 2026-05-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = "a1f3e29d1c5b"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = inspector.get_columns(table_name)
    return any(column["name"] == column_name for column in columns)


def add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if not column_exists(table_name, column.name):
        op.add_column(table_name, column)


def drop_column_if_exists(table_name: str, column_name: str) -> None:
    if column_exists(table_name, column_name):
        op.drop_column(table_name, column_name)


def upgrade() -> None:
    # Raw OCR strings preserved verbatim
    add_column_if_missing(
        "line_items",
        sa.Column("raw_reference", sa.String(500), nullable=True),
    )
    add_column_if_missing(
        "line_items",
        sa.Column("raw_designation", sa.String(2000), nullable=True),
    )
    add_column_if_missing(
        "line_items",
        sa.Column("raw_qty", sa.String(100), nullable=True),
    )
    add_column_if_missing(
        "line_items",
        sa.Column("raw_unit_price", sa.String(100), nullable=True),
    )
    add_column_if_missing(
        "line_items",
        sa.Column("raw_total", sa.String(100), nullable=True),
    )

    # Per-field OCR confidence scores
    add_column_if_missing(
        "line_items",
        sa.Column("reference_confidence", sa.Float(), nullable=True),
    )
    add_column_if_missing(
        "line_items",
        sa.Column("designation_confidence", sa.Float(), nullable=True),
    )
    add_column_if_missing(
        "line_items",
        sa.Column("quantity_confidence", sa.Float(), nullable=True),
    )
    add_column_if_missing(
        "line_items",
        sa.Column("unit_price_confidence", sa.Float(), nullable=True),
    )
    add_column_if_missing(
        "line_items",
        sa.Column("total_confidence", sa.Float(), nullable=True),
    )

    # Math consistency: qty * prix_unitaire ~= total_ligne_ht
    add_column_if_missing(
        "line_items",
        sa.Column("math_consistency_ok", sa.Boolean(), nullable=True),
    )

    # Structured confidence map and aggregate confidence
    add_column_if_missing(
        "line_items",
        sa.Column("field_confidence_map", JSONB(), nullable=True),
    )
    add_column_if_missing(
        "line_items",
        sa.Column(
            "extraction_confidence",
            sa.Float(),
            nullable=True,
            server_default=sa.text("1.0"),
        ),
    )
    add_column_if_missing(
        "line_items",
        sa.Column(
            "has_low_confidence",
            sa.Boolean(),
            nullable=True,
            server_default=sa.text("false"),
        ),
    )

    # Normalized product reference
    add_column_if_missing(
        "line_items",
        sa.Column("ref_produit_normalized", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    drop_column_if_exists("line_items", "ref_produit_normalized")
    drop_column_if_exists("line_items", "has_low_confidence")
    drop_column_if_exists("line_items", "extraction_confidence")
    drop_column_if_exists("line_items", "field_confidence_map")
    drop_column_if_exists("line_items", "math_consistency_ok")
    drop_column_if_exists("line_items", "total_confidence")
    drop_column_if_exists("line_items", "unit_price_confidence")
    drop_column_if_exists("line_items", "quantity_confidence")
    drop_column_if_exists("line_items", "designation_confidence")
    drop_column_if_exists("line_items", "reference_confidence")
    drop_column_if_exists("line_items", "raw_total")
    drop_column_if_exists("line_items", "raw_unit_price")
    drop_column_if_exists("line_items", "raw_qty")
    drop_column_if_exists("line_items", "raw_designation")
    drop_column_if_exists("line_items", "raw_reference")