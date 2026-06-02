import re
from dataclasses import dataclass, field
from app.services.classifier import DocType, ClassificationResult
from app.core.logging import get_logger

logger = get_logger(__name__)
@dataclass
class PageClassified:
    page_number: int
    doc_type: DocType
    confidence: float
    source_tier: int
    raw_text: str
    ref_hint: str = "" 

@dataclass
class DocumentGroup:
    """A logical document assembled from one or more consecutive pages."""
    doc_type: DocType
    pages: list[int]
    ref_document: str = ""
    classification_confidence: float = 1.0
    source_tier: int = 1
    combined_text: str = ""
    raw_ocr_data_per_page: dict = field(default_factory=dict)
    page_images_b64: dict = field(default_factory=dict)
    page_texts: dict = field(default_factory=dict)
_REF_PATTERNS = [
    r"(?:N[°o]?\s*)?BC[-\s/]?\d{2,4}[-\s/]?\d{2,6}",
    r"(?:N[°o]?\s*)?BL[-\s/]?\d{2,4}[-\s/]?\d{2,6}",
    r"(?:N[°o]?\s*)?FAC[-\s/]?\d{2,4}[-\s/]?\d{2,6}",
    r"(?:N[°o]?\s*)?FACT[-\s/]?\d{2,4}[-\s/]?\d{2,6}",
    r"\d{4}[-/]\d{3,6}",
]
_CONTINUATION_PATTERNS = [
    r"PAGE\s+\d+\s+(?:OF|SUR|DE)\s+\d+",
    r"\bSUITE\b",
    r"\bSUITE\s+ET\s+FIN\b",
    r"\*SUITE\*",   
    r"(?<!\w)(?<!\d\s)(?:PAGE\s+)?\d{1,2}\s*/\s*\d{1,2}(?!\s*\d)(?!\w)",
]

_BC_SUMMARY_KEYWORDS = [
    r"TOTAL\s+HORS\s+TAXES",
    r"REMISE\s+HORS\s+TAXE",
    r"NET\s+HORS\s+TAXES",
    r"ARRET[EÉ]\s+(?:LA\s+)?PRESENT",
    r"DIRECTION\s+G[EÉ]N[EÉ]RALE",
    r"APPROVISIONNEMENT",
]

_FACTURE_REQUIRED_KEYWORDS = [
    r"FACTURE\s+N[°o]",
    r"N[°o]\s+FACTURE",
    r"BON\s+DE\s+LIVRAISON",
    r"AVOIR\s+N[°o]",
]


def extract_ref_hint(text: str) -> str:
    """Try to extract a document reference number from page text."""
    text_upper = text.upper()
    for pattern in _REF_PATTERNS:
        match = re.search(pattern, text_upper)
        if match:
            return match.group(0).strip().replace(" ", "").replace("\t", "")
    return ""


def is_continuation_page(text: str) -> bool:
    """Detect if this is a continuation page (page 2 of 2, SUITE, etc.)."""
    text_upper = text.upper()
    for pattern in _CONTINUATION_PATTERNS:
        if re.search(pattern, text_upper):
            return True
    return False

def _refs_compatible(
    page_ref: str,
    group_ref: str,
    is_continuation: bool,
) -> bool:
    """
    Determine whether a page's reference is compatible with the current group.

    Rules (in priority order):
    1. If the page is a continuation (explicit marker detected) → always merge.
    2. If both refs are non-empty → merge only when they are identical.
    3. If the group has no ref yet but the page has one → merge and adopt the ref.
    4. If the page has no ref but the group has one → REJECT merge.
       A page with no detectable reference is more likely a different document
       than a continuation page that simply didn't repeat the reference.
    5. If neither has a ref → conservative: do NOT merge.
       Two consecutive ref-less same-type pages are treated as separate documents.
    """
    if is_continuation:
        return True
    if page_ref and group_ref:
        return page_ref == group_ref
    if not page_ref and group_ref:
        return False
    if page_ref and not group_ref:
        return True
    return False

