# Cognito Lambda Triggers

## Overview

Lambda triggers let you inject custom logic into user pool operations (sign-up, sign-in, token
issuance, migration, messaging). This reference covers **which trigger to use for what** and the
key gotchas. Implementing the Lambda function itself belongs to the `aws-serverless` skill.

## Trigger catalog

| Trigger | Fires when | Use for |
|---------|-----------|---------|
| **Pre sign-up** | A user/admin creates an account | Allow/deny sign-up; auto-**confirm** for trusted flows (see caveat below) |
| **Post confirmation** | Account confirmed or password reset | Post-signup provisioning (add to a group, write to a DB, welcome email) |
| **Pre authentication** | Before sign-in | Block sign-in based on custom rules |
| **Post authentication** | After successful sign-in | Audit / analytics on login |
| **Migrate user** | Sign-in or forgot-password for an unknown user | Lazily import users from a legacy directory/DB |
| **Pre token generation** | Before tokens are issued | Add/modify/suppress token claims (see feature-plan note) |
| **Custom message** | Cognito sends a verification/MFA message | Customize email/SMS content |
| **Define / Create / Verify auth challenge** | Custom authentication flow | CAPTCHA, security questions, or a multi-step challenge sequence your app defines. **Do NOT use for email/SMS OTP passwordless** — Cognito supports those natively as first-auth factors (see [passkeys.md](passkeys.md) for `EMAIL_OTP` / `SMS_OTP` in `AllowedFirstAuthFactors`) |

**Pre sign-up — auto-confirm vs auto-verify are different decisions.** Auto-*confirming* an account
(letting the user skip the confirmation code) is fine for trusted flows. Auto-*verifying* the email
or phone attribute (`autoVerifyEmail`/`autoVerifyPhone`) marks that contact as proven-owned, so only
do it when ownership was established out-of-band — e.g. a federated IdP that already verified it.
**Never auto-verify based solely on the domain of a self-asserted email**, or an attacker can get a
verified attribute they don't own (which then drives password reset / account linking).

## Migrate user — lazy import from a legacy directory

The migrate-user trigger fires when Cognito encounters an unknown username during
sign-in or forgot-password, letting you validate the credentials against a legacy
system and import the user on the fly. Wire this if you're moving 10K+ users off
an existing auth database without forcing everyone to reset their password.

**Wire BOTH trigger sources for a real lazy-migration setup:**

- **`UserMigration_Authentication`** — fires on `InitiateAuth`/`AdminInitiateAuth` for
  an unknown user. Receives `event.request.password` (plaintext, so the Lambda can
  verify against the legacy hash) and `event.request.userAttributes`. Must return
  the user's attributes.
- **`UserMigration_ForgotPassword`** — fires on `ForgotPassword` for an unknown user.
  Does NOT receive the password. Return the user's attributes with
  `email_verified: "true"` so Cognito can send the reset code.

**App client must use `USER_PASSWORD_AUTH` (or `ADMIN_USER_PASSWORD_AUTH`) — SRP
CANNOT WORK for migration.** SRP obscures the plaintext password from Cognito (and
therefore from your Lambda), so the trigger has nothing to verify against the
legacy database. Set `ExplicitAuthFlows` to include `ALLOW_USER_PASSWORD_AUTH` on
the app client. Use TLS end-to-end; the plaintext password appears in the raw
Lambda event, so log-sanitize aggressively.

**Response contract:**

- `userAttributes` — map of Cognito user attributes. Set `email_verified: "true"`
  (or `phone_number_verified: "true"`) to skip re-verification.
- `finalUserStatus` — usually `"CONFIRMED"` so the user can sign in immediately.
  The default is `"RESET_REQUIRED"`, which forces a password reset on next sign-in.
- `messageAction` — `"SUPPRESS"` to skip the default welcome message.

The pool's own password policy is NOT enforced during migration — the legacy hash
was created under its own rules. Consider forcing a rotate-on-next-login for users
whose legacy hash doesn't meet your current policy.

## Pre token generation — feature plan matters

- **V1 (`V1_0`)**: customizes the **ID token** only. Available on the entry-level plan.
- **V2 (`V2_0`)**: customizes the **access token** (and ID token). Requires a **paid feature
  plan** — check the [Cognito feature plans documentation](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-sign-in-feature-plans.html) for which plan currently includes this.
- **V3 (`V3_0`)**: like V2, and also applies to **machine-to-machine** (client-credentials) access
  tokens. Requires a **paid feature plan** — same caveat, verify against current docs.

Verify the feature-plan requirement against the AWS documentation — plan names and inclusions can
change. Do not assume access-token claim customization works on the entry-level plan; choose the
trigger version to match the fields your function expects.

## Custom authentication challenge flow

