# Data — Backend

> **Prerequisites:** Backend defined in `amplify/backend.ts` with `defineBackend({ auth, data })`.

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

Export `Schema` as `ClientSchema<typeof schema>` — without this export,
frontend clients lose all type inference.
**Field types:** `a.string()`, `a.integer()`, `a.float()`, `a.boolean()`,
`a.date()`, `a.datetime()`, `a.timestamp()`, `a.time()`, `a.email()`,
`a.url()`, `a.phone()`, `a.ipAddress()`, `a.json()`, `a.id()`,
`a.enum([...])`. Chain `.required()` or `.array()` on any field;
`.default(value)` on scalar fields only (not enums — see Pitfalls).

> **`a.phone()`:** Only accepts E.164 format (`+15551234567`). Hyphens (`+1-555-0101`) and short formats are rejected.

### Date/Time Field Formats

| Field Type | Storage Format | Example |
|-----------|---------------|---------|
| `a.date()` | ISO date string | `2024-01-15` |
| `a.time()` | ISO time string | `14:30:00.000Z` |
| `a.datetime()` | ISO datetime | `2024-01-15T14:30:00.000Z` |
| `a.timestamp()` | Epoch **seconds** (not ms!) | `1705325400` |

> **Pitfall:** `a.timestamp()` is seconds, not milliseconds. Use `Math.floor(Date.now() / 1000)` when setting values from JavaScript.

### Custom Identifiers

`.identifier(['sku'])` replaces the auto-generated `id` field entirely:

```typescript
Product: a.model({
  sku: a.string().required(),
  name: a.string(),
}).identifier(['sku'])
```

- All queries must use the custom identifier (`{ sku: 'ABC123' }`)
- Duplicate values cause DynamoDB conditional check error
- The `id` field no longer exists on this model

## Authorization Rules

Six strategies, applied per-model or per-field:

**WARNING:** In data authorization rules, `allow.guest()` is a **method
call** (with parentheses). In storage access rules, `allow.guest` is a
**property** (no parentheses). Mixing these up causes TypeScript errors.

```typescript
a.model({ /* fields */ }).authorization(allow => [
  allow.publicApiKey().to(['read']), // API key: public read
  allow.guest().to(['read']), // Requires defaultAuthorizationMode: 'iam'
  allow.owner(), // Creator has full CRUD
  allow.authenticated().to(['read']), // Any signed-in user can read
  allow.group('Admins'), // Named Cognito group
  allow.custom(), // Lambda authorizer
])
```

