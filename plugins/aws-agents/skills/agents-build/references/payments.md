# payments

Add AgentCore Payments to your agent — the managed service that lets your agent pay for x402-protected APIs, MCP tools, and web content via microtransactions (Coinbase CDP, Stripe Privy).

The control-plane resources (payment manager, connector, credential provider) are provisioned with the AgentCore **CLI**. The per-user data-plane resources (instrument, session) are created with the AgentCore **SDK** (a provided script). Payments are wired into the agent with a small **framework-agnostic local tool** (`scripts/x402_payment_tool.py`) — so this works with Strands, LangGraph, OpenAI Agents SDK, or any Python framework, in the AgentCore Runtime or on any other host.

## When to use

- You want your agent to autonomously pay for x402-protected content (APIs, MCP tools, paywalled sites)
- A tool call returns `402 Payment Required` and you want it settled and retried automatically
- You have a payment manager and need to wire payments into your agent code
- You want budget controls on what the agent can spend
- Payment processing isn't working as expected

Do NOT use this skill for:

- Connecting to non-paid external tools/APIs via Gateway → use `agents-connect`
- Inbound auth (who can call your agent) → use `agents-harden`
- General agent scaffolding or project creation
- Non-payment related agent capabilities (memory, VPC, multi-agent)

## Input

`$ARGUMENTS` is optional: `/payments`, `/payments wire`, `/payments debug`, `/payments coinbase`, `/payments stripe`.

## Process

**Execution model — minimize human stops.** Run the steps yourself, in order, without pausing between them. There are only **two** points that require the developer; pause at these and resume automatically once the developer confirms:

- **Step 3b (connector credentials)** — the developer runs the connector command (it involves their secrets). Present it, then wait for them to confirm it's done.
- **Step 7 (delegation + funding)** — the developer authorizes the wallet and funds it (browser + faucet). Surface the instructions, then wait.

Everything else — Steps 0–3a, **4 (deploy), 5 (wire), 6 (instrument/session), 8 (set env + test)** — you run automatically. After the developer confirms 3b, ask them for the **user id** and **email** for the first wallet (Step 6 needs them), then immediately continue through 4 → 5 → 6 (and present Step 7) without asking permission for each. After they confirm 7, run Step 8. Do not stop after every step.

### Step 0: Install / verify the AgentCore CLI

The CLI is the **npm** package `@aws/agentcore` (Node.js 20+). It is NOT a pip package — do not `pip install` it.

```bash
agentcore --version        # need >= 0.20.0 (payment commands are preview, added in 0.20.x)
# if missing or older:
npm install -g @aws/agentcore
```

### Step 1: Have an AgentCore project (for CLI provisioning)

The CLI provisions payment resources into a project (`agentcore/agentcore.json`).

