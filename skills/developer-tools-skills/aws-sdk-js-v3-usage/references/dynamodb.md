# DynamoDB Reference

## DocumentClient (lib-dynamodb)

`@aws-sdk/lib-dynamodb` marshals native JS types to/from DynamoDB AttributeValues automatically.

```js
import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient, GetCommand, PutCommand, QueryCommand, DeleteCommand } from "@aws-sdk/lib-dynamodb";

const client = DynamoDBDocumentClient.from(new DynamoDBClient({ region: "us-east-1" }));

// Put
await client.send(new PutCommand({ TableName: "MyTable", Item: { id: "1", name: "Alice", age: 30 } }));

// Get
const { Item } = await client.send(new GetCommand({ TableName: "MyTable", Key: { id: "1" } }));

// Query
const { Items } = await client.send(new QueryCommand({
  TableName: "MyTable",
  KeyConditionExpression: "id = :id",
  ExpressionAttributeValues: { ":id": "1" },
}));

// Delete
await client.send(new DeleteCommand({ TableName: "MyTable", Key: { id: "1" } }));
```

## Type Mapping

| JS type | DynamoDB type |
|---|---|
| string | S |
| number / bigint / NumberValue | N |
| boolean | BOOL |
| null | NULL |
| Array | L |
| Object | M |
| Uint8Array / Buffer / Blob / File... | B |
| Set\<string\> | SS |
| Set\<number\> / Set\<bigint\> / Set\<NumberValue\> | NS |
| Set\<Uint8Array\> / Set\<Blob\>... | BS |

## Marshall Options

```js
const client = DynamoDBDocumentClient.from(new DynamoDBClient({}), {
  marshallOptions: {
    removeUndefinedValues: true,   // strip undefined from objects/arrays
    convertEmptyValues: false,     // convert "" / empty sets to null
    convertClassInstanceToMap: false,
    allowImpreciseNumbers: false,  // true = allow numbers > MAX_SAFE_INTEGER (loses precision)
  },
  unmarshallOptions: {
    wrapNumbers: false,            // true = return NumberValue instead of JS number
  },
});
```

## Large Numbers

Numbers exceeding `Number.MAX_SAFE_INTEGER` throw by default. Use `NumberValue` for precision:

```js
import { NumberValue, DynamoDBDocumentClient } from "@aws-sdk/lib-dynamodb";

await client.send(new PutCommand({
  TableName: "MyTable",
  Item: { id: "1", bigNum: NumberValue.from("1000000000000000000000.000000001") },
}));
```

Custom unmarshalling with BigInt:

```js
const client = DynamoDBDocumentClient.from(new DynamoDBClient({}), {
  unmarshallOptions: { wrapNumbers: (str) => BigInt(str) },
});
```

## Pagination (Scan / Query)

```js
import { paginateScan } from "@aws-sdk/lib-dynamodb";

for await (const page of paginateScan({ client }, { TableName: "MyTable", Limit: 100 })) {
  console.log(page.Items);
}
```

## Aggregated (full) Client

```js
import { DynamoDBDocument } from "@aws-sdk/lib-dynamodb";

const doc = DynamoDBDocument.from(new DynamoDBClient({}));
await doc.put({ TableName: "MyTable", Item: { id: "1" } });
await doc.get({ TableName: "MyTable", Key: { id: "1" } });
```

## Destroy

`ddbDocClient.destroy()` is a no-op. Call `destroy()` on the underlying `DynamoDBClient`.
