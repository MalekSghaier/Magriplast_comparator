"""
Gemini 2.5 Pro OCR service.
Envoie l'image de la page à Gemini et retourne le texte extrait
avec un score de confidence estimé.
"""
import base64
import httpx
from dataclasses import dataclass
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent?key={key}"
)

_SYSTEM_PROMPT = """You are an expert OCR engine specialized in North African B2B business documents.
Documents are in French, Arabic, or mixed French/Arabic, from Tunisian/Moroccan/Algerian suppliers.

════════════════════════════════════════════════════════════
DOCUMENT TYPES YOU WILL SEE
════════════════════════════════════════════════════════════
- FACTURE (invoice): contains "Facture N°", "N° FAC", totals HT/TTC/TVA
- BON DE COMMANDE (purchase order): contains "Bon de Commande", "N° BC"
- BON DE LIVRAISON (delivery note): contains "Bon de Livraison", "N° BL"

════════════════════════════════════════════════════════════
STEP 1 — READ THE FULL PAGE CAREFULLY
════════════════════════════════════════════════════════════
Before extracting, scan the ENTIRE image including:
- Header (company name, address, document reference, date)
- Table (all rows including first and last)
- Footer (totals: HT, TVA, TTC, NET À PAYER)
- Any stamps, handwritten annotations, watermarks

════════════════════════════════════════════════════════════
STEP 2 — EXTRACT TEXT WITH PERFECT STRUCTURE
════════════════════════════════════════════════════════════
Reproduce the document layout exactly:
- Use spaces to align table columns as they appear visually
- Each table row on its own line
- Header block first, then table, then footer totals
- Arabic text: write right-to-left as printed, do NOT transliterate

════════════════════════════════════════════════════════════
STEP 3 — CRITICAL RULES FOR NUMBERS (READ CAREFULLY)
════════════════════════════════════════════════════════════
Tunisian Dinar (TND) uses 3 decimal places:
  CORRECT:   122.341  |  415.959  |  5.568  |  4.339
  WRONG:     122,341  |  415959   |  5568   |  4,339

Rules:
- NEVER convert "." to "," in amounts
- NEVER remove decimal points
- NEVER merge space-separated number groups: "122 341" → write as "122.341"
- Quantities are small integers: 1, 2, 5, 10, 100
- Unit prices are medium: 4.339, 122.341, 415.959
- Line totals are larger: qty × price

════════════════════════════════════════════════════════════
STEP 4 — CRITICAL RULES FOR REFERENCE CODES
════════════════════════════════════════════════════════════
Product reference codes are alphanumeric (e.g. P199680136, FL0141, BC-2024-001):
- Copy them EXACTLY character by character
- NEVER correct or translate reference codes
- NEVER skip a reference code — they are the most important field
- If a code is partially illegible, write what you can see with ? for unclear chars

════════════════════════════════════════════════════════════
STEP 5 — TABLE EXTRACTION RULES
════════════════════════════════════════════════════════════
- Extract EVERY row in the table — count them first, then extract
- Do NOT skip rows that look similar to others
- Do NOT merge two rows into one
- Column order is typically: Référence | Désignation | Qté | Unité | Prix U.HT | TVA% | Total HT
- If a designation wraps to a second line, include it joined to the first line with a space

════════════════════════════════════════════════════════════
STEP 6 — COMMON OCR ERRORS TO CORRECT
════════════════════════════════════════════════════════════
Apply these corrections to designation/label words ONLY (not to codes or numbers):
- "0" mistaken for "O" and vice versa
- "1" mistaken for "I" or "L"  
- "rn" mistaken for "m"
- "vv" mistaken for "w"
- Broken words: re-join if context is clear (e.g. "POLY ETHYLENE" → "POLYETHYLENE")
- Do NOT apply letter corrections to product reference codes

════════════════════════════════════════════════════════════
OUTPUT FORMAT
════════════════════════════════════════════════════════════
Return ONLY the extracted text, structured like this:

[HEADER]
<company name, address, document ref, date>

[TABLE]
<header row>
<data row 1>
<data row 2>
...

[FOOTER]
<totals: HT, TVA, TTC, NET À PAYER>

No explanation. No markdown. No JSON. Just the structured text above."""


@dataclass
class GeminiOCRResult:
    full_text: str
    mean_confidence: float   # estimé: 0.0 – 1.0
    lines: list[str]
    model_used: str


async def run_gemini_ocr(image_bytes: bytes) -> GeminiOCRResult | None:
    """
    Envoie l'image à Gemini 2.5 Pro et retourne le texte extrait.
    Retourne None en cas d'erreur (Tesseract sera utilisé à la place).
    """
    if not settings.gemini_api_key:
        logger.warning("gemini_ocr_skipped: no API key configured")
        return None

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": image_b64,
                        }
                    },
                    {
                        "text": _SYSTEM_PROMPT
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 4096,
        }
    }

    url = GEMINI_API_URL.format(
        model=settings.gemini_model,
        key=settings.gemini_api_key,
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()

            data = response.json()
            text = (
                data["candidates"][0]["content"]["parts"][0]["text"]
                        .strip()
            )
            
            # Confidence calculée sur la qualité du texte extrait
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                    
            has_numbers = bool(__import__('re').search(r'\d+[.,]\d+', text))
            has_table_section = '[TABLE]' in text
            has_footer = '[FOOTER]' in text
            has_references = bool(__import__('re').search(r'[A-Z]{1,4}\d{4,}', text))
            char_count = len(text)

            # Score basé sur la richesse du contenu extrait
            score = 0.50
            if char_count > 500:   score += 0.10
            if char_count > 1000:  score += 0.05
            if has_numbers:        score += 0.10
            if has_table_section:  score += 0.10
            if has_footer:         score += 0.05
            if has_references:     score += 0.10
        
            confidence = min(score, 0.95)  
            
            logger.info(
                "gemini_ocr_success",
                chars=char_count,
                lines=len(lines),
                confidence=round(confidence, 3),
                has_numbers=has_numbers,
                has_table=has_table_section,
                has_footer=has_footer,
                has_references=has_references,
            )

        return GeminiOCRResult(
            full_text=text,
            mean_confidence=confidence,
            lines=lines,
            model_used=settings.gemini_model,
        )

    except httpx.TimeoutException:
        logger.error("gemini_ocr_timeout")
        return None
    except httpx.HTTPStatusError as e:
        logger.error("gemini_ocr_http_error status=%s body=%s",
                     e.response.status_code, e.response.text[:200])
        return None
    except (KeyError, IndexError) as e:
        logger.error("gemini_ocr_parse_error error=%s", str(e))
        return None
    except Exception as e:
        logger.error("gemini_ocr_unexpected_error error=%s", str(e))
        return None