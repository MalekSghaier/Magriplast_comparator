import boto3
import hashlib
from typing import Generator

from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class StorageClient:

    def __init__(self) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.storage_endpoint_url,
            aws_access_key_id=settings.storage_access_key,
            aws_secret_access_key=settings.storage_secret_key,
            region_name=settings.storage_region,
            config=Config(signature_version="s3v4"),
        )
        self._bucket = settings.storage_bucket_name

    def upload_pdf(self, job_id: str, file_bytes: bytes) -> str:
        """
        Store original PDF immutably.
        Key format: originals/{job_id}/document.pdf
        Returns the storage key.
        """
        key = f"originals/{job_id}/document.pdf"
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=file_bytes,
            ContentType="application/pdf",
            Metadata={"sha256": hashlib.sha256(file_bytes).hexdigest()},
        )
        logger.info("pdf_uploaded", job_id=job_id, key=key, size=len(file_bytes))
        return key

    def upload_page_image(self, job_id: str, page_num: int, image_bytes: bytes) -> str:
        """Store preprocessed page image. 30-day TTL set via bucket lifecycle rule."""
        key = f"pages/{job_id}/page_{page_num:03d}.png"
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=image_bytes,
            ContentType="image/png",
        )
        return key

    def download_pdf(self, storage_key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=storage_key)
        return response["Body"].read()

    def get_pdf_hash(self, storage_key: str) -> str:
        response = self._client.head_object(Bucket=self._bucket, Key=storage_key)
        return response.get("Metadata", {}).get("sha256", "")

    def stream_object(self, storage_key: str, chunk_size: int = 65536) -> Generator[bytes, None, None]:
        """
        Yield the object in chunks for streaming HTTP responses.
        Uses the server-side endpoint_url (internal Docker network or localhost in dev)
        so MinIO is never exposed directly to the browser.
        """
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=storage_key)
            body = response["Body"]
            while True:
                chunk = body.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "Unknown")
            logger.error(
                "stream_object_failed",
                storage_key=storage_key,
                error_code=error_code,
                detail=str(exc),
            )
            raise

    def object_exists(self, storage_key: str) -> bool:
        """Return True if the key exists in the bucket."""
        try:
            self._client.head_object(Bucket=self._bucket, Key=storage_key)
            return True
        except ClientError:
            return False


storage_client = StorageClient()