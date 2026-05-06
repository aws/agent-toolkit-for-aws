# Schemas Reference (v3.953.0+)

Schemas are runtime objects that describe the data structures of modeled shapes. Used internally by the SDK for serialization/deserialization, and available for runtime validation or serialization to non-default formats. Not needed for basic SDK usage.

Each exported interface has a corresponding schema suffixed with `$`:

```ts
import { type PutBucketAclRequest, PutBucketAclRequest$ } from "@aws-sdk/client-s3";
```

## Use case 1: Runtime validation

```ts
import { NormalizedSchema } from "@smithy/core/schema";

const $ = NormalizedSchema.of(PutBucketAclRequest$);
// Use $.isStringSchema(), $.isStructSchema(), $.structIterator(), etc.
// to walk the schema and validate an object at runtime.
```

Useful when accepting unknown user input. Note: schemas do not include required-field or numeric-range constraints (by design — the SDK favors server-side validation).

## Use case 2: Serialization to non-default formats

```ts
import { JsonCodec } from "@aws-sdk/core/protocols";
import { PutItemInput$ } from "@aws-sdk/client-dynamodb";

const codec = new JsonCodec({ timestampFormat: { useTrait: true, default: 7 }, jsonName: false });
const serializer = codec.createSerializer();
serializer.write(PutItemInput$, myData);
const json = serializer.flush(); // serialize DynamoDB input to JSON string

const deserializer = codec.createDeserializer();
const result = await deserializer.read(PutItemInput$, json);
```

A schema is required (rather than dynamic heuristics) because serialized representations can be ambiguous — e.g. a number could be a timestamp, a base64 string could be a `Uint8Array`. CBOR is also supported via `CborCodec` from `@smithy/core/cbor`.
