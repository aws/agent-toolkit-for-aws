---
name: migrating-evaluators-to-agentcore
description: "Moves an existing offline agent-evaluation suite — DeepEval, RAGAS, Phoenix, Strands Evals, or a judge script already scoring an agent locally — onto AWS AgentCore managed evaluation, so the same metrics score production traffic. NOT for migrating the agent itself (Bedrock Agents to AgentCore Runtime or Harness, execution roles, inbound auth) — use amazon-bedrock. NOT for evaluating a model, including a fine-tuned one, with LLM-as-a-Judge or a benchmark — use aws-ai-ml. NOT for scoring traces on demand, online scoring with no local suite to move, or reading results — use aws-observability. Covers evaluator classification, deployment path selection, ADOT spans and score divergence. Triggers: DeepEval or RAGAS to AgentCore, Phoenix evaluators, Strands Evals migration, Langfuse tracing replacement, moving a local judge script onto AgentCore."
version: 1
---

# Migrating Agent Evaluations to AgentCore

## Overview

Performs an offline-to-online evaluation migration for AWS AgentCore: reads an
existing evaluation script, classifies each evaluator to a deployment path,
deploys what needs deploying, and produces a self-sufficient `*_agentcore.py`
script whose scores match the original within a 0.1 divergence budget.

Steps run sequentially. Confirm with the user before proceeding past Step 2
unless `EVAL_MIGRATION_AUTO_APPROVE=1`.

The AWS MCP server is recommended but not required — when connected it provides
sandboxed execution, audit logging, and observability for AWS calls. Without it,
the AWS CLI, `boto3`, and the `agentcore` CLI cover every step. Nothing here
depends on MCP-specific tools.

The steps run shell commands and the Python scripts in `scripts/`, so the skill is
display-only on hosts that lack a shell or a Python interpreter: show the user the
commands and generated files to run elsewhere, and never report a step as run.

**Runtime requirements.** Python 3.12+, Node.js 20+ (for the CDK behind
`agentcore deploy`), `uv`, and valid AWS credentials; Step 0 verifies all four.
Every package is pinned exactly, so no unreviewed release reaches the migration host or
a customer's Lambda. 1.23.0 is the first `bedrock-agentcore` release that ships every
`third_party` adapter this skill uses; boto3/botocore 1.43.75 meet its floor and stay
under the cap aiobotocore 3.9.1 sets.

```bash
pip install "bedrock-agentcore==1.23.0" "strands-agents-evals==1.2.0" \
            "boto3==1.43.75" "botocore==1.43.75" "strands-agents==1.50.1" "uv==0.12.10"
# Plus the SOURCE framework at the version the customer's project pins
# (`pip install -r <project>/requirements.txt`); if it pins none, use the version this
# skill is validated against: "deepeval==4.2.3", "ragas==0.4.4" or
# "arize-phoenix-evals==3.1.1".
# DeepEval source ONLY: also `pip install "aiobotocore==3.9.1"`, which its Bedrock
# judge imports. The other frameworks do not use it.
```

## Guardrail — where this skill's own files live (MCP vs local install)

This skill can be loaded two ways, and they resolve the skill's own bundled
files from different places. Determine how the skill was loaded before reading
a reference or running a script:

- **Loaded through the AWS MCP `retrieve_skill` tool:** The skill is not
  installed on the local filesystem. You MUST fetch each reference or script
  via `retrieve_skill` with the `file` parameter (e.g.
  `file="references/deployment-lambda.md"` or `file="scripts/classify.py"`),
  and run the script from the returned content. Do NOT `file_read` these paths
  locally — they do not exist on disk.
- **Installed locally** (e.g. `.kiro/skills/migrating-evaluators-to-agentcore/`
  or `~/.claude/skills/migrating-evaluators-to-agentcore/`): Read and run files
  from the local skill directory using relative paths.

This distinction applies only to the skill's own packaged files. User data and
session artifacts are always read from and written to the user's working
directory. Never fetch or write customer data through `retrieve_skill`.

