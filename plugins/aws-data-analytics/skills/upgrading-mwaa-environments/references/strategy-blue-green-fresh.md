# New-environment upgrade (no run history carried over)

Low risk. Builds a new environment alongside your current one (a blue-green
deployment). Your current environment keeps running as a zero-risk fallback
until switchover. Historical run data does not carry over; the new
environment gets a new ARN and URL.

**Plan durability:** plan maintenance, self-consistency invariants, and resume
reconciliation follow [plan-materialization.md](plan-materialization.md). Save
progress after every step below - status token plus durable facts (run_ids,
ARNs, S3 versions, reasons) plus `Last updated` and `## Where we are` - before
proceeding to the next action.

## Prerequisites

- Approach recorded as `new-environment` in the plan.
- New environment name and S3 paths determined in the plan.
- Upgrade path determined in the plan.

## Execution Steps

### 1. Create the new environment

Create the new environment at **the first version jump's target**
(`jump_1.to`): the target directly when the upgrade path has a single version
jump, or the latest 2.11.x stepping-stone version when the path requires one.
Match ALL configuration from your current environment: environment class,
VPC, subnets, security groups, execution role, Airflow configuration
overrides, logging configuration, weekly maintenance window, webserver access
mode, and capacity settings (workers, schedulers, webservers). The new
environment owns independent S3 paths for every mutable artifact — DAGs,
requirements, plugins, and startup script — each seeded from your current
environment's version (Step 1a) so the new environment can diverge without
touching your current environment; the engine advances requirements per
version jump toward the target (at create, the new environment's requirements
matches the starting version `jump_1.to`, not the target; see
upgrade-engine.md), and DAGs receive the fixed code. Explicit user
confirmation required.

**1a. Seed the new environment's artifacts from your current environment.**
Copy your current environment's in-use **plugins** and **startup script** to
the new environment's paths verbatim — pin the exact
`PluginsS3ObjectVersion` / `StartupScriptS3ObjectVersion` from Phase 1 discovery
with `s3api copy-object`; on an unversioned bucket omit `?versionId=`, and skip
an artifact your current environment does not use:

```
aws s3api copy-object --bucket <bucket> --key <new-env-plugins-path> \
  --copy-source '<bucket>/<current-env-plugins-path>?versionId=<current-env-plugins-version>'
aws s3api copy-object --bucket <bucket> --key <new-env-startup-path> \
  --copy-source '<bucket>/<current-env-startup-script-path>?versionId=<current-env-startup-script-version>'
```

**Requirements is not copied verbatim** — your current environment's is pinned
to the source version and would conflict on the starting-version environment.
Build `<new-env-requirements-path>` from your current environment's requirements
so `create-environment` does not fail late on a pip resolution:

1. **Constraint URL:** if your current environment's file has a `--constraint`
   line, re-point it to `jump_1.to`'s Airflow+Python constraint file (URL
   template in mwaa-version-matrix.md); if it has none and `jump_1.to` is >=
   2.7.2, add it.
