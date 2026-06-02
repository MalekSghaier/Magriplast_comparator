import re
from decimal import Decimal, InvalidOperation


# ── High-level parsing helpers ─────────────────────────────────────────────────

def parse_quantity(raw: str) -> tuple[Decimal | None, str]:
    """
    Parse a quantity value from OCR output.

    Returns (numeric_value, raw_string_preserved).

    Behaviour:
    - Strips leading tilde (~) or dash (-) prefix that scanners sometimes output
      to mean "approximately" (common in French ERP systems).
    - Normalises decimal separator (comma or period) without multiplying.
    - Returns the original stripped raw string so callers can display it.
    - Never rounds or scales the value.
    - Returns (None, raw) when the string cannot be parsed as a number.

    Generic examples (not specific to any supplier):
        "4.0"   → (Decimal("4.0"),  "4.0")
        "~ 4.0" → (Decimal("4.0"),  "4.0")
        "- 10"  → (Decimal("10"),   "10")
        "20,0"  → (Decimal("20.0"), "20,0")
        "1 200" → (Decimal("1200"), "1 200")
    """
    if not raw:
        return None, ""
    stripped = raw.strip()
    # Remove leading ~ or - (approximate/continuation markers)
    stripped = re.sub(r"^[~\-]\s*", "", stripped).strip()
    value = parse_french_number(stripped)
    return value, stripped


def parse_money(raw: str) -> tuple[Decimal | None, str]:
    """
    Parse a monetary value from OCR output.

    Returns (numeric_value, raw_string_preserved).

    Behaviour:
    - Preserves all decimal places exactly — never rounds or calls toFixed.
    - Supports both period (TND: "122.341") and comma ("122,341") decimal separators.
    - Supports French/Tunisian thousands separators (space, period, comma).
    - Returns the original raw string so callers can display the document value.
    - Returns (None, raw) when the string cannot be parsed.

    Generic examples:
        "122.341"  → (Decimal("122.341"), "122.341")
        "415.959"  → (Decimal("415.959"), "415.959")
        "1 200,50" → (Decimal("1200.50"), "1 200,50")
        "4.0"      → (Decimal("4.0"),     "4.0")
    """
    if not raw:
        return None, ""
    stripped = raw.strip()
    value = parse_french_number(stripped)
    return value, stripped


def parse_french_number(raw: str) -> Decimal | None:
    """
    Parse numbers in French/Tunisian locale format.
    Handles:
      "1 200,50"    → 1200.50   (space thousands sep, comma decimal)
      "1.200,50"    → 1200.50   (period thousands sep, comma decimal)
      "1,200.50"    → 1200.50   (comma thousands sep, period decimal)
      "1200.50"     → 1200.50   (plain international)
      "122.341"     → 122.341   (TND: 3 decimal places = millimes)
      "415.959"     → 415.959   (TND price with millimes)
      "1 200"       → 1200      (whole number, space thousands)
      "1200"        → 1200
    NOTE: single period is ALWAYS treated as decimal separator.
    TND (Tunisian Dinar) uses 3 decimal places (millimes), so "122.341" = 122.341 DT,
    not 122341. Only multiple periods (e.g. "1.200.000") are treated as thousands separators.
    """
    if not raw:
        return None

    raw = raw.strip()
    raw = re.sub(r"[€$£\s]", "", raw)
    raw = re.sub(r"[^\d.,]", "", raw)

    if not raw:
        return None
    comma_count = raw.count(",")
    dot_count = raw.count(".")

    try:
        if comma_count == 1 and dot_count == 0:
            # "1,50" → decimal | "1,200" → ambiguous | "240,278" → TND millimes
            parts = raw.split(",")
            decimal_digits = parts[1]
            if len(decimal_digits) <= 2:
                # Unambiguously decimal: "1,50" → 1.50
                raw = raw.replace(",", ".")
            elif len(decimal_digits) == 3:
                # Ambiguous: TND millimes ("240,278" = 240.278 DT) vs thousands ("1,278" = 1278)
                # Heuristic: integer part < 10 000 → TND millimes
                # (unit prices above 9 999 DT are extremely rare; large amounts
                #  use a space as the thousands separator in Tunisian documents)
                try:
                    integer_part = int(re.sub(r"\s", "", parts[0]))
                except ValueError:
                    integer_part = 0
                if integer_part < 10_000:
                    raw = raw.replace(",", ".")  # TND millimes: "240,278" → 240.278
                else:
                    raw = raw.replace(",", "")   # thousands: rare case
            else:
                # 4+ decimal digits → definitely thousands separator
                raw = raw.replace(",", "")
        elif dot_count == 1 and comma_count == 0:
            # Always treat a single period as decimal separator.
            # This correctly handles TND millime prices like "122.341" or "415.959".
            pass
        elif comma_count == 1 and dot_count >= 1:
            # "1.200,50" → 1200.50
            raw = raw.replace(".", "").replace(",", ".")
        elif dot_count == 1 and comma_count >= 1:
            # "1,200.50" → 1200.50
            raw = raw.replace(",", "")
        else:
            # Multiple separators of same type: "1.200.000" → 1200000
            raw = re.sub(r"[,.](?=.*[,.])", "", raw)
            raw = raw.replace(",", ".")

        return Decimal(raw)

    except InvalidOperation:
        return None