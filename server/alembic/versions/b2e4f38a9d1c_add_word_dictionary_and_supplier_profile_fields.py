"""add word_dictionary table and supplier_profile dynamic fields

Revision ID: b2e4f38a9d1c
Revises: a1f3e29d1c5b
Create Date: 2026-05-14 00:00:00.000000
"""

from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "b2e4f38a9d1c"
down_revision: Union[str, None] = "a1f3e29d1c5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


WORD_CATEGORY_VALUES = [
    "PRODUCT",
    "UNIT",
    "BRAND",
    "ACTION",
    "MATERIAL",
    "MISC",
    "DOCUMENT",
    "HEADER",
    "PAYMENT",
]

WORD_SOURCE_VALUES = [
    "MANUAL",
    "GPT",
    "FUZZY",
]


# Seed data: generic industrial terms
_SEED_WORDS = [
    # Units
    ("pce", "PIECE", "UNIT"),
    ("pcs", "PIECE", "UNIT"),
    ("pc", "PIECE", "UNIT"),
    ("piece", "PIECE", "UNIT"),
    ("pièce", "PIECE", "UNIT"),
    ("ml", "ML", "UNIT"),
    ("mt", "MT", "UNIT"),
    ("kg", "KG", "UNIT"),
    ("kgs", "KG", "UNIT"),
    ("l", "L", "UNIT"),
    ("lit", "L", "UNIT"),
    ("litre", "L", "UNIT"),
    ("m", "M", "UNIT"),
    ("m2", "M2", "UNIT"),
    ("m3", "M3", "UNIT"),
    ("t", "T", "UNIT"),
    ("tonne", "T", "UNIT"),
    ("g", "G", "UNIT"),
    ("gr", "G", "UNIT"),
    ("cm", "CM", "UNIT"),
    ("mm", "MM", "UNIT"),
    ("u", "PIECE", "UNIT"),
    ("un", "PIECE", "UNIT"),
    ("ens", "ENSEMBLE", "UNIT"),
    ("lot", "LOT", "UNIT"),
    ("bte", "BOITE", "UNIT"),
    ("boite", "BOITE", "UNIT"),
    ("rouleau", "ROULEAU", "UNIT"),
    ("rl", "ROULEAU", "UNIT"),
    ("sac", "SAC", "UNIT"),
    ("bidon", "BIDON", "UNIT"),
    ("botte", "BOTTE", "UNIT"),

    # Column header abbreviations / OCR corruptions
    ("qte", "QUANTITE", "HEADER"),
    ("qte.", "QUANTITE", "HEADER"),
    ("qté", "QUANTITE", "HEADER"),
    ("qto", "QUANTITE", "HEADER"),
    ("qtô", "QUANTITE", "HEADER"),
    ("qt", "QUANTITE", "HEADER"),
    ("quantite", "QUANTITE", "HEADER"),
    ("quantité", "QUANTITE", "HEADER"),

    ("ref", "REFERENCE", "HEADER"),
    ("ref.", "REFERENCE", "HEADER"),
    ("réf", "REFERENCE", "HEADER"),
    ("référence", "REFERENCE", "HEADER"),
    ("reference", "REFERENCE", "HEADER"),

    ("dsig", "DESIGNATION", "HEADER"),
    ("desig", "DESIGNATION", "HEADER"),
    ("désig", "DESIGNATION", "HEADER"),
    ("designation", "DESIGNATION", "HEADER"),
    ("désignation", "DESIGNATION", "HEADER"),
    ("description", "DESIGNATION", "HEADER"),
    ("libelle", "DESIGNATION", "HEADER"),
    ("libellé", "DESIGNATION", "HEADER"),

    ("pu", "PRIX_UNITAIRE", "HEADER"),
    ("p.u", "PRIX_UNITAIRE", "HEADER"),
    ("p.u.", "PRIX_UNITAIRE", "HEADER"),
    ("puht", "PRIX_UNITAIRE_HT", "HEADER"),
    ("p.u.ht", "PRIX_UNITAIRE_HT", "HEADER"),
    ("prix un", "PRIX_UNITAIRE", "HEADER"),
    ("prix unit", "PRIX_UNITAIRE", "HEADER"),
    ("prix unitaire", "PRIX_UNITAIRE", "HEADER"),

    ("montant", "MONTANT", "HEADER"),
    ("mnt", "MONTANT", "HEADER"),
    ("montant ht", "MONTANT_HT", "HEADER"),
    ("total ht", "MONTANT_HT", "HEADER"),
    ("total h.t", "MONTANT_HT", "HEADER"),
    ("total ttc", "TOTAL_TTC", "HEADER"),

    # Document type keywords
    ("bc", "BON_COMMANDE", "DOCUMENT"),
    ("b.c", "BON_COMMANDE", "DOCUMENT"),
    ("b.c.", "BON_COMMANDE", "DOCUMENT"),
    ("bon de commande", "BON_COMMANDE", "DOCUMENT"),
    ("commande", "BON_COMMANDE", "DOCUMENT"),

    ("bl", "BON_LIVRAISON", "DOCUMENT"),
    ("b.l", "BON_LIVRAISON", "DOCUMENT"),
    ("b.l.", "BON_LIVRAISON", "DOCUMENT"),
    ("bon de livraison", "BON_LIVRAISON", "DOCUMENT"),
    ("livraison", "BON_LIVRAISON", "DOCUMENT"),

    ("fac", "FACTURE", "DOCUMENT"),
    ("fact", "FACTURE", "DOCUMENT"),
    ("facture", "FACTURE", "DOCUMENT"),

    ("reception", "RECEPTION", "DOCUMENT"),
    ("réception", "RECEPTION", "DOCUMENT"),
    ("recu", "RECEPTION", "DOCUMENT"),
    ("reçu", "RECEPTION", "DOCUMENT"),

    # Tax / financial terms
    ("ht", "HORS_TAXES", "HEADER"),
    ("h.t", "HORS_TAXES", "HEADER"),
    ("h.t.", "HORS_TAXES", "HEADER"),

    ("ttc", "TTC", "HEADER"),
    ("t.t.c", "TTC", "HEADER"),
    ("t.t.c.", "TTC", "HEADER"),

    ("tva", "TVA", "HEADER"),
    ("t.v.a", "TVA", "HEADER"),
    ("t.v.a.", "TVA", "HEADER"),

    ("fodec", "FODEC", "HEADER"),
    ("fodéc", "FODEC", "HEADER"),

    ("remise", "REMISE", "HEADER"),
    ("rem", "REMISE", "HEADER"),

    ("timbre", "TIMBRE_FISCAL", "PAYMENT"),
    ("timbre fiscal", "TIMBRE_FISCAL", "PAYMENT"),

    ("net", "NET", "PAYMENT"),
    ("net a payer", "NET_A_PAYER", "PAYMENT"),
    ("net à payer", "NET_A_PAYER", "PAYMENT"),

    ("cheque", "CHEQUE", "PAYMENT"),
    ("chèque", "CHEQUE", "PAYMENT"),
    ("traite", "TRAITE", "PAYMENT"),
    ("echeance", "ECHEANCE", "PAYMENT"),
    ("échéance", "ECHEANCE", "PAYMENT"),

    # OCR digit/letter confusion helper tokens
    ("rn", "m", "MISC"),
    ("cl", "d", "MISC"),
    ("vv", "w", "MISC"),

    # Common materials
    ("acier", "ACIER", "MATERIAL"),
    ("inox", "INOX", "MATERIAL"),
    ("laiton", "LAITON", "MATERIAL"),
    ("aluminium", "ALUMINIUM", "MATERIAL"),
    ("plastique", "PLASTIQUE", "MATERIAL"),
    ("caoutchouc", "CAOUTCHOUC", "MATERIAL"),
    ("polyethylene", "POLYETHYLENE", "MATERIAL"),
    ("polyéthylène", "POLYETHYLENE", "MATERIAL"),
    ("polypropylene", "POLYPROPYLENE", "MATERIAL"),
    ("polypropylène", "POLYPROPYLENE", "MATERIAL"),
    ("polyamide", "POLYAMIDE", "MATERIAL"),
    ("pvc", "PVC", "MATERIAL"),
    ("pe", "PE", "MATERIAL"),
    ("pp", "PP", "MATERIAL"),
    ("nylon", "NYLON", "MATERIAL"),

    # Useful product words from test PDFs
    ("disque", "DISQUE", "PRODUCT"),
    ("disk", "DISQUE", "PRODUCT"),
    ("disc", "DISQUE", "PRODUCT"),
    ("disq", "DISQUE", "PRODUCT"),
    ("d1sque", "DISQUE", "PRODUCT"),
    ("disoue", "DISQUE", "PRODUCT"),

    ("raccord", "RACCORD", "PRODUCT"),
    ("racor", "RACCORD", "PRODUCT"),
    ("racc0rd", "RACCORD", "PRODUCT"),
    ("racord", "RACCORD", "PRODUCT"),

    ("tuyau", "TUYAU", "PRODUCT"),
    ("flexible", "FLEXIBLE", "PRODUCT"),
    ("collier", "COLLIER", "PRODUCT"),
    ("serrage", "SERRAGE", "PRODUCT"),
    ("boulon", "BOULON", "PRODUCT"),
    ("boulons", "BOULON", "PRODUCT"),
    ("vis", "VIS", "PRODUCT"),
    ("meche", "MECHE", "PRODUCT"),
    ("mèche", "MECHE", "PRODUCT"),
    ("rivet", "RIVET", "PRODUCT"),
    ("cadenas", "CADENAS", "PRODUCT"),
    ("chaine", "CHAINE", "PRODUCT"),
    ("chaîne", "CHAINE", "PRODUCT"),
    ("decapant", "DECAPANT", "PRODUCT"),
    ("décapant", "DECAPANT", "PRODUCT"),
    ("silicone", "SILICONE", "PRODUCT"),
    ("gant", "GANT", "PRODUCT"),
    ("gants", "GANT", "PRODUCT"),

    ("shako", "SHAKO", "BRAND"),
    ("shak0", "SHAKO", "BRAND"),
    ("electrovanne", "ELECTROVANNE", "PRODUCT"),
    ("électrovanne", "ELECTROVANNE", "PRODUCT"),
    ("electroanne", "ELECTROVANNE", "PRODUCT"),
    ("temporisateur", "TEMPORISATEUR", "PRODUCT"),
    ("clavette", "CLAVETTE", "PRODUCT"),
    ("barreau", "BARREAU", "PRODUCT"),
    ("roulement", "ROULEMENT", "PRODUCT"),

    ("emballage", "EMBALLAGE", "PRODUCT"),
    ("cartonnage", "CARTONNAGE", "PRODUCT"),
    ("carton", "CARTON", "PRODUCT"),
    ("caisse", "CAISSE", "PRODUCT"),
    ("fond", "FOND", "PRODUCT"),
    ("couv", "COUVERCLE", "PRODUCT"),
    ("couvercle", "COUVERCLE", "PRODUCT"),
    ("film", "FILM", "PRODUCT"),
    ("bobine", "BOBINE", "PRODUCT"),
    ("pack", "PACK", "PRODUCT"),

    ("tole", "TOLE", "PRODUCT"),
    ("tôle", "TOLE", "PRODUCT"),
    ("profile", "PROFILE", "PRODUCT"),
    ("profilé", "PROFILE", "PRODUCT"),
    ("electrode", "ELECTRODE", "PRODUCT"),
    ("électrode", "ELECTRODE", "PRODUCT"),
    ("soudure", "SOUDURE", "PRODUCT"),
    ("rutile", "RUTILE", "PRODUCT"),
]


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