2. **Pin alignment:** keep explicit `==` pins. For each constraint-governed
   package (airflow, providers, core deps), update the pin to the version in
   `jump_1.to`'s constraint file; leave third-party packages (not in the
   constraint file) at your current environment's pin. If a package genuinely
   needs a version newer than the constraint, modify the constraint file for
   that package (download it, edit that line, save it to the new
   environment's DAGs folder, reference it) rather than leaving a pin that
   fights the constraint.
3. **Verify (Phase 6 Docker, if available):** build the `jump_1.to` image with
   `amazon-mwaa-docker-images` and confirm the requirements, startup script, and
   plugins install cleanly; fix conflicts and retry until clean. If Docker is
   unavailable, rely on the constraint cross-reference above.

The engine advances the constraint per version jump toward the target after
create (see upgrade-engine.md). DAGs are written to `<new-env-dag-path>` by the
engine (fixed code). Each of the new environment's S3 keys is dedicated, so
`create-environment` references the new environment's paths without pinning an
object version. Then create the new environment (only after the requirements
verify clean):

```
aws mwaa create-environment --name <new-env> \
  --airflow-version <jump_1.to> \
  --source-bucket-arn <same-as-current-env> \
  --dag-s3-path <new-env-dag-path> \
  --requirements-s3-path <new-env-requirements-path> \
  --plugins-s3-path <new-env-plugins-path> \
  --startup-script-s3-path <new-env-startup-path> \
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

Omit any path/version flags for artifacts your current environment does not
use.
Poll until AVAILABLE (may take up to a couple of hours):

```
aws mwaa get-environment --name <new-env> --query "Environment.Status"
```

### 2. Migrate Operational Metadata via REST API

No historical run data is migrated. Migrate only operational config:

> **Secrets caveat — read before migrating.** Raw `GET`->`POST` is incomplete
> and sensitive for secret-bearing config:
>
> - **Connection passwords do NOT round-trip.** `GET /connections` omits the
>   password in Airflow 2.x (schema `load_only`) and masks it in 3.x (redacted
>   validator), so the POST below recreates a **passwordless** connection. Treat
>   a migrated connection as incomplete: point it at a Secrets Manager / SSM
>   secrets backend (preferred — the secret never touches the API) or re-enter
>   the password out of band, and verify each connection on the new environment
>   before switchover.
> - **The values that do transit are sensitive.** Variable values (returned
>   cleartext by `GET /variables`) and connection `extra` land in the `--body`
>   argument, visible in process args, shell history, and the MCP-server /
>   CloudTrail audit log. Prefer a secrets backend so they never traverse the
>   API/CLI; if inline migration is unavoidable, treat them as secrets and do
>   not echo them.

**Paginate every read.** `GET /variables`, `/connections`, and `/pools` each
return at most 100 items per call (the Airflow REST API's default `limit`), so
reading once silently migrates only the first 100 and drops the rest on an
environment that has more than 100 of any of them. Pass
`--query-parameters '{"limit":"100","offset":"0"}'` and re-issue with `offset`
incremented by 100 until you have read `total_entries` items — the same
limit/offset loop discovery-preflight.md Step 1.4 uses for `/dags` — POSTing
every page to the new environment.

**Variables** (skip if secrets backend handles these):

```
aws mwaa invoke-rest-api --name <current-env> --method GET --path /variables \
  --query-parameters '{"limit":"100","offset":"0"}'
aws mwaa invoke-rest-api --name <new-env> --method POST --path /variables \
  --body '{"key":"<key>","value":"<value>"}'
```

**Connections** (skip if secrets backend handles these):

```
# recreates a PASSWORDLESS connection — set the password via a secrets backend
# or re-enter it out of band afterward (see the Secrets caveat above)
aws mwaa invoke-rest-api --name <current-env> --method GET --path /connections \
  --query-parameters '{"limit":"100","offset":"0"}'
aws mwaa invoke-rest-api --name <new-env> --method POST --path /connections \
  --body '<connection-json>'
```

**Pools** (skip `default_pool`):

```
aws mwaa invoke-rest-api --name <current-env> --method GET --path /pools \
  --query-parameters '{"limit":"100","offset":"0"}'
aws mwaa invoke-rest-api --name <new-env> --method POST --path /pools \
  --body '{"name":"<name>","slots":<slots>,"description":"<desc>"}'
```

### 3. Run the step-by-step upgrade on the new environment

Run the step-by-step upgrade on the new environment; starting condition:
newly created. See [upgrade-engine.md](upgrade-engine.md). The engine
validates at the starting version and upgrades through the remaining version
jumps to the target.

### 4. Deploy Fixed DAGs in Batches

**Two-phase deployment (multi-jump paths only):** When the upgrade path has
more than one version jump (e.g., 2.7.2 -> 2.11.2 -> 3.2.1), DAG deployment is
split into two phases because AF3-only imports (`from airflow.sdk import ...`)
fail to parse on AF2.x environments:

- **Phase A (first version jump validation at starting version):** Deploy the
  ORIGINAL AF2-compatible DAGs. These are the unmodified source DAGs (or
  minimally patched for the intermediate version). Validate that all DAGs
  parse and run on the starting version before proceeding to the second
  version jump.
- **Phase B (after the second version jump completes at target version):**
  Deploy the FIXED DAGs (Ruff-applied, `airflow.sdk` imports, Asset renames,
  etc.). These contain AF3-only code and can only be deployed once the
  environment is running the target 3.x version.

For single-jump paths (source is already 2.11.x, target is 3.x), only Phase B
applies — deploy fixed DAGs directly after the single version jump completes.

For each batch (0..N):

- Upload batch DAGs to the new environment:

  ```
  aws s3 cp <dag-file>.py s3://<bucket>/<new-env-dag-path>/
  ```

- Wait for parsing (poll `/dags` up to 5 min).
- Verify `has_import_errors` is false:

  ```
  aws mwaa invoke-rest-api --name <new-env> --method GET --path /dags/<dag_id>
  ```

- On import errors, hand off to `debugging-mwaa-workflow`; fix, redeploy,
  re-verify. Loop within the batch until parsing is clean.
- Update plan: mark batch DAGs deployed.

This step establishes clean parsing only — test-run validation is owned by
the required checkpoint in Step 4-checkpoint, not here.

### 4-checkpoint. Test-run the new environment (REQUIRED)

Parse validation (no import errors) is necessary but NOT sufficient. Before
switchover (Phase 8), invoke **skill** `testing-mwaa-workflow` on the new
environment to confirm DAG execution succeeds at the target version. At
switchover the new environment becomes the live environment; a DAG that only
parses but fails at runtime will fail on the new environment once your
current environment is paused and no longer serving it.

- Invoke **skill** `testing-mwaa-workflow` with delegated mode — do NOT trigger
  DAG runs manually via the REST API (`POST /dags/{id}/dagRuns`) or poll run
  states inline. The testing skill owns triggering, polling, classification,
  and the fix loop.
- Every DAG must reach terminal SUCCESS or be classified as blocked on an
  infrastructure/data dependency unrelated to the Airflow version
  (NEEDS-DECISION items from the testing skill's fix loop).
- On artifact failures (wrong operator params, missing imports, incompatible
  API usage): invoke **skill** `debugging-mwaa-workflow` +
  `authoring-mwaa-workflow`, redeploy to the new environment, retest until
  SUCCESS.
- Do NOT begin the batch-by-batch switchover until test-run validation
  passes. Parse success alone does not prove artifacts execute correctly at
  the target version.

Record execution results in the plan under a `## Test-run results` section
(DAG ID, run_id, state, duration, and any NEEDS-DECISION items).

### 5. Proceed to Phase 8

All batches test-run verified (Step 4-checkpoint), operational metadata
migrated. Ready for switchover.
