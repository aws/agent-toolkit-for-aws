# agents-pay setup

A human provisions resources and authorizes payment sessions outside the agent Runtime. The agent can only spend an already approved session. Require AgentCore CLI v1.0.0 or later and a Python environment with `bedrock_agentcore.payments`.

## 0. Install and locate the project

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
npm install -g @aws/agentcore@latest
agentcore --version
python -c "from bedrock_agentcore.payments import PaymentManager; print('payments OK')"
```

Work from the root of an AgentCore CLI v1 project (`agentcore/agentcore.json` has `"version": 2`). If the project is v0, commit it, review `agentcore migrate`, and apply the reviewed plan using `agentcore migrate --yes`. For a project dedicated to payment resources:

```bash
agentcore create --name PaymentsProject --template empty
cd PaymentsProject
```

## 1. Choose the connector

For Coinbase, Quick Create lets the service provision provider credentials. Complete any required AWS Marketplace subscription and Coinbase authorization outside the agent conversation. For manually managed Coinbase or Stripe Privy credentials, obtain them from the provider and store each secret in a local file kept outside git. The v1 CLI accepts secret flags only as `file://<path>` or `-` for stdin; it rejects inline secrets.

## 2. Add the payment manager

```bash
agentcore add payment-manager \
  --name MyPayments \
  --network-preferences eip155:84532 \
  --no-auto-payment
```

Names start with a letter and contain only alphanumeric characters, at most 48 characters. The v1 CLI requires `--name`; the v0 bare-command wizard is gone. If the project uses skill onboarding tags, put `"agentcore:onboarding-source": "agent-toolkit-skill"` in the project's top-level `tags` object and retain existing tags.
The CLI enables auto-payment by default. This skill uses `--no-auto-payment` so spending remains behind its operator-approved session and policy checks.

## 3. Add the payment connector

For Coinbase Quick Create:

```bash
agentcore add payment-connector \
  --manager MyPayments --name Coinbase --quick-create
```

For manual Coinbase or Stripe, first add a v1 payment credential provider. Examples use file inputs for secrets:

```bash
agentcore add credentials payment \
  --name CoinbaseCredentials --provider CoinbaseCDP \
  --api-key-id <CDP_API_KEY_ID> \
  --api-key-secret file://<api-key-secret-file> \
  --wallet-secret file://<wallet-secret-file>
agentcore add payment-connector \
  --manager MyPayments --name Coinbase --credential CoinbaseCredentials
```

For Stripe Privy, the credential command uses `--provider StripePrivy`, `--app-id`, `--app-secret file://<file>`, `--authorization-private-key file://<file>`, and `--authorization-id`. Then add the connector with `--credential <name>`. The provider secrets are stored in `agentcore/.env.local` until deploy sends them to AgentCore Identity. Check that `.env.local` is ignored by git and readable only by the human operator. Do not paste secret values or file contents into an agent conversation.

## 4. Build, deploy, and discover

```bash
agentcore build
agentcore deploy --region <region>
agentcore status --json
```

The first deploy creates a `default` target in `agentcore/aws-targets.json` from the effective account and region. Check that it uses the intended account and region. For Quick Create, complete the Coinbase authorization URL reported at deploy and confirm the connector is ready. The v1 `agentcore/.cli/deployed-state.json` records the stack binding but does not store payment manager and connector IDs. Read them from `agentcore status --json`; `scripts/agents_pay_admin.py` now uses that output for automatic discovery. If discovery is unavailable, pass `--manager-arn` and `--connector-id` explicitly.

## 5. IAM: the four-role model

**Follow the official guide:**
<https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments-iam-roles.html>

AgentCore Payments defines four roles. This skill's design assumes them, and the
security properties below depend on the separation being real in your account.

| Role | Purpose | Who assumes it |
|---|---|---|
| **ControlPlaneRole** | Payment managers, connectors, credential providers | Administrator |
| **ManagementRole** | Payment **instruments and sessions**. Explicitly denied `ProcessPayment` | The human running this admin CLI |
| **ProcessPaymentRole** | Executes payments. Cannot create sessions | The agent runtime |
| **ResourceRetrievalRole** | Service role AgentCore assumes to fetch credentials | `bedrock-agentcore.amazonaws.com` |

The AWS guide states the reason directly:

> "Separating payment management from payment execution prevents a single
> compromised identity from both creating sessions with unlimited budgets and
> executing payments against those sessions."

