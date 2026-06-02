"""
clean_word_dictionary — audit and mark bad entries as ignored=True.

Bad entries are those that should never have been inserted:
  - product codes (P199420414, M400010432, BCF04H…)
  - document reference numbers (BL2460/2025, FA-2025/0531…)
  - financial amounts (6 576,000…)
  - dates (30/06/2025…)
  - pure numeric strings (77600, 4032185…)
  - phone numbers, fiscal IDs, emails

Entries are marked ignored=True (not deleted) so the history is preserved.
Run via:
    python -m app.services.clean_word_dictionary
or from within Python:
    from app.services.clean_word_dictionary import run_cleanup
    asyncio.run(run_cleanup(dry_run=True))
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.word_dictionary import WordDictionaryEntry
from app.services.value_protection import is_protected_value, is_dictionary_candidate

logger = logging.getLogger(__name__)


def _enum_value(value: Any) -> str:
    """
    SQLAlchemy Enum can return either a string or a Python enum.
    This helper always returns a clean uppercase string.
    """
    if value is None:
        return ""

    if hasattr(value, "value"):
        return str(value.value).upper()

    if hasattr(value, "name"):
        return str(value.name).upper()

    return str(value).upper()


def _normalize_for_detection(value: str | None) -> str:
    """
    Normalize only for detection/cleanup.
    Do not use this as business normalization.
    """
    if not value:
        return ""

    v = str(value).strip().lower()

    # remove parasite quotes around OCR tokens:
    # bl2460/2025""" -> bl2460/2025
    v = v.strip("\"'`“”‘’")

    # collapse spaces
    v = re.sub(r"\s+", " ", v)

    return v


