# Generate

Writes the migration plan `$MIGRATION_DIR/generation-ai.json` in the provider-neutral contract `references/vendored/ai/schema-generate-ai.md` (JSON Schema: `references/contracts/generation-ai.schema.json`), and the migration artifacts in `$MIGRATION_DIR/ai-migration/`. This skill writes that contract's shape; the contract's Status section describes what gcp-to-aws and azure-to-aws emit today.

Generate never edits the user's code and never runs anything against AWS. Every artifact is a file the user reviews and runs. To rewrite SDK calls on a branch, the user runs llm-to-bedrock.

**Execute every step in order.** The inputs are the files earlier phases wrote in `$MIGRATION_DIR`. Read nothing outside `$MIGRATION_DIR` and this skill, write nothing outside `$MIGRATION_DIR`, and do not scan code again.

## Step 0: Plan

```bash
python3 <SKILL_BASE>/scripts/generate-ai.py plan $MIGRATION_DIR
```

Read the JSON it prints. Do not redirect it to a file, not even under `/tmp`: Step 1 writes the values you need to copy. On a non-zero exit, stop and tell the user:

| `error`                                    | What to tell the user                                                                       |
| ------------------------------------------ | ------------------------------------------------------------------------------------------- |
| `phase_incomplete`                         | An earlier phase is not complete; resume the run at the phase `detail` names.               |
| `preferences_invalid`                      | The saved answers no longer pass their checks; change answers in Clarify.                   |
| `design_invalid`                           | The design no longer passes `design-ai.py check`; re-run Design.                            |
| `estimate_invalid`                         | `estimation-ai.json` no longer passes `estimate-ai.py check`; re-run Estimate.              |
| `region_invalid` or `model_id_invalid`     | A saved Region or model id is malformed; re-run Clarify or Design as `detail` says.         |
| `iam_unsupported`                          | The IAM helper cannot authorize a row; quote `detail`, then re-run Clarify if it names a recorded requirement, else Design. |
| `no_bedrock_routes`                        | Every workload targets another AWS service; there is nothing for Generate to write.         |
| any other value                            | Quote `detail`.                                                                             |

On success the JSON has:

- `routes[]`: one per `bedrock_models[]` row, with the workloads it serves, the source and target model, `migration_path`, `required_client_api`, `endpoint`, `base_url`, `credential` (`bedrock_token` or `sigv4`), the Mantle selector or `endpoint_assumption`, `fronted_by`, `call_sites`, and `kind`:

  | `kind`             | What changes in the user's code                                                                                      |
  | ------------------ | -------------------------------------------------------------------------------------------------------------------- |
  | `client_config`    | The source SDK stays. Its base URL, credential, and model id change. The request and response shape stay the same.  |
  | `provider_adapter` | The call moves to boto3 Converse or InvokeModel: a new request and response shape.                                   |
  | `gateway_config`   | The gateway stays. Its model mapping points at Bedrock.                                                              |

- `not_generated[]`: workloads that target another AWS service (Transcribe, Polly). They get no artifact; name each in the summary.
- `manifest`: `scaffold` lists the files Step 1 writes, and `agent` lists the two files you write in Step 2.
- `fixed`: the values `generation-ai.json` must carry verbatim (Step 3).
- `budget`, `iam_policy`, `quota_flags`, `compliance`: what `setup_bedrock.sh` uses.
- `confidence_ceiling`: Estimate's confidence. Generate's confidence is never higher.
- `credits_line` and `disclosures[]`: for the README and the summary.

## Step 1: Scaffold the artifacts

```bash
python3 <SKILL_BASE>/scripts/generate-ai.py scaffold $MIGRATION_DIR
```

It deletes `$MIGRATION_DIR/ai-migration/`, keeping only the user's `invoke/<route_id>.py` files listed in `manifest.user`, then writes every file in `manifest.scaffold` from the plan, so a file from an earlier design cannot survive. Do not edit these files: Step 3's check compares them with a fresh render. It also writes `$MIGRATION_DIR/generation-ai.json` with every `fixed` value already in place and each field you write in Step 3 set to a string that starts with `WRITE:`.

| File                                 | What it is                                                                                                                                                                                    |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `routes/<route_id>.py`               | One per route. `call_bedrock(prompt)` uses the route's API, base URL, and model id, and on a `web_search` route sends the `web_search` tool with `external_web_access` false; `call_source(prompt)` calls the current provider where the plan knows how; `generate(prompt, source_call)` switches on `AI_PROVIDER`. |
| `gateway/<route_id>.yaml` or `.json` | `gateway_config` routes only: a LiteLLM `model_list` entry, or the OpenRouter provider-routing fields.                                                                                        |
| `test_comparison.py`                 | Runs every route against Bedrock and, unless `--target-only`, the source; reports latency, errors, and expected-trait scores. Without `--target-only`, a route with no successful source call is `INCOMPLETE`, not a pass. `--quick` sends one built-in prompt per route. |
| `setup_bedrock.sh`                   | Dry run unless `--execute`, and safe to run again: model checks, the IAM policy, environment variables, quota warnings, an AWS Budgets budget on the Amazon Bedrock service and a Cost Anomaly Detection monitor, compliance notes, and a `--target-only --quick` check. Claude models bill through AWS Marketplace, not under Amazon Bedrock, so with a Claude route it creates no budget until the user exports `BUDGET_SERVICES`; `BUDGET_USD` overrides the planned figure the same way. Both are environment variables, so the file stays as scaffolded. |
| `iam-policy.json`                    | The least-privilege policy for exactly these routes, with `ACCOUNT_ID` filled in by `setup_bedrock.sh`. It is a policy document only: this skill does not know which role the application runs as. |

