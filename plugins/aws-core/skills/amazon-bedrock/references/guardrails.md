# Guardrails — Integration Modes & Configuration

**When describing guardrail capabilities, you MUST include both the filter types AND the three integration modes (guardrailConfig, guardContent, ApplyGuardrail) — users need to understand both what they can filter and how to apply filters.**

## Table of Contents

- Three Integration Modes
- PII Masking: BLOCK vs ANONYMIZE
- PII Logging Compliance Gap
- Contextual Grounding Thresholds
- Guardrail Filter Types
- Guardrail Versioning
- Integration with Agents and Knowledge Bases
- Security Considerations

## Three Integration Modes

Agents confuse these. Three distinct ways to apply guardrails:

### 1. guardrailConfig (blanket protection)

Applies guardrail to ALL messages in the Converse API call.

```json
{
  "guardrailConfig": {
    "guardrailIdentifier": "my-guardrail-id",
    "guardrailVersion": "1",
    "trace": "disabled"
  }
}
```

> ⚠️ **trace**: Use `"enabled"` only for debugging — it exposes original PII/harmful content that triggered filters in the API response. Treat the entire response as sensitive data if enabled. See Constraints below.

**Constraints:**

- You MUST set `"trace": "disabled"` in production guardrail configurations. Trace output returns full guardrail assessment details in the API response, including the original text that triggered filters (PII, harmful content) via the `"match"` field in `sensitiveInformationPolicy` and `wordPolicy`.
- You MUST warn the user if trace is enabled in a production context — this is a compliance risk for HIPAA/GDPR workloads.
- If trace is enabled for debugging, You MUST treat the entire API response as sensitive data — do not log it without encryption or access controls.

Refer to the latest [AWS documentation on testing guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-test.html) for trace output format details.

**Use when**: You want every message (user input + model output) evaluated. Most common mode.

**Streaming (`ConverseStream`)**: The `guardrailConfig` field accepts a `GuardrailStreamConfiguration` type which includes the same fields plus `streamProcessingMode`:

- `sync` — Guardrail evaluates chunks before delivering to user. Adds latency but guarantees no policy-violating content is streamed.
- `async` — Chunks stream immediately while guardrail evaluates in the background. No latency impact but **inappropriate content including PII, harmful content, and policy violations will be delivered to the end user before the guardrail can intervene**. Additionally, **guardrails do NOT support PII masking/anonymization in async mode** — PII will pass through unmasked. You MUST NOT use async streaming mode for PII-sensitive or compliance-critical workloads (HIPAA/GDPR).

Refer to the latest AWS documentation on Bedrock ConverseStream guardrail configuration.

### 2. guardContent blocks (selective evaluation)

Wraps specific content in `guardContent` blocks so the guardrail evaluates only that content. When `guardContent` blocks are present, most filter types (content filters, denied topics, PII filters, contextual grounding) evaluate **only** the content inside `guardContent` blocks. However, some filters (word filters) still evaluate all content regardless of `guardContent` boundaries. If no `guardContent` blocks exist in the request, the guardrail evaluates everything.

```json
{
  "messages": [{
    "role": "user",
    "content": [
      {"text": "System context not evaluated by guardrail"},
      {"guardContent": {"text": {"text": "User input to evaluate"}}}
    ]
  }]
}
```

For contextual grounding checks, add `qualifiers` (`"grounding_source"` or `"query"`):

```json
{"guardContent": {"text": {"text": "Source document text", "qualifiers": ["grounding_source"]}}}
```

**Constraints:**

- You MUST wrap ALL untrusted content in `guardContent` blocks — not just user input. In agentic and RAG workloads, tool results and retrieved context can contain adversarial content (indirect prompt injection). Adding a `guardContent` block around user input alone causes most filter types to skip evaluation of tool results and retrieved context, creating a false sense of security.
- You MUST NOT assume content outside `guardContent` blocks is completely unguarded — the behavior is filter-type-dependent. Word filters still evaluate all content; content filters, denied topics, PII filters, and contextual grounding respect `guardContent` boundaries.
- You MUST include a `guardContent` block in the system prompt if you want the guardrail to evaluate it — system prompts are never evaluated unless they contain their own `guardContent` block.

Refer to the latest [AWS documentation on using guardrails with the Converse API](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-converse-api.html) for the full behavior matrix.

**Use when**: You need granular control over which content blocks are evaluated — e.g., to exclude trusted system prompts while still wrapping all untrusted content (user input, tool results, retrieved context).

### 3. ApplyGuardrail standalone API

