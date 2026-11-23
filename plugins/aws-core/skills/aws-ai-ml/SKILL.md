---
name: aws-ai-ml
description: >
  Selects, deploys, and customizes AI models on Amazon SageMaker. Training or
  Processing jobs, fine-tuning (SFT/DPO/RLVR/RLAIF), model selection,
  evaluation, SageMaker or Bedrock deployment, inference optimization and
  endpoint diagnostics. Use when fine-tuning models on SageMaker, choosing a
  base model to customize or deploy from SageMaker JumpStart or Hub,
  SageMakerPublicHub, or the model catalog, checking data quality (duplicates,
  languages, PII), transforming or validating data (reformat, clean, filter,
  dedupe, split, merge, redact), generating synthetic data, labeling data with a
  model, human review or annotation and applying its corrections, evaluating
  model quality, deploying or optimizing endpoints, configuring IAM/S3, or
  managing SageMaker Managed MLflow. Use for endpoint health, latency, logs,
  metrics, errors. Covers Serverless Model Customization, Nova and OSS
  deployment paths, and PySDK v3. NOT for SageMaker Ground Truth labeling jobs,
  Feature Store, or general AWS infrastructure.
metadata:
  version: "8"
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
| Validate dataset quality and format, run quality metrics, assess diversity or toxicity | [references/dataset-quality/](references/dataset-quality/) | **MUST LOAD** when the user wants to check, validate, or evaluate a dataset. It checks the dataset's format, runs one dataset quality evaluation job (built-in metrics and spec-driven checks) and ends in a report; duplicate questions go to its deduplication sub-reference (removing duplicates stays with dataset-transformation), composition questions to its taxonomy sub-reference (us-east-1 only). This is the ONLY validated workflow for dataset quality; do not attempt it from general knowledge. Use when the user says "is my dataset okay", "check my training data", "check data quality", "run DQ metrics", "how good is my training data", "check diversity", "check toxicity", "what languages are in my dataset", "is my data all English", "does my data contain PII", "run a scorecard", "I have my own data", "evaluate my dataset", "quality evaluation", "find duplicates", "how many duplicates", "near-duplicates", "audit duplicates before removing", "what's in my dataset", "what topics does my data cover", "taxonomy of my data", "is my data balanced across tasks", or before starting any fine-tuning job. |
| Transform, deduplicate, split, merge, filter, convert schema, or clean a dataset (CodeGen, built-in operations, or BYOC) | [references/dataset-transformation/](references/dataset-transformation/) | User says "transform", "custom transform", "convert", "reformat", "deduplicate", "remove duplicates", "dedupe", "split", "partition", "train/validation/test split", "propose a train/eval/holdout split", "merge", "combine datasets", "filter", "keep only English rows", "filter by language", "remove PII", "redact personal data", "clean", "normalize", "fix encoding", "convert schema", "derive a field", "edit field values", "bring my own code", "run my transformer.py", "run this transformation locally", or asks to replace awk/sort/uniq/jq for a local or S3 dataset. Covers CodeGen, BYOC, and the built-in DataTransformation operators described by the live schema and operator mapping. Always route here instead of writing an ad-hoc transformation script or shell one-liner. |
| Generate synthetic data for training, database seeding, augmentation, tabular data, or any use case requiring realistic generated data | [references/synthetic-dataset-generation/](references/synthetic-dataset-generation/) | User says "generate data", "synthetic data", "create training data", "augment data" / "I need more data", "seed database", "mock/fake data (rows, CSV, Parquet, SQLite)", or "generate N rows / records / a dataset". Can run standalone for non-training use cases. |
| Set up human annotation or review cycles via local chat review or Label Studio | [references/human-in-the-loop/](references/human-in-the-loop/) | **MUST LOAD** when user mentions annotation, human review, Label Studio, or applying annotations. Triggers: "set up annotation", "review samples", "set up Label Studio", "annotations are done", "summarize annotation results", "apply the annotations", "incorporate human feedback", "human review", "manual review", "annotate my data", "need human feedback", "annotation project", "annotators", "labeling team", "annotation spec", "corrections from annotators". This reference contains the ONLY validated workflow for human annotation — do not attempt annotation setup from general knowledge. Does NOT modify the dataset directly — always delegates edits to dataset-transformation. |
| Automatically label unlabeled data with a labeling spec and a model jury | [references/auto-labeling/](references/auto-labeling/) | **MUST LOAD**; the only validated workflow for labeling by a model. Load when the user mentions labeling, tagging or classifying data at scale, a labeling spec, a refinement loop, or which spec ships, even without the word "label". When people will label or review the rows themselves ("have my team label this", "annotators", "annotate my data"), route to human-in-the-loop instead; auto-labeling hands its own review set there. Triggers: "label my data", "label my dataset", "auto-label", "classify my samples", "I have unlabeled data", "NER tagging", "sentiment labeling", "tag each", "label the rest", "labeling spec", "refine my labeling", "refine my spec", "run the refinement loop", "which spec do I ship", "measure labeling accuracy", "label corpus", "confidence routing", "tag support tickets", "label these rows". |
| Generate fine-tuning code and start training | [references/finetuning/](references/finetuning/) | User says "start training", "fine-tune my model", "I'm ready to train", or plan reaches the finetuning step. Supports SFT, DPO, RLVR, RLAIF trainers. |
| Train a model with a SageMaker Training job | [references/training-jobs/](references/training-jobs/) | Use when the goal is to fit or update model parameters and produce model artifacts or checkpoints. Covers recipes, JumpStart traditional ML, custom training scripts or containers, distributed training, and training-job diagnosis. |
| Process data with a SageMaker Processing job | [references/processing-jobs/](references/processing-jobs/) | Use when the goal is preprocessing, feature engineering, evaluation, transformation, or ETL without model training as the primary operation. Covers scripts, framework processors, Spark, custom containers, Athena, Redshift, and processing-job diagnosis. |
| Evaluate or benchmark a trained model | [references/model-evaluation/](references/model-evaluation/) | User says "evaluate my model", "run a benchmark", "test model performance", "compare models". Supports LLM-as-Judge and Custom Scorer. |
| Deploy, benchmark, or optimize a model on an endpoint or Bedrock | [references/model-deployment/](references/model-deployment/) | User says "deploy my model", "create an endpoint", or "make it available" (plain deploy) — or, for the inference-optimization sub-workflows on SageMaker Real-Time Endpoints only, "benchmark my endpoint" / "compare benchmark runs" (benchmarking), or states a performance/cost/latency/throughput goal for a new deployment such as "find the cheapest instance", or asks for an AI Recommendation Job or to right-size a model already on an endpoint (recommendations). Handles Nova vs OSS deployment pathways. |
| Set up IAM roles, S3 buckets, SDK configuration | [references/sdk-getting-started/](references/sdk-getting-started/) | User says "set up", "getting started", "check my environment", "configure SDK", or as first step in any plan involving SageMaker training/evaluation/deployment. |
| Manage project directory and artifacts | [references/directory-management/](references/directory-management/) | Starting a new project, resuming existing one, or when PLAN.md needs to be associated with a project directory. |
| Set up, update, or delete a SageMaker Managed MLflow app | [references/manage-mlflow/](references/manage-mlflow/) | User says "set up MLflow", "create MLflow app", "update my MLflow app", "delete my MLflow app", "I need an MLflow server", asks "what is SageMaker MLflow", or a workflow needs an MLflow backend and none is connected. |
| Diagnose a failing or unhealthy SageMaker endpoint | [references/endpoint-diagnostics/](references/endpoint-diagnostics/) | User reports endpoint errors, latency, inference failures, or a deployment that failed. "What's the status of my endpoint?", "Is my endpoint erroring?", "My endpoint failed — why?", "How many instances are running behind my endpoint?", "Is the latency my model or SageMaker?", "Show me the container logs for my endpoint." NOT for training-job issues, endpoint deletion, scaling changes, or new deployments. |
| Reduce GPU inference cost or latency with a shared KV cache | [references/kv-cache-handoff.md](references/kv-cache-handoff.md) | User self-hosts open-weight LLMs on GPUs (EC2, EKS, or similar) using vLLM, SGLang, or TensorRT-LLM and asks about reducing inference cost, improving time-to-first-token, sharing KV cache across replicas, setting up ElastiCache for KV tensor storage, configuring LMCache, or adding a distributed L2 cache to their inference fleet. NOT for SageMaker managed endpoint optimization (route to model-deployment instead). |

