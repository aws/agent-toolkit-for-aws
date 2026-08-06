# Input-Output Contracts

| Skill | Inputs and Prerequisites | Outputs | Restrictions |
|---|---|---|---|
| **planning** | User's goal (conversational) | `PLAN.md` | None |
| **directory-management** | None | Project directory | None |
| **use-case-specification** | Problem statement, primary users, success tenets or deployment constraints (conversational) | `use_case_spec.md` | For deployment path: produces Deployment Constraints section instead of Success Tenets |
| **model-selection** | `use_case_spec.md` | For deployment path: a flat deploy config — `model_id` (Hub ID), `instance_type`, and `inference_config_name` (the recommended config, or `null` when the model has no labeled configs). For fine-tuning: base model name | For deployment path: filters full catalog by Deployment Constraints. For fine-tuning: filters to customization-capable models only |
| **sdk-getting-started** | None | Verified environment (region, execution role, SDK version) | None |
| **finetuning-technique** | Base model name; `use_case_spec.md` | Confirmed technique | Not all models support all techniques, compatibility is checked in this skill  |
| **dataset-evaluation** | Dataset file path; for training data only: finetuning-technique and model-selection | Validation result | Evaluation datasets do not require the technique to be known |
| **dataset-transformation** | Dataset file path; output location; for training data only: finetuning-technique and model-selection | Transformed dataset file path | None |
| **finetuning** | `use_case_spec.md`; model-selection; finetuning-technique; training dataset (S3); verified environment | Training job name/ARN | Training dataset must be in the same S3 region as the training job |
| **model-evaluation** | Training job name/ARN or base model identifier; evaluation dataset; for built-in scorers only: dataset-evaluation | Evaluation metrics | LLM-as-Judge and built-in scorers are not supported for Nova models |
| **model-deployment** | Training job name/ARN (fine-tuned) OR the model-selection deploy config — `model_id` + `instance_type` + `inference_config_name` (base model) | Endpoint or Bedrock model ARN | For fine-tuned: only LoRA models supported (no FFT). Base model (JumpStart): SageMaker real-time endpoint only (not Bedrock); GPU-capacity constrained. OSS → Bedrock: supported regions are us-east-1, us-east-2, us-west-2, eu-central-1; model must be under 200 GB. Nova → SageMaker: supported regions are us-east-1, us-west-2, eu-west-2, ap-northeast-1. Nova → Bedrock: us-east-1 only |

**Note on validated scope:** The restrictions above describe what each reference's validated workflow covers. Operations outside these workflows (e.g., FFT deployment, JumpStart→Bedrock base model deployment, BYO container training, HyperPod, traditional ML training/deployment, deploying HuggingFace or externally-trained models) are not precluded by SageMaker — this skill simply does not have a tested step-by-step workflow for them. Per the skill's best-effort principle, help the user with general AWS knowledge and disclose that the guidance is not from a validated workflow.
