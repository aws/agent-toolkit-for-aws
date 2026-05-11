# Error Handling Reference

## Service Errors

Non-2xx responses are thrown as JavaScript `Error`s with SDK-specific fields:

```js
try {
  await client.send(new CreateFunctionCommand({ ... }));
} catch (e) {
  if (e?.$metadata) {
    // e.name          — error code string (e.g. "ResourceNotFoundException")
    // e.$metadata.httpStatusCode — HTTP status
    // e.$response     — raw HTTP response object
    // e.$responseBodyText — set when SDK fails to parse the error body (unexpected format)
    console.error(e.name, e.$metadata.httpStatusCode);
  }
}
```

## Checking Specific Error Types

By name or `instanceof` (both safe — SDK overrides `Symbol.hasInstance`):

```js
import { NoSuchKeyException } from "@aws-sdk/client-s3";

if (e.name === "NoSuchKeyException") { ... }
if (e instanceof NoSuchKeyException) { ... }
```

## Unparseable Error Bodies

If the error body can't be parsed (e.g. a proxy returned HTML), the message will say:
> "Deserialization error: to see the raw response, inspect the hidden field {error}.$response"

Inspect with:

```js
if (e.$responseBodyText) console.debug(e.$responseBodyText);
```

## TypeScript: Version Mismatch Compilation Error

If you see:

```console
error TS2345: Argument of type 'X' is not assignable to parameter of type 'Y'
  'A' is assignable to the constraint of type 'B', but 'B' could be instantiated with a different subtype
```

This is caused by mismatched `@smithy/types` / `@aws-sdk/types` versions across clients. Fix by pinning all `@aws-sdk/client-*` packages to the same version range:

```json
{
  "@aws-sdk/client-s3": "<=3.800.0",
  "@aws-sdk/client-dynamodb": "<=3.800.0"
}
```
