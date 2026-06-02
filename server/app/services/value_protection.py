"""
Value protection — identifies tokens that must NEVER be altered by dictionary,
fuzzy matching, or GPT correction.

Public API:
  is_protected_value(value, field_name, supplier_profile) -> bool
    True = pass raw_value through without touching it.

  is_dictionary_candidate(token, field_name) -> bool
    True = this token is a real word that MAY be looked up / corrected in word_dictionary.
    False = protected value (code, amount, date, etc.) — do NOT touch.

  normalize_dictionary_key(value) -> str
    Stable lookup key: lowercase, no accents, collapsed spaces, no leading punctuation.
    Never transforms protected values.

  is_normalizable_field(field_name) -> bool
    True only for fields where dictionary correction is allowed.
"""
import re
from typing import TYPE_CHECKING
from unidecode import unidecode

if TYPE_CHECKING:
    from app.services.supplier_profile_detector import DetectedSupplierProfile

# ── Field names that are ALWAYS protected (no correction allowed) ─────────────
_PROTECTED_FIELDS: frozenset[str] = frozenset({
    "article_code",
    "reference",
    "ref_produit",
    "ref_produit_normalized",
    "document_number",
    "invoice_number",
    "order_number",
    "delivery_number",
    "receipt_number",
    "quantity",
    "qty",
    "unit_price",
    "prix_unitaire",
    "amount",
    "amount_ht",
    "total_ht",
    "total_ttc",
    "total_ligne_ht",
    "tax_rate",
    "tva_rate",
    "discount_rate",
    "remise_pct",
    "fodec",
    "timbre",
    "document_date",
    "date",
    "fiscal_id",
    "matricule_fiscal",
    "rib",
    "phone",
    "email",
    "ref_bc",
    "ref_bl",
    "ref_facture",
    "ref_bc_linked",
})

# ── Field names where normalisation IS allowed ────────────────────────────────
_NORMALIZABLE_FIELDS: frozenset[str] = frozenset({
    "designation",
    "column_header",
    "unit",
    "supplier_name",
    "product_word",
    "category",
    "label",
})

# ── Patterns that mark a value as a product code / technical reference ─────────
_CODE_PATTERNS: list[re.Pattern] = [
    # Alphanumeric mixed codes: P199420414, M400010432, BCF04H, DW36PT, S096
    re.compile(r'^[A-Za-z]{1,6}\d{2,}$'),
    re.compile(r'^\d{2,}[A-Za-z]{1,6}$'),
    re.compile(r'^[A-Za-z0-9]{3,}[-/_.*+x×][A-Za-z0-9]'),   # contains separator
    # Dimensions: 595X395X330, 1200*1000*980, 115X22.23
    re.compile(r'\d+[xX×*]\d+'),
    # Technical codes with slashes: C/C 595X395X330 F40, CA DO KL/KL F+C
    re.compile(r'[A-Za-z]+/[A-Za-z]+'),
    # Long pure numeric ref (order/invoice numbers): 20250612001
    re.compile(r'^\d{6,}$'),
    # Standard ref patterns: BC-2024-001, FAC/25/0012
    re.compile(r'^[A-Z]{2,6}[-/]\d{2,4}[-/]\d{2,8}$', re.IGNORECASE),
]

# ── Patterns for financial / date / contact values ─────────────────────────────
_FINANCIAL_PATTERN = re.compile(
    r'^\s*[\d\s]+[,.]?\d{0,3}\s*$'   # amount: "6 576,000" or "122.341"
)
_DATE_PATTERN = re.compile(
    r'\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}'
)
_FISCAL_PATTERN = re.compile(
    r'\d{7}[/\-][A-Z][/\-][A-Z][/\-][A-Z][/\-]\d{3}'  # Tunisian MF format
)
_EMAIL_PATTERN = re.compile(r'[\w.+-]+@[\w.-]+\.\w+')
_PHONE_PATTERN = re.compile(r'(?:\+?[\d\s\.\-]{8,15})')
_IBAN_PATTERN = re.compile(r'[A-Z]{2}\d{2}[\dA-Z]{4,}')


def is_protected_value(
    value: str,
    field_name: str | None = None,
    supplier_profile: "DetectedSupplierProfile | None" = None,
) -> bool:
    """
    Return True if this value must NOT be altered by any correction mechanism.

    Protection is granted when ANY of the following applies:
    A) field_name is in the protected-fields list
    B) value matches a product-code / technical-ref pattern
    C) value looks like a financial amount, date, or contact info
    D) value matches a supplier-specific ref_pattern from the profile
    """
    if not value or not value.strip():
        return False

    v = value.strip()
    if field_name and field_name.lower() in _PROTECTED_FIELDS:
        return True
    if _looks_like_code(v):
        return True
    if _DATE_PATTERN.search(v) and len(v) <= 12:
        return True
    if _FINANCIAL_PATTERN.match(v) and len(v) >= 1:
        return True
    if _FISCAL_PATTERN.search(v):
        return True
    if _EMAIL_PATTERN.search(v):
        return True
    if _IBAN_PATTERN.search(v):
        return True
    if supplier_profile is not None:
        for pat in (supplier_profile.ref_patterns or []):
            try:
                if re.search(pat, v, re.IGNORECASE):
                    return True
            except re.error:
                pass

    return False


