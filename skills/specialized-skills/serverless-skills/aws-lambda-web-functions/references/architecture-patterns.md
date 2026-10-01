# Architecture Patterns

## API Backend (most common)

REST API with DynamoDB. Low CPU, I/O-heavy.

```javascript
// index.js
import express from 'express';
import { DynamoDBClient } from '@aws-sdk/client-dynamodb';
import { DynamoDBDocumentClient, GetCommand, PutCommand } from '@aws-sdk/lib-dynamodb';

const client = DynamoDBDocumentClient.from(new DynamoDBClient({}));
const app = express();
app.use(express.json({ limit: '10mb' }));

app.get('/items/:id', async (req, res) => {
  const { Item } = await client.send(new GetCommand({
    TableName: 'Items', Key: { id: req.params.id }
  }));
  Item ? res.json(Item) : res.status(404).json({ error: 'not found' });
});

const [HOST, PORT] = (process.env.AWS_LAMBDA_HTTP_ENDPOINT || '0.0.0.0:3000').split(':');
app.listen(PORT, HOST);
```

## SSR (Server-Side Rendering)

Render HTML on the server per request — a plain `index.js` HTTP server, no build step and
no bundler (the runtime loads your `index.js` directly, and Node 24 does **not** transpile JSX):

```javascript
// index.js
import express from 'express';

const app = express();

function renderPage(req) {
  // Build HTML per request. Escape any user-controlled values you interpolate.
  return `<!DOCTYPE html>
<html>
  <head><title>SSR on Lambda Web Functions</title></head>
  <body>
    <h1>Hello from server-side rendering</h1>
    <p>Rendered at ${new Date().toISOString()} for path ${req.path}</p>
  </body>
</html>`;
}

app.get('/', (req, res) => {
  res.set('Content-Type', 'text/html; charset=utf-8').send(renderPage(req));
});

const [HOST, PORT] = (process.env.AWS_LAMBDA_HTTP_ENDPOINT || '0.0.0.0:3000').split(':');
app.listen(PORT, HOST);
```

For heavy SSR, raise `serviceConfig.timeoutSeconds`. Serve static assets
(CSS/JS) from the bundle via `express.static`.

**Using React?** Don't put JSX in `index.js` — Node 24 strips TypeScript types but does not
transform JSX, so raw JSX is a `SyntaxError` at load. Two runnable options:

- **No build step:** author components with `React.createElement` (not JSX) and render with
  `renderToString` (Node build) or `renderToPipeableStream` for streaming; add `react` and
  `react-dom` as dependencies. Note: `renderToReadableStream` is only in the
  `react-dom/server.browser` entrypoint, not the default Node `react-dom/server`.
- **JSX:** add a build step (e.g. esbuild) that compiles your JSX to a plain `index.js`, and
  zip the *built* `index.js` (the runtime entry point must be `index.js`).
  Install with `npm install`, not `npm ci --omit=dev` — pruning first removes the bundler.

## Streaming / SSE (LLM Gateway)

> **WebSocket is out of scope. Server-Sent Events is the streaming path.** A WebSocket handshake is
> not rejected. The request is delivered to the app as an ordinary `GET`, `server.on('upgrade')`
> never fires, and the app answers with whatever its normal route returns, so the caller gets a
> `200` with the app's own response, or a `404` if no route matches, rather than a protocol error.
> Nothing in the response indicates the upgrade was dropped. Verify with
> `curl -i -H 'Connection: Upgrade' -H 'Upgrade: websocket' …` and check that no
> `101 Switching Protocols` comes back.
>
> For bidirectional or push workloads, keep the HTTP surface here and add an API Gateway WebSocket
> API alongside it, or use SSE below when server-to-client push is enough.

Send a response incrementally over one long-lived connection instead of buffering it and replying once — the pattern behind proxying LLM tokens as they arrive, progress updates, and live feeds. It works natively here because your app owns the socket and the platform does not buffer the response; the request stays open until you end it, so the timeout must cover the whole stream, not just the first byte.

Server-Sent Events for LLM token streaming:

```javascript
app.get('/stream', (req, res) => {
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.flushHeaders();

  const interval = setInterval(() => {
    res.write(`data: ${JSON.stringify({ time: Date.now() })}\n\n`);
  }, 1000);

  req.on('close', () => clearInterval(interval));
});
```

Bandwidth is shaped per request **and** capped per execution environment, so size a streaming
workload on the per-environment budget divided by expected concurrency rather than on the
per-request figure (see Multi-Concurrency Considerations below), and check Service Quotas for
current values. Streaming is server-to-client: do not write the response while the request body
is still uploading (see Anti-Patterns in [SKILL.md](../SKILL.md)).

## Background Tasks

The environment stays running after response — fire-and-forget async work continues. For a public
endpoint, verify the sender's signature **before** doing any work. Signatures are computed over
the **raw** body, so capture the raw bytes before JSON parsing or the comparison will never match:

```javascript
import crypto from 'node:crypto';

// Load the signing secret once at module level, from Secrets Manager.
const secret = await getSigningSecret();

app.post('/webhook', express.raw({ type: 'application/json' }), (req, res) => {
  const expected = crypto.createHmac('sha256', secret).update(req.body).digest('hex');
  const provided = (req.get('X-Hub-Signature-256') ?? '').replace('sha256=', '');

  // Length check first: timingSafeEqual throws on a length mismatch.
  const valid = provided.length === expected.length &&
    crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(provided));
  if (!valid) return res.status(401).json({ error: 'invalid signature' });

  res.json({ accepted: true });
  // Defer the parse into the promise chain. Called directly as an argument it would
  // evaluate synchronously, so a malformed body would throw where .catch cannot see it,
  // after the response was already committed.
  Promise.resolve()
    .then(() => processWebhookAsync(JSON.parse(req.body)))
    .catch(console.error);
});
```

## Multi-Concurrency Considerations

Each environment serves many concurrent requests (see [scaling-and-concurrency.md](./scaling-and-concurrency.md) for more details). Key patterns:

- **CPU-bound work**: an environment is allowed 2 vCPU, but a single-threaded Node process uses only one. Use `worker_threads` (or `cluster`) to occupy both; I/O-bound handlers do not need it
- **Network bandwidth**: the per-environment budget is shared by every concurrent request, so per-request throughput falls as concurrency rises
- **SDK clients**: create once at module level, reuse across requests
- **Database connections**: use connection pooling
- **Global state**: avoid mutable shared state; use per-request context
- **File system**: `/tmp` is shared — use unique filenames per request
