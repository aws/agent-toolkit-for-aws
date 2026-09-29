---
name: authoring-mwaa-workflow
description: >
  Authors and deploys MWAA workflow artifacts: Python Airflow DAGs for provisioned
  environments or YAML workflow files for Serverless. Covers operator selection,
  timeout design, retry strategy, scheduling, failure notifications, idempotency,
  and MWAA Serverless schema compliance. Deploys the artifact (S3 DAG upload or
  Serverless CreateWorkflow/UpdateWorkflow), creates an environment inline when
  approved, and redeploys fixes, then optionally hands off to
  testing-mwaa-workflow. Triggers on: create a DAG, write a pipeline, build a
  workflow, orchestrate tasks, Airflow DAG, data pipeline, schedule a job, deploy
  a DAG, deploy a workflow, YAML workflow. Not applicable to converting or migrating
  existing DAGs between provisioned and serverless (conversion is out of scope),
  running or smoke-testing a deployed workflow (handled by testing-mwaa-workflow) or
  diagnosing a failed run (handled by debugging-mwaa-workflow).
metadata:
  version: "1"
---

# Authoring MWAA Workflows

> **AWS MCP server (optional but recommended):** running the AWS CLI commands in
> this skill through the AWS MCP server gives sandboxed execution and audit
> logging. Every command here also works with the plain AWS CLI, so the skill
> does not require the MCP server or any MCP-only tools.

Author production-grade workflow artifacts for Amazon MWAA. Routes to one
of two paths: Python DAG (provisioned) or YAML workflow (Serverless).

> **Execution note — poll in discrete steps:** whenever you wait for an AWS
> operation to reach a terminal or ready state, issue **one status check per
> call** and decide in your own loop whether to check again. Never block a
> single command or script on the wait (no `while`+`sleep` until done),
> regardless of the operation or how long it takes.

## Guardrail — where this skill's own files live (MCP vs local install)

This skill can be loaded two ways, and they resolve the skill's own bundled
files from different places. Determine how the skill was loaded before reading
a reference:

- **Loaded through the AWS MCP `retrieve_skill` tool:** The skill is not
  installed on the local filesystem. You MUST fetch each reference via
  `retrieve_skill` with the `file` parameter (e.g.
  `file="references/authoring-provisioned-dag.md"`) and read the returned
  content. Do NOT `file_read` these paths locally — they do not exist on disk.
- **Installed locally** (e.g. `.kiro/skills/authoring-mwaa-workflow/` or
  `~/.claude/skills/authoring-mwaa-workflow/`): Read the files from the local
  skill directory using relative paths.

This distinction applies only to the skill's own packaged files. User data and
session artifacts are always read from and written to the user's working
directory. Never fetch or write customer data through `retrieve_skill`.

## Step 0: Route to Path

Evaluate in this order:

1. **Resolvable target provided?** A target reference is a definitive
   routing signal regardless of other keywords:
   - A provisioned environment (ARN like
     `arn:aws:airflow:<region>:<account>:environment/<name>`, or a name
     resolvable via `aws mwaa get-environment`) → go to **Path A**.
   - A Serverless workflow ARN
     (`arn:aws:airflow-serverless:<region>:<account>:workflow/<name>`) → go to
     **Path B**.
2. **Both-path keywords present?** If the request contains keywords from
   both paths and no resolvable target, disambiguate by intent:
   - `PythonOperator` is supported on Serverless, so an operator-level
     `python` cue (`PythonOperator`, `python_callable`, "Python function/task")
     alongside a Path B signal (`yaml`, `serverless`, workflow ARN) is NOT
     ambiguous → go to **Path B**.
   - Conversion context ("convert my Python DAG to serverless") → this
     skill does not apply; conversion is out of scope.
   - A genuine provisioned cue (`Python DAG`, `provisioned`) alongside a
     Serverless cue with no target → ask the clarifying question.
3. **Exactly one path keyword?** Treat only deployment-target terms as Path A
   signals: `provisioned`, `Python DAG`, or "a `.py` for my environment" → go
   to **Path A**. `yaml` or `serverless` → go to **Path B**. Operator-level
   Python mentions are not Path A signals.
4. **No routing signal?** "DAG" or "Workflow" alone is ambiguous — it does
   NOT indicate a path. Ask: is the target **MWAA provisioned (Python
   DAG)** or **MWAA Serverless (YAML)**?

---

## Paths

