# Training Jobs

Launch, monitor, and diagnose SageMaker training jobs with SageMaker Python SDK v3. This capability covers serverful recipes, zero-config JumpStart traditional ML, BYO source/container/algorithm jobs, and training-job debugging.

## When to use

Use this capability when the user asks to:

- fine-tune with a pre-built/custom recipe, reserved capacity/training plan, or distributed compute
- train XGBoost, LightGBM, CatBoost, sklearn, or another JumpStart traditional ML model
- run `train.py`, a custom ECR image, or a Marketplace algorithm on managed training compute
- diagnose a failed, stopped, or stuck SageMaker training job

For ordinary managed serverless SFT/DPO/RLVR/RLAIF requests without those signals, use `finetuning`.

## Training surface decision

| Intended outcome | Use |
|---|---|
| Managed serverless SFT/DPO/RLVR/RLAIF with SageMaker's customization experience | `finetuning` and its `SFTTrainer`/technique-specific flow |
| A serverful recipe that controls launcher/distribution/runtime on explicit training instances | This reference with `ModelTrainer.from_recipe` |
| Traditional ML from JumpStart, or BYO script/image/algorithm | This reference |

Both `SFTTrainer` and recipe training can accept a `Compute` object. The deciding factor is the requested workflow and artifact contract, not the presence of `Compute`: use `SFTTrainer` for the managed customization workflow and `ModelTrainer.from_recipe` when the user explicitly needs a published/custom serverful recipe or its distributed runtime.

## Operating assumptions

| Area | Assumption |
|---|---|
| Runtime | Python supported by `sagemaker>=3.22.0,<4.0`; dependencies are installed by the generated template |
| Credentials | Ambient AWS credentials plus a SageMaker execution role; caller needs `sagemaker:CreateTrainingJob`, `sagemaker:DescribeTrainingJob`, `sagemaker:ListTrainingJobs`, S3/ECR access as applicable, and `iam:PassRole` |
| Storage | Small source/config files may be local under the project directory; datasets, checkpoints, recipes, and model artifacts use S3 |
| Region | Resolve from the current AWS session; verify model/recipe, compute, quota, image, and S3 resources in that region |
| Network | PyPI access is needed for installation; the job needs the AWS endpoints and any image/package endpoints its code uses |

## Decision flow

1. Check conversation and project files before asking for values.
2. Choose exactly one launch branch:
   - **Recipe/serverful LLM** → `code_templates/recipe_training.py`
   - **JumpStart traditional ML** → `code_templates/jumpstart_training.py`
   - **BYO source, image, or algorithm** → `code_templates/custom_training.py`
   - **Existing job failure/status** → `references/troubleshooting.md`