def is_bc_summary_misclassified_as_facture(text: str, current_group_type: DocType) -> bool:
    """
    Detect when a page is a BC/BL summary/totals page that was misclassified as FACTURE.
    These pages contain totals keywords (TOTAL HORS TAXES, REMISE, NET A PAYER) and
    approval signatures (Direction générale, Approvisionnement) but no genuine FACTURE header.
    Returns True if the page should be merged with the preceding BC/BL group.
    """
    if current_group_type not in (DocType.BC, DocType.BL):
        return False
    text_upper = text.upper()
    has_bc_summary = any(re.search(p, text_upper) for p in _BC_SUMMARY_KEYWORDS)
    has_facture_marker = any(re.search(p, text_upper) for p in _FACTURE_REQUIRED_KEYWORDS)
    return has_bc_summary and not has_facture_marker


def group_pages_into_documents(classified_pages: list[PageClassified]) -> list[DocumentGroup]:
    """
    Assemble individually classified pages into logical document groups.

    Logic:
    1. Consecutive pages of same doc_type → same document IF refs match or continuation detected
    2. If ref_hint changes between same-type pages → different document (e.g., two BC in one PDF)
    3. UNKNOWN pages are isolated as their own group for human review
    """
    if not classified_pages:
        return []

    groups: list[DocumentGroup] = []
    current_group: DocumentGroup | None = None

    for page in classified_pages:
        if page.doc_type == DocType.RECEPTION:
            logger.info(
                "reception_page_skipped page=%d ref=%s",
                page.page_number,
                page.ref_hint,
            )
            continue   # ← skip ma ta3mlch group fi docuemtn mahoch tab3a les 3 type markih type jdid unkwon 

        if page.doc_type == DocType.UNKNOWN:
            if current_group:
                groups.append(current_group)
                current_group = None
            groups.append(DocumentGroup(
                doc_type=DocType.UNKNOWN,
                pages=[page.page_number],
                ref_document=page.ref_hint,
                classification_confidence=page.confidence,
                source_tier=page.source_tier,
                combined_text=page.raw_text,
            ))
            continue

        if current_group is None:
            current_group = DocumentGroup(
                doc_type=page.doc_type,
                pages=[page.page_number],
                ref_document=page.ref_hint,
                classification_confidence=page.confidence,
                source_tier=page.source_tier,
                combined_text=page.raw_text,
                page_texts={page.page_number: page.raw_text},
            )
            continue
        same_type = (page.doc_type == current_group.doc_type)
        continuation = is_continuation_page(page.raw_text)
        refs_ok = _refs_compatible(page.ref_hint, current_group.ref_document, continuation)
        bc_summary = (
            page.doc_type == DocType.FACTURE
            and is_bc_summary_misclassified_as_facture(page.raw_text, current_group.doc_type)
        )

        should_merge = (same_type and refs_ok) or bc_summary
        if should_merge:
            current_group.pages.append(page.page_number)
            current_group.combined_text += "\n" + page.raw_text
            current_group.page_texts[page.page_number] = page.raw_text
            current_group.classification_confidence = min(
                current_group.classification_confidence, page.confidence
            )
            current_group.source_tier = max(
                current_group.source_tier, page.source_tier  
            )
            if not current_group.ref_document and page.ref_hint:
                current_group.ref_document = page.ref_hint
        else:
            groups.append(current_group)
            current_group = DocumentGroup(
                doc_type=page.doc_type,
                pages=[page.page_number],
                ref_document=page.ref_hint,
                classification_confidence=page.confidence,
                source_tier=page.source_tier,
                combined_text=page.raw_text,
                page_texts={page.page_number: page.raw_text},
            )
    if current_group:
        groups.append(current_group)

    logger.info("pages_grouped", total_pages=len(classified_pages), groups_formed=len(groups))
    return groups