Follow the reference for the path you routed to (you do not need the other path's reference):

- **Path A — Python DAG (MWAA Provisioned):** [references/authoring-provisioned-dag.md](references/authoring-provisioned-dag.md)
- **Path B — YAML Workflow (MWAA Serverless):** [references/authoring-serverless-workflow.md](references/authoring-serverless-workflow.md)

After the routed path's **Write** step, continue with **Deploy & Test** below.

## Deploy & Test (optional, after Write)

Authoring owns all deployment and redeployment. Detail in
[references/deploying-mwaa.md](references/deploying-mwaa.md).

### Steps

1. **Ask** — present options based on whether the artifact has a schedule.
   Frame the question using path-appropriate language:
   - **Provisioned:** "deploy this DAG to an environment" (DAGs are uploaded
     to an environment's S3 bucket).
   - **Serverless:** "deploy this workflow" (workflows are standalone
     resources — never say "deploy to an environment").

   **If the DAG/workflow has a schedule:**
   - **Deploy and test** — deploy, unpause, trigger a run now
   - **Deploy and unpause** — deploy, unpause, let it run on schedule (no
     immediate trigger)
   - **Deploy only** — upload to S3, leave paused

   **If the DAG/workflow has no schedule (manual-trigger only):**
   - **Deploy and test** — deploy, trigger a run now
   - **Deploy only** — upload to S3, leave paused (no "unpause" option —
     nothing to schedule)

   The user may also decline all options.

2. **Deploy:**
   - **Provisioned:** upload the DAG to the environment's `SourceBucketArn`/
     `DagS3Path`. Run post-deploy verification (see deploying-mwaa.md) to
     confirm the scheduler parsed the new file without import errors or
     dag_id conflicts. If no environment exists and the user approves,
     create one inline (plan-validate-execute + explicit confirmation),
     then poll `CREATING` -> `AVAILABLE` (~20-40 min). The user may instead
     supply an existing environment.
   - **Serverless:** `CreateWorkflow` (new) or `UpdateWorkflow` (redeploy);
     the YAML is validated synchronously here. If the workflow uses
     `PythonOperator`/`BashOperator`, first build and upload the code package
     to S3 and pass it via `--code` (see
     [references/serverless-code-packaging.md](references/serverless-code-packaging.md)
     and [references/deploying-mwaa.md](references/deploying-mwaa.md)). The user
     may instead supply an existing ARN.
   - **Redeploy (fix loop):** the same upload / `UpdateWorkflow` path,
     reused when testing-mwaa-workflow delegates an ARTIFACT or ENVIRONMENT
     fix.
3. **If "Deploy and unpause" selected** — deploy per step 2, then unpause.
   Do not trigger a run or invoke testing-mwaa-workflow.
4. **If "Deploy and test" selected** — deploy per step 2, unpause if
   applicable, then invoke testing-mwaa-workflow with the resolved target
   (env name + `dag_id`, or workflow ARN). That hand-off is testing's
   delegated invocation mode.

> **HARD GATE:**
> If testing is requested — whether upfront ("deploy and test") or later in
> the conversation ("test it", "run it", "try it") — you MUST invoke
> testing-mwaa-workflow. Do NOT trigger, monitor, or verify DAG runs manually.
> "Deploy and unpause" is NOT a test request — it is a deploy-only action.

- **Production safety:** `create-environment`, `update-environment`,
  `create-workflow`, and `update-workflow` mutate state — confirm each with
  its impact stated. Warn on prod-named targets.

## Troubleshooting

| Error | Cause                           | Fix                                           |
|-------|---------------------------------|-----------------------------------------------|
| dagrun_timeout kills DAG early | < timeout set in service called | Raise dagrun_timeout or lower service timeout |
| YAML validation rejects workflow | Wrong type or param             | Use timedelta format; check allowlist         |
| Operator not found in Serverless | Not allowlisted | Use a supported operator, PythonOperator/BashOperator, or Lambda |
| Serverless run: cannot extract code / corrupt env | Bad code package | Files at zip root, no `__pycache__`, ≤250 MB; repackage |
| Serverless Python task ImportError | Missing dep or wrong-platform wheel | Bundle as `manylinux2014_x86_64` / Py3.12 wheel; don't bundle pre-installed packages |
| Template variable undefined | Version mismatch                | Check vars for exact Airflow version          |

## References

- [references/dag-patterns.md](references/dag-patterns.md) — Python DAG templates
- [references/yaml-schema.md](references/yaml-schema.md) — MWAA Serverless format
- [references/deploying-mwaa.md](references/deploying-mwaa.md) — deploy, inline env creation, and redeploy
- [references/serverless-code-packaging.md](references/serverless-code-packaging.md) — Python/Bash code packaging, pre-installed packages, limits
- [references/authoring-provisioned-dag.md](references/authoring-provisioned-dag.md) — Path A: provisioned Python-DAG authoring steps (A1–A7)
- [references/authoring-serverless-workflow.md](references/authoring-serverless-workflow.md) — Path B: Serverless YAML authoring steps (B1–B5)

## Security Considerations

- **State-mutating operations** (`create`/`update-environment`,
  `create`/`update-workflow`, S3 DAG upload) require explicit confirmation with
  impact stated; warn on prod-named targets (see the Deploy HARD-GATE).
- **Least-privilege IAM**: the A5 check adds only the exact `Action`/`Resource`
  pairs the artifact needs — never `*FullAccess` or `service:*`.
- **No hardcoded secrets/endpoints**: use Airflow Variables/Connections backed
  by Secrets Manager or SSM Parameter Store; never emit credentials in DAG code
  or CLI examples.
- **Serverless code packages** ship only the user's own modules plus pinned,
  platform-matched wheels — no unreviewed third-party binaries.
- **Data protection**: keep sensitive data out of SNS/CloudWatch notification
  payloads and logs; rely on their encryption.
- **Secure defaults for inline-created resources**: encrypt and lock down any
  S3/MWAA/SNS/CloudWatch resource this skill creates — see [deploying-mwaa.md](references/deploying-mwaa.md) "Secure defaults".
- **AWS security best practices**: verify the security posture against the MWAA
  User Guide's [Security best practices](https://docs.aws.amazon.com/mwaa/latest/userguide/security-best-practices.html)
  page (and the [MWAA Serverless equivalent](https://docs.aws.amazon.com/mwaa/latest/mwaa-serverless-userguide/security-best-practices.html))
  at runtime — AWS updates them over time; see [deploying-mwaa.md](references/deploying-mwaa.md) "Secure defaults".
