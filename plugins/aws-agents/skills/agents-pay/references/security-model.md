# agents-pay security model

The threat model, and how each control is enforced. Read this before changing
anything in `scripts/` — several behaviors that look over-cautious are load-bearing.

## Scope: this is the run-time skill

Worth stating before anything else, because there is an adjacent skill that looks like
it does the same job.

| | `agents-build` → `references/payments.md` | `agents-pay` (this skill) |
|---|---|---|
| Question | "How do I give the agent I am **building** the ability to pay?" | "This agent needs to pay for this **now**" |
| When | Build time, in a product being shipped | Run time, in the session at hand |
| Wallet | One per **end user** of that product | One for this installation |
| Who approves spend | The product's own flow | The operator, at a terminal |
| Threat model here | The product's customers | **Hostile model input routed through the registered payment tools** |

That last row is why this skill exists separately. When a product mints a session per
customer through its own approval flow, the agent is a component inside a system its
author controls. When an agent spends its **operator's** money mid-task, the agent is
the thing that might be compromised, so every limit has to hold against the agent.
`auto_session=True`, while valid in build-time guidance, lets a runtime replace an
exhausted budget and is unsuitable for this skill.

Neither is wrong. They answer different questions, and `agents-build` is left untouched
by this branch.

## The gate only covers what routes through it

A boundary condition worth stating before the trust table, because it is the easiest
way to end up with none of these controls while believing you have them.

Strands and LangGraph ship AgentCore Payments integrations (`AgentCorePaymentsPlugin`,
`AgentCorePaymentsMiddleware`) that intercept `402` from **any** tool call and settle
it. They are genuinely more convenient than registering `x402_fetch`. They also sit
entirely outside this skill: payment happens inside the framework's own wrapper, so
`x402_policy.py` is never consulted.

What that costs, concretely:

| Control | Via `x402_fetch` | Via native plugin / middleware |
|---|---|---|
| Per-payment ceiling | enforced | **absent** |
| Origin allowlist and SSRF vetting | enforced | **absent** |
| Derived idempotency token | enforced | **absent** — random per call |
| Only the vetted `accepts` entry reaches the signer | enforced | **absent** |
| Proof kept out of model context | enforced | depends on the integration |
| Session creation kept off the runtime role | enforced | **`auto_session=True` requires it** |

An agent that can mint a session can replace a spent budget with a larger one, so
the per-session cap stops bounding anything.

**Do not run both paths in one process.** If the native integration is active *and*
`x402_fetch` is registered, the model chooses which one settles a given `402`, so the
gate becomes advisory. Pick one. For an agent spending an operator's money against the
open web, pick `x402_fetch`; if the native path is used anyway, at minimum pass an
explicit `payment_session_id` so budget still comes from a human.

## Trust boundaries

| Component | Trusted? | Holds credentials? | Who runs it |
|---|---|---|---|
| Operator at a terminal | Yes — the root of authority | Yes (via the CLI wizard) | Human |
| `agents_pay_admin.py` | Yes | Only transiently, from the human | Human |
| `~/.agents-pay/config.json` | Yes — the authorization record | No | Written by human, read by runtime |
| `x402_policy.py` | Yes — the decision point | No | In-process, runtime |
| `x402_fetch.py` | Yes — transport | No (proof is transient) | In-process, runtime |
| The model / agent loop | **No** | No | — |
| Publisher HTTP response | **No** — hostile input | No | — |

The model is inside the threat model, not outside it. The controls hold when hostile
model input reaches the registered payment tools. Unrestricted code execution under
the same OS identity and AWS credentials is a host compromise and needs a separate
process, container, OS account, or IAM boundary.

## Why executable controls matter

Two design rules apply throughout this skill:

1. **A control that a model can decline is not a control.** Every limit in this
   skill is evaluated in Python before signing on the sanctioned runtime path.
2. **Documentation must not claim a guarantee the code does not enforce.** Every
   claim below names the function that implements it, so the two cannot drift
   silently.

## Runtime design

| Capability | Here | Security property |
|---|---|---|
| `get_paid_content` | `x402_fetch(url)` — agent tool | Same capability, now behind the policy gate |
| `get_payment_session_status` | `payment_session_status()` — agent tool | Unchanged in spirit: read-only, cannot mint budget |
| Browser payment | `prepare_browser_payment(url)` + `attach_browser_payment(handle, url)` | The model receives an opaque single-use handle; trusted glue redeems it |
| Create a payment session | `agents_pay_admin.py new-session` — human at a TTY | A runtime that can mint sessions has no cumulative bound |
| Provision infrastructure | `agentcore` CLI wizard + `agents_pay_admin.py init-config` | Provider secrets never enter tool parameters, and setup does not exist at runtime |

The browser flow is worth stating plainly, because it is the one case where a
proof must reach a caller: the model receives a handle, never proof bytes. The
handle is single-use, expires in 90 seconds, and is bound to one origin and path,
so a handle lifted from a transcript cannot be redeemed for another resource or
redeemed twice. `attach_browser_payment` returns the real header and is therefore
for trusted glue, not for the model's tool set.

## Security controls and enforcement