Evaluate content without model invocation. Separate API call.

Apply standalone: `aws bedrock-runtime apply-guardrail --guardrail-identifier <id> --guardrail-version <version> --source INPUT --content '[{"text":{"text":"<content-to-evaluate>"}}]'`

**Use when**: Pre-screening content before sending to model, batch evaluation, or applying guardrails outside of Converse API flow.

### Decision guide

| Scenario | Mode |
|----------|------|
| Protect all conversations | `guardrailConfig` |
| Granular control — exclude trusted system prompts, wrap all untrusted content | `guardContent` blocks |
| Pre-screen before model call | `ApplyGuardrail` API |
| Batch content evaluation | `ApplyGuardrail` API |

## PII Masking: BLOCK vs ANONYMIZE

Two actions per PII type — agents confuse these:

| Action | Behavior | Use When |
|--------|----------|----------|
| `BLOCK` | Reject entire response if PII detected | Zero-tolerance for PII leakage |
| `ANONYMIZE` | Replace PII with placeholder (e.g., `{CREDIT_DEBIT_CARD_NUMBER}`) and return response | Need response but with PII redacted |

Configure per PII type — you can BLOCK credit cards but ANONYMIZE email addresses.

## PII Logging Compliance Gap

**CRITICAL for HIPAA/GDPR workloads:**

Guardrails PII masking only applies to the **API response**. The original unmasked content — including credit card numbers, SSNs, and other PII — is still logged **in plain text** to CloudWatch Logs when model invocation logging is enabled.

**Remediation:**

- You MUST encrypt CloudWatch Logs with a KMS key: `aws logs associate-kms-key --log-group-name <log-group> --kms-key-id <kms-key-arn>`. See [Encrypt log data in CloudWatch Logs](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/encrypt-log-data-kms.html)
- You MUST ensure log groups are not publicly accessible
- You MUST restrict log access with IAM policies (least privilege)
- You SHOULD use Amazon Macie for automated PII detection in S3-exported logs
- If exporting logs to S3: You MUST enable SSE-KMS encryption on the log bucket, enable S3 bucket versioning for audit trail, block all public access, and restrict bucket policies with `aws:SourceAccount` condition keys
- You SHOULD configure CloudWatch Logs retention period appropriate for compliance requirements (GDPR requires data minimization — PII should not be retained indefinitely)
- You SHOULD consider disabling model invocation logging for sensitive workloads

## Contextual Grounding Thresholds

Prevents hallucination by checking model response against source documents. Two thresholds:

| Threshold | What It Checks | Impact |
|-----------|---------------|--------|
| Grounding threshold | How closely response matches source documents | Too strict → blocks legitimate responses. Too loose → passes hallucinations. |
| Relevance threshold | How relevant response is to the user query | Too strict → blocks tangential but useful answers. Too loose → passes off-topic responses. |

**Starting values**: Begin with 0.7 for both. Tune based on evaluation:

- If legitimate responses are blocked → lower the threshold
- If hallucinated responses pass → raise the threshold
- Refer to the latest AWS documentation on Bedrock contextual grounding for current configuration options

## Guardrail Filter Types

**Filter types** (refer to the latest AWS documentation on Bedrock guardrails configuration for current setup):

- Content filters (hate, insults, sexual, violence, misconduct, prompt attack)
- **Denied topics** — custom topic definitions that block specific subjects (e.g., "do not discuss competitor products"). Bedrock-specific: you define topics with example phrases and the guardrail blocks matching content.
- Word filters and managed word lists
- PII filters (see BLOCK vs ANONYMIZE above)
- Regex filters for custom patterns
- Contextual grounding (see thresholds above)
- **Automated Reasoning checks** — validates model response accuracy against logical rules, detects hallucinations, and suggests corrections. Refer to the latest AWS documentation on Bedrock guardrails automated reasoning for setup.

## Guardrail Versioning

- `DRAFT` version: mutable, for testing only
- Numbered versions (`1`, `2`, ...): immutable snapshots
- You MUST pin a numbered version in production — DRAFT can change without notice
- You MUST NOT use DRAFT version in production guardrail configurations — DRAFT is mutable and can be modified without warning, causing silent behavior changes
- Create a new version after any configuration change: `aws bedrock create-guardrail-version --guardrail-identifier <id>`

## Integration with Agents and Knowledge Bases

**With Agents**: Specify guardrail ID and version when creating the agent. The guardrail applies to all agent interactions automatically.

**Constraints:**

