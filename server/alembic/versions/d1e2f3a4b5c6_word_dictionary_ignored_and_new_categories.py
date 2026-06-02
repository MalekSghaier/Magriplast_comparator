"""word_dictionary: add ignored column + DOCUMENT/HEADER/PAYMENT categories

Revision ID: d1e2f3a4b5c6
Revises: c9f1a2b3d4e5
Create Date: 2026-05-15 12:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c9f1a2b3d4e5"
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
    # 1. Add `ignored` column (default False — existing entries stay active)
    if not column_exists("word_dictionary", "ignored"):
        op.add_column(
            "word_dictionary",
            sa.Column("ignored", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
    else:
        op.execute("UPDATE word_dictionary SET ignored = false WHERE ignored IS NULL")
        op.alter_column(
            "word_dictionary",
            "ignored",
            existing_type=sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        )
    if not index_exists("word_dictionary", "ix_word_dictionary_active"):
        op.create_index(
            "ix_word_dictionary_active",
            "word_dictionary",
            ["ignored", "verified"],
        )

    # 2. Extend word_category enum with new values
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE word_category ADD VALUE IF NOT EXISTS 'DOCUMENT'")
        op.execute("ALTER TYPE word_category ADD VALUE IF NOT EXISTS 'HEADER'")
        op.execute("ALTER TYPE word_category ADD VALUE IF NOT EXISTS 'PAYMENT'")

    # 3. Re-classify existing ACTION entries that are really HEADER entries
    #    (headers like DESIGNATION, QUANTITE, PRIX_UNITAIRE_HT were seeded as ACTION)
    op.execute("""
        UPDATE word_dictionary
        SET category = 'HEADER'
        WHERE source = 'MANUAL'
          AND category = 'ACTION'
          AND canonical_form IN (
            'DESIGNATION', 'QUANTITE', 'UNITE', 'PRIX_UNITAIRE_HT',
            'MONTANT_HT', 'REFERENCE', 'ARTICLE', 'MONTANT',
            'TOTAL_TTC', 'NET_A_PAYER', 'REMISE', 'TVA', 'FODEC',
            'TIMBRE_FISCAL', 'HORS_TAXES', 'TTC',
            'FOURNISSEUR', 'CLIENT', 'NUMERO', 'DATE', 'PAGE',
            'ADRESSE', 'TELEPHONE', 'FAX', 'EMAIL', 'SITE_WEB',
            'MATRICULE_FISCAL', 'RIB', 'SIGNATURE', 'CACHET',
            'CHAUFFEUR', 'VEHICULE', 'CONDITIONS_LIVRAISON'
          )
    """)

    # 4. Re-classify document-type keywords as DOCUMENT
    op.execute("""
        UPDATE word_dictionary
        SET category = 'DOCUMENT'
        WHERE source = 'MANUAL'
          AND category = 'ACTION'
          AND canonical_form IN (
            'FACTURE', 'BON_COMMANDE', 'BON_LIVRAISON', 'RECEPTION'
          )
    """)

    # 5. Mark any entry whose raw_form looks like a protected value as ignored
    #    (safety cleanup for accidentally seeded codes)
    op.execute(r"""
        UPDATE word_dictionary
        SET ignored = true
        WHERE raw_form ~ '^[a-z]{1,4}[0-9]{4,}$'          -- e.g. p199420414
           OR raw_form ~ '^[0-9]{4,}[a-z]{1,4}$'          -- e.g. 4032185ab
           OR raw_form ~ '^[0-9]{5,}$'                     -- e.g. 77600
           OR raw_form ~ '[0-9]{1,2}[/\-\.][0-9]{1,2}[/\-\.][0-9]{2,4}'  -- dates
           OR raw_form ~ '^bl[0-9]'                        -- bl2460/2025
           OR raw_form ~ '^fa[-/][0-9]'                    -- fa-2025/0531
    """)


def downgrade() -> None:
    op.drop_index("ix_word_dictionary_active", table_name="word_dictionary")
    op.drop_column("word_dictionary", "ignored")
    # Note: PostgreSQL does not support removing enum values.