## When to Use

- Migrate Strands Evals, DeepEval, RAGAS, or Phoenix evaluators to AgentCore
- Replace local or offline evaluation with AgentCore (produces `*_agentcore.py`)
- Diagnose score divergence between a local evaluator and its AgentCore twin

## Reference Files

Rules needed on every migration are in this file; the references cover branches.
Read one when its trigger fires, not up front.

| Read this | WHEN |
|---|---|
| [strands-evals.md](references/strands-evals.md) | source is Strands Evals — before mapping any `Builtin.*` |
| [adot-domain-knowledge.md](references/adot-domain-knowledge.md) | before writing ADOT, or on `no spans to evaluate` |
| [deployment-lambda.md](references/deployment-lambda.md) | before `agentcore deploy` — dependency + pre-deploy checks |
| [deployment-lambda-troubleshooting.md](references/deployment-lambda-troubleshooting.md) | a deploy/invoke failed, or scores are all 0.0 |
| [deployment-llmaaj.md](references/deployment-llmaaj.md) | `classify.py` returned `llm_judge` for any metric |
| [divergence-handling.md](references/divergence-handling.md) | any metric breached 0.1, or topology is live |
| [troubleshooting.md](references/troubleshooting.md) | stuck, or a decision feels ambiguous |

## Efficiency Rules

CDK deploys, evaluation runs, and dependency debugging are the slow operations.
These rules keep the migration on the shortest path that still works.

1. **Do NOT explore `bedrock_agentcore` or `strands_evals` site-packages** (`find`,
   `pip show`, `cat`). Everything required is in `references/` and `scripts/`. You MAY
   read the SOURCE framework's code (deepeval, ragas, phoenix) to extract a prompt or
   understand a metric.
2. **Use the deterministic scripts; do NOT hand-write what they generate**
   (classification, names, handlers, ADOT construction, the client script).
3. **Read [adot-domain-knowledge.md](references/adot-domain-knowledge.md) before
   constructing or touching ADOT.** Never build ADOT JSON from memory.
4. **Do NOT test handlers locally before deploying.** Generated handlers are correct by
   construction, and the Lambda receives transformed spans (`body` becomes
   `span_events[0].body`), so a local import proves nothing. Deploy, then fix with
   `update_function_code()` if needed.
5. **After 2 failed attempts at any operation, change strategy.** Do not retry the
   same approach a third time.
6. **Cap dependency and span debugging at 2 attempts each.** Both fix chains are
   documented: [deployment-lambda.md](references/deployment-lambda.md) and the recovery
   tree in [adot-domain-knowledge.md](references/adot-domain-knowledge.md).
7. **Never end your turn while a command is still running**, including the preflight
   `pip install`. A slow command may be auto-backgrounded and return empty output or a
   PID; that is NOT completion, and nothing can notify you after your turn ends. Poll
   with `sleep 30; tail -20 <log>` until the command's `exit=` marker prints. Never
   background deliberately (`&`, `run_in_background`) or run concurrent npm installs.
8. **Allow long-running steps 15 minutes.** Run `bash deploy/migration.sh`, the original eval
   script and the migrated `_agentcore.py` once each under `timeout 900`, polling per
   rule 7. Do NOT wrap migration.sh in a shorter timeout: it bounds its own CDK deploy
   at 600s, and killing it mid-`npm install` corrupts node_modules. If it is cut off
   anyway, RE-RUN it; completed steps are skipped. Never cap an `evaluate()` run at
   120s: Lambda cold starts alone take 60-120s.
9. **Check for the agentcore CLI first** (`agentcore --version`). If it errors, use the
   CLI-broken fallbacks in
   [deployment-lambda-troubleshooting.md](references/deployment-lambda-troubleshooting.md).
10. **For 5+ evaluators:** after ONE Lambda tests successfully, deploy ALL the rest in
    a single `migration.sh` batch. Each deploy-and-test cycle takes 10-15 min.
