# AWS Agents Pay for OpenClaw

The `@aws/aws-agents-pay` OpenClaw plugin performs guarded x402 v2 payments
through AWS AgentCore Payments. It exposes two runtime tools:

- `get_payment_session_status` checks an operator-provisioned session.
- `get_paid_content` pays an approved HTTPS resource and returns response
  metadata and a SHA-256 body digest, never the signed proof or paid body.

Install from ClawHub:

```bash
openclaw plugins install clawhub:@aws/aws-agents-pay
```

## Getting started

After installation, provision AWS resources and configure the plugin before
activation. The fastest path is to ask your agent to walk you through it:

> Ask OpenClaw: "help me set up the agents-pay skill"

This drives the bundled skill's interactive setup wizard end-to-end — it
prompts for AWS credentials, network, recipients, and spend limits, then
provisions the payment instrument and session for you.

If you'd rather run it yourself, or want to see the raw steps first, open
[`skills/agents-pay/SKILL.md`](skills/agents-pay/SKILL.md) directly (there is
no `openclaw skills read` command — use `openclaw skills info agents-pay`
once the skill is installed/staged, or just open the file). For
OpenClaw-specific configuration, see
[`skills/agents-pay/references/openclaw-setup.md`](skills/agents-pay/references/openclaw-setup.md).

The package bundles the canonical `agents-pay` skill. It guides users through
human-run setup in a separate terminal while the plugin keeps only the two
runtime payment tools model-visible.

The plugin accepts an unconfigured installation state so OpenClaw can load the
bundled skill before setup. The payment tools validate the complete trusted
configuration when invoked and fail closed while it is absent or incomplete.

The plugin keeps policy validation and paid HTTP replay in TypeScript. It uses
the package-local Python virtual environment created during setup for only
`GetPaymentSession` and `ProcessPayment`, through a fixed helper path with no
shell. This preserves the standard boto3 AWS credential chain without adding
the JavaScript AgentCore SDK to the runtime dependency graph.

The runtime requires an existing payment manager, instrument, user, and session.
It cannot provision payment infrastructure or create replacement sessions.
Configure approved origins, a recipient mode, networks, assets, and a positive
per-payment ceiling before enabling the payment tool.

Required configuration:

- `paymentManagerArn`, `paymentInstrumentId`, `payment_session_id`, and `userId`
- Exactly one recipient mode: `allowedRecipients`, or the explicit high-risk
  `allowAnyRecipient: true`
- Optional `allowedOrigins` and `networkPreferences`
- `allowedAssetsByNetwork` for exact network-to-asset policy
- `maxPaymentAmountAtomic` — **required**, no default. Set this to the maximum
  amount the agent may spend in a single payment, in the asset's smallest unit
  (e.g. `"100000"` = 0.10 USDC at 6 decimals). This is the PER-PAYMENT ceiling;
  it is not a substitute for the session budget, which caps cumulative spend.
- Optional `returnBody` (boolean, default unset/false). When true,
  `get_paid_content` returns the actual paid response body (capped at 10 KiB,
  marked `untrusted: true`) instead of metadata only. Leave this unset unless
  you have deliberately decided to accept the risk: unsanitized paid content
  may contain prompt injection aimed at the agent. See "Content isolation" in
  [`references/security-model.md`](../../references/security-model.md) for the
  full tradeoff. This is a separate, TypeScript-runtime-only setting from the
  Python `x402_fetch.py` path's `return_body` policy field — set both if you
  run both runtimes and want consistent behavior.

The manifest accepts either an unconfigured installation or the complete
configuration listed above. Partial payment configuration is rejected. Both
tools fail closed unless every required field is present in trusted plugin
settings or the protected `~/.x402/config.json` file.

`allowAnyRecipient` delegates beneficiary choice to the publisher. It is
mutually exclusive with `allowedRecipients` and does not relax origin, network,
asset, per-payment, or cumulative session limits.

## Hard boundary: sessions are human-only

Payment sessions are created **outside the agent loop** by a human operator
using the AWS CLI or console — never inside an OpenClaw conversation. The
plugin exposes no tool to create, extend, or replace a session. If a session
expires or drains, the operator must create a new one and update the config;
the agent cannot self-authorize continued spending.

This is by design: the `payment_session_id` in config is a spending credential
that names the budget being drawn down. Keeping session creation out of the
agent's reach means a compromised or manipulated agent cannot point itself at a
larger budget.

Provision infrastructure and create the bounded session outside the
model-facing runtime. Use separate administration and runtime IAM roles, and
never put CDP or Privy credentials in prompts, tool arguments, transcripts, or
plugin config.

References:

- [AgentCore Payments getting started](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments-getting-started.html)
- [AgentCore Payments IAM roles](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments-iam-roles.html)
- [x402 v2 specification](https://github.com/coinbase/x402/blob/main/specs/x402-specification-v2.md)
