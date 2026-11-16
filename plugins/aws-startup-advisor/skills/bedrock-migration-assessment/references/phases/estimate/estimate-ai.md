# Estimate

Prices the design in `$MIGRATION_DIR/aws-design-ai.json` and writes `$MIGRATION_DIR/estimation-ai.json` in the provider-neutral contract `references/vendored/ai/schema-estimate-ai.md` (JSON Schema: `references/contracts/estimation-ai.schema.json`). This skill writes that contract's shape; the contract's Status section describes what gcp-to-aws and azure-to-aws emit today. This phase covers AI inference cost only: no compute, database, storage, or networking.

**Execute every step in order.** The inputs are `aws-design-ai.json`, `ai-workload-profile.json`, `preferences.json`, and the usage profiles Discover wrote (`openai-usage-profile.json`, `anthropic-usage-profile.json`, `openrouter-usage-profile.json`). Read nothing outside `$MIGRATION_DIR` and this skill, and write nothing outside `$MIGRATION_DIR`.

## Step 0: Compute the figures

```bash
python3 <SKILL_BASE>/scripts/estimate-ai.py plan $MIGRATION_DIR
```

Read the JSON it prints. Do not redirect it to a file. On a non-zero exit, stop and tell the user:

| `error`                 | What to tell the user                                                                    |
| ----------------------- | ---------------------------------------------------------------------------------------- |
| `design_not_found`      | Design has not finished; resume at Design.                                               |
| `design_invalid`        | `aws-design-ai.json` no longer passes `design-ai.py check`; re-run Design.               |
| `token_volume_unknown`  | Clarify's Q7 answer is not a known tier; re-run Clarify.                                 |
| `usage_unreadable`      | A usage profile is damaged; re-run that usage reader in Discover, or remove the file.    |
| any other value         | Quote `detail`.                                                                          |

The script does the arithmetic. Copy its numbers; never recompute or round them differently. It reads every price from the design rows' `bedrock_price` and `source_provider_price`, so a price Design wrote as `unverified`, or per image, stays unknown here.

- `token_volume.basis` is `measured` when every source model in the design has full-window usage from a usage profile, and `tier` otherwise. A `tier` basis prices the Q7 band's bounds from `token-volume-tiers.json`, because the user named a band, not a number. A band with no upper bound (`very_high`) has only a lower bound.
- `projected_bedrock_monthly_range` and `source_list_monthly_range` are the total monthly cost at Bedrock rates and at the source provider's list rates. On a `tier` basis the range covers every way the traffic could be split across the design's targets, so it can be wide; `per_model[].if_all_traffic` gives each model's range if it carried the whole band.
- `source_measured_monthly` is the measured spend from the usage profiles, only on a `measured` basis with every cost read successfully.
- `cost_comparison` holds single figures only when they are known: a range or a missing price leaves them `null`, never `0`.
- `cost_by_source`, `services_not_estimated`, and `pricing_source` are written as given.
- `models_in_two_sources` lists models two sources share; say in the summary that their cost appears under both.
- `usage_unmatched` lists usage-profile models with no design row; name them in the summary as measured but not designed.
- `overlap_excluded` lists OpenRouter rows left out because a direct usage profile already counts that model's BYOK traffic; name them in the summary, with `spend_excludes_usd` when it is above zero.

## Step 1: Model comparison

Write `model_comparison[]`, one entry per Bedrock target in the design and per alternative the design's rationale names, with `model`, `monthly_cost` (the target's figure from `per_model`, or its `if_all_traffic` range as `{low, high}`), `vs_current`, `quality`, `capabilities_match`, and `missing_capabilities[]`.

- Apply the lifecycle rules in `references/vendored/ai/ai-model-lifecycle.md`: an Excluded model is left out, a Legacy model carries `(Legacy — EOL YYYY-MM-DD)`, and a `restricted (…)` model in `references/vendored/ai/bedrock-pricing-cache.md` is never `recommended_model` or `backup_model`.
- An alternative's price comes from `bedrock-pricing-cache.md` at the same token basis. A cell marked `_unverified_` is unknown: write `null`, never a sibling's rate.
- Long context: use the exact published rate for the model, Region, and inference profile. Opus 5.5 has no long-context surcharge. For GPT-5.x and GPT-6, both the source and the Bedrock side must use the same context tier; when request sizes are unknown, write `pricing_tier: "approximate — request-size distribution unknown"`.

`recommended_model` is the design's target for the main workload, with its figure and a rationale that names the user's priority and volume. `backup_model` is the next-best entry, or `{"model": null, "rationale": "..."}` when there is none. `embeddings` is present only when the design has an embedding row.

## Step 2: Current cost and ROI