This separation keeps payment management and execution in different trusted roles.

### Which role runs which command

| Step | Command | Role |
|---|---|---|
| 1 | `agentcore add payment-manager` / `payment-connector` / `deploy` | **ControlPlaneRole** |
| 2 | `agents_pay_admin.py init-config` | none — writes a local file only |
| 3 | `agents_pay_admin.py create-instrument` | **ManagementRole** |
| 4 | `agents_pay_admin.py new-session` | **ManagementRole** |
| 6 | the agent calling `x402_fetch` | **ProcessPaymentRole** |

### ManagementRole — for the human running the admin CLI

Note the explicit `Deny`. It is not decoration: it is what stops this role from
being usable to both mint budget and spend it.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowPaymentManagement",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:CreatePaymentInstrument",
        "bedrock-agentcore:GetPaymentInstrument",
        "bedrock-agentcore:ListPaymentInstruments",
        "bedrock-agentcore:DeletePaymentInstrument",
        "bedrock-agentcore:CreatePaymentSession",
        "bedrock-agentcore:GetPaymentSession",
        "bedrock-agentcore:ListPaymentSessions",
        "bedrock-agentcore:DeletePaymentSession"
      ],
      "Resource": [
        "arn:aws:bedrock-agentcore:*:ACCOUNT:payment-manager/*/instrument/*",
        "arn:aws:bedrock-agentcore:*:ACCOUNT:payment-manager/*/session/*"
      ]
    },
    {
      "Sid": "DenyProcessPayment",
      "Effect": "Deny",
      "Action": "bedrock-agentcore:ProcessPayment",
      "Resource": "*"
    }
  ]
}
```

### ProcessPaymentRole — for the agent runtime

`ProcessPayment` plus reads. **No session-write actions.**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowProcessPayment",
      "Effect": "Allow",
      "Action": "bedrock-agentcore:ProcessPayment",
      "Resource": ["arn:aws:bedrock-agentcore:*:ACCOUNT:payment-manager/*/session/*"]
    },
    {
      "Sid": "AllowPaymentReadOperations",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:GetPaymentInstrument",
        "bedrock-agentcore:GetPaymentInstrumentBalance",
        "bedrock-agentcore:GetPaymentSession"
      ],
      "Resource": [
        "arn:aws:bedrock-agentcore:*:ACCOUNT:payment-manager/*/instrument/*",
        "arn:aws:bedrock-agentcore:*:ACCOUNT:payment-manager/*/session/*"
      ]
    }
  ]
}
```

The AWS guide is emphatic about the combination to avoid:

> "Do not include PaymentSession *write* permissions (for example,
> `CreatePaymentSession`) and `ProcessPayment` in the same role, or the caller can
> bypass payment limits by creating new sessions with elevated budgets."

Verify after deploy:

```bash
aws iam get-role-policy --role-name <ProcessPaymentRole> --policy-name <Policy> \
  | grep -c CreatePaymentSession        # must be 0
```

A runtime `AccessDeniedException` on `CreatePaymentSession` is **the control
working**. Do not "fix" it by granting the permission.

### ResourceRetrievalRole

The service role AgentCore assumes at runtime. Created and wired by
`agentcore deploy`; it is not assigned to a human. Its trust policy must name
`bedrock-agentcore.amazonaws.com` with an `aws:SourceAccount` condition. See the
guide for the full base and per-connector permissions.

## 6. Write the payment policy

```bash
python3 scripts/agents_pay_admin.py init-config \
  --max-per-payment-usd 0.05 \
  --network eip155:84532 \
  --recipient 0xMerchantWalletAddress
```

To find a merchant's real `payTo` and amount before allowlisting, read its
challenge without paying:

```bash
curl -sD - https://<merchant-host>/<path> -o /dev/null \
  | awk '/^payment-required:/{print $2}' | base64 -d | python3 -m json.tool
```

Inspect `accepts[].payTo`, `.amount` (integer base units; USDC has 6 decimals,
so `2000` = $0.002), `.asset`, and `.network`, then allowlist deliberately with
`--recipient`. Unknown recipients are refused before signing.

If the operator deliberately accepts publisher-selected beneficiaries, replace
all `--recipient` flags with `--allow-any-recipient`. These modes are mutually
exclusive. The flag does not relax scheme, network, asset, origin/resource,
per-payment, or cumulative session limits.