11. **Keep `_agentcore.py` self-sufficient** (only `bedrock_agentcore` + the agent
    framework) and **suppress verbose output** with `2>&1 | tail -50`.
12. **If credentials expire mid-run: STOP IMMEDIATELY.** Do not retry. Save whatever
    artifacts exist and report partial progress in `summary.json`.
13. **For live topologies: capture traces FIRST, then pin them.** The generated
    `_agentcore.py` separates agent capture from evaluation through a `traces.json`
    cache. Keep that two-phase structure in `load_cases()`; do NOT move agent calls
    into `evaluate_case()`.

## Core Invariants

Violating any of these means the migration is broken, not merely imperfect.

- **Divergence ≤ 0.1 for every metric individually.** A mean of 0.09 is meaningless if
  one metric sits at 1.0. Check each key: `abs(mean_before - mean_after) <= 0.1`. On any
  breach, go straight to the diagnosis table in
  [divergence-handling.md](references/divergence-handling.md); do not iterate blindly.
- **Divergence on a Builtin or adapter metric is a MAPPING bug, never "inherent".**
  Those paths run the original's own judge or metric code, so scores move only if the
  evaluator sees different text. Check `--field-map` first (which trace field became
  `input`, `output`, `context`). Only single-prompt LLM-as-a-Judge metrics diverge
  inherently, and only after trace-pinning.
- **`mean_scores` MUST hold the SAME KEY SET in both score files.** The divergence check
  fails on any key present in only one (shape in Step 0). This is the most common way
  a correct migration reads as a failure.
- **Lambda handlers MUST return `EvaluatorOutput(value=..., label=..., explanation=...)`**,
  not a dict and not `score=`/`reason=`. Pydantic drops unknown fields, so `score=`
  leaves `value: null` and every metric reads 1.0; the validator rejects a response
  without `label`. Generated handlers already comply (see Handler Return Format in
  [deployment-lambda.md](references/deployment-lambda.md)).
- **Lambda-mandatory metrics MUST NOT fall back to LLM-as-a-Judge.** Everything
  `classify.py` marks `lambda_adapter` or `lambda_custom` is Lambda-only: all DeepEval
  multi-step (Faithfulness, Bias, Toxicity, DAGMetric…), deterministic (ExactMatch,
  ToolCorrectness…), `GEval`, and every RAGAS metric, the NVIDIA ones included. If
  Lambda deployment fails, fix it; do not approximate.
- **Metrics marked `unsupported` MUST NOT be migrated.** In this version `classify.py`
  refuses DeepEval multi-turn/conversational metrics (`ConversationalGEval`,
  `GoalAccuracy`, `RoleAdherence`, `ToolUse`, `Turn*`, `ConversationCompleteness`,
  `KnowledgeRetention`, `TopicAdherence`) and RAGAS `DataCompyScore` and `RougeScore`.
  Report them to the user as out of scope, migrate the rest, and do NOT substitute an
  approximation: an LLM-as-a-Judge stand-in diverges 0.2-0.5 and fails the fidelity
  check anyway. RAGAS multi-turn metrics are unaffected.
- **LLM-as-a-Judge is valid ONLY for** Phoenix single-prompt classifiers and Strands
  `OutputEvaluator`, which have no SDK adapter. Every DeepEval and RAGAS metric runs its
  own code through `DeepEvalAdapter` or `RagasAdapter` in Lambda. `classify.py`'s
  mapping.json is authoritative: never hand-edit `path`/`adapter` (`generate_handlers.py`
  refuses a DeepEval or RAGAS metric routed to `llm_judge`).
- **Do NOT call `DeepEvalAdapter`/`RagasAdapter` in-process.** Deploy them as Lambda
  handlers via `@custom_code_based_evaluator()` and invoke through
  `_dp_client.evaluate()`.