An `invoke` route other than Titan Text Embeddings has no body the plan knows. Its `call_bedrock` loads `invoke(client, model_id, prompt)` from `ai-migration/invoke/<route_id>.py`, which the user writes and check accepts; do not write it yourself.

The feature flag is `AI_PROVIDER`: `source` (the default, the current provider), `bedrock`, or `shadow` (both; the source answer is returned and the Bedrock call is logged).

## Step 2: Write README.md and prompts.json

Write `$MIGRATION_DIR/ai-migration/prompts.json`: a JSON list of 3 to 8 entries `{"id", "prompt", "expected_traits": [...], "route"}` drawn from what the workloads do (their `workload_id`, capability, and the design rationale). `route` is a route id, or omit it so every route gets the prompt. Every route needs at least one prompt. Never copy text from the user's code, logs, or data into a prompt.

Write `$MIGRATION_DIR/ai-migration/README.md` for the person doing the migration, in this order:

1. What this folder is: artifacts only, no code was changed, and llm-to-bedrock rewrites the SDK calls on a branch.
2. One section per route: the workloads and call sites, the source and Bedrock model ids, the endpoint (`bedrock-mantle (<selector>, <source>)` or `bedrock-runtime`, quoting `endpoint_assumption` verbatim), and a before and after example in the workload's language from its `sdk_method`. For `client_config`, show only the client construction and model string changing; an OpenAI client also passes `default_headers={"OpenAI-Organization": Omit(), "OpenAI-Project": Omit()}`, as the route file does, so the source account's ids are not sent to Bedrock. For `provider_adapter`, show the new Converse or InvokeModel call and its response parsing. For `gateway_config`, show the gateway entry.
3. How to use `AI_PROVIDER`: wire `generate(prompt, source_call=<existing call>)` or the route's `call_bedrock`, start in `shadow`, then `bedrock`; set `source` to roll back.
4. The order to run things: `setup_bedrock.sh` (dry run, then `--execute`), `test_comparison.py --target-only --quick`, then the full comparison with source credentials in the environment the SDKs already read.
5. Every entry in `disclosures[]`, every `not_generated[]` workload, and `credits_line`.

Credentials come from Bedrock tokens (`aws-bedrock-token-generator`) or the default AWS credential chain. Never tell the user to put a key in a file, and never show a key, a `.env` file, or a dotenv loader. Dependencies to name: `openai>=2.45.0,<3` and `aws-bedrock-token-generator>=1,<2` for OpenAI-compatible routes, `anthropic` for Messages routes, `boto3` for Converse and InvokeModel.

## Step 3: Complete generation-ai.json and check

Edit `$MIGRATION_DIR/generation-ai.json` in place: replace every string that starts with `WRITE:`, fill `migration_plan.phases`, and change nothing else. The `fixed` values, the dashboards, and `artifacts_by_source` (each model's `ai-migration/` files; call sites stay in `files_to_modify`) are already correct. What you write:

- `migration_plan.approach`: one sentence per route kind present.
- `migration_plan.phases[]` of `{name, sequence, activities[]}`: set up and shadow, compare, then set `AI_PROVIDER=bedrock` on one service or environment at a time, and retire the source credentials after the service is stable. The flag switches a whole process, so a rollout is by deployment, not by percentage of requests.
- `migration_plan.duration_drivers[]`: named by mechanism (model count, `provider_adapter` routes, prompt and eval work for `model_change: true` rows), never in weeks or hours.
- `step_by_step_guide.dependency_changes`: the packages to add and remove.
- `production_readiness_checklist`: at least 5 items, covering model access, IAM attached to the right role, quotas, the comparison passing, monitoring, and a tested rollback.
- `recommendation.approach` and `key_risks[]` (every `model_change: true` row, every `quota_flags[]` entry, every disclosure). `confidence` starts at `confidence_ceiling`; lower it if you have a reason, never raise it.

Then:

```bash
python3 <SKILL_BASE>/scripts/generate-ai.py check $MIGRATION_DIR
```

Fix every reported `errors[]` entry and run the check again until it prints `"ok": true`. For `artifact_modified`, `artifact_missing`, or `artifact_unexpected`, run Step 1 again, then do Step 2 and Step 3 again. Do not complete Generate while the check fails. It enforces the contract, the `fixed` values, that no `WRITE:` string is left, the confidence ceiling, that `ai-migration/` holds exactly the manifest, that every scaffolded file is unchanged, that README.md names every Bedrock model id and the flag, the shape of prompts.json, and that no file holds a credential-shaped string or reads a `.env` file. It cannot judge the prose, the examples, or the prompts.

## Step 4: Present the summary

In under 25 lines:

1. That these are artifacts only: no code changed, nothing ran against AWS, and llm-to-bedrock rewrites the calls.
2. A table per route: workloads, source model, Bedrock model, endpoint, kind, and the route file.
3. The order to run things (README.md item 4), with `setup_bedrock.sh` dry run first.
4. The budget figure and its basis and which services it covers, or that no budget is set and why.
5. Every quota flag, compliance note, disclosure, and `not_generated[]` workload.
6. `credits_line`, as one line with no dollar amounts.
