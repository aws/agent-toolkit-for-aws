# Heroku live-discovery fixtures (replay mode)

Canned Heroku CLI outputs for testing the `heroku-to-aws` live-discovery path
(`discover-live-capture.md` → `discover-live.md` → `discover-assemble.md`) without
a Heroku account. The fake account is deliberately small but exercises every
designed-for behavior:

- **acme-web** — production app: 2× Standard-2X web + 1× Standard-1X worker,
  Postgres `standard-2` (42.3 GB — large enough to matter for migration-tool
  selection), Redis `premium-0` (HA + TLS), Papertrail, one custom domain, and a
  config var list whose keys imply an AI workload (`OPENAI_API_KEY`).
- **acme-staging** — small staging app on `essential-0`.
- **acme-data-team** — a team app the captured account cannot read: every per-app
  capture is `failed` with a 403 in `manifest.json`. Expected result:
  `discovery_status: "discovery_failed"`, confidence `reduced`, run continues.
- **kafka** capture is `skipped` (plugin not installed) — expected to be a
  warning, never a halt.
- `spaces.json` is empty — the common startup case.

## How to replay

**Scenario A — live-only (no Terraform):**

1. Create a scratch directory containing NO `.tf` files.
2. Create `.migration/0715-1820/` and copy `live-capture/` into it.
3. Invoke the heroku-to-aws skill ("migrate my Heroku app to AWS").
4. The Discover phase's source precondition passes via the manifest; the `live`
   fragment parses the captures. Expect an inventory with `discovery_sources:
   ["live"]`, 2 successful apps + 1 failed, and no `drift` key.

**Scenario B — live + Terraform (drift exercise):**

1. As above, but also copy `workspace-terraform/heroku.tf` into the scratch
   directory root.
2. `heroku.tf` is deliberately stale — each divergence is commented with the
   merge rule it exercises (config conflicts, plan change, terraform-only,
   live-only, scaled-to-zero gap-fill).
3. Check the assembled `heroku-resource-inventory.json` against
   `expected-drift.json` — machine-checkable via
   `python3 check_expected_drift.py <run-dir>` (exits non-zero on any failed
   assertion, including secret-hygiene checks for config-var values).

**Scenario C — Estimate baseline from live prices (no billing data):**

1. Create a scratch directory with `.migration/0715-1820/` containing the three
   artifacts from `seed-estimate/` (`heroku-resource-inventory.json`,
   `preferences.json`, `aws-design.json`) plus `seed-estimate/.phase-status.json`
   (discover/clarify/design completed, estimate in progress).
2. Invoke the heroku-to-aws skill and resume the run — the Estimate phase starts.
3. The inventory has NO `billing_profile`, but its live-discovered add-ons carry
   `config.monthly_price_usd`. Expect a `current_costs.source:
   "live_prices_plus_cache"` baseline of exactly **$352/month** (add-ons $220
   exact + $0 scheduler from cache + dynos $132 from cache), the mandatory
   derived-baseline caveat, and a full `cost_comparison` +
   `migration_cost_considerations` — the comparison must NOT be gated on billing
   data.
4. Check the produced `estimation-infra.json` against `expected-estimate.json` —
   machine-checkable via `python3 check_expected_estimate.py <run-dir>`.

**What a run must never produce** (from either scenario):

- Config var values anywhere (fixture keys like `STRIPE_SECRET_KEY` are key
  NAMES; if a value shows up, the keys-only rule broke)
- Clustering fields (`cluster_id`, `edges`, `dependencies`, ...)
- A halt due to the 403 app or the skipped kafka capture

## Regenerating / extending

Captures follow the exact command allowlist in `discover-live-capture.md` Step 3
(same filenames, `.out` extension for text captures). If you add a capture type,
add its row to the allowlist first, then the fixture, then extend
`expected-drift.json`. All IDs, names, and emails are synthetic.