- **Use the customer's test cases as-is.** Never reword, replace or add one, and never drop
  a case to improve a score. If divergence is too high, fix the evaluator or deployment,
  never the test cases. Evaluating a **subset** is allowed only to fit a runtime budget: take
  a prefix, run BOTH evaluators over that same subset, and record in `summary.json` how many
  of how many cases were used. A subset compared against a full baseline is not a comparison.

## Deterministic Scripts

```bash
SKILL=<this skill's directory>   # e.g. .claude/skills/migrating-evaluators-to-agentcore

# 1. Write metrics.json from the source (your judgment); schema in Step 1.
# 2. Classify: deployment path + exact score keys aligned to the baseline.
python3 $SKILL/scripts/classify.py --framework deepeval --metrics metrics.json \
    --scores-before scores_before.json --output mapping.json
# 3. Names, with the project/evaluator/Lambda-name limits enforced. Run it ONCE, keep
#    --task to 1-3 chars (e.g. "s", "rag") and leave --uid alone: long tasks collide
#    at the 48-char evaluator truncation.
python3 $SKILL/scripts/names.py --task <task_name> --framework <framework> \
    --mapping mapping.json --output names.json
# 4. Lambda handlers + manifest (skip if no code-based metrics).
python3 $SKILL/scripts/generate_handlers.py --mapping mapping.json --names names.json --output-dir handlers
# 5. The deliverable script.
python3 $SKILL/scripts/generate_client_script.py --source-script <original>.py \
    --topology traces|live [--traces-file <path> --field-map input=...,output=...,context=...,reference=...] \
    --mapping mapping.json --names names.json --output-dir .
```

The scripts are a set, not standalone files. [deployer.py](scripts/deployer.py) loads
[names.py](scripts/names.py) and [package_ragas_lambda.py](scripts/package_ragas_lambda.py);
[generate_handlers.py](scripts/generate_handlers.py) loads deployer,
[classify.py](scripts/classify.py) and names;
[generate_client_script.py](scripts/generate_client_script.py) reads
[adot.py](scripts/adot.py); [verify_deps.py](scripts/verify_deps.py) loads
package_ragas_lambda; [smoke_test_lambda.py](scripts/smoke_test_lambda.py) runs after the
deploy; [`__init__.py`](scripts/__init__.py) marks the package. deployer.py also copies
[cdk-package-lock.json](assets/cdk-package-lock.json), the lockfile migration.sh installs
the CDK app from. Over MCP, fetch EVERY `scripts/` file into ONE local directory, and the
lockfile, `assets/requirements/deepeval.txt` and `assets/requirements/ragas.txt` (the
constraint files `generate_migration_sh()` reads) into `assets/` beside it, before
running any; never regenerate a missing file from memory.

Your judgment: reading the source (Step 1), trace field mapping, completing
`TODO(EVAL-MIGRATION)` markers, LLM-as-a-Judge prompt extraction (Step 4), deployment
error diagnosis, and the divergence fix loop (Step 5). Everything else is generated.

## Step 0: Pre-flight (Target: 3-5 steps)

Run `deployer.preflight_check()`, which checks Node.js, uv, TypeScript, AWS
credentials and the agentcore CLI:

```python
import sys; sys.path.insert(0, '<this skill\'s directory>')  # same path as $SKILL
from scripts.deployer import preflight_check
print(preflight_check())
```

In parallel, read the source evaluation script and check `EVAL_MIGRATION_AUTO_APPROVE`; for a
DeepEval source also run `pip install "aiobotocore==3.9.1" 2>&1 | tail -5`. Apply the
fixes preflight suggests. If AWS credentials are expired, STOP.

**Run the original evaluation script** (ask first unless `EVAL_MIGRATION_AUTO_APPROVE=1`) with
`RAGAS_DO_NOT_TRACK=true DEEPEVAL_TELEMETRY_OPT_OUT=YES` set, so neither framework
sends usage analytics to a non-AWS endpoint. Then **normalise its output into
`scores_before.json`** in this exact shape; do NOT dump the original output verbatim.
Frameworks print different shapes (`overall_score`, a bare list, a nested report), and
the divergence check reads `mean_scores`, so a baseline without that block compares
against nothing.

