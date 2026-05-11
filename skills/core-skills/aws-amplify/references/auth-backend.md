# Auth — Backend

> **Prerequisites:** Backend defined in `amplify/backend.ts` with `defineBackend({ auth, data })`.

## Basic Auth Setup

Define authentication in `amplify/auth/resource.ts`:

```typescript
import { defineAuth } from '@aws-amplify/backend';

export const auth = defineAuth({
  loginWith: {
    email: true,
    // phone: true, // SMS-based login
  },
  userAttributes: {
    preferredUsername: { required: false },
  },
});
```

Import into `amplify/backend.ts`:

```typescript
import { defineBackend } from '@aws-amplify/backend';
import { auth } from './auth/resource';
defineBackend({ auth });
```

## MFA Configuration

```typescript
export const auth = defineAuth({
  loginWith: { email: true },
  multifactor: {
    mode: 'REQUIRED', // or 'OPTIONAL'
    totp: true,
    sms: true,
    email: true,
  },
});
```

Set `mode: 'REQUIRED'` to enforce MFA for all users. `'OPTIONAL'` lets
users enable it themselves.

> **Frontend impact:** When MFA is enabled, the Authenticator component handles all MFA steps automatically. For custom UI, see auth-web.md for signInStep handling.

## Passwordless Authentication

Passwordless login methods can coexist with traditional password-based auth.

**Email OTP:**

```typescript
export const auth = defineAuth({
  loginWith: {
    email: {
      otpLogin: true,
    },
  },
});
```

**SMS OTP:**

```typescript
export const auth = defineAuth({
  loginWith: {
    phone: {
      otpLogin: true,
    },
  },
});
```

**WebAuthn / Passkeys:**

```typescript
export const auth = defineAuth({
  loginWith: {
    webAuthn: true,
  },
});
```

These passwordless methods can be combined with each other and with
password-based login in the same `defineAuth` configuration.

## Social Login

Use `secret()` for OAuth client secrets — hardcoding credentials exposes
them in source control.

```typescript
import { defineAuth, secret } from '@aws-amplify/backend';

export const auth = defineAuth({
  loginWith: {
    email: true,
    externalProviders: {
      google: {
        clientId: secret('GOOGLE_CLIENT_ID'),
        clientSecret: secret('GOOGLE_CLIENT_SECRET'),
        scopes: ['email', 'profile', 'openid'],
        attributeMapping: {
          email: 'email', // values are strings, NOT objects
          fullname: 'name',
        },
      },
      facebook: { clientId: secret('FB_CLIENT_ID'), clientSecret: secret('FB_CLIENT_SECRET') },
      signInWithApple: {
        clientId: secret('APPLE_CLIENT_ID'),
        teamId: secret('APPLE_TEAM_ID'),
        keyId: secret('APPLE_KEY_ID'),
        privateKey: secret('APPLE_PRIVATE_KEY'),
      },
      loginWithAmazon: { clientId: secret('AMAZON_CLIENT_ID'), clientSecret: secret('AMAZON_CLIENT_SECRET') },
      callbackUrls: ['http://localhost:3000/', 'https://myapp.com/'],
      logoutUrls: ['http://localhost:3000/', 'https://myapp.com/'],
    },
  },
});
```

Set secrets via CLI: `echo -n "<value>" | npx ampx sandbox secret set MY_OAUTH_CLIENT_ID`. (The documented approach uses an interactive prompt; piping with `echo -n` is a practical alternative for scripts.)
For provider-specific OAuth setup guides, consult AWS
documentation via available tools; when unavailable, use web
search or AWS CLI.

## SAML / OIDC (Enterprise)

OIDC providers are configured inside `loginWith.externalProviders`:

```typescript
import { defineAuth, secret } from '@aws-amplify/backend';

export const auth = defineAuth({
  loginWith: {
    email: true,
    externalProviders: {
      oidc: [{
        name: 'MyOIDC',
        clientId: secret('OIDC_CLIENT_ID'),
        clientSecret: secret('OIDC_CLIENT_SECRET'),
        issuerUrl: 'https://idp.example.com',
        attributeMapping: { email: 'email' },
      }],
      callbackUrls: ['http://localhost:3000/'],
      logoutUrls: ['http://localhost:3000/'],
    },
  },
});
```

**SAML** is NOT supported in `defineAuth` — the `ExternalProviderSpecificFactoryProps` type has no `saml` property. The lower-level `auth-construct` package supports SAML, but it was never wired up to the high-level API. Use CDK escape hatches via `backend.auth.resources` to configure SAML providers:

```typescript
// In backend.ts — SAML requires CDK-level configuration
const { cfnUserPool } = backend.auth.resources.cfnResources;
// Configure SAML identity provider via CfnUserPoolIdentityProvider
```

Consult AWS documentation for `CfnUserPoolIdentityProvider` SAML configuration properties.

