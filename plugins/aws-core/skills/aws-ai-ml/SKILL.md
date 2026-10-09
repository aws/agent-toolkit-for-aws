---
name: aws-ai-ml
description: >
  Selects, deploys, and customizes AI models on Amazon SageMaker. Training or
  Processing jobs, fine-tuning (SFT/DPO/RLVR/RLAIF), model selection, dataset
  preparation, evaluation, SageMaker or Bedrock deployment, inference
  optimization and endpoint diagnostics. Covers the full lifecycle from planning
  through production. Use when fine-tuning models on SageMaker, choosing which
  base model to customize, fine-tune, or deploy from SageMaker JumpStart or Hub,
  SageMakerPublicHub, or the SageMaker public model catalog, transforming or
  validating training data, evaluating model quality, deploying or optimizing
  endpoints, configuring IAM/S3 for training, or managing SageMaker Managed
  MLflow. Use for endpoint health, failures, latency, logs, metrics, errors.
  Covers Serverless Model Customization, Nova and OSS deployment paths, and
  PySDK v3. NOT for Ground Truth labeling, Feature Store, or general-purpose AWS
  infrastructure.
metadata:
  version: "5"
---

# AWS AI/ML Model Customization

Domain expertise for fine-tuning and deploying models on Amazon SageMaker. Covers the full model customization lifecycle from planning through production deployment.

## Routing

Match the user's intent to the appropriate reference folder and load only that content.

| User intent | Reference | When to use |
|-------------|-----------|-------------|
| Plan a model customization project, discover scope of work, resume or modify a plan | [references/planning/](references/planning/) | User's request relates to model customization or deployment (fine-tuning, training, building, customizing, reviewing data, deploying or standing up a model — including selecting or deploying an off-the-shelf or base model with no training — or getting advice on approach). Always co-activate with other intents to discover full scope. Load this reference FIRST when the request matches multiple rows in this table — read its plan templates before routing to a single-action reference. |
| Define the business problem, success criteria, or use case spec | [references/use-case-specification/](references/use-case-specification/) | User says "define my use case", "capture requirements", "what should I decide up front", or as default first step in any plan. Skip only if user explicitly declines. |
| Select or change a base model | [references/model-selection/](references/model-selection/) | User asks which model to use, mentions a model name or family, or wants to evaluate what's available. **Always activate model-selection even for known model names** because the exact Hub model ID must be resolved. **Recommended:** route to use-case-specification first to capture requirements — this produces better filtering results. Routing to use-case-specification first is not required if user provides a specific model name/ID or declines. If intent is ambiguous (fine-tune vs deploy as-is), model-selection MUST confirm which path before proceeding. Base model filtering for deployment MUST go through select-for-deployment.md and its scripts for any final recommendation. |
| Choose a fine-tuning technique (SFT, DPO, RLVR, RLAIF) | [references/finetuning-technique/](references/finetuning-technique/) | User has decided to fine-tune and needs to choose a technique, or technique needs validation against the selected model's recipes. Requires a base model to be selected first. |
| Validate dataset quality and format | [references/dataset-evaluation/](references/dataset-evaluation/) | User says "is my dataset okay", "check my training data", "I have my own data", or before starting any fine-tuning job. |
| Transform or convert a dataset between formats | [references/dataset-transformation/](references/dataset-transformation/) | User says "transform", "convert", "reformat", or dataset schema needs to change. Always use this rather than writing inline transformation code. |
| Generate fine-tuning code and start training | [references/finetuning/](references/finetuning/) | User says "start training", "fine-tune my model", "I'm ready to train", or plan reaches the finetuning step. Supports SFT, DPO, RLVR, RLAIF trainers. |
| Train a model with a SageMaker Training job | [references/training-jobs/](references/training-jobs/) | Use when the goal is to fit or update model parameters and produce model artifacts or checkpoints. Covers recipes, JumpStart traditional ML, custom training scripts or containers, distributed training, and training-job diagnosis. |
| Process data with a SageMaker Processing job | [references/processing-jobs/](references/processing-jobs/) | Use when the goal is preprocessing, feature engineering, evaluation, transformation, or ETL without model training as the primary operation. Covers scripts, framework processors, Spark, custom containers, Athena, Redshift, and processing-job diagnosis. |
| Evaluate or benchmark a trained model | [references/model-evaluation/](references/model-evaluation/) | User says "evaluate my model", "run a benchmark", "test model performance", "compare models". Supports LLM-as-Judge and Custom Scorer. |
| Deploy, benchmark, or optimize a model on an endpoint or Bedrock | [references/model-deployment/](references/model-deployment/) | User says "deploy my model", "create an endpoint", or "make it available" (plain deploy) — or, for the inference-optimization sub-workflows on SageMaker Real-Time Endpoints only, "benchmark my endpoint" / "compare benchmark runs" (benchmarking), or states a performance/cost/latency/throughput goal for a new deployment such as "find the cheapest instance" (recommendations). Handles Nova vs OSS deployment pathways. |
| Set up IAM roles, S3 buckets, SDK configuration | [references/sdk-getting-started/](references/sdk-getting-started/) | User says "set up", "getting started", "check my environment", "configure SDK", or as first step in any plan involving SageMaker training/evaluation/deployment. |
| Manage project directory and artifacts | [references/directory-management/](references/directory-management/) | Starting a new project, resuming existing one, or when PLAN.md needs to be associated with a project directory. |
| Set up, update, or delete a SageMaker Managed MLflow app | [references/manage-mlflow/](references/manage-mlflow/) | User says "set up MLflow", "create MLflow app", "update my MLflow app", "delete my MLflow app", "I need an MLflow server", asks "what is SageMaker MLflow", or a workflow needs an MLflow backend and none is connected. |
| Diagnose a failing or unhealthy SageMaker endpoint | [references/endpoint-diagnostics/](references/endpoint-diagnostics/) | User reports endpoint errors, latency, inference failures, or a deployment that failed. "What's the status of my endpoint?", "Is my endpoint erroring?", "My endpoint failed — why?", "How many instances are running behind my endpoint?", "Is the latency my model or SageMaker?", "Show me the container logs for my endpoint." NOT for training-job issues, endpoint deletion, scaling changes, or new deployments. |

## Rules

- **Service boundary.** This skill covers SageMaker, including deployment of a customized model to Bedrock. Bedrock-native work (invoking Bedrock's managed foundation models, Bedrock Agents, Knowledge Bases, Guardrails, AgentCore) is supported by AWS but has no validated workflow in this skill: let the user know and proceed with best-effort guidance using general AWS knowledge. If the user asks for a model on AWS without naming a service, compare SageMaker and Bedrock or ask one service-choice question. Do not select a service by default. The two services have different model catalogs, deployment paths, and pricing, and a default selection can send the user into an incorrect workflow.
- **Progressive disclosure.** Load only the reference folder relevant to the current user intent. Do not load all references at once.
- **Best-effort help.** If the user's request falls outside this skill's references, do not dead-end the conversation. Help them using general AWS knowledge and documentation, and inform the user that the guidance is not covered by this skill's validated workflows.
- **Usage attribution.** Before running any AWS CLI command or packaged script, set `export AWS_SDK_UA_APP_ID=AWSSkill-SageMaker`.
