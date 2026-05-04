# Client Configuration Reference

## Request Handler (HTTP)

### Node.js (shorthand, v3.521.0+)

```js
const client = new S3Client({
  requestHandler: {
    requestTimeout: 15_000,    // ms to receive response
    connectionTimeout: 6_000,  // ms to establish connection
    httpsAgent: { keepAlive: true, maxSockets: 50 },
  },
});
```

### Node.js (explicit)

```js
import { NodeHttpHandler } from "@smithy/node-http-handler";
import https from "node:https";

const client = new S3Client({
  requestHandler: new NodeHttpHandler({
    httpsAgent: new https.Agent({ keepAlive: true, maxSockets: 200 }),
    requestTimeout: 15_000,
    connectionTimeout: 6_000,
  }),
});
```

Default `maxSockets` is 50 per client. Socket exhaustion warning:

```text
@smithy/node-http-handler:WARN - socket usage at capacity=N and M additional requests are enqueued.
```

### Browser

```js
import { FetchHttpHandler } from "@aws-sdk/config/requestHandler";
const client = new S3Client({ requestHandler: new FetchHttpHandler({ requestTimeout: 30_000 }) });
```

XHR (for upload progress events):

```js
import { XhrHttpHandler } from "@aws-sdk/xhr-http-handler";
const handler = new XhrHttpHandler({ requestTimeout: 30_000 });
handler.on(XhrHttpHandler.EVENTS.UPLOAD_PROGRESS, (event) => { ... });
const client = new S3Client({ requestHandler: handler });
```

## Retry Strategy

```js
// Simple: set max attempts
new S3Client({ maxAttempts: 5 });

// Custom backoff
import { ConfiguredRetryStrategy } from "@aws-sdk/config/retryStrategy";
new S3Client({
  retryStrategy: new ConfiguredRetryStrategy(5, (attempt) => 500 + attempt * 1_000),
});

// Adaptive (rate-limiting)
new S3Client({ retryMode: "ADAPTIVE" });
```

When `retryStrategy` is set, `retryMode` and `maxAttempts` are ignored.

## Logging

```js
// Enable SDK logging (suppress trace/debug)
new S3Client({
  logger: { ...console, debug() {}, trace() {} },
});
```

For full request/response logging, use middleware (see SKILL.md Middleware section).

## Endpoint

```js
// Custom endpoint (e.g. local mock)
new S3Client({ endpoint: "http://localhost:8888" });
```

## FIPS / Dual-stack

```js
new S3Client({ useFipsEndpoint: true });
new S3Client({ useDualstackEndpoint: true });
```

## Retrieving the Endpoint Without Making a Request

**This interface is not public/stable.** Do not use in production, or verify it on every SDK version upgrade.

```ts
import { GetObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { getEndpointFromInstructions } from "@smithy/middleware-endpoint";

const client = new S3Client({ region: "us-east-1" });

/** @internal do not directly use in production. */
const endpoint = await getEndpointFromInstructions(
  { Key: "foo", Bucket: "bar" }, // 1. command input
  GetObjectCommand,               // 2. Command class
  client.config                   // 3. client config
);
```

## Protocol Selection (v3.953.0+)

Most services support only one protocol. CloudWatch and SQS support multiple:

```js
import { AwsJson1_0Protocol, AwsSmithyRpcV2CborProtocol } from "@aws-sdk/core/protocols";

new CloudWatch({ protocol: AwsJson1_0Protocol });       // default
new CloudWatch({ protocol: AwsSmithyRpcV2CborProtocol }); // CBOR
```

## Middleware Caching

```js
// Cache middleware stack per client+command — reduces per-request overhead.
// Do not use if you modify the middleware stack after requests begin.
new S3Client({ cacheMiddleware: true });
```

## S3-Specific Options

```js
// Retry with corrected region on 301 redirect (use only if bucket region is unknown)
new S3Client({ followRegionRedirects: true });
```

## Schemas (v3.953.0+)

See `references/schemas.md`.