| Control | Enforcement |
|---|---|
| Challenge validation | Strict schema, configured scheme and network, exact asset contract, explicit recipient mode, canonical positive amount under `max_per_payment_usd`, and resource/origin checks are enforced before signing. Conflicting `amount` and `maxAmountRequired` aliases are refused; the signer receives one version-canonical amount field. The normal mode requires `payTo` in `allowed_recipients`; the explicit `allow_any_recipient: true` mode delegates beneficiary choice to the publisher. |
| Secret handling | No script accepts a secret argument. Provider credentials go only to the `agentcore` CLI wizard; signing happens inside AgentCore Payments. `preflight` rejects credential-shaped environment variables. |
| Network protection | `assert_public_https_url()` and `assert_public_ip()` require HTTPS and reject loopback, RFC1918, link-local, metadata, multicast, reserved, unspecified, CGNAT, and v4-mapped forms. `_PinnedResolverTransport` connects to the vetted address; redirects are refused and bodies are capped. |
| Content isolation | Paid bodies are withheld from model-visible output. The runtime returns status, content type, byte count, and SHA-256 hash only; authorisation never reads content. |
| Idempotency | `derive_client_token()` hashes session, origin, path, network, asset, recipient, and amount. It excludes a publisher nonce so retries reuse the same authorisation. |
| Role separation | Session creation exists only in `agents_pay_admin.py new-session`, which refuses without a TTY and has no `--yes` flag. The human uses **ManagementRole** and the agent uses **ProcessPaymentRole** with no session writes. |
| Proof isolation | `x402_fetch` holds the proof locally for one request. The browser path returns an opaque single-use handle bound to one origin and path, and output carries a redacted receipt only. |
| Runtime surface | No provisioning or session-creation tool exists in the runtime path. |
| Reproducible installation | Runtime dependencies and version floors are documented; tests are stdlib-only. Operators requiring full reproducibility should install from a hashed lockfile. |
| Local configuration | `_atomic_write_0600()` creates a `0700` directory and `0600` file. `load_config()` checks ownership, type, symlinks, and writable parents. Runtime path resolution uses the OS account and ignores `HOME`, `AGENTS_PAY_CONFIG`, and `X402_POLICY_FILE`; file resource values win over environment fallbacks. |
| Documentation checks | This table names enforcing code; `test_x402_policy.py` asserts behaviour; `preflight` checks deployed state. |

### Limits of the controls

- **Cumulative ceiling.** A per-session budget plus human-only session
  creation bounds spend per session and forces a human into the loop between
  sessions. It is not a *service-side* cumulative ceiling across sessions — that
  requires support in AgentCore Payments, outside a skill's reach. An operator who
  approves ten sessions has authorized ten budgets.
- **Dependency pinning.** A skill folder cannot ship a Python lockfile that the
  host environment will honor. Operators wanting reproducibility should install
  from a `requirements.txt` with hashes, or `pip install --require-hashes`. The
  skill states floors; it cannot enforce the resolution.
- **DNS rebinding.** IP pinning closes the common TOCTOU window by
  dialing the vetted address. A network-level egress allowlist remains the
  stronger control for a payment-capable agent, and is recommended, not replaced.

  Implementation note worth preserving: the pin **must not** be implemented by
  temporarily replacing `socket.getaddrinfo`. That global is shared, so two
  concurrent fetches can restore or observe each other's state and a request can
  end up resolving *unpinned*, silently reopening the window. The pin therefore
  lives in the connection pool's network backend, which is per-transport.
  `test_pin_is_not_implemented_by_patching_a_global` guards the regression.
- **Same-identity code execution.** A process with the runtime's OS identity and
  AWS credentials can modify owner-writable files or call the payment SDK directly.
  Restrict the model to registered tools, or place the signer and policy behind a
  separate process, container, OS account, or IAM role.

## One config file, with a fixed runtime path

Resource identifiers and the payment policy live in one operator-owned file,
`~/.agents-pay/config.json` (`0600`, in a `0700` directory, written atomically):

```json
{
  "resources": { "payment_session_id": "ps-...", "payment_manager_arn": "arn:...", ... },
  "policy":    { "max_per_payment_usd": "0.05", "allowed_networks": ["eip155:84532"], ... }
}
```

They were separate at first, which forced the operator to hand-copy identifiers
between steps. Merging them removed that, but it also bought a control worth
naming.

**The session ID is a spending credential** — it names the budget being drawn
down. `runtime_config_path()` resolves `.agents-pay/config.json` from the OS
account and ignores `HOME`, `AGENTS_PAY_CONFIG`, and `X402_POLICY_FILE`.
`resolve_resource()` then reads the **config file first and the environment
second**, deliberately reversing the usual precedence.

Containers and Lambda may inject resource identifiers when the fixed policy file
omits them. The environment cannot select a replacement policy file. File modes
protect against other principals; unrestricted code already running as the owner
requires a stronger process, container, OS account, or IAM boundary.
*Tests: `test_runtime_ignores_environment_selected_policy_file`,
`test_runtime_config_path_ignores_home_environment`, and
`test_config_file_beats_environment`.*

## Recipient validation

