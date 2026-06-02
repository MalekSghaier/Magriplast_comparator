"""
MinIO Storage Cleanup Script
Deletes all objects in the magriplast-documents bucket
"""
import boto3
from botocore.client import Config

# MinIO connection
s3_client = boto3.client(
    's3',
    endpoint_url='http://localhost:9000',
    aws_access_key_id='minioadmin',
    aws_secret_access_key='minioadmin',
    config=Config(signature_version='s3v4'),
    region_name='us-east-1'
)

bucket_name = 'magriplast-documents'

print(f"🗑️  Cleaning bucket: {bucket_name}")

# List all objects
try:
    response = s3_client.list_objects_v2(Bucket=bucket_name)
    
    if 'Contents' not in response:
        print("✅ Bucket is already empty!")
    else:
        objects = response['Contents']
        print(f"📦 Found {len(objects)} objects")
        
        # Delete all objects
        delete_keys = [{'Key': obj['Key']} for obj in objects]
        s3_client.delete_objects(
            Bucket=bucket_name,
            Delete={'Objects': delete_keys}
        )
        
        print(f"✅ Deleted {len(delete_keys)} objects!")
        
        # Calculate freed space
        total_size = sum(obj['Size'] for obj in objects)
        print(f"💾 Freed {total_size / (1024*1024):.2f} MB")

except Exception as e:
    print(f"❌ Error: {e}")
