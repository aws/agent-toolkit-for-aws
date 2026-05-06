# Pagination Reference

## Paginators

Most `list_*`, `describe_*`, and `get_*` operations that return collections support pagination. When you only need specific fields, use `.search()` to extract and flatten across pages:

```python
client = boto3.client("ec2")
paginator = client.get_paginator("describe_instances")

for instance_id in paginator.paginate().search("Reservations[].Instances[].InstanceId"):
    print(instance_id)
```

When you need the full response object per item, or need per-page control (e.g. counting pages, batching by page), iterate pages directly:

```python
for page in paginator.paginate():
    for reservation in page.get("Reservations", []):
        for instance in reservation.get("Instances", []):
            process(instance)
```

Check if an operation supports pagination:

```python
client.can_paginate("describe_instances")  # True
```

## Pagination Configuration

Control page size and total items via `PaginationConfig`:

```python
paginator = client.get_paginator("list_objects_v2")
pages = paginator.paginate(
    Bucket="my-bucket",
    PaginationConfig={
        "PageSize": 100,        # items per API call
        "MaxItems": 500,        # total items across all pages
        "StartingToken": None,  # resume from a previous NextToken
    },
)
```

- `PageSize` controls the `MaxKeys`/`MaxResults`/`Limit` parameter sent to the API
- `MaxItems` stops iteration after this many total items and provides a `NextToken` for resuming
- The paginator uses the correct token parameter name for each service automatically

## JMESPath Filtering

Use `.search()` to extract and flatten results across pages:

```python
paginator = client.get_paginator("list_objects_v2")
page_iterator = paginator.paginate(Bucket="my-bucket")

# Flatten all keys across all pages
keys = page_iterator.search("Contents[].Key")
for key in keys:
    print(key)

# Filter with JMESPath expressions
large_objects = page_iterator.search(
    "Contents[?Size > `1048576`].{Key: Key, Size: Size}"
)
```

`.search()` returns a generator that yields individual items, not pages -- no need to handle page boundaries.

## Common Paginated Operations

| Service | Operation | Result key |
|---|---|---|
| S3 | `list_objects_v2` | `Contents` |
| DynamoDB | `scan` | `Items` |
| DynamoDB | `query` | `Items` |
| EC2 | `describe_instances` | `Reservations` |
| IAM | `list_users` | `Users` |
| Lambda | `list_functions` | `Functions` |
| CloudWatch Logs | `describe_log_groups` | `logGroups` |

Note: `list_buckets` is not paginated -- it returns all buckets in a single response.

## Resource-Level Pagination

Resources handle pagination automatically via collection methods:

```python
s3 = boto3.resource("s3")
bucket = s3.Bucket("my-bucket")

# .all() paginates automatically
for obj in bucket.objects.all():
    print(obj.key)

# .filter() also paginates
for obj in bucket.objects.filter(Prefix="logs/"):
    print(obj.key)

# .limit() limits total results
for obj in bucket.objects.limit(100):
    print(obj.key)
```
