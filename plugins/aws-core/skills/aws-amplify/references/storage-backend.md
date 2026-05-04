# Storage — Backend

## Basic Setup

Define storage in `amplify/storage/resource.ts`:

```typescript
import { defineStorage } from '@aws-amplify/backend';

export const storage = defineStorage({
  name: 'myFiles',
  access: (allow) => ({
    'public/*': [
      allow.guest.to(['read']),
      allow.authenticated.to(['read', 'write', 'delete']),
    ],
    'protected/{entity_id}/*': [
      allow.authenticated.to(['read']),
      allow.entity('identity').to(['read', 'write', 'delete']),
    ],
    'private/{entity_id}/*': [
      allow.entity('identity').to(['read', 'write', 'delete']),
    ],
  }),
});
```

Import into `amplify/backend.ts`:

```typescript
import { defineBackend } from '@aws-amplify/backend';
import { auth } from './auth/resource';
import { storage } from './storage/resource';
defineBackend({ auth, storage });
```

## Access Rules

Path patterns control who can access files. The `{entity_id}` placeholder
resolves to the authenticated user's identity ID at runtime — each user
gets an isolated directory.

Actions: `'read'`, `'write'`, `'delete'` (granular: `'get'` and `'list'`
instead of `'read'`). Subjects: `allow.guest.to([...])`,
`allow.authenticated.to([...])`, `allow.groups(['Admins']).to([...])`,
`allow.entity('identity').to([...])`. Every rule **MUST** end with `.to()`
specifying the permitted actions — omitting `.to()` means NO permissions
are granted.

**WARNING:** Storage access rules use `allow.guest` (PROPERTY, no
parentheses) and `allow.authenticated` (PROPERTY). Data authorization
rules use `allow.guest()` (METHOD, with parentheses). Mixing these up
causes TypeScript errors.

**WARNING:** `{entity_id}` **MUST** be paired with
`allow.entity('identity')`. Using `{entity_id}` in a path without
`allow.entity('identity')` in that path's rules has no effect.

Paths **MUST** end with `/*` to match all objects under that prefix.
Paths **MUST NOT** start with `/`.

## Multiple Buckets

```typescript
export const primaryStorage = defineStorage({ name: 'primaryFiles', isDefault: true, access: (allow) => ({ /* rules */ }) });
export const secondaryStorage = defineStorage({ name: 'secondaryFiles', access: (allow) => ({ /* rules */ }) });
```

You **MUST** set `isDefault: true` on exactly one bucket when defining
multiple. Each bucket **MUST** have a unique `name` property. The `name`
is what clients reference when targeting a non-default bucket.

## Event Triggers

```typescript
import { defineFunction, defineStorage } from '@aws-amplify/backend';

const onUploadHandler = defineFunction({ entry: './on-upload-handler.ts' });

export const storage = defineStorage({
  name: 'myFiles',
  triggers: { onUpload: onUploadHandler, onDelete: onUploadHandler },
  access: (allow) => ({ 'public/*': [allow.authenticated.to(['read', 'write'])] }),
});
```

The trigger handler receives an `S3Handler` event with bucket name and
object key. You **MUST** import the trigger function into `backend.ts`.

Typed handler example:

```ts
import type { S3Handler } from 'aws-lambda';

export const handler: S3Handler = async (event) => {
  const objectKeys = event.Records.map((record) => record.s3.object.key);
  console.log(`Upload handler invoked for objects [${objectKeys.join(', ')}]`);
};
```

## Pitfalls

- **Paths without `/*`:** A path like `'public'` matches nothing — you
  **MUST** use `'public/*'` to match files under that prefix.
- **Missing `.to([])`:** Omitting `.to(['read', 'write'])` from an access
  rule grants NO permissions — the rule is silently ignored.
- **Missing `{entity_id}`:** Using `'private/*'` instead of
  `'private/{entity_id}/*'` exposes every user's private files to all
  authenticated users.
- **Leading slash:** Paths **MUST NOT** start with `/` — use `'public/*'`,
  not `'/public/*'`.
- **Forgetting `isDefault`:** With multiple buckets and no `isDefault: true`,
  client operations fail because no default bucket is resolved.
- **`grantReadWrite()` path argument:** Do NOT pass a path argument to
  `grantReadWrite(lambda)` — it operates on the whole bucket. There is no
  per-path grant API.

## Links

- [Storage Overview](https://docs.amplify.aws/react/build-a-backend/storage/)
- [Set Up Storage](https://docs.amplify.aws/react/build-a-backend/storage/set-up-storage/)
- [Storage Authorization](https://docs.amplify.aws/react/build-a-backend/storage/authorization/)
- [Storage Event Triggers](https://docs.amplify.aws/react/build-a-backend/storage/lambda-triggers/)