- You MUST specify both `guardrailIdentifier` and `guardrailVersion` in the `guardrailConfiguration` — omitting either causes the guardrail to not be applied (silent failure)
- You MUST use a numbered version, not DRAFT, for production agents

**With Knowledge Bases**: Add `guardrailConfiguration` to `RetrieveAndGenerate` calls. The guardrail evaluates both the retrieved context and the generated response.

**Constraints:**

- You MUST include `guardrailConfiguration` with both `guardrailId` and `guardrailVersion` in the `RetrieveAndGenerate` request — the guardrail is not applied by default

Refer to the latest AWS documentation on Bedrock guardrails integration with agents and knowledge bases for current integration steps.

## Security Considerations

These are guardrail-specific security controls. For general Bedrock security (IAM roles, Secrets Manager, confused deputy protection), see the parent skill's Security Considerations section.

### Encrypt guardrail configuration with customer-managed KMS key

Guardrail configurations contain sensitive policy definitions (denied topics, PII filter rules, custom regex patterns). Encrypt with a customer-managed KMS key for regulated workloads:

`aws bedrock create-guardrail --name <name> --kms-key-id <kms-key-arn> ...`

**Constraints:**

- For HIPAA/GDPR workloads, You MUST encrypt guardrails with a customer-managed KMS key — AWS-managed keys do not satisfy customer-managed encryption requirements in most compliance frameworks
- KMS permissions required: guardrail creators need `kms:Decrypt`, `kms:GenerateDataKey`, `kms:DescribeKey`, `kms:CreateGrant`; guardrail users (inference callers) need `kms:Decrypt`
- You SHOULD encrypt guardrails with a customer-managed KMS key even for non-regulated workloads as defense-in-depth

Refer to the latest [AWS documentation on guardrail KMS encryption](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-permissions-kms.html) for key policy examples.

### Enforce guardrail usage via IAM condition keys

Without enforcement, developers can bypass guardrails by omitting `guardrailConfig` from API calls. Use the `bedrock:GuardrailIdentifier` condition key to deny inference requests that don't include the required guardrail:

```json
{
    "Effect": "Deny",
    "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
    "Resource": ["arn:aws:bedrock:<region>::foundation-model/*"],
    "Condition": {
        "StringNotEquals": {
            "bedrock:GuardrailIdentifier": "arn:aws:bedrock:<region>:<account-id>:guardrail/<guardrail-id>:<version>"
        }
    }
}
```

**Constraints:**

- You MUST recommend IAM enforcement via `bedrock:GuardrailIdentifier` condition key or account/org-level enforcement when setting up guardrails for production workloads — without enforcement, guardrails are trivially bypassable
- This applies to Converse, ConverseStream, InvokeModel, and InvokeModelWithResponseStream

**Limitations:** Users can bypass guardrail on input via input tags (but guardrail always applies on output), and the guardrail must be in the same account as the IAM role for condition key enforcement.

For account-wide or organization-wide enforcement, use `PutEnforcedGuardrailConfiguration` (account-level) or AWS Organizations Amazon Bedrock policies (org-level). These enforce guardrails on ALL inference calls without relying on developers to include `guardrailConfig`. Refer to the latest [AWS documentation on guardrail IAM enforcement](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-permissions-id.html) and [guardrail enforcements](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-enforcements.html).

### Audit guardrail configuration changes with CloudTrail

All guardrail management operations (`CreateGuardrail`, `UpdateGuardrail`, `DeleteGuardrail`, `CreateGuardrailVersion`) are logged as CloudTrail management events by default. For guardrail data events (`ApplyGuardrail`), configure advanced event selectors with resource type `AWS::Bedrock::Guardrail`. Amazon GuardDuty can detect suspicious activity such as removing guardrails. Set up CloudWatch alarms on guardrail configuration changes to detect unauthorized weakening of protections. Refer to the latest [AWS documentation on Bedrock CloudTrail logging](https://docs.aws.amazon.com/bedrock/latest/userguide/logging-using-cloudtrail.html).

### Cross-account guardrail access

AWS supports cross-account guardrail usage via resource-based policies (RBPs) — attach an RBP granting `bedrock:ApplyGuardrail` to the guardrail, scoped by `aws:PrincipalOrgID` or `aws:PrincipalOrgPaths`. However, IAM condition key enforcement (`bedrock:GuardrailIdentifier`) requires the guardrail to be in the same account as the calling IAM role. For organization-wide enforcement across accounts, use AWS Organizations Amazon Bedrock policies rather than per-account IAM condition keys. Refer to the latest [AWS documentation on guardrail resource-based policies](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-resource-based-policies.html).
