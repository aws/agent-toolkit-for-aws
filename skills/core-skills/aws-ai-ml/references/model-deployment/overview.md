# Model Deployment

Identifies the correct deployment pathway based on model characteristics and generates deployment code. Also provides inference optimization sub-workflows for benchmarking endpoint performance and getting deployment recommendations.

## Scope

### Deployment (Steps 1–6)

This reference supports two families of deployment:

1. **Fine-tuned models** (Nova or OSS) that were fine-tuned through **SageMaker Serverless Model
   Customization** (LoRA) → SageMaker or Bedrock.
2. **Open-weight foundation (base) models from SageMaker JumpStart** → a SageMaker real-time
   endpoint. This path deploys the config the **model-selection** skill resolved (a flat dict with
   `model_id`, `instance_type`, `inference_config_name`, etc.) — not a training job.

### Inference Optimization (Step 0)

This reference also provides two independent optimization sub-workflows:

| Sub-workflow        | Purpose                                                                                | Model Requirements                                     |
| ------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| **Benchmarking**    | Measure inference performance (latency, throughput) on an existing SageMaker endpoint  | Any model on a SageMaker Managed Inference endpoint (see *Optimization applicability* below for scope) |
| **Recommendations** | Find the best instance type, serving config, and optimizations for deploying a model   | OSS base models only (no Nova, no LoRA)                |

