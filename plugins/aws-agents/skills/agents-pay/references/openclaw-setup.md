# OpenClaw Setup

OpenClaw uses the `@aws/aws-agent-payments` package from ClawHub. Its canonical
source lives at
`plugins/aws-agents/skills/agents-pay/packages/openclaw/` in this repository.

## Install

```bash
openclaw plugins install clawhub:@aws/aws-agent-payments
```

## Configure

Add to your OpenClaw config (`~/.openclaw/config.yaml` or via `openclaw config`):

```yaml
plugins:
  agentcore-payments:
    enabled: true
    config:
      region: us-east-1
      paymentManagerArn: arn:aws:bedrock-agentcore:us-east-1:ACCOUNT:payment-manager/NAME
      paymentInstrumentId: payment-instrument-XXXX
      payment_session_id: payment-session-XXXX
      userId: your-user-id
      networkPreferences:
        - eip155:84532
      allowedOrigins:
        - "https://merchant.example"
      allowedRecipients:
        - "0xMerchantWalletAddress"
      allowedAssetsByNetwork:
        eip155:84532:
          - "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
      maxPaymentAmountAtomic: "100000"
```

The `paymentManagerArn`, `paymentInstrumentId`, `payment_session_id`, and
`userId` come from the human-run administrative setup. Configure origins,
recipients, networks, and exact asset contracts from values approved out of
band. The default `maxPaymentAmountAtomic` is `100000` (0.10 USDC with 6
decimals).

## How it works

The plugin exposes two scoped OpenClaw runtime tools only:

| Tool | What it does | Permission |
|---|---|---|
| `get_payment_session_status` | Check session budget/expiry | Read-only |
| `get_paid_content` | Pay for an approved x402 URL and return response metadata only | Spend (within pre-approved session budget) |

### Security boundaries

- **No shell access.** The agent cannot run scripts, read files, or access env vars.
- **No setup at runtime.** Payment Manager, connector, credential provider,
  instrument, and session creation happen outside the model-visible runtime.
- **No credential exposure.** Wallet provider secrets never appear in the tool
  interface. Rotate any provider credential previously entered through chat.
- **No replacement sessions.** The runtime cannot mint a fresh session. If the
  configured session expires or drains, create a new one through the trusted
  management path and update config.
- **No signed proof exposure.** The signed payment proof is attached only inside
  trusted request handling code and is never returned as tool output.
- **Trusted challenge policy.** Runtime code selects an approved offer instead
  of trusting `accepts[0]`, and enforces HTTPS, public destinations, no
  redirects, configured origin and network, exact asset, positive bounded
  amount, approved recipient, and matching resource before `ProcessPayment`.
- **x402 v2 only.** The paid replay uses the required `PAYMENT-SIGNATURE`
  header. v1 challenges fail closed.
- **Stable retries.** The AgentCore client token binds the session, resource,
  network, asset, recipient, and amount while excluding publisher-controlled
  nonces.
- **Publisher content isolation.** Paid response bodies are not returned to the
  payment-capable model context. `get_paid_content` returns status, content type,
  byte count, and SHA-256 hash only.
- **Budget enforcement.** The AgentCore service enforces `maxSpendAmount` and
  `expiryTimeInMinutes` server-side regardless of what the agent requests.

## Publish updates

See
`plugins/aws-agents/skills/agents-pay/packages/openclaw/PUBLISHING.md` in the
source repository for the build and publication workflow.
