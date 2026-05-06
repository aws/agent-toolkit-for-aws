# Effective Practices Reference

## Client Reuse

Create one client per region+credentials combination. Don't create clients inside loops:

```js
// WRONG:
for (const item of items) {
  const client = new S3Client({ region, credentials });
  await client.send(new PutObjectCommand(item));
}

// OK:
const client = new S3Client({ region, credentials });
for (const item of items) {
  await client.send(new PutObjectCommand(item));
}
```

## Don't Read or Mutate `client.config`

`client.config` is a resolved form — `region` becomes `async () => "us-east-1"`, credentials are wrapped, etc. Reading or writing it directly will cause errors:

```js
// WRONG: — throws "config.region is not a function"
client.config.region = "us-west-2";

// WRONG: — throws "client.config.endpoint is not a function"
const endpoint = await client.config.endpoint();
```

To use multiple regions, create separate clients (share credentials to avoid duplicate resolution):

```js
import { fromTemporaryCredentials } from "@aws-sdk/credential-providers";
const creds = fromTemporaryCredentials({ params: { RoleArn: "..." } });
const east = new S3Client({ region: "us-east-1", credentials: creds });
const west = new S3Client({ region: "us-west-2", credentials: creds });
```

To get the resolved endpoint for a specific operation:

```js
import { getEndpointFromInstructions } from "@smithy/middleware-endpoint";
const endpoint = await getEndpointFromInstructions(
  { Bucket, Key },
  GetObjectCommand,
  { region: "us-west-2", useDualstackEndpoint: false, useFipsEndpoint: false }
);
console.log(endpoint.url.toString());
```

## Always Read or Discard Streaming Responses

Unread streams hold sockets open → socket exhaustion / memory leak:

```js
const { Body } = await client.send(new GetObjectCommand({ Bucket, Key }));

// OK: read
const bytes = await Body.transformToByteArray();

// OK: pipe
await client.send(new PutObjectCommand({ Bucket: dest, Key, Body }));

// OK: discard
await (Body.destroy?.() ?? Body.cancel?.());

// WRONG: — socket stays open
// (no action on Body)
```

## Cross-Region Connection Timeouts (Node.js 20+)

For cross-region requests that hit `ETIMEDOUT` / `AggregateError`:

```js
import net from "node:net";
net.setDefaultAutoSelectFamilyAttemptTimeout(500); // default is 250ms
```
