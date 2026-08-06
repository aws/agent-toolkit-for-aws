# Select for Deployment

Select a base model to deploy by filtering the catalog against the user's `use_case_spec.md`.

## Prerequisites

- A `use_case_spec.md` file exists with a **Deployment Constraints** section. If not, activate the `use-case-specification` skill first.

## Step 1: Discover Available Filter Values

Run: `python3 model-selection/scripts/get_deployable_models.py <hub-name> --list-values`

This returns a JSON object showing all unique values available for each filterable field in the catalog. For example:

```json
{
  "tasks": ["text generation", "image classification", "translation", ...],
  "sizes": ["1b", "1b-10b", "10b-70b", "70b-100b", ">100b", ...],
  "data_types": ["text", "vision", "audio", "multimodal", "tabular"],
  ...
}

```

## Step 2: Map Soft Constraints to Hard Filters

Read `use_case_spec.md` and extract the **Deployment Constraints** section. These are natural language preferences from the user.

For each constraint in the spec, compare the user's words against the available values from Step 1 and select the best matching filter value(s):

| Spec Field | Filter Key | Mapping Approach |
|---|---|---|
| Task | `task` | Match user's description to closest value(s) in `tasks` list. E.g., "chatbot" → "text generation" |
| Data type | `data_type` | Match to closest value in `data_types` list |
| Size preference | `size` | Map descriptive language to size bucket(s). E.g., "small" → "1b" and "1b-10b"; "large" → "10b-70b" and "70b-100b" |
| Deployment target | `bedrock` | If "Bedrock" → `bedrock:true`. If "SageMaker" or "either" → no filter needed |
| License | `license` | Match to closest value in `licenses` list. Use substring matching. |
| Context window | `context_window` | Map to closest bucket. E.g., "long documents" → "32k-128k" or ">128k" |
| Languages | `language` | Match to value in `languages` list |
| Model type | `model_type` | "open source" / "open weights" → "open_weights"; "proprietary" → "proprietary" |
| Recency | *(not a filter)* | If user wants "latest" or "newest", sort filtered results by `original_creation_time` descending and present the most recent models first |

**Rules:**

- If a user's preference maps to multiple valid values (e.g., "small" could be "1b" or "1b-10b"), pass all of them as separate arguments with the same key (e.g., `"size:1b" "size:1b-10b"`). The filter OR-s values within the same key.
- If a preference doesn't clearly map to any available value, skip it (don't filter on it).
- If the user said "any" or "don't care", do not create a filter for that field.

Present your mapping to the user for confirmation before filtering:

> "Based on your preferences, I'll filter with these criteria: [list each mapping]. Does this look right?"

⏸ Wait for user confirmation. If they disagree, adjust.

## Step 3: List Models and Apply Filters

Run: `python3 model-selection/scripts/get_deployable_models.py <hub-name> > /tmp/deployable_models.json`

Then run the filter script with the resolved filter values:

```
python3 model-selection/scripts/filter_deployable_models.py /tmp/deployable_models.json <filter1> <filter2> ...

```

After filtering, report:

> "Based on your constraints, I applied these filters: [list each]. This narrowed [total_models] models down to [matched] candidates."

## Step 4: Handle Results

### If results are non-empty (≤20 models)

Present all matching models. Cross-reference with `references/model-licenses.md` for license links where available. Display each model on its own line:

```
<model name> — <size> | <license> | Bedrock: ✓/✗

```

Omit fields that are unknown rather than showing blanks. **Display every matching model — completeness is required.**

Ask the user to select:

> "Which model would you like to deploy?"

⏸ Wait for user selection. Once the user selects a model, **proceed immediately to Step 5** (do not confirm or hand off yet).

### If results are non-empty but large (>20 models)

Show the first 20, state how many total matched, and ask:

> "There are [matched] models matching your constraints. Here are the first 20. Would you like to see more, or would you like to tighten your constraints to narrow further?"

### If results are empty

Re-run the filter script with one constraint removed at a time to identify which filter is most restrictive (eliminates the most models). Report:

> "No models matched all your constraints. The most restrictive filter was [field]: [value], which eliminated [N] candidates. Would you like to relax this constraint?"

If the user agrees, adjust the filter and re-run from Step 3. If they want to change their use case spec, activate the `use-case-specification` skill, then re-run from Step 1.

## Step 5A: Select Instance Type

Once the user selects a model, use the AWS API `describe-hub-content` (SageMaker service) with:

- `HubName`: the hub name from Step 1
- `HubContentType`: "Model"
- `HubContentName`: the selected model name

From the response, parse the `HubContentDocument` JSON and determine the instance type:

### If `InferenceConfigs` exists (labeled configs):

The model has pre-configured hosting profiles optimized for different use cases. Each config name follows the pattern `<use-case>_<optimization>`, e.g.:

- `generate_best_price_performance` — balanced cost/speed for text generation
- `summarize_lowest_latency` — fastest for summarization tasks
- `interact_lowest_cost` — cheapest for interactive/chatbot use
- `max_context_best_price_performance` — best value for long-context inputs

Each config includes `BenchmarkMetrics` with latency and throughput per instance type.

**Recommend a config** based on the user's use case from `use_case_spec.md`:

1. Match the use-case prefix (`generate`, `summarize`, `interact`, `max_context`, `modify`) to the user's task.
2. Default to `best_price_performance` optimization unless the user expressed a preference for speed (`lowest_latency`) or cost (`lowest_cost`).
3. Use the `DefaultInferenceInstanceType` from the matched config component as the instance type.
4. Present your recommendation with the benchmark metrics:

> "For your use case ([task]), I recommend the **[config_name]** hosting configuration on **[instance_type]** ([latency] latency, [throughput] throughput). There are [N] other configurations available if you'd like to optimize differently. Would you like to proceed with this, or see other options?"

⏸ Wait for user confirmation or selection.

### If `InferenceConfigs` does NOT exist (no labeled configs):

The model has basic hosting info only. Collect ALL available instance types from both sources:

1. `SupportedInferenceInstanceTypes` — the top-level list
2. `HostingInstanceTypeVariants.Variants` — keys in this object are instance families or specific instance types (e.g., `g5`, `ml.g5.2xlarge`) that also support the model

Merge both into a single candidate set (union, deduplicated). The `HostingInstanceTypeVariants` often contains smaller/cheaper instances not listed in `SupportedInferenceInstanceTypes`.

From the merged set, select the **cheapest** instance type as the default recommendation. Consider both:

1. **Instance family** (cost tier): `g4dn` < `g5` ≈ `g6` < `g6e` < `p4d` < `p5`
2. **Instance size** (suffix): `xlarge` < `2xlarge` < `4xlarge` < `12xlarge` < `24xlarge` < `48xlarge`

Pick the cheapest family available, then the smallest size within that family.

**Important:** A hosting config entry (with `ResourceRequirements`, `ImageUri`, etc.) is NOT required to recommend an instance. If an instance family appears in `HostingInstanceTypeVariants` with just an `ImageUri`, that is sufficient — the model can run on it. Do not bias toward instances that have a more detailed config. Always recommend the cheapest option regardless of whether it has a full config or just an image URI.

Present:

> "For this model, I recommend starting with **[cheapest_instance]** (the most cost-effective supported instance). Other supported options from smallest to largest: [list]. Would you like to proceed with this, or choose a different instance?"

⏸ Wait for user confirmation.

---

## Step 5B: Resolve Hosting Configuration

> ⚠️ Do NOT proceed to Step 6 until you have completed this step. The user confirming an instance type does NOT mean the step is done.

Now that the instance type is confirmed, resolve the hosting configuration:

1. Check `RecipeCollection` entries in the `HubContentDocument`. Within each recipe, look at `HostingConfigs` — an array of objects keyed by `InstanceType`.
2. Find an entry where `InstanceType` matches the confirmed instance (e.g., `ml.g5.2xlarge`).
3. If a match exists, it contains deployment-specific settings (`EcrAddress`, `Environment`, `ComputeResourceRequirements`, `Profile`). Record this as the hosting config.
4. If no match in `RecipeCollection`, check `HostingInstanceTypeVariants.Variants` for the instance family (e.g., `g5`). This may contain `ImageUri` or environment variable overrides.
5. If neither has a config for the selected instance, record that no hosting config was found.

---

## Step 6: Hand Off

Emit a flat deployment config with exactly these three fields:

- [ ] `model_id` — the selected Hub model ID.
- [ ] `instance_type` — the user-confirmed instance type.
- [ ] `inference_config_name` — the config name the user **confirmed** in Step 5A (the one you
      recommended, or a different one they chose), e.g. `generate_best_price_performance`, so
      deployment deploys THAT config instead of the SDK's top-ranked default. This is required
      whenever the model has labeled `InferenceConfigs`: because the instance type was derived from
      this config, omitting the name lets deployment pick a different (top-ranked) config for which
      the chosen instance may be unsupported. If the user switched to a different config, make sure
      the `instance_type` you hand off is that config's `DefaultInferenceInstanceType` (re-derive
      it), so the pair stays consistent. Set it to `null` ONLY on the Step 5A "no labeled configs"
      path.

Do NOT hand off the image URI / environment / `ComputeResourceRequirements` resolved in Step 5B —
the serving container and environment are re-resolved from `inference_config_name`, so Step 5B stays
a validation step (confirm a hosting config exists for the chosen instance) and its output is not
part of the hand-off. Do not emit the role ARN, region, or endpoint/model naming either — those are
set at deployment time, not here.

If any of the three fields is missing, go back and resolve it before proceeding.

Return to Step 4 of the main SKILL.md (Confirm Selection) with these outputs.
