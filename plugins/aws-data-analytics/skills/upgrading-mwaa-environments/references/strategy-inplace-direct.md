# Direct in-place upgrade (no rehearsal — unrecommended)

UNRECOMMENDED. Upgrades your current environment in place with no test
copy. Issues are discovered only against your live environment. The same environment (its ARN/URL) is preserved; historical run data preserved via MWAA's
upgrade snapshot. Offered only as an escape hatch when the customer refuses
to stand up a test copy. Prefer the Rehearsed in-place upgrade, which tests
on a temporary copy first.

**Plan durability:** plan maintenance, self-consistency invariants, and resume
reconciliation follow [plan-materialization.md](plan-materialization.md). Save
progress after every step below - status token plus durable facts (run_ids,
ARNs, S3 versions, reasons) plus `Last updated` and `## Where we are` -
before proceeding to the next action.

## Prerequisites

- Approach recorded as `in-place-direct` in the plan.
- Upgrade path determined in the plan.
- Docker validation (Phase 6) strongly recommended, since there is no test
  copy.

## Execution Steps

### 1. Unrecommended Banner + Extra Confirmation Checkpoint

Present to the user and require explicit confirmation beyond the standard
in-place checkpoint:

WARNING: This upgrades your live environment in place with no test copy.
Compatibility issues surface only against your live environment. Rollback
options: downgrade from 3.x to 2.11.x is supported; a within-major downgrade
to a still-supported (non-EOS) version is supported; downgrade to an EOS
version is not possible (verify the current EOS list at runtime). The
Rehearsed in-place upgrade is recommended instead. Confirm to proceed with
the Direct in-place upgrade.

### 2. Run the step-by-step upgrade on your current environment

Run the step-by-step upgrade on your current environment; starting
condition: upgraded in place. The engine walks every version jump to the
target, each version jump confirmed separately. See
[upgrade-engine.md](upgrade-engine.md).

### 3. Re-check your current environment at the target version

```
aws mwaa invoke-rest-api --name <current-env> --method GET --path /health
aws mwaa invoke-rest-api --name <current-env> --method GET --path /dags \
  --query-parameters '{"limit":"100","offset":"0"}'
```

Confirm metadatabase=healthy, scheduler=healthy, and no import errors. On
failure, hand off to `debugging-mwaa-workflow`, then re-verify. `/dags`
paginates (default `limit` 100) — loop `offset` until `total_entries` (as in
discovery-preflight.md Step 1.4) so an import error on a DAG beyond the first
100 is not missed.

### 4. Test-run your current environment (REQUIRED)

Parse validation (health + no import errors from Step 3) is necessary but NOT
sufficient. Invoke **skill** `testing-mwaa-workflow` to confirm DAG execution
succeeds at the target version on your current environment.

- Invoke **skill** `testing-mwaa-workflow` with delegated mode — do NOT trigger
  DAG runs manually via the REST API (`POST /dags/{id}/dagRuns`) or poll run
  states inline. The testing skill owns triggering, polling, classification,
  and the fix loop. Prioritize batch 1 / user-specified critical DAGs first.
- Every triggered DAG must reach terminal SUCCESS or be classified as blocked
  on an infrastructure/data dependency unrelated to the Airflow version
  (NEEDS-DECISION items from the testing skill's fix loop).
- On artifact failures: fix via `debugging-mwaa-workflow` +
  `authoring-mwaa-workflow`, redeploy, retest until SUCCESS. Because the
  upgrade was in-place with no test copy, failures surface against your live
  environment — a downgrade (see Step 1 rollback options) may be
  warranted if execution is broadly broken.
- Do NOT mark the migration complete until test-run validation passes.

Record execution results in the plan under a `## Test-run results`
section (DAG ID, run_id, state, duration, and any NEEDS-DECISION items).

### 5. Mark Complete

There is no Phase 8 (no test copy to switch over or decommission). Update
the plan: status complete, approach `in-place-direct`, completion timestamp.
