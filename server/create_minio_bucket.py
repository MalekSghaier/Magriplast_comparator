import os
import sys
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


def main():
    endpoint = os.getenv("STORAGE_ENDPOINT_URL", "http://localhost:9000")
    access = os.getenv("STORAGE_ACCESS_KEY", "minioadmin")
    secret = os.getenv("STORAGE_SECRET_KEY", "minioadmin")
    bucket = os.getenv("STORAGE_BUCKET_NAME", "magriplast-documents")
    region = os.getenv("STORAGE_REGION", "us-east-1")

    print(f"Using endpoint={endpoint}, bucket={bucket}")

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        config=Config(signature_version="s3v4"),
        region_name=region,
    )

    try:
        s3.head_bucket(Bucket=bucket)
        print(f"Bucket '{bucket}' already exists")
        return 0
    except ClientError as e:
        err = e.response.get("Error", {})
        code = err.get("Code", "")
        # If the error indicates the bucket doesn't exist, create it
        print(f"head_bucket failed: {code} - creating bucket")

    try:
        # For MinIO, plain create_bucket is fine
        s3.create_bucket(Bucket=bucket)
        print(f"Created bucket '{bucket}'")
        return 0
    except Exception as e:
        print(f"Failed to create bucket: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