## Rules

- **Service boundary.** This skill covers SageMaker, including deployment of a customized model to Bedrock. Bedrock-native work (invoking Bedrock's managed foundation models, Bedrock Agents, Knowledge Bases, Guardrails, AgentCore) is supported by AWS but has no validated workflow in this skill: let the user know and proceed with best-effort guidance using general AWS knowledge. If the user asks for a model on AWS without naming a service, compare SageMaker and Bedrock or ask one service-choice question. Do not select a service by default. The two services have different model catalogs, deployment paths, and pricing, and a default selection can send the user into an incorrect workflow.
- **Progressive disclosure.** Load only the reference folder relevant to the current user intent. Do not load all references at once.
- **Best-effort help.** If the user's request falls outside this skill's references, do not dead-end the conversation. Help them using general AWS knowledge and documentation, and inform the user that the guidance is not covered by this skill's validated workflows.
- **Usage attribution.** Before running any AWS CLI command or packaged script, set `export AWS_SDK_UA_APP_ID=AWSSkill-SageMaker`.
- **KV caching for self-hosted inference.** When the user self-hosts inference on GPUs and asks about reducing cost or latency via distributed KV caching, hand off to the `distributed-kv-caching` skill. See [references/kv-cache-handoff.md](references/kv-cache-handoff.md). This is outside SageMaker's service boundary but is a common follow-on from model deployment to self-hosted GPUs.

## Guardrail — where this skill's own files live (MCP vs local install)

This skill can be loaded two ways, and they resolve the skill's own bundled
files from different places. Determine how the skill was loaded before reading
a reference or running a script:

- **Loaded through the AWS MCP `retrieve_skill` tool:** The skill is not
  installed on the local filesystem. You MUST fetch each reference or script
  via `retrieve_skill` with the `file` parameter, using its path relative to
  the skill root (e.g. `file="references/dataset-transformation/overview.md"`
  or `file="references/dataset-transformation/scripts/dataset_split.py"`), and
  run the script from the returned content. When a reference says to copy a
  packaged file into the project, write the returned content unchanged to that
  destination. Also fetch every skill module that script imports, so its
  imports resolve, and never regenerate a file from context. Do NOT
  `file_read` these paths locally — they do not exist on disk.
- **Installed locally** (e.g. `.kiro/skills/aws-ai-ml/` or
  `~/.claude/skills/aws-ai-ml/`): Read and run files from the local skill
  directory using relative paths.

This distinction applies only to the skill's own packaged files. User data and
session artifacts are always read from and written to the user's working
directory. Never fetch or write customer data through `retrieve_skill`.
