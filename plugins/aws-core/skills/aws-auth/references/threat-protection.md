# Threat Protection & Adaptive Authentication

## Overview

Cognito's threat protection (formerly "advanced security features") detects and
responds to suspicious sign-in activity: compromised (breached) passwords,
risky patterns (new device, unusual IP), and risk-based adaptive MFA.

## Feature-plan gate

Threat protection features require the **Plus** feature plan:

- `AdvancedSecurityMode = AUDIT | ENFORCED` — Plus only.
- Adaptive-auth risk configuration — Plus only.
- Threat-protection log delivery (`userAuthEvents` event source) — Plus only.

Attempting these on a lower tier returns `FeatureUnavailableInTierException`.
Set via `update-user-pool --user-pool-tier PLUS`.

## `AdvancedSecurityMode` — three modes

Lives on `UserPool.UserPoolAddOns.AdvancedSecurityMode` (nested, not top-level):

| Mode | Behavior |
|------|----------|
| `OFF` | Threat protection disabled |
| `AUDIT` | Records risk assessments; takes NO action. Data-gathering mode |
| `ENFORCED` | Records AND applies your configured risk responses |

Toggle via `update-user-pool` (NOT `set-risk-configuration`):

```
aws cognito-idp update-user-pool \
  --user-pool-id <pool-id> \
  --user-pool-add-ons AdvancedSecurityMode=ENFORCED \
  ... (re-send every other existing field — full-replace API)
```

## Compromised-credentials protection

Detects passwords on known-breached lists. Configure via `set-risk-configuration`:

```
aws cognito-idp set-risk-configuration \
  --user-pool-id <pool-id> \
  --compromised-credentials-risk-configuration \
    'Actions={EventAction=BLOCK},EventFilter=[SIGN_IN,SIGN_UP,PASSWORD_CHANGE]'
```

- `EventAction`: **`BLOCK`** (reject the auth attempt) or **`NO_ACTION`** (log only).
- `EventFilter`: any subset of `SIGN_IN | SIGN_UP | PASSWORD_CHANGE`. Defaults
  to all three when omitted.
- Omit `--client-id` for pool-wide config; include it to scope to one client.

## Adaptive authentication (risk-based MFA)

Cognito classifies each sign-in as **No Risk / Low / Medium / High**. The API
exposes **three configurable action tiers** (`LowAction` / `MediumAction` /
`HighAction`) — `No Risk` proceeds without triggering any Action.

```
aws cognito-idp set-risk-configuration \
  --user-pool-id <pool-id> \
  --account-takeover-risk-configuration '
    NotifyConfiguration={
      SourceArn=arn:aws:ses:us-east-1:<account>:identity/no-reply@example.com,
      From=no-reply@example.com
    },
    Actions={
      LowAction={EventAction=NO_ACTION,Notify=false},
      MediumAction={EventAction=MFA_IF_CONFIGURED,Notify=true},
      HighAction={EventAction=MFA_REQUIRED,Notify=true}
    }'
```

### `EventAction` — four values per tier

| Value | Behavior |
|-------|----------|
| `NO_ACTION` | Allow the sign-in |
| `MFA_IF_CONFIGURED` | Require MFA if the user has it set up; allow otherwise (**optional MFA**) |
| `MFA_REQUIRED` | Require MFA; block if user has no MFA method (**required MFA**) |
| `BLOCK` | Reject the sign-in outright |

Do NOT collapse `MFA_IF_CONFIGURED` and `MFA_REQUIRED` — they behave differently.
Typical: `Low → NO_ACTION`, `Medium → MFA_IF_CONFIGURED`, `High → MFA_REQUIRED`
or `BLOCK`.

### `NotifyConfiguration`

- **`SourceArn`** is **required** and must be a verified SES identity ARN.
- Optional: `From`, `ReplyTo`, and per-outcome message bodies (`BlockEmail`,
  `MfaEmail`, `NoActionEmail`, each with `Subject`/`HtmlBody`/`TextBody`).

## Log delivery to CloudWatch

Route threat-protection events to CloudWatch/S3/Firehose via
`set-log-delivery-configuration`:

```
aws cognito-idp set-log-delivery-configuration \
  --user-pool-id <pool-id> \
  --log-configurations '[
    {
      "EventSource": "userAuthEvents",
      "LogLevel": "INFO",
      "CloudWatchLogsConfiguration": {"LogGroupArn": "arn:aws:logs:<region>:<account>:log-group:<name>"}
    }
  ]'
```

**Enum-pair rules** (Cognito rejects mismatched pairs):

| `EventSource` | `LogLevel` | Purpose | Tier |
|---------------|------------|---------|------|
| `userAuthEvents` | `INFO` | Threat-protection sign-in events | Plus |
| `userNotification` | `ERROR` | Message-delivery errors (SMS, email) | Lite+ |

**Encrypt the target CloudWatch Logs log group with a customer-managed KMS key** —
threat-protection events contain user PII (IP addresses, user identifiers) and sign-in
risk metadata. Either set the KMS key at log-group creation, or associate one after the
fact:

```
aws logs associate-kms-key \
  --log-group-name /aws/cognito/<pool-id> \
  --kms-key-id arn:aws:kms:<region>:<account>:key/<key-id>
```

The KMS key policy must allow the `logs.<region>.amazonaws.com` service principal
`kms:Encrypt*` / `kms:Decrypt*` / `kms:GenerateDataKey*` / `kms:Describe*` scoped to
the log group ARN via `kms:EncryptionContext:aws:logs:arn`.

## Inspect current state

```
aws cognito-idp describe-user-pool --user-pool-id <pool-id>          # AdvancedSecurityMode
aws cognito-idp describe-risk-configuration --user-pool-id <pool-id> # risk config
aws cognito-idp get-log-delivery-configuration --user-pool-id <pool-id>
```

## Gotchas

- `UserPoolAddOns` block may be absent if threat protection never enabled —
  inspect defensively: `pool.get("UserPoolAddOns", {}).get("AdvancedSecurityMode")`.
- Downgrading Plus → lower tier fails while `AdvancedSecurityMode` is
  `AUDIT`/`ENFORCED`. Set to `OFF` first, then change tier.
- `set-risk-configuration` with only `UserPoolId` clears the config to defaults
  — always read-modify-write.

## Authoritative sources

- [Threat protection](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pool-settings-threat-protection.html)
- [`SetRiskConfiguration`](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_SetRiskConfiguration.html)
- [`SetLogDeliveryConfiguration`](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_SetLogDeliveryConfiguration.html)
- [Feature plans](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-sign-in-feature-plans.html)