```json
{"mean_scores": {"<metric_key>": 0.8}, "scores": [{"input": "...", "<metric_key>": 0.8}]}
```

- `<metric_key>` is what the ORIGINAL evaluator reports, lowercased with underscores
  (`coherence`, `goal_success_rate`), NOT DeepEval's internal `metric_data.name` format
  (`_[geval]`, `_[dag]`).
- Aggregates count as keys. If the original reports `overall_score` and you are not
  migrating it, omit it from BOTH files.
- Run `classify.py --scores-before` before Step 2 so downstream naming aligns to this
  file; it also maps ragas aliases (RubricsScore → `domain_specific_rubrics`).

**If the baseline run fails on a framework quirk** (aiobotocore conflict, CrewAI 1.15+
`ChatBedrock`, GEval kwargs), apply the minimum fix from
[troubleshooting.md](references/troubleshooting.md).

## Step 1: Discover

Scan imports: `strands_evals.evaluators` / `deepeval.metrics` / `phoenix.evals` /
`ragas.metrics`. Also identify tracers to replace: Langfuse `@observe()`, Phoenix
`register()`.

**Output:** `metrics.json`, one entry per evaluator found in the source:

```json
[
  {"class": "FaithfulnessMetric", "init_kwargs": "threshold=0.5"},
  {"class": "SimpleCriteriaScore", "name": "clarity", "score_transform": "score/5"},
  {"class": "GEval", "name": "Helpfulness", "init_kwargs": "threshold=0.7",
   "evaluation_params": ["INPUT", "ACTUAL_OUTPUT"], "criteria": "<verbatim>"}
]
```

`GEval` MUST carry `name` + `criteria` (or `evaluation_steps`): the rubric IS the
metric, and `classify.py` rejects a GEval without it. `DAGMetric` MUST carry `name`,
and a metric's required literal arguments (`PatternMatchMetric`'s `pattern=`,
`PromptAlignmentMetric`'s `prompt_instructions=`) go in `init_kwargs`. When the source
builds one DeepEval metric with different arguments per case (a `PatternMatchMetric` per
regex, a `JsonCorrectnessMetric` per schema), list it ONCE with
`"variants": {"<name>": "<init_kwargs>"}`, never as a second entry, and give each case
`{"variants": {"<score_key>": "<name>"}}` in its Metric Inputs (Step 3). Copy verbatim;
never paraphrase, and edit a generated handler only inside its `TODO(EVAL-MIGRATION)`
block. If the source rescales a score after evaluation
(e.g. divides a 0-5 rubric score by 5), record it as `score_transform` (an expression
over `score`); otherwise the migrated run reports raw-scale scores.

## Step 2: Clarify & Map

Run `classify.py` (step 2 of Deterministic Scripts); do NOT decide deployment paths by
hand. It encodes this ruleset:

| Source Framework | Deployment Path |
|---|---|
| **Strands Evals** (named evaluators) | No deployment — use `Builtin.*` ID directly |
| **Strands `OutputEvaluator`** | Custom LLM-as-a-Judge via SDK |
| **Phoenix** (single-prompt classifiers) | Custom LLM-as-a-Judge via SDK |
| **DeepEval GEval** | Lambda — NO fallback |
| **DeepEval multi-step** (Faithfulness, AnswerRelevancy, Bias, Toxicity, DAGMetric, ArgumentCorrectness, TaskCompletion) | Lambda (`DeepEvalAdapter`) — NO fallback |
| **DeepEval deterministic** (ExactMatch, PatternMatch, JsonCorrectness, ToolCorrectness) | Lambda (`DeepEvalAdapter`) — NO fallback |
| **RAGAS** (every metric, including AnswerAccuracy, ContextRelevance, ResponseGroundedness) | Lambda (`RagasAdapter`, PyPI pins + overrides) — NO fallback |

