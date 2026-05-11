# DynamoDB Reference

Use the resource interface to work with native Python types instead of AttributeValue dicts:

```python
import boto3
from boto3.dynamodb.conditions import Key, Attr

table = boto3.resource("dynamodb").Table("my-table")
table.put_item(Item={"pk": "user#1", "name": "Alice", "age": 30})
item = table.get_item(Key={"pk": "user#1"}).get("Item")
```

## Common Pitfall: AttributeValue Dicts

If you see `{"id": {"S": "1"}, "count": {"N": "42"}}` instead of `{"id": "1", "count": 42}`, you're using `boto3.client("dynamodb")` which does not auto-marshal types. You have two options:

1. Use the **resource interface** (recommended) -- `Table` methods auto-marshal types.
2. Use the **resource's underlying client** -- a low-level client that still
   auto-marshals types is available through the `.meta.client` attribute of a
   resource type:

```python

# Instead of: boto3.client('dynamodb')
# you can use `boto3.resource('dynamodb').meta.client`.
# This is still a boto3 DynamoDB client with custom handlers
# to automatically marshal to the AttributeValue dict types.
dynamodb = boto3.resource("dynamodb").meta.client
# This client auto-converts Python types to/from DynamoDB AttributeValue format
response = dynamodb.get_item(TableName="my-table", Key={"pk": "user#1"})
item = response.get("Item")  # {"pk": "user#1", "name": "Alice"} -- plain Python types
```

ALWAYS prefer using native python types instead of low level AttributeValue
dicts.  These are more idiomatic for Python developers to work with and handle the
conversion and various edge cases automatically for you.

## Error Handling

Access typed exceptions via `table.meta.client.exceptions` (not directly on the table):

```python
table = boto3.resource("dynamodb").Table("my-table")

try:
    table.put_item(
        Item=new_item,
        ConditionExpression=Attr("pk").not_exists(),
    )
except table.meta.client.exceptions.ConditionalCheckFailedException:
    # Actionable: item was created by another process, re-fetch it
    return table.get_item(Key={"pk": new_item["pk"]})["Item"]
```

## Resource Interface (Recommended)

The resource interface automatically marshals between Python types and DynamoDB's type system:

```python
import boto3
from boto3.dynamodb.conditions import Key, Attr
from decimal import Decimal

table = boto3.resource("dynamodb").Table("my-table")
```

### CRUD Operations

```python
# Put item
table.put_item(Item={"pk": "user#1", "sk": "profile", "name": "Alice", "age": 30})

# Get item
response = table.get_item(Key={"pk": "user#1", "sk": "profile"})
item = response.get("Item")  # None if not found

# Update item
table.update_item(
    Key={"pk": "user#1", "sk": "profile"},
    UpdateExpression="SET #n = :name, age = :age",
    ExpressionAttributeNames={"#n": "name"},  # "name" is a reserved word
    ExpressionAttributeValues={":name": "Bob", ":age": 31},
)

# Delete item
table.delete_item(Key={"pk": "user#1", "sk": "profile"})

# Conditional write
table.put_item(
    Item={"pk": "user#1", "sk": "profile", "name": "Alice"},
    ConditionExpression=Attr("pk").not_exists(),  # only if item doesn't exist
)
```

### Query

```python
# Query by partition key
response = table.query(
    KeyConditionExpression=Key("pk").eq("user#1"),
)

# Query with sort key condition
response = table.query(
    KeyConditionExpression=Key("pk").eq("user#1") & Key("sk").begins_with("order#"),
)

# Query with filter (applied after read, still consumes RCUs)
response = table.query(
    KeyConditionExpression=Key("pk").eq("user#1"),
    FilterExpression=Attr("status").eq("active"),
)

# Query a GSI
response = table.query(
    IndexName="gsi-email",
    KeyConditionExpression=Key("email").eq("alice@example.com"),
)

# Reverse order
response = table.query(
    KeyConditionExpression=Key("pk").eq("user#1"),
    ScanIndexForward=False,  # descending sort key order
)

# Projection -- return only specific attributes
response = table.query(
    KeyConditionExpression=Key("pk").eq("user#1"),
    ProjectionExpression="pk, sk, #n",
    ExpressionAttributeNames={"#n": "name"},
)
```

### Scan

```python
# Full table scan (expensive -- prefer query when possible)
response = table.scan()
items = response["Items"]

# Scan with filter
response = table.scan(
    FilterExpression=Attr("age").gte(18) & Attr("status").eq("active"),
)
```

### Batch Operations

