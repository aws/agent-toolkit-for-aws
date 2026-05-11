# TypeScript Reference

## Remove `| undefined` from Response Structures

SDK response fields are typed as `T | undefined` by default. To opt out of this for a client:

```ts
import { S3Client } from "@aws-sdk/client-s3";
import type { AssertiveClient } from "@smithy/types";

const client = new S3Client({}) as AssertiveClient<S3Client>;
// Response fields are no longer unioned with undefined
```

See `@smithy/types` docs for `AssertiveClient` and `UncheckedClient` (skips all runtime checks).

## Narrow Streaming Blob Types

`GetObjectCommand` Body is typed as a union because the runtime type depends on the request handler (Node.js vs browser). To narrow it:

```ts
import { S3Client } from "@aws-sdk/client-s3";
import type { NodeJsClient } from "@smithy/types";

const client = new NodeJsClient<S3Client>(new S3Client({}));
// Body is now typed as NodeJsRuntimeStreamingBlob (Readable) instead of a union
```

## Minimum TypeScript Version

No official minimum. Use a recent version. The SDK's own TypeScript version is in the root `package.json` of the aws-sdk-js-v3 repo.
