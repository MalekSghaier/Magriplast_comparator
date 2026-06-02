"""
SupplierProfileDetector — detects and manages supplier profiles from raw document text.

Key rules:
  - MAGRIPLAST (and its aliases) is NEVER a supplier — it is the buyer/client.
  - The detector distinguishes document roles: issuer, supplier, customer.
  - Profile enrichment requires evidence_count >= 3 before a pattern is promoted.
  - Cold-start creates a GenericProfile when confidence is too low.
"""
import re
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.supplier_profile import SupplierProfile as SupplierProfileModel
from app.core.logging import get_logger

logger = get_logger(__name__)

# Minimum keyword overlap to consider a profile a match
MATCH_THRESHOLD = 0.35

# Pattern occurrences needed in a single document before mining
MIN_PATTERN_HITS = 2

# Evidence count before a candidate pattern is promoted to the profile
PROMOTION_EVIDENCE_COUNT = 3
PROMOTION_CONFIDENCE_THRESHOLD = 0.92

# ── Known buyers / clients — NEVER treat these as suppliers ──────────────────
# Add lowercase variants; comparison is always lowercased.
_KNOWN_CLIENTS: frozenset[str] = frozenset({
    "magriplast",
    "magri plast",
    "magriplast sarl",
    "magriplast s.a.r.l",
    "magriplast s.a.r.l.",
})

# ── Generic reference pattern candidates ─────────────────────────────────────
_GENERIC_REF_PATTERNS: list[str] = [
    r"[A-Z]{1,4}\d{6,12}",          # P199681847, MPC12345
    r"[A-Z]{2,4}-\d{2,4}-\d{2,8}",  # BC-2024-001234
    r"[A-Z]{2,6}\d{2,4}-\d{2,4}",   # NPC10-04
    r"[A-Z]{1,3}\d{3,6}[A-Z]?",     # Z10100, HI1234
    r"\d{4,8}[A-Z]{1,3}",           # 12345AB
    r"[A-Z]{2,4}\.\d{3,8}",         # ART.001234
]

# ── Column header vocabularies ────────────────────────────────────────────────
_COLUMN_VOCABULARIES: dict[str, list[str]] = {
    "ref_produit": ["réf", "ref", "reference", "référence", "article", "code", "cod", "art", "produit", "item"],
    "designation": ["désignation", "designation", "description", "libellé", "libelle", "intitulé", "intitule", "produit", "article"],
    "qty": ["quantité", "quantite", "qté", "qte", "qt", "nb", "nbre", "quantit", "qnt"],
    "unit": ["unité", "unite", "um", "u.m", "mesure", "unit"],
    "prix_unitaire": ["prix unit", "p.u", "pu", "prix u", "prix ht", "prix un", "tarif", "p.u.ht", "pu ht"],
    "tva_rate": ["tva", "t.v.a", "taxe", "%tva", "taux tva"],
    "remise": ["remise", "rem", "% rem", "rabais", "discount", "%rem"],
    "total_ligne": ["montant ht", "total ht", "montant", "total", "total ligne", "net ht", "tot ht", "montant net"],
}

# ── Document role signals ─────────────────────────────────────────────────────
# These labels indicate who is the issuer (= supplier) of the document
_ISSUER_LABELS: list[str] = [
    "fournisseur", "vendeur", "emetteur", "émetteur",
    "société", "societe", "raison sociale",
    "de :", "de:", "from:",
]
# These labels indicate who is the recipient (= client / buyer)
_RECIPIENT_LABELS: list[str] = [
    "client", "acheteur", "destinataire", "à :", "a:", "to:",
    "bon de commande", "commande", "réception", "reception",
]

# Tunisian supplier signal patterns
_SUPPLIER_SIGNAL_PATTERNS = [
    r"MF\s*:?\s*[\d/]+",
    r"RC\s*:?\s*[\w/]+",
    r"(?:TEL|TÉL|FAX)\s*:?\s*[\d\s\.\-\+]+",
    r"(?:RUE|AVENUE|BD|ROUTE)\s+.{5,40}",
    r"(?:TUNIS|SFAX|SOUSSE|NABEUL|BIZERTE|GABES|GAFSA|MONASTIR|ARIANA)\b",
]


class DocumentRole(str, Enum):
    ISSUER = "issuer"         # the company that issued the document (= supplier for invoices)
    SUPPLIER = "supplier"
    CUSTOMER = "customer"
    PURCHASE_ORDER_ISSUER = "purchase_order_issuer"
    DELIVERY_RECEIVER = "delivery_receiver"
    UNKNOWN = "unknown"


