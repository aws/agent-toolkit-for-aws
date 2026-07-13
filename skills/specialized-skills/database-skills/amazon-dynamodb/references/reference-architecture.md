# DynamoDB-backed full-stack on AWS: a reference architecture

How to build a multi-tenant SaaS web app on AWS with DynamoDB as the
system of record. Every architectural decision is justified by an
access pattern or an operational constraint; every trade-off is stated.

This is a **reference**, not a tutorial. Scope: a full-stack web app
on AWS, backed by DynamoDB, using AWS-recommended patterns.
Non-goals: comparison with third-party IaC tooling
equivalents; vendor-neutral generalities; production-perfect security
posture (see [Known Gaps](#11-known-gaps--honest-trade-offs)).

If you're trying to build something similar, this document is intended
to be a **defensible default** — opinions are stated explicitly, and
where they're contrarian the reasoning is there too. Read this when
you've built CRUD endpoints before, but the *end-to-end composition*
— auth + edge + API + data + async + real-time + search + observability
— is what you're trying to get right. The data modeling section is the
longest because that's where most full-stack designs crack first; the
earlier sections set up the constraints the data layer has to live
inside.

Worked example throughout: a multi-tenant kanban task-board app ("TaskBoard").
Code paths in this doc (e.g. `server/src/...`, `infra/lib/...`) are
illustrative of the example app's layout; they are not links to a
published repository.

## The app, in one paragraph

A multi-tenant kanban task-board app. **Boards** are the tenancy unit; every
piece of content (lists, cards, comments, attachments, activity) hangs
off a board. **Memberships** grant users access to boards with two
roles (`owner`, `editor`). The app must be fast enough for drag-and-
drop reordering, must fan changes out in real-time to every open tab
on a board, must produce a per-board activity feed, and must support
full-text search across cards and lists scoped to boards the caller
can see. Boards have tens to low-thousands of items; users belong to
1–20 boards; total cardinality is well under the levels at which
single-table DynamoDB design begins to dominate.

## Access patterns, ranked by frequency

The schema serves these. If a query isn't on this list, the schema
doesn't promise to make it efficient. **This list is written before
the schema is, and any architecture review starts here.**

| # | Pattern                                                       | Frequency  |
|---|---------------------------------------------------------------|------------|
| 1 | "Render board view" — board meta + all lists + all cards      | every page load on a board |
| 2 | "List my boards"                                              | every home-page load |
| 3 | "Am I a member of this board, and what role?"                 | every API call under `/api/boards/:id/*` (auth gate) |
| 4 | "List comments on this card"                                  | every time a card is opened |
| 5 | "List attachments on this card"                               | every time a card is opened |
| 6 | "Move this card / list" — update one item's `position`        | drag-drop, high burst rate |
| 7 | "Resolve this email to a userId" (invite-by-email)            | once per invite |
| 8 | "List members of this board"                                  | when the share dialog opens |
| 9 | "List recent activity on this board"                          | when the activity panel opens |
| 10 | "Search across my boards" (full text)                        | medium-rare; not a DDB query |
| 11 | "Has this Idempotency-Key been seen?"                        | every mutating request with the header |
| 12 | "Cascade-delete a card, list, or board"                      | rare, but must be correct |

## The big picture

```
                          ┌──────────────────────────────────┐
                          │   Cross-cutting: Identity        │   ← Cognito User Pool
                          │   Cross-cutting: Observability   │   ← Powertools + X-Ray
                          └──────────────────────────────────┘
                                       │
  ┌──── Edge ────┐    ┌── API ──┐    ┌─ Compute ─┐    ┌──── Data ────┐
  │              │    │         │    │           │    │              │
  │  CloudFront  │───▶│  HTTP   │───▶│  Lambda   │───▶│  DynamoDB ×9 │
  │  + WAF       │    │  API    │    │ (Lambda-  │───▶│  S3          │
  │  + SPA via   │    │ + JWT   │    │   lith)   │───▶│  OpenSearch  │
  │    S3 + OAC  │    │  authz  │    │           │───▶│  AppSync ─── ─── (WebSocket back to browser)
  │              │    │         │    │           │───▶│  EventBridge │
  └──────────────┘    └─────────┘    └───────────┘    │  → SQS → SES │
                                                       └──────────────┘
                                          ▲
                                          │ DynamoDB Streams
                                          │
                                          ▼
                                    Sidecar Lambdas
                                    (activity feed,
                                     OpenSearch indexer,
                                     SQS→SES email)
```

**Edge** terminates TLS, runs WAF, serves the SPA, and proxies `/api/*`
to the API layer (same-origin from the browser's perspective). **API**
authenticates the request at the managed edge and routes to compute.
**Compute** is one HTTP server framework app on Lambda (a "lambdalith"), with a
few sidecar Lambdas for event-driven work. **Data** is multiple small
DynamoDB tables with natural keys, S3 for blobs, OpenSearch for
search-time queries. Two cross-cutting concerns — identity and
observability — touch every layer.

### A request, end to end

Useful to walk once. A user opens the app and creates a card:

1. Browser hits the CloudFront URL. CloudFront serves `/index.html` and
   the SPA bundle from a private S3 bucket via Origin Access Control.
2. The SPA fetches `/api/config` (public, no auth) to learn the Cognito
   domain + clientId + AppSync realtime URL.
3. The SPA redirects to Cognito Managed Login with PKCE. User signs in,
   Cognito redirects back to `/auth/callback?code=…&state=…`.
4. The SPA exchanges the code for tokens at Cognito's token endpoint,
   stores the access token, opens an AppSync Events WebSocket using
   that token for auth.
5. SPA fetches `/api/boards` with `Authorization: Bearer <access_token>`.
   CloudFront's `/api/*` behavior forwards to the HTTP API. HTTP API's
   native Cognito JWT authorizer validates the token at the managed
   edge — no Lambda invocation if validation fails.
6. Lambda (the lambdalith) runs the HTTP framework app, hits `BoardMemberships.ByUser`
   GSI to list memberships, parallel-`GetItem`s the `Boards` rows,
   returns JSON.
7. User opens a board, drags a card to a new list, drops it. SPA sends
   `PATCH /api/boards/:id/cards/:id` with the new `position` and
   `listId`. The same Lambda authorizes membership, writes one
   `UpdateItem` to `BoardItems` (with a `ConditionExpression` so a
   bogus cardId 404s instead of upserting a phantom row), and best-
   effort-publishes a `card.updated` event to AppSync Events.
8. The DynamoDB Stream on `BoardItems` fires:
   - **ActivityFn** writes a summary row into `Activity(boardId, SK)`.
   - **SearchIndexFn** upserts the card into OpenSearch.
9. Every other browser tab subscribed to this board's AppSync channel
   receives the `card.updated` payload over its WebSocket and merges
   the change into local state.
10. The user invites a teammate. The route writes a `BoardMemberships`
    row and emits one EventBridge event. The rule routes it to SQS,
    which triggers a separate notification Lambda, which calls SES
    SendEmail. The HTTP response returned 201 before any of that ran.

What an agent designing this should internalize from the walkthrough:
**the HTTP request's job is to make the durable write and return.**
Every observable effect (activity feed, search indexing, real-time
fan-out, transactional email) is fanned out asynchronously. Latency
on the request path is bounded by one or two DynamoDB calls.

## 1. Identity: Cognito + OAuth 2.1

**Pattern**: managed identity provider, standards-based OAuth, IdP
state projected into your application database.

Use [Amazon Cognito User Pools][cognito] when you need to ship sign-up,
sign-in, password reset, MFA enrollment, federated identity, and a
hosted UI without writing it. The alternative is rolling your own
password storage + bcrypt + email verification + MFA secrets, and the
math never works out: managed wins on both effort and security.

**OAuth flow**: authorization-code grant **with PKCE**, implicit grant
**disabled**. Implicit puts tokens in URLs and gives you no refresh
token; the IETF's OAuth 2.0 for Browser-Based Apps BCP
deprecates it for SPAs. PKCE binds code redemption to a per-request
secret only the originating client knows.

**Use access tokens, not ID tokens** for API authorization. ID tokens
identify the user to the client; access tokens authorize the client to
the API. AWS makes this point explicitly in the
[HTTP API JWT authorizer docs][jwt-authorizer]:

> "There is no standard mechanism to differentiate JWT access tokens
> from other types of JWTs… we recommend that you configure your
> routes to require authorization scopes."

This codebase defines two custom scopes on a Cognito resource server
(`boards.read`, `boards.write`); the access token carries them, and
the API Gateway authorizer enforces presence per-route.

**Managed Login over a custom hosted UI for v1.** Managed Login is
Cognito's hosted sign-in experience; it gets you passkeys,
branding, MFA enrollment, password reset, and federated sign-in
out-of-box. Adopt the SRP flow with a fully bespoke UI later if you
need brand control beyond what the Managed Login editor exposes — the
brand-control ceiling is the only common reason to leave Managed
Login, and you can stage the migration without breaking existing
tokens because both flows ultimately hit the same User Pool.

**Project identity into your DB**. Application code should never query
Cognito at request time — too slow, single point of failure. A
**post-confirmation Lambda trigger** (`cognito-post-confirmation.ts`)
fires once per verified signup and writes a `Users` row keyed by the
Cognito `sub` (immutable UUID). App code then reads `Users` like any
other table.

**Make the trigger writes idempotent and unconditional.** An earlier
revision of this Lambda used a `TransactWriteItems` with
`attribute_not_exists(email)` to enforce uniqueness on `UserEmails`,
which rolled back on any stale row — leaving Cognito users without app
rows, manifesting as `/api/auth/me` 404s. Replace with two
unconditional `PutCommand`s; let idempotency be a property of the
writes, not a property of the transaction.

**Gotcha: the callback-URL circular dependency.** Cognito needs to
know the SPA's URL (for callback registration). The SPA is served by
CloudFront. CloudFront's URL isn't known until it's deployed. Lambda
needs the Cognito clientId, which doesn't exist until Cognito does. If
you wire all of this naively in one stack, CFN deadlocks.

The fix in `infra/bin/app.ts`: externalize the
SPA URL via a `TASKBOARD_APP_URL` env var read at synth time. First
deploy uses `http://localhost:5173` as a placeholder; subsequent
deploys use the real CloudFront URL. Any time you have an
asymmetric two-way reference between resources in a stack, breaking
the cycle externally is cleaner than dependency-injecting a stub.

## 2. Edge: CloudFront + WAF

**Pattern**: edge cache + edge security in front of compute, single
origin to the browser.

```
Browser → CloudFront (with WAF web ACL) ┬→ /          → S3 SPA bucket (OAC, cached)
                                        └→ /api/*     → HTTP API → JWT authorizer → Lambda
```

**WAF lives on CloudFront, not API Gateway.** HTTP API isn't on
[WAF's supported-resource list][waf-resources]. The workaround everyone
arrives at: front the HTTP API with CloudFront and attach the web ACL
to the distribution.

**CloudFront WAF WebACLs must be in `us-east-1`** because CloudFront
is a global service. The main stack can be in any region. Resolution:
a second CDK stack (`infra/lib/waf-stack.ts`)
deploys to us-east-1 and the main stack references it via CDK's
`crossRegionReferences: true`. CDK handles the ARN handoff through a
custom-resource Lambda that reads SSM Parameters cross-region.

**Single-origin trick**: CloudFront has two cache behaviors — `/api/*`
forwards to the HTTP API; everything else serves from the S3 SPA
bucket via Origin Access Control. The SPA fetches `/api/*` as
same-origin paths and never has to know the HTTP API hostname. CORS
becomes a non-issue for the SPA → API hop. (CORS still configured for
the Function URL path used in local dev.)

**Security headers** (HSTS, X-Frame-Options, X-Content-Type-Options,
Referrer-Policy) come from a CloudFront `ResponseHeadersPolicy`, not
from the Lambda. Adding CSP belongs here too if you care about
hardening against XSS-based token theft (this codebase doesn't yet —
known gap).

**SPA fallback**: 403 and 404 from the S3 origin remap to `/index.html`
with status 200. Client-side routes (`/boards/abc`, `/auth/callback`,
etc.) work without server config.

**Gotcha: HTTP API's invoke URL is publicly reachable.** Even with the
WAF on CloudFront, the underlying HTTP API endpoint
(`xxx.execute-api.region.amazonaws.com`) is also reachable directly,
which bypasses WAF entirely. Production hardening: have CloudFront
inject a secret origin header; reject requests at the Lambda (or in a
Lambda@Edge) that lack it. This codebase ships with the gap documented
but unfixed — fine for a reference, not fine for prod.

## 3. API: HTTP API + JWT authorizer

**Pattern**: managed API gateway with managed-edge JWT verification,
not a Lambda authorizer or in-app auth middleware.

**Choose HTTP API over REST API.** AWS publishes a
[direct comparison][http-vs-rest]; HTTP API is materially cheaper, lower
latency, and has a native JWT authorizer (check the comparison for the
current price delta). REST-API-only features (API
keys, usage plans, edge-optimized endpoints, request validation,
direct WAF attach) are mostly enterprise concerns that don't apply to
modern web apps. Pick REST API the day you sell metered API access by
plan.

**Native Cognito JWT authorizer**, not a Lambda authorizer. The
authorizer validates `iss`, `aud`, `exp`, scopes, and caches JWKS for
2 hours — all at the managed edge, never inside your function. Token
verification stays off the cold-start path. The Lambda *also* verifies
the token via a JWT verification library as defense in depth
(<1 ms per request) — relevant if a future change accidentally
removes the authorizer at the API Gateway level.

**Public vs. authenticated routes.** The CDK adds the JWT authorizer
only to a catch-all `/{proxy+}` route. The two public endpoints
(`/api/health`, `/api/config`) are added as separate routes without
the `authorizer` prop. There's no `defaultAuthorizer` — adding routes
without explicit auth would silently make them public if there were.

**CORS belongs on the API**, not in your application framework. API Gateway
strips backend CORS headers ([per the docs][http-cors]) and applies its
own. Concretely:

```ts
corsPreflight: {
  allowOrigins: [spaUrl, "http://localhost:5173"],
  allowMethods: [CorsHttpMethod.ANY],
  allowHeaders: ["authorization", "content-type", "idempotency-key"],
  allowCredentials: true,
  maxAge: Duration.minutes(5),
}
```

Wildcard origins (`["*"]`) with `allowCredentials: true` is invalid
per the CORS spec; always enumerate concrete origins.

**Idempotency**. Mutating requests carry an `Idempotency-Key` header
(an `Idempotency-Key`-aware middleware caches 2xx responses in a
`IdempotencyKeys` DDB table with 24h TTL). The client auto-generates
the UUID, so the dedup is invisible to user code. Pattern lifted from
the [Well-Architected Serverless Lens][wa-serverless] and matches the
shape of the [Powertools Idempotency module][powertools-idempotency].

## 4. Compute: the Lambdalith

**Pattern**: one Lambda function per *microservice*, not per route.

A "lambdalith" runs your whole HTTP framework app inside one function via
a Lambda adapter for that framework. Most teams default to
one-function-per-route because "single responsibility"; the
[AWS Well-Architected Serverless Lens][wa-serverless-rest] actually
shows one Lambda fronted by one API Gateway as the canonical
RESTful-microservices pattern. "Single purpose" applies at the
microservice boundary, not the URL.

Trade-offs:

| Aspect                 | Lambdalith                                        | One-per-route                                            |
|------------------------|---------------------------------------------------|----------------------------------------------------------|
| Cold starts            | Fewer (shared warm pool), bigger init             | Many, but each smaller                                   |
| IAM blast radius       | Union of all routes' permissions on one role      | Per-route least-privilege                                |
| Local dev parity       | Same app runs on a local HTTP port or in Lambda   | Local dev needs a router shim                            |
| Deploy granularity     | One artifact, one version                         | N artifacts; per-route rollback                          |
| Per-route concurrency  | Function-level reserved concurrency only          | Per-route throttling natively                            |
| Observability          | One log group, route-level dims via Powertools    | Per-function metrics free                                |

**When to split out a separate Lambda**: different trigger, different
scaling profile, or different IAM surface. This codebase has four
sidecar Lambdas, each clearly matching one of those:

- `notification-lambda.ts` —
  triggered by SQS (different trigger), needs `ses:SendEmail`
  (different IAM scope).
- `activity-lambda.ts` — triggered by
  DynamoDB Streams.
- `search-index-lambda.ts` —
  Streams again, but separated from activity so a search-indexer bug
  can't break activity tracking.
- `cognito-post-confirmation.ts`
  — Cognito User Pool trigger.

**Bundling**. `aws-cdk-lib/aws-lambda-nodejs` bundles via its built-in bundler. The
non-obvious knob:

```ts
bundling: {
  format: OutputFormat.CJS,
  minify: false,
  sourceMap: true,
  target: "node20",
  externalModules: ["@aws-sdk/*"],   // ← important
}
```

The Lambda runtime ships with `@aws-sdk/*` v3 preinstalled. Bundling
your own copy adds ~3 MB to every deploy and is slower at cold start.
`externalModules` keeps it out of the artifact.

**arm64** (Graviton) over x86 — generally better price-performance for
Node workloads (check the current Lambda pricing page for the delta).
Always default to arm64 unless you have a native
dependency that doesn't ship an arm64 binary.

## 5. Data: DynamoDB, multi-table, on purpose

**Pattern**: many small tables with obvious natural keys, partitioned
on the tenancy boundary — not one overloaded mega-table.

This section is the longest. It's where most full-stack designs crack
first — the API and edge layers compose from well-documented
primitives; the data layer is where the tenancy model, the
authorization model, and the access patterns all collide.

### Schema overview

```
Users(userId)                       UserEmails(email)         ← email→userId pointer for invite-by-email
   │                                       │
   └─────── identity layer ───────┬────────┘
                                  │
Boards(boardId)                   │
   │                              │
   ├─ BoardMemberships(boardId, userId)  ─GSI ByUser(userId, boardId)─▶  "list my boards"
   │
   ├─ BoardItems(boardId, SK)     SK = "list#<uuid>" | "card#<uuid>"  → polymorphic items
   │     └─Streams─▶ ActivityFn   ──▶ Activity(boardId, SK)         TTL 90d
   │              ─▶ SearchIndex  ──▶ OpenSearch                    (projection, not DDB)
   │
   ├─ Attachments(boardId, SK)    SK = "<cardId>#<attachmentId>"    ─cascade─▶ S3
   │
   └─ Comments(boardId, SK)       SK = "<cardId>#<createdAt>#<commentId>"

IdempotencyKeys(id)               TTL 24h                            ← request-dedup cache
```

Nine tables, each holding one entity (`BoardItems` is the principled
exception — see *Composite SKs* below). The schema lives in
`infra/lib/taskboard-app-stack.ts`;
access is mediated by one module per table in
`server/src/repositories/`.

### Walking the tables

#### `Users(userId)`

```jsonc
{ "userId": "<cognito-sub-uuid>", "email": "alice@example.com",
  "displayName": "Alice", "createdAt": "2026-05-01T10:00:00Z" }
```

PK is the Cognito `sub` (immutable UUID). Written by the
post-confirmation Lambda. Access: `GetItem(userId)`. No GSI.

#### `UserEmails(email)`

```jsonc
{ "email": "alice@example.com", "userId": "<sub>" }
```

The reverse pointer for invite-by-email. A separate table (not a GSI
on `Users`) so it can be repointed during backfills without touching
the canonical user row. Normalize email to lowercase + trimmed at
every write and read.

#### `Boards(boardId)`

```jsonc
{ "boardId": "<uuid>", "name": "Q2 launch", "createdAt": "...",
  "createdBy": "<userId>" }
```

Board metadata. Tiny rows. `GetItem(boardId)`.

#### `BoardMemberships(boardId, userId)`

```jsonc
{ "boardId": "<uuid>", "userId": "<uuid>",
  "role": "owner" | "editor", "addedAt": "..." }
```

The join table. PK `boardId` so "who is in this board?" is one
`Query`. SK `userId` so "is this user in this board?" — the auth-gate
query fired on **every** request — is one `GetItem`.

**GSI `ByUser(userId, boardId)`** with `ALL` projection. Inverts the
relationship so "list my boards" is one `Query(userId)`. One
inverse-direction GSI per many-to-many table is near-universal;
resist adding more.

#### `BoardItems(boardId, SK)` — polymorphic items table

```jsonc
// A list
{ "boardId": "<uuid>", "SK": "list#<uuid>",
  "name": "Doing", "position": 2048 }

// A card
{ "boardId": "<uuid>", "SK": "card#<uuid>",
  "listId": "<uuid>", "title": "Wire up CI",
  "description": "...", "labels": ["infra"],
  "dueDate": null, "position": 1024 }
```

**One table, two entity types, partitioned by board.** The canonical
item-collection pattern. "Render board view" — pattern #1, the most
frequent read — becomes a single `Query(boardId)` returning everything.
The SK encodes the type as a prefix (`list#…` / `card#…`).

Position-based reordering (drag-drop, #6) uses a numeric `position`
attribute computed as `midpoint(prev, next)` between neighbors. An
insert is one `UpdateItem`. *Never* reorder DDB items.

Streams enabled (`NEW_AND_OLD_IMAGES`) — this is the only table whose
changes power downstream projections.

#### `Attachments(boardId, SK)`

```jsonc
{ "boardId": "<uuid>", "SK": "<cardId>#<attachmentId>",
  "cardId": "<uuid>", "attachmentId": "<uuid>",
  "filename": "logo.png", "contentType": "image/png",
  "size": 42137, "s3Key": "attachments/<attachmentId>",
  "uploadedAt": "...", "uploadedBy": "<userId>" }
```

PK is `boardId`, not `cardId`. The reason is its own section below
(*Authorization via partition key*). SK `<cardId>#<attachmentId>` lets
`begins_with(SK, "<cardId>#")` list one card's attachments.

#### `Comments(boardId, SK)`

```jsonc
{ "boardId": "<uuid>", "SK": "<cardId>#<createdAt>#<commentId>",
  "cardId": "<uuid>", "commentId": "<uuid>",
  "authorId": "<userId>", "authorDisplayName": "Alice",
  "content": "shipping today", "createdAt": "..." }
```

Three-segment SK: **grouping** (`cardId`) + **ordering** (`createdAt`,
ISO-8601 lexicographic = chronological) + **uniqueness** (`commentId`).
Reusable shape for any "subset queried in stable order" pattern.

#### `Activity(boardId, SK)` — TTL'd append-only feed

```jsonc
{ "boardId": "<uuid>", "SK": "<createdAt>#<eventId>",
  "type": "card.created", "actorId": "<userId>",
  "summary": "Alice created \"Wire up CI\"",
  "createdAt": "...", "expiration": 1735689600 }
```

Append-only. Written by `ActivityFn` from the `BoardItems` Stream.
`Query(boardId)` with `ScanIndexForward: false` returns newest-first.
TTL on `expiration` (90 days) silently deletes old rows.

**TTL gotcha**: `expiration` must be **unix epoch in seconds**. Writing
`Date.now()` (milliseconds) gives you a year-50,000 timestamp and the
row never deletes. Divide by 1000.

#### `IdempotencyKeys(id)`

```jsonc
{ "id": "<userId>:POST:/api/boards:<client-uuid>",
  "status": "completed", "responseStatus": 201, "responseBody": { ... },
  "expiration": 1735689600, "createdAt": "..." }
```

PK is a composite string scoping the key by user + method + path +
client UUID, so two users using the same client UUID can't collide,
and the same UUID across two different routes is a different cache
entry. 24h TTL.

### Patterns worth copying

#### Authorization via partition key

The single most-load-bearing principle in this schema:

> **A row's partition key is the same as the authorization scope you
> check before reading or writing the row.**

`BoardMemberships` is the auth gate: every request to
`/api/boards/:boardId/*` does one `GetItem(boardId, userId)` to prove
membership. *Every table holding board-scoped data is then
partitioned by `boardId`* — so the membership check and the data
lookup share the same partition.

The reason this matters becomes vivid the moment you violate it. An
earlier revision keyed `Comments` and `Attachments` by `cardId` alone
— natural because they're hierarchically owned by cards. But the auth
check proves `boardId`, and the data lives under `cardId`. A member of
board A who learned a `cardId` from board B (UUIDs aren't
secret-grade authorization material) could route through their own
`boardId` and reach data they shouldn't see. Classic
IDOR (Insecure Direct Object Reference).

The fix was repartitioning both tables onto `boardId`:

- `Comments`: PK `cardId` → `boardId`; SK `<createdAt>#<commentId>` →
  `<cardId>#<createdAt>#<commentId>`.
- `Attachments`: PK `cardId` → `boardId`; SK `attachmentId` →
  `<cardId>#<attachmentId>`.

After: `Query(boardId=A, begins_with(SK, "<cardId-from-B>#"))` *finds
nothing* because the data isn't in that partition. The auth and the
lookup collapse into the same operation.

**Generalization**: pick PK to match your tenancy boundary. Multi-
tenant on `accountId`? PK is `accountId`. Per-user data? PK is
`userId`. If a piece of data must cross tenants, expose it through a
*separate* table with its own keying rules — don't compromise the
guarantee on the main one.

#### Composite sort keys, two flavors

| Purpose | Example | SK shape |
|---|---|---|
| **Polymorphism** — many entity types in one partition | `BoardItems`: lists + cards | `<type>#<id>` |
| **Ordering + grouping** — query a logical subset in stable order | `Comments`: one card's comments, chronologically | `<group>#<order>#<unique>` |

Both compose with `begins_with(SK, prefix)`. `Query` reads in SK
order, so the order segment becomes the result order.

#### One GSI, on the inverse relationship

`BoardMemberships.ByUser` (PK `userId`, SK `boardId`, projection
`ALL`) turns "list my boards" from a scan into one `Query(userId)`.
Pattern: when a many-to-many join table exists, the GSI flips PK/SK so
you can ask either direction.

Each GSI costs storage and write capacity (every base-table write
replicates to every GSI). Build them as access patterns surface and
prove themselves, not eagerly. This codebase has one GSI total.

#### `TransactWriteItems` for atomic cross-table creates

Creating a board must atomically write a `Boards` row **and** a
`BoardMemberships` row with `role = "owner"`. Either both land or
neither.

```ts
await ddb.send(new TransactWriteCommand({
  TransactItems: [
    { Put: { TableName: BOARDS_TABLE,
             Item: { boardId, name, createdAt, createdBy: userId } } },
    { Put: { TableName: BOARD_MEMBERSHIPS_TABLE,
             Item: { boardId, userId, role: "owner", addedAt: createdAt } } },
  ],
}));
```

Constraints worth knowing: max **100 items / 4 MB** per transaction,
items can span tables but not regions or accounts, 2× the WCU cost of
the equivalent single-item writes. Use only when atomicity matters;
don't use for bulk writes (BatchWriteItem) or for read consistency
(`ConsistentRead: true` on `GetItem`).

#### Conditional writes encode invariants in the data layer

Two examples worth copying:

**Prevent upsert.** `UpdateItem` defaults to creating the row if the
key doesn't exist. `PATCH` with a guessed cardId would silently create
a phantom card. Fix:

```ts
new UpdateCommand({
  TableName: BOARD_ITEMS_TABLE,
  Key: { boardId, SK: cardSk(cardId) },
  UpdateExpression: "SET ...",
  ConditionExpression: "attribute_exists(boardId)",  // ← update-only, no upsert
})
```

Catch `ConditionalCheckFailedException` and translate to 404.

**Invariant preservation: the last-owner guard.** A board must always
have ≥1 owner; demoting or removing the last owner is blocked. Two
implementations:

- *Application-side*: `countOwners(boardId)` first; 409 if it would
  drop to zero. Easy to write; races under concurrent demotes.
- *DDB-side*: maintain `Boards.ownerCount` transactionally with every
  membership-role write; demote/delete carries
  `ConditionExpression: "ownerCount > 1"`. Race-free.

This codebase uses the first because contention is sub-millisecond and
the cost of a lost race is recoverable. Production code with real
concurrent edits would use the second. The choice is honest: encode
the invariant where the contention matters.

#### Streams as the integration backbone

`BoardItems` emits a DynamoDB Stream (`StreamViewType: NEW_AND_OLD_IMAGES`).
Two Lambdas consume it independently:

- `ActivityFn` → writes to `Activity` for the feed.
- `SearchIndexFn` → upserts into OpenSearch.

The property this buys: **one write to `BoardItems` deterministically
produces N derived projections.** Search and activity can be
re-derived from the table (`scripts/backfill-search-index.mjs`)
without touching the source.

Three settings every Stream consumer must set:

- `bisectBatchOnError: true` — a poison record halves the batch,
  isolating the bad item instead of stalling the shard.
- `reportBatchItemFailures: true` + `onFailure: new SqsDlq(dlq)` —
  failures don't retry forever; bad records end up in a DLQ.
- `retryAttempts: 5` (or bounded) — combined with the DLQ.

Without these, one malformed record stalls the shard for the full
**24-hour** stream retention while every batch fails. Look for these
on every Stream consumer you write.

#### Cascade deletes via chunked `BatchWriteItem`

```ts
const items = await ddb.send(new QueryCommand({ /* … */ }));
for (let i = 0; i < items.length; i += 25) {              // ← BatchWriteItem
  const chunk = items.slice(i, i + 25);                   //   caps at 25
  await ddb.send(new BatchWriteCommand({                  //   items per call
    RequestItems: { [TABLE]: chunk.map(it => ({
      DeleteRequest: { Key: { /* pk + sk */ } }
    })) },
  }));
}
// S3 deletes follow, after DDB rows are durable
```

Mid-cascade crash leaves orphan S3 objects (recoverable via S3
lifecycle), not dangling DDB rows pointing at nothing.

Not used here, but possible: `TransactWriteItems` for deletes — but
the 100-item cap and 2× cost make it wrong for cascades over a few
items.

#### TTL for ephemeral state

`IdempotencyKeys` (24h) and `Activity` (90d). TTL is **free** — no
extra WCU, eventually-consistent delete (typically within 48h of the
timestamp). Right shape for: idempotency caches, sessions, audit logs,
short-lived events, soft-deletes.

### What this schema deliberately rejects

#### Single-table design

The most-cited DynamoDB pattern from Rick Houlihan's talks: collapse
all entities into one table with overloaded PK/SK to maximize index
re-use. It wins at high scale with **stable, fully-known** access
patterns.

Rejected here because:

- Access patterns are still evolving. The reference exists to be
  cloned and modified; an overloaded schema is brittle to change.
- IAM is per-table: granting "this Lambda can write to the search
  index but not modify board content" requires separate tables.
- Operational clarity: `aws dynamodb scan --table-name Boards` returns
  boards. The reader doesn't need a 60-line ER mental model.

If you ever become I/O-bound (sustained tens of thousands of WCUs
across many small tables, with each access pattern's round-trip cost
becoming the bottleneck), single-table starts to pull ahead. Until
then, multi-table with natural keys is the boring-and-correct default.

Read a dedicated DynamoDB single-table-design reference regardless of which
camp you're in.

#### A `Cards(cardId)` table separate from lists

Cards and lists share one partitioning key (`boardId`) and one access
pattern (#1). Splitting them would mean two `Query` round trips on
the most-frequent read for no benefit. They live in `BoardItems`
together, distinguished by SK prefix.

#### A GSI on every alternate-access dimension

Tempting to add `Cards.ByListId`, `Cards.ByLabel`, `Cards.ByDueDate`
as patterns surface. Resist until a pattern is **frequent enough** to
justify the write amplification. For one-off "all cards with label X"
queries, the OpenSearch projection is the right home.

#### A `Notifications` table

Notifications are dispatched **immediately** via EventBridge → SQS →
SES (email) and via AppSync Events (real-time). Nothing is buffered
in DDB. If you wanted a per-user in-app inbox, the shape would be
`Notifications(userId, SK="<createdAt>#<eventId>")` with TTL — same
pattern as `Activity`, scoped to user.

### DynamoDB defaults worth keeping

- **`PAY_PER_REQUEST`** until traffic is forecastable. Break-even with
  **provisioned** capacity is roughly 18% sustained utilization
  (reserved/committed capacity needs higher sustained use to pay off — see
  the capacity-mode note in §12), but PAY_PER_REQUEST shields you from
  forecasting errors.
- **Point-in-Time Recovery** on every table. 35-day continuous backup,
  cheap, one toggle. The day you need it, it's there.
- **AWS-managed-key encryption at rest** unless compliance requires
  CMK.
- **`removalPolicy: RETAIN`** on production tables in CDK. The default
  is `DESTROY`, which deletes your data when the stack is deleted.
  This codebase uses `DESTROY` for reference-cleanliness; don't copy
  that bit to prod.

## 6. Async & real-time

**Pattern**: anything that doesn't have to finish before the HTTP
response gets fanned out asynchronously; the HTTP request's job is to
make the durable write and return.

Four canonical patterns. Each shape has a reason for being what it is.

```
1. Transactional email (fire-and-forget, must be reliable):
   API Lambda → EventBridge → SQS → Notification Lambda → SES

2. Real-time push (browser sees changes within ~250 ms):
   API Lambda → AppSync Events ─WebSocket─▶ subscribed browsers

3. Derived state (search index, activity feed):
   DynamoDB Streams → consumer Lambda → projection

4. Large file upload (never proxy through Lambda):
   Browser ─presigned PUT─▶ S3
```

### `EventBridge → SQS → Lambda → SES`, not `Lambda → SES`

Why the extra hops? Decoupling. The user POSTs an invite; the API
writes the `BoardMemberships` row and emits one EventBridge event;
the rule routes to SQS; the notification Lambda consumes from SQS and
calls SES. The user's HTTP request returned 201 before any of that
ran.

What this buys:

- **SES throttling** doesn't back-pressure the API.
- **Failures** get retry + DLQ for free (SQS visibility timeout +
  redrive policy).
- **A second consumer** of the same event (e.g. in-app notifications)
  is one new EventBridge rule, no API changes.
- **Auditability** — the event payload sits in CloudWatch (and
  optionally S3 via EventBridge archive) for replay.

Settings to copy:

- SQS visibility timeout ≥ Lambda timeout × 6 (AWS recommendation for
  Lambda consumers).
- `batchSize: 10`, `reportBatchItemFailures: true` so one failed
  message in a batch doesn't redrive the rest.
- DLQ with `maxReceiveCount: 5` and 14-day retention.

### AppSync Events for real-time

[AppSync Events][appsync-events] is a purpose-built serverless WebSocket
pub/sub service. **It replaces** the legacy
pattern of (API Gateway WebSocket + Connections table + DynamoDB
Streams + fan-out Lambda calling `PostToConnection` per connectionId).
All of that plumbing — easily 200 LOC and four resources — collapses
into "publish to a channel; subscribers receive over WebSocket."

This codebase uses AppSync Events with two auth modes:

- **IAM** (SigV4) for the API Lambda to publish (it owns the
  publishing identity).
- **Cognito User Pool** for browsers to subscribe with their access
  token.

The publish call from the API Lambda is **best-effort** — wrapped in a
try/catch that swallows errors. A transient AppSync blip shouldn't
fail the user's HTTP request. Real-time is a *side channel*; the
HTTP response is the source of truth, and a missed event simply gets
reconciled on the next page load.

**Gotcha: channel-level authorization is not enforced by default.**
Anyone with a valid Cognito token can subscribe to *any* board's
channel. The fix is a channel-namespace JS resolver that checks
`BoardMemberships` before allowing subscribe. Documented known gap in
this codebase.

### S3 presigned URLs for uploads

The API generates a short-lived URL signed for `PutObject`; the
browser PUTs bytes directly to S3. The Lambda never touches the file
data — a 5 MB upload doesn't push the Lambda through its memory tier.

Flow:

1. SPA POSTs metadata (filename, contentType, size) to the API.
2. API validates (size cap 25 MB), generates `attachmentId`, writes
   the `Attachments` row, returns a presigned PUT URL (5-min TTL).
3. SPA PUTs the file bytes to S3 directly, no `Authorization` header
   (the signature is in the URL).
4. SPA re-fetches the attachment list to get a fresh presigned GET URL
   (1-hour TTL) for display.

Two S3 clients in the Lambda code
(`server/src/lib/s3.ts`):

- The **internal** client for SDK calls reachable from the Lambda
  runtime.
- A **signer-only** client whose endpoint is the hostname *the browser*
  will resolve. With a local AWS-emulation tool this matters (container-internal IP vs.
  `localhost:4566`); in real AWS the two are the same, so the
  abstraction is a no-op.

**S3 bucket CORS**: keep it tight. Wildcard `["*"]` is overly
permissive even with presigning; restrict to your CloudFront origin
in production.

## 7. Search: OpenSearch as a projection

**Pattern**: search is a derived view, not the source of truth.

`SearchIndexFn` consumes the `BoardItems` Stream and writes documents
to an OpenSearch index. The API's `/api/search` route queries
OpenSearch, filtering by the caller's `boardId` set (the auth check
moves to the application here since OpenSearch doesn't know about
membership).

Drop the index, re-run `scripts/backfill-search-index.mjs`, no data
lost.

**Sizing for small apps**: a smallest-tier single search node, single AZ,
~10 GB GP3 EBS — typically the largest single contributor to the stack's
idle cost. Check current supported instance types and their rates with
`aws opensearch list-instance-type-details --engine-version <ver>` (and the
OpenSearch Service pricing page) rather than hardcoding a class, since the
small-tier instance families and prices change over time. For production:
2+ data nodes + 3 dedicated master nodes across AZs.

**Auth: SigV4 with IAM**, not user/password.
The OpenSearch project's official client library provides an AWS SigV4 signer that
handles request signing inside the client. Both the indexer Lambda
and the API Lambda use it; the domain's resource policy
(`grantReadWrite`) is what actually allows the call.

**Mapping gotcha**: OpenSearch dynamic mapping indexes string fields
as both `text` (analyzed, broken into tokens) and `<field>.keyword`
(exact). A `terms` filter on UUIDs (e.g. `terms: { boardId: [...] }`)
only works against `.keyword` because UUID dashes split the text
analyzer into multiple terms. Use `boardId.keyword` for exact-match
filtering, or set an explicit index template that maps `boardId` as
`keyword` to control this rather than discovering it later.

## 8. Observability: Powertools + X-Ray

**Pattern**: structured logs + distributed traces + custom metrics,
wired identically on every Lambda.

- [**Logger**][powertools-logger]: structured JSON, auto-injects
  `cold_start`, `xray_trace_id`, `function_request_id`, `service`.
  Per-request fields (`user_id`, `board_id`) added via
  `logger.appendKeys()` from middleware. CloudWatch Logs Insights
  queries the JSON natively.
- [**Tracer**][powertools-tracer]: X-Ray subsegments per AWS SDK call.
  *Wrap every SDK v3 client* with `tracer.captureAWSv3Client(...)`.
  Without the wrap, X-Ray shows no DynamoDB/S3/SES subsegments. Easy
  to forget — your traces look empty when they shouldn't.
- [**Metrics**][powertools-metrics]: CloudWatch EMF, zero per-emission
  cost, flushed at handler return.

Wiring is one middleware chain repeated on every Lambda:

```ts
export const handler = withMiddleware(lambdaHttpAdapter(app))
  .use(captureLambdaHandler(tracer))
  .use(logMetrics(metrics))
  .use(injectLambdaContext(logger, { clearState: true }));
```

Correlation IDs propagate CloudFront → API Gateway → Lambda → DynamoDB
because X-Ray injects `X-Amzn-Trace-Id` at the edge and every
downstream SDK call (when wrapped) propagates it.

CloudWatch Logs default retention is **never expire**. Set
`logRetention: RetentionDays.ONE_MONTH` on every Lambda for dev,
`ONE_YEAR` for production. The default is a silent ongoing cost.

## 9. Security: least privilege via CDK grants

**Pattern**: let the IaC tool write the IAM policies.

CDK grants — `table.grantReadWriteData(lambda)`,
`bucket.grantRead(lambda)`, `eventApi.grantPublish(lambda)` — produce
minimal, resource-scoped policies you'd struggle to hand-write
correctly. Use them instead of writing JSON.

Other security defaults observed throughout:

- **OAC, not OAI** for S3 origins (Origin Access Identity is
  deprecated).
- **HTTPS-only viewer policy** on CloudFront behaviors.
- **`BlockPublicAccess: BLOCK_ALL`** on every S3 bucket; CloudFront
  reads via OAC, never via public ACL.
- **Encryption at rest** on S3, DynamoDB, OpenSearch by default.
- **TLS 1.2+** end-to-end.
- **Secrets in env vars are for non-secret config only.** Real secrets
  belong in Secrets Manager or SSM Parameter Store SecureString.
- **Permission scoping at the data layer**, not just middleware — see
  *Authorization via partition key* above.
- **Cognito hardening**: `preventUserExistenceErrors: true`,
  `enableTokenRevocation: true`, strong password policy, MFA optional
  with TOTP (no SMS), email-only account recovery.
- **Input validation everywhere** via a schema-validation library with explicit size
  caps; client input is never trusted.

## 10. Infra-as-code topology

```
            ┌─────────────────────┐         ┌─────────────────────┐
            │  TaskBoardAppStack  │◀────────│  TaskBoardWafStack  │
            │  (e.g. us-east-2)   │  WebACL │  (us-east-1, fixed) │
            │                     │   ARN   │                     │
            │  • DynamoDB ×9      │         │  • Web ACL          │
            │  • Lambda ×5        │         │  • Managed rules    │
            │  • S3 ×2            │         │  • Rate-based rule  │
            │  • CloudFront       │         └─────────────────────┘
            │  • HTTP API         │
            │  • Cognito          │
            │  • AppSync Events   │
            │  • EventBridge      │
            │  • SQS ×3 (+DLQs)   │
            │  • SES identity     │
            │  • OpenSearch       │
            └─────────────────────┘
```

Two stacks, one CDK app. `crossRegionReferences: true` handles the
ARN handoff via a custom-resource Lambda that reads SSM Parameters
between regions.

**Why two stacks**: CloudFront WAF WebACLs must be in `us-east-1`
(global service). The main stack can be in any supported region.
**Why one CDK app**: deploys in dependency order on a single command.
**Why CDK over other IaC options**: full programmability,
type-safe construct composition, stable L2 abstractions. The
[CDK best-practices guide][cdk-bp] is worth a read alongside.

**Local dev** uses a local AWS-emulation tool deployed via a
CDK-local wrapper. Same CDK code, `target=local`
context switches off the AWS-only pieces (AppSync Events Pro,
OpenSearch). Inner-loop time: the client dev server (hot reload)
plus a local CDK deploy on API changes.

## 11. Known gaps & honest trade-offs

This codebase is a reference for the *patterns*, not a production
template. The cuts:

| Gap | "Right" answer |
|---|---|
| Single AWS account | [AWS Organizations + Control Tower][aws-orgs]; separate dev/staging/prod accounts; SCPs at OU. |
| No custom domain | Route 53 ALIAS → CloudFront; ACM cert (us-east-1) for CloudFront + regional cert for HTTP API custom domain. |
| HTTP API endpoint publicly reachable (bypasses WAF) | CloudFront injects a secret origin header; Lambda rejects requests missing it. Or Lambda@Edge origin verification. |
| AppSync Events channel auth not enforced | A channel-namespace JS resolver checking `BoardMemberships` before allowing subscribe. |
| Access + refresh tokens in `localStorage` | Access in memory; refresh in `HttpOnly; Secure; SameSite=Strict` cookie set by a backend-for-frontend. |
| SES sandbox mode | Request production access; verify a domain with DKIM; SNS bounce/complaint handling. |
| No Content-Security-Policy | Add CSP to the CloudFront `ResponseHeadersPolicy`. Meaningful hardening against XSS-based token theft. |
| No CloudWatch alarms | Starter set: Lambda errors > 0, p99 > 3s, DynamoDB throttles > 0, API 5xx > 1%, SNS → a team chat channel via AWS Chatbot. |
| No Cognito Threat Protection | Enable in audit-only mode for 2 weeks, then full-function. Requires the Plus feature plan. |
| Single-AZ OpenSearch | Multi-AZ, 3 data nodes + 3 dedicated masters. Doubles cost. |
| `RemovalPolicy.DESTROY` on production tables | `RETAIN`. Catches "I meant to delete the stack but not the data." |
| No load test / Power Tuning | AWS Lambda Power Tuning to find the cost/latency knee per function. |

Each is genuinely fixable; the roadmap-shaped cost is roughly "a
quarter for a small team." None are blocking adoption of the patterns
this codebase demonstrates.

## 12. When to deviate from these defaults

| Situation | Reconsider |
|---|---|
| Sustained > 10K WCUs after eliminating hot keys | Single-table design; or shard hot partitions with a random suffix |
| "List my X" is more frequent than membership checks | Promote a GSI so the inverse direction is primary |
| Cross-region replication required | DynamoDB [Global Tables][ddb-global] (active-active); changes the consistency model |
| Read-after-write needed across an item collection | `ConsistentRead: true` on Query; 2× RCU cost |
| Bursty + predictable workload | Reserved capacity is cheaper than PAY_PER_REQUEST above ~50% sustained utilization |
| Items > 400 KB | Store the bulk in S3, keep a pointer in DDB |
| Periodic full-data scans | Maintain a second copy in S3 (Streams → Lambda → S3, or Kinesis Data Firehose). `Scan` doesn't scale. |
| Real "join" required | Denormalize at write time; or maintain a materialized view via Streams (same shape as `Activity` projection) |
| Per-route throttling needed | Move from lambdalith to per-route Lambdas, or add an L1 escape hatch on the HTTP API for route settings |
| User-facing latency p99 budget < 200 ms | Provisioned Concurrency on the API Lambda; or move the auth path off Lambda entirely (HTTP API JWT authorizer handles this for free) |

[cognito]: https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-identity-pools.html
[jwt-authorizer]: https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html
[waf-resources]: https://docs.aws.amazon.com/waf/latest/developerguide/how-aws-waf-works-resources.html
[http-vs-rest]: https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-vs-rest.html
[http-cors]: https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-cors.html
[wa-serverless]: https://docs.aws.amazon.com/wellarchitected/latest/serverless-applications-lens/welcome.html
[wa-serverless-rest]: https://docs.aws.amazon.com/wellarchitected/latest/serverless-applications-lens/restful-microservices.html
[appsync-events]: https://aws.amazon.com/blogs/mobile/announcing-aws-appsync-events-serverless-websocket-apis/
[powertools-logger]: https://docs.aws.amazon.com/powertools/typescript/latest/features/logger/
[powertools-tracer]: https://docs.aws.amazon.com/powertools/typescript/latest/features/tracer/
[powertools-metrics]: https://docs.aws.amazon.com/powertools/typescript/latest/features/metrics/
[powertools-idempotency]: https://docs.aws.amazon.com/powertools/typescript/latest/features/idempotency/
[ddb-global]: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/GlobalTables.html
[aws-orgs]: https://docs.aws.amazon.com/whitepapers/latest/organizing-your-aws-environment/organizing-your-aws-environment.html
[cdk-bp]: https://docs.aws.amazon.com/cdk/v2/guide/best-practices.html