```python
# Batch write -- auto-chunks into 25-item batches, retries unprocessed items
with table.batch_writer() as batch:
    for item in items:
        batch.put_item(Item=item)

    # Can also delete
    batch.delete_item(Key={"pk": "user#old", "sk": "profile"})

# Batch get (across tables) -- use the resource, not table
dynamodb = boto3.resource("dynamodb")
response = dynamodb.batch_get_item(
    RequestItems={
        "my-table": {
            "Keys": [
                {"pk": "user#1", "sk": "profile"},
                {"pk": "user#2", "sk": "profile"},
            ],
        }
    }
)
items = response["Responses"]["my-table"]
```

## Condition Expressions

Always use `Key` and `Attr` condition builders with the resource interface. Never hand-build expression strings or manually construct `ExpressionAttributeNames`/`ExpressionAttributeValues` when a condition builder can do it:

```python
# Right -- condition builders handle serialization and placeholders
table.put_item(
    Item=item,
    ConditionExpression=Attr("pk").not_exists(),
)

# Wrong -- manual string building defeats the purpose of the resource interface
table.put_item(
    Item=item,
    ConditionExpression="attribute_not_exists(#pk)",
    ExpressionAttributeNames={"#pk": "pk"},
)
```

```python
from boto3.dynamodb.conditions import Key, Attr

# Key conditions (for KeyConditionExpression in query)
Key("pk").eq("value")
Key("sk").begins_with("prefix")
Key("sk").between("a", "z")
Key("sk").lt("value")
Key("sk").lte("value")
Key("sk").gt("value")
Key("sk").gte("value")

# Attribute conditions (for FilterExpression and ConditionExpression)
Attr("field").eq("value")
Attr("field").ne("value")
Attr("field").lt(10)
Attr("field").lte(10)
Attr("field").gt(10)
Attr("field").gte(10)
Attr("field").begins_with("prefix")
Attr("field").between(1, 100)
Attr("field").is_in(["a", "b", "c"])
Attr("field").exists()
Attr("field").not_exists()
Attr("field").contains("substring")  # works on strings, lists, and sets
Attr("field").size()

# Combine with & (AND), | (OR), ~ (NOT)
(Attr("age").gte(18)) & (Attr("status").eq("active"))
(Attr("role").eq("admin")) | (Attr("role").eq("superadmin"))
~Attr("deleted").exists()

# Nested attributes
Attr("address.city").eq("Seattle")
```

## Type Handling

### Resource auto-marshalling

The resource interface handles type conversion automatically:

| Python type | DynamoDB type |
|---|---|
| `str` | S |
| `int`, `Decimal` | N |
| `bytes`, `bytearray` | B |
| `bool` | BOOL |
| `None` | NULL |
| `list` | L |
| `dict` | M |
| `set` of `str` | SS |
| `set` of `int`/`Decimal` | NS |
| `set` of `bytes` | BS |

Use `Decimal` for numbers when precision matters. DynamoDB stores numbers as strings internally, and `float` values may introduce floating-point precision artifacts:

```python
from decimal import Decimal

# Exact representation
table.put_item(Item={"pk": "1", "price": Decimal("19.99")})

# Works but may lose precision -- float 19.99 is stored as
# Decimal("19.9900000000000002131628...") internally
table.put_item(Item={"pk": "1", "price": 19.99})
```

### Client interface (manual marshalling)

If you must use the client interface, use `TypeSerializer`/`TypeDeserializer`:

```python
from boto3.dynamodb.types import TypeSerializer, TypeDeserializer

serializer = TypeSerializer()
deserializer = TypeDeserializer()

# Serialize a Python value to DynamoDB format
serializer.serialize("hello")     # {"S": "hello"}
serializer.serialize(42)          # {"N": "42"}
serializer.serialize(True)        # {"BOOL": True}

# Deserialize DynamoDB format to Python value
deserializer.deserialize({"S": "hello"})  # "hello"
deserializer.deserialize({"N": "42"})     # Decimal("42")
```

## Pagination (Query / Scan)

DynamoDB returns up to 1MB per call. Use the resource's underlying client to get paginators with auto-marshalled types:

```python
dynamodb = boto3.resource("dynamodb").meta.client
paginator = dynamodb.get_paginator("query")
for page in paginator.paginate(
    TableName="my-table",
    KeyConditionExpression="pk = :pk",
    ExpressionAttributeValues={":pk": "user#1"},  # auto-marshalled, no {"S": ...}
):
    for item in page["Items"]:
        print(item)
```