Wire the three challenge triggers only when you need a **custom** challenge sequence your app
defines: CAPTCHA on high-risk sign-in, security-question fallback, hardware-token wrap, or a
multi-step approval flow. It runs as three triggers in sequence:

1. **Define auth challenge** — the state machine: decides the next challenge or issues tokens.
2. **Create auth challenge** — generates and delivers the challenge.
3. **Verify auth challenge response** — checks the user's answer, sets `answerCorrect`.

Drive it from the client with `initiate-auth --auth-flow CUSTOM_AUTH` then
`respond-to-auth-challenge`.

**Do NOT use this flow for email/SMS OTP passwordless.** Cognito offers native email/SMS
OTP as first-auth factors on supported feature plans, without any custom triggers — set
`EMAIL_OTP` or `SMS_OTP` in the pool's `SignInPolicy.AllowedFirstAuthFactors` and use the
`USER_AUTH` flow. Custom-auth adds three Lambdas, three invoke-permission grants, and a
bespoke state machine to maintain — the native path is a single `update-user-pool` call.
See [passkeys.md](passkeys.md) for the `USER_AUTH` flow and `AllowedFirstAuthFactors` mechanics
(the same wiring covers passkeys, email OTP, and SMS OTP).

## Notification recipients (custom message / MFA)

Send verification codes and MFA messages only to attributes that are already verified, or are
being verified in this same flow (e.g. the address the user just entered at sign-up, before it's
confirmed) — never to an unverified, caller-supplied address that was set for another purpose
(e.g. an attribute updated outside the verification flow). Otherwise a caller-controlled email/phone
value could be used to redirect a code meant for the account owner to an address the caller
chose.

## Gotchas

- A trigger that returns an error **halts** the originating Cognito API call and returns an error
  to the user. **Fail closed** for triggers that make an authentication or authorization decision
  (pre sign-up, pre authentication, verify auth challenge, pre token generation, migrate user):
  return an error rather than allowing the operation to proceed on an unexpected condition or a
  failed dependency call. Fail-open is acceptable only for non-authoritative side-effect triggers
  such as post-authentication analytics or custom messaging, where an error should not block the
  user's sign-in. Example deny path (pre sign-up, Node.js):

  ```js
  if (isBlockedDomain(event.request.userAttributes.email)) {
    throw new Error("Sign-up not permitted for this domain."); // halts sign-up; do not return normally
  }
  ```

- Triggers must return the event with the expected response fields populated, or Cognito rejects
  the response.
- Keep triggers fast; they run inline on the auth path and add latency to every affected request.
- Grant Cognito permission to invoke the function (`lambda:InvokeFunction` for
  `cognito-idp.amazonaws.com` with the pool as source). **The console and CDK wire this
  automatically** — the CDK `UserPool` construct adds the `AWS::Lambda::Permission` when you set
  `lambdaTriggers` or call `addTrigger` (note it sets `aws:SourceArn` but **not**
  `aws:SourceAccount`). Only the raw **CLI / API / CloudFormation** paths need a manual
  `lambda add-permission` / `AWS::Lambda::Permission`. When you add it yourself, include both
  `aws:SourceArn` (the user pool ARN) and `aws:SourceAccount` (your account id) on the Lambda
  resource policy to prevent confused-deputy attacks. Via the CLI, `--source-arn` alone is not
  enough — you **must also pass `--source-account`**, and you must run `add-permission` once per
  Lambda you wire (each trigger function needs its own grant):

  ```
  aws lambda add-permission \
    --function-name <trigger-fn-name-or-arn> \
    --statement-id cognito-<trigger>-invoke \
    --action lambda:InvokeFunction \
    --principal cognito-idp.amazonaws.com \
    --source-arn arn:aws:cognito-idp:<region>:<account>:userpool/<pool-id> \
    --source-account <account>          # REQUIRED alongside --source-arn; omitting it leaves a confused-deputy gap
  ```

  The resulting resource-policy statement carries both conditions:

  ```json
  "Condition": {
    "ArnLike":      { "aws:SourceArn":     "arn:aws:cognito-idp:<region>:<account>:userpool/<pool-id>" },
    "StringEquals": { "aws:SourceAccount": "<account>" }
  }
  ```

- Trigger functions receive user PII (email, phone, custom attributes). Avoid logging full event
  payloads, and encrypt the function's CloudWatch Logs group with a KMS key.

## Related

- [tokens-and-sessions.md](tokens-and-sessions.md) for what the claims feed into.
- `aws-serverless` skill for authoring and deploying the Lambda functions.

## Authoritative sources

- [Customizing user pool workflows with Lambda triggers](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-identity-pools-working-with-aws-lambda-triggers.html)
- [Pre token generation Lambda trigger](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-lambda-pre-token-generation.html)
