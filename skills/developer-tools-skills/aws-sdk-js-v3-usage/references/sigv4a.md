# SigV4a and S3 Multi-Region Access Points

SigV4a (multi-region signing) is required for:

- S3 Multi-Region Access Points (MRAP)
- S3 Object Integrity with certain checksum types
- CloudFront KeyValueStore

Without it you get: `Neither CRT nor JS SigV4a implementation is available.`

## Two implementations — pick one

### Option A: CRT (Node.js only, better performance)

```bash
npm install @aws-sdk/signature-v4-crt
```

```js
import "@aws-sdk/signature-v4-crt"; // side-effect import only — registers itself
import { S3Client, PutObjectCommand } from "@aws-sdk/client-s3";

const client = new S3Client({ region: "us-east-1" });
await client.send(new PutObjectCommand({
  Bucket: "arn:aws:s3::123456789012:accesspoint/mfzwi23gnjvgw.mrap",
  Key: "my-key",
  Body: "hello",
}));
```

### Option B: JavaScript / non-CRT (Node.js + browsers)

```bash
npm install @aws-sdk/signature-v4a
```

```js
import "@aws-sdk/signature-v4a"; // side-effect import only — registers itself
import { S3Client, PutObjectCommand } from "@aws-sdk/client-s3";

const client = new S3Client({ region: "us-east-1" });
// same usage as above
```

## Key rules

- The import is a **side-effect only** — do not use any exported values. Just `import "..."`.
- Do NOT install both. If both are present, CRT takes precedence.
- CRT version does not work in browsers. Use JS version for browser environments.
- JS version in browsers is not recommended due to large bundle size.
- The MRAP bucket ARN format: `arn:aws:s3::<account-id>:accesspoint/<alias>.mrap`
