# Data — Web

> **Prerequisites:** Project initialized, `amplify_outputs.json` exists (from `npx ampx sandbox`), and `Amplify.configure(outputs)` called in app entry point.
>
> **Backend required:** Data must be defined in `amplify/data/resource.ts`
> using `defineData` — see [data-backend.md](data-backend.md).

## Client Setup

> Call `generateClient<Schema>()` at module scope (outside any component). Calling it inside a component creates a new client on every render, breaking subscriptions, caching, and causing memory leaks.

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

Both return an observable; call `.subscribe({ next })` and call `sub.unsubscribe()` in cleanup.

```tsx
useEffect(() => {
  const sub = client.models.Todo.observeQuery().subscribe({
    next: ({ items }) => setTodos(items),
  });
  return () => sub.unsubscribe();
}, []);
```

### Filtering Subscriptions

```tsx
useEffect(() => {
  const sub = client.models.Vote.observeQuery({
    filter: { pollId: { eq: currentPollId } },
  }).subscribe({
    next: ({ items }) => setVotes(items),
  });
  return () => sub.unsubscribe();
}, [currentPollId]);
```

### When to Use Which

| Pattern | Best For |
|---------|----------|
| `observeQuery()` | Continuously updated lists — handles pagination, filtering, deduplication. **Use by default.** |
| `onCreate` / `onUpdate` / `onDelete` | Fine-grained control — animations, toasts, or single event type only. |

> `observeQuery` does NOT support server-side sorting. Sort results client-side after receiving them.

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

## Querying a Secondary Index

```typescript
// Backend: define with queryField name
.secondaryIndexes(index => [
  index('pollId').sortKeys(['voterId']).queryField('votesByPollAndVoter')
])

// Frontend: call by name
const { data } = await client.models.Vote.votesByPollAndVoter({
  pollId: currentPollId,
  voterId: { eq: currentVoterId },
});
```

### JSON Fields — Serialization Asymmetry

`a.json()` fields require `JSON.stringify()` on write but auto-parse on read:

```typescript
// Write: stringify before saving
await client.models.Config.create({
  metadata: JSON.stringify({ key: "val", nested: { a: 1 } })
});

// Read: auto-parsed back to object
const { data } = await client.models.Config.get({ id });
console.log(data.metadata.key); // "val" — already an object
```

> Passing a raw object on write fails silently with: `"Variable 'metadata' has an invalid value"`
>
> (The `a.json()` field maps to GraphQL's `AWSJSON` scalar, which expects a JSON-encoded string as input.)

## Pitfalls

- **Array field updates = full replacement:** Array fields have no append/remove operations. You must read, modify, and write the entire array:

  ```typescript
  const item = await client.models.Todo.get({ id });
  const updated = [...(item.data?.tags ?? []), 'newTag'];
  await client.models.Todo.update({ id, tags: updated });
  ```

  **Risk:** Concurrent updates can overwrite each other. For frequently-modified lists, consider a separate model with a relationship instead.

- **Subscription memory leaks:** `useEffect` must return
  `() => sub.unsubscribe()` as a cleanup function. Without it,
  subscriptions accumulate across re-renders, causing memory leaks and
  duplicate data updates.
- **Wrong auth mode for subscriptions:** Subscriptions require a
  WebSocket-compatible auth mode (`userPool` or `iam`). API key auth on
  subscriptions fails silently.
- **Missing `<Schema>` generic:** `generateClient()` without `<Schema>`
  returns an untyped client — all operations lose autocomplete and type checking.
- **Server client without cookies:** Using `generateClient()` in Next.js
  server components fails (no browser session) — use
  `generateServerClientUsingCookies` instead.

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
