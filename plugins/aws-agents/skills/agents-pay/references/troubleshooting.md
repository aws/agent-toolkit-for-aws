# agents-pay troubleshooting

Run Python commands from the virtual environment created during setup:

```bash
source .venv/bin/activate
```

Two different situations, and it matters which one you are in:

- **A refusal** — trusted code declined to pay. The control worked. Fix the
  policy (deliberately) or accept the refusal.
- **A failure** — something is misconfigured or broken. Fix the wiring.

`x402_fetch` never raises into the agent loop; it returns JSON. `refused: true`
means a policy decision, not a bug.

> **For agents reading this:** a refusal is not an obstacle to route around. Do
> not retry unchanged, do not fetch the URL with another tool, and do not press
> the user to raise a limit so you can continue. Report the reason and stop.

## Refusals

### "No payment option in this challenge satisfies the configured policy"

The catch-all refusal. It is uniform on purpose: naming the failed field would
let a hostile publisher iterate challenges until the message changed, mapping
your policy. Diagnose locally instead.

```bash
# 1. What is the merchant actually asking for?
curl -sD - https://<host>/<path> -o /dev/null \
  | awk '/^payment-required:/{print $2}' | base64 -d | python3 -m json.tool

# 2. What does the policy allow?
python3 scripts/agents_pay_admin.py show-config
```

Compare, in this order:

| Check | Challenge field | Policy key |
|---|---|---|
| Recipient | `accepts[].payTo` | `allowed_recipients` |
| Amount | `accepts[].amount` (base units) | `max_per_payment_usd` |
| Network | `accepts[].network` | `allowed_networks` |
| Asset | `accepts[].asset` | `allowed_assets[network]` |
| Scheme | `accepts[].scheme` | `allowed_schemes` |

Amounts are integer base units and USDC has 6 decimals: `2000` = $0.002,
`500000` = $0.50. A cap of `0.001` refuses a `2000` challenge — that is correct
arithmetic, not a bug.

To confirm which rule fired, evaluate the real challenge directly:

```bash
python3 - <<'PY'
import base64, json, httpx, sys
sys.path.insert(0, "scripts")
import x402_policy as pol
url = "https://<host>/<path>"
r = httpx.get(url, timeout=15)
ch = json.loads(base64.b64decode(r.headers["payment-required"]))
print(json.dumps(ch["accepts"], indent=2))
try:
    print("AUTHORIZED:", pol.authorize_payment(url, ch))
except pol.PolicyError as e:
    print("REFUSED:", e)
PY
```

Then widen the policy only if the merchant's values are genuinely expected.
Re-run `init-config --force` with the corrected allowlists — never hand-edit
mode or ownership.

### "Origin ... is not in the configured allowed_origins"

The host is not allowlisted. Add it with `--origin https://host` (scheme + host,
no path, no trailing slash). Note the default HTTPS port is normalized away, so
`https://host:443` and `https://host` are the same origin.

### "Only https:// payment URLs are allowed"

Plain HTTP, `file://`, and other schemes are refused. Payment traffic must be
encrypted; there is no override.

### "Payment URL resolves to a non-public address"

The hostname resolved to loopback, RFC1918, link-local, metadata (169.254.x.x),
multicast, reserved, unspecified, or CGNAT space. This is the SSRF guard. If a
legitimate merchant trips it, the merchant is not internet-reachable and is not a
valid payment target from this agent.

### "No payment policy at ..."

There is no permissive default — payments are refused until a policy exists:

```bash
python scripts/agents_pay_admin.py init-config \
  --max-per-payment-usd 0.05 \
  --recipient 0xMerchantWalletAddress
```

### "... has mode -rw-rw-r--; expected 0600" / "is a symlink"

The policy file is a security control, so a file others can write, or a symlink,
is treated as no policy at all. Fail-closed by design:

```bash
chmod 600 ~/.agents-pay/config.json
```

If it is a symlink, replace it with a real file. If it is not owned by you,
investigate before "fixing" it — something wrote it as another user.