**Get user confirmation before proceeding** (unless `EVAL_MIGRATION_AUTO_APPROVE=1`).

## Step 3: Generate Migrated Script

| Topology | Evidence | Strategy |
|---|---|---|
| **A: Pre-generated traces** | Script reads saved traces (no live agent) | `generate_client_script.py --topology traces` produces the COMPLETE script |
| **B: Live agent (no OTel)** | Agent runs but has no tracing | `--topology live` scaffold + instrument agent → capture spans → map to ADOT |

Run the three generators from "Deterministic Scripts" (`names.py`,
`generate_handlers.py`, `generate_client_script.py`). `score_transform` entries apply
automatically; `--metric-transform key=expr` overrides one, and
`--metric-inputs-map sample_field=trace_field` supplies per-sample fields, named in each
metric's mapping.json notes. For RAGAS they are sample fields (`rubrics`,
`reference_contexts`, image lists, context IDs) plus, for the multi-turn metrics, the
agent's `tools_called` or the whole conversation as `user_input`; for DeepEval they are
the tools the agent called (`tools_called`, plus `expected_tools` for ToolCorrectness)
and each case's variants (`variants`). In live topology `_run_agent()` returns them as
`metric_inputs`. When the source scores a
metric on only some cases, give each of those cases a `"metrics"` list of the keys that
apply; the others record `null`, as the source's do, and the means skip them.

The generated `{original}_agentcore.py` is self-sufficient, resolves Lambda evaluator
IDs at runtime by PROJECT-SCOPED fragment, raises on evaluator errors (never records
silent 0.0s), and writes `scores_after.json` + `summary.json` with keys matching the
baseline. **LLM-as-a-Judge IDs cannot self-resolve**: after creating them in Step 4,
paste each returned `evaluatorId` into the script's `EVALUATORS` dict.

**Topology A:** read the trace file FIRST, then pass `--field-map` with its actual field
names. Ground truth goes in `reference=`; the tool embeds it with the exact separators
the RagasAdapter splits on, and JSON-encodes list-shaped references.

**Topology B — MANDATORY TWO-PHASE ARCHITECTURE:** implement `load_cases()` so it reads
`traces.json` when the file exists (skipping ALL agent calls) and otherwise runs the
agent via `_run_agent()` and saves `traces.json`. This separation is what makes
retries possible without re-running the agent. Instrument the agent with OTel and map
its spans with the pipeline in
[adot-domain-knowledge.md](references/adot-domain-knowledge.md) (Strands agents:
`convert_strands_to_adot(raw_spans)`); never hand-build raw ADOT JSON.

**Complete every `TODO(EVAL-MIGRATION)` marker**; the generated client exits 3 with a
marker checklist while any remain. Handlers carry them too: `DAGMetric`'s `dag=` and
`JsonCorrectnessMetric`'s `expected_schema=` are Python objects mapping.json cannot
carry, so copy each from the source VERBATIM into the block `generate_handlers.py`
leaves. `generate_migration_sh()` and migration.sh refuse a handler that still has one.

**Protect manual code from regeneration:** `generate_client_script.py` overwrites its
output. Once you have implemented `load_cases()` or other manual code, edit the
generated script directly. If you MUST regenerate (names or mapping changed), copy
your manual code out first and reapply it after.

## Step 4: Deploy (Non-Strands only)

**Deploy every Lambda evaluator with `scripts/deployer.generate_migration_sh()`.** Do
NOT run `agentcore create`, patch CDK files, or write deployment scripts by hand: the
generated script applies both x86_64 CDK patches (python.js AND evaluator.js), the
exact dependency pins and the scoped IAM policy. Call signature, handler settings and
the RAGAS packaging are in [deployment-lambda.md](references/deployment-lambda.md).
Evaluator and project names come from `names.json`; never hand-write them.

