# Protecting APIs with Cognito

## Overview

This reference covers wiring a Cognito user pool to an Amazon API Gateway API (and ALB) so only
authenticated requests get through. It covers only the **authorizer** side. Creating the API's
routes, integrations, and backing Lambda belongs to the `aws-serverless` skill.

## Choose the authorizer by API type

| API type | Authorizer | Token used |
|----------|-----------|------------|
| **HTTP API** (API Gateway v2) | Built-in **JWT authorizer** | ID or access token |
| **REST API** (API Gateway v1) | **Cognito user pools authorizer** (`COGNITO_USER_POOLS`) | ID token by default |
| Application Load Balancer | ALB built-in `authenticate-cognito` action | Performs the OIDC login itself |

## HTTP API — JWT authorizer

The JWT authorizer validates the token's signature, issuer, and audience with no Lambda.

```
aws apigatewayv2 create-authorizer \
  --api-id <api-id> \
  --authorizer-type JWT \
  --name cognito-jwt \
  --identity-source '$request.header.Authorization' \
  --jwt-configuration Audience=<app-client-id>,Issuer=https://cognito-idp.<region>.amazonaws.com/<pool-id>
```

- **Issuer** MUST be `https://cognito-idp.<region>.amazonaws.com/<userPoolId>`.
- **Audience** MUST be the **app client id**.
- Attach the authorizer to a route and (optionally) require scopes on the route.
- Audience matching: the **ID token** carries `aud` = client id; the **access token** carries
  `client_id` and `scope`. If you send access tokens, the JWT authorizer still validates against
  the configured audience/issuer — send the token type your configuration expects and, for
  scope-based authorization, use the access token.

### What the JWT authorizer does NOT enforce

The HTTP-API JWT authorizer validates only the signature, `iss`, `aud` / `client_id`,
`exp`/`nbf`/`iat`, and — if you set `authorizationScopes` on the route — the `scope` /
`scp` claim. It does **not** enforce arbitrary custom claims like `custom:tenant_id`,
`cognito:groups`, or attributes added by a pre-token-generation Lambda. Those must be
inspected in the backend / integration.

API Gateway forwards the JWT claims into the request context. In a Lambda integration:

```js
// event.requestContext.authorizer.jwt.claims is a flat map of every claim in the token
const tenantId = event.requestContext.authorizer.jwt.claims["custom:tenant_id"];
const groups   = event.requestContext.authorizer.jwt.claims["cognito:groups"];  // string or array
if (tenantId !== requestedTenant) {
  return { statusCode: 403, body: "wrong tenant" };
}
```

For heavier claim-based policy, use a Lambda authorizer (any custom logic) or Amazon
Verified Permissions (Cedar policies over token claims) instead.

## REST API — Cognito user pools authorizer

```
aws apigateway create-authorizer \
  --rest-api-id <api-id> \
  --name cognito-authorizer \
  --type COGNITO_USER_POOLS \
  --provider-arns arn:aws:cognito-idp:<region>:<account>:userpool/<pool-id> \
  --identity-source method.request.header.Authorization
```

Then set the method's `authorizationType` to `COGNITO_USER_POOLS` and reference the authorizer.
REST API Cognito authorizers validate the **ID token** by default.

## Verifying tokens yourself (non-API-Gateway backends)

If your backend isn't behind an API Gateway authorizer, validate the JWT on every request:

1. Fetch the pool JWKS: `https://cognito-idp.<region>.amazonaws.com/<pool-id>/.well-known/jwks.json`.
2. Verify the RS256 signature against the matching `kid`.
3. Check `iss` (the issuer URL above), `exp`, `token_use` (`id` vs `access`), and
   `aud`/`client_id`.

Use a maintained JWT library (e.g. `aws-jwt-verify`) rather than hand-rolling verification.

## Defense in depth

The authorizer authenticates callers but is not the whole story:

- Enable **AWS WAF** on the API Gateway stage (managed rules + rate-based rules) to blunt common
  web exploits and volumetric/token-stuffing attacks.
- Configure API Gateway **throttling / rate limiting** to cap brute-force attempts.
- Validate and sanitize request inputs beyond the authorization token.

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| 401 with a valid token | Issuer or audience mismatch, or wrong token type | Set issuer/audience exactly as above; send the token the authorizer expects |
| 401 "Unauthorized" but token looks fine | `identity-source` header not sent or wrong casing | Send `Authorization: <token>`; match the configured identity source |
| Works locally, 403 in prod | CORS preflight blocked (OPTIONS needs no auth) | Allow unauthenticated `OPTIONS`; configure CORS on the API |

## Related

- [tokens-and-sessions.md](tokens-and-sessions.md) for which token to send.
- `aws-serverless` skill for API Gateway routes/integrations and Lambda implementation.

## Authoritative sources

- [Control access to HTTP APIs with JWT authorizers](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html)
- [Control access to REST APIs using Cognito user pools as an authorizer](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-integrate-with-cognito.html)
