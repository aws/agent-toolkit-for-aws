# Lambda Reference

## SDK Version in Lambda Runtimes

Lambda bundles a specific SDK version — not the latest. To control the version, bundle the SDK with your function or use a Lambda layer.

Check the installed version:

```js
const pkg = require("@aws-sdk/client-s3/package.json");
exports.handler = () => JSON.stringify(pkg);
```

## Creating a Lambda Layer

```json
// package.json for layer content
{
  "dependencies": {
    "@aws-sdk/client-s3": "<=3.750.0",
    "@aws-sdk/client-dynamodb": "<=3.750.0"
  }
}
```

Run `npm install`, then zip as:

```text
layer_content.zip
└ nodejs/node_modules/@aws-sdk/...
```

Deploy:

```js
import { Lambda } from "@aws-sdk/client-lambda";
import fs from "node:fs";

const lambda = new Lambda();
await lambda.publishLayerVersion({
  LayerName: "my-sdk-layer",
  Content: { ZipFile: fs.readFileSync("./layer_content.zip") },
  CompatibleRuntimes: ["nodejs20.x", "nodejs22.x"],
  CompatibleArchitectures: ["x86_64", "arm64"],
});
```

## One-Time Async Initialization

Don't call async setup outside the handler — signed requests may expire during provisioned concurrency pre-warming. Use a lazy flag inside the handler instead:

```js
// WRONG: risky — network requests may be frozen pre-flight
const ready = prepare();
export const handler = async (event) => { await ready; ... };

// OK: lazy init inside handler
let client = null;
export const handler = async (event) => {
  if (!client) client = await prepare();
  return client.getItem({ ... });
};
```

SDK clients themselves (no async setup) are safe to initialize outside the handler:

```js
const s3 = new S3Client({}); // OK: outside handler — reused across invocations
export const handler = async (event) => {
  return s3.send(new GetObjectCommand({ ... }));
};
```
