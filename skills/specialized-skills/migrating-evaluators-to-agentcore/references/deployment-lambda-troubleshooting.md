# Lambda Deployment: Failure Modes and Environment Repair

Diagnostic companion to [deployment-lambda.md](deployment-lambda.md). Load this
only when a deploy or invoke has actually failed — read the specific section
matching the symptom rather than the whole file.

## Contents

- [CDK Platform Mismatch (aarch64 vs x86_64)](#cdk-platform-mismatch-aarch64-vs-x86_64)
- [Lambda Failure Recovery](#lambda-failure-recovery)
- [Silent Failure Modes (Lambda Returns All 0.0)](#silent-failure-modes-lambda-returns-all-00)
- [Evaluator ID Resolution](#evaluator-id-resolution)
- [Node.js Installation (Robust Fallback Chain)](#nodejs-installation-robust-fallback-chain)
- [CLI-Broken Fallbacks (use after ≤5 steps of CLI repair)](#cli-broken-fallbacks-use-after-5-steps-of-cli-repair)
- [CDK Architecture Fix (x86_64 Hosts)](#cdk-architecture-fix-x86_64-hosts)
- [Gotchas](#gotchas)

## CDK Platform Mismatch (aarch64 vs x86_64)

The `agentcore deploy` CDK construct defaults to ARM64 (aarch64) Lambda runtime.
If your build host is x86_64 (check with `uname -m`), Python packages bundled by
`uv` will be x86_64 binaries — causing `ImportError: pydantic_core` at Lambda runtime.

**Detection (run BEFORE deploying):**

```bash
HOST_ARCH=$(uname -m)
echo "Host architecture: $HOST_ARCH"
# If x86_64 → CDK default arm64 WILL cause platform mismatch
```

**Fix options:**

1. Patch the CDK-generated Lambda to use x86_64 architecture:
   - In the CDK `bin/` entrypoint or construct, set `architecture: lambda.Architecture.X86_64`
   - Or find where `uv` is called and add `--platform manylinux2014_x86_64`
2. Use `--platform manylinux2014_aarch64` in `pyproject.toml` [tool.uv] section to
   force bundling ARM64 packages on x86_64 host (less reliable)
3. After deployment, verify Lambda architecture matches packaged binaries
   (boto3, so this works without the aws CLI installed):

   ```bash
   python3 -c "import boto3; print(boto3.client('lambda').get_function_configuration(FunctionName='$FUNC')['Architectures'])"
   ```

**If platform mismatch persists after 1 fix attempt:** Free disk, clean up, and retry
with the alternative platform fix. Do NOT fall back to LLM-as-a-Judge.

## Lambda Failure Recovery

**When Lambda deployment fails**, read the error message and apply the known fix.
If the same error recurs after the fix was applied, STOP and report to user.

| Error Signal | Known Fix |
|---|---|
| `ENOSPC` / `No space left on device` | Clean up: `rm -rf $DEPLOY_DIR/cdk.out $DEPLOY_DIR/node_modules /tmp/* .deepeval`; retry |
| CF stack `ROLLBACK_COMPLETE` or `REVIEW_IN_PROGRESS` | Delete the stuck stack (boto3: `boto3.client('cloudformation').delete_stack(StackName=...)`) and wait for `DELETE_COMPLETE`. Then delete the `/aws/lambda/<project>-eval-*` log groups it left behind (boto3: `boto3.client('logs').delete_log_group(logGroupName=...)` for each group `describe_log_groups(logGroupNamePrefix=f"/aws/lambda/{project}-eval-")` returns): the CDK sets `DeletionPolicy: Retain` on them, so the redeploy fails with `AlreadyExists` while they exist. Updates NEVER succeed from these states — always delete then redeploy |
| `ImportError: pydantic_core` / architecture mismatch | Patch CDK platform (see above); retry |
| TypeScript / CDK synth errors | Pin `typescript@5.9.3`; retry |
| `third_party` submodule missing | Pin `bedrock-agentcore==1.23.0`; if still missing, write custom handler |
| Timeout (>600s) | Check for conflicting stack; delete and retry |

**After each successful deploy**, clean up local CDK artifacts to free space for next:

```bash
rm -rf $DEPLOY_DIR/cdk.out $DEPLOY_DIR/node_modules
find $DEPLOY_DIR -name "*.zip" -delete
```

**If disk truly cannot be freed (<200MB after cleanup):** STOP and inform user.

**Key principle:** Do NOT proactively check/manage disk space. Only clean up when
you encounter an actual error or between successful deployments.

## Silent Failure Modes (Lambda Returns All 0.0)

### 1. async_mode Event Loop Conflict

DeepEval metrics default to `async_mode=True` → calls `asyncio.run()`.
The `@custom_code_based_evaluator()` decorator already runs an event loop.
Result: `RuntimeError: This event loop is already running` → silent 0.0.

**Fix:** ALWAYS set `async_mode=False`:

```python
metric = FaithfulnessMetric(threshold=0.5, async_mode=False)
```

### 2. Missing Bedrock IAM Permissions

Lambda execution role needs explicit `bedrock:InvokeModel`. Without it,
LLM-calling metrics silently return 0.0.

**Fix (after deploy):**

```python
import boto3, json, sys
sys.path.insert(0, "<this skill's directory>")  # same path as $SKILL
from scripts.deployer import judge_invoke_resources
lambda_client = boto3.client('lambda')
config = lambda_client.get_function_configuration(FunctionName=func_name)
role_name = config['Role'].split('/')[-1]
account = boto3.client('sts').get_caller_identity()['Account']
boto3.client('iam').put_role_policy(
    RoleName=role_name, PolicyName='BedrockAccess',
    PolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow",
        "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
        # Name the models this evaluator invokes. `"Resource": "*"` would grant invoke
        # on every model in the account. Use the same three ARNs the deployer grants:
        # scripts/deployer.py::judge_invoke_resources(region, account).
        "Resource": judge_invoke_resources(region, account)
    }]})
)
```

`judge_invoke_resources(region, account)` returns the cross-region inference profile
the evaluator calls, its underlying foundation model (a profile invokes it in whichever
region it routes to, so only this ARN has a wildcard region), and the embeddings model
every RAGAS `needs_embeddings` metric invokes. The profile and embeddings ARNs are
scoped to `region`, the Lambda's own region, which is where the handler calls them.
`account` is required and must be the 12-digit account ID: the helper raises rather
than widening the profile ARN to every account. Import it rather than re-deriving the
ARNs, so the literal the Lambda invokes and the ARN the policy grants cannot drift
apart.

### 3. DeepEval Model Configuration

DeepEval defaults to OpenAI. Configure Bedrock explicitly:

```python
from deepeval.models import AmazonBedrockModel
# CORRECT: use model= (NOT model_name=), and region= is REQUIRED
model = AmazonBedrockModel(model="us.anthropic.claude-sonnet-4-5-20250929-v1:0", region="us-east-1")
metric = FaithfulnessMetric(threshold=0.5, model=model, async_mode=False)
```

### 4. Missing aiobotocore Dependency

DeepEval's Bedrock judge imports aiobotocore transitively, so DeepEval Lambdas need it
(migration.sh injects it into their pyproject automatically). RAGAS bundles carry the
same SDK without it — do not add it to a non-DeepEval Lambda. If a DeepEval Lambda
logs `No module named 'aiobotocore'`, add the exact pin the deployer uses:

```toml
dependencies = [
    "aiobotocore==3.9.1",
    # ... other deps
]
```

### 5. uv Not Installed (CDK Package Bundling Fails)

CDK uses `uv` to bundle Python packages for Lambda. If `uv` is not in PATH,
deployment fails silently with exit code null or "uv install failed on platform
x86_64-manylinux... with exit code null" (the tag is whichever CDK candidate was tried).

**Fix:** Install uv BEFORE running `agentcore deploy`:

```bash
pip install 'uv==0.12.10' && uv --version
```

### Dependency Verification

The `migration.sh` script uses `sed` to inject dependencies into each Lambda app
dir's `pyproject.toml`. These sed commands can **fail silently**, which is why
the generated script runs `verify_deps.py` itself right before its deploy step.
When debugging a dependency error anyway (e.g. after hand-editing an app dir),
re-run the tool directly:

```bash
python3 $SKILL/scripts/verify_deps.py \
    --deploy-dir deploy/deploy_workspace/<ProjectName> \
    --framework deepeval
```

For RAGAS, use `--framework ragas` (checks that `app/` holds at least one generated
handler, and that `overrides.txt` is present).

The tool auto-fixes missing dependencies (deepeval,
strands-agents-evals) in one pass. Exit code 0 = all verified; exit code 1 =
unfixable issue.

**Impact of skipping this:** You will encounter the error chain one-at-a-time:

1. `ModuleNotFoundError: No module named 'deepeval'` — fix, redeploy
2. `ModuleNotFoundError: No module named 'strands_evals'` — fix, redeploy

Each fix+redeploy costs 3-5 steps and 5+ minutes.

### Fast Handler Fixes: `update_function_code()`

When a handler has a code bug but the deployment infrastructure (CDK stack,
Lambda function, evaluator registration) is all working fine, do NOT redeploy
from scratch. Replace the handler inside the deployed bundle and upload it again.
Three details decide whether this works:

- The handler is the bundle's `lambda_function.py` (the CDK entrypoint is
  `lambda_function.handler`), whatever its file name under `handlers/`.
- Rebuild the zip with that entry replaced. Appending a second
  `lambda_function.py` leaves two entries with one name, and which one Lambda
  loads is undefined.
- Upload through S3. A direct `ZipFile=` upload is capped at 50 MB zipped, and a
  CDK bundle is usually over it, so it fails with `RequestEntityTooLargeException`.
  Use the bucket the CDK bootstrap created, which the deploy itself used; do not
  create an ad-hoc bucket.

```python
import boto3, io, urllib.request, zipfile

region = "us-east-1"  # the deploy region
function_name = "<Project>-eval-<evaluator>"  # the CDK names it {project}-eval-{evaluator}
lambda_client = boto3.client("lambda", region_name=region)
account = boto3.client("sts").get_caller_identity()["Account"]
# CDK bootstrap bucket (default qualifier hnb659fds): TLS-only, encrypted by default.
bucket = f"cdk-hnb659fds-assets-{account}-{region}"

code_url = lambda_client.get_function(FunctionName=function_name)["Code"]["Location"]
with urllib.request.urlopen(code_url) as resp:
    original = zipfile.ZipFile(io.BytesIO(resp.read()))
patched = io.BytesIO()
with zipfile.ZipFile(patched, "w", zipfile.ZIP_DEFLATED) as out:
    for item in original.infolist():
        if item.filename != "lambda_function.py":
            out.writestr(item, original.read(item.filename))
    out.writestr("lambda_function.py", new_handler_code)

key = f"handler-fixes/{function_name}.zip"
boto3.client("s3", region_name=region).put_object(
    Bucket=bucket, Key=key, Body=patched.getvalue(), ServerSideEncryption="aws:kms"
)
lambda_client.update_function_code(FunctionName=function_name, S3Bucket=bucket, S3Key=key)
lambda_client.get_waiter("function_updated_v2").wait(FunctionName=function_name)
```

Save the same fix to the handler under `handlers/` and regenerate migration.sh,
or the next `bash deploy/migration.sh` redeploys the old code. This takes 2 steps
vs 10-15 for a full CDK redeploy. **Always prefer this for code-only fixes**
(wrong field extraction, missing label, model config, etc.).

### Diagnosis: Distinguishing Failure Modes

| Symptom | Root Cause | Fix |
|---|---|---|
| Score 0.0 with empty explanation | Lambda NOT invoked (wrong evaluator ID) | Resolve by the project-scoped fragment `{project}_{evaluator-name}` |
| Score 0.0 with "No actual output" | span_events extraction bug | Read from `span_events[0].body` |
| Score 0.0 with "RuntimeError: event loop" | async_mode=True | Set `async_mode=False` |
| Score 0.0 with no Lambda logs | IAM permission denied | Add bedrock:InvokeModel |
| Score 0.0 with "No module named 'aiobotocore'" | Missing dependency (DeepEval Lambdas only) | Add `aiobotocore==3.9.1` to pyproject.toml |
| Score 0.0 with "No module named '...third_party'" | The resolved release predates `third_party` | Pin `bedrock-agentcore==1.23.0`, which ships every adapter |
| Deploy fails with "exit code null" | uv not installed | `pip install 'uv==0.12.10'` before deploy |
| Deploy succeeds but Lambda silent | model= kwarg wrong or missing region= | `AmazonBedrockModel(model="...", region="us-east-1")` |
| `ReadTimeoutError` on evaluate() calls | Lambda cold start (60-120s init on 200MB+ bundles) vs boto3's default 60s read timeout | Generated client scripts set `read_timeout=300` on the data-plane client and retry once. Not a deployment failure |
| `No module named 'strands.plugins.plugin'; 'strands.plugins' is not a package` | An outdated stub prelude in the handler shadows the real strands.plugins package (strands-agents >= 1.50 ships it) | Re-run `package_ragas_lambda.py`, which replaces the prelude. Do NOT add sub-stubs (`.plugin`, `.registry`, ...) |
| `ModuleNotFoundError: No module named 'strands.plugins'` (no "not a package") | The bundled strands-agents predates strands.plugins | Re-run `package_ragas_lambda.py`; `lambda_deps()` pins `strands-agents==1.50.1`, which ships the real package. Never stub it |
| `resolve_evaluator_id` returns None though deploy succeeded | Unpaginated list_evaluators — evaluator is on page 2+ (shared accounts have 800+) | Regenerate the client script (`scripts/generate_client_script.py`); adot.py paginates via nextToken |
| `evaluate()` returns `label: 'Error'` with no detail | Handler raised inside the Lambda | Invoke the Lambda directly with boto3 to get the real traceback |
| evaluate() times out / Lambda task timed out on multi-step metrics | Evaluator was deployed with the CLI's 120s default instead of migration.sh's `--timeout 300` | Update in place — see "Fixing a 120s Evaluator Timeout" below |

### Fixing a 120s Evaluator Timeout (already-deployed evaluators only)

Current `migration.sh` deploys with `--timeout 300`; only touch this if the
evaluator was deployed by older tooling. The `evaluatorConfig` nesting is
strict — the wrong shapes below caused 4/10 failures:

```python
from bedrock_agentcore.evaluation import EvaluationClient
client = EvaluationClient(region_name="us-east-1")

resp = client._cp_client.get_evaluator(evaluatorId=evaluator_id)
lambda_arn = resp["evaluatorConfig"]["codeBased"]["lambdaConfig"]["lambdaArn"]

client._cp_client.update_evaluator(
    evaluatorId=evaluator_id,
    evaluatorConfig={
        "codeBased": {
            "lambdaConfig": {
                "lambdaArn": lambda_arn,          # REQUIRED even when unchanged
                "lambdaTimeoutInSeconds": 300,
            }
        }
    },
)
```

```python
# WRONG — missing lambdaConfig nesting → ValidationError
evaluatorConfig={"codeBased": {"lambdaTimeoutInSeconds": 300}}
# WRONG — missing lambdaArn (required field) → ValidationError
evaluatorConfig={"codeBased": {"lambdaConfig": {"lambdaTimeoutInSeconds": 300}}}
```

## Evaluator ID Resolution

See "Evaluator ID Discovery" above — one story, applied by the generated scripts:

- Lambda evaluators: runtime resolution by the PROJECT-SCOPED fragment
  (`{project}_{evaluator-name}`) is collision-proof. Bare-name fragments are
  the anti-pattern (they match stale evaluators from other runs).
- LLM-as-a-Judge evaluators: paste the exact ID returned by
  `create_evaluator_and_wait()` into the script's `EVALUATORS` dict.
- Hardcoding CLI-deployed IDs from deploy output also works, but is unnecessary
  when the fragment is project-scoped.

## Node.js Installation (Robust Fallback Chain)

Check `agentcore --version` FIRST; only install if it's missing.
Never run two npm installs concurrently — corrupted `node_modules` are
expensive to recover from.

```bash
# Primary: the distro package. Older distros ship v12-v18, so check the version.
apt-get update && apt-get install -y nodejs npm 2>/dev/null
node --version

# Missing or below v20: a version manager, at an exact version.
mise install node@20.19.2   # or: nvm install 20.19.2

# Last resort, no version manager: the official tarball, checked against the
# published SHA-256 before it is extracted. Never pipe a downloaded script into a shell.
V=20.19.2
ARCH=$(uname -m | sed -e 's/x86_64/x64/' -e 's/aarch64/arm64/')
F="node-v$V-linux-$ARCH.tar.xz"
curl -fsSLO "https://nodejs.org/dist/v$V/$F"
curl -fsSLO "https://nodejs.org/dist/v$V/SHASUMS256.txt"
grep " $F\$" SHASUMS256.txt | sha256sum -c - && tar -xJf "$F" -C /usr/local --strip-components=1
```

Verify: `node --version` (need v20+ — the agentcore CDK build fails on 18/19),
`npm --version`, then `npm install -g @aws/agentcore@0.28.1` (the version the generated
migration.sh installs — keep the two in step).

## CLI-Broken Fallbacks (use after ≤5 steps of CLI repair)

If `agentcore` still errors after ~5 steps of fixing (npm corruption, ESM/CJS
errors, broken upstream release), STOP repairing and pick a fallback:

```
agentcore CLI works?
├─ yes → scripts/deployer.generate_migration_sh() as normal (preferred — do NOT skip to fallbacks)
└─ no, after ≤5 repair steps:
   ├─ DeepEval or RAGAS metric? → B: direct boto3 Lambda deploy
   └─ Phoenix classifier or Strands OutputEvaluator? → A: LLM-as-a-Judge via SDK
      (the path these always take; it needs no CLI)
```

Do NOT use A for a DeepEval or RAGAS metric, even one that looks like a single LLM call
(GEval, AspectCritic, SimpleCriteriaScore): the Lambda runs the metric's own code, a
judge stand-in diverges from it, and `generate_handlers.py` refuses a mapping.json
that routes one to `llm_judge`.

### A. LLM-as-a-Judge via SDK (Phoenix and Strands `OutputEvaluator` only)

```python
import sys
from bedrock_agentcore.evaluation import EvaluationClient
sys.path.insert(0, "<this skill's directory>")  # same path as $SKILL
from scripts.deployer import judge_model_id  # region-prefixed profile, not a us.* literal
client = EvaluationClient(region_name=region)  # region = the deploy region
response = client._cp_client.create_evaluator(
    evaluatorName=evaluator_name,  # from names.json
    evaluatorConfig={
        # Canonical shape. `llmAsAJudge` (not llmAsJudge), `instructions` (not
        # customInstructions or evaluationPromptTemplate), and the model nested under
        # modelConfig.bedrockEvaluatorModelConfig. See deployment-llmaaj.md.
        "llmAsAJudge": {
            "instructions": prompt_text,
            "ratingScale": rating_scale,
            "modelConfig": {
                "bedrockEvaluatorModelConfig": {
                    "modelId": judge_model_id(region),
                }
            },
        }
    }
)
evaluator_id = response["evaluatorId"]
```

Paste the returned `evaluatorId` into the generated script's `EVALUATORS` dict
(SDK-created IDs are NOT project-prefixed — runtime resolution won't find them).

### B. Direct Lambda deployment via boto3 (no CLI/CDK)

Prepare the handler directory first (`scripts/package_ragas_lambda.py` for RAGAS;
adapter inlining for DeepEval), then:

```python
import boto3, json, zipfile, io, os

lambda_client = boto3.client("lambda", region_name="us-east-1")
s3_client = boto3.client("s3", region_name="us-east-1")

# 1. Zip the prepared handler directory (bundle deps included)
zip_buffer = io.BytesIO()
with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(handler_dir):
        for file in files:
            filepath = os.path.join(root, file)
            zf.write(filepath, os.path.relpath(filepath, handler_dir))

# 2. Upload to S3 (direct upload caps at 50MB; bundles exceed it). Set the bucket
#    defaults rather than trusting the caller: the bundle is customer evaluation code.
bucket = f"agentcore-lambda-{account_id}-us-east-1"
s3_client.put_bucket_encryption(
    Bucket=bucket,
    ServerSideEncryptionConfiguration={"Rules": [{
        "ApplyServerSideEncryptionByDefault": {
            "SSEAlgorithm": "aws:kms", "KMSMasterKeyID": s3_kms_key_arn},
        "BucketKeyEnabled": True,
    }]},
)
s3_client.put_bucket_policy(
    Bucket=bucket,
    Policy=json.dumps({"Version": "2012-10-17", "Statement": [{
        "Sid": "DenyNonTLS", "Effect": "Deny", "Principal": "*", "Action": "s3:*",
        "Resource": [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"],
        "Condition": {"Bool": {"aws:SecureTransport": "false"}},
    }]}),
)
s3_client.put_object(Bucket=bucket, Key=f"{function_name}.zip",
                     Body=zip_buffer.getvalue(),
                     ServerSideEncryption='aws:kms')

# 3. Create the log group FIRST, with a KMS key. Lambda creates an unencrypted group on
#    first invoke otherwise, and evaluation inputs and outputs — customer traces, prompts
#    and model responses — are written there in full.
logs_client = boto3.client("logs", region_name="us-east-1")
log_group = f"/aws/lambda/{function_name}"
logs_client.create_log_group(logGroupName=log_group, kmsKeyId=logs_kms_key_arn)
logs_client.put_retention_policy(logGroupName=log_group, retentionInDays=30)

# 4. Create the function (x86_64 to match the bundled wheels)
lambda_arn = lambda_client.create_function(
    FunctionName=function_name,   # {project}-eval-{evaluator}, as the CDK names it; ≤64 chars
    Runtime="python3.12",
    Handler="lambda_function.handler",
    Code={"S3Bucket": bucket, "S3Key": f"{function_name}.zip"},
    Role=role_arn,
    Timeout=300,
    MemorySize=1024,
    Architectures=["x86_64"],
)["FunctionArn"]

# 5. Register it as an AgentCore evaluator
created = client._cp_client.create_evaluator(
    evaluatorName=evaluator_name,
    evaluatorConfig={"codeBased": {"lambdaConfig": {"lambdaArn": lambda_arn}}}
)

# 6. Let AgentCore invoke it, scoped to this evaluator. The CDK path grants this
#    automatically; a hand-built function has none and is never invoked.
lambda_client.add_permission(
    FunctionName=function_name,
    StatementId="AgentCoreEvaluatorInvoke",
    Action="lambda:InvokeFunction",
    Principal="bedrock-agentcore.amazonaws.com",
    SourceAccount=account_id,
    SourceArn=created["evaluatorArn"],
)
```

Deploy-then-verify still applies: deploy ONE, test with a single `evaluate()`
call, then deploy the rest. Code-only fixes go through
`update_function_code()` (2 steps), never a full redeploy.

## CDK Architecture Fix (x86_64 Hosts)

**TWO separate patches required:**

```bash
# Patch 1: Package bundling (uv downloads x86_64 wheels)
PYTHON_JS=$(find $DEPLOY_DIR -path "*/agentcore-cdk/dist/lib/packaging/python.js")
[ -n "$PYTHON_JS" ] && sed -i "s/aarch64-manylinux/x86_64-manylinux/g" "$PYTHON_JS"

# Patch 2: Lambda architecture — search ALL of dist/, not dist/lib/.
# On CLI 0.24.x the hardcoded ARM_64 lives in dist/cdk/constructs/AgentCoreEvaluator.js;
# a dist/lib-only search silently misses it.
for f in $(grep -rlE "ARM_64|'arm64'|\"arm64\"" $DEPLOY_DIR/agentcore/cdk/node_modules/@aws/agentcore-cdk/dist/ 2>/dev/null); do
    sed -i -e 's/ARM_64/X86_64/g' -e "s/'arm64'/'x86_64'/g" -e 's/"arm64"/"x86_64"/g' "$f"
done
```

Patch 1 alone → arm64 Lambda with x86_64 packages → `ImportError: pydantic_core`.
Patch 2 alone → x86_64 Lambda with arm64 packages → same error.
Generated `migration.sh` (scripts/deployer.py) already applies both patches with the
full-`dist/` search — only apply these by hand if you wrote your own deploy script.

**Post-deploy verification** (boto3, so no aws CLI is needed):

```bash
python3 -c "import boto3; print(boto3.client('lambda').get_function_configuration(FunctionName='$FUNC')['Architectures'])"
# If still "arm64":
python3 -c "import boto3; boto3.client('lambda').update_function_configuration(FunctionName='$FUNC', Architectures=['x86_64'])"
```

## Gotchas

| Agent might think... | But actually... | Instead... |
|---|---|---|
| "I'll write both score files from one evaluator" | Cheating. The point is comparing ORIGINAL vs AgentCore. | Run original script for before, `_agentcore.py` for after |
| "I'll map Phoenix/RAGAS/DeepEval to AgentCore builtins" | Builtins are Strands-only. Different prompts/scales. | Deploy as custom LLM-as-a-Judge or code-based Lambda |
| "I'll import the skill's helpers as a package in the Lambda" | The helpers ship as skill scripts, not an installable package | Use `bedrock_agentcore` + `strands_evals` only. Read skill helpers for reference, don't import from them at runtime |
| "I'll use `aws` CLI to check credentials" | May not be installed | Use `boto3.client('sts').get_caller_identity()` |
| "I need to deploy for Strands Evals migrations" | Named evaluators map to builtins directly | Just reference by `Builtin.*` ID |
| "I'll hand-write the client script before deploying" | Don't hand-write it either way — `generate_client_script.py` emits it in one command, so there is no wasted work to avoid | Follow SKILL.md's order: generate the script in Step 3, deploy in Step 4, then paste each returned `evaluatorId` into the script's `EVALUATORS` dict |
| "I'll use `client.evaluate()`" | No public `evaluate()` on EvaluationClient | Use `client._dp_client.evaluate()` for data-plane calls |
| "I'll use `client._dp_client.list_evaluators()`" | Listing is control-plane | Use `client._cp_client.list_evaluators()` |
| "ToolResponseHandling just needs tool data" | Phoenix evaluates ONE tool response; AgentCore sees full conversation | Test inputs that trigger exactly ONE tool call |
| "I'll read full agent output" | Can exceed 60KB with search tools | Use `2>&1 \| tail -50` |
| "I found an existing evaluator, I'll reuse it" | Reusing masks prompt drift; stale evaluators may have outdated prompts/scales | Deploy fresh with UUID prefix. Ask "Keep them? [y/N]" — default deletes stale ones; `EVAL_MIGRATION_AUTO_APPROVE=1` keeps them and deploys alongside |
| "I'll use `evaluationLevel=` in create_evaluator_and_wait" | SDK kwarg is `level`, not `evaluationLevel` | Use `level="TRACE"` (or `"TOOL_CALL"` for tool evaluators) |
| "I'll delete the old evaluator without asking" | In concurrent environments, you may delete another run's evaluator | Deploy fresh with UUID prefix. Only delete evaluators matching YOUR prefix |
| "I'll call DeepEvalAdapter locally to skip Lambda deployment" | Bypasses AgentCore entirely — the point is migrating TO managed infrastructure | Deploy `DeepEvalAdapter` as Lambda handler via `@custom_code_based_evaluator()` + CLI, then invoke via `_dp_client.evaluate()` |
| "The original returns 0.0 but my judge returns 1.0 — that's 'correct'" | Fidelity does not care who is semantically right. abs(0.0 - 1.0) = 1.0 = FAIL | Match the original's behavior exactly, including scoring 0.0 when data is absent |
| "CrewAI just needs ChatBedrock" | CrewAI 1.15+ requires its own `crewai.LLM` class with litellm string | Create minimal fixed copy with `from crewai import LLM; llm = LLM(model="bedrock/...")` |
| "Lambda deployment failed, let me debug CloudFormation state" | CF debugging burns 10-20 steps and often fails again due to shared stacks or prior state | Read the error message. Apply the known fix (delete stuck stack, patch platform, clean disk). Retry once. If same error recurs, STOP and report to user |
| "I'll use the same evaluator name as the task prefix" | Concurrent runs of the same task will collide — one run deletes another's evaluators | Always use a UUID prefix: `f"{uuid.uuid4().hex[:8]}_{task}_{metric}"` |
| "I'll delete all existing evaluators matching my task before deploying" | In concurrent environments, you may be deleting evaluators deployed by a parallel run | Only delete evaluators matching YOUR UUID prefix. In auto-approve mode, keep others and deploy fresh alongside |
| "The `third_party` submodule isn't available, let me find the right version" | Some PyPI wheel versions don't include it. Exploring versions wastes many steps | Pin `bedrock-agentcore==1.23.0` in pyproject.toml. If still missing after 1 attempt, write a custom handler using the `@custom_code_based_evaluator()` decorator directly |
| "I only need DEEPEVAL_HOME env var in Lambda handler" | DeepEval also checks `DEEPEVAL_CACHE_FOLDER` via `constants.py` at import time | Set BOTH `DEEPEVAL_HOME` AND `DEEPEVAL_CACHE_FOLDER` to `/tmp/.deepeval` BEFORE any deepeval imports |
| "I'll check mise/nvm before installing Node.js" | In container environments, neither exists. Wastes 2-3 steps discovering this | Run `apt-get update && apt-get install -y nodejs npm` directly. Only try alternatives if apt fails |
| "CDK arm64 Lambda is fine since my code is pure Python" | pydantic_core and other C extensions need matching architecture | Check `uname -m` before deploying. If x86_64 host, patch CDK to deploy x86_64 Lambda |
| "The evaluator name can be any descriptive string" | Pattern: `^[a-zA-Z][a-zA-Z0-9_]{0,47}$` (max 48 chars). Violations cause deployment failures | Use `scripts/names.py` which enforces length limits and valid patterns |
| "DeepEval metrics will work in Lambda with defaults" | `async_mode=True` conflicts with Lambda event loop → score 0.0 | Set `async_mode=False` on ALL metrics |
| "Lambda has Bedrock access by default" | Execution role needs explicit `bedrock:InvokeModel` permission | Add IAM policy after deployment |
| "I'll resolve evaluator IDs by the BARE name at runtime" | Bare-name fragments match stale evaluators from other runs | Resolve by the project-scoped fragment `{project}_{evaluator-name}` |
| "CDK arm64 Lambda is fine since python.js was patched" | python.js controls package bundling, NOT Lambda architecture | Also patch `AgentCoreEvaluator.js`: `Architecture.ARM_64` → `Architecture.X86_64` |
| "apt-get install nodejs is sufficient" | May install old version (v12) or miss npm entirely | Fall back to `mise`/`nvm` at an exact version, or the checksum-verified tarball in [Node.js Installation](#nodejs-installation-robust-fallback-chain) |
| "I'll debug CloudFormation ROLLBACK_COMPLETE state" | CF debugging burns 10-20 steps; usually wrong approach | `aws cloudformation delete-stack`, wait, delete the `/aws/lambda/<project>-eval-*` log groups it left behind, then redeploy from scratch |
| "I need DEEPEVAL_HOME only" | DeepEval also checks DEEPEVAL_CACHE_FOLDER at import time | Set BOTH to `/tmp/.deepeval` before any deepeval imports |
| "I'll pin bedrock-agentcore>=1.15.0 in Lambda pyproject.toml" | `>=` can resolve to a release with no `third_party` package → `ImportError` at runtime | Pin exactly: `bedrock-agentcore==1.23.0`, which ships every adapter including ragas |
| "I need a git URL, so I'll strip `--only-binary :all:` from CDK's python.js" | Nothing is installed from source any more — every adapter ships in the pinned `bedrock-agentcore` wheel, and the one package PyPI cannot serve as a wheel (`rouge-score`) is prebuilt on demand. Stripping the flag lets uv build arbitrary sdists at bundle time for no benefit | **Leave the flag in place.** If a dependency will not resolve, prebuild a wheel for it — never relax the constraint |
| "uv will be available because Python is installed" | `uv` is a separate tool not bundled with Python. CDK needs it for Lambda package bundling | Install explicitly: `pip install 'uv==0.12.10' && uv --version` in Step 0 pre-flight |
| "AmazonBedrockModel takes model_name= kwarg" | The correct kwarg is `model=` (not `model_name=`), and `region=` is also REQUIRED | `AmazonBedrockModel(model="us.anthropic.claude-sonnet-4-5-20250929-v1:0", region="us-east-1")` |
| "I'll fix Lambda issues by redeploying from scratch each time" | Full CDK redeploy costs 10-15 steps per iteration, quickly exhausting budget | Use `lambda_client.update_function_code()` for code-only fixes (wrong model kwarg, async_mode, Turn vs LLMTestCase). Only full redeploy for dependency changes |
| "I'll deploy all Lambda evaluators then test them all at once" | If the first Lambda has a packaging bug, all will fail the same way — wasting debug time | Test ONE Lambda immediately after deploy. If it works, the others will too. If it fails, fix before deploying the rest |
| "DeepEvalAdapter imported locally so it'll work in Lambda" | Local env may differ from what Lambda resolves | Pin `bedrock-agentcore==1.23.0` explicitly in the Lambda pyproject.toml; never rely on `>=` |
