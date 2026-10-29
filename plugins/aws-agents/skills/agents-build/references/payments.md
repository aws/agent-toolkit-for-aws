# payments

Add AgentCore Payments to an existing agent. This reference covers the v1 CLI provisioning path and Runtime wiring. For the detailed human operated setup and IAM role split, use the bundled `agents-pay` [setup](../../agents-pay/references/setup.md) and [operator guide](../../agents-pay/references/operator-guide.md). The SDK based payment code below remains applicable after the resources are deployed.

## When to use

- Wire a Strands or LangGraph Runtime to x402 or MPP payments.
- Add an AgentCore payment manager and connector to a v1 project.
- Debug a 402 challenge after the payment resources exist.

## Process

### Step 0: Check the CLI and project

Require `agentcore --version` at v1.0 or later. Read `agentcore/agentcore.json`; a v1 project has `"version": 2` and payment managers in `payments`. Read `agentcore/aws-targets.json` and select the deployment target, account, and region for all later commands. A v0 project must be committed and migrated first: review `agentcore migrate`, then apply the reviewed plan with `agentcore migrate --yes`. If there is no project and one is needed, use `agentcore create --name PaymentsProject --template empty`. A Strands Runtime project can instead start with `--template agent-python-strands`.

Choose the Runtime framework by reading its code and `runtimes[]` entry. The CLI does not wire the payment plugin into the Runtime source; Step 5 is still required.

### Step 1: Select provider and authenticate the operator

For Coinbase, Quick Create is the smallest v1 path. The human completes any required Marketplace subscription and Coinbase authorization. For manual Coinbase or Stripe Privy, the human uses `agentcore add credentials payment` with secret values read from files or stdin. The v1 CLI rejects inline secrets and the v0 bare-command wizard no longer applies. Keep provider credentials outside the agent conversation. See the `agents-pay` setup reference for the manual provider flags and IAM role separation.

### Step 2: Add resources

```bash
agentcore add payment-manager \
  --name MyPayments \
  --network-preferences eip155:84532 \
  --no-auto-payment
agentcore add payment-connector \
  --manager MyPayments --name Coinbase --quick-create
```

For a manual connector, replace `--quick-create` with `--credential <PaymentCredentialName>` after adding that credential. Manager names are alphanumeric, start with a letter, and have at most 48 characters; connector names can also contain underscores. Add any intended onboarding tag to the project's top-level `tags` before deploying.

### Step 3: Build and deploy

```bash
agentcore deploy --target <target>
agentcore status --target <target> --json
```

Run `agentcore build` before deploying a Quick Create connector. For a manual connector referencing a new payment credential, the first build can fail because that credential has no deployed ARN; deploy provisions it before building the stack, then `agentcore build` can run successfully.

If this is a new project with no targets, run `agentcore deploy --region <region>` to create `default`, then use `--target default`. For an existing target, use its account and region; `--region` does not change them. Coinbase Quick Create reports an authorization URL; the human completes that flow and waits for the connector to become ready. v1 payment identifiers are surfaced by `agentcore status --target <target> --json`, not the `payments[]` branch of `agentcore/.cli/deployed-state.json`. If an admin script cannot discover them, supply its `--manager-arn` and `--connector-id` flags.

### Step 5: Wire the agent

#### Step 5a: Native integration (Strands or LangGraph) — agent runs

If the project uses Strands or LangGraph, use the framework's native payments integration. This is simpler than the generic tool — no `process_payment_tool.py` needed, no `x402_fetch` registration, and the middleware/plugin automatically handles ALL tool calls (not just a dedicated payment tool).

**Strands:**

```python
import os
from strands import Agent
from strands_tools import http_request
from bedrock_agentcore.payments.integrations.config import AgentCorePaymentsPluginConfig
from bedrock_agentcore.payments.integrations.strands.plugin import AgentCorePaymentsPlugin

config = AgentCorePaymentsPluginConfig(
    payment_manager_arn=os.environ["PAYMENT_MANAGER_ARN"],
    user_id=os.environ["PAYMENT_USER_ID"],
    payment_instrument_id=os.environ["PAYMENT_INSTRUMENT_ID"],
    payment_session_id=os.environ["PAYMENT_SESSION_ID"],
    region=os.environ.get("AWS_REGION", "us-west-2"),
)
plugin = AgentCorePaymentsPlugin(config=config)
agent = Agent(
    system_prompt="You are a helpful assistant that can access paid APIs.",
    tools=[http_request],
    plugins=[plugin],
)
```

The plugin intercepts 402 responses from ANY tool, signs payment, and retries automatically. No special tool needed — the agent just uses `http_request` normally.

**LangGraph:**

```python
import os
from langchain.agents import create_agent
from bedrock_agentcore.payments.integrations.langgraph import (
    AgentCorePaymentsConfig,
    AgentCorePaymentsMiddleware,
)

config = AgentCorePaymentsConfig(
    payment_manager_arn=os.environ["PAYMENT_MANAGER_ARN"],
    user_id=os.environ["PAYMENT_USER_ID"],
    payment_instrument_id=os.environ["PAYMENT_INSTRUMENT_ID"],
    payment_session_id=os.environ["PAYMENT_SESSION_ID"],
    region=os.environ["AWS_REGION"],
)
payments = AgentCorePaymentsMiddleware(config)

agent = create_agent(
    model=model,  # the LangGraph model already configured in this project
    tools=[],  # middleware auto-registers http_request + payment query tools
    middleware=[payments],
)
```