@dataclass
class DocumentRoleResult:
    name: str
    role: DocumentRole
    confidence: float
    position_hint: str = ""   # "header", "footer", "body"


@dataclass
class DetectedSupplierProfile:
    """Lightweight profile returned by SupplierProfileDetector."""
    id: str
    name: str
    supplier_code: str
    field_aliases: dict = field(default_factory=dict)
    number_locale: str = "fr"
    date_format: str = "%d/%m/%Y"
    price_tolerance: float | None = None
    quantity_tolerance: float | None = None
    ref_patterns: list[str] = field(default_factory=list)
    column_layout: dict = field(default_factory=dict)
    known_products: list[dict] = field(default_factory=list)
    ocr_corrections: dict = field(default_factory=dict)
    confidence_score: float = 0.5
    auto_detected: bool = False
    is_generic: bool = False


class SupplierProfileDetector:
    """
    Detects supplier identity from raw document text.

    Important invariants:
    - MAGRIPLAST is always the client/buyer — never the supplier.
    - If confidence < MATCH_THRESHOLD, a GenericProfile is returned (not a new profile).
    - Pattern enrichment requires PROMOTION_EVIDENCE_COUNT occurrences.
    """

    # In-memory candidate evidence store: {supplier_id: {pattern: count}}
    # Used until a real supplier_profile_candidates DB table is available.
    _pattern_candidates: dict[str, dict[str, int]] = {}

    async def detect_from_document(
        self,
        text: str,
        db: AsyncSession,
    ) -> DetectedSupplierProfile | None:
        """
        Main entry point.  Returns a DetectedSupplierProfile or None.

        1. Detect document roles (issuer vs client) to find the real supplier name.
        2. Guard against MAGRIPLAST being returned as supplier.
        3. Try matching against known profiles.
        4. On cold start: create a minimal profile only if confidence is sufficient.
        5. On very low confidence: return a GenericProfile.
        """
        # Step 1: detect roles
        roles = self._detect_document_roles(text)
        supplier_name = self._pick_supplier_from_roles(roles, text)

        # Step 2: guard — never use MAGRIPLAST as supplier
        if supplier_name and _is_known_client(supplier_name):
            logger.debug(
                "supplier_detection_skipped_known_client",
                name=supplier_name,
            )
            supplier_name = None

        # Step 3: match against existing profiles
        result = await db.execute(select(SupplierProfileModel))
        all_profiles = result.scalars().all()

        matched, confidence = self._match_existing_profile(text, all_profiles, supplier_name)
        if matched and confidence >= MATCH_THRESHOLD:
            # Enrich with evidence-count gating
            await self._enrich_profile_with_candidates(matched, text, db)
            logger.info(
                "supplier_profile_matched",
                supplier=matched.name,
                confidence=round(confidence, 3),
            )
            return self._to_dataclass(matched)

        # Step 4: cold start — only if we have a usable name
        if not supplier_name:
            supplier_name = self._extract_supplier_name_fallback(text)

        if not supplier_name or _is_known_client(supplier_name):
            logger.info(
                "supplier_profile_detection_no_signal",
                text_preview=text[:120],
            )
            return _make_generic_profile()

        # Confidence too low → generic profile
        if confidence < 0.20:
            logger.info(
                "supplier_profile_detection_low_confidence",
                confidence=round(confidence, 3),
                name=supplier_name,
            )
            return _make_generic_profile()

        ref_patterns = self.mine_ref_patterns(text)
        column_layout = self.detect_column_layout(text)
        doc_keywords = self._extract_doc_keywords(text)
        supplier_code = _make_supplier_code(supplier_name)

        new_model = SupplierProfileModel(
            supplier_code=supplier_code,
            name=supplier_name,
            ref_patterns=ref_patterns,
            column_layout=column_layout,
            doc_type_keywords=doc_keywords,
            confidence_score=0.4,
            auto_detected=True,
            last_seen=datetime.now(timezone.utc),
        )
        db.add(new_model)
        try:
            await db.flush()
            await db.commit()
        except Exception:
            await db.rollback()
            result2 = await db.execute(
                select(SupplierProfileModel).where(SupplierProfileModel.name == supplier_name)
            )
            existing = result2.scalar_one_or_none()
            if existing:
                return self._to_dataclass(existing)
            return _make_generic_profile()

        logger.info(
            "supplier_profile_auto_created",
            supplier=supplier_name,
            code=supplier_code,
            ref_patterns=ref_patterns,
        )
        return self._to_dataclass(new_model)

    def _detect_document_roles(self, text: str) -> list[DocumentRoleResult]:
        """
        Parse the document to identify which entity is the issuer and which is
        the client.  Uses label proximity heuristics.
        """
        results: list[DocumentRoleResult] = []
        lines = text.splitlines()
        text_lower = text.lower()

        # Check for explicit issuer labels in header (first 30 lines)
        header_lines = lines[:30]
        for i, line in enumerate(header_lines):
            line_lower = line.lower().strip()

            for label in _ISSUER_LABELS:
                if label in line_lower:
                    # Extract the name from the same or next line
                    name = _extract_name_near_label(line, header_lines, i)
                    if name and not _is_known_client(name):
                        results.append(DocumentRoleResult(
                            name=name,
                            role=DocumentRole.ISSUER,
                            confidence=0.80,
                            position_hint="header",
                        ))
                    break

            for label in _RECIPIENT_LABELS:
                if label in line_lower:
                    name = _extract_name_near_label(line, header_lines, i)
                    if name:
                        results.append(DocumentRoleResult(
                            name=name,
                            role=DocumentRole.CUSTOMER,
                            confidence=0.75,
                            position_hint="header",
                        ))
                    break

        # Fallback: first ALL-CAPS block in header that is NOT a known client
        for line in lines[:15]:
            stripped = line.strip()
            if (
                stripped
                and stripped == stripped.upper()
                and len(stripped.split()) >= 2
                and len(stripped) >= 5
                and not re.match(r"^(BON|FACTURE|COMMANDE|LIVRAISON|RECEPTION|N[°O])", stripped)
                and not _is_known_client(stripped)
            ):
                results.append(DocumentRoleResult(
                    name=stripped[:100],
                    role=DocumentRole.ISSUER,
                    confidence=0.55,
                    position_hint="header_caps",
                ))
                break

        return results

    def _pick_supplier_from_roles(
        self,
        roles: list[DocumentRoleResult],
        text: str,
    ) -> str | None:
        """Return the best candidate supplier name from role detection results."""
        # Prefer explicit ISSUER role with highest confidence
        issuers = [r for r in roles if r.role in (DocumentRole.ISSUER, DocumentRole.SUPPLIER)]
        issuers.sort(key=lambda r: r.confidence, reverse=True)
        for r in issuers:
            if r.name and not _is_known_client(r.name):
                return r.name
        return None

    def _extract_supplier_name_fallback(self, text: str) -> str | None:
        """Heuristic fallback when role detection finds nothing."""
        header = "\n".join(text.splitlines()[:20])
        for pattern in [
            r"(?:FOURNISSEUR|RAISON SOCIALE|VENDEUR|SOCIETE|SOCIÉTÉ)\s*[:\-]?\s*([A-ZÀ-Ÿ][A-ZÀ-Ÿa-zà-ÿ0-9\s&\.\-]{3,60})",
            r"(?:DE\s*:)\s*([A-ZÀ-Ÿ][A-ZÀ-Ÿa-zà-ÿ0-9\s&\.\-]{3,60})",
        ]:
            m = re.search(pattern, header, re.IGNORECASE)
            if m:
                name = m.group(1).strip().rstrip(".,;")
                if len(name) >= 3 and not _is_known_client(name):
                    return name

        for line in text.splitlines()[:15]:
            stripped = line.strip()
            if (
                stripped
                and stripped == stripped.upper()
                and len(stripped.split()) >= 2
                and len(stripped) >= 5
                and not re.match(r"^(BON|FACTURE|COMMANDE|LIVRAISON|RECEPTION)", stripped)
                and not _is_known_client(stripped)
            ):
                return stripped[:100]

        return None

    def mine_ref_patterns(self, text: str) -> list[str]:
        """Mine product reference patterns. Only returns patterns with >= MIN_PATTERN_HITS."""
        candidates = re.findall(
            r"\b([A-Z]{1,6}[\-\.]?[A-Z0-9]{2,}(?:[\-\.][A-Z0-9]+)*)\b",
            text.upper(),
        )
        candidates = [
            c for c in candidates
            if re.search(r"[A-Z]", c) and re.search(r"\d", c) and 4 <= len(c) <= 20
        ]
        if not candidates:
            return []

        freq = Counter(candidates)
        frequent = [tok for tok, cnt in freq.items() if cnt >= MIN_PATTERN_HITS]
        if not frequent:
            return []

        pattern_groups: dict[str, list[str]] = {}
        for tok in frequent:
            pat = _token_to_pattern(tok)
            pattern_groups.setdefault(pat, []).append(tok)

        ranked = sorted(
            pattern_groups.keys(),
            key=lambda p: sum(freq[t] for t in pattern_groups[p]),
            reverse=True,
        )
        return ranked[:8]

    def detect_column_layout(self, text: str) -> dict:
        """Detect table column headers from document text."""
        lines = text.splitlines()
        best_header_line: str | None = None
        best_score = 0
        best_positions: dict[str, int] = {}

        for line in lines:
            line_lower = line.lower()
            found: dict[str, int] = {}
            for col_name, vocab in _COLUMN_VOCABULARIES.items():
                for keyword in vocab:
                    idx = line_lower.find(keyword)
                    if idx != -1:
                        found[col_name] = idx
                        break
            score = len(found)
            if score > best_score:
                best_score = score
                best_header_line = line
                best_positions = found

        if best_score < 3 or best_header_line is None:
            return {}

        columns = [
            {"name": col, "x_position": pos}
            for col, pos in sorted(best_positions.items(), key=lambda kv: kv[1])
        ]
        return {"detected_header": best_header_line.strip(), "columns": columns}

    def _match_existing_profile(
        self,
        text: str,
        profiles: list[SupplierProfileModel],
        detected_name: str | None = None,
    ) -> tuple[SupplierProfileModel | None, float]:
        """Match text against known profiles; return best match + confidence."""
        text_upper = text.upper()
        best_profile: SupplierProfileModel | None = None
        best_conf = 0.0

        for profile in profiles:
            if _is_known_client(profile.name or ""):
                continue  # never match MAGRIPLAST as supplier

            score = 0.0
            checks = 0

            if profile.name and len(profile.name) >= 3 and profile.name.upper() in text_upper:
                score += 0.70
                checks += 1

            # Boost if detected name matches profile name
            if detected_name and profile.name:
                from rapidfuzz import fuzz as _fuzz
                sim = _fuzz.ratio(detected_name.upper(), profile.name.upper()) / 100.0
                if sim >= 0.85:
                    score += 0.30
                    checks += 1

            for alias in (profile.name_aliases or []):
                if alias and len(alias) >= 3 and alias.upper() in text_upper:
                    score += 0.50
                    checks += 1
                    break

            if profile.siret and profile.siret in text:
                score += 0.90
                checks += 1
            if profile.vat_number and profile.vat_number in text:
                score += 0.90
                checks += 1

            if profile.doc_type_keywords:
                kw_hits = sum(1 for kw in profile.doc_type_keywords if kw and kw.upper() in text_upper)
                kw_ratio = kw_hits / len(profile.doc_type_keywords)
                score += kw_ratio * 0.40
                checks += 1

            if profile.ref_patterns:
                for pat in profile.ref_patterns:
                    try:
                        if re.search(pat, text_upper):
                            score += 0.30
                            checks += 1
                            break
                    except re.error:
                        pass

            conf = min(score / max(checks, 1), 1.0) if checks > 0 else 0.0
            if conf > best_conf:
                best_conf = conf
                best_profile = profile

        return best_profile, best_conf

    async def _enrich_profile_with_candidates(
        self,
        profile: SupplierProfileModel,
        text: str,
        db: AsyncSession,
    ) -> None:
        """
        Enrich an existing profile using an evidence-count gate.

        A pattern is added to the profile only after appearing PROMOTION_EVIDENCE_COUNT
        times across different documents (tracked in _pattern_candidates in memory).
        """
        new_patterns = self.mine_ref_patterns(text)
        existing_patterns: list[str] = list(profile.ref_patterns or [])
        changed = False
        profile_id = str(profile.id)

        if profile_id not in self._pattern_candidates:
            self._pattern_candidates[profile_id] = {}

        for pat in new_patterns:
            if pat in existing_patterns:
                continue
            # Increment evidence counter
            self._pattern_candidates[profile_id][pat] = (
                self._pattern_candidates[profile_id].get(pat, 0) + 1
            )
            evidence = self._pattern_candidates[profile_id][pat]
            if evidence >= PROMOTION_EVIDENCE_COUNT:
                existing_patterns.append(pat)
                changed = True
                logger.info(
                    "supplier_pattern_promoted",
                    supplier=profile.name,
                    pattern=pat,
                    evidence_count=evidence,
                )

        if changed:
            profile.ref_patterns = existing_patterns[:12]
            profile.confidence_score = min(profile.confidence_score + 0.05, 1.0)
            profile.last_seen = datetime.now(timezone.utc)
            await db.commit()

    def _extract_doc_keywords(self, text: str) -> list[str]:
        """Extract supplier-specific keywords from document header."""
        header = text[:500].upper()
        words = re.findall(r"\b[A-ZÀ-Ÿ]{3,20}\b", header)
        _generic = {
            "BON", "DE", "COMMANDE", "LIVRAISON", "FACTURE", "DATE", "REF",
            "REFERENCE", "TOTAL", "TVA", "HT", "TTC", "PRIX", "QTE",
            "DESIGNATION", "ARTICLE", "MONTANT", "NET", "MAGRIPLAST",
        }
        freq = Counter(words)
        return [w for w, cnt in freq.most_common(15) if w not in _generic and cnt >= 1]

    def _to_dataclass(self, model: SupplierProfileModel) -> DetectedSupplierProfile:
        return DetectedSupplierProfile(
            id=model.id,
            name=model.name,
            supplier_code=model.supplier_code or _make_supplier_code(model.name),
            field_aliases=model.field_aliases or {},
            number_locale=model.number_locale or "fr",
            date_format=model.date_format or "%d/%m/%Y",
            price_tolerance=model.price_tolerance,
            quantity_tolerance=model.quantity_tolerance,
            ref_patterns=list(model.ref_patterns or []),
            column_layout=dict(model.column_layout or {}),
            known_products=list(model.known_products or []),
            ocr_corrections=dict(model.ocr_corrections or {}),
            confidence_score=model.confidence_score or 0.5,
            auto_detected=model.auto_detected or False,
            is_generic=False,
        )