3. For JumpStart, hand off model discovery to `model-selection`; use the exact Hub model ID/version it returns. If direct CLI verification is needed, use `aws sagemaker list-hub-contents` and `aws sagemaker describe-hub-content`. Never invent IDs or silently select a different version.
4. For recipes, search the [SageMaker HyperPod recipes catalog](https://github.com/aws/sagemaker-hyperpod-recipes/) or use a user-provided YAML. Inspect the selected schema and call `get_resolved_recipe()` before approval; never invent recipe names or override keys.
5. For custom jobs, require exactly one of a versioned/digest-pinned training image URI or an algorithm name/ARN.

## Recipe configuration precedence

`ModelTrainer.from_recipe` loads the base recipe, applies `recipe_overrides`, and derives source code, image, distributed settings, compute details, and hyperparameters. The explicit `Compute` argument is required, but only `INSTANCE_TYPE` must be supplied by this template. Leave `INSTANCE_COUNT` and `VOLUME_SIZE_GB` as `None` to preserve the selected recipe/SDK defaults; set them only from confirmed user inputs when an explicit override is required. `TRAINING_PLAN_ARN`, when set, is also an explicit compute override. Direct constructor inputs such as networking, stopping condition, output, checkpoint, role, and base job name are then applied to the trainer. Review `get_resolved_recipe()` output before launch so the user can see the final merged configuration.

General published recipes may resolve their image. Nova and LLM fine-tuning recipe families require an explicit, verified `training_image`; use a supported, versioned URI from the selected recipe/provider documentation rather than `latest`. Verify the selected recipe's requirements because recipe contracts may change.

## Gather inputs

Use cascading fallback: conversation → project files → ask one unresolved question at a time.

| Input | Recipe | JumpStart | Custom |
|---|---:|---:|---:|
| Recipe name/YAML | Required | — | — |
| JumpStart model ID/version | — | Required | — |
| Training image or algorithm | Recipe-dependent | Resolved by config | Required |
| Source directory/entry script | Optional | Optional override | Optional |
| Training S3 URI | If recipe needs it | Required | Required if algorithm needs it |
| Instance type/count | Required | Optional override | Required |
| Training plan ARN | Optional | Optional | Optional |
| Role and output S3 URI | Required | Required | Required |
| Hyperparameters/recipe overrides | Optional | Optional | Optional |
| Checkpoint, VPC, encryption | Optional, only when requested/required | Optional | Optional |
| Max runtime | Required spend bound | Required spend bound | Required spend bound |

A code-level `accept_eula` switch exists only on `JumpStartConfig`. Set it to `True` only after the user explicitly accepts the gated model license. Recipe licenses and prerequisites are recipe/provider-specific; surface and confirm them before launch rather than claiming that an EULA flag is propagated by `from_recipe`.

## Preflight and confirmation

Before generating code or submitting a job:

1. Verify region, role trust, S3 region, image/algorithm/recipe existence, and service quota for requested compute.
2. If quota is insufficient, report the exact requested/current values and explain how to request an increase without submitting one: open [Service Quotas](https://console.aws.amazon.com/servicequotas/home/services/sagemaker/quotas), choose the target Region, find the SageMaker quota matching the job type and instance type, select **Request increase**, enter the required value and use-case rationale, then monitor request history. For CLI users, first discover the matching quota code with `aws service-quotas list-service-quotas --service-code sagemaker --region <region>`; only draft `request-service-quota-increase` after the user confirms the quota code and desired value. Do not submit a request, silently switch compute, or downsize without approval.
3. Validate optional checkpoint, VPC/security groups, output KMS key permissions, network isolation implications, and inter-container encryption only when selected.
4. Summarize model/recipe/image, input/output, instance type/count, training plan, max runtime, optional advanced settings, and wait behavior.
5. Link to [SageMaker pricing](https://aws.amazon.com/sagemaker/ai/pricing/) rather than calculating a dollar estimate.
6. Ask for explicit approval. Stop until approved.

## Generate and launch

1. Read `references/configuration.md` and the selected template.
2. Write the customized output under the project directory in notebook or script mode.
3. Keep `WAIT_FOR_COMPLETION=False` unless the user asks to block.
4. Templates create a collision-resistant job prefix, launch asynchronously, and resolve only that submission through public `ListTrainingJobs`/`DescribeTrainingJob` APIs. They do not use the SDK's private `_latest_training_job` state.
5. Report output model artifacts only after the job reaches `Completed`.

## Diagnose an existing job

Read `references/troubleshooting.md`. Start with `DescribeTrainingJob`, then inspect only the job's CloudWatch stream and relevant metrics. Return the failure signature, root cause category, evidence, and concrete fix; state what was not checked.

## Out of Scope

The following are supported by SageMaker and AWS but do not have a validated workflow in this reference. If the user's request matches one of these, let them know and proceed with best-effort guidance using general AWS knowledge:

- HyperPod job submission and cluster lifecycle
- Autopilot/AutoML job creation
- distributed configuration that requires custom launcher code beyond a published recipe
- every optional `CreateTrainingJob` field; templates intentionally expose only verified checkpoint, VPC, output-KMS, network-isolation, and traffic-encryption settings

## References

- `code_templates/recipe_training.py` — serverful pre-built/custom recipe
- `code_templates/jumpstart_training.py` — JumpStart zero-config traditional ML
- `code_templates/custom_training.py` — BYO source/image/algorithm
- `references/configuration.md` — placeholder and branch configuration
- `references/troubleshooting.md` — status and failure classification
- [SageMaker HyperPod recipes](https://github.com/aws/sagemaker-hyperpod-recipes/)
- [SageMaker Python SDK image URI utility](https://sagemaker.readthedocs.io/en/stable/api/utility/image_uris.html)
