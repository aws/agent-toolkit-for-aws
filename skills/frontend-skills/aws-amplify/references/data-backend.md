# Data — Backend

## Schema Definition

Define your data models in `amplify/data/resource.ts`:

```typescript
import { type ClientSchema, a, defineData } from '@aws-amplify/backend';

const schema = a.schema({
  Todo: a.model({
    content: a.string().required(),
    priority: a.enum(['low', 'medium', 'high']),
    done: a.boolean().default(false),
    dueDate: a.date(),
    owner: a.string(),
  }).authorization(allow => [allow.owner()]),
});

export type Schema = ClientSchema<typeof schema>;
export const data = defineData({
  schema,
  authorizationModes: {
    defaultAuthorizationMode: 'userPool',
  },
});
```

Import into `amplify/backend.ts`:

```typescript
import { defineBackend } from '@aws-amplify/backend';
import { auth } from './auth/resource';
import { data } from './data/resource';
defineBackend({ auth, data });
```

You **MUST** export `Schema` as `ClientSchema<typeof schema>` — without
this export, frontend clients lose all type inference.
**Field types:** `a.string()`, `a.integer()`, `a.float()`, `a.boolean()`,
`a.date()`, `a.datetime()`, `a.timestamp()`, `a.time()`, `a.email()`,
`a.url()`, `a.phone()`, `a.ipAddress()`, `a.json()`, `a.id()`,
`a.enum([...])`. Chain `.required()` or `.array()` on any field;
`.default(value)` on scalar fields only (not enums — see Pitfalls).

## Authorization Rules

Six strategies, applied per-model or per-field:

**WARNING:** In data authorization rules, `allow.guest()` is a **method
call** (with parentheses). In storage access rules, `allow.guest` is a
**property** (no parentheses). Mixing these up causes TypeScript errors.

```typescript
a.model({ /* fields */ }).authorization(allow => [
  allow.publicApiKey().to(['read']), // API key: public read
  allow.guest().to(['read']), // Requires defaultAuthorizationMode: 'iam' — NOTE: method call ()
  allow.owner(), // Creator has full CRUD
  allow.authenticated().to(['read']), // Any signed-in user can read
  allow.group('Admins'), // Named Cognito group
  allow.custom(), // Lambda authorizer
])
```

Per-field authorization overrides model-level rules:

```typescript
Post: a.model({
  title: a.string(),
  secret: a.string().authorization(allow => [allow.owner()]),
}).authorization(allow => [allow.authenticated().to(['read'])])
```

**Multi-owner:** Use `allow.ownersDefinedIn('editors')` with an
`editors: a.string().array()` field to grant multiple users ownership.
**Dynamic groups:** Use `allow.groupsDefinedIn('teamGroups')` with a
string field to control access via group names stored on each record.

## Relationships

Three types — reference field types **MUST** match the related model's
identifier type.

```typescript
const schema = a.schema({
  Team: a.model({
    name: a.string().required(),
    members: a.hasMany('Member', 'teamId'),
  }).authorization(allow => [allow.owner()]),

  Member: a.model({
    name: a.string().required(),
    teamId: a.id().required(),
    team: a.belongsTo('Team', 'teamId'),
    profile: a.hasOne('Profile', 'memberId'),
  }).authorization(allow => [allow.owner()]),

  Profile: a.model({
    bio: a.string(),
    memberId: a.id().required(),
    member: a.belongsTo('Member', 'memberId'),
  }).authorization(allow => [allow.owner()]),
});
```

The second argument to `hasMany`/`belongsTo`/`hasOne` is the foreign key
field name. That field **MUST** be declared explicitly on the child model.

You **MUST** declare **both sides** of every relationship — the parent model
needs `a.hasMany('Child', 'fkField')` AND the child model needs
`a.belongsTo('Parent', 'fkField')`. Omitting either side causes silent
query failures (e.g., lazy-loading the relation returns `undefined`).

The foreign-key field **MUST** use `a.id()` — NOT `a.string()` — to match
the related model's identifier type. Using `a.string()` causes runtime
relationship resolution failures.

```typescript
// CORRECT — both sides declared, FK uses a.id()
Team: a.model({
  name: a.string().required(),
  members: a.hasMany('Member', 'teamId'), // parent side
})

Member: a.model({
  name: a.string().required(),
  teamId: a.id().required(), // FK: a.id(), NOT a.string()
  team: a.belongsTo('Team', 'teamId'), // child side — REQUIRED
})
```

## Secondary Indexes

```typescript
Todo: a.model({
  content: a.string(),
  status: a.string(),
  createdAt: a.datetime(),
}).secondaryIndexes(index => [
  index('status').sortKeys(['createdAt']).queryField('listByStatus'),
])
```

Indexes enable `client.models.Todo.listByStatus({ status: 'active' })`.
Composite sort keys allow multi-field sorting within a partition. You
**SHOULD** name the `queryField` descriptively — it becomes the typed
client method name.

## Enum Types

Define enums with `a.enum()` at the top level of `a.schema()`, then reference them in model fields with `a.ref()`:

```typescript
const schema = a.schema({
  Priority: a.enum(['low', 'medium', 'high']),

  Task: a.model({
    title: a.string().required(),
    priority: a.ref('Priority'),
  }).authorization(allow => [allow.owner()]),
});
```

You can also use `a.enum()` inline on a model field:

```typescript
Todo: a.model({
  content: a.string().required(),
  priority: a.enum(['low', 'medium', 'high']),
})
```

> ⚠️ **Pitfall:** `.default()` does not work on `a.enum()` fields — default values are only supported on scalar types (`a.string()`, `a.integer()`, etc.). Applying `.default()` to an enum field silently fails at deployment.

## Custom Types

Custom types group related fields into a reusable structure:

```typescript
const schema = a.schema({
  Location: a.customType({ lat: a.float(), lng: a.float() }),

  Task: a.model({
    title: a.string().required(),
    location: a.ref('Location'),
  }).authorization(allow => [allow.owner()]),
});
```

Use `a.ref('TypeName')` to reference custom types or enums in model fields.

## Custom Queries and Mutations

Expose Lambda-backed operations through the schema:

```typescript
const schema = a.schema({
  // ... models ...
  echo: a.query()
    .arguments({ message: a.string().required() })
    .returns(a.string())
    .handler(a.handler.function('echoHandler'))
    .authorization(allow => [allow.authenticated()]),

  placeOrder: a.mutation()
    .arguments({ productId: a.id().required(), qty: a.integer() })
    .returns(a.json())
    .handler(a.handler.function('orderHandler'))
    .authorization(allow => [allow.authenticated()]),
});
```

The handler function name **MUST** match a `defineFunction` name imported
into `backend.ts`.

## Authorization Modes

Configure default and additional auth modes in `defineData`:

**Starter template default** (public access):

```typescript
export const data = defineData({
  schema,
  authorizationModes: {
    defaultAuthorizationMode: 'apiKey',
    apiKeyAuthorizationMode: { expiresInDays: 30 },
  },
});
```

**With auth** (user-scoped access):

```typescript
export const data = defineData({
  schema,
  authorizationModes: {
    defaultAuthorizationMode: 'userPool',
    apiKeyAuthorizationMode: { expiresInDays: 30 },
    // lambdaAuthorizationMode: { function: myAuthFn },
  },
});
```

The `defaultAuthorizationMode` **MUST** match at least one strategy used in
your model `authorization()` rules (e.g., `userPool` ↔ `owner()` /
`authenticated()` / `group()`; `apiKey` ↔ `publicApiKey()`; `iam` ↔ `guest()`).

Guest access is enabled by default in Amplify Gen2 — see [auth-backend.md](auth-backend.md) for details and how to disable it.

**Guest access configuration** (with `allow.guest()`):

```typescript
// amplify/data/resource.ts — set IAM as default auth mode for guest access
export const data = defineData({
  schema,
  authorizationModes: {
    defaultAuthorizationMode: 'iam',
  },
});
```

## Pitfalls

- **Missing `ClientSchema` export:** Without `export type Schema =
  ClientSchema<typeof schema>`, frontend `generateClient<Schema>()` has no
  type information and all operations are untyped.
- **FK field type `a.string()` instead of `a.id()`:** Using `a.string()`
  for foreign key fields causes relationship resolution to fail silently —
  queries return `null` for related models. Always use `a.id()` for FK fields.
- **Missing relationship side:** Omitting `belongsTo` on the child model
  (or `hasMany` on the parent) causes lazy-loading the relation to return
  `undefined` with no error.
- **Guest access auth mode:** `allow.guest()` requires
  `defaultAuthorizationMode: 'iam'` in `defineData`. Guest access
  (unauthenticated identities) is enabled by default in Amplify Gen2.
- **Auth mode conflict:** Using `allow.publicApiKey()` in model rules but
  setting `defaultAuthorizationMode: 'userPool'` without adding
  `apiKeyAuthorizationMode` causes API key requests to be rejected.
- **Forgetting `defineBackend`:** Defining `data` without importing it
  into `backend.ts` means the schema is never deployed.
- **`.default()` on enum fields:** `.default()` does not work on
  `a.enum()` fields — default values are only supported on scalar types
  (`a.string()`, `a.integer()`, `a.float()`, `a.boolean()`, etc.).
  Applying `.default()` to an enum field silently fails at deployment.

## Links

- [Data Overview](https://docs.amplify.aws/react/build-a-backend/data/)
- [Set Up Data](https://docs.amplify.aws/react/build-a-backend/data/set-up-data/)
- [Data Modeling](https://docs.amplify.aws/react/build-a-backend/data/data-modeling/)
- [Data Modeling — Relationships](https://docs.amplify.aws/react/build-a-backend/data/data-modeling/relationships/)
- [Data Modeling — Add Fields](https://docs.amplify.aws/react/build-a-backend/data/data-modeling/add-fields/)
- [Customize Authorization](https://docs.amplify.aws/react/build-a-backend/data/customize-authz/)
- [Connect to Existing Data Sources](https://docs.amplify.aws/react/build-a-backend/data/connect-to-existing-data-sources/)