For a dev/test Runtime that may create sessions, omit `payment_session_id` and set `auto_session=True`, `auto_session_budget="5.00"`, and `auto_session_expiry_minutes=60` on the same config. Its execution role then needs `CreatePaymentSession`; use the explicit session above with the separated production roles.

The middleware wraps ALL tool calls, detects 402 from any response format (no `PAYMENT_REQUIRED:` marker needed), signs payment, and retries. It also auto-registers an `http_request` tool and payment query tools.

**LangGraph simplifications vs the generic tool path:**

- No `process_payment_tool.py` script needed — the middleware IS the payment tool
- No special system prompt — no need to tell the model to use a specific tool for paid URLs; all tools are payment-aware
- `auto_session=True` can lazily create a session on first 402 (dev/test convenience — requires `CreatePaymentSession` IAM permission on the runtime role)
- Error recovery — optional `on_payment_error` callback for programmatic recovery (create new session, swap instrument) without the LLM seeing errors

> **Note on `auto_session`**: This creates exactly one session per middleware instance with the developer-set budget. The LLM cannot trigger or control this. In production with IAM role separation (recommended ProcessPaymentRole), the `CreatePaymentSession` call would be denied — use explicit `payment_session_id` instead. See [IAM roles for AgentCore payments](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments-iam-roles.html).

#### Step 5b: Framework-agnostic local tool (any framework) — agent runs

Payments are wired with a small local tool, not a framework-specific plugin — so the same code works in any framework.

1. **Copy [`scripts/process_payment_tool.py`](../scripts/process_payment_tool.py) into the agent project.** It exposes `x402_fetch(url, method="GET")`, which on a `402` calls the SDK's `PaymentManager.generate_payment_header` — the SDK validates the 402, selects the network, processes the payment, and builds the version-aware proof (v1 `X-PAYMENT` / v2 `PAYMENT-SIGNATURE`) — then retries with a fresh client. Base Sepolia settlement is intermittently transient (the header is valid but the paid retry still returns 402), so the tool re-runs the settle+replay flow up to `X402_MAX_PAYMENT_ATTEMPTS` times (default 5, env-overridable) before giving up. It reuses a single idempotency token across those retries, so `ProcessPayment` stays idempotent — every attempt replays the same on-chain authorization/nonce and the user is never charged twice (a retry either settles the not-yet-settled payment or, if it was already settled, reverts on-chain). It reads its config from environment variables (set in Step 8): `PAYMENT_MANAGER_ARN`, `PAYMENT_INSTRUMENT_ID`, `PAYMENT_SESSION_ID`, `PAYMENT_USER_ID`, `AWS_REGION`.

2. **Register `x402_fetch` as a tool** in the agent's framework. The tool function is identical; only the registration decorator differs:

   ```python
   # Strands
   from strands import Agent, tool
   from process_payment_tool import x402_fetch as _x402
   x402_fetch = tool(_x402)
   agent = Agent(model=..., tools=[x402_fetch], system_prompt="... use x402_fetch for paid URLs ...")
   ```

   ```python
   # LangGraph
   from langchain_core.tools import tool
   from langgraph.prebuilt import create_react_agent
   from process_payment_tool import x402_fetch as _x402
   graph = create_react_agent(model, tools=[tool(_x402)])
   ```

   ```python
   # OpenAI Agents SDK
   from agents import Agent, function_tool
   from process_payment_tool import x402_fetch as _x402
   agent = Agent(name="PaymentAgent", tools=[function_tool(_x402)], instructions="... use x402_fetch for paid URLs ...")
   ```

   For any other framework, register `x402_fetch` using that framework's tool mechanism — the function is plain Python.

The agent calls `x402_fetch` instead of a generic HTTP tool; payment is handled inside the tool. (Tell the model, via the system prompt, to use `x402_fetch` for URLs that may require payment.)

### Step 6: Provision the per-user instrument (SDK script — data plane) — human operator runs

The instrument (per-user wallet) and session (budget-bounded spend window) are data-plane resources — the v1 CLI can inspect them with `agentcore payment instrument` and `agentcore payment session`, while creation remains an SDK workflow. The human operator obtains the **user id** and **email** and runs this skill's [`scripts/setup_payment_user.py`](../scripts/setup_payment_user.py) from the AgentCore project root, using its absolute path so the CLI can find the project. Use the separate ManagementRole described in the `agents-pay` operator guide; do not give its session-creation permission to the payment-capable Runtime. Select the same target used for deployment; the script discovers the manager ARN and connector ID from `agentcore status --target <target> --json`:

```bash
python /absolute/path/to/agents-build/scripts/setup_payment_user.py \
  --user-id alice --email alice@example.com --target <target>
```

It creates the instrument (with the email in `linkedAccounts`) and prints its ID, wallet address, and delegation URL for Step 7. Create the time-limited session after delegation and funding in Step 8.
If the target contains multiple managers or the chosen manager has multiple connectors, pass the intended `--manager-arn` and `--connector-id` explicitly. The script refuses ambiguous discovery.