### Deploy Sequence (straight-line — no detours)

1. `generate_migration_sh()` → 2. `bash deploy/migration.sh` (runs `verify_deps.py`
itself, then deploys; ONE deploy, never a separate `agentcore deploy`) → 3.
`smoke_test_lambda.py --project <ProjectName> --all` → 4. `python3 _agentcore.py`

migration.sh is safe to RE-RUN after any failure or interruption; the project,
evaluator, and target steps it already completed are skipped. If `verify_deps.py`
stops it, fix the reported issue and re-run migration.sh.

Deploy ONE evaluator, test it with a single `evaluate()` call, then deploy the rest.
If the first fails, fix it before deploying others; they fail identically. For
code-only handler fixes use `update_function_code()` (2 steps instead of 10-15): keep
the full dependency bundle, replace only its `lambda_function.py`, and upload it
through S3, since the bundle is over the direct-upload limit. Procedure in
[deployment-lambda-troubleshooting.md](references/deployment-lambda-troubleshooting.md).

### LLM-as-a-Judge Deployment

Follow [deployment-llmaaj.md](references/deployment-llmaaj.md) with the evaluator name
from `names.json`, **then paste the returned `evaluatorId` into the generated script's
`EVALUATORS` dict.** Copy the source's prompt verbatim: Phoenix
`{NAME}_CLASSIFICATION_EVALUATOR_CONFIG.messages` or the Strands `OutputEvaluator`
`rubric`.

## Step 5: Run & Verify

Write to a log file rather than relying on the run finishing inside one tool call:
cold starts of 60-120s × N metrics × N cases routinely push RAGAS and multi-metric
runs past the agent tool's own command limit.

```bash
timeout 900 python3 {name}_agentcore.py > /tmp/verify.log 2>&1; echo "exit=$?"
tail -50 /tmp/verify.log
```

Cut off before `exit=` prints? It was auto-backgrounded: poll per Efficiency Rule 7
and do NOT launch a second copy. If the log stops growing with no summary, re-run in
the foreground.

The generated script prints per-metric divergence and **exits 2 if any metric exceeds
0.1**; treat exit 2 as "enter the fix loop", not as completion.

### Divergence Fix Loop

1. **Live topology (B): trace-pinning is MANDATORY** before accepting or reporting any
   divergence, because the agent's own nondeterminism dominates. Re-run the ORIGINAL
   evaluators over the same `traces.json` and overwrite `scores_before.json`
   (procedure in [divergence-handling.md](references/divergence-handling.md)).
2. **Lambda + adapter:** debug the handler (env vars, model config, components). Uncapped,
   but every attempt must CHANGE something. Re-running `evaluate()` with the handler, the
   evaluator config and the traces unchanged is not an attempt — do that at most once, to see
   whether the divergence reproduces, then fix or report. Repeating an identical run until the
   number passes is the largest time sink there is and makes the result a lucky draw.
3. **LLM-as-a-Judge:** never reword a recovered prompt to close a gap. Confirm
   `instructions` is the source text verbatim, that every source placeholder reaches
   `{context}`, and that the `ratingScale` order reproduces the source's label-to-score
   mapping; correct a deployed evaluator with `UpdateEvaluator` on its existing ID rather
   than deploying a second, suffixed one. See
   [divergence-handling.md](references/divergence-handling.md).
4. **After 2 fix attempts, LLM-as-a-Judge metrics ONLY:** report as inherent divergence in
   `summary.json`. A verbatim prompt whose fields all arrive is already terminal — report it
   at zero attempts rather than changing the judge to find something to do. **This exit does
   not exist for a Builtin or Lambda+adapter metric**, which runs the original's own metric
   code: there, divergence is a mapping or handler bug with no attempt cap (invariant above).

## Step 6: Confirm Artifacts

Required outputs: `scores_before.json`, `scores_after.json`, `summary.json`,
`workspace/{original}.py`, `workspace/{original}_agentcore.py`

