"""
OCR confusion rules — character-level substitution candidates.

These rules help GENERATE candidate corrections for noisy OCR tokens.
They must NEVER be applied directly to:
  - product codes / references
  - financial amounts
  - dates
  - document numbers

Usage: call generate_candidates(token) to get a list of possible corrections,
then rank them against the dictionary or present to the user.
"""
import re
from itertools import product as itertools_product


# ── Substitution table (OCR confusable pairs) ─────────────────────────────────
# Each tuple: (ocr_char_or_seq, likely_real_char_or_seq)
_SUBSTITUTIONS: list[tuple[str, str]] = [
    # Digit / letter confusion
    ("0", "O"), ("O", "0"),
    ("1", "I"), ("I", "1"),
    ("1", "L"), ("L", "1"),
    ("5", "S"), ("S", "5"),
    ("8", "B"), ("B", "8"),
    ("6", "G"), ("G", "6"),
    ("2", "Z"), ("Z", "2"),
    ("4", "A"), ("A", "4"),
    # Multi-char confusion
    ("rn", "m"),
    ("m",  "rn"),
    ("cl", "d"),
    ("d",  "cl"),
    ("vv", "w"),
    ("w",  "vv"),
    ("li", "h"),
    ("ri", "n"),
    ("fi", "A"),
    # French diacritics stripped by OCR
    ("e",  "é"), ("e",  "è"), ("e",  "ê"), ("e",  "ë"),
    ("a",  "à"), ("a",  "â"), ("a",  "ä"),
    ("u",  "ù"), ("u",  "û"), ("u",  "ü"),
    ("i",  "î"), ("i",  "ï"),
    ("o",  "ô"), ("o",  "ö"),
    ("c",  "ç"),
    # Space artifacts
    (" ",  ""),   # missing space
]

# ── Regex patterns for common OCR spacing / merging errors ────────────────────
_SPACE_BREAK_PATTERN = re.compile(r'(\w)-\s+(\w)')   # "quan- tité" → "quantité"
_DOUBLE_SPACE_PATTERN = re.compile(r'  +')


def generate_candidates(token: str, max_candidates: int = 6) -> list[str]:
    """
    Generate plausible character-substitution candidates for an OCR token.

    Only applies to short tokens (≤ 20 chars).  Returns the original token
    among the candidates so callers can always fall back to it.
    """
    if not token or len(token) > 20:
        return [token]

    candidates: set[str] = {token}

    # Single-pass substitutions (one replacement at a time)
    for ocr_seq, real_seq in _SUBSTITUTIONS:
        if ocr_seq in token:
            candidates.add(token.replace(ocr_seq, real_seq, 1))
        # Case-insensitive for letter/digit pairs
        lower = token.lower()
        if ocr_seq.lower() in lower:
            idx = lower.find(ocr_seq.lower())
            replaced = token[:idx] + real_seq + token[idx + len(ocr_seq):]
            candidates.add(replaced)

    return list(candidates)[:max_candidates]


def fix_broken_spaces(text: str) -> str:
    """Repair common OCR line-break hyphenation and multiple-space artifacts."""
    text = _SPACE_BREAK_PATTERN.sub(r'\1\2', text)
    text = _DOUBLE_SPACE_PATTERN.sub(' ', text)
    return text.strip()


def is_ocr_noise(token: str) -> bool:
    """
    Heuristic: return True if a token looks like pure OCR noise
    (no intelligible word, mostly special characters or isolated chars).
    """
    if len(token) <= 1:
        return True
    # More than 60% non-alphanumeric chars
    alpha_ratio = sum(c.isalnum() for c in token) / len(token)
    return alpha_ratio < 0.40
