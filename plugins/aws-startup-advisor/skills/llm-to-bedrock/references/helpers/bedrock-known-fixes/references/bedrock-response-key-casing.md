# Fix: bedrock-response-key-casing

## Symptom

A Python file accesses the Bedrock response body with `response["Body"]` (uppercase) or `response['Body']`. At runtime this raises `KeyError: 'Body'` because boto3's `bedrock-runtime` returns the body under the lowercase key `"body"` (matching the AWS API response, not S3's convention).

## Fix

**Pattern**:

```python
# WRONG — will crash with KeyError
result = json.loads(response["Body"].read())

# CORRECT — boto3 bedrock-runtime uses lowercase "body"
result = json.loads(response["body"].read())
```

**When to check**: Any file that calls `bedrock_client.invoke_model()` or `bedrock_runtime.invoke_model()`. Search for `response["Body"]` or `response['Body']` and fix to lowercase.

## Verification

```bash
grep -rn 'response\[.Body.\]\.read' .
```

Expected: no matches. Every Bedrock invocation reads from `response["body"]` (lowercase). Re-run any failing test that exercised the Bedrock call path — the `KeyError` is gone.