### "Payment policy allows no recipients" / recipient modes are mutually exclusive

An empty allowlist denies everything. Absent keys deny rather than allow; there
is no implicit wildcard. Re-run `init-config` with at least one `--recipient`,
or deliberately use `--allow-any-recipient` instead. Never combine the two
modes. Add `--origin` only when you want to pin the merchant host set.

## Failures

### "PAYMENT_MANAGER_ARN is not set" (or INSTRUMENT/SESSION/USER)

Runtime identifiers are missing. Run `preflight` to see which:

```bash
python3 scripts/agents_pay_admin.py preflight
```

Manager ARN and connector ID come from
`agentcore/.cli/deployed-state.json`; the session ID from `new-session`.

### "bedrock-agentcore with payments support is not installed"

```bash
python -m pip install --upgrade 'bedrock-agentcore>=1.19.0'
python -c "from bedrock_agentcore.payments import PaymentManager; print('OK')"
```

### "Response exceeded N bytes"

The body passed `X402_MAX_BODY_BYTES` (default 256 KiB) and was not buffered
further — a memory-exhaustion guard. Raise it deliberately if a merchant is
legitimately large:

```bash
export X402_MAX_BODY_BYTES=1048576
```

### Content withheld: `"omitted": true`

The response was not `application/json`, `text/plain`, `text/markdown`, or
`text/csv`. HTML is withheld by length because it is a much richer injection and
rendering surface. If you need HTML, fetch and summarize it in a separate context
that has no payment tool — do not widen the allowed types in a payment-capable
context.

### `ConnectError` during the payment flow

Usually TLS trust, not the payment path. Check:

```bash
python3 -c "import ssl; print(ssl.get_default_verify_paths().cafile)"
python3 -c "import certifi; print(certifi.where())"
```

`x402_fetch` prefers certifi's CA bundle when present, because some interpreters
(notably mise-managed Pythons) have no system CA file. Verification is never
disabled — install `certifi` rather than working around it.

### 30x response instead of content

Redirects are never followed: a redirect after a 402 can move a signed proof to
another origin. Point the agent at the final URL instead.

### ProcessPayment errors from the service

| Message | Meaning | Action |
|---|---|---|
| `Payment session not found` | Session invalid or deleted | Human runs `new-session` |
| `PaymentSessionExpired` | Past `expiry_time_in_minutes` | Human runs `new-session` |
| `Payment instrument not found` / `does not belong to user` | Instrument/user mismatch | Confirm `PAYMENT_USER_ID` matches the instrument's user |
| `Payment connector is not active` | Still provisioning, or deleted | Check status; recreate if needed |
| `Network mismatch` | Challenge chain ≠ instrument family | `ETHEREUM` covers Base/Base Sepolia; `SOLANA` covers Solana |
| `Wallet does not have a USDC balance` | Unfunded wallet | Fund via <https://faucet.circle.com/> |
| `Failed to obtain resource payment token` | Service role lacks token-vault/secrets access | Fix role; allow ~15s for IAM propagation |
| `Failed to assume payment execution role` | Trust policy wrong | Must trust `bedrock-agentcore.amazonaws.com` with the right `aws:SourceAccount` |
| `Delegated signing grant is not active` | End user has not delegated | Complete the `redirectUrl` (Coinbase) or Privy SDK flow |
| `Delegated signing is not enabled` | CDP project setting off | Portal → Wallet → Embedded Wallets → Policies → enable |
| `AccessDeniedException` on `CreatePaymentSession` | Runtime tried to mint a session | **Expected and correct.** Sessions are human-only |

### A payment went through that the policy should have refused

Almost always: something other than `x402_fetch` settled it. The gate is only in the
path for calls that route through this skill's tool.

Check whether a framework-native integration is active:

```bash
grep -rn 'AgentCorePaymentsPlugin\|AgentCorePaymentsMiddleware\|payments.integrations' .
```

