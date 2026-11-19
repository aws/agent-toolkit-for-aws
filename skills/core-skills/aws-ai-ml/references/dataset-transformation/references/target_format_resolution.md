# Target Format Resolution

Use this reference whenever a workflow step needs to know the exact target schema for a dataset — either for a schema transform operation (`op_schema_transform.md`) or for a notebook-delivered transformation (`notebook_delivery.md`).

Do not rely on memorized schemas. Always resolve through one of the paths below.

## Step 1 — Determine the purpose

Resolve whether the transformation is for:

- **Model training** — the dataset feeds a SageMaker fine-tuning job (SFT, DPO, RLVR, RLAIF).
- **Model evaluation** — the dataset feeds a SageMaker evaluation job.

The purpose is usually clear from context (spec metadata, project use case, upstream skill handoff). If it is not, ask the user before proceeding:

> "Is this dataset for model training or model evaluation? This determines which target format I resolve."

⏸ Wait for user.

## Step 2 — Resolve the target schema

### If purpose is training

Read `../../dataset-quality/references/strategy_data_requirements.md`. The required format depends on two dimensions:

- **Model type** — Open Weights (Llama, Qwen, Mistral, ...) or Nova.
- **Finetuning technique** — SFT, DPO, RLVR, or RLAIF.

If either dimension is missing from context, ask the user before resolving:

> "Which model family and fine-tuning technique are you targeting? (e.g., Llama + SFT, Nova + DPO)"

⏸ Wait for user.

Once both dimensions are known, look up the schema in `strategy_data_requirements.md` and record the resolved format identifier (e.g., `openai_chat`, `nova_sft`, `llama_dpo`).

Treat the resolved schema as a literal output contract. In particular, **Open
Weights + SFT** requires one JSONL object with top-level `prompt` and
`completion` fields. Do not substitute `system` / `instruction` / `response` or
`messages` fields, and do not return only a rendering template; generate the
record mapping that emits `prompt` and `completion`.

### If purpose is evaluation

1. Attempt to fetch the live documentation at
   `https://docs.aws.amazon.com/sagemaker/latest/dg/model-customize-evaluation-dataset-formats.html`.
2. **On success** — use the schema from the live docs.
3. **On failure** (no internet, VPC-only environment) — fall back to `sagemaker_dataset_formats.md` and inform the user:

   > "I couldn't reach the live AWS docs, so I'm using the cached schema reference. The format may be slightly outdated — double-check against the live docs when possible."

If the user named a specific evaluation format (e.g., "SageMaker Q&A format"), surface the resolved format (**{name}** / schema **{schema}**) as part of the single pre-execution review (`spec_execution_flow.md` Phase A) — do not stop for a separate re-confirm pause here.

## Step 3 — Record the resolved format

The calling workflow step must record the resolved format identifier so it can be embedded in the generated code's stats output (`target_format` in `op_schema_transform.md` Output Contract) and shown in the final run summary.

## Custom formats

If the user describes a custom target format (not a well-known one above), ask for a sample record:

> "Please share a sample record in the desired target format so I can mirror its schema exactly."

⏸ Wait for user.

Use the sample as the authoritative target schema. No lookup is performed.
