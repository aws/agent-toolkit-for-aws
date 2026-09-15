# Managed Login & OAuth Flows

## Overview

Cognito serves two versions of its hosted sign-in pages, chosen **per domain** via
`ManagedLoginVersion`: the classic hosted UI (`ManagedLoginVersion` 1) and **managed login**
(`ManagedLoginVersion` 2), which adds a no-code visual branding designer and native support
for passkeys and email/SMS OTP as first-factor sign-in. They are separate domain versions
selected at domain-creation time — not two names for the same thing. Both are hosted, OAuth
2.0–compliant authorization servers with built-in sign-up, sign-in, MFA, password reset, and
social/SAML login. **Prefer `ManagedLoginVersion` 2 for new integrations** — managed login
is the successor brand to the classic hosted UI, and passkey / native-OTP factors
require v2. Prefer the hosted pages over a custom login page for faster, more secure
time-to-market; build a custom UI only when branding requirements are strict (and you accept
owning MFA, reset, and federation UX).

## Set up the domain

```
aws cognito-idp create-user-pool-domain \
  --user-pool-id <pool-id> \
  --domain my-app-login \
  --managed-login-version 2      # 2 = managed login (branding designer); 1 = classic hosted UI
  # Cognito prefix domain: my-app-login.auth.<region>.amazoncognito.com
```

### Managed login v2 needs a branding style per app client

**The console auto-assigns a default branding style when you enable managed login v2; the CLI
and API do not.** Cognito documents managed login as unavailable for an app client until a
branding style exists, so a domain created with `--managed-login-version 2` produces a broken
login page for every client that has no style. After the app client is created, run:

```
aws cognito-idp create-managed-login-branding \
  --user-pool-id <pool-id> \
  --client-id <client-id> \
  --use-cognito-provided-values
```

`--use-cognito-provided-values` seeds Cognito's default look; the branding can be customized
later. Run this **per app client** that uses the domain (each client owns its own style).
Omit this on `ManagedLoginVersion` 1 (classic hosted UI) — v1 has no branding designer and
does not require this step.

### Custom domain (production branding)

For a production custom domain like `auth.mycompany.com` instead of the default
`<prefix>.auth.<region>.amazoncognito.com`:

1. **ACM certificate must be in `us-east-1`** — regardless of your user pool's region.
   Cognito serves the hosted pages via CloudFront under the hood, and CloudFront
   distributions require certs in us-east-1. The certificate's primary name (or a SAN)
   must match the exact custom domain (`auth.mycompany.com`).
2. **Create the user pool domain with the certificate:**

   ```
   aws cognito-idp create-user-pool-domain \
     --user-pool-id <pool-id> \
     --domain auth.mycompany.com \
     --custom-domain-config CertificateArn=arn:aws:acm:us-east-1:<account>:certificate/<uuid> \
     --managed-login-version 2
   ```

3. **Point DNS at Cognito's CloudFront distribution.** The response contains the
   distribution FQDN as `CloudFrontDomain` (in the create response) / `CloudFrontDistribution`
   (in `describe-user-pool-domain`). Set a `CNAME` — or a Route 53 alias A record — from
   `auth.mycompany.com` to that CloudFront FQDN.

**Parent-domain gotcha.** Cognito refuses the subdomain if the parent domain
(`mycompany.com`) has no `A` record — an SOA record is NOT sufficient. If your apex isn't
behind a real `A` record (e.g. Route 53 with no landing page), add a dummy `A` record for
validation and remove it after Cognito accepts the domain.

**Timing.** Provisioning can take several minutes; `describe-user-pool-domain` reports
`Status: CREATING` until CloudFront is ready. Wait for `ACTIVE` before pointing DNS.

## Configure OAuth on the app client

**`update-user-pool-client` replaces the entire client configuration — any field you omit is
reset to its default.** It is not a partial update (`PATCH`); it is a full replace (`PUT`). Calling
it with only the OAuth parameters against an existing client silently wipes everything else you set
before — `ExplicitAuthFlows`, `AccessTokenValidity`/`IdTokenValidity`, `EnableTokenRevocation`,
refresh-token rotation, read/write attributes, and more. In an agent context that is a one-shot
outage: the client keeps working just enough that the wipe is invisible until a user hits the
missing flow.

**Always read-modify-write.** Describe the client first, keep every existing field, add or change
only what you were asked to, then re-send the full set.

**Most reliable method — round-trip the exact config with `--cli-input-json`.** Rather than
re-typing every flag by hand (easy to drop a field, which then silently resets), take the
`describe` output, delete the three read-only fields that `update` rejects
(`ClientSecret`, `CreationDate`, `LastModifiedDate`), apply your change, and feed the whole object
back. Every other field is preserved verbatim:

