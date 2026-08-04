# OpenClaw Setup

OpenClaw uses the `@aws/aws-agent-payments` plugin from ClawHub. The plugin
source lives in this repo at [`../packages/openclaw/`](../packages/openclaw/).

## Install

```bash
openclaw plugins install clawhub:@aws/aws-agent-payments
```

## Configure

Add to your OpenClaw config (`~/.openclaw/config.yaml` or via `openclaw config`):

```yaml
plugins:
  x402-payments:
    enabled: true
    config:
      region: us-east-1
      paymentManagerArn: arn:aws:bedrock-agentcore:us-east-1:ACCOUNT:payment-manager/NAME
      paymentInstrumentId: payment-instrument-XXXX
      payment_session_id: payment-session-XXXX
      userId: your-user-id
      networkPreferences:
        - eip155:84532
      allowedRecipients:
        - "0xMerchantWalletAddress"
      allowedAssets:
        - "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
      maxPaymentAmountAtomic: "100000"
```

The `paymentManagerArn`, `paymentInstrumentId`, `payment_session_id`, and
`userId` come from the provisioning steps (Steps 3-6 in the main SKILL.md) or
from `setup_payment_user.py` output. Configure `allowedRecipients` with merchant
wallets that the user has approved out of band. The default `maxPaymentAmountAtomic`
is `100000` (0.10 USDC with 6 decimals).

## How it works

The plugin runs as an isolated MCP server inside OpenClaw. The agent interacts
through two scoped runtime tool calls only:

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
- **Trusted challenge policy.** Runtime code enforces HTTPS, public destinations,
  configured network, exact asset, positive bounded amount, approved recipient,
  and resource origin before calling `ProcessPayment`.
- **Publisher content isolation.** Paid response bodies are not returned to the
  payment-capable model context. `get_paid_content` returns status, content type,
  byte count, and SHA-256 hash only.
- **Budget enforcement.** The AgentCore service enforces `maxSpendAmount` and
  `expiryTimeInMinutes` server-side regardless of what the agent requests.

### The `payments-aware-browse` skill

OpenClaw also ships a companion skill (`payments-aware-browse`) that teaches the
agent the protocol: check pre-approved session → pay approved resource → return
metadata. Use a separate no-payment/no-network analysis path if content
summarisation is required.

## Publish updates

See [`../packages/openclaw/PUBLISHING.md`](../packages/openclaw/PUBLISHING.md) for
the build and publish workflow.
