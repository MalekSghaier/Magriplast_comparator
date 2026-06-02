import re
from datetime import date
from decimal import Decimal
from dateutil import parser as dateutil_parser
from app.utils.number_parser import parse_french_number
from app.core.logging import get_logger

logger = get_logger(__name__)
_TIMESTAMP_SUFFIX_RE = re.compile(r"\s+\d{1,2}:\d{2}(?::\d{2})?$")
def correct_ocr_numeric(raw: str) -> str:
    """
    Apply OCR character corrections to numeric and reference fields.

    Substitution rules:
    - Spaces are always stripped (thousands separators in numbers).
    - Letter↔digit substitutions (O↔0, l↔1, etc.) are applied ONLY when the
      character appears within a run of digits or at a position where a digit
      is unambiguously expected (surrounded by digits on both sides, or at
      the end of a digit run).

    This prevents "OM176652" from becoming "0M176652": the leading 'O' is
    followed by 'M' (a letter), so it is not inside a digit run and is
    left unchanged.
    """
    if not raw:
        return raw
    s = raw.replace(" ", "")
    _DIGIT_SUBS = {
        "O": "0", "o": "0",
        "l": "1", "I": "1",
        "S": "5",
        "B": "8",
        "G": "6",
        "Z": "2",
    }
    result = list(s)
    for idx, ch in enumerate(s):
        if ch not in _DIGIT_SUBS:
            continue # zedtha peak lel neighbors bech ynajm ya3ml determine lel contxt 5ir 
        prev_is_digit = idx > 0 and (s[idx - 1].isdigit() or s[idx - 1] in _DIGIT_SUBS)
        next_is_digit = idx < len(s) - 1 and (s[idx + 1].isdigit() or s[idx + 1] in _DIGIT_SUBS)
        if prev_is_digit or next_is_digit:
            result[idx] = _DIGIT_SUBS[ch]

    return "".join(result)

def normalize_reference(raw: str) -> str:
    """Normalize a document or product reference number."""
    if not raw:
        return ""
    corrected = correct_ocr_numeric(raw)
    return corrected.strip().upper()

def normalize_number(raw: str, supplier_locale: str = "fr") -> Decimal | None:
    """
    Parse and normalize a numeric value from OCR output.
    Applies OCR char correction first, then locale-aware number parsing.
    """
    if not raw:
        return None
    corrected = correct_ocr_numeric(str(raw))
    result = parse_french_number(corrected)
    if result is None:
        logger.debug("number_parse_failed", raw=raw, corrected=corrected)
    return result

def normalize_date(raw: str, supplier_date_fmt: str | None = None) -> date | None:
    """
    Parse a date string to a Python date object.

    Strips trailing timestamp suffixes (e.g. "15/01/26 15:33:15" → "15/01/26")
    before attempting format parsing. This handles ERP systems that embed a
    datetime in what visually appears to be a date field on the document.

    Tries: supplier-specific format → French common formats → dateutil fallback.
    Always stores internally as ISO 8601.
    """
    if not raw:
        return None

    raw = raw.strip()
    raw = _TIMESTAMP_SUFFIX_RE.sub("", raw).strip()

    if supplier_date_fmt:
        try:
            from datetime import datetime
            return datetime.strptime(raw, supplier_date_fmt).date()
        except ValueError:
            pass

    french_formats = [
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%Y-%m-%d",
        "%d/%m/%y",
        "%d %B %Y",
    ]

    for fmt in french_formats:
        try:
            from datetime import datetime
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    # Fallback: dateutil parser (handles many edge cases)
    try:
        return dateutil_parser.parse(raw, dayfirst=True).date()
    except Exception:
        logger.debug("date_parse_failed raw=%r", raw)
        return None


def normalize_text(raw: str) -> str:
    """Clean a text field: strip whitespace, collapse multiple spaces."""
    if not raw:
        return ""
    return re.sub(r"\s+", " ", raw.strip())