- **Project exists**: read `agentcore/agentcore.json` — check the `payments` array and the `runtimes` array (framework).
- **No project**: scaffold one (don't call `--help`; run it directly). Non-interactive:

  ```bash
  agentcore create --project-name <ProjectName> --name <AgentName> --framework Strands --defaults
  ```

  `--project-name` and `--name` are both required non-interactively (`--name` is the agent/resource name; without it the CLI drops to the interactive wizard). Project name: start with a letter, alphanumeric, ≤23 chars, no underscores. `--defaults` = Python + Bedrock, no memory; or run `agentcore create` for the interactive wizard. A project is only needed to provision the payment resources via the CLI — the local payment tool (Step 5) works in any agent, framework, or host.

### Step 2: Determine the situation

- **Case A — nothing configured**: proceed to Step 3.
- **Case B — manager/connector exist, needs wiring**: skip to Step 5.
- **Case C — wired, debugging**: ask what's failing, then use the Debugging section.
- **Case D — developer asking about payments without a project** (architecture, flow explanation): explain the x402 end‑to‑end flow (see **How x402 Payment Works** section), and ask whether they want to set up payments (→ proceed to Step 3) or need wiring help (→ Step 5).

### Step 3: Provision the payment manager and connector (CLI — control plane)

**3a. Payment manager — no secrets, run it directly (non-interactive).** The agent can run this for the developer:

```bash
agentcore add payment-manager \
--name <ManagerName> \
--network-preferences eip155:84532
```

`eip155:84532` is Base Sepolia (testnet). Names: alphanumeric + underscores, ≤48 chars, start with a letter.

**3b. Payment connector — needs provider credentials. The DEVELOPER runs this, not the agent.** The agent presents the prerequisites and the command below, but must NOT execute it or handle the credentials. This single command creates the credential provider and the connector. The CLI writes the provider secrets in **plaintext to `agentcore/.env.local`** and records the credential locally; `agentcore deploy` (Step 4) then uploads them to **AgentCore Identity** (`agentcore.json` keeps only a reference). The provider secrets are used only here — nothing later reuses them.

**Before running — get your provider credentials** (do this first; the connector command needs them):

- **Coinbase CDP** (<https://portal.cdp.coinbase.com/>):
    1. Create or log in to a Coinbase Developer Platform account and project
    2. Generate an API key (or reuse existing) — note the **API Key ID** and **API Key Secret**
    3. Generate a **Wallet Secret** (for cryptographic wallet operations like signing transactions)
    4. Under Project > Wallet > Embedded Wallets > Policies, **enable Delegated signing** (required)
- **Stripe Privy** (<https://dashboard.privy.io/>):
    1. Create a **dedicated** Privy app for AgentCore (do not reuse apps serving other purposes)
    2. Copy the **App ID** and **App Secret** from app settings
    3. Navigate to Wallet Infrastructure > Authorization > New Key to generate a P-256 key pair
    4. The private key is prefixed with `wallet-auth:` — **strip this prefix**, use only the raw base64 content (starting `MIGHAgEA...`)
    5. Note the **Authorization ID** (signer ID) shown alongside the key

Recommended — interactive wizard. Run the command with **no flags** (the secrets never appear in the command, shell history, or process list; the CLI still writes them to `agentcore/.env.local` either way — see the security note below). Passing `--manager`/`--name`/`--provider` does NOT trigger the wizard — those flags switch the CLI to non-interactive mode and it then requires every secret flag too, failing with "Missing required options" otherwise:

```bash
agentcore add payment-connector
# the wizard prompts for everything interactively — manager, connector name, provider, then the secrets:
#   CoinbaseCDP : API Key ID, API Key Secret, Wallet Secret
#   StripePrivy : App ID, App Secret, Authorization Private Key, Authorization ID
```

Non-interactive alternative (CI/scripted) — pass the secrets as flags. These land in shell history and the process list, so prefer the wizard for local setup:

```bash
# Coinbase CDP (dummy values — replace with your own)
agentcore add payment-connector --manager <ManagerName> --name <ConnectorName> --provider CoinbaseCDP \
--api-key-id 11111111-2222-3333-4444-555555555555 \
--api-key-secret cdp_sk_EXAMPLEexampleEXAMPLEexampleEXAMPLE0000 \
--wallet-secret  cdp_wallet_EXAMPLEexampleEXAMPLEexample1111
# Stripe Privy (dummy values — replace with your own)
agentcore add payment-connector --manager <ManagerName> --name <ConnectorName> --provider StripePrivy \
--app-id clxxxxxxxxxxxxxxxxxxxxxxxx \
--app-secret privy_sk_EXAMPLEexampleEXAMPLEexample2222 \
--authorization-private-key MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBHkwEXAMPLE... \
--authorization-id ezzzzzzzzzzzzzzzzzzzzzzzz
```

> **Wizard vs flags:** The flags `--manager`, `--name`, and `--provider` are marked `[non-interactive]` — if you provide any of them, the CLI switches to **non-interactive mode** and expects **all required secrets as flags**. Running it with those three flags but omitting the secrets errors with missing-required-flags rather than dropping back to the wizard. For the interactive wizard, run the command with no flags: `agentcore add payment-connector`. Then wait for the developer to confirm it's done.

Security:

- **`agentcore/.env.local` holds the provider secrets in plaintext.** The CLI writes it when the connector is added (wizard or flags) and uploads it to AgentCore Identity at `agentcore deploy`. Ensure it is gitignored — the Python scaffold's default `.gitignore` only lists `.env`, so add `.env.local` (or `.env.*`). The agent must not read `agentcore/.env.local`.
- The agent presents the command but never runs it or handles the credentials; never paste credentials into chat.

### Step 4: Deploy (create the resources) — agent runs

```bash
agentcore deploy -y
```

`agentcore deploy` provisions the project's resources to your AWS account: the payment manager/connector via the AgentCore control plane, and supporting IAM (the `Payment<Name>ProcessPaymentRole`) and any runtime via a CloudFormation stack (CDK). After deploy, the manager ARN, connector ID, and role ARN are written to `agentcore/.cli/deployed-state.json`. On CLI 0.20.x these live under `targets.<target>.resources.payments[]` (`managerArn`, `connectors[].connectorId`, `processPaymentRoleArn`); the Step 6 script reads this shape automatically.

### Step 5: Wire the agent (framework-agnostic local tool) — agent runs

Payments are wired with a small local tool, not a framework-specific plugin — so the same code works in any framework.

1. **Copy [`scripts/x402_payment_tool.py`](../scripts/x402_payment_tool.py) into the agent project.** It exposes `x402_fetch(url, method="GET")`, which on a `402` calls the SDK's `PaymentManager.generate_payment_header` — the SDK validates the 402, selects the network, processes the payment, and builds the version-aware proof (v1 `X-PAYMENT` / v2 `PAYMENT-SIGNATURE`) — then retries with a fresh client. Base Sepolia settlement is intermittently transient (the header is valid but the paid retry still returns 402), so the tool re-runs the settle+replay flow up to `X402_MAX_PAYMENT_ATTEMPTS` times (default 5, env-overridable) before giving up. It reuses a single idempotency token across those retries, so `ProcessPayment` stays idempotent — every attempt replays the same on-chain authorization/nonce and the user is never charged twice (a retry either settles the not-yet-settled payment or, if it was already settled, reverts on-chain). It reads its config from environment variables (set in Step 8): `PAYMENT_MANAGER_ARN`, `PAYMENT_INSTRUMENT_ID`, `PAYMENT_SESSION_ID`, `PAYMENT_USER_ID`, `AWS_REGION`.

2. **Register `x402_fetch` as a tool** in the agent's framework. The tool function is identical; only the registration decorator differs:

   ```python
   # Strands
   from strands import Agent, tool
   from x402_payment_tool import x402_fetch as _x402
   x402_fetch = tool(_x402)
   agent = Agent(model=..., tools=[x402_fetch], system_prompt="... use x402_fetch for paid URLs ...")
   ```

   ```python
   # LangGraph
   from langchain_core.tools import tool
   from langgraph.prebuilt import create_react_agent
   from x402_payment_tool import x402_fetch as _x402
   graph = create_react_agent(model, tools=[tool(_x402)])
   ```

   ```python
   # OpenAI Agents SDK
   from agents import Agent, function_tool
   from x402_payment_tool import x402_fetch as _x402
   agent = Agent(name="PaymentAgent", tools=[function_tool(_x402)], instructions="... use x402_fetch for paid URLs ...")
   ```

   For any other framework, register `x402_fetch` using that framework's tool mechanism — the function is plain Python.

The agent calls `x402_fetch` instead of a generic HTTP tool; payment is handled inside the tool. (Tell the model, via the system prompt, to use `x402_fetch` for URLs that may require payment.)

### Step 6: Provision the per-user instrument and session (SDK script — data plane) — agent runs

The instrument (per-user wallet) and session (budget-bounded spend window) are data-plane resources — there is no CLI command for them. First ask the developer for the **user id** and **email** to provision the wallet for (if not already collected after Step 3b). Then run the provided script [`scripts/setup_payment_user.py`](../scripts/setup_payment_user.py) once per user. It auto-reads the manager ARN/connector ID from `deployed-state.json` (or accepts `--manager-arn`/`--connector-id`):

```bash
python scripts/setup_payment_user.py --user-id alice --email alice@example.com --budget 5
```

It creates the instrument (with the email in `linkedAccounts`) and a budget-bounded session, then prints the `export` lines for `PAYMENT_INSTRUMENT_ID` / `PAYMENT_SESSION_ID` / `PAYMENT_USER_ID` (used in Step 8), plus the `wallet_address` and `redirect_url` (used in Step 7). The script is the canonical data-plane path — do not hand-write the SDK calls.

### Step 7: Delegation and funding (one-time per wallet) — developer does this

Using the `wallet_address` / `redirect_url` the script printed:

1. **Delegation** — authorize the agent to spend from the wallet.
    - **Coinbase CDP**: the end user visits `redirect_url`, logs in, and grants permissions to `wallet_address`.
    - **Stripe Privy**: no `redirect_url`; use the Privy frontend SDK (<https://github.com/privy-io/aws-agentcore-sdk>), log in with the end user's email, approve delegation.

2. **Funding** — send testnet USDC to `wallet_address` via the Circle faucet (<https://faucet.circle.com/>), Base Sepolia.

### Step 8: Set env vars and test — agent runs

Set the tool's config from the `export` lines the Step 6 script printed — it emits all of them (`PAYMENT_MANAGER_ARN`, `PAYMENT_INSTRUMENT_ID`, `PAYMENT_SESSION_ID`, `PAYMENT_USER_ID`, `AWS_REGION`), so just copy them into the agent's environment:

```bash
export PAYMENT_MANAGER_ARN=...      # all five printed by setup_payment_user.py
export PAYMENT_INSTRUMENT_ID=...
export PAYMENT_SESSION_ID=...
export PAYMENT_USER_ID=...
export AWS_REGION=...
```

Run the agent and prompt it to fetch a paid endpoint:

```
Fetch https://sandbox.node4all.com/v1/x402-test and tell me what you find.
```

Run it however your agent runs — directly in your framework, or `agentcore dev` for a local server / `agentcore invoke` for the deployed runtime (set the same `PAYMENT_*` env vars on the runtime). A successful run shows `x402_fetch` hitting `402`, settling payment, and the retry returning `200`.

## Debugging payments

**Agent sees 402 but does not pay:**

1. Verify `PAYMENT_MANAGER_ARN` env var is set and not None
2. Check that the agent is using `x402_fetch` tool (not a generic `http_request`)
3. Verify the x402 challenge is present in either the response body (`x402Version` + `accepts` fields) or the `payment-required` header

**ProcessPayment fails with "Failed to obtain resource payment token":**

- The IAM service role is missing permissions. Ensure it has `GetResourcePaymentToken` on the token-vault and `secretsmanager:GetSecretValue` on the secrets.
- Wait 15+ seconds after creating the role before calling ProcessPayment (IAM propagation).

**ProcessPayment fails with "Failed to obtain workload access token":**

- The service role is missing `GetWorkloadAccessToken` permission on the workload-identity-directory resources.

**ProcessPayment fails with "Failed to assume payment execution role":**

- The service role's trust policy is incorrect. Ensure it trusts `bedrock-agentcore.amazonaws.com` with the correct `aws:SourceAccount` condition.
- Verify the role ARN passed to the Payment Manager matches the actual role.

**ProcessPayment succeeds but merchant still returns 402:**

- **Transient on‑chain settlement failure** (common on Base Sepolia): the tool already re‑settles up to `X402_MAX_PAYMENT_ATTEMPTS` times (default 5). If still 402s, raise the cap (`export X402_MAX_PAYMENT_ATTEMPTS=8`) or retry shortly.
- **Cookie contamination**: The retry is sending cookies from the initial 402 request. Ensure you use a fresh httpx client: `httpx.Client(cookies=None).request(...)` — do NOT reuse the same client/session.
- **Wrong x402 version / header**: The merchant is x402 v2 but the proof was sent as v1 (or vice versa). v1 expects an `X-PAYMENT` header with a flat proof (top-level `scheme`/`network`); v2 expects a `PAYMENT-SIGNATURE` header where `accepted` is a top-level sibling of `payload`, and `payload` holds only `signature` + `authorization` (no top-level `scheme`/`network`). A v2 merchant that receives a v1 `X-PAYMENT` header ignores it and re-issues the same 402 — often with an empty `{}` body and no error, which is hard to diagnose. Read `x402Version` from the challenge (body or `payment-required` header) and build the matching proof.
- **Proof format mismatch (network field)**: For **v1**, the proof `network` must use the merchant's human label (e.g., `"base-sepolia"` not `"eip155:84532"`). For **v2**, the proof keeps the CAIP-2 identifier from the challenge unchanged (e.g., `"eip155:84532"`). Note: the `ProcessPayment` input always uses CAIP-2 regardless of version — only the proof presented to the merchant differs.
- **Proof expired**: The proof has a ~60 second validity window (`validBefore`). If the agent loop is slow, the proof may expire before the retry.

**ProcessPayment succeeds (PROOF_GENERATED) but merchant returns 402 with an empty `{}` body and no error:**

- The merchant is x402 **v2** and is ignoring the v1 `X-PAYMENT` header. Detect the version from the challenge (`x402Version: 2`, present in the body or the `payment-required` response header) and send a `PAYMENT-SIGNATURE` header. The v2 proof puts `accepted` (the full requirements, CAIP-2 network) as a top-level sibling of `payload`, with `payload` containing only `signature` + `authorization`. Note: if ProcessPayment returns `PROOF_GENERATED` and the proof shape is correct but the merchant still 402s, it may be a transient on-chain settlement failure — retry once before assuming a format problem.

**ProcessPayment fails with "Payment session not found":**

- The session ID is invalid or the session was deleted. Create a new session.
- Ensure the `paymentManagerArn` in the session creation matches the one used in ProcessPayment.

**ProcessPayment fails with "PaymentSessionExpired":**

- Payment sessions are time-bounded. Create a fresh session with `expiryTimeInMinutes`.

**ProcessPayment fails with "Payment instrument not found" or "does not belong to user":**

- Verify the instrument ID is correct and belongs to the same Payment Manager.
- Check that the `userId` passed to ProcessPayment matches the `userId` used when the instrument was created.

**ProcessPayment fails with "Payment connector is not active":**

- The connector may still be provisioning. Check its status and wait.
- If the connector was deleted or deactivated, create a new one.

**ProcessPayment fails with "Network mismatch":**

- The x402 challenge specifies a network that does not match the instrument's network.
- Instruments created with `network: "ETHEREUM"` support Base, Base Sepolia, and Ethereum chains.
- Instruments created with `network: "SOLANA"` support Solana and Solana Devnet chains.

**ProcessPayment fails with "Payment asset not supported USDC token address":**

- The USDC contract address in the x402 challenge does not match the expected address for that network.
- Base Sepolia USDC: `0x036CbD53842c5426634e7929541eC2318f3dCF7e`
- Only USDC is supported.

**ProcessPayment fails with "Wallet does not have a USDC balance":**

- The wallet has no USDC on the specified chain.
- Fund via Circle faucet (testnet): https://faucet.circle.com/
- For mainnet: the end user must fund the wallet directly.

**Coinbase: "Delegated signing grant is not active":**

- The end user has not completed the delegation step.
- Redirect them to the `redirectUrl` returned during instrument creation (Coinbase Hub).
- They must log in and grant permissions to the wallet.

**Coinbase: "Delegated signing is not enabled":**

- The Coinbase CDP project does not have delegated signing enabled.
- Go to portal.cdp.coinbase.com > Project > Wallet > Embedded Wallets > Policies > Enable Delegated signing.

**Stripe Privy: "Privy credentials are invalid":**

- The App ID or App Secret stored in the credential provider is wrong.
- Verify in Privy Dashboard that the credentials match.
- Recreate the credential provider with the correct values.

**Stripe Privy: "Privy appId is invalid or missing":**

- The `appId` in the credential provider configuration is incorrect.
- Check Privy Dashboard for the correct App ID.

**Stripe Privy: "Privy signing key is invalid or expired":**

- The Authorization Private Key or Authorization ID is invalid or has expired.
- Generate a new P-256 key pair in Privy Dashboard > Wallet Infrastructure > Authorization.
- Remember to strip the `wallet-auth:` prefix from the private key.
- Update the credential provider with the new key.

**Stripe Privy: "Wallet policy denied the transaction":**

- A wallet policy configured in Privy is blocking the transaction.
- Review wallet policy settings in Privy Dashboard.
- Check if the transaction amount, recipient, or frequency exceeds policy limits.

**Stripe Privy: "The linked account data is invalid":**

- The email or phone number used in `linkedAccounts` when creating the instrument is malformed.
- Verify the email format is valid.

**Stripe Privy: "Rate limited by Privy":**

- The Privy API is rate limiting your requests.
- Back off and retry. Check Privy's rate limits documentation.

**ProcessPayment fails with "Payment amount exceeds maximum":**

- The x402 challenge requests more than the maximum allowed per transaction.
- Check the amount in the challenge and verify your session budget allows it.

**ProcessPayment fails with "Rate exceeded":**

- Too many API calls. Back off and retry after a few seconds.

**Coinbase: "Delegation not completed":**

- The end user has not granted the agent permission to spend from their wallet.
- Visit the `redirectUrl` returned during instrument creation, log in, and grant permissions.

**Stripe Privy: "Delegation not completed":**

- The agent auth key has not been added as a signer on the embedded wallet.
- Set up a frontend using the Privy frontend SDK (https://github.com/privy-io/aws-agentcore-sdk), log in with the end user email provided during setup, and approve delegation for the wallet.

## Security Considerations

- **Credential rotation**: Rotate payment provider credentials periodically. Recreate the credential provider with updated values.
- **Budget/spend limits**: Use Payment Session `expiryTimeInMinutes` and per-session budget controls to prevent runaway payments.
- **Audit logging**: Verify CloudTrail is logging all `bedrock-agentcore` API calls, especially `ProcessPayment`. For production, set up a CloudWatch alarm for failed payment attempts as a potential abuse indicator.
- **SSRF mitigation**: The `x402_fetch` tool enforces HTTPS-only and blocks private IP ranges to prevent fetching internal endpoints.
- **Least privilege**: The IAM service role should only have the minimum permissions required (token-vault, workload-identity, secrets access).
- **Session expiry**: Keep payment sessions short-lived (60 minutes or less). Create fresh sessions per user interaction rather than reusing long-lived ones.
- **Encryption in transit**: All payment requests must use HTTPS. The `x402_fetch` tool rejects non-HTTPS URLs.

For comprehensive security guidance, see the [AgentCore Security documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/security.html).

## How x402 Payment Works (End-to-End)

```
Agent calls x402_fetch("https://paid-api.example.com/data")
  │
  ├─ 1. HTTP GET → 402 Payment Required
  │     Body: {"x402Version": 1, "accepts": [{"scheme": "exact", "network": "base-sepolia", ...}]}
  │
  ├─ 2. Extract x402 challenge
  │
  ├─ 3. ProcessPayment(paymentManagerArn, instrumentId, sessionId, challenge)
  │     → Returns signed proof (signature + authorization)
  │
  ├─ 4. Build payment header (X-PAYMENT for v1, PAYMENT-SIGNATURE for v2)
  │
  ├─ 5. Retry with payment header (fresh HTTP client, no cookies)
  │     → 200 OK + paid content
  │
  └─ 6. Return content to agent
```

## Supported Networks

Two concepts: **network** (blockchain family, used when creating instruments) and **chain** (specific chain, used in x402 challenges and balance queries).

**Networks (for instrument creation):**

| Network | Instrument Value | Providers |
|---|---|---|
| Ethereum (includes Base, Base Sepolia) | `ETHEREUM` | Coinbase, Stripe |
| Solana (includes Solana Devnet) | `SOLANA` | Coinbase, Stripe |

**Chains (in x402 challenges and balance queries):**

| Chain | Identifier (x402) | Balance API value | Type | Provider |
|---|---|---|---|---|
| Base Sepolia | `base-sepolia` or `eip155:84532` | `BASE_SEPOLIA` | Testnet | Coinbase |
| Base | `eip155:8453` | `BASE` | Mainnet | Coinbase |
| Ethereum Mainnet | `eip155:1` | `ETHEREUM` | Mainnet | Coinbase, Stripe |
| Solana Mainnet | `solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp` | `SOLANA` | Mainnet | Coinbase, Stripe |
| Solana Devnet | `solana-devnet` | `SOLANA_DEVNET` | Testnet | Stripe |

For testing, start with **Base Sepolia** (network: `ETHEREUM`, chain: `BASE_SEPOLIA`) — free testnet tokens from https://faucet.circle.com/.

## Quality criteria

- CLI is installed via `npm install -g @aws/agentcore`, not pip
- Control plane (credential provider, manager, connector) is provisioned via the CLI; the manager non-interactively, only the connector's credential entry involves the developer
- Data plane (instrument, session) is created via the SDK script, not hand-written code
- Payments are wired via the framework-agnostic `x402_fetch` tool, so any framework works
- Credentials never pass through the agent or the chat
