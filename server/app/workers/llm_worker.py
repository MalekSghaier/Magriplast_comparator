"""
Gemini vision OCR helper.

Gemini is used only to produce clean plain text from scanned page images.
Structured document extraction stays in the template extractor first and
GPT-4o as the final LLM fallback.
"""

import re

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models"
    "/{model}:generateContent"
)


def _extract_gemini_text(data: dict) -> tuple[str, str | None]:
    """Return candidate text across all response parts plus finish reason."""
    candidate = data["candidates"][0]
    finish_reason = candidate.get("finishReason")
    parts = candidate.get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts if part.get("text"))
    return text.strip(), finish_reason


async def extract_page_text_gemini(
    image_b64: str,
    page_number: int | None = None,
) -> str | None:
    """
    Transcribe a scanned page image into plain OCR text.

    The result is fed back into the normal pipeline as page text, so template
    extraction and the GPT-4o fallback both receive cleaner OCR context.
    """
    if not settings.gemini_api_key or not image_b64:
        return None

    system_prompt = (
        "You are an OCR engine for scanned French business documents. "
        "Transcribe the page exactly in reading order. Output plain text only. "
        "Do not summarize, translate, explain, or return JSON. "
        "Preserve product codes, article references, invoice/order numbers, "
        "quantities, dates, TVA rates, TND prices with three decimals, "
        "punctuation, and capitalization. For tables, output one visual table "
        "row per line and separate columns with tab characters. If a character "
        "is illegible, write [?]."
    )

    payload = {
        "system_instruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": image_b64,
                        }
                    },
                    {
                        "text": (
                            "Transcribe this page as OCR text. Return only the "
                            "page text. Keep table columns separated by tabs."
                        )
                    },
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 8_192,
        },
    }

    url = _GEMINI_URL.format(model=settings.gemini_model)
    headers = {"x-goog-api-key": settings.gemini_api_key}

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()

        raw_text, finish_reason = _extract_gemini_text(resp.json())
        raw_text = re.sub(r"^```(?:text)?\s*\n?", "", raw_text, flags=re.IGNORECASE)
        raw_text = re.sub(r"\n?```\s*$", "", raw_text, flags=re.IGNORECASE).strip()

        if not raw_text:
            logger.warning("gemini_ocr_empty", page_number=page_number)
            return None

        logger.info(
            "gemini_ocr_success",
            page_number=page_number,
            chars=len(raw_text),
            finish_reason=finish_reason,
        )
        return raw_text

    except httpx.HTTPStatusError as exc:
        logger.error(
            "gemini_ocr_http_error page_number=%s status=%s body=%.300s",
            page_number,
            exc.response.status_code,
            exc.response.text,
        )
        return None
    except httpx.TimeoutException:
        logger.error("gemini_ocr_timeout page_number=%s timeout=90s", page_number)
        return None
    except (KeyError, IndexError) as exc:
        logger.error(
            "gemini_ocr_response_parse_error page_number=%s error=%s",
            page_number,
            str(exc),
        )
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "gemini_ocr_failed page_number=%s error=%s",
            page_number,
            str(exc),
        )
        return None
