import re
import httpx
import json
from dataclasses import dataclass
from enum import Enum
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class DocType(str, Enum):
    BC = "BC"
    BL = "BL"
    FACTURE = "FACTURE"
    RECEPTION = "RECEPTION"
    UNKNOWN = "UNKNOWN"


@dataclass
class ClassificationResult:
    doc_type: DocType
    confidence: float
    source_tier: int   # 1=rule, 2=LLM, 3=human
    reasoning: str = ""


# --- Keyword patterns — order matters, more specific first ---

_BC_KEYWORDS = [
    r"\bBON\s+DE\s+COMMANDE\b",
    r"\bBON\s+COMMANDE\b",
    r"\bCOMMANDE\s+N[°o]\b",
    r"\bN[°o]\s*BC[-\s]\d",
    r"\bBC[-/]\d{4}",
    r"\bPURCHASE\s+ORDER\b",
]

_RECEPTION_KEYWORDS = [
    r"\bRECEPTION\b",
    r"\bR[ÉE]CEPTION\b",
    r"\bBON\s+DE\s+R[ÉE]CEPTION\b",
    r"\bQT[OÔ]\s+R[OÔ]CEPT\b",
    r"\bQT[EÉ]\s+R[EÉ]CEPT\b",
    r"\bQT[OÔ]\s+BON\s+LIVR\b",
    r"\bORDRE\s+D[''E]ACHAT\s*:",
    r"\bR[OÔ]CEPTION\s*:",
    r"\bDATE\s+RE[ÇCOO]U\b",
    r"\bEXP[OÔ]DI[OÔ]\s+LE\b",
]

_BL_KEYWORDS = [
    r"\bBON\s+DE\s+LIVRAISON\b",
    r"\bBON\s+LIVRAISON\b",
    r"\bLIVRAISON\s+N[°o]\b",
    r"\bN[°o]\s*BL[-\s]\d",
    r"\bBL[-/]\d{4}",
    r"\bDELIVERY\s+NOTE\b",
    r"\bBORDEREAU\s+DE\s+LIVRAISON\b",
]

_FACTURE_KEYWORDS = [
    r"\bFACTURE\b",
    r"\bFACTURE\s+N[°o]\b",
    r"\bN[°o]\s*FAC[-\s]\d",
    r"\bFAC[-/]\d{4}",
    r"\bINVOICE\b",
    r"\bAVOIR\b",
    r"\bFACT\s+N[°o]\b",
]