**Optimization applicability** (where these validated sub-workflows apply — outside these bounds the sub-workflow can't help, but you can still assist from general AWS knowledge or other references; don't tell the user it's impossible):

- **Regions**: us-east-1, us-west-2, us-east-2, ap-northeast-1, eu-west-1, ap-southeast-1, eu-central-1. This list may change — confirm current availability in the [SageMaker AI Region availability docs](https://docs.aws.amazon.com/sagemaker/latest/dg/regions-quotas.html). This is the single source of truth for optimization region availability; other optimization references defer to this list.
- **Benchmarking**: SageMaker Managed Inference endpoints — OpenAI ChatCompletions-compatible out of the box, plus custom (non-OpenAI) formats via template mode. This is the single source of truth for benchmarking scope; other references defer here. Bedrock and SageMaker HyperPod use different hosting stacks — this workflow cannot benchmark them, so do **not** search for or attempt to benchmark Bedrock/HyperPod endpoints; if asked, explain the scope and offer general-knowledge guidance (e.g. bedrock-runtime metrics / CloudWatch) or benchmarking on a SageMaker endpoint instead.
- **Recommendations**: OSS base models in HuggingFace format (not Nova or LoRA adapters; deploys to SageMaker endpoints).

## Out of Scope

The following are supported by SageMaker and AWS but do not have a validated workflow in this reference. If the user's request matches one of these, let them know and proceed with best-effort guidance using general AWS knowledge:

- Deploying models fine-tuned outside SageMaker Serverless Model Customization (e.g., HyperPod-trained, BYO container, HuggingFace-trained models)
- Deploying Full Fine-Tuned (FFT) models
- Deploying a JumpStart foundation model to Bedrock (via Bedrock Marketplace or Custom Model Import)
- Traditional ML deployments (XGBoost, scikit-learn, BYO inference containers)
- HyperPod deployment

Note: Closed-source / proprietary foundation models (e.g. Anthropic Claude) are managed Bedrock models invoked directly via the Bedrock runtime — there is nothing to deploy; the user just calls the API.

## Prerequisites

- The SDK environment has been verified (SDK version, region, execution role). If not done, activate the `sdk-getting-started` reference first.

---

## Principles

1. **One thing at a time.** Each response advances exactly one decision.
2. **State your intent, don't re-ask.** When information is already available — from the conversation, from session/artifact lookups you can perform yourself (e.g. session default execution role, region, existing endpoints, model metadata), or from what the user has already told you — **look it up, state the values you'll use, and proceed** rather than making the user repeat or re-confirm the same input. If the user wants to change something, they'll say so. **This does not waive mandatory gates.** Always pause for *explicit* approval before: (a) an action with real cost or risk (sending load to a live endpoint, running a job that takes 30+ min), or (b) any required license / EULA acceptance for a gated or licensed model — see the deployment "Display License Agreement" step; a general "proceed" / "skip confirmation" instruction from the user does **not** count as license acceptance.
3. **Don't read files until you need them.** Only read pathway references after the pathway is confirmed.
4. **Use what you know.** If conversation history or artifacts already answer a question, confirm your understanding instead of asking again.

## Workflow

### Step 0: Optimization (only when the user asks for it)

Optimization has two sub-workflows: **benchmarking** (measure latency/throughput on an existing endpoint) and **recommendations** (find the best instance + serving config before deploying). **Default is plain deployment** — if the user asked to deploy a model without mentioning performance, benchmarking, cost/latency/throughput goals, or instance-choice help, go straight to Step 1 and do not enter optimization. Enter Step 0 only when the user's intent explicitly signals it (see the routing below).

**Constraints — when the optimization sub-workflows don't apply.** These bound the *validated benchmark/recommendation workflows only* — they don't limit deployment. If a constraint rules optimization out, skip the offer and continue with the deploy pathway (Step 1); if the user explicitly asked to optimize something out of scope, say the workflow can't drive it and help from general AWS knowledge instead — never a dead-end.

- **Benchmarking** applies to SageMaker Managed Inference endpoints only — **not** Bedrock or HyperPod (see *Optimization applicability* above for the canonical scope + the don't-search directive).
- **Recommendations** cover **OSS base models only** — not **Nova**, not proprietary models, and **not LoRA adapters** (base models only). They produce a config that deploys to **SageMaker endpoints, not Bedrock**. (A model that's already deployed to a SageMaker endpoint can still be **benchmarked**, regardless of how it was built.)
- The **region** isn't in the supported list (see *Optimization applicability* above).

Note that deploying **to Bedrock** (Nova or OSS LoRA via `BedrockModelBuilder`/CMI) is a fully supported deployment pathway in this reference — the optimization offer just doesn't apply to it, so go straight to the deploy pathway. (HyperPod deployment has no validated workflow here at all — see Out of Scope.)

**When to enter Step 0.** Only if the user's intent explicitly signals optimization:

- They asked to **benchmark**, **optimize**, **compare** runs, **load-test**, or measure performance → go straight to the sub-workflow.
- They stated a **performance / cost / latency / throughput goal** for a *new* deployment (e.g. "find the cheapest instance", "hit p99 under 200ms") → go to Step 0B (Recommendations).
- They asked for an **AI Recommendation Job**, or a cheaper or faster configuration for a model **already on an endpoint** (right-sizing) → go to Step 0B (Recommendations).
- Otherwise (plain "deploy my model" / "create an endpoint" / "make it available" with no perf or cost cues) → **skip Step 0 entirely, go to Step 1.** Do not "offer" optimization; the user can ask if they want it later.

**Route to the sub-workflow that fits what they have:**

- They have an **endpoint** (or just created one) and want to measure it, load-test it, run it on their own dataset/traffic, or compare runs → **Step 0A: Benchmark**.
- They have a **base model to deploy** (or a performance goal to hit) and want the best config first → **Step 0B: Recommendations**. The job takes an OSS base model from either source: the user's own **HF-format weights in S3**, or a **JumpStart base model** (via `from_jumpstart_config` + `build()`; works for ungated models — a gated one fails with *Access denied*, so stage its weights to S3 instead). For a HuggingFace-Hub model that isn't on JumpStart, first stage it to S3 (see `references/optimization/huggingface-to-s3.md`), then run recommendations on the S3 copy.
- They have an **endpoint** and want a better instance type or serving configuration for the model on it → **Step 0B: Recommendations**, with the model and workload taken from the endpoint (`references/optimization/workload-from-endpoint.md`).

#### Step 0A: Benchmark an Existing Endpoint

Read `references/optimization/benchmark-workflow.md` and follow its instructions.

#### Step 0B: Get Deployment Recommendations

Read `references/optimization/recommendation-workflow.md` and follow its instructions.

#### Optimization reference index (load only what the intent needs)

The `references/optimization/` folder has several files — **read only the one(s) for the current sub-workflow**, not all of them:

| Intent | Read |
|--------|------|
| Benchmark an endpoint / load test | `references/optimization/benchmark-workflow.md` (know-how in `benchmarking-guidance.md`) |
| Present / compare benchmark results | `references/optimization/interpreting-results.md` |
| Get deployment recommendations | `references/optimization/recommendation-workflow.md` (options in `recommendation-options.md`) |
| Size recommendations from a model already on an endpoint | `references/optimization/workload-from-endpoint.md` |
| Deploy a recommendation's ModelPackage | `references/optimization/recommendation-deploy.md` |
| Deploy a HuggingFace-Hub (non-JumpStart) model | `references/optimization/huggingface-to-s3.md` |

---

### Step 1: Identify the Model and its Source

First determine which family this is (infer from the conversation before asking):

- **JumpStart foundation (base) model** — the user wants to deploy an open-weight foundation model
  from SageMaker JumpStart (e.g. "deploy the Qwen3 0.6B JumpStart model", names a JumpStart model
  id, or asks for a base foundation model). There is **no training job**. The deployment config
  (`model_id`, `instance_type`, `inference_config_name`, etc.) comes from the **model-selection**
  skill — use it as-is; do not re-derive it. The `role_arn` and region are owned by this reference, not
  model-selection, and there is no training job to extract them from, so if either is not already
  known from the conversation, ASK the user for it. Then proceed to Step 2. Do not look for a training job.
- **Fine-tuned model** — the user is deploying a model they fine-tuned via SageMaker Serverless
  Model Customization. Continue with the training-job identification below.

#### Fine-tuned model: identify the training job

You need the training job name or ARN. Check the conversation history first — the user may have already mentioned it, or it may be available from earlier steps in the workflow (e.g., fine-tuning). If not, ask the user.

Once you have the training job name or ARN, use the AWS MCP tool to look it up:

1. Use the AWS MCP tool `describe-training-job` and extract:
   - **S3 output path** (from `ModelArtifacts.S3ModelArtifacts` or `OutputDataConfig.S3OutputPath`)
   - **IAM role ARN** (from `RoleArn`)
   - **Region**
2. Use the AWS MCP tool `list-tags` on the training job ARN and extract:
   - **Model ID** from the `sagemaker-studio:jumpstart-model-id` tag
3. Determine the **model type** from the model ID:
   - Contains "nova" (nova-micro, nova-lite, nova-pro) → **Nova**
   - Llama, Mistral, Qwen, GPT-OSS, DeepSeek, etc. → **OSS**

**Models without a validated workflow:** This reference has validated workflows for OSS and Nova models that were LoRA fine-tuned through SageMaker Serverless Model Customization. If the model doesn't match (e.g., FFT, BYO container, HuggingFace-trained, or HyperPod-trained), inform the user that this reference does not have a validated workflow for their model but you can help with general AWS knowledge. Proceed with best-effort guidance.

### Step 2: Determine Eligible Deployment Targets

Use the following table:

Note: This table covers this skill's validated workflows only. The user's request may be achievable through other AWS paths (e.g. Bedrock Custom Model Import) not covered here.

| Model Type                  | Eligible Targets   |
| --------------------------- | ------------------ |
| OSS (fine-tuned)            | SageMaker, Bedrock |
| Nova (fine-tuned)           | SageMaker, Bedrock |
| JumpStart foundation (base) | SageMaker          |

If only one target is eligible, confirm it with the user. Use details from Step 5.

If multiple targets are eligible, help the user decide. Use details from Step 5.

If no targets are eligible, tell the user and explain why.

### Step 3: Let the User Choose a Deployment Target

Present the eligible options to the user. Present these details to help them decide between SageMaker and Bedrock, if both are available options:

**SageMaker Endpoint:**

- Dedicated compute resources for consistent performance
- Control instance types and scaling
- Best for predictable workloads with specific latency requirements

**Bedrock:**

- Fully managed serverless inference
- Auto-scales instantly with no capacity planning
- Pay per request
- Best for variable workloads with fluctuating demand

Do NOT make a recommendation. Let the user choose.

Do NOT mention technical details like merged/unmerged weights, reference files, or APIs, unless the user asks.

⏸ Wait for user to select a deployment option.

### Step 4: Display License Agreement

Before generating any code, present the model's license or service terms to the user and wait for confirmation.

**Always perform this step for the deployment, even if the model's license was already shown or accepted earlier in the conversation** (e.g. during model selection, fine-tuning, or evaluation). Deployment is a distinct action and requires its own explicit license/terms confirmation before any deployment code is generated. Do NOT skip this step or generate code by citing an earlier acceptance — re-present the license and wait for the user to confirm again.

**A user instruction to "proceed without asking", "skip confirmation", "deploy now", or similar does NOT constitute license acceptance.** Such instructions waive the deployment-configuration confirmation, not the license gate. For a gated model you must still present the license and obtain *explicit* acceptance (e.g. "yes, I accept the license") before generating any code or setting `accept_eula=True`. Never infer acceptance from a general "proceed" instruction, and never auto-accept on the user's behalf.

1. Read `references/model-licenses.md` and look up the model by its model ID (determined in Step 1).
2. Follow the instructions in the Notes column — use the exact phrasing provided. End your response there. Do not generate code in this step.
3. If the model ID is not found in the table, warn the user that you could not find license information for their model and recommend they verify the license independently before proceeding.

   ⏸ Wait for the user to confirm before proceeding.

4. Once the user confirms, continue to Step 5 to follow the pathway workflow and generate the deployment code.

### Step 5: Follow Pathway Workflow

Read the reference file for the selected pathway and follow its instructions.

| Model Type                  | Deployment Target | Reference                                   |
| --------------------------- | ----------------- | ------------------------------------------- |
| OSS (fine-tuned)            | SageMaker         | `references/deploy-oss-sagemaker.md`        |
| OSS (fine-tuned)            | Bedrock           | `references/deploy-oss-bedrock.md`          |
| Nova (fine-tuned)           | SageMaker         | `references/deploy-nova-sagemaker.md`       |
| Nova (fine-tuned)           | Bedrock           | `references/deploy-nova-bedrock.md`         |
| JumpStart foundation (base) | SageMaker         | `references/deploy-jumpstart-sagemaker.md`  |

### Step 6: Post-Deployment Summary

After deployment completes, provide the user with a summary. Cover these topics, using details from the pathway reference doc you followed in Step 5:

- **What was deployed** — endpoint or model name, ARN, status
- **How to use it** — sample invoke code for the specific deployment target
- **Cost** — billing model (instance-based vs. pay-per-request) and what to expect
- **Cleanup** — how to delete the endpoint or model when done

## Troubleshooting

### How to check if a model was LoRA or FFT fine-tuned

If deployment fails unexpectedly, the model may have been full fine-tuned (FFT) rather than LoRA. To check, download the training job's hydra config from its S3 output path at `.hydra/config.yaml`:

- `peft_config` populated (r, alpha, dropout, etc.) → **LoRA** (validated workflow available)
- `peft_config: null` → **FFT** (no validated workflow in this reference — proceed with best-effort guidance)
