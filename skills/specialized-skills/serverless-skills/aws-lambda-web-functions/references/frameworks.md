# Frameworks

Entry point must be `index.js` (`aws lambda-web deploy` adds one that imports your entry file when it has another name). Bind the host and port from `AWS_LAMBDA_HTTP_ENDPOINT`. Use `"type": "module"` in package.json for ESM.

## Express.js (Default)

```bash
npm init -y && npm pkg set type=module && npm install express helmet
```

```javascript
// index.js
import express from 'express';
import helmet from 'helmet';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const app = express();
app.use(helmet());
app.use(express.static(join(__dirname, 'public')));
app.use(express.json({ limit: '10mb' }));
app.get('/api/health', (req, res) => res.json({ status: 'ok' }));
app.use((req, res) => res.status(404).json({ error: 'not found' }));
const [HOST, PORT] = (process.env.AWS_LAMBDA_HTTP_ENDPOINT || '0.0.0.0:3000').split(':');
app.listen(PORT, HOST);
```

## Hono

```bash
npm init -y && npm pkg set type=module && npm install hono @hono/node-server
```

```javascript
// index.js
import { serve } from '@hono/node-server';
import { Hono } from 'hono';
import { serveStatic } from '@hono/node-server/serve-static';
import { secureHeaders } from 'hono/secure-headers';

const app = new Hono();
app.use(secureHeaders());
app.use('/static/*', serveStatic({ root: './' }));
app.get('/', (c) => c.html('<h1>Hello from Web Functions</h1>'));
app.get('/api/health', (c) => c.json({ status: 'ok' }));
const [HOST, PORT] = (process.env.AWS_LAMBDA_HTTP_ENDPOINT || '0.0.0.0:3000').split(':');
serve({ fetch: app.fetch, port: Number(PORT), hostname: HOST });
```

## Fastify

```bash
npm init -y && npm pkg set type=module && npm install fastify @fastify/static @fastify/helmet
```

```javascript
// index.js
import Fastify from 'fastify';
import fastifyStatic from '@fastify/static';
import fastifyHelmet from '@fastify/helmet';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const fastify = Fastify({ logger: true });
fastify.register(fastifyHelmet);
fastify.register(fastifyStatic, { root: join(__dirname, 'public') });
fastify.get('/api/health', async () => ({ status: 'ok' }));
const [HOST, PORT] = (process.env.AWS_LAMBDA_HTTP_ENDPOINT || '0.0.0.0:3000').split(':');
fastify.listen({ port: Number(PORT), host: HOST });
```

## TypeScript (Native — No Build Step)

Node 24 type stripping is enabled. Use an `index.js` shim:

```javascript
// index.js (required entry point)
import './app.ts';
```

```typescript
// app.ts (your actual code)
import type { Request, Response } from 'express';
import express from 'express';
const app = express();
app.get('/api/health', (req: Request, res: Response) => res.json({ status: 'ok' }));
const [HOST, PORT] = (process.env.AWS_LAMBDA_HTTP_ENDPOINT || '0.0.0.0:3000').split(':');
app.listen(PORT, HOST);
```

Key: must use `import type` for type-only imports. No `tsc` needed.

**Packaging (required):** the `.ts` source is loaded at runtime, so it MUST be in the ZIP alongside `index.js`. Add your TypeScript source to the include list:

```bash
zip -r function.zip index.js app.ts package.json node_modules/ \
  -x "*.test.*" -x ".git/*" -x ".env"
```

If `app.ts` is omitted from the archive, the deploy starts but crashes immediately with `ERR_MODULE_NOT_FOUND: Cannot find module '/var/task/app.ts'`. Include every `.ts` file your entry shim imports.

## Key Rules

- Entry point: `index.js` (runtime loads `/var/task/index.js`, nothing else)
- Port: bind the host and port from `AWS_LAMBDA_HTTP_ENDPOINT`; the runtime probes that exact address
- Bind to `0.0.0.0` (not localhost)
- Multi-concurrency: many concurrent requests per environment — avoid global mutable state
- Background tasks continue after response — the execution environment stays running
- Streaming/SSE works natively (chunked transfer-encoding)