def classify_page_rule_based(text: str) -> ClassificationResult:
    """
    Tier 1: Rule-based page classification.
    Examines the top 40% of page text for document type keywords.
    Returns confidence 0.0–1.0.
    """
    if not text or len(text.strip()) < 10:
        return ClassificationResult(
            doc_type=DocType.UNKNOWN,
            confidence=0.0,
            source_tier=1,
            reasoning="Insufficient text for classification",
        )

    lines = text.splitlines()
    top_section = "\n".join(lines[:max(1, len(lines) * 4 // 10)]).upper()
    full_text_upper = text.upper()

    scores: dict[DocType, float] = {
        DocType.BC: 0.0,
        DocType.BL: 0.0,
        DocType.FACTURE: 0.0,
    }

    for pattern in _RECEPTION_KEYWORDS:
        if re.search(pattern, top_section):
            scores.setdefault(DocType.RECEPTION, 0.0)
            scores[DocType.RECEPTION] += 0.4
        elif re.search(pattern, full_text_upper):
            scores.setdefault(DocType.RECEPTION, 0.0)
            scores[DocType.RECEPTION] += 0.15

    for pattern in _BC_KEYWORDS:
        if re.search(pattern, top_section):
            scores[DocType.BC] += 0.4
        elif re.search(pattern, full_text_upper):
            scores[DocType.BC] += 0.15

    for pattern in _BL_KEYWORDS:
        if re.search(pattern, top_section):
            scores[DocType.BL] += 0.4
        elif re.search(pattern, full_text_upper):
            scores[DocType.BL] += 0.15

    for pattern in _FACTURE_KEYWORDS:
        if re.search(pattern, top_section):
            scores[DocType.FACTURE] += 0.4
        elif re.search(pattern, full_text_upper):
            scores[DocType.FACTURE] += 0.15

    scores = {k: min(v, 1.0) for k, v in scores.items()}

    best_type = max(scores, key=lambda k: scores[k])
    best_score = scores[best_type]
    if best_score < 0.15:
        return ClassificationResult(
            doc_type=DocType.UNKNOWN,
            confidence=best_score,
            source_tier=1,
            reasoning=f"No clear keyword match. Scores: {scores}",
        )

    sorted_scores = sorted(scores.values(), reverse=True)
    if len(sorted_scores) > 1 and (sorted_scores[0] - sorted_scores[1]) < 0.1:
        best_score *= 0.7

    logger.debug("rule_classification", doc_type=best_type, confidence=best_score, scores=scores)

    return ClassificationResult(
        doc_type=best_type,
        confidence=min(best_score, 1.0),
        source_tier=1,
        reasoning=f"Keyword match. Scores: {scores}",
    )


async def classify_page_llm(
    text: str,
    image_b64: str | None = None,
) -> ClassificationResult:
    """
    Tier 2: LLM page classification.
    When image_b64 is provided (scanned pages), sends the page image alongside
    the OCR text so the model can correct OCR artifacts from the visual.
    temperature=0, JSON-only response.
    """
    system_prompt = """You are a document classification expert for a Tunisian manufacturing company.
You must classify a document page as one of: BC (Bon de Commande / Purchase Order), BL (Bon de Livraison / Delivery Note), FACTURE (Invoice), or UNKNOWN.

Respond ONLY with this exact JSON format, nothing else:
{
  "doc_type": "BC" | "BL" | "FACTURE" | "UNKNOWN",
  "confidence": 0.0 to 1.0,
  "reasoning": "brief explanation in one sentence"
}

Rules:
- BC = purchase order, lists products to be ordered with quantities and agreed prices
- BL = delivery note, confirms physical delivery of goods, usually no prices
- FACTURE = invoice, includes prices, totals, TVA, payment terms
- UNKNOWN = cannot determine with confidence"""

    if image_b64:
        user_content = [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{image_b64}",
                    "detail": "low",   # classification needs overview, not fine detail
                },
            },
            {
                "type": "text",
                "text": (
                    f"Classify this document page.\n\n"
                    f"OCR text (may contain errors — use the image above as ground truth):\n"
                    f"---\n{text[:2000]}\n---"
                ),
            },
        ]
    else:
        user_content = f"Classify this document page:\n\n---\n{text[:3000]}\n---"

    payload = {
        "model": settings.llm_model,
        "max_tokens": 200,
        "temperature": settings.llm_temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "content-type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()

        data = response.json()
        raw_text = data["choices"][0]["message"]["content"].strip()
        
        if not raw_text:
            logger.error("llm_classification_empty_response", response_data=data)
            return ClassificationResult(
                doc_type=DocType.UNKNOWN,
                confidence=0.0,
                source_tier=2,
                reasoning="LLM returned empty response",
            )
        
        # Strip markdown code fences if present
        raw_text = re.sub(r'^```(?:json)?\s*', '', raw_text, flags=re.MULTILINE)
        raw_text = re.sub(r'\s*```$', '', raw_text, flags=re.MULTILINE)
        
        parsed = json.loads(raw_text)
        doc_type = DocType(parsed["doc_type"])
        confidence = float(parsed.get("confidence", 0.7))
        reasoning = parsed.get("reasoning", "")

        logger.info("llm_classification", doc_type=doc_type, confidence=confidence)

        return ClassificationResult(
            doc_type=doc_type,
            confidence=confidence,
            source_tier=2,
            reasoning=reasoning,
        )

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error("llm_classification_parse_error error=%s", str(e))
        return ClassificationResult(
            doc_type=DocType.UNKNOWN,
            confidence=0.0,
            source_tier=2,
            reasoning=f"LLM response parse failed: {e}",
        )
    except httpx.HTTPError as e:
        logger.error("llm_classification_http_error error=%s", str(e))
        return ClassificationResult(
            doc_type=DocType.UNKNOWN,
            confidence=0.0,
            source_tier=2,
            reasoning=f"LLM API call failed: {e}",
        )


async def classify_page(
    text: str,
    image_b64: str | None = None,
) -> ClassificationResult:
    """
    Full classification cascade:
    Tier 1 (rules) → Tier 2 (LLM if needed) → UNKNOWN if both fail
    """
    # Tier 1
    result = classify_page_rule_based(text)
    if result.confidence >= settings.classification_confidence_threshold:
        return result

    logger.info(
        "rule_classification_insufficient",
        confidence=result.confidence,
        falling_back_to="LLM",
    )
    if settings.openai_api_key:
        llm_result = await classify_page_llm(text, image_b64)
        if llm_result.confidence >= 0.70:
            return llm_result

    return ClassificationResult(
        doc_type=DocType.UNKNOWN,
        confidence=0.0,
        source_tier=3,
        reasoning="Both rule-based and LLM classification failed. Requires human review.",
    )