def constraint_exists(table_name: str, constraint_name: str) -> bool:
    if not table_exists(table_name):
        return False

    bind = op.get_bind()
    inspector = sa.inspect(bind)

    constraints = inspector.get_unique_constraints(table_name)
    return any(constraint["name"] == constraint_name for constraint in constraints)


def add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if not column_exists(table_name, column.name):
        op.add_column(table_name, column)


def enum_exists(enum_name: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = :name"),
        {"name": enum_name},
    )
    return result.fetchone() is not None


def ensure_word_category_enum() -> None:
    if not enum_exists("word_category"):
        op.execute(
            "CREATE TYPE word_category AS ENUM "
            "('PRODUCT', 'UNIT', 'BRAND', 'ACTION', 'MATERIAL', 'MISC', "
            "'DOCUMENT', 'HEADER', 'PAYMENT')"
        )
    else:
        # PostgreSQL enum ADD VALUE should run outside a normal transaction.
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE word_category ADD VALUE IF NOT EXISTS 'DOCUMENT'")
            op.execute("ALTER TYPE word_category ADD VALUE IF NOT EXISTS 'HEADER'")
            op.execute("ALTER TYPE word_category ADD VALUE IF NOT EXISTS 'PAYMENT'")


def ensure_word_source_enum() -> None:
    if not enum_exists("word_source"):
        op.execute("CREATE TYPE word_source AS ENUM ('MANUAL', 'GPT', 'FUZZY')")


