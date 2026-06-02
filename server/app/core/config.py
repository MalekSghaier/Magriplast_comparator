from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = "Magriplast Document Processing"
    debug: bool = False
    api_prefix: str = "/api/v1"


    database_url: str = Field(
        default="postgresql+asyncpg://postgres:malek@localhost:5432/magriplast"
    )
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # Celery / Redis
    redis_url: str = Field(default="redis://localhost:6379/0")
    celery_broker_url: str = Field(default="redis://localhost:6379/0")
    celery_result_backend: str = Field(default="redis://localhost:6379/1")

    # Storage (S3 / MinIO)
    storage_endpoint_url: str = Field(default="http://localhost:9000")
    storage_access_key: str = Field(default="minioadmin")
    storage_secret_key: str = Field(default="minioadmin")
    storage_bucket_name: str = Field(default="magriplast-documents")
    storage_region: str = Field(default="us-east-1")

    # OCR
    tesseract_cmd: str = Field(default="/usr/bin/tesseract")
    tesseract_language: str = "fra"
    ocr_confidence_threshold: float = 0.70  # below this → cloud fallback
    classification_confidence_threshold: float = 0.90  # below this → LLM fallback

    # Google Document AI (cloud OCR fallback)
    google_docai_enabled: bool = False
    google_docai_project_id: str = Field(default="")
    google_docai_processor_id: str = Field(default="")
    google_application_credentials: str = Field(default="")

   # LLM — GPT-4o (extraction fallback)
    openai_api_key: str = Field(default="")
    llm_model: str = "gpt-4o"
    llm_max_tokens: int = 1500
    llm_temperature: float = 0.0

    # Gemini — parallel vision extractor
    # Add GEMINI_API_KEY=... and USE_PARALLEL_VISION=true to your .env
    gemini_api_key: str = Field(default="")
    gemini_model: str = "gemini-3.5-flash"         # override in .env if needed
    use_parallel_vision: bool = True

    # Matching tolerances
    # 0.10 DT covers last-millime OCR rounding (4.339 vs 4.399) without hiding
    # real discrepancies (which are always > 0.10 DT in TND pricing)
    price_tolerance: float = 0.10
    quantity_tolerance: float = 0.0     # units — exact by default
    line_total_tolerance: float = 0.02
    tva_tolerance: float = 0.0
    reference_levenshtein_max_distance: int = 2
    max_pdf_size_bytes: int = 52_428_800  # 50MB
    max_pdf_pages: int = 50
    job_timeout_seconds: int = 300


    # JWT / Auth  ← ADD THESE inside the Settings class
    secret_key: str = Field(default="CHANGE_ME_USE_OPENSSL_RAND_HEX_32_IN_PROD")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()