def is_normalizable_field(field_name: str) -> bool:
    """
    Return True only for fields where dictionary / fuzzy / GPT normalisation
    is allowed.  Everything else defaults to protected (False).
    """
    return field_name.lower() in _NORMALIZABLE_FIELDS


def is_dictionary_candidate(token: str, field_name: str | None = None) -> bool:
    """
    Return True only if this token is a genuine word candidate for dictionary lookup.
    False (= do NOT touch) when the token:
    - is a product code / article reference
    - is a document number (BL/BC/facture)
    - is a financial amount
    - is a date
    - is a dimension / technical spec
    - is a phone / email / fiscal ID / RIB
    - corresponds to a protected field name
    True when the token looks like a real word that may have been garbled by OCR:
    - designation words (disk, disq, racc0rd)
    - column headers (qte, desig, p.u.ht)
    - units (pc, pcs, ml, kg)
    - generic commercial terms (facture, livraison, commande)
    """
    if not token or not token.strip():
        return False

    v = token.strip()

    # 1. Protected field name → never a candidate
    if field_name and field_name.lower() in _PROTECTED_FIELDS:
        return False

    # 2. Looks like a code / numeric value / date → never a candidate
    if is_protected_value(v, field_name=field_name):
        return False

    # 3. Too short (single char) or pure punctuation → not useful
    alnum = re.sub(r'[^A-Za-z0-9]', '', v)
    if len(alnum) < 2:
        return False

    # 4. Purely numeric token → amount / quantity, not a word
    if re.match(r'^\d[\d\s.,]*$', v):
        return False

    # 5. Contains only digits and separators → not a word
    if re.match(r'^[\d\s.,/\-]+$', v):
        return False

    # 6. Must contain at least one letter
    if not re.search(r'[A-Za-z]', v):
        return False

    # 7. Mixed letter+digit short token where digit ratio > 40% → likely a code, not a word
    # e.g. "S096", "4032185", "77600" — not words
    if len(alnum) <= 10 and re.search(r'\d', v):
        digit_ratio = sum(c.isdigit() for c in alnum) / len(alnum)
        if digit_ratio > 0.40:
            return False

    # Passed all guards → it's a candidate
    return True


def normalize_dictionary_key(value: str) -> str:
    """
    Produce a stable lookup key for word_dictionary.

    Rules:
    - strip leading/trailing whitespace
    - lowercase
    - remove accents (unidecode)
    - collapse multiple spaces to one
    - remove leading/trailing punctuation EXCEPT dots and hyphens inside words
      (to preserve keys like "p.u.ht" or "b.l")
    - never called on protected values (caller's responsibility)

    Examples:
      " Disqué "    -> "disque"
      "D1SQUE"      -> "d1sque"
      "Qté"         -> "qte"
      "Désignation" -> "designation"
      "P.U.HT"      -> "p.u.ht"
      "Bon de Commande" -> "bon de commande"
    """
    if not value:
        return ""
    v = value.strip()
    v = unidecode(v).lower()
    # Collapse whitespace
    v = re.sub(r'\s+', ' ', v)
    # Strip leading/trailing punctuation that is not useful
    v = re.sub(r'^[,;:!?@#$%^&*()\[\]{}]+', '', v)
    v = re.sub(r'[,;:!?@#$%^&*()\[\]{}]+$', '', v)
    return v.strip()


# ── Internal helpers ───────────────────────────────────────────────────────────

def _looks_like_code(value: str) -> bool:
    """Return True if the value looks like a product code or technical ref."""
    # Must have both letters and digits to be a code
    has_letter = bool(re.search(r'[A-Za-z]', value))
    has_digit = bool(re.search(r'\d', value))

    if has_letter and has_digit:
        # Short mixed tokens (4-20 chars) are almost always codes
        if 4 <= len(value.replace(' ', '')) <= 25:
            for pat in _CODE_PATTERNS:
                if pat.search(value):
                    return True
            # Any token that mixes letters+digits in compact form
            # e.g. S096, BCF04H, NPC10 — just 3-10 chars, no spaces
            stripped = value.replace('-', '').replace('/', '').replace('.', '')
            if 3 <= len(stripped) <= 15 and not value.count(' ') > 2:
                # Ratio of digits to total chars > 30% → likely a code
                digit_ratio = sum(c.isdigit() for c in stripped) / len(stripped)
                if digit_ratio >= 0.30:
                    return True

    # Dimension strings like "595X395X330" or "1200*1000"
    if re.search(r'\d+[xX×*]\d+', value):
        return True

    # Slash-separated codes: "C/C F+C" or "KL/KL"
    if re.search(r'[A-Za-z]+/[A-Za-z]+', value):
        return True

    return False
