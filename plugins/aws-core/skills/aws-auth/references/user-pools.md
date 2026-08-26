# Cognito User Pools

## Overview

A user pool is a managed user directory and OpenID Connect (OIDC) identity provider. It handles
sign-up, sign-in, MFA, password policies, and issues JWTs (ID, access, refresh). Use this
reference to create and configure a user pool and its app clients.

## Create a user pool (email sign-in)

```
# Create the pool first. Do NOT pass --mfa-configuration ON|OPTIONAL to create-user-pool:
# at create time that requires --sms-configuration (an SmsConfiguration with an SnsCallerArn)
# or the call fails with InvalidParameterException. Enable MFA after creation (below).
aws cognito-idp create-user-pool \
  --pool-name my-app-users \
  --auto-verified-attributes email \
  --username-attributes email \
  --policies '{"PasswordPolicy":{"MinimumLength":12,"RequireUppercase":true,"RequireLowercase":true,"RequireNumbers":true,"RequireSymbols":true}}'

# Require MFA and enable the TOTP (software token) factor — no SMS/SNS needed for TOTP.
aws cognito-idp set-user-pool-mfa-config \
  --user-pool-id <pool-id> \
  --mfa-configuration ON \
  --software-token-mfa-configuration Enabled=true
```

The example uses a strong default (12+ chars, all character classes, mandatory TOTP MFA). A
shorter/relaxed password policy or a non-mandatory MFA posture is possible but should be
treated as a **non-production exception** — for example, in a local/dev-only pool:

```
# Development-only variant, for local testing — do not use in production.
# Same rule: don't pass --mfa-configuration to create-user-pool; relax MFA (OPTIONAL/OFF) via
# set-user-pool-mfa-config afterward if you need it.
aws cognito-idp create-user-pool \
  --pool-name my-app-users-dev \
  --auto-verified-attributes email \
  --username-attributes email \
  --policies '{"PasswordPolicy":{"MinimumLength":12,"RequireUppercase":true,"RequireLowercase":true,"RequireNumbers":true,"RequireSymbols":true}}'
```

- `--username-attributes email` lets users sign in with their email as the username. Choose this
  or `--alias-attributes`; it is fixed at creation and cannot be changed later.
- `--auto-verified-attributes email` sends a verification code on sign-up.
- The feature plan (tier) governs advanced features (threat protection, access-token
  customization, email OTP). The tiers are **Lite** (entry-level), **Essentials**, and **Plus**;
  set the tier via `--user-pool-tier` where supported. Which tier includes a given feature can
  change, so verify feature-to-tier inclusion against the
  [Cognito feature plans docs](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-sign-in-feature-plans.html).

## App clients

An app client represents one application that talks to the pool. Create one per app/frontend.

```
# Public client (SPA / mobile): NO secret; token revocation + refresh rotation enabled.
# NOTE: with rotation enabled, do NOT include ALLOW_REFRESH_TOKEN_AUTH — that flow is
# incompatible with refresh-token rotation. Refresh via GetTokensFromRefreshToken instead.
aws cognito-idp create-user-pool-client \
  --user-pool-id <pool-id> \
  --client-name web-spa \
  --no-generate-secret \
  --explicit-auth-flows ALLOW_USER_SRP_AUTH \
  --enable-token-revocation \
  --refresh-token-rotation Feature=ENABLED,RetryGracePeriodSeconds=30

# Confidential client (server-side): WITH secret; token revocation + refresh rotation enabled.
# Set --explicit-auth-flows explicitly so the default set (which includes ALLOW_REFRESH_TOKEN_AUTH)
# is not picked up — again, that flow conflicts with rotation.
aws cognito-idp create-user-pool-client \
  --user-pool-id <pool-id> \
  --client-name backend \
  --generate-secret \
  --explicit-auth-flows ALLOW_USER_SRP_AUTH \
  --enable-token-revocation \
  --refresh-token-rotation Feature=ENABLED,RetryGracePeriodSeconds=30
```

**Rule:** public clients (browser/mobile) MUST use `--no-generate-secret`. A secret on a public
client breaks token calls because the browser cannot protect the `SECRET_HASH`. Generate a secret
only for confidential clients running on a server you control.