def _is_hard_protected_value(value: str | None) -> bool:
    """
    Detect values that are certainly not dictionary words.
    This function is intentionally strict but avoids blocking manual OCR variants
    like d1sque -> DISQUE or racc0rd -> RACCORD.
    """
    v = _normalize_for_detection(value)
    if not v:
        return False

    # Email
    if re.search(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", v):
        return True

    # Dates: 30/06/2025, 30-06-2025, 2025-06-30
    if re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", v):
        return True

    if re.fullmatch(r"\d{4}[/-]\d{1,2}[/-]\d{1,2}", v):
        return True

    # Financial amounts / numeric strings:
    # 6 576,000 ; 6576.000 ; 77600 ; 4032185
    if re.fullmatch(r"[\d\s.,]+", v) and re.search(r"\d", v):
        return True

    # Document references: BL2460/2025, BC-2025/0142, FA-2025/0531
    if re.search(r"\b(bl|bc|fa|fac|fact|facture)[-_/]?\s*\d+", v, re.IGNORECASE):
        return True

    # Fiscal IDs / MF-like values
    # Fiscal IDs / MF-like values.
    # Attention: "timbre fiscal" is a valid invoice/payment term and must NOT be ignored.
    if re.search(r"\b(mf|m\.f)\s*[:\-/]?\s*[0-9]", v, re.IGNORECASE):
       
       
       return True

    if re.search(
        r"\b(matricule\s+fiscal|mat\s+fiscal|code\s+tva|c\.?tva)\b.*[0-9]",
        v,
        re.IGNORECASE,
    ):
         return True

    # Dimensions: 595X395X330, 1200*1000*980, 1000x2000
    if re.search(r"\d+\s*[xX*]\s*\d+", v):
        return True

    # Technical values with digits and separators:
    # BL2460/2025, ART-001, REF/2024, EW36PT=
    if re.search(r"\d", v) and re.search(r"[/_\-=]", v):
        return True

    return False


def _looks_like_generated_code_or_reference(
    value: str | None,
    source: str | None = None,
) -> bool:
    """
    Detect bad GPT/FUZZY entries that look like codes or references.

    Important:
    We do NOT apply the generic "letters + digits" rule to MANUAL entries,
    because manual seeds may intentionally contain OCR variants like:
      d1sque -> DISQUE
      racc0rd -> RACCORD
    """
    v = _normalize_for_detection(value)
    if not v:
        return False

    source_value = _enum_value(source)

    # These are always unsafe as dictionary words.
    if _is_hard_protected_value(v):
        return True

    # For manual entries, stop here.
    # Manual seeds can contain controlled OCR variants with digits.
    if source_value == "MANUAL":
        return False

    has_letter = bool(re.search(r"[a-zA-Z]", v))
    has_digit = bool(re.search(r"\d", v))
    alnum_len = len(re.sub(r"[^a-zA-Z0-9]", "", v))

    # 605n004, BCF04H, DW36PT, S096, P199420414, M400010432
    if has_letter and has_digit and alnum_len >= 4:
        return True

    # Mostly code-like with uppercase/lowercase + separators + digits.
    if has_digit and re.search(r"[/_.+\-=]", v):
        return True

    return False


async def run_cleanup(dry_run: bool = False) -> dict:
    """
    Scan word_dictionary and mark bad entries as ignored=True.

    Args:
        dry_run: if True, only report — do not write to DB.

    Returns:
        {"scanned": int, "bad_entries": list[str], "marked_ignored": int}
    """
    bad: list[str] = []

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WordDictionaryEntry).where(
                WordDictionaryEntry.ignored == False  # noqa: E712
            )
        )
        entries = result.scalars().all()

        for entry in entries:
            raw = entry.raw_form or ""
            canonical = entry.canonical_form or ""
            source = _enum_value(entry.source)

            def mark_bad() -> None:
                bad.append(raw)
                if not dry_run:
                    entry.ignored = True
                    entry.updated_at = datetime.now(timezone.utc)

            # Check 0: local strict cleanup for GPT/FUZZY/code-like entries.
            # This catches 605n004, BCF04H, DW36PT, BL2460/2025, etc.
            if _looks_like_generated_code_or_reference(raw, source):
                mark_bad()
                continue

            if _looks_like_generated_code_or_reference(canonical, source):
                mark_bad()
                continue

            # Manual entries are trusted seeds, unless caught above as hard-protected.
            # This prevents accidental removal of:
            #   d1sque -> DISQUE
            #   racc0rd -> RACCORD
            if source == "MANUAL":
                continue

            # Check 1: is it a protected value? code, amount, date, ref…
            if is_protected_value(raw):
                mark_bad()
                continue

            # Check 2: is it NOT a valid dictionary candidate?
            if not is_dictionary_candidate(raw, field_name="designation"):
                mark_bad()
                continue

            # Check 3: canonical_form looks like a protected value too
            if is_protected_value(canonical):
                mark_bad()
                continue

        if not dry_run and bad:
            await db.commit()

    result_summary = {
        "scanned": len(entries),
        "bad_entries": bad,
        "marked_ignored": len(bad) if not dry_run else 0,
        "dry_run": dry_run,
    }

    if bad:
        logger.info(
            "word_dictionary_cleanup scanned=%d bad=%d dry_run=%s",
            len(entries),
            len(bad),
            dry_run,
        )
        for b in bad[:20]:
            logger.info("  bad_entry: %r", b)
        if len(bad) > 20:
            logger.info("  … and %d more", len(bad) - 20)
    else:
        logger.info(
            "word_dictionary_cleanup: no bad entries found (scanned=%d)",
            len(entries),
        )

    return result_summary


def report_cleanup(dry_run: bool = True) -> dict:
    """Synchronous wrapper for use outside async contexts."""
    return asyncio.run(run_cleanup(dry_run=dry_run))


if __name__ == "__main__":
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(
        description="Clean word_dictionary of bad entries"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Actually mark entries as ignored (default: dry run only)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    summary = asyncio.run(run_cleanup(dry_run=not args.apply))
    print(_json.dumps(summary, indent=2, ensure_ascii=False))