**LangGraph with `auto_session=True`**: Skip the manual session step below. The middleware creates a session on the first 402. The instrument is still required.

### Step 7: Delegation and funding (one-time per wallet) — developer does this

Using the `wallet_address` / `redirect_url` the script printed:

1. **Delegation** — authorize the agent to spend from the wallet.
    - **Coinbase CDP**: the end user visits `redirect_url`, logs in, and grants permissions to `wallet_address`.
    - **Stripe Privy**: Delegation requires a frontend app where the end user authenticates with Privy and approves the agent as a session signer on their wallets. Use the reference frontend at <https://github.com/privy-io/aws-agentcore-sdk>. The agent automates the mechanical parts (7a, 7c, 7f); the developer handles the two steps that touch secrets or the dashboard (7b, 7d) and the browser approval (7e). Configure the frontend for the same Privy app and authorization key used by the manual payment credential in Step 1:

      **7a. Clone and install the delegation frontend — agent runs:**

      ```bash
      git clone https://github.com/privy-io/aws-agentcore-sdk.git agentcore-privy-frontend
      cd agentcore-privy-frontend
      pnpm install
      ```

      **7b. Configure environment. The DEVELOPER runs this, not the agent.**

      In the frontend project, copy `.env.example` to `.env.local`. Set `NEXT_PUBLIC_PRIVY_APP_ID` to the App ID used with `agentcore add credentials payment --provider StripePrivy`, `PRIVY_APP_SECRET` to that app's secret, and `NEXT_PUBLIC_PRIVY_SIGNER_ID` to the same authorization ID. Get the values from the original credential inputs or the Privy Dashboard under **Configuration > App settings** and **Wallet infrastructure > Authorization keys**. Set `NEXT_PUBLIC_NETWORK_MODE=testnet` for Base Sepolia or Solana Devnet, or `mainnet` for production. The frontend does not need the authorization private key.

      Do not copy `agentcore/.env.local` into the frontend. The v1 CLI names entries after the **credential provider name** (`AGENTCORE_CREDENTIAL_<CREDENTIAL_NAME>_<FIELD>`) and encrypts secret values there; a text copy would give the frontend unusable ciphertext. The developer should enter the values directly in the frontend's local configuration without posting them to the agent.

      The `NEXT_PUBLIC_PRIVY_SIGNER_ID` is the Authorization Key ID for the same key whose private key went to the payment credential. If the app or key IDs differ, delegation can succeed while payments fail.

      **7c. Start the frontend — agent runs:**

      ```bash
      pnpm dev
      ```

      The app starts at `http://localhost:3000`. If port 3000 is occupied (e.g. by the agent's own dev server), Next.js auto-selects the next available port — **read the actual URL from the terminal output** before the next step.

      **7d. Allow the local origin in the Privy Dashboard — developer does this:**

      Privy restricts which origins may use an App ID from the browser. Unless the local origin is allowlisted, login in Step 7e fails client-side even though every credential is correct.

      In the [Privy Dashboard](https://dashboard.privy.io/apps?setting=domains&page=settings), go to **Configuration > App settings > Domains**, and under **Allowed origins** select **Web & mobile web**, then add the URL the dev server printed:

      ```
      http://localhost:3000
      ```

      Requirements (Privy matches the browser's **origin**, so anything beyond scheme + host + port is rejected):

      - **No trailing slash and no path** — `http://localhost:3000`, not `http://localhost:3000/`.
      - **The port is required** and must be the port the dev server actually bound (Step 7c). `http://localhost` alone does not match.
      - Add each port separately if the dev server moves between runs.

      > **Check what's already in the field first.** Privy's default is permissive — an app with an **empty** allowed-origins list accepts every origin, so delegation works without this step. Adding the first entry switches the app to allowlist-only:
      >
      > - **Dedicated AgentCore app**: the list is normally empty and nothing else uses the App ID, so adding `http://localhost:3000` is safe. Remember to also add the deployed origin before going to production, or the hosted frontend will break.
      > - **Shared app** with existing entries: append the localhost URL, don't replace the list. Remove it again once delegation testing is done.

      **7e. Complete delegation — developer does this in browser:**

      1. Open `http://localhost:3000` in a browser
      2. Log in with the **same email** used in the `setup_payment_user.py` `--email` flag (Step 6) — Privy creates embedded wallets for this user
      3. On the "Complete setup" screen, click **"Connect agent"**
      4. In the modal, click **"Give access"** — this calls `addSessionSigners` which registers the authorization key as a session signer on all the user's Privy embedded wallets
      5. Once the success toast appears ("Agent connected successfully"), the agent is authorized to sign transactions on behalf of this user

      After delegation succeeds, the developer can optionally fund the wallet directly from the same UI (click "Add funds" > use the Circle faucet address shown, or transfer from an external wallet).

      > **How it works under the hood:** The frontend calls Privy's `addSessionSigners` API with the `NEXT_PUBLIC_PRIVY_SIGNER_ID`. This adds the AgentCore authorization key as an approved signer on the user's embedded wallets. When AgentCore later calls `ProcessPayment`, it uses the corresponding private key to sign transactions — Privy's wallet infrastructure validates that the signer is authorized and executes the transaction.

      **7f. Verify delegation — agent can validate:**

      After the developer confirms delegation is complete, the agent can verify by calling the same check-signers endpoint the frontend uses. Obtain the Privy wallet IDs from the authenticated frontend session; the payment instrument ID and wallet address printed in Step 6 are different identifiers:

      ```bash
      curl -s -X POST http://localhost:3000/api/check-signers \
        -H "Content-Type: application/json" \
        -d '{"walletIds": ["<privy-wallet-id>"]}' | python3 -m json.tool
      ```

      Expected: `{"connected": true}`. If `false`, the developer needs to repeat step 7e.

      **Deployed alternative:** For production, deploy the frontend (e.g. to Vercel: `vercel --prod`) and direct end users to the hosted URL. The same `.env.local` values go into Vercel's environment variables settings, and the **deployed origin must be added to Allowed origins** the same way `http://localhost:3000` was in Step 7d (`https://your-app.vercel.app`, no trailing slash). Privy does not allow generic preview-deployment wildcards like `https://*.vercel.app`, so map previews to a subdomain you control if they need to work. Each end user logs in with their own email, delegates once, and is then ready for agent-initiated payments.

2. **Funding** — fund `wallet_address` on the network your target merchant settles on:
    - **x402 (Base Sepolia)**: send testnet USDC via the Circle faucet (<https://faucet.circle.com/>).
    - **MPP on Tempo Moderato** (StripePrivy instruments only): send the canonical test stablecoin **pathUSD** via the Tempo faucet (<https://tempo.xyz/developers/docs/quickstart/faucet>). AgentCore accepts only the network's canonical token — the faucet's other stablecoins (AlphaUSD/BetaUSD/ThetaUSD) are rejected with `MPP_EVM_NON_CANONICAL_USDC`. For buyer-pays challenges (`buyerPaysGasFees: true`) the wallet also needs native Tempo gas. See [MPP networks, providers, and funding](#mpp-networks-providers-and-funding).

### Step 8: Have the human operator create a session, then set env vars and test

After the end user completes delegation and funding, the human operator creates a bounded session for the **same user ID** without creating another instrument. Use the instrument ID printed in Step 6:

```bash
python /absolute/path/to/agents-build/scripts/setup_payment_user.py \
  --user-id alice --session-only --instrument-id <instrument-id> \
  --budget 5 --target <target>
```

The SDK script prints `PAYMENT_SESSION_ID` and the same instrument ID. With LangGraph `auto_session=True`, skip this command; the middleware creates the session on the first 402.

Set the tool's config from the `export` lines the Step 6 and Step 8 script runs printed (`PAYMENT_MANAGER_ARN`, `PAYMENT_INSTRUMENT_ID`, `PAYMENT_SESSION_ID`, `PAYMENT_USER_ID`, `AWS_REGION`):

```bash
export PAYMENT_MANAGER_ARN=...
export PAYMENT_INSTRUMENT_ID=...
export PAYMENT_SESSION_ID=...
export PAYMENT_USER_ID=...
export AWS_REGION=...
```

**LangGraph (Step 5a with `auto_session=True`)**: You only need these env vars:

```bash
export PAYMENT_MANAGER_ARN=...
export PAYMENT_INSTRUMENT_ID=...
export PAYMENT_USER_ID=...
export AWS_REGION=...
# PAYMENT_SESSION_ID is not needed — auto_session manages it internally
```

Run the agent and prompt it to fetch a paid endpoint:

```
Fetch https://sandbox.node4all.com/v1/x402-test and tell me what you find.
```

Run it however your agent runs — directly in your framework, or `agentcore dev` for a local server / `agentcore invoke` for the deployed runtime (set the same `PAYMENT_*` env vars on the runtime). A successful run shows `x402_fetch` hitting `402`, settling payment, and the retry returning `200`.

## The `upto` scheme and Permit2 allowance

The setup and wiring above are scheme-agnostic: the agent passes through whichever x402 scheme the merchant's `402` advertises. Most endpoints use `exact` (a fixed price known up front). Some use **`upto`**, for metered or usage-based pricing such as pay-per-inference — the agent authorizes a spending ceiling and the merchant settles the actual amount consumed, up to that ceiling. No configuration change is required to pay an `upto` endpoint.

The `upto` scheme has one additional prerequisite: it settles through the [Uniswap Permit2](https://docs.uniswap.org/contracts/permit2/overview) contract, so the payer wallet must hold a Permit2 allowance for the asset. The optional **`permit2_allowance_limit`** field is an add-on for `upto` that grants this allowance — when set, `ProcessPayment` submits the one-time on-chain `approve` before signing. Set it on the native integration config (Step 5a):

```python
config = AgentCorePaymentsPluginConfig(   # AgentCorePaymentsConfig for LangGraph
    ...,
    permit2_allowance_limit="1000000",     # decimal string, asset's smallest unit (1000000 = 1 USDC)
)
```

- A decimal string in the asset's smallest denomination. The uint256 maximum (`115792089237316195423570985008687907853269984665640564039457584007913129639935`) grants an unlimited allowance.
- Applies only to `upto`; supplying it for an `exact` payment returns a validation error.
- It broadcasts a real on-chain `approve` transaction — gas is paid from the wallet's native-token balance (not its USDC balance).
- Needed only for a wallet's first `upto` payment. `approve` sets the allowance rather than adding to it, so omit it on later calls to avoid a redundant transaction.
- Requires an SDK build whose integration config (or `generate_payment_header`) accepts `permit2_allowance_limit`.

For the generic `x402_fetch` tool (Step 5b), pass `permit2_allowance_limit="..."` to its `generate_payment_header` call when paying an `upto` endpoint.

## Debugging payments

**QuickCreate: the Coinbase authorization URL shows "Invalid request" (or does nothing):**

- The `authorizationUrl` is valid for only **10 minutes** and is **single-use** — this error means it expired, was already used, or was consumed by a link preview before you clicked it.
- **Link unfurling is the most common cause**: pasting the URL into Slack/Teams/chat (or letting the agent fetch it) fires a preview request that spends the one-time consent session. Share the URL as plain text and open it directly in a browser, once, promptly.
- Check the connector with `GetPaymentConnector` (e.g. `aws bedrock-agentcore-control get-payment-connector --payment-manager-id <id> --payment-connector-id <id> --region <target-region>`) and poll until the status is terminal: `READY` = it already succeeded (no action); `AUTHENTICATION_EXPIRED`/`AUTHENTICATION_FAILED` = the consent window lapsed or failed — delete the connector and recreate it via QuickCreate to get a fresh URL; `AWS_MARKETPLACE_SUBSCRIPTION_REQUIRED` = subscribe to "Coinbase Wallets for AgentCore Payments" then recreate (on the CLI deploy path the manager may have rolled back — inspect the deployment failure first); `CREATING`/`PENDING_AUTHENTICATION`/`PROVISIONING` = still in progress, keep polling.

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

**`CreatePaymentManager` / `CreateWorkloadIdentity` fails with `AccessDenied` even though your IAM policy grants the action:**

- The Payment Manager's underlying **WorkloadIdentity name is not the display name you supplied** — AgentCore derives it by **lowercasing** that name and appending a random suffix (e.g. `MyManager` → `mymanager-a1b2c3d4e5`). IAM authorizes on the resource **ARN**, and that ARN is built from the generated **id**, not your display name — so a policy scoped to the mixed-case display name never matches and the call is denied (ARNs are case-sensitive).
- Fix: scope the policy to the **generated id/ARN**, not the display name — either read the real id back from the `CreatePaymentManager` response (or `GetPaymentManager`) and use it verbatim, or use a suffix wildcard such as `.../workload-identity/mymanager-*`.

**ProcessPayment succeeds but merchant still returns 402:**

- **Transient on‑chain settlement failure** (common on Base Sepolia): the tool already re‑settles up to `X402_MAX_PAYMENT_ATTEMPTS` times (default 5). If still 402s, raise the cap (`export X402_MAX_PAYMENT_ATTEMPTS=8`) or retry shortly.
- **Cookie contamination**: The retry is sending cookies from the initial 402 request. Ensure you use a fresh httpx client: `httpx.Client(cookies=None).request(...)` — do NOT reuse the same client/session.
- **Wrong x402 version / header**: The merchant is x402 v2 but the proof was sent as v1 (or vice versa). v1 expects an `X-PAYMENT` header with a flat proof (top-level `scheme`/`network`); v2 expects a `PAYMENT-SIGNATURE` header where `accepted` is a top-level sibling of `payload`, and `payload` holds only `signature` + `authorization` (no top-level `scheme`/`network`). A v2 merchant that receives a v1 `X-PAYMENT` header ignores it and re-issues the same 402 — often with an empty `{}` body and no error, which is hard to diagnose. Read `x402Version` from the challenge (body or `payment-required` header) and build the matching proof.
- **Proof format mismatch (network field)**: For **v1**, the proof `network` must use the merchant's human label (e.g., `"base-sepolia"` not `"eip155:84532"`). For **v2**, the proof keeps the CAIP-2 identifier from the challenge unchanged (e.g., `"eip155:84532"`). Note: the `ProcessPayment` input always uses CAIP-2 regardless of version — only the proof presented to the merchant differs.
- **Proof expired**: The proof has a ~60 second validity window (`validBefore`). If the agent loop is slow, the proof may expire before the retry.

**ProcessPayment succeeds (PROOF_GENERATED) but merchant returns 402 with an empty `{}` body and no error:**

- The merchant is x402 **v2** and is ignoring the v1 `X-PAYMENT` header. Detect the version from the challenge (`x402Version: 2`, present in the body or the `payment-required` response header) and send a `PAYMENT-SIGNATURE` header. The v2 proof puts `accepted` (the full requirements, CAIP-2 network) as a top-level sibling of `payload`, with `payload` containing only `signature` + `authorization`. Note: if ProcessPayment returns `PROOF_GENERATED` and the proof shape is correct but the merchant still 402s, it may be a transient on-chain settlement failure — retry once before assuming a format problem.

**MPP: `ProcessPayment` fails with `ValidationException` mentioning gas/network fees:**

- The MPP challenge does not offer seller-sponsored fees (`methodDetails.feePayer` is `false` or absent), so AgentCore will not silently charge the buyer for network fees. Either set `paymentInput.mpp.buyerPaysGasFees: true` to authorize paying them from the buyer's wallet, or obtain a challenge whose seller sponsors fees.

**MPP: `ProcessPayment` fails with `ValidationException` on the challenge header:**

- `wwwAuthenticateHeaders` must contain the raw `WWW-Authenticate: Payment …` value **verbatim** and **exactly one** entry. Do not decode, reassemble, or re-encode it — altering the bytes breaks the challenge HMAC binding. If the `402` returned several `WWW-Authenticate: Payment` lines, send only the single option your instrument can satisfy.
- Confirm `paymentType` is `MPP` and the payload is under the `mpp` arm of `paymentInput` (not `cryptoX402`).

**MPP: agent gets a fresh `402` after retrying with the credential:**

- Attach the credential exactly as returned: `Authorization: Payment <token>`, using `paymentOutput.mpp.paymentCredential` verbatim (it already includes the `Payment` scheme prefix). Retry with a fresh HTTP client so cookies from the initial `402` are not resent.
- MPP credentials are single-use — a replay of an already-consumed `challenge.id` is rejected. Re-run `ProcessPayment` against the new challenge from the fresh `402`.

**MPP: `ProcessPayment` fails with `SubscriptionRequiredException` (403):**

- The account is not subscribed to the required AWS Marketplace offering. Follow the `subscriptionUrl` in the error to subscribe, then retry.

**MPP: `ProcessPayment` fails with `AccessDeniedException` (`MPP_ACCESS_NOT_ALLOWLISTED`, 403):**

- MPP is gated by a **fail-closed account allowlist** ("Access to MPP … is not enabled for this account. Contact AWS Support for access."), separate from the Marketplace subscription gate above. Request MPP access for the account through AWS Support — this is not a wiring bug, and it cannot be worked around.

**MPP on Tempo: `ProcessPayment` fails with `ValidationException` (`MPP_EVM_NON_CANONICAL_USDC`):**

- The Tempo charge currency is not the network's canonical USD stablecoin. On Moderato, fund and pay with **pathUSD** — the faucet's other test tokens (AlphaUSD/BetaUSD/ThetaUSD) are rejected.

**MPP on Tempo: `ProcessPayment` fails with `TEMPO_INSUFFICIENT_BALANCE` or a memo error:**

- `TEMPO_INSUFFICIENT_BALANCE` — the buyer wallet is underfunded for a buyer-pays charge (`eth_estimateGas` reverted). Top it up with pathUSD via the Tempo faucet (Step 7); the wallet also needs native Tempo gas for buyer-pays.
- "Tempo server memo must be exactly 32 bytes" — the merchant's `methodDetails.memo` is malformed. This is a seller-side error; do not try to fix it by editing the challenge (that breaks the HMAC binding).

**MPP on Tempo: `ProcessPayment` fails with "Tempo payments are not supported for Coinbase-managed payment instruments":**

- Tempo requires a **StripePrivy** connector/instrument. Add a StripePrivy payment credential in Step 1, then create the connector with `--credential <name>` in Step 2 and create the instrument on it — Coinbase-managed instruments cannot pay Tempo at all.

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

- The agent auth key has not been added as a session signer on the embedded wallet.
- Follow Step 7 (Stripe Privy sub-steps 7a–7e) to set up the delegation frontend, log in with the end user email provided during setup, and approve delegation for the wallet.
- Verify delegation status with the `/api/check-signers` endpoint (Step 7f).

**Stripe Privy: Delegation frontend setup issues:**

- **Login fails, the Privy modal won't open, or the browser console shows an origin/CORS or "not a valid origin for this app" error**: the local origin is not allowlisted. Add the dev server's exact URL under Privy Dashboard > Configuration > App settings > Domains > Allowed origins > Web & mobile web (Step 7d). Privy matches the browser **origin**, so `http://localhost:3000` works but `http://localhost:3000/` (trailing slash) and `http://localhost` (no port) do not. If the dev server moved off port 3000, the allowlisted port must move with it.
- **"Missing server configuration" from /api/check-signers**: One or more env vars (`NEXT_PUBLIC_PRIVY_APP_ID`, `PRIVY_APP_SECRET`, `NEXT_PUBLIC_PRIVY_SIGNER_ID`) are not set in the frontend's `.env.local`. Set them from the same Privy app and authorization key used for the payment credential in Step 1, as described in Step 7b. `cut -d= -f1` on the frontend's `.env.local` shows which keys are present without printing their values.
- **Login fails or no wallets appear**: The Privy app may not have embedded wallets enabled. In Privy Dashboard > Wallet Infrastructure, ensure embedded wallets are configured for the relevant chains (Ethereum/Solana).
- **"Give access" succeeds but payments still fail with "Wallet policy denied"**: The `NEXT_PUBLIC_PRIVY_SIGNER_ID` in the frontend may not match the Authorization ID used by the StripePrivy payment credential. Have the developer compare the IDs against the original credential input or Privy Dashboard, without exposing the secret or authorization private key to the agent.
- **User logged in with wrong email**: The email must match the one passed to `setup_payment_user.py --email`. If mismatched, the instrument points to a different Privy user's wallets. Log out, log back in with the correct email.
- **Port conflict**: If the agent's own server is on port 3000, the frontend auto-selects another port. Check the terminal output for the actual URL — and allowlist that port (Step 7d), otherwise login fails.

**None of the errors above match what you are seeing?**

- Check the **CloudTrail** logs to debug further. Every `bedrock-agentcore` control-plane and data-plane call (`CreatePaymentManager`, `CreatePaymentConnector`, `ProcessPayment`, …) is recorded there with the exact request, the authenticated caller identity, and the real `errorCode` / `errorMessage`. Find the failing call in CloudTrail (Event history, or your trail's S3 / CloudWatch Logs destination) — the underlying error and principal there usually pinpoint the permission, resource-id, or input mismatch that the surfaced error only summarizes.

## Security Considerations

- **Prefer QuickCreate for Coinbase**: QuickCreate avoids the developer handling long-lived provider secrets — you authorize through Coinbase and AgentCore Payments provisions and stores the credential provider for you, removing the plaintext-secret step that manual entry requires.
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

## MPP (Machine Payments Protocol)

MPP is the second payment protocol AgentCore Payments speaks, alongside x402. It is a protocol-neutral, HTTP-native scheme for machine-to-machine payments (an IETF-track draft; see <https://mpp.dev>). AgentCore acts on the **buyer** side: the agent hits a paid endpoint, receives an MPP challenge in a `402 Payment Required` response, and calls `ProcessPayment` to mint the credential that satisfies it — the same lifecycle as x402, over a different wire format.

### How MPP differs from x402 on the wire

x402 carries its challenge in the response **body** (`x402Version` + `accepts`) and the proof in an `X-PAYMENT` (v1) or `PAYMENT-SIGNATURE` (v2) header. MPP uses the standard HTTP auth handshake instead:

| Primitive | Direction | HTTP header | Encoding |
|---|---|---|---|
| **Challenge** | server → agent (402) | `WWW-Authenticate: Payment ...` | RFC 9110 auth-params (`id="…", realm="…", method="…", intent="…", request="<base64url>", …`) |
| **Credential** | agent → server (retry) | `Authorization: Payment <token>` | `base64url(JSON)`, no padding |
| **Receipt** | server → agent (200) | `Payment-Receipt: <token>` | `base64url(JSON)`, no padding |

Each `402` may carry **one or more** `WWW-Authenticate: Payment` header lines — one per payment option (each a distinct `method`/`intent`). The agent picks one it can satisfy and returns exactly one `Authorization: Payment` header. `method` (`tempo`, `evm`, `solana`, `stripe`, `card`, …) and `intent` (`charge`, `session`, `subscription`) are open IANA registries — MPP is method- and currency-agnostic (crypto or fiat), where x402 is USDC-only. The per-method `request` payload rides inside the challenge as an opaque base64url blob; AgentCore parses it and mints the matching proof, so you forward the challenge verbatim rather than decoding it yourself.

### The MPP ProcessPayment contract

Call the same `ProcessPayment` operation used for x402, with `paymentType` set to `MPP` and the `mpp` arm of `paymentInput`:

```jsonc
// ProcessPayment request (MPP)
{
  "paymentManagerArn": "arn:aws:bedrock-agentcore:us-west-2:111122223333:payment-manager/pm-abc123",
  "paymentSessionId": "payment-session-…",
  "paymentInstrumentId": "payment-instrument-…",
  "paymentType": "MPP",
  "paymentInput": {
    "mpp": {
      "version": "1",
      // The raw WWW-Authenticate: Payment header value(s) from the 402, passed verbatim.
      // Exactly one entry in this release (ACP fulfills a single challenge per call).
      "wwwAuthenticateHeaders": [
        "Payment id=\"qB3…\", realm=\"api.example.com\", method=\"evm\", intent=\"charge\", request=\"eyJ…\""
      ],
      // Optional. Authorizes ACP to sign when the buyer pays the blockchain (gas) fees.
      "buyerPaysGasFees": false
    }
  }
}
```

```jsonc
// ProcessPayment response (MPP) — status PROOF_GENERATED
{
  "paymentType": "MPP",
  "status": "PROOF_GENERATED",
  "paymentOutput": {
    "mpp": {
      "version": "1",
      // Echoes the id of the challenge that was paid, so you can correlate without decoding.
      "selectedPaymentId": "qB3…",
      // Ready-to-send Authorization header value: "Payment <base64url-token>".
      // Attach it verbatim and retry the original request — no assembly required.
      "paymentCredential": "Payment eyJ…"
    }
  }
}
```

Notes grounded in the API model:

- **Forward the header verbatim.** Pass the raw `WWW-Authenticate: Payment …` value(s) unchanged. AgentCore parses the auth-params itself — you do no field-mapping or base64 handling — and forwarding as-is preserves the exact bytes the challenge's HMAC binds to.
- **One challenge per call.** `wwwAuthenticateHeaders` accepts exactly one entry in this release. When a `402` offers several options, select the one the instrument can satisfy and send just that line. (It is modeled as a list so the contract can widen to multiple options later without a breaking change.)
- **`paymentCredential` is the finished `Authorization` header.** No assembly needed — attach it to the retry as `Authorization: Payment <token>`. It is a bearer-like secret; do not log it.
- **`buyerPaysGasFees` controls fee sponsorship.** A crypto challenge advertises who pays network (gas) fees via `methodDetails.feePayer`: `true` = the seller sponsors, `false`/absent = the buyer pays from their own wallet on top of the amount. Because that extra cost is not in the challenge `amount`, AgentCore will not assume the buyer accepts it — if the challenge does not offer seller-sponsored fees, it signs only when you set `buyerPaysGasFees: true`, otherwise it fails with `ValidationException`. Omit it (or `false`) for fee-sponsored challenges; it has no effect there.
- **`version`** is the MPP protocol version (a bare numeric string, e.g. `"1"`), distinct from the x402 version.

### MPP end-to-end flow

```
Agent GETs https://paid-api.example.com/data
  │
  ├─ 1. 402 Payment Required
  │     WWW-Authenticate: Payment id="qB3…", realm="api.example.com", method="evm", intent="charge", request="eyJ…"
  │
  ├─ 2. ProcessPayment(paymentType="MPP", paymentInput.mpp.wwwAuthenticateHeaders=[<that header, verbatim>])
  │     → status PROOF_GENERATED, paymentOutput.mpp.paymentCredential = "Payment eyJ…"
  │
  ├─ 3. Retry with  Authorization: Payment eyJ…   (fresh HTTP client, no cookies)
  │     → 200 OK + paid content  (optional  Payment-Receipt: <token>)
  │
  └─ 4. Return content to agent
```

### MPP networks, providers, and funding

MPP is method-agnostic, but the one crypto network AgentCore adds *beyond* the x402 chains is **Tempo** — a stablecoin chain from Stripe and Tempo, reachable **only via MPP**. Tempo never appears in an x402 challenge, so it is deliberately **not** a row in the x402 Chains table below.

| Tempo network | CAIP-2 id | Type |
|---|---|---|
| Tempo Mainnet | `eip155:4217` | Mainnet |
| Tempo Moderato | `eip155:42431` | Testnet |

- **Provider — StripePrivy only.** Tempo is not supported on Coinbase-managed instruments (`ValidationException("Tempo payments are not supported for Coinbase-managed payment instruments.")`). To pay Tempo/MPP endpoints, add a Stripe Privy payment credential and use `--credential <name>` on the connector and create the instrument on it.
- **No up-front network choice.** As with x402, you do not "target" Tempo when provisioning — AgentCore maps the MPP challenge to Tempo automatically (a `method="evm"` challenge carrying `chainId=42431` maps to Moderato). Provision once with a StripePrivy connector; the agent then pays x402 *and* Tempo/MPP merchants through the same manager/instrument/session.
- **Asset — the network's canonical stablecoin.** AgentCore validates the charge against the network's canonical USD stablecoin (`MPP_EVM_NON_CANONICAL_USDC` otherwise). On **Moderato** that canonical token is **pathUSD**; fund the wallet with pathUSD from the Tempo faucet (<https://tempo.xyz/developers/docs/quickstart/faucet>) — see Step 7.
- **Access gate.** MPP (including Tempo) is behind a fail-closed account allowlist — a first call may return `AccessDeniedException(MPP_ACCESS_NOT_ALLOWLISTED)`. Request access via AWS Support (see Debugging).

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

> **These are the x402 chains.** The table above lists chains that appear in **x402** challenges. **Tempo** (`eip155:4217` mainnet, `eip155:42431` Moderato testnet) is reachable only via **MPP**, is StripePrivy-only, and settles in the network's canonical stablecoin (pathUSD on Moderato). It is documented separately in [MPP networks, providers, and funding](#mpp-networks-providers-and-funding).

## Quality criteria

- CLI is installed via `npm install -g @aws/agentcore`, not pip
- Control plane (credential provider, manager, connector) is provisioned via the CLI; the manager non-interactively. For a Coinbase connector, **Quick Create (`--quick-create`, no secrets) is offered first**; manual secret entry is the alternative and the only path for Stripe (Privy). Only the connector step involves the developer — QuickCreate: browser authorization; Manual: entering secrets
- The `agentcore:onboarding-source: agent-toolkit-skill` tag is added to `agentcore/agentcore.json` (Step 3a) before deploy — this is mandatory, so the provisioned resources are attributable to this skill
- Data plane (instrument, session) is created via the SDK script, not hand-written code
- If the project is Strands or LangGraph, the native integration (Step 5a) is offered first as the simpler path
- The generic tool path (Step 5b) is used only for other frameworks or when the developer explicitly wants manual control
- Payments are wired via the framework-native integration (Step 5a) or the framework-agnostic `x402_fetch` tool (Step 5b)
- Both x402 and MPP merchants are payable through the same manager/connector/instrument/session and the same `ProcessPayment` API — no protocol is chosen up front
- Tempo/MPP endpoints are paid on a **StripePrivy** connector (Coinbase-managed instruments cannot pay Tempo), funded with the network's canonical stablecoin (pathUSD on Moderato via the Tempo faucet) — not the x402 Base Sepolia + Circle path
- For MPP, the raw `WWW-Authenticate: Payment` header is forwarded verbatim (one per call) and the returned `paymentCredential` is attached as `Authorization: Payment <token>` unchanged
- Credentials never pass through the agent or the chat