# ── Utilities ──────────────────────────────────────────────────────────────────

def _is_known_client(name: str) -> bool:
    """Return True if this name is a known buyer/client (e.g. MAGRIPLAST)."""
    return name.lower().strip() in _KNOWN_CLIENTS


def _make_generic_profile() -> DetectedSupplierProfile:
    """Return a minimal profile used when supplier cannot be identified."""
    return DetectedSupplierProfile(
        id="GENERIC",
        name="GENERIC",
        supplier_code="GENERIC",
        confidence_score=0.0,
        auto_detected=True,
        is_generic=True,
    )


def _make_supplier_code(name: str) -> str:
    from unidecode import unidecode
    clean = unidecode(name.upper())
    words = re.findall(r"[A-Z0-9]+", clean)
    stop_words = {"SA", "SARL", "STE", "SNC", "LTD", "SPA", "DE", "DU", "ET", "LES"}
    significant = [w for w in words if w not in stop_words and len(w) >= 2]
    if not significant:
        significant = words
    code = "".join(w[:4] for w in significant[:2])[:10]
    return code or "UNKNOWN"


def _token_to_pattern(token: str) -> str:
    runs = re.findall(r"[A-Z]+|[0-9]+|[\-\.]", token)
    pattern_parts = []
    for run in runs:
        if re.match(r"^[A-Z]+$", run):
            pattern_parts.append(run if len(run) <= 3 else f"[A-Z]{{1,{len(run)}}}")
        elif re.match(r"^\d+$", run):
            pattern_parts.append(rf"\d{{{len(run)}}}")
        else:
            pattern_parts.append(re.escape(run))
    return "".join(pattern_parts)


def _extract_name_near_label(line: str, lines: list[str], line_idx: int) -> str | None:
    """Extract a name value from the same line (after ':') or the next line."""
    # Try same line after ':'
    if ":" in line:
        after_colon = line.split(":", 1)[1].strip()
        if len(after_colon) >= 3:
            return after_colon[:80]

    # Try next line
    if line_idx + 1 < len(lines):
        next_line = lines[line_idx + 1].strip()
        if len(next_line) >= 3 and not any(
            lbl in next_line.lower() for lbl in _ISSUER_LABELS + _RECIPIENT_LABELS
        ):
            return next_line[:80]

    return None


# Module-level singleton
supplier_profile_detector = SupplierProfileDetector()
