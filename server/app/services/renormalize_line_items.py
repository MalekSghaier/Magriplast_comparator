"""
Re-apply word_dictionary corrections to already-saved line_items.designation.

When a new entry is added to word_dictionary after a job has been processed,
this command updates the stored designations without reprocessing the PDFs.

Source for each line:
  designation (or raw_designation if designation is empty).
Never touched:
  raw_designation, ref_produit, ref_produit_normalized, qty,
  prix_unitaire, total_ligne_ht, tva_rate.

Usage:
    python -m app.services.renormalize_line_items              # dry-run (default)
    python -m app.services.renormalize_line_items --apply      # write to DB
    python -m app.services.renormalize_line_items --document-id <uuid>
    python -m app.services.renormalize_line_items --only-containing BLOUS
"""
import asyncio
import logging
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.line_item import LineItem
from app.models.document import Document  
from app.models.job import Job 
from app.services.adaptive_dictionary import word_dictionary
from app.models.match_result import MatchResult 
from app.models.audit_log import AuditLog        
from app.models.supplier_profile import SupplierProfile


logger = logging.getLogger(__name__)
async def _process_batch(
    items: list,
    dry_run: bool,
    only_containing: str | None = None,
) -> tuple[int, int, list[dict]]:
    """
    Core processing — separated from DB setup so tests can call it directly.

    Returns (scanned, changed, corrections).
    """
    scanned = 0
    changed = 0
    corrections: list[dict] = []

    for item in items:
        if only_containing:
            needle = only_containing.lower()
            des = (item.designation or "").lower()
            raw = (item.raw_designation or "").lower()
            if needle not in des and needle not in raw:
                continue

        scanned += 1
        source_text = item.designation or item.raw_designation
        if not source_text:
            continue

        normalized = await word_dictionary.normalize_text(
            source_text, field_name="designation"
        )

        if normalized and normalized != item.designation:
            corrections.append(
                {
                    "line_item_id": item.id,
                    "document_id": item.document_id,
                    "line_number": item.line_number,
                    "before": item.designation,
                    "after": normalized,
                }
            )
            if not dry_run:
                item.designation = normalized
            changed += 1

    return scanned, changed, corrections


async def renormalize_line_items(
    dry_run: bool = True,
    document_id: str | None = None,
    only_containing: str | None = None,
) -> dict:
    """
    Re-apply word_dictionary to designation of existing line_items.

    Returns a report dict:
      {dry_run, scanned, changed, corrections: [{line_item_id, document_id,
                                                  line_number, before, after}]}
    """
    async with AsyncSessionLocal() as db:
        stmt = select(LineItem)
        if document_id:
            stmt = stmt.where(LineItem.document_id == document_id)

        result = await db.execute(stmt)
        items = result.scalars().all()

        scanned, changed, corrections = await _process_batch(
            items, dry_run, only_containing
        )

        if not dry_run and changed:
            await db.commit()
            logger.info("renormalize committed %d changes", changed)

        logger.info(
            "renormalize_line_items dry_run=%s scanned=%d changed=%d",
            dry_run,
            scanned,
            changed,
        )
        return {
            "dry_run": dry_run,
            "scanned": scanned,
            "changed": changed,
            "corrections": corrections,
        }


if __name__ == "__main__":
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(
        description="Re-apply word_dictionary corrections to existing line_items.designation"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write changes to DB (default: dry-run, no write)",
    )
    parser.add_argument(
        "--document-id",
        default=None,
        metavar="UUID",
        help="Limit scan to a single document UUID",
    )
    parser.add_argument(
        "--only-containing",
        default=None,
        metavar="TEXT",
        help=(
            "Limit to lines where designation or raw_designation "
            "contains TEXT (case-insensitive)"
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    report = asyncio.run(
        renormalize_line_items(
            dry_run=not args.apply,
            document_id=args.document_id,
            only_containing=args.only_containing,
        )
    )

    mode = "DRY-RUN" if report["dry_run"] else "APPLIED"
    print(f"\n[{mode}] Scanned: {report['scanned']}  Changed: {report['changed']}\n")

    if report["corrections"]:
        print(f"Examples (first 10 of {len(report['corrections'])}):")
        for c in report["corrections"][:10]:
            print(f"  doc={c['document_id']}  line={c['line_number']}")
            print(f"    BEFORE: {c['before']!r}")
            print(f"    AFTER:  {c['after']!r}")
    else:
        print("No corrections found.")

    print("\n--- JSON report ---")
    print(_json.dumps(report, indent=2, ensure_ascii=False))