> **Security note:** `allow.guest()` and `allow.publicApiKey()` both permit unauthenticated access. Only use for intentionally public, non-sensitive data. Prefer `allow.authenticated()` or `allow.owner()` for sensitive resources. See [Amplify authorization best practices](https://docs.amplify.aws/react/build-a-backend/data/customize-authz/) and [Amazon Cognito Identity Pool security](https://docs.aws.amazon.com/cognito/latest/developerguide/identity-pools.html) for guidance on choosing the right authorization strategy.

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

### Authorization Rule Combining

When multiple rules are applied, the **most permissive wins**. You cannot use `deny` rules — if `allow.authenticated()` grants full CRUD, you cannot selectively deny `delete` for non-owners. Structure rules from most restrictive:

```typescript
.authorization(allow => [
  allow.owner(),           // Owner: full CRUD
  allow.authenticated().to(['read', 'create']),  // Others: read + create only
])
```

> **Pitfall:** `groupsDefinedIn('fieldName')` automatically creates an implicit field on the model. Do NOT also declare that field explicitly — this causes: `"Implicit field conflicts with explicit field definition."`
>
> **Type system gap:** The implicit field from `groupsDefinedIn('fieldName')` is NOT exposed in generated TypeScript client types. To set the field programmatically, use an untyped approach:
>
> ```typescript
> await client.graphql({
>   query: mutations.updateProject,
>   variables: { id: projectId, teamGroups: ['Admins', 'Editors'] },
> });
> ```

| Pattern | Use Case | Field Type | Who Gets Access |
|---------|----------|------------|-----------------|
| `allow.ownersDefinedIn('editors')` | Multiple named users own the resource | `a.string().array()` — declare explicitly | Specific users listed in the array |
| `allow.groupsDefinedIn('teamGroups')` | Access by Cognito group membership | Implicit — do NOT declare | Any user in the named Cognito group |

## Relationships

Three types — reference field types must match the related model's
identifier type.

> **Foreign key fields must use `a.id()`**, not `a.string()`. Using `a.string()` causes silent relationship resolution failures.

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
field name. That field must be declared explicitly on the child model.

Declare **both sides** of every relationship — the parent model
needs `a.hasMany('Child', 'fkField')` AND the child model needs
`a.belongsTo('Parent', 'fkField')`. Omitting either side causes silent
query failures (e.g., lazy-loading the relation returns `undefined`).

### Deletion Behavior — No Referential Integrity

Deleting a parent record does NOT cascade to children and does NOT fail. Child records become orphaned silently — manually delete children first or implement a soft-delete pattern.

```typescript
// Delete children before parent
const books = await client.models.Book.list({ filter: { authorId: { eq: authorId } } });
await Promise.all(books.data.map(b => client.models.Book.delete({ id: b.id })));
await client.models.Author.delete({ id: authorId });
```

### Self-Referential Models (Tree Structures)

```typescript
Category: a.model({
  name: a.string().required(),
  parentId: a.id(),
  parent: a.belongsTo('Category', 'parentId'),
  children: a.hasMany('Category', 'parentId'),
})
```

> Requires explicit FK field (`parentId: a.id()`). Works for trees, org charts, threaded comments.

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
>
> **`.required()` on enums:** `a.enum(['A','B']).required()` does NOT work — `.required()` doesn't exist on EnumType. Define the enum separately and use `a.ref()`:
>
> ```typescript
> const Priority = a.enum(['low', 'medium', 'high']);
> const schema = a.schema({
>   Todo: a.model({
>     priority: a.ref('Priority').required(), // ✅ Works
>     // priority: Priority.required(),       // ❌ Fails
>   })
> });
> ```

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

The handler function name must match a `defineFunction` name imported
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

The `defaultAuthorizationMode` must match at least one strategy used in
your model `authorization()` rules (e.g., `userPool` ↔ `owner()` /
`authenticated()` / `group()`; `apiKey` ↔ `publicApiKey()`; `iam` ↔ `guest()`).

Guest access is enabled by default in Amplify Gen2 — see [auth-backend.md](auth-backend.md) for details and how to disable it.

> Guest access configuration: see [auth-backend.md](auth-backend.md) § Guest Access.

## Pitfalls

- **Missing `ClientSchema` export:** Without `export type Schema =
  ClientSchema<typeof schema>`, frontend `generateClient<Schema>()` has no
  type information and all operations are untyped.
- **Auth mode conflict:** Using `allow.publicApiKey()` in model rules but
  setting `defaultAuthorizationMode: 'userPool'` without adding
  `apiKeyAuthorizationMode` causes API key requests to be rejected.
- **Per-field auth + `.required()`:** Fields with owner-only authorization (`allow.owner()`) cannot be `.required()` — other users can't provide a value on create. Make private fields optional.

## Links

- [Data Overview](https://docs.amplify.aws/react/build-a-backend/data/)
- [Set Up Data](https://docs.amplify.aws/react/build-a-backend/data/set-up-data/)
- [Data Modeling](https://docs.amplify.aws/react/build-a-backend/data/data-modeling/)
- [Data Modeling — Relationships](https://docs.amplify.aws/react/build-a-backend/data/data-modeling/relationships/)
- [Data Modeling — Add Fields](https://docs.amplify.aws/react/build-a-backend/data/data-modeling/add-fields/)
- [Customize Authorization](https://docs.amplify.aws/react/build-a-backend/data/customize-authz/)
- [Connect to Existing Data Sources](https://docs.amplify.aws/react/build-a-backend/data/connect-to-existing-data-sources/)
