# Error Handling Reference

## Core Principle

Only catch an exception when you have an actionable response: return a fallback, retry, take a different code path. If the only thing you'd do is print the error, don't catch it -- let it propagate. The caller (or a top-level handler) is in a better position to decide what to do.

## ClientError Anatomy

`botocore.exceptions.ClientError` is the base exception for all AWS API errors:

```python
from botocore.exceptions import ClientError

try:
    client.describe_instances(InstanceIds=["i-nonexistent"])
except ClientError as e:
    error = e.response["Error"]
    metadata = e.response["ResponseMetadata"]

    error["Code"]               # "InvalidInstanceID.NotFound"
    error["Message"]            # "The instance ID 'i-nonexistent' does not exist"
    metadata["HTTPStatusCode"]  # 400
    metadata["RequestId"]       # AWS request ID for support cases
```

## Service-Specific Exceptions

Each client exposes typed exceptions generated from the service model. These are subclasses of `ClientError`, so a `ClientError` catch still works as a fallback:

```python
s3 = boto3.client("s3")
try:
    s3.get_object(Bucket="bucket", Key="key")
except s3.exceptions.NoSuchKey:
    return None  # actionable: missing key is a valid case
```

List available exceptions for a client:

```python
print([e for e in dir(s3.exceptions) if not e.startswith("_")])
```

## Common botocore Exceptions

```python
from botocore.exceptions import (
    ClientError,              # AWS API returned an error response
    NoCredentialsError,       # no credentials found in the chain
    PartialCredentialsError,  # incomplete credentials (e.g. key without secret)
    NoRegionError,            # no region configured
    ParamValidationError,     # invalid parameters before request is sent
    EndpointConnectionError,  # could not connect to the endpoint
    ConnectTimeoutError,      # connection timed out
    ReadTimeoutError,         # read timed out waiting for response
    WaiterError,              # waiter reached max attempts without success
)
```

`ParamValidationError` is raised locally before any network request -- it means the parameters failed botocore's client-side validation.

## Error Handling Patterns

### Actionable catch: convert to return value

```python
def get_item(table, key: dict) -> dict | None:
    response = table.get_item(Key=key)
    return response.get("Item")  # None if missing, no exception needed

def head_object(client, bucket: str, key: str) -> dict | None:
    try:
        return client.head_object(Bucket=bucket, Key=key)
    except client.exceptions.ClientError as e:
        if e.response["ResponseMetadata"]["HTTPStatusCode"] == 404:
            return None
        raise
```

### Actionable catch: conditional put race

```python
try:
    table.put_item(
        Item=new_item,
        ConditionExpression=Attr("pk").not_exists(),
    )
except table.meta.client.exceptions.ConditionalCheckFailedException:
    # Another writer got there first -- fetch what they wrote
    return table.get_item(Key={"pk": new_item["pk"]})["Item"]
```

### Actionable catch: create-if-not-exists

```python
try:
    client.create_bucket(Bucket="my-bucket")
except client.exceptions.BucketAlreadyOwnedByYou:
    pass  # already exists, that's fine
```

### Top-level catch-all in main()

Business logic functions should let exceptions propagate. The `main()` function is the right place for a generic catch-all that presents errors cleanly to the user. Keep the catch-all simple -- just `ClientError`. Other exceptions like `NoCredentialsError` already have clear messages and can propagate naturally:

```python
from botocore.exceptions import ClientError

def main() -> int:
    try:
        do_the_work()
        return 0
    except ClientError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
```

### What NOT to do

```python
# Wrong: catching just to print and swallow
try:
    client.describe_table(TableName=name)
except client.exceptions.ResourceNotFoundException:
    print("Table not found")     # swallowed -- caller has no idea it failed
except NoCredentialsError:
    print("No credentials")      # swallowed
except EndpointConnectionError:
    print("Can't connect")       # swallowed

# Wrong: sys.exit() from a business logic function
def process_queue(queue_url):
    if not queue_url:
        print("No queue URL provided")
        sys.exit(1)              # untestable, unusable as library code
```
