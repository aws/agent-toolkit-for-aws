# Select for Deployment

Select a base model to deploy by filtering the catalog against the user's `use_case_spec.md`.

## Prerequisites

- A `use_case_spec.md` file exists with a **Deployment Constraints** section. If not, activate the `use-case-specification` skill first.
- Public-Hub Search requires the boto3 and botocore versions enforced by `search_deployable_models.py`'s `MINIMUM_SDK_VERSION`. SageMaker PySDK v3 does not expose `Search(Resource="HubContent")`, so the public path intentionally uses the version-gated boto3 client. An older client triggers the visible List-and-filter fallback described in Step 3.

## Step 1: Discover Available Filter Values

Branch on the selected Hub.

### SageMakerPublicHub

Create one unique, short-lived catalog snapshot while discovering values:

```bash
python3 model-selection/scripts/get_deployable_models.py \
    SageMakerPublicHub --list-values --create-snapshot <region>
```

The command creates a unique private temporary file and returns four fields:

- `snapshot_file`: the file to reuse for preflight and Search.
- `available_values`: values observed in the compact `ListHubContents` keywords.
- `canonical_values`: every value allowed by the public-Hub producer's closed contracts.
- `canonical_rules`: how to handle language and provider, whose contracts are not closed lists.

`available_values` is an observation, not an allowlist: the Hub writes at most 50 keywords per model, so a value may be absent there while still present in the Search document. Record the exact `snapshot_file` value in conversation context; later commands MUST use that literal path.

The snapshot is a per-selection-session cache of compact, normalized `ListHubContents` summaries. It provides current keyword spellings, raw size values, `OriginalCreationTime`, local fallback data, and compatibility with models published before the canonical contracts. It does not contain credentials, model documents, or markdown. The canonical values and rules are static contract data returned alongside the snapshot, not inferred from it. Reuse the snapshot only while the Hub and region remain unchanged, and delete it as described under **Snapshot cleanup**.

### Private Hub

Run the existing discovery command without a snapshot:

```bash
python3 model-selection/scripts/get_deployable_models.py <hub-name> --list-values <region>
```

The private-Hub command returns only its observed values because private Hubs have no public producer contract and continue using local filtering. For the public Hub, the same observed object appears under `available_values`, alongside `canonical_values` and `canonical_rules`. An observed values object looks like:

```json
{
  "tasks": ["text generation", "image classification", "translation", ...],
  "sizes": ["<=10b", "11b-70b", "71b-100b", ">100b", "unknown"],
  "data_types": ["text", "vision", "audio", "multimodal", "tabular"],
  ...
}

```

## Step 2: Map Soft Constraints to Hard Filters

Read `use_case_spec.md` and extract the **Deployment Constraints** section. These are natural language preferences from the user.

> **ENFORCEMENT — read before mapping.** Apply these rules in order:
>
> 1. **Use only the tables and contract output below.** Do not infer size,
>    task, context-window, or canonical metadata values from model knowledge, and
>    do not substitute a "close enough" value. The same user words MUST produce
>    the same filter set every run.
> 2. **An absent observed value is still eligible.** `available_values` is the
>    capped keyword observation, not an allowlist. If a concrete public-Hub value
>    is absent there, keep it and let the deterministic preflight resolve it
>    through `canonical_values` or `canonical_rules`.
> 3. **Unknown or ambiguous → ASK.** Do not guess and do not run a fuzzy metadata
>    search. Run the Step 2f preflight first. If it cannot produce one
>    deterministic value, offer the candidates in its error and ask the user to
>    choose. For an unmapped soft term such as "qa," offer the relevant table
>    options before preflight.
> 4. **"any" / "don't care" → no filter** for that field.
> 5. **Pass each value in a cell as its own argument** with the same key; the
>    filter OR-s values within a key.

### 2a. Size — soft term → exact `size` value

