# Auth Troubleshooting

## Overview

The most common Cognito failures, by symptom, with root cause and fix.

## Redirect & hosted UI

| Symptom | Cause | Fix |
|---------|-------|-----|
| `redirect_mismatch` after login | Callback URL not registered exactly (scheme/host/path/trailing slash/case) | Add the exact callback URL to the app client's Allowed callback URLs; localhost must be `http://localhost:<port>`, all else HTTPS |
| Login page 400 "invalid_request" | Missing/invalid `response_type`, `client_id`, or unsupported scope | Send `response_type=code`, a valid client id, and scopes the client allows |
| `invalid_grant` at `/oauth2/token` | Code reused, expired, or `code_verifier` missing/wrong | Exchange the code once, promptly, with the matching PKCE verifier |
| CORS error hitting hosted UI or token endpoint | Browser calling `/oauth2/token` cross-origin, or proxying it | Do the code+PKCE exchange client-side per the flow; don't proxy the token endpoint |

## Client secret / auth flow

| Symptom | Cause | Fix |
|---------|-------|-----|
| `NotAuthorizedException: Unable to verify secret hash` | Client secret set on a public (SPA/mobile) client | Recreate the app client with no secret, or compute `SECRET_HASH` in a server-side client |
| `InvalidParameterException: Auth flow not enabled` | The flow isn't in the client's explicit auth flows | Add e.g. `ALLOW_USER_SRP_AUTH` / `ALLOW_REFRESH_TOKEN_AUTH` (note: `ALLOW_REFRESH_TOKEN_AUTH` is incompatible with refresh-token rotation — with rotation on, use `GetTokensFromRefreshToken` instead) |
| Password auth rejected | `ALLOW_USER_PASSWORD_AUTH` disabled (good default) | Use SRP; enable password auth only for migration/server flows |

## Tokens & sessions

| Symptom | Cause | Fix |
|---------|-------|-----|
| Forced re-login every hour | Not using the refresh token | Refresh via `GetTokensFromRefreshToken` / Amplify auto-refresh |
| `Refresh Token has been revoked` | Rotation invalidated the old refresh token | Always use the newest refresh token returned by each refresh |
| API returns 401 with a "valid" token | Issuer/audience mismatch or wrong token type | Issuer `https://cognito-idp.<region>.amazonaws.com/<pool-id>`, audience = client id; send the expected token (see api-authorization.md) |

## MFA & sign-up

| Symptom | Cause | Fix |
|---------|-------|-----|
| TOTP enrollment fails | Software MFA not enabled on the pool | `set-user-pool-mfa-config --software-token-mfa-configuration Enabled=true` |
| Users stuck `UNCONFIRMED` | Verification code expired, never entered, or went to spam | Prefer `resend-confirmation-code` so each user re-verifies via `confirm-sign-up` — this proves email ownership. `admin-confirm-sign-up` flips the status instantly but confirms the account **without verifying the email**, leaving the attribute unverified (risky when email drives password reset / account linking); reserve it for trusted or migrated accounts and set the attribute verified separately only when ownership is established another way. |
| Sign-up blocked unexpectedly | Pre sign-up trigger returned an error | Inspect the trigger's logic/logs; it halts the sign-up on error |

## Federation

| Symptom | Cause | Fix |
|---------|-------|-----|
| Social user "already exists" / duplicate accounts | Same email across IdPs creates separate users | Enable attribute mapping and deliberate account linking; treat email as non-unique across providers |
| Missing name/email after social login | IdP claims not mapped to pool attributes | Set `--attribute-mapping` on the identity provider |
| SAML login fails | Metadata stale or attribute mapping wrong | Refresh IdP metadata; verify NameID/attribute mapping |

## Identity pools

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Token is not from a supported provider` | Provider/ClientId not registered on the identity pool | Match `cognito-idp.<region>.amazonaws.com/<pool-id>` and the app client id |
| `Access denied` after credentials returned | Authenticated role policy too narrow / trust policy wrong | Fix the role (see `aws-iam`); ensure it trusts `cognito-identity.amazonaws.com` for the pool |

## Related

- [managed-login-oauth.md](managed-login-oauth.md), [tokens-and-sessions.md](tokens-and-sessions.md),
  [api-authorization.md](api-authorization.md), [identity-pools.md](identity-pools.md).

## Authoritative sources

- [Amazon Cognito user pools — Developer Guide](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-identity-pools.html)
- [Managed login & federation error responses (redirect/token errors)](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-userpools-server-contract-reference.html)
