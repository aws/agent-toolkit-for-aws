# MWAA Version Matrix

## Source of Truth (runtime-first)

The authoritative list of MWAA-supported Airflow versions, their Python
version, and their constraints file is the AWS docs page, fetched at runtime:
https://docs.aws.amazon.com/mwaa/latest/userguide/airflow-versions.html

Phase 1 fetches that page and derives:

- `supported_versions` — versions creatable/available on MWAA.
- `eos_versions` — versions past MWAA end-of-support (not creatable).
- `python_by_version` — Airflow version to Python version.
- `latest_by_major` — the highest available version per major (the 2.x entry
  is the required stepping-stone version before crossing to a new major
  version).

If the fetch fails, retry or ask the user for the target details; do NOT plan
against assumed version numbers. MWAA rejects any invalid target at execution
time regardless, so treat execution-time validation as the backstop.

## Python-Line Boundaries

Derive the current supported set, EOS status, and Python-by-version mapping
from the runtime fetch above — do NOT hardcode a version list, it changes as
MWAA adds releases and retires EOS versions.
After the end-of-support date, a new environment cannot be created at that
version. This does not block any remaining approach: the New-environment
upgrade creates the new environment at the newer first-version-jump target
rather than the source, and the in-place approaches (Rehearsed and Direct)
upgrade away from the EOS source.

**Python-line boundaries** (stable across releases): Airflow 2.4–2.6 run
Python 3.10; 2.7–2.10 run Python 3.11; 2.11.x through 3.2.1 run Python 3.12.
For releases newer than 3.2.1, derive the Python version from the runtime fetch
(`python_by_version`) above rather than from this list, since a future 3.x may
adopt Python 3.13+.
A version jump that crosses any of these boundaries carries compiled-dependency
risk and is flagged `python_change`. `GetEnvironment` returns `AirflowVersion`
but not the Python version, so derive the source Python from these boundaries.

A source below the current minimum supported version is below supported
upgrade paths: report as manual intervention or environment recreation; do not
auto-plan.

## Constraint File URL Template

```
https://raw.githubusercontent.com/apache/airflow/constraints-<version>/constraints-<python-version>.txt
```

Example for AF 3.2.1 on Python 3.12:

```
https://raw.githubusercontent.com/apache/airflow/constraints-3.2.1/constraints-3.12.txt
```

Example for the 2.10.1 on Python 3.11:

```
https://raw.githubusercontent.com/apache/airflow/constraints-2.10.1/constraints-3.11.txt
```

## Version-jump rules

- **Same major (2->2 or 3->3):** a single direct version jump source -> target
  is the candidate. Flag `python_change` when it crosses a Python-line boundary.
- **Cross-major (2->3):** MWAA offers the major upgrade only through the latest
  2.11.x. Route source -> latest-2.11.x (omit if source is already 2.11.x),
  then latest-2.11.x -> 3.x target. The final version jump is flagged
  `crosses_major`.
- **Runtime validation:** the exact allowed minor version-jump matrix is not
  hardcoded. `update-environment` validates each jump at execution; on
  rejection, the API error message indicates the maximum allowed target from
  the current source. Insert that version as an intermediate version jump and
  re-plan the remainder from the new position, logging inserted version jumps.
  If the error does not specify a maximum, bisect: try the highest supported
  version below the rejected target (from the runtime-fetched
  `supported_versions` list) until a version jump succeeds.
- **Downgrade / rollback:** downgrade from 3.x to 2.11.x is supported; a
  within-major downgrade to a still-supported (non-EOS) version is supported;
  downgrade to an EOS version is not possible. Verify EOS at runtime.

**Documentation discrepancy (recorded, not resolved here):** the MWAA
`upgrading-environment.html` page documents the major 2-to-3 in-place upgrade
via 2.11.x, while `airflow-versions.html` states upgrades cannot cross a major
version. Treat `upgrading-environment.html` as authoritative because it is the
specific procedure page. Verify at runtime if MWAA behavior appears to differ.

## Pre-installed Provider Packages

MWAA pre-installs a set of provider packages whose versions differ by Airflow
version and change over time. Do NOT assume specific pinned versions — fetch
the current list at runtime from
https://docs.aws.amazon.com/mwaa/latest/userguide/connections-packages.html
and compare against the target version's constraints.

## Features NOT Supported on MWAA (even with AF3)

_Verify against the AWS MWAA documentation at runtime; feature support can change across releases._

- `core.multi_team` — incompatible with MWAA auth, CeleryExecutor, and secrets management
- `triggerer.queues_enabled` — causes deferred tasks to hang
- Edge Executor / task isolation (AIP-69)
- Multi-language support (AIP-72)
- Full SimpleAuthManager replacement — MWAA uses FAB for auth

## invoke-rest-api Behavior

- MWAA auto-routes paths based on environment Airflow version
- AF2 environments: paths resolve to `/api/v1`
- AF3 environments: paths resolve to `/api/v2`
- Pass just the path portion (e.g., `/dags`, `/health`) without the version prefix
- 10-second timeout, 6 MB max response
  (https://docs.aws.amazon.com/mwaa/latest/userguide/access-mwaa-apache-airflow-rest-api.html)
- Requires IAM permission: `airflow:InvokeRestApi`
- Cannot serialize task instances with cross-version pickle data in
  `rendered_template_fields` (throws `RestApiServerException`). Fallback: use
  the MWAA CLI-token endpoint — `aws mwaa create-cli-token` returns a bearer
  token + `WebServerHostname`; POST the Airflow CLI command (text/plain) to
  `https://<hostname>/aws_mwaa/cli` (stdout/stderr are base64-encoded, token
  TTL ~60s, needs `airflow:CreateCliToken`). It reads the metadata DB directly,
  bypassing JSON serialization and the 10s / 6 MB REST limits.

## Webserver Login Path Change

- AF2: `/aws_mwaa/login`
- AF3: `/pluginsv2/aws_mwaa/login`

## IAM Requirements for invoke-rest-api

- Action: `airflow:InvokeRestApi`
- Resource: the RBAC role ARN —
  `arn:<partition>:airflow:<region>:<account>:role/<environment-name>/<role-name>`
  where `<role-name>` is one of `Admin`, `Op`, `User`, `Viewer`, or `Public`
- Reference: https://docs.aws.amazon.com/service-authorization/latest/reference/list_mwaa.html#list_mwaa-resource-rbac-role