def upgrade() -> None:
    # 1. Create / complete ENUM types
    ensure_word_category_enum()
    ensure_word_source_enum()

    word_category_enum = postgresql.ENUM(
        *WORD_CATEGORY_VALUES,
        name="word_category",
        create_type=False,
    )

    word_source_enum = postgresql.ENUM(
        *WORD_SOURCE_VALUES,
        name="word_source",
        create_type=False,
    )

    # 2. Create word_dictionary table
    if not table_exists("word_dictionary"):
        op.create_table(
            "word_dictionary",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("raw_form", sa.String(200), nullable=False),
            sa.Column("canonical_form", sa.String(200), nullable=False),
            sa.Column(
                "category",
                word_category_enum,
                nullable=False,
                server_default=sa.text("'MISC'::word_category"),
            ),
            sa.Column(
                "weight",
                sa.Float(),
                nullable=False,
                server_default=sa.text("1.0"),
            ),
            sa.Column(
                "source",
                word_source_enum,
                nullable=False,
                server_default=sa.text("'MANUAL'::word_source"),
            ),
            sa.Column(
                "usage_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

        op.create_index(
            "ix_word_dictionary_raw_form",
            "word_dictionary",
            ["raw_form"],
        )
        op.create_index(
            "ix_word_dictionary_raw_weight",
            "word_dictionary",
            ["raw_form", "weight"],
        )
        op.create_unique_constraint(
            "uq_word_dictionary_raw_form",
            "word_dictionary",
            ["raw_form"],
        )

    # 3. Add dynamic fields to supplier_profiles
    if table_exists("supplier_profiles"):
        add_column_if_missing(
            "supplier_profiles",
            sa.Column("supplier_code", sa.String(50), nullable=True),
        )

        if not constraint_exists("supplier_profiles", "uq_supplier_profiles_supplier_code"):
            op.create_unique_constraint(
                "uq_supplier_profiles_supplier_code",
                "supplier_profiles",
                ["supplier_code"],
            )

        add_column_if_missing(
            "supplier_profiles",
            sa.Column(
                "ref_patterns",
                JSONB(),
                nullable=True,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )

        add_column_if_missing(
            "supplier_profiles",
            sa.Column(
                "column_layout",
                JSONB(),
                nullable=True,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )

        add_column_if_missing(
            "supplier_profiles",
            sa.Column(
                "known_products",
                JSONB(),
                nullable=True,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )

        add_column_if_missing(
            "supplier_profiles",
            sa.Column(
                "ocr_corrections",
                JSONB(),
                nullable=True,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )

        add_column_if_missing(
            "supplier_profiles",
            sa.Column(
                "doc_type_keywords",
                JSONB(),
                nullable=True,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )

        add_column_if_missing(
            "supplier_profiles",
            sa.Column(
                "confidence_score",
                sa.Float(),
                nullable=True,
                server_default=sa.text("0.5"),
            ),
        )

        add_column_if_missing(
            "supplier_profiles",
            sa.Column(
                "auto_detected",
                sa.Boolean(),
                nullable=True,
                server_default=sa.text("false"),
            ),
        )

        add_column_if_missing(
            "supplier_profiles",
            sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        )

    # 4. Seed word_dictionary with generic industrial terms
    seed_columns = [
        sa.column("id", UUID(as_uuid=True)),
        sa.column("raw_form", sa.String()),
        sa.column("canonical_form", sa.String()),
        sa.column("category", word_category_enum),
        sa.column("weight", sa.Float()),
        sa.column("source", word_source_enum),
        sa.column("usage_count", sa.Integer()),
    ]
    has_verified = column_exists("word_dictionary", "verified")
    has_ignored = column_exists("word_dictionary", "ignored")
    has_supplier_id = column_exists("word_dictionary", "supplier_id")

    if has_verified:
        seed_columns.append(sa.column("verified", sa.Boolean()))
    if has_ignored:
        seed_columns.append(sa.column("ignored", sa.Boolean()))
    if has_supplier_id:
        seed_columns.append(sa.column("supplier_id", sa.String()))

    word_dict_table = sa.table("word_dictionary", *seed_columns)

    existing_raw_forms = set()
    result = op.get_bind().execute(sa.text("SELECT raw_form FROM word_dictionary"))
    existing_raw_forms = {row[0] for row in result}

    rows_to_insert = []
    for raw, canonical, category in _SEED_WORDS:
        if raw not in existing_raw_forms:
            row = {
                "id": uuid.uuid4(),
                "raw_form": raw,
                "canonical_form": canonical,
                "category": category,
                "weight": 1.0,
                "source": "MANUAL",
                "usage_count": 0,
            }
            if has_verified:
                row["verified"] = True
            if has_ignored:
                row["ignored"] = False
            if has_supplier_id:
                row["supplier_id"] = None

            rows_to_insert.append(row)

    if rows_to_insert:
        op.bulk_insert(word_dict_table, rows_to_insert)


def downgrade() -> None:
    # Remove supplier_profiles dynamic columns
    if table_exists("supplier_profiles"):
        if constraint_exists("supplier_profiles", "uq_supplier_profiles_supplier_code"):
            op.drop_constraint(
                "uq_supplier_profiles_supplier_code",
                "supplier_profiles",
                type_="unique",
            )

        for col in [
            "last_seen",
            "auto_detected",
            "confidence_score",
            "doc_type_keywords",
            "ocr_corrections",
            "known_products",
            "column_layout",
            "ref_patterns",
            "supplier_code",
        ]:
            if column_exists("supplier_profiles", col):
                op.drop_column("supplier_profiles", col)

    # Drop word_dictionary
    if table_exists("word_dictionary"):
        op.drop_table("word_dictionary")

    # Drop ENUMs
    if enum_exists("word_source"):
        op.execute("DROP TYPE word_source")

    if enum_exists("word_category"):
        op.execute("DROP TYPE word_category")