Add `--origin https://host` (repeatable) only if you want to pin the agent to a
known merchant set; omitted, it may fetch any public HTTPS site.

## 7. Create the per-user instrument

One wallet for this installation. The payer identity is read from the config, where
`init-config` generated it — this skill is single-tenant, so there is nothing to
invent or keep in sync:

```bash
python3 scripts/agents_pay_admin.py create-instrument --email you@example.com
```

The manager ARN and connector ID are read from `agentcore status --json`
automatically, so run this from your AgentCore project directory. Otherwise pass
`--manager-arn` and `--connector-id` explicitly.

Add `--network-family SOLANA` for Solana; the default `ETHEREUM` covers Base and
Base Sepolia.

Run it under the **setup** role, not the runtime role. It prints the instrument ID,
the wallet address, the delegation URL, and the `export` lines for the runtime.

## 8. Delegation and funding

One-time per wallet, and **do this before creating a session.**

Both steps attach to the *wallet*, not to a session: `create_payment_session` takes
only a user, an expiry, and a budget. Sessions are time-bounded (60 minutes by
default), so minting one first and then going off to complete a browser flow and a
faucet transfer simply burns the clock — the budget can expire before the agent has
spent anything.

**Delegation** — authorize the agent to spend from the wallet:

- *Coinbase CDP*: the end user visits the `redirectUrl`, signs in, grants
  permission to the wallet address
- *Stripe Privy*: no redirect URL; use the Privy frontend SDK
  (<https://github.com/privy-io/aws-agentcore-sdk>), sign in with the end user's
  email, approve delegation

**Funding** — send testnet USDC to the wallet address via
<https://faucet.circle.com/> (Base Sepolia). Fund only what the agent may
plausibly spend: wallet balance is the backstop if every other control fails.

## 9. Approve a session and run preflight

```bash
python3 scripts/agents_pay_admin.py new-session --budget 1.00 --expiry-minutes 60

export PAYMENT_MANAGER_ARN=...   PAYMENT_INSTRUMENT_ID=...
export PAYMENT_SESSION_ID=...    PAYMENT_USER_ID=alice
export AWS_REGION=us-west-2

python3 scripts/agents_pay_admin.py preflight
python3 scripts/test_x402_policy.py
```

Keep sessions short (≤60 minutes) and budgets small. When the budget is spent, a
human runs `new-session` again — the agent cannot.

## Networks

Two distinct concepts, and mixing them up is a common setup failure:

- **network family** — used when creating the instrument (`--network-family`)
- **chain** — the CAIP-2 identifier that appears in x402 challenges and in this
  skill's `allowed_networks`

**Families (instrument creation):**

| Family | Value | Covers | Providers |
|---|---|---|---|
| Ethereum | `ETHEREUM` | Base, Base Sepolia, Ethereum mainnet | Coinbase, Stripe |
| Solana | `SOLANA` | Solana, Solana Devnet | Coinbase, Stripe |

**Chains (x402 challenges, `allowed_networks`, balance queries):**

| Chain | CAIP-2 identifier | Balance API value | Type | Providers |
|---|---|---|---|---|
| Base Sepolia | `eip155:84532` (or `base-sepolia`) | `BASE_SEPOLIA` | **Testnet** | Coinbase |
| Base | `eip155:8453` | `BASE` | Mainnet | Coinbase |
| Ethereum | `eip155:1` | `ETHEREUM` | Mainnet | Coinbase, Stripe |
| Solana | `solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp` | `SOLANA` | Mainnet | Coinbase, Stripe |
| Solana Devnet | `solana-devnet` | `SOLANA_DEVNET` | **Testnet** | Stripe |

Start on **Base Sepolia** (family `ETHEREUM`, chain `eip155:84532`) — free testnet
USDC from <https://faucet.circle.com/>. `init-config` only knows the USDC contract for
the Base chains; adding another chain means adding its exact contract to `KNOWN_USDC`
in the admin CLI, deliberately, rather than passing an address in.

## Operational monitoring

- Confirm CloudTrail records `bedrock-agentcore` calls, especially `ProcessPayment`
- Alarm on `CreatePaymentSession` by the runtime principal — it should be
  impossible, so any occurrence means the IAM split has regressed
- Alarm on repeated `ProcessPayment` failures as an abuse signal
- Review `show-config` output whenever payments start refusing unexpectedly
