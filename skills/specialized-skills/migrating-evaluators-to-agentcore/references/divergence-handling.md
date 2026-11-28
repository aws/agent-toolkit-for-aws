# Score Divergence: Root Causes & Fix Protocol

## Contents

- [Overview](#overview)
- [Root Cause Classification](#root-cause-classification)
- [Metric-Specific Recipes](#metric-specific-recipes)
- [Reporting (in summary.json)](#reporting-in-summaryjson)
- [Gotchas](#gotchas)
- [Divergence Rules](#divergence-rules)
- [Metric Key Name Rules](#metric-key-name-rules)
- [Live-Agent Divergence Fix Loop (Topology B)](#live-agent-divergence-fix-loop-topology-b)

## Overview

When `abs(mean(scores_before) - mean(scores_after)) > 0.1` for a metric, the migration
is not faithful enough. The goal is to achieve ≤ 0.1 divergence per metric so the
migrated evaluator produces equivalent results to the original.

**Key insight:** Divergence > 0.1 ONLY occurs with LLM-as-a-Judge metrics (Phoenix
classifiers, Strands `OutputEvaluator`). Every DeepEval and RAGAS metric deploys as a
Lambda that runs the actual metric code through DeepEvalAdapter or RagasAdapter →
divergence ≈ 0.0 for deterministic metrics and small for LLM-based ones.

## Root Cause Classification

### Category A: Structural Bug (all zeros or systematic errors)

| Symptom | Root Cause | Fix |
|---|---|---|
| All scores 0.0 | ADOT body missing required fields | Read `adot-domain-knowledge.md`, use `convert_strands_to_adot()` |
| All scores 0.0 | Context not in first user message | Embed: `f"{query}\n\nContext:\n{ctx}"` in first message |
| All scores 0.0 | Wrong scope name | Use `strands.telemetry.tracer` |
| All scores 0.0 (tool evals) | Tool data not in ADOT first user message | Embed tool_call + tool_result in `{context}` |
| `RuntimeError: unmapped categorical label` | Label absent from the evaluator's own ratingScale | Check the deployed ratingScale; confirm `bedrock-agentcore:GetEvaluator` is permitted |
| All scores 0.0 (Lambda) | Handler using OpenAI judge by default | Configure `model=AmazonBedrockModel(model="us.anthropic.claude-sonnet-4-5-20250929-v1:0")` |
| Scores inverted (1↔0) | Scale semantics mismatch | Order the ratingScale with the best label first |
| All scores 1.0 when some should be 0 | Prompt too lenient | Use verbatim original prompt |

### Category B: LLM-as-a-Judge Semantic Mismatch (fixable with strategy changes)

These produce non-zero but systematically wrong scores. They are caused by the
LLM-as-a-Judge prompt (Phoenix classifier, Strands `OutputEvaluator`) not matching the
original evaluator. **They ARE fixable.**

| Pattern | Root Cause | Fix Strategy |
|---|---|---|
| Judge scores higher than the original | Prompt lenient vs original | Copy the original prompt or rubric verbatim from the source |
| Original 0.0 but judge scores quality | The original returns 0.0 when its input is absent, without consulting its judge at all | Reproduce that outside the judge: score the case 0.0 in the client when the field is absent, as the original does. Do NOT add a default to `instructions` — the source never gave its judge one, and a judge told how to decide no longer measures what the original measured (deployment-llmaaj.md, fidelity rule) |
| Binary judge can't capture partial credit | The deployed scale is narrower than the source's: the original scores between its extremes | Reproduce the SOURCE's scale — a numerical ratingScale carrying the source's own values. This is matching the original, not widening the scale to close a gap; never add values the source cannot produce |

### Category C: Flattened Context Lists (fixable — regenerate, don't report)

**Context-precision metrics (`LLMContextPrecision`, `LLMContextPrecisionWithReference`,
`LLMContextPrecisionWithoutReference`, `NonLLMContextPrecisionWithReference`):**

- Original scripts pass `retrieved_contexts` as a LIST of N chunks; ragas ranks
  each chunk's relevance and computes precision@k over the ranked list.
- If the chunks get joined into ONE string anywhere in the pipeline, the metric
  sees a single chunk and precision collapses to a binary "is the blob relevant"
  judgment. Signature: per-sample migrated scores are all 1.0 (or all 0.0)
  while the originals are fractional; divergence ≈ 1.0 on affected cases.
- **Only samples with MORE THAN ONE chunk can be affected.** Single-chunk samples
  score identically either way, so when a trace set mixes chunk counts the overall
  pattern looks mixed and the signature above does NOT match. The reliable test:
  list the per-sample chunk counts and check whether the diverging samples are
  exactly the multi-chunk ones. If they are, this is Category C however mixed the
  pattern looks. Worked example — chunk counts 2/1/1, originals
  [0.0, 0.0, 1.0], migrated [1.0, 0.0, 1.0]: one diverging sample, and it was
  the only multi-chunk one.
- Confirm before changing anything: score the metric locally on one affected
  sample twice, once with `retrieved_contexts` as the list and once with
  `["\n".join(chunks)]`. If the joined form reproduces the migrated score and the
  list form reproduces the original, the diagnosis is settled and the fixture is
  not at fault.
- **The fix is list passthrough, which current tooling does end-to-end:** the
  generated client script keeps list contexts as lists for RAGAS, embeds them
  as a JSON array, and the RagasAdapter recovers the ranked chunk list intact.
  If you see the flattening signature:
  1. Regenerate the client script with current `scripts/generate_client_script.py`
     (older scripts joined list contexts with `"\n".join`).
  2. Confirm the traces actually carry the context as a list under the field
     you mapped with `--field-map context=<field>`.
  3. Re-run and check per-sample scores are fractional again.
- Do NOT report this as inherent divergence — the fidelity budget is ≤ 0.1 on
  every metric, and a documented explanation does not count as a pass.

### Category D: Agent Response Nondeterminism (Topology B — Live Agent)

Live-agent tasks (Topology B) introduce a divergence source that is NOT an evaluator
bug: the agent produces different responses each time it runs. When the original eval
script and the migrated agentcore script call the agent independently, borderline test
cases can score differently even if both evaluators are functioning correctly.

| Symptom | Root Cause | Fix |
|---|---|---|
| Divergence varies wildly across runs (some pass, some don't) | Agent produces different responses; borderline cases score differently | Trace-pin: save traces from agentcore run, re-run original evaluators on SAME traces |
| Custom GEval (e.g., NonAdviceMetric) consistently diverges 0.15-0.25 | Borderline cases flip with the evaluation steps: a GEval with only `criteria` has the judge write its steps on first use, and a `measure()` loop reuses that one draw for every case. A handler that scores the embedded Context/Reference sections as part of `input` diverges the same way | Trace-pin. Check the handler passes `custom_mapper=_test_case` and builds a new metric per invocation (regenerate it with `generate_handlers.py` if not). GEval is Lambda-mandatory, so there is no inherent exit here: if divergence survives a regenerated handler, keep debugging the handler and report the per-case scores as evidence, not as an accepted result |
| Lambda+adapter divergence >0.05 on live topology but ~0.0 on traces topology | Independent agent runs produce different outputs evaluated identically | Trace-pin — if divergence persists after trace-pinning, the handler has a bug |

### The fix: trace-pinning (MANDATORY for Topology B)

1. The `_agentcore.py` script runs the live agent AND saves all conversation
   traces to `traces.json` during execution.
2. Create a validation script that reads those SAME traces, reconstructs test
   cases, and runs the ORIGINAL local evaluators (DeepEval/RAGAS) on them.
3. **OVERWRITE `scores_before.json`** with the validation script's output.
4. Re-compute divergence — now you're comparing evaluator implementations on
   identical data, not comparing agent runs.

This is NOT a workaround — it's the correct methodology for proving evaluator
equivalence independent of agent variability. What matters is evaluator
faithfulness, not agent determinism.

**When to report as inherent (Category D only):**

- After trace-pinning, if a genuine LLM-as-a-Judge metric (Phoenix classifier, Strands
  `OutputEvaluator`) still shows >0.1 divergence after 2 fix attempts on the SAME traces,
  that's inherent LLM nondeterminism in the evaluator itself — report in summary.json.
- For Lambda-mandatory metrics, divergence after trace-pinning = handler bug. Fix it.

### Step 1: Classify

1. All after-scores 0.0? → **Category A** (structural bug) → fix from table above
2. Scores systematically inverted? → **Category A** (scale bug)
3. Non-zero but diverging? → **Category B** (semantic mismatch) → fix with strategy change
4. Context-precision metric diverging at all? → check per-sample chunk counts. If
   the diverging samples are exactly those with >1 chunk → **Category C**
   (flattened lists) → regenerate. Do not require an all-1.0/all-0.0 pattern:
   with mixed chunk counts only the multi-chunk samples move.
5. Live-agent task with inconsistent divergence across runs? → **Category D** (response nondeterminism) → trace-pin
6. Using Lambda+DeepEvalAdapter or RagasAdapter but still diverging? → Debug handler (env, model, fields)

### Step 2: Iterative Fix (keep going until ≤ 0.1)

**There is NO iteration cap for Lambda-mandatory metrics** — if Lambda is deployed
and still shows divergence, the handler has a bug. Keep fixing the handler.

**But re-running an unchanged deployment is not a fix attempt.** The uncapped budget above is
for *changing* something and measuring again. Re-running `evaluate()` while the handler, the
prompt, the `ratingScale` and the traces are all byte-identical measures the same thing twice
and only re-rolls the judge's nondeterminism. Do it at most ONCE, to establish whether a
divergence reproduces:

- **It reproduces** → it is a property of the deployment, not a bad draw. Fix something or
  report it. Running it a third time is not progress.
- **It does not reproduce** → the metric is noisy at this case count. Record both readings in
  `summary.json` and move on; do not keep drawing until one passes.

Repeating an identical evaluation until the number comes in under 0.1 does not make the
migration faithful, it makes the result a lucky draw, and it is the single largest waste of a
task's time budget — one trial spent 3527 of its 3600 seconds doing exactly this. Each new
attempt must change the handler, the evaluator config or the traces. If you cannot name what
changed since the last run, do not run it again.

**For genuine LLM-as-a-Judge metrics** (Phoenix classifiers, Strands `OutputEvaluator`;
every DeepEval and RAGAS metric, GEval included, is Lambda-mandatory):
try up to 2 fix iterations. Each iteration should try a fundamentally different approach:

1. **Structural ADOT fix** — fields missing, format wrong
2. **Prompt extraction fix** — use the exact prompt from the original source, not rewritten
3. **Field delivery fix** — a source placeholder that never reached the judge, re-embedded
   into `{context}` under a label the prompt body references
4. **Label order fix** — the deployed `ratingScale` order does not reproduce the source's
   label-to-score mapping

All four restore something the original had. **None of them changes what the judge is asked
to decide.** Once the prompt is the recovered source text and every source field arrives,
there is no fix left to apply: rewording `instructions`, adding guidance or a default,
switching the scale, or writing a `definition` that names a condition all move the judge
rather than the migration, and they turn a real divergence into a hidden one. Correct a
deployed evaluator with `UpdateEvaluator` on its existing ID; never deploy a second,
suffixed evaluator (see deployment-llmaaj.md).

Options 3 and 4 only exist while something is still missing or mis-ordered. **A verbatim
prompt whose fields all arrive is a terminal state** — report the remaining divergence as
inherent, having changed nothing. Zero fix iterations is a valid outcome.

After 2 iterations for LLM-as-a-Judge metrics, report remaining divergence as inherent.

### Step 3: When to Stop

**Lambda-mandatory metrics:** If divergence > 0.1 with DeepEvalAdapter or RagasAdapter,
the handler has a bug (env vars, model config, field extraction). Fix the handler — there is
no attempt cap here and "inherent" is never the answer, because the Lambda runs the original's
own metric code. Below 0.1 the metric passes; a deterministic metric should land at ≈0.0 and a
residual of a few hundredths on an LLM-based one is the judge, not a bug. If the Lambda cannot
be deployed due to insufficient disk, STOP and report to user.

**LLM-as-a-Judge metrics (Phoenix classifiers, Strands `OutputEvaluator`):** After 2
fix attempts, report remaining divergence as inherent in `summary.json`. Include which
cases diverged, why, and what was attempted.

## Metric-Specific Recipes

### ToolCorrectnessMetric — Lambda (DeepEvalAdapter)

- **Inputs:** it compares the tools the agent called with the tools the case expects,
  which the client passes per case as Metric Inputs (`--metric-inputs-map
  expected_tools=<trace field> --metric-inputs-map tools_called=<trace field>`, or
  `metric_inputs={"expected_tools": [...], "tools_called": [...]}` from `_run_agent()`).
  If either list is in neither the case's Metric Inputs nor its spans, the Lambda
  returns `MISSING_REQUIRED_FIELD`.
- **Algorithm:** the Lambda runs DeepEval's own code. By default each expected tool
  counts once it matches a distinct called tool by name, and the score is the matched
  fraction of the expected tools: extra calls cost nothing, and 1 of 2 expected tools
  scores 0.5. `evaluation_params` can also require matching arguments or output, and
  `available_tools` adds an LLM tool-selection score (the lower of the two is reported).
- **Edge case:** an empty list in Metric Inputs stays empty, so as in DeepEval 4.2.3 a
  case that expects no tools scores 1.0 if it called none, else 0.0.

### ArgumentCorrectnessMetric — Lambda (DeepEvalAdapter)

- **Inputs:** it scores the tools the agent called, which the client passes per case as
  Metric Inputs (`--metric-inputs-map tools_called=<trace field>`, or
  `metric_inputs={"tools_called": [...]}` from `_run_agent()`), each with its
  `input_parameters`.
- **Edge case:** DeepEval returns 0.0 when `input_parameters=None`. The Lambda runs the
  same code, so pass the arguments the source had rather than working around it.

### GEval — Lambda-mandatory; copy the rubric verbatim

- **Deployment:** Lambda with DeepEvalAdapter, never LLM-as-a-Judge.
- **Rubric:** copy `name`, `criteria` or `evaluation_steps`, and `evaluation_params`
  into metrics.json exactly as the source spells them. Do NOT paraphrase or rewrite.
- **Key name:** DeepEval appends `_[geval]`; classify.py aligns it to the key the
  source reports (`NonAdviceMetric` → `non_advice_metric`).
- **The same rule applies to ALL LLM-as-a-Judge prompts:** Phoenix classifiers and
  Strands OutputEvaluator — always find and copy the original prompt verbatim.

### FaithfulnessMetric / ContextualX metrics — Lambda-Mandatory

- **Algorithm:** Multi-step NLI (claim extraction → entailment per claim)
- **Deployment:** Lambda+DeepEvalAdapter (exact replication, 0.0 divergence)
- **Do NOT use LLM-as-a-Judge** — single prompts cannot replicate multi-step NLI

### BiasMetric / ToxicityMetric — Lambda-Mandatory

- **Algorithm:** Multi-step (opinion generation → classification pipeline)
- **Deployment:** Lambda+DeepEvalAdapter
- **Do NOT use LLM-as-a-Judge** — appears to work on benign data but diverges on adversarial inputs
- **Scale:** on the pinned `deepeval==4.2.3`, 1.0 = clean and `threshold` is the MINIMUM
  passing score. Pre-4.0 scored the proportion of violations with `threshold` as a maximum,
  so a threshold copied from older source means the opposite of what it did there.

### SummarizationMetric — Lambda-Mandatory

- **Algorithm:** Multi-step coverage pipeline
- **Deployment:** Lambda+DeepEvalAdapter
- **Edge case in handler:** If `input` is a question (not a document), coverage = 0.0

### RoleViolationMetric — Lambda-Mandatory

- **Algorithm:** Single-turn violation detection over the response
- **Deployment:** Lambda+DeepEvalAdapter

### DeepEval multi-turn / conversational metrics — NOT SUPPORTED
`classify.py` marks these `path="unsupported"` and this skill version does not
migrate them: `ConversationalGEval`, `GoalAccuracyMetric`, `RoleAdherenceMetric`,
`ToolUseMetric`, `TurnContextualPrecisionMetric`, `TurnContextualRecallMetric`,
`TurnFaithfulnessMetric`, `TurnRelevancyMetric`, `ConversationCompletenessMetric`,
`KnowledgeRetentionMetric`, `TopicAdherenceMetric`.

Report them to the user as out of scope and migrate the remaining metrics. Do NOT
deploy them, and do NOT substitute an LLM-as-a-Judge approximation — a holistic
prompt diverges 0.27-0.49 from DeepEval's per-turn averaging, so an approximation
fails the divergence check anyway.

**RAGAS multi-turn metrics are unaffected** and remain fully supported.

## Reporting (in summary.json)

For each metric, report:

```json
{
  "metric": "hallucination",
  "before_mean": 0.9,
  "after_mean": 0.85,
  "divergence": 0.05,
  "status": "PASS",
  "deployment_path": "custom_llm_judge",
  "fix_iterations": 2,
  "fix_notes": "Replaced a paraphrased prompt with the verbatim Phoenix classifier template"
}
```

## Gotchas

| Agent might think... | But actually... | Instead... |
|---|---|---|
| "I'll run original and migrated scripts separately" | Two independent agent runs = different LLM responses = artificial divergence often >0.1 | Use trace-dump pattern: `_agentcore.py` captures traces, then validate with old evaluator on those SAME traces |
| "2 test cases is enough" | Single disagreement on 2 binary cases = 0.5 divergence | ≥5 cases for binary evaluators |
| "I'll use borderline test inputs" | Ambiguous inputs cause unavoidable divergence | Clear, unambiguous expected outcomes only |
| "2-3 cases enough for binary evaluators" | 1 disagreement on 3 cases = 0.33 divergence | ≥5 test cases |
| "I'll add test cases to reduce divergence" | Only use customer-provided cases | Report divergence as suggestion; don't modify test set |
| "I'll save artifacts after running the script" | Costs extra steps; may run out of budget | The `_agentcore.py` saves `scores_after.json` + `summary.json` internally; original script output captured in Step 0 |
| "Divergence > 0.1 means my migration is broken" | For genuine LLM-as-a-Judge metrics (Phoenix classifiers, Strands `OutputEvaluator`), borderline cases can cause legitimate disagreement | For LLM-as-a-Judge metrics: extract the exact prompt from source, confirm every source field reaches `{context}` and that the label order reproduces the source mapping, then report inherent if still > 0.1. For Lambda-mandatory metrics: divergence means the handler has a bug — fix it. |
| "I'll keep retrying until scores match" | Nondeterminism means borderline cases may never perfectly match | Diagnose root cause; if structural → fix; if borderline nondeterminism → report to user; if data-absent edge case → match zero-score; if semantic mismatch → match algorithm |
| "I'll write an LLM-as-a-Judge prompt for ExactMatch" | LLMs cannot reliably do exact string `==` comparison or `re.fullmatch()` | Use `DeepEvalAdapter(metric=ExactMatchMetric(...))` deployed as Lambda — the adapter handles all `BaseMetric` types including deterministic |
| "I'll use LLM-as-a-Judge for PatternMatch/JsonCorrectness" | LLMs cannot replicate regex engines or Pydantic schema validation | Use `DeepEvalAdapter(metric=PatternMatchMetric(...))` deployed as Lambda |
| "I'll write a custom LLM prompt for FaithfulnessMetric" | DeepEval's NLI pipeline is multi-step with claim extraction; single prompts diverge badly | Use `DeepEvalAdapter(metric=FaithfulnessMetric(...))` to wrap the actual metric |
| "The GEval metric key must be `helpfulness_[geval]`" | `_[geval]` is DeepEval's internal name; the key is whatever the original script reports | Keep the source's key in `scores_before.json`; `classify.py --scores-before` aligns `helpfulness_[geval]` to it |
| "I'll use cleaner metric names in scores_after.json" | Verifier matches by key name; mismatched keys = two failed metrics | Use IDENTICAL keys from `scores_before.json` |
| "Divergence is 0.12, close enough — I'll declare Category B" | For LLM-as-a-Judge metrics, confirm the prompt and the fields first. For Lambda-mandatory metrics, "inherent" is NEVER valid — the handler has a bug. | LLM-as-a-Judge metrics: confirm `instructions` is the recovered source text and every source field reaches `{context}`, then report inherent — do not reword the prompt to close the gap. Lambda-mandatory: debug the handler (env vars, model config, field extraction). |
| "I'll run the multi-turn eval on all 5×8 conversations" | 5 conversations × 8 turns × N metrics = hours of API calls, will timeout | Subset to 3 conversations for multi-turn, running BOTH evaluators over the same 3 and recording the count in `summary.json` (SKILL.md, Core Invariants). Keep the evaluator at `--timeout 300` and the client run under `timeout 900`; a subset is what buys the headroom, not a larger timeout |
| "ToolCorrectness and the RAGAS NVIDIA metrics are simple enough for LLM-as-a-Judge" | ToolCorrectness is arithmetic over tool lists, with partial credit and empty-list cases, and each NVIDIA metric averages two judge prompts. One prompt reproduces neither, and `generate_handlers.py` refuses a DeepEval or RAGAS metric routed to `llm_judge` | Every supported DeepEval metric → Lambda with DeepEvalAdapter; every supported RAGAS metric → Lambda with RagasAdapter; DeepEval conversational → unsupported, do not migrate |
| "I'll install Node.js upfront for all deployments" | Node.js is only needed for Lambda path (agentcore CLI uses CDK) | Skip Node.js entirely for pure LLM-as-a-Judge deployments — saves time |
| "I'll keep iterating on the same LLM-as-a-Judge prompt" | Tweaking a recovered prompt moves the judge, not the migration | Do not tweak it at all. Check instead that every source placeholder reaches `{context}` and that the `ratingScale` order reproduces the source mapping; fix whichever is wrong with `UpdateEvaluator`, then stop |
| "I'll keep retrying with the same strategy" | Nondeterminism means indefinite retry won't help | Retrying is not the fix and neither is rewording. Confirm field delivery and label order once; if both are right, report inherent |
| "Lambda failed due to disk space, I'll use LLM-as-a-Judge for Faithfulness/Bias" | Multi-step NLI CANNOT be faithfully replicated by a single prompt. Divergence will be 0.2-0.5. | Clean up previous deploy artifacts (`rm -rf cdk.out node_modules *.zip`), retry. Deploy one at a time. If truly unfixable, STOP and report to user |
| "DAGMetric is just checking format and content quality, an LLM can do that" | DAGMetric uses a hardcoded decision tree with deterministic node traversal. LLM diverges 0.2-0.5 | Deploy as Lambda with DeepEvalAdapter. DAGMetric is deterministic — LLM-as-a-Judge is NEVER valid |
| "The original eval script only needs deepeval" | DeepEval's Bedrock judge imports `aiobotocore` transitively; without it the script crashes before writing scores_before.json | Install it in Step 0 for **DeepEval sources ONLY**: `pip install "aiobotocore==3.9.1"`. NEVER for RAGAS/Phoenix/Strands — it caps botocore below the SDK's floor and pip backtracks for minutes (see SKILL.md, Runtime requirements) |

## Divergence Rules

Divergence must be ≤ 0.1 **for every metric individually**. A mean divergence of 0.09
is meaningless if one metric has 1.0 divergence — the migration is still broken.
Check each metric key independently: `abs(mean_before - mean_after) <= 0.1`.

1. **Divergence > 0.1 only applies to LLM-as-a-Judge metrics.** Lambda + adapter
   (DeepEvalAdapter/RagasAdapter) runs the actual metric → divergence ≈ 0.0 for
   deterministic metrics and small for LLM-based ones. Every DeepEval and RAGAS
   metric deploys this way.
2. **For Lambda+adapter metrics, divergence >0.1 means the handler is BROKEN** —
   do not accept as "inherent". EVER. Do NOT rationalize it as "the Lambda is
   scoring more correctly" or "inherent to how the metric evaluates this input."
   Lambda runs the same metric code as the original — if scores differ, the INPUT
   data is being corrupted in transit. Traces topology should yield ~0.0; live
   topology should yield near-zero after trace-pinning (see the live-agent fix loop
   below).
3. **For LLM-as-a-Judge divergence fixes**, use the Root Cause Classification above.
4. **Try up to 2 fix iterations for genuine LLM-as-a-Judge metrics** (Phoenix
   classifiers, Strands `OutputEvaluator`). If still > 0.1, report as inherent
   divergence in `summary.json`.
5. **DeepEval and RAGAS metrics MUST NOT use LLM-as-a-Judge as a fallback**, whether
   multi-step, multi-turn, deterministic or GEval. They require Lambda. If Lambda
   deployment fails, apply the known fix and retry.
6. **Context-precision metrics (LLMContextPrecision etc.) where the original passes
   `retrieved_contexts` as a LIST of chunks: keep the list a list.** The generated
   client script passes ranked chunk lists through as a JSON array and the
   RagasAdapter recovers them in order — do NOT join chunks into one string
   (that collapses precision@k to a binary judgment; divergence ≈ 1.0).
   If per-sample migrated scores are all 1.0 while originals are fractional,
   this is context flattening. Fix: regenerate the client script, verify the
   traces carry context as a LIST, confirm ADOT embeds it as a JSON array.
7. **ALL metrics must reach ≤ 0.1 divergence to pass.** For Lambda-mandatory metrics,
   divergence > 0.1 means the handler is broken — find the technical fix.
   **EXCEPTION, LLM-as-a-Judge metrics only:** for live-topology tasks where trace-pinning
   has been performed and per-case scores show LLM nondeterminism (same input yields
   different scores locally), report as inherent after trace-pinning + 2 fix attempts. Do
   NOT retry indefinitely — credential expiry is worse than reporting inherent divergence.
   This exception never extends to a Lambda+adapter metric, which has no judge of its own:
   rule 2 above governs it, and "inherent" is never a valid outcome there.
8. **For Topology B (live agent): trace-pinning is MANDATORY before accepting any
   divergence.** See the live-agent fix loop below — you MUST overwrite `scores_before.json`
   from the same traces. Simply proving divergence is low without persisting it is
   NOT sufficient.

### Divergence Diagnosis Table (jump to fix, don't iterate)

| Divergence Pattern | Root Cause | Fix |
|---|---|---|
| All scores = 1.0 (or fixed constant) | `EvaluatorOutput(score=...)` — value is None, falls back to label | Change to `EvaluatorOutput(value=...)` |
| Every result has `explanation: null` | `EvaluatorOutput(reason=...)` — accepted and discarded as an unknown field | Change to `EvaluatorOutput(explanation=...)` |
| All scores = 0.0 | Handler returning error (check Lambda logs) | Check EvaluatorOutput has no errorCode set |
| Context-precision scores all 1.0 | Context list flattened to single string | Verify list passthrough in client script + ADOT |
| One metric diverges, others perfect | Metric-specific handler bug (field parsing) | Check that specific handler's input parsing |
| Scores correct for some cases, wrong for one | LLM judge nondeterminism (LLM-based metrics only) | Trace-pin: re-run original on same traces |
| Migrated judge saturates (1.0 on every case) while the original docks specific cases | The adapted prompt lost fields the original judges with — Phoenix `{{tool_call}}`/`{{tool_result}}` flattened into `{context}`/`{assistant_turn}` | Embed the lost fields into `{context}` with labels (see deployment-llmaaj.md, placeholder adaptation) via `UpdateEvaluator`. This fix restores a missing field and nothing else — if every source field already arrives, the saturation is not an adaptation error and the prompt must not be touched |

### Lambda Handler Error Diagnosis

| Error Message | Cause | Fix |
|---|---|---|
| `Evaluator must return an EvaluatorOutput` | Handler returns dict instead of EvaluatorOutput | Add `EvaluatorOutput` import, change return |
| `No module named 'datasets'` | Handler overwritten without stub prelude | Re-package: tool adds stubs automatically |
| `METRIC_ERROR` "Pass an LLM or embeddings wrapper" | Missing `llm=` or `embeddings=` | Verify component_setup in handler |
| `MISSING_REQUIRED_FIELD` | The case lacks a field the metric requires (reference, retrieved contexts, or the Metric Inputs its mapping.json notes name) | Supply it with `--field-map` or `--metric-inputs-map`; if the case has it, regenerate the handler with generate_handlers.py |
| `FIELD_EXTRACTION_ERROR` | The spans carry no user message, or for a multi-turn metric no conversation turns | Check the ADOT conversion, and that a multi-turn evaluator is SESSION level |
| `UNSUPPORTED_METRIC` | The RAGAS metric exposes none of `single_turn_score`, `multi_turn_score` or `score` | Regenerate the handler with generate_handlers.py, which passes a `ragas.metrics` instance |
| Zip too large for `update_function_code` | Deployment package > 50MB | Use S3 upload path |

## Metric Key Name Rules

The `scores_before.json` and `scores_after.json` MUST use IDENTICAL metric key names.
`classify.py --scores-before` aligns all downstream keys against the baseline
automatically (including ragas column aliases like RubricsScore → `domain_specific_rubrics`).

**Use the EXACT key names the original eval script produces.** If the original
writes `"coherence": 0.6`, the migrated script MUST also use `"coherence"`. Do NOT
append DeepEval internal suffixes (`_[geval]`, `_[dag]`) unless the original
script itself uses them.
Consistency between before and after is mandatory.

**Named-metric key alignment (GEval, DAGMetric):**

- `classify.py` derives `{name}_[geval]` / `{name}_[dag]` (e.g. `nonadvicemetric_[geval]`)
  and also tries the name in snake_case (`non_advice_metric`), ignoring case, so a
  baseline that reports `NonAdviceMetric`, `non_advice_metric` or `non_advice` aligns.
- Run classify.py WITH `--scores-before`. If a key still fails to align, check that the
  metric's `"name"` in metrics.json is the source's `name=`. Never rename the baseline's
  keys to classify.py's derived ones: the keys must stay what the original reports.

## Live-Agent Divergence Fix Loop (Topology B)

For live-agent tasks, response nondeterminism is the primary divergence source.
The agent produces different outputs each run, so running the original script
independently from the agentcore script will ALWAYS show some divergence on
borderline test cases. **Trace-pinning eliminates this — it is NOT optional.**

1. **The `_agentcore.py` script generates traces AND runs deployed evaluators.**
   It saves conversation traces (agent inputs/outputs) to `traces.json` and produces
   `scores_after.json` from AgentCore evaluate() calls.
2. **If divergence > 0.1 on any metric:** write a validation script that reads the
   SAME `traces.json`, reconstructs test cases from it, runs the ORIGINAL local
   evaluators, and **OVERWRITES `scores_before.json`**. You MUST persist that
   file — proving divergence is low without saving it is NOT sufficient.
3. **If STILL diverging:** the handler has a bug. Use the Divergence Diagnosis Table
   above rather than iterating; it maps each symptom straight to its fix.
4. **After trace-pinning + 2 fix attempts on genuinely LLM-based metrics:** report
   as inherent divergence in `summary.json` and STOP. Credential expiry is worse
   than reporting inherent divergence.
