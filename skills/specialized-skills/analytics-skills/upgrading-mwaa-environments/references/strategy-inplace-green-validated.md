# Rehearsed in-place upgrade (same environment, history kept)

Your current environment is kept as-is — same ARN and webserver URL. Historical run data preserved via MWAA's upgrade
snapshot. A temporary test copy is stood up first purely to rehearse the
upgrade at each stage, so upgrading your real environment is de-risked.

**Plan durability:** plan maintenance, self-consistency invariants, and resume
reconciliation follow [plan-materialization.md](plan-materialization.md). Save
progress after every step below - status token plus durable facts (run_ids,
ARNs, S3 versions, reasons) plus `Last updated` and `## Where we are` -
before proceeding to the next action.

## Prerequisites

- Approach recorded as `in-place-rehearsed` in the plan.
- Test-copy environment name and S3 paths determined in the plan.
- Upgrade path determined in the plan.

## Execution Steps

### 1. Rehearsal (on the test copy)

Stand up the test copy so it mirrors your current environment's staged path.
This runs as the rehearsal (`working_on`: the test copy).

a. Create the test copy at **the first version jump's target**
   (`jump_1.to`) so the rehearsal follows your current environment's staged
   path (surfacing the same pre-cross deprecation warnings your current
   environment will hit). Never create the test copy at the source version.
   Match ALL configuration from your current environment: environment class,
   VPC, subnets, security groups, execution role, Airflow configuration
   overrides, logging configuration, weekly maintenance window, webserver
   access mode, and capacity settings (workers, schedulers, webservers). The
   test copy owns independent S3 paths for every mutable artifact (DAGs,
   requirements, plugins, startup script), each seeded from your current
   environment's in-use object versions so the test copy can diverge without
   touching your current environment: copy your current environment's
   in-use **plugins** and **startup script** (`PluginsS3ObjectVersion` /
   `StartupScriptS3ObjectVersion`, from Phase 1 discovery) to the test copy's
   paths with `s3api copy-object` so the source version is pinned (omit
   `?versionId=` on an unversioned bucket; skip an artifact your current
   environment does not use). The engine advances requirements per version
   jump toward the target (at create, the test copy's requirements matches
   the starting version `jump_1.to`, not the target; see upgrade-engine.md),
   and DAGs receive the fixed code. Explicit user confirmation required.

   ```
   aws s3api copy-object --bucket <bucket> --key <test-copy-plugins-path> \
     --copy-source '<bucket>/<current-env-plugins-path>?versionId=<current-env-plugins-version>'
   aws s3api copy-object --bucket <bucket> --key <test-copy-startup-path> \
     --copy-source '<bucket>/<current-env-startup-script-path>?versionId=<current-env-startup-script-version>'
   ```

   Requirements is not copied verbatim — your current environment's is
   pinned to the source version and would conflict on the starting-version
   environment. Build `<test-copy-requirements-path>` from your current
   environment's requirements so `create-environment` does not fail late on
   a pip resolution:

   1. **Constraint URL:** if your current environment's file has a
      `--constraint` line, re-point it to `jump_1.to`'s Airflow+Python
      constraint file (URL template in mwaa-version-matrix.md); if it has
      none and `jump_1.to` is >= 2.7.2, add it.
   2. **Pin alignment:** keep explicit `==` pins. For each constraint-governed
      package (airflow, providers, core deps), update the pin to the version
      in `jump_1.to`'s constraint file; leave third-party packages (not in
      the constraint file) at your current environment's pin. If a package
      genuinely needs a version newer than the constraint, modify the
      constraint file for that package (download it, edit that line, save it
      to the test copy's DAGs folder, reference it) rather than leaving a
      pin that fights the constraint.
   3. **Verify (Phase 6 Docker, if available):** build the `jump_1.to` image
      with `amazon-mwaa-docker-images` and confirm the requirements, startup
      script, and plugins install cleanly; fix conflicts and retry until
      clean. If Docker is unavailable, rely on the constraint
      cross-reference above.

   The engine advances the constraint per version jump toward the target
   after create (see upgrade-engine.md). Then create the test copy (only
   after the requirements verify clean):

   ```
   aws mwaa create-environment --name <test-copy> \
     --airflow-version <jump_1.to> \
     --source-bucket-arn <same-as-current-env> \
     --dag-s3-path <test-copy-dag-path> \
     --requirements-s3-path <test-copy-requirements-path> \
     --plugins-s3-path <test-copy-plugins-path> \
     --startup-script-s3-path <test-copy-startup-path> \
     --execution-role-arn <same-as-current-env> \
     --kms-key <same-as-current-env-KmsKey; omit ONLY if your current environment uses the AWS-owned key — confirm this immutable fallback> \
     --network-configuration '{"SubnetIds":<current-env-SubnetIds-array>,"SecurityGroupIds":<current-env-SecurityGroupIds-array>}' \
     --environment-class <same-as-current-env> \
     --airflow-configuration-options <same-as-current-env> \
     --logging-configuration <same-as-current-env> \
     --weekly-maintenance-window-start <same-as-current-env> \
     --webserver-access-mode <same-as-current-env> \
     --max-workers <same-as-current-env> \
     --min-workers <same-as-current-env> \
     --schedulers <same-as-current-env> \
     --min-webservers <same-as-current-env> \
     --max-webservers <same-as-current-env>
   ```

   Omit any path/version flags for artifacts your current environment does
   not use. Poll until AVAILABLE.

b. Migrate operational config to the test copy via `aws mwaa
   invoke-rest-api` (variables, connections, pools — same pattern as the
   New-environment upgrade Step 2, including the pagination note and the
   secrets caveat there: `/variables`, `/connections`, and `/pools` paginate
   at limit 100 (loop `offset` until `total_entries`), connection passwords
   do not round-trip (2.x omits, 3.x masks), and migrated values land in
   argv/audit logs). Prefer a secrets backend; skip variables/connections
   when one is in use.

c. Run the step-by-step upgrade on the test copy; starting condition: newly
   created. See [upgrade-engine.md](upgrade-engine.md).

d. Deploy fixed DAGs to the test copy in batches; confirm no import errors
   via the engine's parse validation.

### 1-checkpoint. Test-run the test copy (REQUIRED)

Parse validation (no import errors) is necessary but NOT sufficient. Before
starting the live upgrade, invoke **skill** `testing-mwaa-workflow` on the
test copy to confirm DAG execution succeeds at the target version. This is
the entire value of the test copy — proving artifacts execute, not just
parse.

- Invoke **skill** `testing-mwaa-workflow` with delegated mode — do NOT trigger
  DAG runs manually via the REST API (`POST /dags/{id}/dagRuns`) or poll run
  states inline. The testing skill owns triggering, polling, classification,
  and the fix loop.
- Every DAG must reach terminal SUCCESS or be classified as blocked on an
  infrastructure/data dependency unrelated to the Airflow version
  (NEEDS-DECISION items from the testing skill's fix loop).
- On artifact failures (wrong operator params, missing imports, incompatible
  API usage): invoke **skill** `debugging-mwaa-workflow` +
  `authoring-mwaa-workflow`, redeploy to the test copy, retest until SUCCESS.
- Do NOT request user confirmation for the live upgrade until execution
  validation passes. A DAG that only parses but fails at runtime will fail
  identically on your current environment after an irreversible in-place
  upgrade.

Record execution results in the plan under a `## Test-run results` section
(DAG ID, run_id, state, duration, and any NEEDS-DECISION items).

### 2. Upgrade your current environment (the live upgrade)

**Prerequisite:** Step 1-checkpoint test-run validation must have passed.
When presenting the live upgrade for user confirmation, include a summary of
the test copy's execution results so the user can make an informed decision.
Example:

> Test-run validation passed on the test copy: N/M DAGs reached SUCCESS at
> `<target-version>`. K DAGs blocked on infrastructure dependencies (unrelated
> to Airflow version). Requesting confirmation to upgrade your current
> environment in place.

Run the step-by-step upgrade on your current environment; starting
condition: upgraded in place, using artifacts already proven on the test
copy (validated requirements.txt, plugins.zip, fixed DAGs). See
[upgrade-engine.md](upgrade-engine.md). Your current environment's history
rides MWAA's snapshot through each version jump. Each version jump requires
its own explicit confirmation.

Re-entry during the live upgrade is identified by `working_on`: your current
environment; the rehearsal is complete once test-run validation has passed
(not just parse validation).

### 3. Re-check your current environment (REQUIRED)

After the irreversible in-place upgrade, confirm your current environment
is healthy before marking complete. Do NOT proceed to Step 4 or 5 until this
checkpoint passes.

```
aws mwaa invoke-rest-api --name <current-env> --method GET --path /health
aws mwaa invoke-rest-api --name <current-env> --method GET --path /dags \
  --query-parameters '{"limit":"100","offset":"0"}'
```

Verify: metadatabase=healthy, scheduler heartbeat advancing, and no import
errors. `/dags` paginates (default `limit` 100) — loop `offset` until
`total_entries` (as in discovery-preflight.md Step 1.4) so an import error on a
DAG beyond the first 100 is not missed. On failure, hand off to `debugging-mwaa-workflow` and resolve before
proceeding.

### 4. Remove the test copy

The test copy was a rehearsal; remove it per Phase 8 (test-copy
decommission path), with per-step user approval:

```
aws mwaa delete-environment --name <test-copy>
```

### 5. Mark Complete

Your current environment's ARN and URL are preserved end-to-end. Update the
plan: status complete, approach `in-place-rehearsed`, completion timestamp.
