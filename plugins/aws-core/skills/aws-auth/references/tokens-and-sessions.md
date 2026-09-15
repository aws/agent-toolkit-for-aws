# Tokens & Sessions

## Overview

Cognito issues three JWTs after authentication. Knowing which token to use where — and how to
refresh, rotate, revoke, and store them safely — prevents most auth bugs.

## The three tokens

| Token | Contents | Use it for | Lifetime |
|-------|----------|------------|----------|
| **ID token** | Identity claims (name, email, etc.) | Proving **who** the user is (identity) to your app; identity-based checks you run yourself. NOT the credential for scope-based API authorization | Short-lived, configurable per app client — check the current default and valid range in the [Cognito quotas docs](https://docs.aws.amazon.com/cognito/latest/developerguide/limits.html) or via `aws cognito-idp describe-user-pool-client` |
| **Access token** | Groups, scopes, user claims | **Authorizing API calls** — scope- and group-based access to your API and OAuth-scoped resources. This is the token meant for authorization | Short-lived, configurable per app client — check the current default and valid range in the [Cognito quotas docs](https://docs.aws.amazon.com/cognito/latest/developerguide/limits.html) or via `aws cognito-idp describe-user-pool-client` |
| **Refresh token** | Opaque | Getting new ID and access tokens without re-login | Long-lived, configurable per app client — check the current default and min/max range in the [Cognito quotas docs](https://docs.aws.amazon.com/cognito/latest/developerguide/limits.html) or via `aws cognito-idp describe-user-pool-client` |

ID and access tokens are short-lived; the refresh token is long-lived. Send the token your
consumer expects: an API Gateway JWT authorizer can be configured for either, but the audience
(`aud`) claim is present on the ID token while the access token carries `client_id` and `scope` —
match the authorizer's `audience`/identity source to the token you send. See
[api-authorization.md](api-authorization.md).

For **authorization** decisions, use the **access token** — it carries `scope` and
`cognito:groups`, so scope- or group-based checks belong there. The **ID token** proves identity
and is fine for identity-based checks you perform inside your own app, but it is not the token to
gate API access with.

### InitiateAuth-issued access tokens don't carry custom scopes

An important architectural fact: `InitiateAuth` and `AdminInitiateAuth` issue access tokens that
carry only the reserved scope `aws.cognito.signin.user.admin` — **custom scopes are NEVER
included regardless of what's configured in the app client's `AllowedOAuthScopes`**. This is
independent of the auth flow (SRP, USER_PASSWORD_AUTH, USER_AUTH — all the same). Custom scopes
are only issued through the OAuth 2.0 endpoints: `/oauth2/authorize` (hosted UI / managed-login
authorization-code + PKCE flow) and `/oauth2/token` (for token-grant endpoints including
`client_credentials`).

If your API Gateway route requires a custom scope like `https://api.example.com/orders.read`, an
InitiateAuth-signed user cannot pass it — the scope is simply not in their access token. Three
workarounds:

1. Switch the sign-in flow to hosted UI / OAuth (authorization-code + PKCE) — the standard fix.
2. Authorize on `cognito:groups` (or a custom claim) at the API instead of on scopes.
3. Use a V2/V3 pre-token-generation Lambda trigger to inject scopes into the access token via
   `scopesToAdd` — requires the Essentials or Plus feature plan (V3 for machine-to-machine).

Adding the scope to `AllowedOAuthScopes` on the app client does NOT fix this — the config is
already relevant only to the OAuth endpoints.

## Refresh token rotation

Enable rotation so each refresh returns a **new** refresh token and invalidates the old one,
limiting the blast radius of a stolen token.

```
aws cognito-idp update-user-pool-client \
  --user-pool-id <pool-id> --client-id <client-id> \
  --refresh-token-rotation Feature=ENABLED,RetryGracePeriodSeconds=30
```

**`update-user-pool-client` is a full replace, not a partial update** — any field you omit reverts
to its default. The one-flag command above is safe **only** on a client that has no other
configuration to lose. On an already-configured client, describe it first and re-send every
existing field alongside the rotation flag, or you will silently wipe its auth flows, token
validity, and scopes. See the read-modify-write pattern in
[managed-login-oauth.md](managed-login-oauth.md).

- `RetryGracePeriodSeconds` (0–60) lets the rotated-out token stay valid briefly for client
  retries. `0` invalidates it immediately on a successful refresh.
- Refresh with the `GetTokensFromRefreshToken` API (or the token endpoint `grant_type=refresh_token`).
- **Rotation disables the `REFRESH_TOKEN_AUTH` flow.** An app client with rotation enabled cannot
  use `InitiateAuth`/`AdminInitiateAuth` with `AuthFlow=REFRESH_TOKEN_AUTH` — that call is rejected
  at runtime. So `ALLOW_REFRESH_TOKEN_AUTH` and refresh-token rotation are **not** a valid
  combination: leave `ALLOW_REFRESH_TOKEN_AUTH` out of the client's `--explicit-auth-flows` when
  rotation is on, and refresh via `GetTokensFromRefreshToken` (or the token endpoint) instead.

## Session termination — pick the right API

Three APIs end sessions, each with different reach:

| API | What it kills | Use for |
|-----|---------------|---------|
| `RevokeToken` / `/oauth2/revoke` | ONE refresh token + the access/ID tokens issued from it | Signing out a single device |
| `AdminUserGlobalSignOut` | **All** refresh tokens for the user (across every session) | Stolen device / password compromise |
| `AdminDisableUser` | All tokens **AND** blocks future auth attempts | Account termination / suspected compromise |

`RevokeToken` requires token revocation enabled on the app client
(`EnableTokenRevocation=true`). Revoking a refresh token invalidates every access/ID token
issued from it; other refresh tokens for the same user are unaffected.
`AdminUserGlobalSignOut` invalidates the user's identity, access, and refresh tokens across
all sessions — but the user's account is still active, so they can sign back in and get
fresh tokens. `AdminDisableUser` goes further: existing tokens die AND new auth attempts
fail (`NotAuthorizedException: User is disabled`).

### Nuance: access tokens against non-Cognito resource servers

All three APIs invalidate server-side session state. When a downstream resource server
verifies the token:

- **Cognito's own user-pool APIs** check revocation state and reject revoked tokens
  immediately.
- **External resource servers** that verify the JWT locally (signature + `exp` + `iss` +
  `aud`) have no way to know a token was revoked. Already-issued access tokens remain
  usable against those servers until natural `exp`.

The mitigation is short access-token lifetimes (5–15 minutes) plus refresh-token
revocation for the long-tail lockout — force the client to refresh, at which point the
revoked refresh token blocks the flow.

### The hosted-UI / managed-login session cookie is SEPARATE

Signing out via any of the three APIs above does **not** clear the managed-login session
cookie. A user with a valid cookie can hit `/oauth2/authorize` and receive fresh tokens
without ever presenting a refresh token — so a "kill all sessions" flow that only calls
`AdminUserGlobalSignOut` leaves that back door open. For a full teardown, also redirect
the user through:

```
https://<domain>/logout?client_id=<id>&logout_uri=<url>
```

The `/logout` endpoint clears the cookie and returns the user to `logout_uri` (which
must be registered as an Allowed sign-out URL on the app client).

## Token revocation (single-session detail)

Enable revocation on the app client so any of the APIs above can invalidate a session.
Revocation adds `jti` / `origin_jti` claims to issued tokens, slightly increasing token
size.

```
aws cognito-idp update-user-pool-client \
  --user-pool-id <pool-id> --client-id <client-id> \
  --enable-token-revocation \
  ... (re-send every other existing field — full-replace API)
```

Revoke via the API:

```
aws cognito-idp revoke-token \
  --client-id <client-id> \
  --token <refresh-token>
```

Or the OAuth endpoint (for public clients that don't want to expose the API):

```
POST https://<domain>/oauth2/revoke
Content-Type: application/x-www-form-urlencoded

client_id=<id>&token=<refresh-token>
```

## Frontend token storage (security)

The Amplify client library defaults to **`localStorage`**, which is readable by any injected
script — an XSS foothold can exfiltrate tokens. For anything sensitive:

- Prefer **`cookieStorage`** with `Secure` and `SameSite=Strict`. Note that Amplify's cookie store **cannot** be `HttpOnly` — the SDK reads tokens client-side to attach them to requests, so setting `HttpOnly` would break token retrieval. For true `HttpOnly` storage, use a **backend-for-frontend (BFF)** that holds tokens server-side.
- Keep the refresh token lifetime short and enable **rotation + revocation**.
- Never place tokens in URLs or logs.

There is no perfect browser storage; reducing token lifetime and enabling rotation/revocation
matters more than the storage location alone.

## Amplify client library (using an existing user pool)

This is the client SDK (`aws-amplify` / `@aws-amplify/auth`) pointed at a user pool you configured —
**not** the Amplify Gen2 backend (`amplify/auth.ts`), which belongs to the `aws-amplify` skill.

```ts
import { Amplify } from 'aws-amplify';
import { signIn, signInWithRedirect, fetchAuthSession } from 'aws-amplify/auth';

Amplify.configure({
  Auth: { Cognito: { userPoolId: '<pool-id>', userPoolClientId: '<client-id>' } },
});

// Direct SRP / username-password sign-in (your own UI, no hosted UI):
await signIn({ username, password });

// Hosted UI / managed login via the OAuth authorization-code + PKCE flow:
await signInWithRedirect();   // redirects to the hosted UI; Amplify completes the code+PKCE exchange on return

const { tokens } = await fetchAuthSession();   // tokens.idToken / tokens.accessToken
```

`signIn({ username, password })` runs the **SRP / username-password** flow directly against the
user pool — it does **not** use the hosted UI or the OAuth code+PKCE exchange. The hosted-UI
authorization-code + PKCE flow goes through **`signInWithRedirect()`**; that is the call that
performs the code+PKCE exchange. Either way, Amplify handles token storage and automatic refresh.

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| Users forced to re-login every hour | Not refreshing; only using ID/access token | Use the refresh token (or Amplify auto-refresh) to get new tokens |
| `NotAuthorizedException: Refresh Token has been revoked` | Rotation invalidated the old token | Store and use the newest refresh token from each refresh |
| Token accepted then suddenly rejected | Revocation or expiry | Re-authenticate; check `exp` and revocation state |

## Related

- [managed-login-oauth.md](managed-login-oauth.md) for obtaining tokens.
- [api-authorization.md](api-authorization.md) for validating tokens at the API.

## Authoritative sources

- [Understanding user pool JSON web tokens (JWTs)](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-with-identity-providers.html)
- [Ending user sessions with token revocation](https://docs.aws.amazon.com/cognito/latest/developerguide/token-revocation.html)
