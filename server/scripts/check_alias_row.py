import asyncio
from app.core.database import AsyncSessionLocal
from app.models.product_alias import SupplierProductAlias
from app.utils.fuzzy import normalize_ref


async def main():
    async with AsyncSessionLocal() as session:
        # targets to check
        external = "210100"
        internal = "P199450235"
        ext_norm = normalize_ref(external)
        int_norm = normalize_ref(internal)

        from sqlalchemy import select
        stmt = select(SupplierProductAlias).where(
            (SupplierProductAlias.external_ref_normalized == ext_norm)
            | (SupplierProductAlias.internal_ref_normalized == int_norm)
        )
        q = await session.execute(stmt)
        rows = q.scalars().all()
        if not rows:
            print("No alias rows found for", external, internal)
            return
        for r in rows:
            print({
                "id": r.id,
                "supplier_key": r.supplier_key,
                "external_ref": r.external_ref,
                "external_ref_normalized": r.external_ref_normalized,
                "internal_ref": r.internal_ref,
                "internal_ref_normalized": r.internal_ref_normalized,
                "is_active": r.is_active,
                "usage_count": r.usage_count,
                "approved_by": r.approved_by,
                "approved_at": r.approved_at.isoformat() if r.approved_at else None,
            })


if __name__ == "__main__":
    asyncio.run(main())
