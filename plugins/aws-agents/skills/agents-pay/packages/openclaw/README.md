# AgentCore Payments for OpenClaw

This OpenClaw plugin performs guarded x402 v2 payments through AWS AgentCore
Payments. It exposes two runtime tools:

- `get_payment_session_status` checks an operator-provisioned session.
- `get_paid_content` pays an approved HTTPS resource and returns response
  metadata and a SHA-256 body digest, never the signed proof or paid body.

The runtime requires an existing payment manager, instrument, user, and session.
It cannot provision payment infrastructure or create replacement sessions.
Configure approved origins, recipients, networks, assets, and a positive
per-payment ceiling before enabling the payment tool.

Required configuration:

- `paymentManagerArn`, `paymentInstrumentId`, `payment_session_id`, and `userId`
- `allowedRecipients`
- Optional `allowedOrigins` and `networkPreferences`
- `allowedAssetsByNetwork` for exact network-to-asset policy
- `maxPaymentAmountAtomic`, which defaults to `100000` (0.10 USDC)

Provision infrastructure and create the bounded session outside the
model-facing runtime. Use separate administration and runtime IAM roles, and
never put CDP or Privy credentials in prompts, tool arguments, transcripts, or
plugin config.

References:

- [AgentCore Payments getting started](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments-getting-started.html)
- [AgentCore Payments IAM roles](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments-iam-roles.html)
- [x402 v2 specification](https://github.com/coinbase/x402/blob/main/specs/x402-specification-v2.md)