`get_deployable_models.py` normalizes every model into one of five canonical size
buckets (`<=10b` / `11b-70b` / `71b-100b` / `>100b` / `unknown`). The four below
are the selectable values; `unknown` means the model's size could not be
determined — it is excluded by any size filter and has no soft-term mapping.

| If the user says… | Use exactly |
|---|---|
| small, tiny, lightweight, cheap, low-cost, smallest | `size:<=10b` |
| medium, mid-size, moderate | `size:11b-70b` |
| large | `size:71b-100b` |
| very large, huge, biggest, largest | `size:>100b` |

### 2b. Task — soft term → exact `task` value(s)

Task tags in the hub overlap and are matched by substring, so use these exact
OR-lists (do not shorten them — e.g. bare `task:classification` wrongly matches
image/tabular/token classification).

| If the user wants… | Use exactly |
|---|---|
| chatbot, chat, assistant, conversational, customer support | `task:text generation` `task:generation-text` |
| summarize, summarization, summaries | `task:text generation` `task:generation-text` |
| classify, classification, categorize | `task:text classification` `task:classification-text` |
| translate, translation | `task:translation` |
| code, coding, programming | `task:text generation` `task:generation-text` — then tell the user that code-focused models are not separately tagged; to find them, look for the `codellama`, `qwen-coder`, `starcoder`, or `granite-code` families by name |

> Note on summarization: the hub's dedicated `text summarization` /
> `summarization-text` tags are almost entirely older short-context (≤4k)
> seq2seq models (BART/Pegasus/DistilBART) that mostly lack a `context_window`
> value — so filtering on them (especially combined with a long-context
> constraint) returns few or zero usable models. Capable long-document
> summarizers are general instruction-tuned LLMs tagged `text generation` /
> `generation-text`, which is why "summarize" maps there.

### 2c. Context window — soft term → exact `context_window` value(s)

| If the user says… | Use exactly |
|---|---|
| short, small context | `context_window:<4k` `context_window:4k-8k` |
| medium context | `context_window:8k-32k` |
| long, long documents, long context | `context_window:32k-128k` `context_window:>128k` |
| very long, largest context | `context_window:>128k` |

> `context_window` uses the public-Hub canonical buckets exactly: `<4k` /
> `4k-8k` / `8k-32k` / `32k-128k` / `>128k`. A canonical bucket does not
> need to appear in `available_values`; the preflight can resolve it directly.
> A value outside these buckets, such as `16k`, is not canonical. Do not silently
> substitute a bucket; run preflight and ask the user to choose from the returned
> canonical options.

### 2d. Other fields — exact mappings

| Field | If the user says… | Use exactly |
|---|---|---|
| Data type | text | `data_type:text` |
| | image, vision | `data_type:vision` |
| | audio, speech | `data_type:audio` |
| | multimodal | `data_type:multimodal` |
| | tabular | `data_type:tabular` |
| | biology, protein, protein structure | `data_type:biology` |
| Model type | open source, open weights | `model_type:open_weights` |
| | proprietary, closed | `model_type:proprietary` |
| Deployment target | Bedrock | `bedrock:true` |
| | SageMaker, either, unspecified | *(no filter)* |

### 2e. Concrete fields — user names the value directly

For **license, language, provider, model name**, and **modalities**, the user names a concrete value rather than a soft category.

For the public Hub:

1. Check `available_values` first. A match preserves every current keyword spelling, including legacy aliases from models published before the canonical contracts.
2. If license, language, provider, or modality is absent, do **not** reject it. Keep the customer's value and run the Step 2f preflight. Closed fields resolve against `canonical_values`; language and provider follow `canonical_rules`.
3. Model name is the exception: it has no producer contract. It must match an observed model name; otherwise ask the user.

The preflight resolves case and known aliases. For example, `license:apache 2.0` becomes `Metadata.License = Apache-2.0`, and `language:somali` becomes `Metadata.Languages = Somali` even when neither value has a keyword. Provider is open text and is searched in the producer casings supported by the adapter.

