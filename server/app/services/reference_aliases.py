from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from unidecode import unidecode

from app.core.logging import get_logger
from app.models.product_alias import SupplierProductAlias
from app.utils.fuzzy import normalize_ref

logger = get_logger(__name__)

_SUPPLIER_NOISE_WORDS = {
    "ETS",
    "ETABLISSEMENT",
    "ETABLISSEMENTS",
    "STE",
    "SOCIETE",
    "SARL",
    "SUARL",
    "SA",
    "SAS",
    "EURL",
    "TUNISIE",
    "TUNIS",
}


@dataclass(frozen=True)
class ReferenceAlias:
    id: str
    supplier_key: str
    external_ref: str
    external_ref_normalized: str
    internal_ref: str
    internal_ref_normalized: str
    supplier_name: str | None = None


def normalize_supplier_name(value: str | None) -> str | None:
    if not value:
        return None
    ascii_value = unidecode(value).upper()
    tokens = re.findall(r"[A-Z0-9]+", ascii_value)
    filtered = [token for token in tokens if token not in _SUPPLIER_NOISE_WORDS]
    normalized = "".join(filtered or tokens)
    return normalized or None


def build_supplier_alias_keys(
    *,
    supplier_id: str | None = None,
    supplier_code: str | None = None,
    supplier_name: str | None = None,
) -> list[str]:
    keys: list[str] = []
    if supplier_id:
        keys.append(f"id:{supplier_id}")
    code_key = normalize_supplier_name(supplier_code)
    if code_key:
        keys.append(f"code:{code_key}")
    name_key = normalize_supplier_name(supplier_name)
    if name_key:
        keys.append(f"name:{name_key}")
    return list(dict.fromkeys(keys))


def choose_supplier_alias_key(
    *,
    supplier_id: str | None = None,
    supplier_code: str | None = None,
    supplier_name: str | None = None,
) -> str | None:
    keys = build_supplier_alias_keys(
        supplier_id=supplier_id,
        supplier_code=supplier_code,
        supplier_name=supplier_name,
    )
    return keys[0] if keys else None


async def load_reference_alias_map(
    db: AsyncSession,
    *,
    supplier_id: str | None = None,
    supplier_code: str | None = None,
    supplier_name: str | None = None,
) -> dict[str, ReferenceAlias]:
    keys = build_supplier_alias_keys(
        supplier_id=supplier_id,
        supplier_code=supplier_code,
        supplier_name=supplier_name,
    )
    if not keys:
        return {}
    key_priority = {key: idx for idx, key in enumerate(keys)}

    result = await db.execute(
        select(SupplierProductAlias).where(
            SupplierProductAlias.is_active.is_(True),
            SupplierProductAlias.supplier_key.in_(keys),
        )
    )
    aliases: dict[str, ReferenceAlias] = {}
    rows = sorted(
        result.scalars().all(),
        key=lambda row: key_priority.get(row.supplier_key, len(key_priority)),
    )
    for row in rows:
        alias = ReferenceAlias(
            id=row.id,
            supplier_key=row.supplier_key,
            supplier_name=row.supplier_name,
            external_ref=row.external_ref,
            external_ref_normalized=row.external_ref_normalized,
            internal_ref=row.internal_ref,
            internal_ref_normalized=row.internal_ref_normalized,
        )
        existing = aliases.get(row.external_ref_normalized)
        if existing is not None:
            if existing.internal_ref_normalized != alias.internal_ref_normalized:
                logger.warning(
                    "reference_alias_conflict_ignored",
                    external_ref=row.external_ref_normalized,
                    kept_supplier_key=existing.supplier_key,
                    ignored_supplier_key=row.supplier_key,
                    kept_internal_ref=existing.internal_ref_normalized,
                    ignored_internal_ref=alias.internal_ref_normalized,
                )
            continue
        aliases[row.external_ref_normalized] = alias
    return aliases


async def approve_reference_alias(
    db: AsyncSession,
    *,
    supplier_key: str,
    external_ref: str,
    internal_ref: str,
    approved_by: str,
    supplier_id: str | None = None,
    supplier_name: str | None = None,
    source_job_id: str | None = None,
    source_line: dict | None = None,
    description: str | None = None,
    notes: str | None = None,
) -> tuple[SupplierProductAlias, bool]:
    external_norm = normalize_ref(external_ref)
    internal_norm = normalize_ref(internal_ref)
    if not external_norm or not internal_norm:
        raise ValueError("Both external_ref and internal_ref are required")

    result = await db.execute(
        select(SupplierProductAlias).where(
            SupplierProductAlias.supplier_key == supplier_key,
            SupplierProductAlias.external_ref_normalized == external_norm,
        )
    )
    existing = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if existing:
        if existing.internal_ref_normalized != internal_norm:
            raise ValueError(
                "Conflicting alias: this supplier external reference already maps "
                f"to {existing.internal_ref}"
            )
        existing.external_ref = external_ref
        existing.internal_ref = internal_ref
        existing.supplier_id = supplier_id or existing.supplier_id
        existing.supplier_name = supplier_name or existing.supplier_name
        existing.description = description or existing.description
        existing.source_job_id = source_job_id or existing.source_job_id
        existing.source_line = source_line or existing.source_line
        existing.approved_by = approved_by
        existing.approved_at = now
        existing.notes = notes or existing.notes
        existing.is_active = True
        return existing, False

    alias = SupplierProductAlias(
        supplier_id=supplier_id,
        supplier_key=supplier_key,
        supplier_name=supplier_name,
        external_ref=external_ref,
        external_ref_normalized=external_norm,
        internal_ref=internal_ref,
        internal_ref_normalized=internal_norm,
        description=description,
        confidence=1.0,
        is_active=True,
        source_job_id=source_job_id,
        source_line=source_line,
        approved_by=approved_by,
        approved_at=now,
        notes=notes,
    )
    db.add(alias)
    return alias, True


async def mark_aliases_used(db: AsyncSession, alias_ids: set[str]) -> None:
    if not alias_ids:
        return
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(SupplierProductAlias).where(SupplierProductAlias.id.in_(alias_ids))
    )
    for alias in result.scalars().all():
        alias.usage_count = (alias.usage_count or 0) + 1
        alias.last_used_at = now