The normal mode requires the payee (`payTo`) named by the publisher to match an
operator-approved entry in `allowed_recipients`. Missing or empty recipient
policy denies every payment. An operator may instead set
`allow_any_recipient: true`, explicitly delegating beneficiary choice to the
publisher. The modes are mutually exclusive, and non-boolean values fail closed.

Open-recipient mode does not relax scheme, network, exact asset, origin/resource,
per-payment, or cumulative session controls. It does remove the deterministic
beneficiary boundary, so it is a deliberate high-risk operator choice.

`RecipientValidationTests` covers unknown-recipient refusal, missing-allowlist
denial, case-insensitive matching, open-recipient acceptance, mode conflicts,
malformed values, and retention of the other policy checks.

## Origins are optional

HTTPS only, internal-address rejection, manual redirect handling, DNS-rebinding
protection, timeouts, and a strict byte limit are enforced unconditionally. An
approved domain egress policy is an additional protection for payment-capable
agents, but is not required.

So `allowed_origins` is **optional**: unset means any public HTTPS site, and a
deployment with a known merchant set can still pin it. *Test: `OptionalOriginTests`.*

## Two ceilings, not a duplicate

A reasonable objection: the session already has a budget, so why does the policy
also carry `max_per_payment_usd`?

Because they bound different things:

| Bound | Scope | Set by |
|---|---|---|
| Session budget | **Cumulative** — total spend before a human must re-approve | `new-session`, typed approval |
| `max_per_payment_usd` | **Per transaction** | the policy section |

With only the session budget, a hostile merchant returns one challenge for the
entire remaining balance and drains it in a single payment. A positive, trusted
maximum for each payment makes the per-payment bound necessary, not redundant. A
missing per-payment ceiling is a refusal, never an unbounded payment.
*Test: `test_missing_per_payment_cap_refuses_rather_than_paying_unbounded`.*

## Role separation is the real boundary

The controls in this skill are meaningful only if the IAM separation described in
the [official guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments-iam-roles.html)
holds in the account:

| Role | Holds | Must NOT hold |
|---|---|---|
| **ManagementRole** — the human | Create/Get/Delete instrument and session | `ProcessPayment` (explicit `Deny`) |
| **ProcessPaymentRole** — the agent | `ProcessPayment`, Get instrument/balance/session | Any session **write** |

**The agent must have neither the ManagementRole nor the ability to run
`agents_pay_admin.py`.** If it has both, it can mint a fresh budget whenever it
exhausts one and the per-session cap bounds nothing.

The TTY requirement on `new-session` is defence in depth, not the boundary. An
agent running as the operator's own user in an interactive terminal could still
drive it — IAM is what actually stops that, which is why the runtime role must
exclude `CreatePaymentSession`.

## Validate one document, sign another

The gate can validate a challenge perfectly and still be useless if the
*signer* is handed something else.

An x402 challenge may carry several `accepts` entries, and the terms can appear
both in the `payment-required` header and in the body. If trusted code validates
one entry but forwards the publisher's raw response to
`generate_payment_header`, the SDK may settle terms the policy never saw:

- **Ordering.** `accepts[0]` = $50 to an attacker, `accepts[1]` = $0.10 to the
  merchant. The gate approves entry 1 and reports $0.10; the signer, given both,
  settles entry 0.
- **Header/body split.** A compliant header alongside a hostile body. The gate
  reads the header and approves; the signer reads the body and authorizes a
  larger amount on a different chain. The receipt then *lies* to the operator.

Both are silent: the returned receipt reflects the approved entry, not what was
signed. A test that asserts only on the gate's return value can pass while the
exploit still works.

The fix is structural: `x402_policy` rejects conflicting amount aliases and builds
a version-canonical vetted entry. `x402_fetch` reserializes that single entry into
a fresh minimal challenge (`{"x402Version": ..., "accepts": [vetted]}`) and passes
only that, with a synthetic `content-type` header. `SignerInputTests` asserts on
the object handed to the signer, not only the gate's return value.

**Rule for anyone changing `scripts/`:** the signer must receive data that
trusted code constructed, never data a publisher supplied.

## Verification

```bash
python3 scripts/test_x402_policy.py                 # all must pass
python3 scripts/agents_pay_admin.py show-config      # confirm 0600 + contents
python3 scripts/agents_pay_admin.py preflight        # wiring + secret exposure
```

The reproducible evidence is: the test suite passing, a `show-config` transcript,
and a refusal captured against a live endpoint whose recipient is deliberately
absent from the allowlist.

## Residual risks the operator owns

- **The policy is only as tight as its allowlists.** A wildcard-ish policy (many
  recipients, high ceiling) is permitted by the code and is the operator's risk.
- **Testnet first.** Defaults target Base Sepolia. Moving to mainnet means real
  money; re-check the ceiling before switching `--network`.
- **Wallet funding is a cap of last resort.** Fund the wallet with only what the
  agent may plausibly spend. It is the final backstop if every other control fails.
- **Host or runtime-role compromise is out of scope.** An attacker who can execute
  arbitrary code as the runtime identity, change the policy as its owner, read
  process memory, or call `ProcessPayment` directly can bypass this local gate.