```
# 1. Read current config into the exact shape update expects (strip read-only fields).
aws cognito-idp describe-user-pool-client \
  --user-pool-id <pool-id> --client-id <client-id> \
  --query 'UserPoolClient' --output json \
  | jq 'del(.ClientSecret, .CreationDate, .LastModifiedDate)' > client.json

# 2. Apply only the requested change (add callback2 + the `profile` scope), keeping the rest.
jq '.CallbackURLs += ["https://app.example.com/callback2"] | .AllowedOAuthScopes += ["profile"]' \
  client.json > client-updated.json

# 3. Re-send the FULL object. Unspecified fields would reset; here nothing is omitted.
aws cognito-idp update-user-pool-client --cli-input-json file://client-updated.json
```

If you instead pass individual `--flags`, you must repeat **every** existing field (from the
describe) alongside your change, or the omitted ones reset to default. The `--cli-input-json`
round-trip above avoids that trap.

The same full-replace rule applies to `set-identity-pool-roles` (it replaces the whole roles +
`RoleMappings` structure) — see [identity-pools.md](identity-pools.md).

## OAuth flow selection

| Flow | `allowed-o-auth-flows` | Use for |
|------|------------------------|---------|
| **Authorization code + PKCE** | `code` | SPAs and mobile (public clients) — **default choice** |
| Authorization code (with secret) | `code` | Server-side/confidential clients |
| Client credentials | `client_credentials` | Machine-to-machine (no user); requires a resource server + custom scopes and a client secret |
| Implicit (`token`) | `implicit` | **Legacy only** — returns tokens in the URL fragment; avoid for new apps |

**Authorization code + PKCE** is the secure default for browser/mobile. The authorize request adds
`code_challenge`/`code_challenge_method=S256`; the token exchange sends the matching
`code_verifier`. No client secret is used.

## Machine-to-machine (client credentials) & resource servers

`client_credentials` is the OAuth flow for **service-to-service** auth with **no user**. It needs a
**resource server** that declares **custom scopes**, plus a **confidential app client** (with a
secret) that has the flow enabled and those scopes granted.

1. Create a resource server with custom scopes. A scope's full identifier is
   `<resource-server-identifier>/<scope-name>` (e.g. `https://api.example.com/orders.read`):

   ```
   aws cognito-idp create-resource-server \
     --user-pool-id <pool-id> \
     --identifier https://api.example.com \
     --name orders-api \
     --scopes ScopeName=orders.read,ScopeDescription="Read orders" \
              ScopeName=orders.write,ScopeDescription="Write orders"
   ```

2. Create a **confidential** app client (with a secret), enable the `client_credentials` flow, and
   grant the custom scopes — no `openid`/user scopes, because there is no user:

   ```
   aws cognito-idp create-user-pool-client \
     --user-pool-id <pool-id> --client-name svc-client \
     --generate-secret \
     --allowed-o-auth-flows-user-pool-client \
     --allowed-o-auth-flows client_credentials \
     --allowed-o-auth-scopes https://api.example.com/orders.read
   ```

3. The service fetches an **access token** from the token endpoint (HTTP Basic auth with
   `client_id:client_secret`) — no user login, no hosted UI:

   ```
   curl -X POST https://<domain>/oauth2/token \
     -H 'Authorization: Basic <base64(client_id:client_secret)>' \
     -H 'Content-Type: application/x-www-form-urlencoded' \
     -d 'grant_type=client_credentials&scope=https://api.example.com/orders.read'
   ```

- The response is an **access token only** — **no ID token and no refresh token**. Request a new
  token when it expires.
- The access token's `scope` claim carries the granted scopes; enforce them at your API (require
  the scope on the route or check the `scope` claim). See [api-authorization.md](api-authorization.md).