**Refresh-token rotation makes the `ALLOW_REFRESH_TOKEN_AUTH` (`REFRESH_TOKEN_AUTH`) flow
unavailable at runtime**: an app client with rotation enabled cannot use
`InitiateAuth`/`AdminInitiateAuth` with `AuthFlow=REFRESH_TOKEN_AUTH` — that call is rejected. So
omit `ALLOW_REFRESH_TOKEN_AUTH` from `--explicit-auth-flows` when rotation is on (and set the flows
explicitly on the confidential client so it isn't inherited from the default set), and refresh
tokens with the `GetTokensFromRefreshToken` API instead.

Prefer SRP (`ALLOW_USER_SRP_AUTH`) over `ALLOW_USER_PASSWORD_AUTH` so raw passwords never leave
the client. Enable `ALLOW_USER_PASSWORD_AUTH` only for migration or server-side flows.

## MFA

- `--mfa-configuration` = `OFF` | `OPTIONAL` | `ON`. Default to `ON` (mandatory) for production
  pools. `OPTIONAL` (opt-in) or `OFF` are non-production exceptions — mark them clearly as such
  when used. **Set MFA with `set-user-pool-mfa-config`, not `create-user-pool`:**
  `create-user-pool --mfa-configuration ON|OPTIONAL` only succeeds if you also pass
  `--sms-configuration` (an `SmsConfiguration` with an `SnsCallerArn`), otherwise it fails with
  `InvalidParameterException`. For TOTP or email MFA (no SMS), leave MFA unset at creation and
  configure it afterward with `set-user-pool-mfa-config`.
- Software TOTP (authenticator apps) is the recommended second factor; SMS incurs cost and is
  weaker. Enable TOTP with `set-user-pool-mfa-config --software-token-mfa-configuration Enabled=true`
  — note this call alone only makes TOTP *available*; `--mfa-configuration` (above) is what
  actually requires it.
- Email OTP as a factor requires a supported feature plan.

## Sign-up / sign-in flows (programmatic)

| Action | API |
|--------|-----|
| Register a user | `sign-up` (public) or `admin-create-user` (admin) |
| Confirm sign-up | `confirm-sign-up` with the emailed code, or `admin-confirm-sign-up` |
| Sign in | `initiate-auth` (SRP or `USER_PASSWORD_AUTH`) → returns tokens or a challenge |
| Respond to MFA/other challenge | `respond-to-auth-challenge` |
| Forgot password | `forgot-password` → `confirm-forgot-password` |

Most web/mobile apps should use the **hosted UI / managed login** or the Amplify client library
instead of calling these APIs directly. See [managed-login-oauth.md](managed-login-oauth.md) and
[tokens-and-sessions.md](tokens-and-sessions.md).

## Custom attributes

Add custom attributes at creation with a `custom:` prefix (e.g. `custom:tenant_id`). You can also
add them **after the pool exists** with `aws cognito-idp add-custom-attributes` (up to **50**
custom attributes total). Once defined, a custom attribute cannot be renamed or deleted, and its
mutability is fixed — mark mutable attributes explicitly at definition time.

## User pool groups

Groups let you label users and (optionally) attach an IAM role for identity-pool role mapping.

```
aws cognito-idp create-group \
  --user-pool-id <pool-id> --group-name admins \
  --role-arn <admins-role-arn> --precedence 1

aws cognito-idp admin-add-user-to-group \
  --user-pool-id <pool-id> --username <user> --group-name admins
```

- A user's groups appear in the `cognito:groups` claim; the chosen group role surfaces as
  `cognito:preferred_role`.
- **`--precedence`** breaks ties when a user belongs to multiple groups: the group with the
  **lowest** precedence value wins for `cognito:preferred_role` / identity-pool "role from token".
  Lower number = higher priority.
- This is what the identity-pool "role from token" selection in
  [identity-pools.md](identity-pools.md) depends on.

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `InvalidParameterException: Cannot modify the username attributes` | `username-attributes` fixed at creation | Recreate the pool with the desired setting |
| `NotAuthorizedException: Unable to verify secret hash` | Secret set on a client used without `SECRET_HASH` | Use a no-secret public client, or compute `SECRET_HASH` server-side |
| `UsernameExistsException` | User already registered | Use sign-in or `admin-get-user`; for social users see federation notes |

## Related

- [managed-login-oauth.md](managed-login-oauth.md) for the login UI and OAuth flows.
- [tokens-and-sessions.md](tokens-and-sessions.md) for what to do with the tokens.
- [lambda-triggers.md](lambda-triggers.md) to validate sign-up or customize the flow.

## Authoritative sources

- [Amazon Cognito user pools — Developer Guide](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-identity-pools.html)
- [`aws cognito-idp` CLI reference](https://docs.aws.amazon.com/cli/latest/reference/cognito-idp/)
