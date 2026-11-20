# Troubleshooting: Common Mistakes, Heuristics, Domain Knowledge

Lookup reference for when a step fails or a decision is ambiguous. Read the
relevant section rather than the whole file.

## Contents

- [Common Mistakes to Avoid](#common-mistakes-to-avoid)
- [Decision Heuristics](#decision-heuristics)
- [Domain Knowledge](#domain-knowledge)
- [Framework Compatibility Fixes (baseline run only)](#framework-compatibility-fixes-baseline-run-only)

## Common Mistakes to Avoid

| Agent might think... | But actually... | Instead... |
|---|---|---|
| "I'll run the agent inside evaluate_case() each time" | Agent calls take 1-5 min each; 6 cases × 3 metrics = timeout | **Use the generated two-phase pattern: capture traces ONCE, evaluate from saved traces** |
| "I'll chase missing Lambda deps one by one" | Each dep fix = 3-5 steps; the dep chain is deepeval→strands_evals→strands→docstring_parser→opentelemetry.instrumentation | **Re-run `bash deploy/migration.sh` (verify_deps runs inside it); fix pyproject.toml directly on the manual path** |
| "I'll install uv later if CDK complains" | CDK fails silently with exit code null | Run `scripts/deployer.preflight_check()` — it catches this |
| "I can use model_name= for AmazonBedrockModel" | The kwarg is `model=`, and `region=` is required | `AmazonBedrockModel(model="...", region="us-east-1")` |
| "I'll manually construct ADOT JSON for non-Strands agents" | Manual JSON causes validation errors | Instrument agent with OTel → `detect_otel_mapper()` → `to_adot_docs()` |
| "I'll manually patch CDK for x86_64" | You'll miss one of the two patches | Use `scripts/deployer.generate_migration_sh()` — it applies both |
| "I'll fix handler issues by redeploying from scratch" | Full redeploy costs 10-15 steps | Use `update_function_code()` for code-only fixes (but include full bundle!) |
| "pyproject.toml >=1.15.0 will get the adapters" | `>=` can resolve to a release with no `third_party` | Pin `bedrock-agentcore==1.23.0`; RAGAS uses the same pin, resolved from PyPI |
| "I can deploy all metrics then test" | If first fails, all fail the same way | Deploy ONE, test, then deploy rest |
| "LLM-as-a-Judge can approximate any metric" | Multi-step metrics are too complex to replicate in one prompt | Lambda is mandatory; never fall back |
| "I'll use DeepEval's internal key format (_[geval],_[dag])" | Output keys must match the original script's format | Copy exact key names from original output |
| "I'll upload just the handler .py to update Lambda code" | This destroys the full CDK bundle (100-300MB dependencies) | Download existing zip first, patch, re-upload — or CDK redeploy |
| "IAM role quota won't affect me" | Account often has 1000/1000 roles from old deploys | Check quota early; delete stale AgentCore roles if needed |

## Decision Heuristics

### When to use `update_function_code()` vs CDK redeploy

| Scenario | Approach | Rationale |
|---|---|---|
| Handler logic bug (code-only change) | Download existing zip, patch handler, re-upload | 2 steps vs 10-15 |
| Missing dependency in Lambda | CDK redeploy (after fixing pyproject.toml) | Need full bundling |
| CDK stack in ROLLBACK_COMPLETE | Delete stack and the `/aws/lambda/<project>-eval-*` log groups it left behind, fresh CDK deploy | Can't update failed stacks; the kept log groups block the redeploy |
| Second deploy needed after first succeeded | CDK deploy (it's incremental) | Safe and correct |

### When to accept divergence vs continue fixing

| Condition | Action |
|---|---|
| Lambda+adapter metric, divergence > 0.1, same traces | Handler is BROKEN — must fix |
| LLM-as-a-Judge metric, divergence > 0.1, prompt verbatim and all fields arriving | Report as inherent — do not reword the prompt |
| Divergence moves between runs with nothing changed | The metric is noisy at this case count, not fixable by repetition. Re-run once to confirm, record both readings, move on — never draw again until one passes |
| Live-topology, divergence > 0.1, WITHOUT trace-pinning | Trace-pin first (mandatory) |
| Live-topology, divergence > 0.1, WITH trace-pinning, LLM metric | Accept after 2 fix attempts |

## Domain Knowledge

1. **AgentCore service span normalization:** The service ALWAYS collapses multiple
   ADOT span documents with the same session_id into ONE span with multiple
   `span_events` entries. Each original span becomes one `span_event`.

2. **Lambda cold start timing:** First invoke after deploy takes 60-120s for
   bundles >50MB. Budget 2-3 minutes for the first evaluate() call.

3. **The `sed` commands in migration.sh for injecting dependencies fail frequently**
   because they match on package name strings that appear elsewhere
   in pyproject.toml (project name, comments). Always verify with grep after.

4. **`model=` / `async_mode=` in `init_kwargs` need no manual step.**
   `generate_handlers.py` drops a source-supplied value before appending the
   handler's own, so a duplicate keyword cannot reach the Lambda. It drops
   DAGMetric's `dag=` and JsonCorrectnessMetric's `expected_schema=` too, and leaves
   a `TODO(EVAL-MIGRATION)` block for copying the object from the source instead.

5. **Evaluator name fragment for resolve must match EXACTLY what was deployed.**
   The format is `{project}_{evaluator_name}` (without `deepeval_` prefix unless
   names.py generated it that way). Check `names.json` for the exact fragments.

## Framework Compatibility Fixes (baseline run only)

Apply the minimum needed to get the ORIGINAL script producing `scores_before.json`.

- **`aiobotocore` dependency conflict:** `pip install "aiobotocore==3.9.1" "boto3==1.43.75" "botocore==1.43.75"`.
  aiobotocore 3.9.1 caps botocore below 1.43.76 and bedrock-agentcore 1.23.0 needs
  1.43.72 or later, so these pins satisfy both without `--no-deps`.
- **CrewAI 1.15+:** use `crewai.LLM`, not `ChatBedrock`
