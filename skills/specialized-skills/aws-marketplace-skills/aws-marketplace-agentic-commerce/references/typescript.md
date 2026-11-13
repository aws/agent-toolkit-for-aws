# TypeScript: `@aws/fiat-extension-for-x402`

## Contents

- [Install](#install)
- [Express next to an existing network](#express-next-to-an-existing-network)
- [Express with aws:base only](#express-with-awsbase-only)
- [Other frameworks and AWS Lambda](#other-frameworks-and-aws-lambda)
- [Bring-your-own key](#bring-your-own-key)
- [Accept each payment once](#accept-each-payment-once)
- [DPoP replay store](#dpop-replay-store)
- [Behind a proxy](#behind-a-proxy)

## Install

```bash
npm install @aws/fiat-extension-for-x402@^1.0.1 @x402/core @x402/express express   # keep @x402/evm etc. if already used
```

Install the latest release; 1.0.1 is the minimum (the first that signs and requires the scheme and network claims). `@x402/core` 2.x is a peer dependency; see the npm page for the supported Node.js and `@x402/core` versions.

## Express next to an existing network

The seller already protects `GET /weather` with USDC on Base through a remote facilitator. Lines marked `// added` are the whole change:

```typescript
import express from 'express';
import { paymentMiddleware } from '@x402/express';
import { x402Facilitator } from '@x402/core/facilitator';
import { HTTPFacilitatorClient, x402ResourceServer } from '@x402/core/server';
import { ExactEvmScheme } from '@x402/evm/exact/server';
import {
  AgenticCommerceVerifier,
  ExactAgenticCommerceFacilitatorScheme,
  InProcessFacilitatorClient,
  KmsQuoteSigner,
  registerExactAgenticCommerceServer,
} from '@aws/fiat-extension-for-x402'; // added

const KEY_ARN = 'arn:aws:kms:us-east-1:111122223333:alias/my-quote-key'; // added: the listing's key
const SERVICE_URL = 'https://api.example.com'; // added: the listing's endpoint URL
const EXISTING_FACILITATOR_URL = 'https://facilitator.example.com'; // existing

const signer = new KmsQuoteSigner({ keyArn: KEY_ARN, region: 'us-east-1', serviceUrl: SERVICE_URL }); // added
const verifier = new AgenticCommerceVerifier({
  sellerKeyResolver: { type: 'kms', kmsKeyArn: KEY_ARN, region: 'us-east-1' },
}); // added
const awsFacilitator = new x402Facilitator().register(
  'aws:base',
  new ExactAgenticCommerceFacilitatorScheme({ verifier })
); // added

const server = new x402ResourceServer([
  new HTTPFacilitatorClient({ url: EXISTING_FACILITATOR_URL }), // existing
  new InProcessFacilitatorClient(awsFacilitator), // added
]).register('eip155:*', new ExactEvmScheme()); // existing
registerExactAgenticCommerceServer(server, { signer }); // added: aws:base

const payments = paymentMiddleware(
  {
    'GET /weather': {
      accepts: [
        { scheme: 'exact', network: 'eip155:8453', payTo: '0xYourWallet', price: '$0.01' }, // existing
        {
          scheme: 'exact',
          network: 'aws:base',
          payTo: 'prod-example123',
          price: '$0.01',
          extra: { description: 'Current weather', reference: 'weather-v1' },
        }, // added
      ],
      description: 'Current weather',
    },
  },
  server
);

const app = express();
// Express 4 ignores the promise a handler returns, so pass a rejection on.
app.use((req, res, next) => {
  payments(req, res, next).catch(next);
});
// x402 protects GET only, but Express answers HEAD with the GET handler: refuse it.
app.head('/weather', (_req, res) => {
  res.set('Allow', 'GET').sendStatus(405);
});
app.get('/weather', (_req, res) => {
  res.json({ temperatureF: 58 });
});
app.listen(3000);
```

x402 core maps each facilitator client to the networks and schemes it advertises; when two advertise the same pair, the earlier one in the list wins. The remote facilitator advertises `eip155:*`, the in-process facilitator advertises `aws:base`. Instead of a `HEAD` handler per route, a route key `'* /weather'` makes every method pay.

## Express with aws:base only

```typescript
const facilitator = new x402Facilitator().register(
  'aws:base',
  new ExactAgenticCommerceFacilitatorScheme({ verifier })
);
const server = registerExactAgenticCommerceServer(
  new x402ResourceServer(new InProcessFacilitatorClient(facilitator)),
  { signer }
);
```

## Other frameworks and AWS Lambda

Any framework works through x402's framework-neutral `x402HTTPResourceServer` from `@x402/core/server`: build the same `x402ResourceServer` and routes, then for each request call `processHTTPRequest(context)` with an `HTTPAdapter` for the framework's request. On `payment-error`, return the instructions it gives (the `402`). On a verified payment, produce the response, call `processSettlement(paymentPayload, paymentRequirements, declaredExtensions)`, and add its headers (`PAYMENT-RESPONSE`). Call `initialize()` once before the first request.

For an API Gateway HTTP API (payload format 2.0) Lambda, build the adapter's `getUrl()` from `https://${event.requestContext.domainName}${event.rawPath}` plus the raw query string: that is the public URL the buyer called, so DPoP checks pass. Bundle the handler with esbuild (or similar) with this package and `@x402/core` as dependencies, and initialize the resource server once per instance, outside the handler. The function's role needs `kms:Sign` and `kms:GetPublicKey` on the quote key's key ARN (`key/<id>`).

## Bring-your-own key

Replace the KMS signer and resolver when the listing has a JWKS URL:

```typescript
import { readFileSync } from 'node:fs';
import { LocalQuoteSigner, jwksDocument } from '@aws/fiat-extension-for-x402';

const signer = LocalQuoteSigner.fromPem(readFileSync('/run/secrets/quote-key.pem'), {
  kid: 'quote-key-1',
  serviceUrl: SERVICE_URL,
  password: process.env.QUOTE_KEY_PASSWORD || undefined,
});
const verifier = new AgenticCommerceVerifier({
  sellerKeyResolver: { type: 'jwks', jwksUrl: SERVICE_URL }, // /.well-known/jwks.json is appended
});

const jwks = jwksDocument(signer.publicJwk);
app.get('/.well-known/jwks.json', (_req, res) => {
  res.json(jwks); // not a paid route
});
```

Key rules are in [seller-keys.md](seller-keys.md).

## Accept each payment once

Verification is stateless: the facilitator accepts the same payment token on every request until the token or its quote expires. Add an after-verify hook that records the verified payment token's `payment_id` and refuses one already recorded. x402 runs hooks registered with `onAfterVerify` for **every** payment, on every network and also when verification failed, so the hook **MUST** skip anything that is not a valid `aws:base` payment, because recording an unverified token would let a forged one block a real payment:

```typescript
const SKEW_SECONDS = 60;
const claimsOf = (jwt: string) =>
  JSON.parse(Buffer.from(jwt.split('.')[1], 'base64url').toString('utf8'));

interface PaymentStore {
  claim(paymentId: string, expiresAt: number): Promise<boolean>; // false if already recorded
}

// Single process only. Behind several instances, use a shared store instead.
class MemoryPaymentStore implements PaymentStore {
  private seen = new Map<string, number>();
  async claim(paymentId: string, expiresAt: number): Promise<boolean> {
    const now = Date.now() / 1000;
    for (const [id, exp] of this.seen) if (exp <= now) this.seen.delete(id);
    if (this.seen.has(paymentId)) return false;
    this.seen.set(paymentId, expiresAt);
    return true;
  }
}

const acceptEachPaymentOnce =
  (store: PaymentStore) =>
  async ({ paymentPayload, requirements, result }: any) => {
    if (requirements.network !== 'aws:base' || !result.isValid) return undefined;
    // The payment token the facilitator has just verified. Never key on the payload's
    // paymentId: the buyer sets it and nothing checks it.
    const token = claimsOf(paymentPayload.payload.paymentToken);
    const quote = claimsOf(token.quote_token);
    const expiresAt = Math.max(Number(token.exp), Number(quote.exp)) + SKEW_SECONDS;
    return (await store.claim(String(token.payment_id), expiresAt))
      ? undefined
      : { abort: true, reason: 'payment_replayed', message: 'Payment already used' };
  };

server.onAfterVerify(acceptEachPaymentOnce(new MemoryPaymentStore()));
```

Behind several instances, every instance **MUST** share the record. Ask the seller which shared store they use, and implement `claim` on it as an atomic "insert if absent or expired" (for example a conditional write in their database or cache), so two instances cannot both accept the same `payment_id`. If the seller has no shared store, tell them replay protection is not in place across instances.

## DPoP replay store

Pass a `DPoPNonceStore` (`has(jti)`, `add(jti, expiresAt)`, either may be async) to `registerExactAgenticCommerceServer(server, { signer, dpopNonceStore })`. `has` **MUST** return `true` for an id until its `expiresAt` (Unix seconds); the store may forget it from then on. For one process, an in-memory `Map` from `jti` to `expiresAt` that drops expired entries is enough.

With several instances, the store **MUST** be shared, and an async shared store **MUST** record the id atomically in `has` (for example a conditional write in the seller's shared store), because two concurrent requests with the same proof could otherwise both pass. Such a store gets no expiry in `has`, so keep the id for 71 seconds (the default maximum proof age of 60 seconds, plus 5 seconds of clock skew on each side, plus 1).

## Behind a proxy

DPoP proofs are bound to the request URL. `@x402/express` builds it from `req.protocol` and the `Host` header, so behind a load balancer or proxy that terminates TLS you **MUST** set Express's `trust proxy` (for example `app.set('trust proxy', 1)`) and have the proxy forward the original `Host`; otherwise every DPoP-bound payment fails with `dpop_invalid`.
