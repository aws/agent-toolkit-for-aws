# Data — Web

> **Backend required:** Data must be defined in `amplify/data/resource.ts`
> using `defineData` — see [data-backend.md](data-backend.md).

## Client Setup

**`generateClient<Schema>()` MUST be called at module scope** (outside
any React component). Calling it inside a component creates a new client
per render, breaking subscriptions and caching.

```typescript
import { generateClient } from 'aws-amplify/data';
import type { Schema } from '../amplify/data/resource';

// Module scope — called once
const client = generateClient<Schema>();
```

The `<Schema>` generic gives full type inference on all model operations.

## CRUD Operations

All operations return `{ data, errors }`. You **SHOULD** check `errors` before using `data`.

```typescript
const { data, errors } = await client.models.Todo.create({ content: 'Ship feature', priority: 'high' });
```

Same shape for `.list()`, `.get({ id })`, `.update({ id, done: true })`, `.delete({ id })`.
`.list()` accepts an optional `filter`: `{ filter: { done: { eq: false } } }`.

### Error Handling

You **SHOULD** handle both GraphQL-level errors and network failures:

```tsx
try {
  const { data, errors } = await client.models.Todo.create({ content: 'New todo' });
  if (errors) { /* handle GraphQL field/validation errors */ }
} catch (err) {
  /* handle network or unexpected errors */
}
```

## Real-Time

- **`observeQuery()`** — auto-updating list, returns `{ items }` snapshots. Recommended default.
- **`onCreate()` / `onUpdate()` / `onDelete()`** — per-event subscriptions.

Both return an observable; call `.subscribe({ next })` and **MUST** call `sub.unsubscribe()` in cleanup.

```tsx
useEffect(() => {
  const sub = client.models.Todo.observeQuery().subscribe({
    next: ({ items }) => setTodos(items),
  });
  return () => sub.unsubscribe();
}, []);
```

## Server-Side (Next.js)

```typescript
import { generateServerClientUsingCookies } from '@aws-amplify/adapter-nextjs/data';
import { cookies } from 'next/headers';
import outputs from '@/amplify_outputs.json';
import type { Schema } from '@/amplify/data/resource';

const cookieClient = generateServerClientUsingCookies<Schema>({ config: outputs, cookies });
```

Use `cookieClient.models.*` the same as the browser client. Works in Server Components, Server Actions, and App Router API routes.

## React Native

Identical to the web client — uses `generateClient<Schema>()` from `aws-amplify/data`.
All CRUD, `observeQuery()`, and subscription APIs (`onCreate`, `onUpdate`, `onDelete`) are the same.

## Pitfalls

- **Subscription memory leaks:** `useEffect` **MUST** return
  `() => sub.unsubscribe()` as a cleanup function. Without it,
  subscriptions accumulate across re-renders, causing memory leaks and
  duplicate data updates.
- **Wrong auth mode for subscriptions:** Subscriptions require a
  WebSocket-compatible auth mode (`userPool` or `iam`). API key auth on
  subscriptions fails silently.
- **Missing `<Schema>` generic:** `generateClient()` without `<Schema>`
  returns an untyped client — all operations lose autocomplete and type checking.
- **Server client without cookies:** Using `generateClient()` in Next.js
  server components fails (no browser session) — you **MUST** use
  `generateServerClientUsingCookies`.

## Links

- [Data Overview (React)](https://docs.amplify.aws/react/build-a-backend/data/)
- [Set Up Data (React)](https://docs.amplify.aws/react/build-a-backend/data/set-up-data/)
- [Connect to API (React)](https://docs.amplify.aws/react/frontend/data/connect-to-API/)
- [Data Client (React)](https://docs.amplify.aws/react/frontend/data/)
- [Data Overview (Next.js)](https://docs.amplify.aws/nextjs/build-a-backend/data/)
- [Set Up Data (Next.js)](https://docs.amplify.aws/nextjs/build-a-backend/data/set-up-data/)
- [Data Client (Next.js)](https://docs.amplify.aws/nextjs/frontend/data/)
- [Data Overview (React Native)](https://docs.amplify.aws/react-native/build-a-backend/data/)
- [Set Up Data (React Native)](https://docs.amplify.aws/react-native/build-a-backend/data/set-up-data/)
- [Data Client (React Native)](https://docs.amplify.aws/react-native/frontend/data/)