A short language token can be both a code and a language name. For example, `so` can mean the ISO code for Somali or the language named So. Do not choose one. Let preflight return both interpretations, then ask: "Did you mean Somali, or So (Democratic Republic of Congo)?" ⏸ Wait for the answer. Do not run fuzzy Search over structured metadata.

For a private Hub, keep the existing rule: concrete values must appear in its Step 1 observed values because private selection has no public producer contract or metadata Search fallback.

The filter keys you pass are the same for every field. Internally the adapter
sends `data_type`, `input_modality`, `output_modality`, `model_type`, `bedrock`,
`customization`, `license`, `provider`, `task`, `size`, `context_window`, and
`language` as exact `Metadata.*` filters over the model document. License,
provider, and task also include exact `HubContentSearchKeywords` alternatives:
license and provider protect existing matches from new producer casing, while
task preserves legacy aliases that are not values of `Metadata.Task`. The
`name` filter uses `HubContentName`. A `size`,
`context_window`, `language`, or `license` filter can return a few models the
private-Hub path would not: the Hub writes at most 50 keywords per model, and a
model with many languages can run out of slots before its remaining metadata is
written. The document still carries every value, so Search finds the model and
the script fills in `size_raw`, `context_window`, `license`, and the missing
`languages` from the document. Present those models exactly like the others. A
contract-resolved language is requestable even if no model kept it as a
keyword; Search, not the keyword snapshot, determines whether a model carries
it.

### 2f. Preflight public-Hub values

After assembling the complete public-Hub filter list, resolve it without calling Search:

```bash
python3 model-selection/scripts/search_deployable_models.py \
    SageMakerPublicHub --snapshot-file <recorded-snapshot-path> \
    --resolve-only <filter1> <filter2> ...
```

Preflight reads the recorded snapshot and does not call AWS, so it does not need a region argument.

Handle the result as follows:

- **Exit 0:** The filters are deterministic. Record every `resolution_notes` entry; it names a value absent from the keyword snapshot and the exact document value that Search will use.
- **Unknown or ambiguous value:** The error says `Ask the user` and includes either canonical choices or language interpretations. Present those choices in one concise question and ⏸ wait. Do not substitute a value, omit the constraint, or call Search. After the user answers, replace the value and rerun this preflight.
- **Any other error:** Report it and stop. Do not bypass preflight.

This is the only value-validity gate for public-Hub Search. `available_values`
is consulted first for compatibility, but absence there does not reject a
contract-resolvable value.

**General rules:**

- If the user said "any" or "don't care" for a field, do not create a filter for it.
- If a soft term is not covered by the tables above, ASK a clarifying question and list the relevant mapped options so the user can choose (for tasks: chatbot/assistant, summarization, classification, translation; for size: small, medium, large, very large). Do not guess.
- For a concrete public-Hub value, let preflight determine whether it is canonical, unknown, or ambiguous. Do not reject it merely because it is absent from `available_values`, and do not use a fuzzy metadata query.

After preflight succeeds, present the resolved mapping to the user for confirmation. If `resolution_notes` is non-empty, explain each contract-resolved value in the mapping:

> "Based on your preferences, I'll filter with these criteria: [list each mapping, including any canonical value resolved by preflight]. Does this look right?"

⏸ Wait for user confirmation. If they disagree, adjust only to a table value, an observed value, or a value the preflight resolves successfully; then rerun preflight before asking for confirmation again.

## Step 3: Retrieve and Filter Candidates

Branch on the selected Hub after the user confirms the complete filter mapping.

### SageMakerPublicHub: Search

Run Search with the literal snapshot path recorded in Step 1:

```bash
python3 model-selection/scripts/search_deployable_models.py \
    SageMakerPublicHub --region <region> \
    --snapshot-file <recorded-snapshot-path> \
    <filter1> <filter2> ...
```

The adapter uses Search for candidate membership, restores each result's cached `OriginalCreationTime`, and applies the existing deterministic order. It never substitutes Search `CreationTime`, because that timestamp belongs to the indexed version and can move when a new version becomes `latestSupported`.