The migrated script also writes `evaluation_requests.jsonl`, a record of every evaluator request
it sent, which lets you re-score a case without re-running the migration.

**Verification checklist:**

- [ ] `mean_scores` key sets match between the two score files — verify with
  `python3 -c "import json;L=lambda f:set(json.load(open(f))['mean_scores']);a,b=L('scores_before.json'),L('scores_after.json');print('OK' if a==b else f'MISMATCH before-only={a-b} after-only={b-a}')"`
- [ ] Per-metric divergence ≤ 0.1 (or, for an LLM-as-a-Judge metric only, reported as
      inherent in summary.json — never for a Builtin or Lambda+adapter metric)
- [ ] All Lambda-mandatory metrics use Lambda (not LLM-as-a-Judge approximation)
- [ ] summary.json has deploy_success=true and invoke_success=true

## Troubleshooting

Symptoms whose fix is not simply "read a reference" (that table is above):

| Symptom | Fix |
|---|---|
| A metric is in one score file but not the other | Normalise `mean_scores` per Step 0 — the scores are probably already right |
| `ModuleNotFoundError` in Lambda (deepeval, strands_evals, `...third_party`) | Re-run `bash deploy/migration.sh` (verify_deps runs inside it). Do NOT chase deps one at a time — [deployment-lambda.md](references/deployment-lambda.md) |
| `MISSING_REQUIRED_FIELD` from a DeepEval or RAGAS Lambda | The case lacks the field (`--field-map context=`/`reference=`, or the Metric Inputs the metric's mapping.json notes name, such as `tools_called`, `expected_tools`, `reference_contexts` or `variants`); if it has it, the handler predates its `custom_mapper`, so regenerate it |
| Evaluator name collision after truncation | `names.py` resolves this itself — it shortens the project prefix until the truncated evaluator names are unique and prints `[names] auto-shortened project ...`. It only raises when a 1-char prefix still collides, which means two metric keys are indistinguishable within 48 chars; rename nothing and report that. Do not re-run `names.py` with a different `--task` |
| CDK stack stuck in `ROLLBACK_COMPLETE` | `aws cloudformation delete-stack --stack-name <stack> --region <region>`, wait for it to finish, then delete the `/aws/lambda/<project>-eval-*` log groups the failed stack left behind (the CDK sets `DeletionPolicy: Retain`, so the re-run fails with `AlreadyExists` while they exist), then re-run `bash deploy/migration.sh` |

## Security Considerations

This skill provisions Lambda functions, IAM roles, CloudFormation stacks and S3 objects in the customer's account. Required controls, none of which may be relaxed to clear an error: grant `bedrock:InvokeModel` only on the three named ARNs returned by `deployer.judge_invoke_resources(region, account_id)` — the inference profile and the embeddings model in the deploy region, and the profile's foundation model in the regions it routes to — never `"Resource": "*"`, which grants invoke on every model in the account (`account_id` is your 12-digit account from `sts:GetCallerIdentity`; the helper raises without it rather than widening the profile ARN to every account); pin every injected dependency exactly with `==`, since a floor resolves to whatever PyPI serves at bundle time and puts unreviewed code on a customer Lambda (the declared pins are listed in `assets/requirements.txt`); upload deployment packages with `ServerSideEncryption='aws:kms'`, enable default encryption on the target bucket and deny non-TLS access to it; encrypt the handlers' CloudWatch Logs group with a KMS key by exporting `EVAL_MIGRATION_LOGS_KMS_KEY_ARN` before `migration.sh`, which associates the key with each group the CDK stack creates, right after the deploy and before anything invokes the Lambdas, because evaluation inputs and outputs are customer traces, prompts and model responses and are written there in full; enable CloudTrail data events so `InvokeModel` and evaluator invocations are attributable; and deploy fresh UUID-prefixed evaluators rather than reusing stale ones against live traffic. See AWS best practices for [Lambda](https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html) and [IAM](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html).