- `current_costs`: `source` is `measured_usage` when `source_measured_monthly` is a number, `list_price` when only `cost_comparison.current_source_monthly` is, and `unknown` otherwise; `monthly_ai_spend` is `cost_comparison.current_source_monthly`; `services` lists each source service. When `preferences.json` has a Q3 `ai_monthly_spend` band, name it in the summary as the user's own answer.
- `roi_analysis`: the three figures from Step 0 (`projected_bedrock_monthly_range`, `source_list_monthly_range`, `source_measured_monthly`), `monthly_cost_delta` and `annual_cost_delta` from `cost_comparison`, `justification`, and `non_cost_benefits[]`. A same-model move (`model_change: false`) is priced at the selected inference option, not at an assumed premium or parity. When Bedrock costs more, say so and name the non-cost benefits, or say it is not justified on cost alone.
- `migration_cost_considerations`: `categories` is always `[]`, `note` says human and professional-services migration costs are excluded, and `complexity_factors[]` lists technical factors only (integration pattern, model count, `quota_risk: "high"` needing a quota increase).

## Step 3: Optimizations

Write `optimization_opportunities[]` only for levers that fit this workload. Every entry has `opportunity`, `type`, `target_services: ["Bedrock"]`, `commitment`, `potential_savings_monthly` (a number or `null`), `potential_savings_percent` (always set), `available`, `implementation_effort`, and `description`.

| `type`                       | `potential_savings_percent`          | `commitment`                     | When                                                                                   |
| ---------------------------- | ------------------------------------ | -------------------------------- | -------------------------------------------------------------------------------------- |
| `prompt_caching`             | up to 90% on cached input tokens     | `none`                           | Repeated system prompts or long shared context, on a model and API that cache          |
| `batch_api`                  | 50% of on-demand                     | `none`                           | `ai_latency` is `flexible` and the model's batch rate is confirmed in the pricing cache |
| `model_tiering`              | 60-87%                               | `none`                           | High volume with a premium model selected                                              |
| `multi_model_routing`        | 60-87%                               | `none`                           | The design has a `tiered_strategy`                                                     |
| `intelligent_prompt_routing` | up to 30%                            | `none`                           | `router_available` is true (a Claude or Llama target) and routing latency is acceptable |
| `input_token_reduction`      | 10-30%                               | `none`                           | Long prompts that can be shortened                                                     |
| `provisioned_throughput`     | varies                               | `no-commit, 1-month, or 6-month` | Sustained, predictable traffic above 100M tokens a month                               |

Provisioned Throughput has no 1-year or 3-year term. These levers have no upfront cost, so add no Activate-credits caveat. `optimized_projection` is the best-case monthly figure with the applicable levers, or `null` when the base figure is unknown, with a `note`.

## Step 4: Recommendation

| Condition                                                                                   | `recommendation.path` |
| ------------------------------------------------------------------------------------------- | --------------------- |
| Design's `honest_assessment` is `recommend_stay`                                             | `stay`                |
| Bedrock costs more, `ai_priority` is `cost`, and no non-cost reason justifies the move       | `stay`                |
| Some workloads favor the move and some do not                                                | `migrate_phased`      |
| Otherwise (cheaper, same model, or more expensive with a justifying non-cost reason)        | `migrate_optimized`   |

Write `path`, `path_label`, `migrate_if`, `stay_if`, `confidence`, and a `rationale` that cites the figures from Step 0. A `tier` basis or a missing price lowers `confidence`; say why.

## Step 5: Write and check

Write `$MIGRATION_DIR/estimation-ai.json` with `phase: "estimate"`, `timestamp`, `pricing_source`, and `accuracy_confidence` (`±15-25%` for cached prices), then:

```bash
python3 <SKILL_BASE>/scripts/estimate-ai.py check $MIGRATION_DIR
```

Fix every reported `errors[]` entry and run the check again until it prints `"ok": true`. Do not complete Estimate while it fails. The check enforces the contract, every figure from Step 0, `cost_by_source`, `services_not_estimated`, the `recommend_stay` rule, the Provisioned Throughput term, and Intelligent Prompt Routing availability. It cannot judge the comparison, the optimizations you chose, or the rationale.

## Step 6: Present the summary

In under 25 lines, labeling every dollar figure as an estimated monthly cost:

1. The pricing source and accuracy, and whether the volume was measured or a Q7 band.
2. Current cost (measured, list price, or the Q3 band) against the projected Bedrock cost or range.
3. A model comparison table: model, estimated monthly cost, vs source, capabilities match.
4. The recommended model, and the cost increase with its non-cost justification when Bedrock costs more.
5. The top two or three optimizations, with Provisioned Throughput's terms when it is listed.
6. The recommendation, and that Generate is not in this skill yet.
