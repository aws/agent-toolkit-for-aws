# AgentCore Payments

## Overview

Add AgentCore Payments to your agent — the managed service that enables microtransaction payments in AI agents to access paid APIs, MCP servers, and content via the x402 protocol.

The AWS MCP server is recommended for executing AWS commands (sandboxed execution, audit logging, observability), but is not required. If the MCP server is not available, use AWS CLI or boto3 scripts instead.

## When to Use

- Your agent encounters HTTP 402 Payment Required responses from paid endpoints
- You want your agent to autonomously pay for x402-protected content (APIs, MCP tools, paywalled sites)
- You want to establish granular budget controls at user and agent levels
- You need to set up AgentCore Payments resources from scratch
- You already have payments configured but need to wire the plugin into agent code
- Payment processing is not working as expected

Do NOT use for:

- General agent scaffolding or project creation
- Connecting to external APIs via Gateway (OpenAPI specs, Lambda, MCP servers)
- Agent deployment or infrastructure
- Non-payment related agent capabilities (memory, VPC, multi-agent)

## Input

`$ARGUMENTS` is optional. If provided, use it as context:

```
/payments                          # full setup from scratch
/payments wire                     # already have resources, need code
/payments debug                    # payments not working
/payments coinbase                 # use Coinbase connector
/payments stripe                   # use Stripe connector
```

## Process

### Step 1: Read the project context

Read the agent's entrypoint file (e.g., `main.py`, `app.py`). Detect the framework:

- `from strands import Agent` → **Strands**
- `from langgraph` or `from langchain` → **LangGraph**
- `from agents import Agent` → **OpenAI Agents SDK**
- No recognizable framework → default to the **custom tool pattern**

### Step 2: Determine the situation

**Case A — No payments configured yet**
No Payment Manager exists. Proceed to Step 3 (prerequisites) then Step 4 (resource creation).

**Case B — Payments resources exist, needs wiring**
The developer already has a Payment Manager. Skip to Step 5 (generate wiring code). Ask for their Payment Manager ARN, Instrument ID, and Session ID.

**Case C — Payments configured and wired, debugging**
Ask: "What's happening? Is the agent seeing 402 but not paying? Is ProcessPayment failing? What error do you see?"
Then diagnose using the Debugging section below.

**Case D — Developer asking about payments without a project**
Answer directly. For architecture questions, explain the x402 flow. For code questions, show the custom tool pattern.

### Step 3: Collect inputs from the developer

Before setting up payments, collect these inputs:

1. **Which payment provider?** — Coinbase CDP or Stripe Privy
2. **Which AWS region?** — must be one of: us-east-1, us-west-2, eu-central-1, ap-southeast-2
3. **AWS account ID** — the account where resources will be created
4. **AWS credentials** — the developer needs two levels of access:

   **For running the setup script** (one-time, admin-level):
   - `iam:CreateRole`, `iam:PutRolePolicy` — to create the service role
   - `bedrock-agentcore:CreatePaymentCredentialProvider` — to store provider credentials
   - `bedrock-agentcore:CreatePaymentManager`, `bedrock-agentcore:GetPaymentManager` — to create the manager
   - `bedrock-agentcore:CreatePaymentConnector` — to create the connector
   - `bedrock-agentcore:CreatePaymentInstrument` — to create the wallet
   - `bedrock-agentcore:CreatePaymentSession` — to create a session

   In practice, an **Admin** or **PowerUser** role covers all of these.

   **For running the agent** (ongoing, can be scoped down):
   - `bedrock-agentcore:ProcessPayment` — to execute payments
   - `bedrock-agentcore:GetPaymentInstrument`, `bedrock-agentcore:GetPaymentSession` — for read operations
   - `bedrock:InvokeModel` or `bedrock:InvokeModelWithResponseStream` — if using Bedrock models

   Verify credentials are active: `aws sts get-caller-identity`

5. **End user email** — the email of the person whose wallet the agent will spend from. For POC/testing, the developer's own email is fine.

