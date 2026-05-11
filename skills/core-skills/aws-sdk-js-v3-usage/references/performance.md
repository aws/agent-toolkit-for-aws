# Performance Reference

## Parallel Workloads (Node.js)

### Socket Configuration

Set `maxSockets` to match your parallel batch size:

```js
import { NodeHttpHandler } from "@aws-sdk/config/requestHandler";
import { Agent } from "node:https";

const client = new S3Client({
  cacheMiddleware: true, // cache middleware resolution — only if not adding custom middleware
  requestHandler: new NodeHttpHandler({
    httpsAgent: new Agent({ keepAlive: true, maxSockets: 50 }),
  }),
});

// Shorthand (v3.521.0+):
const client = new S3Client({
  requestHandler: { requestTimeout: 3_000, httpsAgent: { maxSockets: 50 } },
});
```

Too few sockets → queuing slowdown. Too many → new socket overhead + risk of `EMFILE` (too many open files).

### Sharing Credentials and Socket Pool

```js
const primary = new S3Client({ region: "us-east-1" });
const { credentials, requestHandler } = primary.config;
const secondary = new S3Client({ region: "us-west-2", credentials, requestHandler });
```

### Streaming Deadlock

With limited sockets, don't `await` the request before setting up stream consumption:

```js
// WRONG: deadlock with maxSockets: 1
const responses = await Promise.all([
  s3.getObject({ Bucket, Key: "1" }),
  s3.getObject({ Bucket, Key: "2" }),
]);
await Promise.all(responses.map((r) => r.Body.transformToByteArray()));

// OK: chain stream handling before awaiting
const responses = [s3.getObject({ Bucket, Key: "1" }), s3.getObject({ Bucket, Key: "2" })];
const objects = responses.map((get) => get.Body.transformToByteArray());
await Promise.all(objects);
```

### Batch Upload Example

```js
const BATCH_SIZE = 100;
const client = new S3Client({ requestHandler: { httpsAgent: { maxSockets: 100 } } });

const promises = [];
while (files.length) {
  promises.push(...files.splice(0, BATCH_SIZE).map((f) =>
    client.send(new PutObjectCommand({ Bucket: "b", Key: f.name, Body: f.contents }))
  ));
  await Promise.all(promises);
  promises.length = 0;
}
```
