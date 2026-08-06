# SageMaker Python SDK Setup

Workflow for validating the SageMaker Python SDK environment.

## Step 1: Install/Verify SDK

First, check if the SDK is already installed:

```
python -c "from importlib.metadata import version; print(version('sagemaker'))"

```

- If version ≥ 3.17.0 → the SDK is ready. Report the version and move on. Only upgrade if the user explicitly asks for it.
- If missing or < 3.17.0 → install:

```
pip install 'sagemaker>=3.17.0,<4.0' boto3 -q

```

Then re-run the version check to confirm.

> Baseline is `'sagemaker>=3.17.0,<4.0'` (not 3.7.x) — the release that adds fine-tuned support to the deployment-config API (`list_deployment_configs` / `set_deployment_config`) the OSS deploy pathway uses. Earlier v3 releases run finetuning/evaluation fine but not that deploy pathway.

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
  SDK:    sagemaker X.Y.Z ✅
  Region: <region> ✅
  Role:   <arn> ✅
          sagemaker trust ✅ | bedrock trust ⚠️ | lambda trust ✅

```

Downstream references use REGION and ROLE_ARN from conversation context. They MUST NOT re-resolve these values.