- `client_credentials` requires a user pool **domain** and a **client secret**, so it is only for
  confidential clients — never public browser/mobile clients. Cognito's token endpoint does NOT
  return `invalid_scope`: requesting a scope the client wasn't granted is silently dropped from
  the response `scope` claim, or the request fails with `invalid_grant` — do not branch on
  `invalid_scope`. The documented error set for `/oauth2/token` is `invalid_request`,
  `invalid_client`, `invalid_grant`, `unauthorized_client`, and `unsupported_grant_type`. See
  [token endpoint docs](https://docs.aws.amazon.com/cognito/latest/developerguide/token-endpoint.html).

## Authorize → token exchange (code + PKCE)

1. Redirect the browser to:
   `https://<domain>/oauth2/authorize?response_type=code&client_id=<id>&redirect_uri=<callback>&scope=openid+email&code_challenge=<challenge>&code_challenge_method=S256&state=<state>`
2. Cognito redirects back to `redirect_uri?code=<code>&state=<state>`.
3. Exchange the code at `/oauth2/token` with `grant_type=authorization_code`, the `code`, the
   `redirect_uri`, and the `code_verifier`. Response contains `id_token`, `access_token`,
   `refresh_token`.

**`state` and `nonce` (CSRF + replay protection — use both alongside PKCE):** generate `state` as a
cryptographically random, single-use value (e.g. 32 bytes from a CSPRNG), store it bound to the
browser session, and **reject the callback if the returned `state` doesn't match**. For OIDC, also
send a random `nonce` on the authorize request and verify the `nonce` claim in the returned ID
token. PKCE protects the code exchange; `state`/`nonce` protect against CSRF and replay — they are
complementary, not alternatives.

The Amplify client library performs this whole flow for you; see
[tokens-and-sessions.md](tokens-and-sessions.md).

## Social & SAML federation

**Never put the IdP `client_secret` on the command line.** Interpolating it into
`--provider-details "...client_secret=${G_SECRET}..."` exposes it via `ps`, shell history, and the
agent transcript. Pass `--provider-details` by **file reference** instead: write the details to a
`umask 077` temp file, pass `file://`, and delete it. Never echo or log the secret value.

```
# Example: Google — read the secret from Secrets Manager into a locked-down temp file,
# pass it by file reference (never on the command line), then delete the file.
umask 077
DETAILS=$(mktemp)
G_SECRET=$(aws secretsmanager get-secret-value \
  --secret-id google-idp-secret --query SecretString --output text)
cat > "$DETAILS" <<JSON
{"client_id":"<g-id>","client_secret":"${G_SECRET}","authorize_scopes":"openid email profile"}
JSON
unset G_SECRET

aws cognito-idp create-identity-provider \
  --user-pool-id <pool-id> \
  --provider-name Google --provider-type Google \
  --provider-details "file://${DETAILS}" \
  --attribute-mapping email=email,name=name

rm -f "$DETAILS"
```

Then add the provider to the app client's `--supported-identity-providers` (e.g. `COGNITO Google`).
SAML and OIDC third-party IdPs use `--provider-type SAML|OIDC` with the metadata URL/document.

**Secret handling:** store the social IdP `client_secret` in AWS Secrets Manager, read it at
configuration time, pass it only by `file://` reference (as above), and never commit it to source.

**Attribute mapping matters:** map the IdP's email/name claims to user pool attributes. Without
account linking, the same person signing in via different IdPs (or via email + Google) creates
**separate** users. Treat email as non-unique across providers and link deliberately.

## Multi-tenant SAML — routing users to their tenant's IdP

A common B2B SaaS pattern: one Cognito user pool, each enterprise tenant brings their own SAML
IdP (Okta, Azure AD, Ping), and each tenant's users must land on **their** IdP without seeing
the managed-login provider picker. Two `/authorize` query parameters do this — both silently
redirect through the Authorize endpoint straight to the tenant's IdP:

- **`identity_provider=<ProviderName>`** — pass the IdP's `ProviderName` (as configured on
  `CreateIdentityProvider`) directly on the authorize URL. Use when the client already knows
  which tenant the user belongs to.

  ```
  https://<domain>/oauth2/authorize?response_type=code&identity_provider=TenantASAML&client_id=<id>&redirect_uri=<url>
  ```

- **`idp_identifier=<friendly-id>`** — pass an IdP *identifier* configured on the IdP via
  `IdpIdentifiers` (an array of up to 50 friendly names per IdP). Useful when a single IdP
  owns multiple aliases, or when identifiers match the tenants' email domains and managed
  login can auto-route by asking the user for their email.

  ```
  aws cognito-idp create-identity-provider \
    --user-pool-id <pool-id> \
    --provider-name TenantASAML --provider-type SAML \
    --idp-identifiers tenant-a.example.com corp.tenant-a.io \
    --provider-details MetadataURL=https://tenant-a.example.com/saml/metadata.xml \
    --attribute-mapping email=...
  # then on /authorize:
  #   idp_identifier=tenant-a.example.com
  ```

Add the IdP to the app client's `--supported-identity-providers` (each tenant IdP still needs
to be a supported provider on the client). Since the routing parameters bypass the picker, users
never see other tenants' IdPs — the tenant list stays private per tenant.

## Callback URL rules

Registered callback and logout URLs must match **exactly** — scheme, host, path, and trailing
slash all count. HTTP (not HTTPS) is allowed only for **loopback** addresses — `http://localhost`,
`http://127.0.0.1`, and `http://[::1]` — for local dev; every other web URL must be HTTPS.
**Custom application schemes** (e.g. `myapp://callback`) are also allowed — that's how native
mobile apps receive the redirect, which matters because this skill steers mobile apps to the
authorization-code + PKCE flow. A mismatch produces `redirect_mismatch`.

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `redirect_mismatch` | Callback URL not registered exactly | Add the exact URL to Allowed callback URLs |
| `invalid_grant` on token exchange | Reused/expired code, or missing `code_verifier` | Exchange the code once, promptly, with the matching verifier |
| Social login loops or drops attributes | Missing attribute mapping / provider not on client | Map attributes; add the IdP to the app client |

## Related

- [tokens-and-sessions.md](tokens-and-sessions.md) for handling the returned tokens.
- [troubleshooting.md](troubleshooting.md) for redirect/CORS/federation issues.

## Authoritative sources

- [User pool managed login / hosted UI](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-managed-login.html)
- [User pool endpoints & managed login reference (OAuth 2.0 `/authorize`, `/token`, PKCE)](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-userpools-server-contract-reference.html)
