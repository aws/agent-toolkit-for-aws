import json
import boto3
import os

s3_client = boto3.client('s3')

def lambda_handler(event, context):
    print(f"Received event: {json.dumps(event)}")

    detail = event.get('detail', {})
    bucket = detail.get('bucket', {}).get('name')
    key = detail.get('object', {}).get('key')
    size = detail.get('object', {}).get('size', 0)

    # Validate S3 parameters before downloading
    if not bucket or not key or not isinstance(key, str) or '/..' in key:
        raise ValueError('Invalid S3 path')
    if len(key) > 1024:
        raise ValueError('S3 key exceeds maximum length')
    if size > 512 * 1024 * 1024:
        raise ValueError('File too large for Lambda processing')

    # Download the file to /tmp
    local_path = f"/tmp/{os.path.basename(key)}"
    try:
        s3_client.download_file(bucket, key, local_path)
        print(f"Downloaded s3://{bucket}/{key} to {local_path}")

        # Log metadata
        metadata = {
            'bucket': bucket,
            'key': key,
            'size_bytes': size,
            'local_path': local_path,
            'file_size_on_disk': os.path.getsize(local_path)
        }
        print(f"File metadata: {json.dumps(metadata)}")
    finally:
        try:
            os.remove(local_path)
        except OSError:
            pass

    return {
        'statusCode': 200,
        'body': metadata
    }
