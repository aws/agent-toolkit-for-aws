# Fargate file processor for Step Functions workflow
import json
import boto3
import os
import sys

s3_client = boto3.client('s3')

def process_file(bucket, key):
    # Download the file
    local_path = f"/tmp/{os.path.basename(key)}"
    s3_client.download_file(bucket, key, local_path)
    print(f"Downloaded s3://{bucket}/{key} to {local_path}")

    # Log metadata
    file_size = os.path.getsize(local_path)
    metadata = {
        'bucket': bucket,
        'key': key,
        'local_path': local_path,
        'file_size_bytes': file_size
    }
    print(f"File metadata: {json.dumps(metadata)}")

    return metadata

if __name__ == '__main__':
    event = json.loads(os.environ.get('TASK_EVENT', '{}'))

    detail = event.get('detail', {})
    bucket = detail.get('bucket', {}).get('name')
    key = detail.get('object', {}).get('key')

    if not bucket or not key:
        print("Error: No bucket or key in event")
        sys.exit(1)

    # Validate inputs
    if not isinstance(key, str) or '/..' in key or len(key) > 1024:
        print("Error: Invalid S3 key")
        sys.exit(1)

    metadata = process_file(bucket, key)
    print(f"Done. File size: {metadata['file_size_bytes']} bytes")