If either is registered, payment happens inside the framework and
`x402_policy.py` is never consulted — no ceiling, no origin check, no derived token.
Remove it and register `x402_fetch`, or accept that the controls do not apply. Running
both means the model picks which one settles a given `402`.

Also confirm the runtime role really lacks session-write permission, since
`auto_session=True` needs it:

```bash
aws iam get-role-policy --role-name <ProcessPaymentRole> --policy-name <Policy> \
  | grep -c CreatePaymentSession        # must be 0
```

### Provider-specific errors

#### Coinbase CDP

| Message | Cause | Fix |
|---|---|---|
| `Delegated signing is not enabled` | Project setting off | portal.cdp.coinbase.com → Project → Wallet → Embedded Wallets → Policies → enable Delegated signing |
| `Delegated signing grant is not active` / `Delegation not completed` | End user has not delegated | Have them visit the `redirectUrl` from `create-instrument`, sign in, grant access to the wallet address |

#### Stripe Privy

| Message | Cause | Fix |
|---|---|---|
| `Privy credentials are invalid` | Wrong App ID or App Secret in the credential provider | Re-check both in the Privy dashboard and recreate the connector |
| `Privy appId is invalid or missing` | `appId` wrong in the credential provider | Correct it in the dashboard, recreate |
| `Privy signing key is invalid or expired` | Authorization key rotated or expired | Generate a new P-256 pair (Wallet Infrastructure → Authorization), **strip the `wallet-auth:` prefix**, keep the raw base64 |
| `Wallet policy denied the transaction` | A Privy wallet policy is blocking it | Review amount, recipient, and frequency limits in the dashboard |
| `The linked account data is invalid` | Malformed email in `linkedAccounts` | Re-create the instrument with a valid address |
| `Rate limited by Privy` | Privy API throttling | Back off and retry |
| `Delegation not completed` | Agent key not added as a wallet signer | Use the [Privy frontend SDK](https://github.com/privy-io/aws-agentcore-sdk), sign in with the end user's email, approve delegation |

Privy has no `redirectUrl`: delegation goes through the frontend SDK, not a hosted
page. If `create-instrument` printed no delegation URL, that is expected on Privy and
not a failure.

That last row is worth restating: a runtime `AccessDeniedException` on
`CreatePaymentSession` is the control working, not a misconfiguration. Do not
"fix" it by granting the permission.

### Method not allowed

`GET` and `HEAD` only. A body-bearing verb (`POST`, `PUT`, `PATCH`) is refused: the
policy gate validates the URL, not a request body, so allowing one would let the agent
send agent-chosen data to an arbitrary origin. If a paid API genuinely requires `POST`,
that call belongs in code you control,
not behind this tool.

### Paid but the merchant still returns 402

The tool already replays this automatically up to `X402_MAX_PAYMENT_ATTEMPTS` times
(default 5, clamped 1–10) because testnet settlement is intermittently slow. If you see
`"attempts": 5` with `"paid": false`, all five replays still got 402 — the payment is
not lost and was not doubled, since the same authorization was replayed each time.
Retry shortly, or raise the cap:

```bash
export X402_MAX_PAYMENT_ATTEMPTS=8
```

The retry reuses the same derived `client_token`, so re-attempting replays the
*same* authorization rather than paying twice. Verify with:

```bash
python3 scripts/test_x402_policy.py -k IdempotencyTests
```

If it persists, the merchant's settlement is lagging (common on testnets) or its
x402 version handling differs. Confirm `x402Version` in the challenge and retry
shortly. Never bypass the tool to "just fetch it" — that is how a double payment
happens.

## Health check

```bash
python3 scripts/test_x402_policy.py                  # all must pass
python3 scripts/agents_pay_admin.py show-config      # 0600, owned by you
python3 scripts/agents_pay_admin.py preflight        # wiring + no stray secrets
aws iam get-role-policy --role-name <RuntimeRole> --policy-name <P> \
  | grep -c CreatePaymentSession                     # must be 0
```