Inspect these output fields before presenting candidates:

- `retrieval_backend: "search"` means Search returned the candidate set.
- `retrieval_backend: "list_fallback"` means an explicit SDK, permission, service, transport, or Search-response failure caused the adapter to apply the complete confirmed filter set to the cached List catalog. The adapter performs this fallback internally from the existing snapshot. Do not call `get_deployable_models.py` or `filter_deployable_models.py` after a Search failure, and do not make another List request. Tell the user: "SageMaker Search was unavailable, so I used the existing complete Hub catalog filtering path for this selection."
- A successful Search with `matched: 0` is a real empty result and does not invoke fallback.
- Present every entry in `warnings`. In particular, if a Search result lacks cached `OriginalCreationTime`, explain that it was placed after dated models and ordered by name.

Never merge Search and List results. One invocation uses either the Search result or the complete local fallback.

### Private Hub: existing local filtering

Run the unchanged List-and-filter path:

```bash
python3 model-selection/scripts/get_deployable_models.py \
    <hub-name> <region> > /tmp/deployable_models.json

python3 model-selection/scripts/filter_deployable_models.py \
    /tmp/deployable_models.json <filter1> <filter2> ...
```

For either Hub, report:

> "Based on your constraints, I applied these filters: [list each]. This narrowed [total_models] models down to [matched] candidates."

## Step 4: Handle Results

### If results are non-empty (≤20 models)

The candidate script returns models in a fixed, deterministic order: **newest
first** (by original creation date, descending), with model name (A→Z) breaking
ties and any models lacking a creation date placed last (also A→Z). **Present
the models in exactly the order the script returned them — do NOT re-sort,
re-group, or reorder by size, name, license, or relevance.** This guarantees the
same constraints always produce the same ordered list.

Present all matching models. Cross-reference with `references/model-licenses.md` for license links where available. Display each model on its own line, preserving script order:

```
<model name> — <size_raw> | <license> | Bedrock: ✓/✗

```

For the size column use the model's `size_raw` field (the actual parameter count,
e.g. `7b`) when present — it is more informative than the normalized `size`
bucket. Fall back to `size` only if `size_raw` is absent. Omit fields that are unknown rather than showing blanks. **Display every matching model — completeness is required.**

Ask the user to select:

> "Which model would you like to deploy?"

⏸ Wait for user selection. Once the user selects a model, **proceed immediately to Step 5** (do not confirm or hand off yet).

### If results are non-empty but large (>20 models)

Show the first 20 (the 20 newest, since the script returns newest-first — preserve script order), state how many total matched, and ask:

> "There are [matched] models matching your constraints. Here are the first 20. Would you like to see more, or would you like to tighten your constraints to narrow further?"

### If results are empty

Re-run the active Hub's candidate command with one constraint removed at a time to identify which filter is most restrictive. For `SageMakerPublicHub`, reuse the same snapshot and rerun `search_deployable_models.py`; for a private Hub, rerun `filter_deployable_models.py`.

Do not treat a successful zero-result Search as an availability failure and do not switch to List merely because the result is empty. Report:

> "No models matched all your constraints. The most restrictive filter was [field]: [value], which eliminated [N] candidates. Would you like to relax this constraint?"

If the user agrees, adjust the filter and re-run from Step 3. If they want to change their use case spec, activate the `use-case-specification` skill, then re-run from Step 1.

### Snapshot cleanup

For `SageMakerPublicHub`, keep the snapshot while the user may refine filters or ask to see more. When the user selects a model, cancels selection, changes Hub or region, or the workflow ends with an unrecoverable error, delete only the exact temporary file created in Step 1:

```bash
rm -f -- "<recorded-snapshot-path>"
```

If the Hub or region changes, delete the old snapshot and create a new one before filtering. The snapshot is selection-session state, not a shared or long-lived cache.

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