Once you have answers 1-5, show the provider-specific `.env.payments` template and ask the developer to create the file and run `source .env.payments`:

   For **Coinbase CDP** (get credentials from https://portal.cdp.coinbase.com/):

   How to get these credentials:

   1. Create or log in to a Coinbase Developer Platform account and project
   2. Generate an API key (or reuse existing) — note the **API Key ID** and **API Key Secret**
   3. Generate a **Wallet Secret** (for cryptographic wallet operations like signing transactions)
   4. Under Project > Wallet > Embedded Wallets > Policies, **enable Delegated signing**

   ```bash
   # .env.payments — DO NOT COMMIT THIS FILE
   export COINBASE_API_KEY_ID=your-api-key-id-uuid-here
   export COINBASE_API_KEY_SECRET=your-base64-encoded-api-key-secret-here
   export COINBASE_WALLET_SECRET=your-base64-encoded-wallet-secret-here
   ```

   For **Stripe Privy** (get credentials from https://dashboard.privy.io/):

   How to get these credentials:

   1. Create a **dedicated** Privy app for AgentCore (do not reuse apps serving other purposes)
   2. Copy the **App ID** and **App Secret** from app settings
   3. Navigate to Wallet Infrastructure > Authorization > New Key to generate a P-256 key pair
   4. The private key is prefixed with `wallet-auth:` — **strip this prefix**, use only the raw base64 content
   5. Note the **Authorization ID** (signer ID) shown alongside the key

   ```bash
   # .env.payments — DO NOT COMMIT THIS FILE
   export AUTH_PRIVATE_KEY=your-base64-encoded-ec-private-key-here
   export AUTH_ID=your-hex-auth-id-here
   export PRIVY_APP_ID=your-privy-app-id-here
   export PRIVY_APP_SECRET=privy_app_secret_your-secret-here
   ```

   > [!WARNING]
   > For Privy: The generated private key starts with `wallet-auth:`. You MUST
   > strip this prefix. Only the raw base64 content (starting with `MIGHAgEA...`)
   > is accepted by AgentCore.

After they confirm the file exists and have run `source .env.payments`, add `.env.payments` to `.gitignore`.

> **Security:** Do NOT paste credentials directly in chat or ask the agent to read
> the `.env.payments` file. Instead, run `source .env.payments` in your terminal
> to expose the values as environment variables locally. The setup script reads
> from environment variables, not the file directly.
>
> **Production:** If needed to be stored outside of AgentCore Identity ever,
> store credentials in AWS Secrets Manager or SSM Parameter Store
> (SecureString) and retrieve them at runtime. The `.env.payments` file is for
> local development only.

### Step 4: Generate and execute the setup script

Read [setup-script.md](agentcore-payments-setup-script.md) for the full script template. Substitute the developer's inputs and execute it.

The script creates:

1. Payment Credential Provider (stores provider credentials in AgentCore Identity)
2. IAM execution role with trust policy and permissions
3. Payment Manager (waits for READY status)
4. Payment Connector
5. Payment Instrument (wallet)
6. Payment Session

### Step 5: Wire the x402 tool into the agent

Read [wiring.md](agentcore-payments-wiring.md) for framework-specific tool code. Use the pattern matching the detected framework from Step 1.

The `x402_fetch` tool:

1. Makes an HTTP request to the target URL
2. If 402, extracts the x402 challenge from body or `payment-required` header
3. Calls `ProcessPayment` to get a signed payment proof
4. Retries with the payment header (`X-PAYMENT` for v1, `PAYMENT-SIGNATURE` for v2) using a fresh HTTP client to avoid cookie contamination
5. Returns the paid content

### Step 6: Test the integration

Set environment variables (printed by setup script) and run the agent:

```bash
export PAYMENT_MANAGER_ARN="..."
export PAYMENT_INSTRUMENT_ID="..."
export PAYMENT_SESSION_ID="..."
export PAYMENT_USER_ID="..."
export AWS_REGION="..."
```

Test with:

```
Fetch the content from https://sandbox.node4all.com/v1/x402-test and tell me what you find.
```

> **Note:** This test endpoint is an x402 **v2** merchant. The `x402_fetch` tool
> detects the version from the challenge and sends a `PAYMENT-SIGNATURE` header
> with the v2 proof shape. If the agent loops on 402 here, the proof is likely
> being sent as v1 (`X-PAYMENT`) — see the Debugging section.

Expected behavior:

1. Agent calls `x402_fetch` with the URL
2. Gets 402 with x402 challenge (0.1 USDC on Base Sepolia)
3. Calls ProcessPayment → gets signed proof
4. Retries with `PAYMENT-SIGNATURE` header (v2 endpoint) → gets 200
5. Returns the content to the user

If the session has expired, create a fresh one:

```bash
export PAYMENT_SESSION_ID=$(aws bedrock-agentcore create-payment-session \
  --payment-manager-arn "$PAYMENT_MANAGER_ARN" \
  --user-id "$PAYMENT_USER_ID" \
  --expiry-time-in-minutes 60 \
  --region "$AWS_REGION" \
  --query 'paymentSession.paymentSessionId' --output text)
```

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