## Cognito Triggers

```typescript
import { defineAuth } from '@aws-amplify/backend';
import { preSignUp } from './pre-sign-up/resource';
import { postConfirmation } from './post-confirmation/resource';

export const auth = defineAuth({
  loginWith: { email: true },
  triggers: {
    preSignUp,
    postConfirmation,
    // Also: preAuthentication, postAuthentication,
    // createAuthChallenge, defineAuthChallenge, verifyAuthChallengeResponse,
    // preTokenGeneration, customMessage, userMigration
  },
});
```

Define each trigger with `defineFunction`:

```typescript
// amplify/auth/pre-sign-up/resource.ts
import { defineFunction } from '@aws-amplify/backend';
export const preSignUp = defineFunction({ name: 'pre-sign-up' });
```

> **Tip:** Auth trigger handlers need `@types/aws-lambda` for TypeScript types.

### Trigger Lambda + Data Table Access

If a trigger Lambda (e.g., `postConfirmation`) needs to write to a `defineData` table, this can create a circular dependency. Workarounds:

1. **Access via `backend.auth.resources`** (avoids cycle when trigger is in auth stack):

```typescript
// backend.ts
const postConfirmFn = backend.auth.resources.userPool.triggers?.postConfirmation;
const table = backend.data.resources.tables['UserProfile'];
table.grantWriteData(postConfirmFn);
postConfirmFn.addEnvironment('TABLE_NAME', table.tableName);
```

1. **Separate DynamoDB table** — create via CDK (not `defineData`) to avoid stack coupling.

## Guest (Unauthenticated) Access

Guest access is **enabled by default** in Amplify Gen2 — the Cognito Identity Pool is created with `allowUnauthenticatedIdentities: true` automatically.

To use guest access in your data models, set `defaultAuthorizationMode` to `'iam'` and add `allow.guest()` authorization rules:

```typescript
const schema = a.schema({
  Todo: a.model({
    content: a.string(),
  }).authorization(allow => [
    allow.guest().to(['read']),   // unauthenticated users can read
    allow.owner(),                // owners can CRUD
  ]),
});

export const data = defineData({
  schema,
  authorizationModes: {
    defaultAuthorizationMode: 'iam',   // required for guest access
    apiKeyAuthorizationMode: { expiresInDays: 7 }, // optional alternative
  },
});
```

> **Security:** Guest access grants unauthenticated users IAM-authorized access. For production, explicitly evaluate whether guest access is needed and prefer `allow.authenticated()` as the default. If guest access is required, scope it to read-only on non-sensitive models only.

To **disable** guest access, use a CDK override in `backend.ts`:

```typescript
const { cfnIdentityPool } = backend.auth.resources.cfnResources;
cfnIdentityPool.allowUnauthenticatedIdentities = false;
```

## Pitfalls

- **Trigger not registered (silent no-op):** Defining a trigger function
  with `defineFunction` but NOT adding it to `triggers: {}` in `defineAuth`
  causes a **silent no-op** — the function deploys but never fires.
  Both define AND register: `triggers: { preSignUp, postConfirmation }`.
- **Hardcoded secrets:** Using string literals instead of `secret()` for
  OAuth credentials exposes them in source control.
- **Missing scopes:** Social providers default to minimal scopes — add
  `'email'`, `'profile'` explicitly or user attributes won't populate.
- **Google attribute mapping:** The Google claim `name` maps to Cognito
  `fullname` (NOT `name`). The `attributeMapping` values are plain strings,
  NOT objects: `{ email: 'email', fullname: 'name' }`.
- **MFA method mismatch:** Enabling `sms: true` in MFA requires a phone
  number attribute on the user pool — add `phone_number` to user attributes.
  Similarly, `email: true` in MFA requires an email attribute on the user pool.
- **Secrets in CI/CD:** For branch environments, manage secrets through the
  **Amplify console** (App settings → Environment variables → Secrets).
  The `ampx sandbox secret` command only works for local sandbox environments.

## Links

- [Auth Overview](https://docs.amplify.aws/react/build-a-backend/auth/)
- [Set Up Auth](https://docs.amplify.aws/react/build-a-backend/auth/set-up-auth/)
- [External Identity Providers](https://docs.amplify.aws/react/build-a-backend/auth/concepts/external-identity-providers/)
- [Multi-Factor Authentication](https://docs.amplify.aws/react/build-a-backend/auth/concepts/multi-factor-authentication/)
- [Passwordless Authentication](https://docs.amplify.aws/react/build-a-backend/auth/concepts/passwordless/)
- [User Attributes](https://docs.amplify.aws/react/build-a-backend/auth/concepts/user-attributes/)
- [Grant Access to Auth Resources](https://docs.amplify.aws/react/build-a-backend/auth/grant-access-to-auth-resources/)
