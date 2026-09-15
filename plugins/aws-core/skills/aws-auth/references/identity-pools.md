# Identity Pools (Federated Identities)

## Overview

An identity pool exchanges a proof of authentication (a user pool token, a third-party OIDC/SAML
token, or a social access token) for **temporary AWS credentials** from AWS STS. Use it only when
the client must call AWS services (S3, DynamoDB, etc.) **directly**. If the client only calls your
own backend/API, you do not need an identity pool — send the user pool token to your API instead.

## User pool vs identity pool (the core distinction)

- **User pool** = authentication. "Who are you?" Issues JWTs.
- **Identity pool** = authorization to AWS. "What AWS resources can this identity touch?" Vends
  temporary AWS credentials via STS.

They compose: the user signs in to the user pool, then the app passes the ID token to the identity
pool, which returns temporary AWS credentials.

## What each provider passes to an identity pool

The token type is **provider-specific** — get it wrong and identity resolution fails at
configuration time.

| Provider | Authentication artifact |
|----------|-------------------------|
| Cognito user pool | ID token |
| Generic OIDC IdP | ID token |
| Google, Apple (OIDC providers) | ID token (`id_token`) |
| Facebook, Login with Amazon | Access token |
| SAML 2.0 IdP | SAML assertion |

Google and Apple are OIDC providers: pass their **`id_token`** (Cognito reads it from the
`accounts.google.com` / `appleid.apple.com` logins key). Only **Facebook** and **Login with
Amazon** hand the identity pool an **access token**. Wiring Google (or Apple) with an access
token fails identity resolution at config time.

## Create and wire an identity pool

```
aws cognito-identity create-identity-pool \
  --identity-pool-name my_app_identities \
  --no-allow-unauthenticated-identities \
  --cognito-identity-providers ProviderName=cognito-idp.<region>.amazonaws.com/<pool-id>,ClientId=<app-client-id>

aws cognito-identity set-identity-pool-roles \
  --identity-pool-id <identity-pool-id> \
  --roles authenticated=<auth-role-arn>
```

**`set-identity-pool-roles` replaces the entire roles + `RoleMappings` structure — it is a full
replace, not a merge.** To add or change one role mapping on a pool that already has roles or
mappings, first read the current state with `aws cognito-identity get-identity-pool-roles
--identity-pool-id <id>`, then re-send **all** existing roles and `RoleMappings` plus your addition
in a single `set-identity-pool-roles` call. Sending only the new mapping silently drops the
existing default role and every other mapping.

**The authenticated role's trust policy MUST scope to this identity pool** to prevent
confused-deputy attacks where another Cognito identity pool assumes the role. IAM role
authoring itself belongs to the `aws-iam` skill, but this identity-pool-specific condition
is not covered there:

```json
"Condition": {
  "StringEquals":         { "cognito-identity.amazonaws.com:aud": "<identity-pool-id>" },
  "ForAnyValue:StringLike": { "cognito-identity.amazonaws.com:amr": "authenticated" }
}
```

The `:aud` condition binds the trust to your pool id; `:amr` = `authenticated` ensures the
guest (unauthenticated) role can never assume the authenticated role. Mirror the pattern with
`:amr` = `unauthenticated` on the guest role.

Default to `--no-allow-unauthenticated-identities`. Only enable guest access
(`--allow-unauthenticated-identities` plus an `unauthenticated=<guest-role-arn>` role) when guest
access is genuinely required.

## Two credential flows

- **Enhanced (simplified) flow** — the recommended default. `GetCredentialsForIdentity` returns
  credentials in one step; the pool decides the role.
- **Basic (classic) flow** — the app calls `GetOpenIdToken` then `sts:AssumeRoleWithWebIdentity`
  itself, for full control over the assumed role.

## Role selection

- **Default role** for all authenticated users.
- **Rules-based** — choose a role from claims (e.g. a group claim).
- **Role from token (`cognito:preferred_role`)** — the user pool group's associated role. When a
  user is in multiple groups, the group with the **lowest `Precedence`** value wins; see the
  "User pool groups" section in [user-pools.md](user-pools.md) for `create-group` /
  `admin-add-user-to-group` and the `--precedence` field.
- **Attributes for access control** — map user claims to STS **principal tags**, then gate access
  in resource policies with `aws:PrincipalTag/...`. This is app-level ABAC via Cognito.

Scope the authenticated role tightly (least privilege). The IAM policy language and role authoring
itself belong to the `aws-iam` skill.

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `NotAuthorizedException` / `Token is not from a supported provider` | Provider not registered on the pool, or wrong ClientId | Match `ProviderName` = `cognito-idp.<region>.amazonaws.com/<pool-id>` and the correct app client id |
| `Access denied` after getting credentials | Authenticated role policy too narrow, or trust policy wrong | Fix the role's permissions (see `aws-iam`); ensure the role trusts `cognito-identity.amazonaws.com` with the pool id condition |
| Guests unexpectedly allowed | Unauthenticated identities enabled | Disable guest access; remove the unauthenticated role |

## Related

- [tokens-and-sessions.md](tokens-and-sessions.md) for the token you feed in.
- `aws-iam` skill for authoring the authenticated/guest IAM roles and their trust policies.
- **Authoritative sources** (for guest access details, basic vs enhanced flow, developer-authenticated identities, and multi-provider linking — topics this skill intentionally does not cover): [Amazon Cognito identity pools (developer guide)](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-identity.html) and [External identity providers](https://docs.aws.amazon.com/cognito/latest/developerguide/external-identity-providers.html).
