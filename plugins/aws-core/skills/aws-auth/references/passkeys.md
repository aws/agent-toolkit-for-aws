# Passkeys (FIDO2 / WebAuthn) in Cognito

## Overview

Cognito supports passkeys — FIDO2/WebAuthn credentials backed by Face ID, Touch
ID, platform authenticators, or hardware security keys — as a **first-factor**
sign-in method. Passkeys can be the only method, or coexist with passwords so
users choose per session.

## Feature-plan gate

Passkeys require the **Essentials** or **Plus** feature plan. NOT available on
Lite. Set at pool creation or via `update-user-pool --user-pool-tier ESSENTIALS`.

## Two integration paths

Passkeys work through **exactly one of these two paths** — the classic hosted
UI (managed login v1) does NOT support passkeys:

- **Managed login v2** — hosted flow. Create the pool domain with
  `--managed-login-version 2`; Cognito renders the passkey prompt automatically.
- **`USER_AUTH` runtime auth flow** — custom UI. App client's `ExplicitAuthFlows`
  must include `ALLOW_USER_AUTH`; call `InitiateAuth` with `AuthFlow=USER_AUTH`.

## Pool-level configuration

Two settings enable passkeys at the pool:

1. **`Policies.SignInPolicy.AllowedFirstAuthFactors`** — declares which factors
   the pool offers as the first step. Include `WEB_AUTHN` to allow passkeys;
   add `PASSWORD` too for coexistence.

   ```
   aws cognito-idp update-user-pool \
     --user-pool-id <pool-id> \
     --policies 'SignInPolicy={AllowedFirstAuthFactors=[PASSWORD, WEB_AUTHN]}' \
     ... (re-send every other existing field — full-replace API)
   ```

   Accepted values: `PASSWORD | EMAIL_OTP | SMS_OTP | WEB_AUTHN` (the enum also
   lists `SOFTWARE_TOKEN` but docs mark it unusable — do not include).

2. **`WebAuthnConfiguration`** — lives on the pool's **MFA configuration**, NOT
   on `SignInPolicy`. Set via `set-user-pool-mfa-config`:

   ```
   aws cognito-idp set-user-pool-mfa-config \
     --user-pool-id <pool-id> \
     --web-authn-configuration RelyingPartyId=auth.example.com,UserVerification=preferred
   ```

   - `RelyingPartyId` — the origin the passkey is bound to. Must match your
     app's domain.
   - `UserVerification` — `required` or `preferred` only (Cognito does NOT
     accept the WebAuthn-spec `discouraged`).

## App client configuration

Include `ALLOW_USER_AUTH` in `ExplicitAuthFlows`:

```
aws cognito-idp update-user-pool-client \
  --user-pool-id <pool-id> --client-id <client-id> \
  --explicit-auth-flows ALLOW_USER_AUTH ALLOW_USER_SRP_AUTH ALLOW_REFRESH_TOKEN_AUTH \
  ... (re-send every other existing field — full-replace API)
```

`ALLOW_USER_AUTH` is distinct from `ALLOW_USER_SRP_AUTH`. Add both if you want
passkey users AND password/SRP users on the same client.

## Password + passkey coexistence

Yes — passkeys and passwords coexist on the **same pool and same app client**;
no need to split. Configure both `PASSWORD` and `WEB_AUTHN` in
`AllowedFirstAuthFactors` and `ALLOW_USER_AUTH` in `ExplicitAuthFlows`.

What each user sees depends on which factors THEY have registered:

- Users with an enrolled passkey → managed login v2 offers passkey first, with
  password fallback.
- Users without → password sign-in, with a prompt to add a passkey after.

## `USER_AUTH` sign-in flow (custom UI)

**Agent-directed** — client picks the factor up front via `PREFERRED_CHALLENGE`:

```
aws cognito-idp initiate-auth \
  --client-id <client-id> \
  --auth-flow USER_AUTH \
  --auth-parameters USERNAME=alice@example.com,PREFERRED_CHALLENGE=WEB_AUTHN
```

Valid `PREFERRED_CHALLENGE`: `PASSWORD | PASSWORD_SRP | WEB_AUTHN | EMAIL_OTP | SMS_OTP`.

**User-directed** — omit `PREFERRED_CHALLENGE`; server returns
`ChallengeName: SELECT_CHALLENGE` with `AvailableChallenges: [...]` filtered to
what the user has registered. Client then responds via
`respond-to-auth-challenge` with `ANSWER=<picked>`.

## Enrollment (registering a passkey)

Two-call flow, authorized by user access token — user must be signed in first:

```
aws cognito-idp start-web-authn-registration \
  --access-token <user-access-token>            # returns PublicKeyCreationOptions

aws cognito-idp complete-web-authn-registration \
  --access-token <user-access-token> \
  --credential file://attestation.json           # browser's attestation
```

WebAuthn APIs authorize via the user's access token (scope
`aws.cognito.signin.user.admin`), NOT via IAM. Companion APIs:
`list-web-authn-credentials`, `delete-web-authn-credential`.

## Authoritative sources

- [`SignInPolicyType`](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_SignInPolicyType.html) — `AllowedFirstAuthFactors` enum
- [`WebAuthnConfigurationType`](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_WebAuthnConfigurationType.html) — on `SetUserPoolMfaConfig`
- [`InitiateAuth`](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_InitiateAuth.html) — `USER_AUTH` flow
- [Sign-in with passkeys](https://docs.aws.amazon.com/cognito/latest/developerguide/authentication.html)
