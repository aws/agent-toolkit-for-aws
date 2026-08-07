# OpenClaw Setup

OpenClaw uses the `@aws/aws-agents-pay` package from ClawHub. Its canonical
source lives at
`plugins/aws-agents/skills/agents-pay/packages/openclaw/` in this repository.

## Install

```bash
openclaw plugins install clawhub:@aws/aws-agents-pay
```

## Configure

Add to your OpenClaw config (`~/.openclaw/openclaw.json` or via
`openclaw config`). Explicitly allow the installed plugin:

If payment infrastructure or a session does not exist, stop the LLM workflow.
Open a separate terminal and run the human setup from the bundled skill:

```bash
cd ~/.openclaw/extensions/aws-agents-pay/skills/agents-pay
npm install -g @aws/agentcore
agentcore add payment-manager
agentcore add payment-connector
agentcore deploy
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/agents_pay_admin.py init-config \
  --max-per-payment-usd 0.05 \
  --network eip155:84532 \
  --recipient 0xMerchantWalletAddress
python scripts/agents_pay_admin.py create-instrument --email you@example.com
python scripts/agents_pay_admin.py new-session \
  --budget 1.00 \
  --expiry-minutes 60
```

The two `agentcore add` commands must run without flags so credentials remain in
the interactive terminal. Do not paste credentials, command output, deployed
state, or generated identifiers into an LLM conversation.

Complete delegation and testnet funding before creating the session. Then edit
the OpenClaw config locally in the same terminal or a local editor:

```json
{
  "plugins": {
    "allow": ["aws-agents-pay"],
    "entries": {
      "aws-agents-pay": {
        "enabled": true,
        "config": {
          "region": "us-east-1",
          "paymentManagerArn": "arn:aws:bedrock-agentcore:us-east-1:ACCOUNT:payment-manager/NAME",
          "paymentInstrumentId": "payment-instrument-XXXX",
          "payment_session_id": "payment-session-XXXX",
          "userId": "your-user-id",
          "networkPreferences": ["eip155:84532"],
          "allowedOrigins": ["https://merchant.example"],
          "allowedRecipients": ["0xMerchantWalletAddress"],
          "allowedAssetsByNetwork": {
            "eip155:84532": [
              "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
            ]
          },
          "maxPaymentAmountAtomic": "100000"
        }
      }
    }
  }
}
```

The `paymentManagerArn`, `paymentInstrumentId`, `payment_session_id`, and
`userId` come from the human-run administrative setup. Configure origins,
recipients, networks, and exact asset contracts from values approved out of
band. To deliberately allow publisher-selected beneficiaries, replace
`allowedRecipients` with `"allowAnyRecipient": true`; the plugin rejects both
fields together. The example `maxPaymentAmountAtomic` value is `100000` (0.10
USDC with 6 decimals), and no default is supplied.

## How it works

OpenClaw executes payments through this TypeScript plugin, using
`get_paid_content`. Policy validation, SSRF controls, idempotency, proof
isolation, and merchant replay remain in TypeScript. The plugin invokes a fixed
package-relative Python helper, without a shell, only for `GetPaymentSession`
and `ProcessPayment`; the package-local `.venv` created above supplies boto3 and
the standard AWS credential chain. It does not invoke the Python `x402_fetch`
runtime. For other agent hosts, use the Python runtime described in `SKILL.md`
instead, and never enable both paths at once.

The plugin exposes two scoped OpenClaw runtime tools only:

| Tool | What it does | Permission |
|---|---|---|
| `get_payment_session_status` | Check session budget/expiry | Read-only |
| `get_paid_content` | Pay for an approved x402 URL and return response metadata only | Spend (within pre-approved session budget) |

### Security boundaries

- **No general shell access.** The agent cannot choose a command, script, path,
  or environment variable. The plugin starts only its fixed AgentCore helper
  with `shell: false`, bounded JSON, a timeout, and output limits.
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
