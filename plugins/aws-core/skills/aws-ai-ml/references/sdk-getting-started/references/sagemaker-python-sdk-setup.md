# SageMaker Python SDK Setup

Workflow for validating the SageMaker Python SDK environment.

## Step 1: Install/Verify SDK

First, check if the SDK is already installed:

```
python -c "from importlib.metadata import version; print(version('sagemaker'))"

```

- If version ≥ 3.30.0 → the SDK is ready. Report the version and move on. Only upgrade if the user explicitly asks for it.
- If missing or < 3.30.0 → install:

```
pip install 'sagemaker>=3.30.0,<4.0' boto3 -q

```

Then re-run the version check to confirm.

- If the user is on 3.22.0–3.29.0 and declines the upgrade → continue on their version. Fine-tuning, evaluation, deployment, training and processing all work there. Data preparation does not: if that is what they asked for, tell them synthetic dataset generation, dataset quality and dataset transformation need 3.30.0, and stop.

> Baseline is `'sagemaker>=3.30.0,<4.0'` — the release that carries the data preparation API (`DataPreparer`, `DatasetJobConfig`, `JobCategory`) used by synthetic dataset generation, dataset quality and dataset transformation. Earlier v3 releases run the fine-tuning, evaluation and deployment pathways but have no data preparation. The baseline also has to stay at or above 3.22.0 for the OSS deploy pathway, which needs fine-tuned support in `list_deployment_configs()` / `set_deployment_config()`.
>
> This is where the baseline is set. Five data preparation files state it literally, at the points a reader needs a version they can act on — a `%pip` cell, a troubleshooting row, a runtime error. `test/sdk_baseline/` fails the build if any of them disagrees with the version above, or silently drops it. Bump it here, run the tests, and they name anything left behind.

### If install fails

STOP. Do NOT proceed with the plan. Tell the user:

> pip install failed — this is likely a system-level issue, not something I can fix by trying different install commands.

Show the exact error, then:

> Common causes: missing C build tools (gcc/python3-devel), incompatible Python version, or network/proxy issues.

**Do NOT** retry with `--no-deps`, alternative package names, or extras like `[core]` or `[train]`. These result in a broken partial install that fails later with import errors.

## Step 2: Check Region

If REGION is already stored in conversation context, skip this step — do not re-prompt the user.

Otherwise, run:

```
python -c "import boto3; print(boto3.session.Session().region_name)"

```

- `None` → STOP. Tell user: "Set your region via `export AWS_DEFAULT_REGION={region}` or `aws configure`."
- Set → store REGION in context, continue.

## Step 3: Resolve and Validate Execution Role

Read and follow `execution-role-setup.md`.

## Step 4: Summary

Print:

```
Environment ready:
  SDK:    sagemaker <installed version> ✅
  Region: <region> ✅
  Role:   <arn> ✅
          sagemaker trust ✅ | bedrock trust ⚠️ | lambda trust ✅

```

Downstream references use REGION and ROLE_ARN from conversation context. They MUST NOT re-resolve these values.
