---
_fragment: iac
_of_phase: discover
_contributes:
  - azure-resource-inventory.json (resources[], iac_metadata section)
  - ai-workload-profile.json (minimal iac_cognitive profile when Azure AI infrastructure is present)
---

# Discover — Infrastructure as Code

> **Fragment unit.** One of the discover phase's independent discoverers. See
> `discover.md` for how it is composed into the phase.

## Why one fragment covers three dialects

Terraform `azurerm_*`, Bicep, and ARM JSON all land here. Bicep compiles _to_ ARM and
both key off the same `Microsoft.*` type namespace, so they share one reason to
change; all three converge on one section of one artifact; and the extraction
semantics (Azure resource type → inventory entry) are shared, with only the surface
syntax differing.

Its trigger is `{ _always: true }`, not a `_glob`. No single glob spans `.tf`,
`.bicep`, and ARM templates — ARM is plain `.json`, identifiable only by a `$schema`
containing `deploymentTemplate`. A `_when` would fail open: one misjudgment silently
drops all IaC discovery. So this fragment always runs, detects the dialects present
itself, and exits cleanly when it finds none.

## Step 1: Detect the dialects present

Record each independently — a repo may carry all three.

| Dialect     | Detection                                                                                                                                                                                                                                                                    |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `terraform` | a `**/*.tf` or `**/*.tf.json` file containing a `resource "azurerm_` block, a `resource "azapi_` block, or a `module "` block whose source resolves to Azure resources (including `.terraform/modules/` downloaded module source) — `extract-terraform.md` handles all three |
| `bicep`     | a `**/*.bicep` file                                                                                                                                                                                                                                                          |
| `arm`       | a `**/*.json` file whose top-level `$schema` contains `deploymentTemplate`                                                                                                                                                                                                   |

Exclude `.terraform/`, `**/node_modules/`, `**/.git/`, and anything under
`$MIGRATION_DIR` from all three scans.

**If no dialect is present:** write nothing, add no entry to
`metadata.discovery_sources`, and exit cleanly. This is a normal outcome — a startup
with no IaC is the common case, and the phase's other fragments cover it.

## Step 2: Load the extraction ref for each dialect present — and HALT if it is missing

For each detected dialect, load its ref and follow it:

| Dialect     | Ref                                      |
| ----------- | ---------------------------------------- |
| `terraform` | `references/shared/extract-terraform.md` |
| `bicep`     | `references/shared/extract-bicep.md`     |
| `arm`       | `references/shared/extract-arm.md`       |

> **HALT if a dialect is present and its ref is not on disk.** Emit `GATE_FAIL` naming
> the dialect and the missing file. Do **not** extract that dialect from your own
> knowledge of the syntax, and do not silently skip it.
>
> This guard exists because the two failure modes are otherwise indistinguishable, and
> they need opposite responses. "No dialect present" is a clean exit. "The dialect is
> present but this skill has not been taught to read it" is a bug, and improvising
> past it produces output that looks correct, satisfies every shape assertion in the
> phase's `_postconditions`, and is unreproducible — because it came from model priors
> rather than from `arm-type-canonicalization.md`. That output would be labelled
> `confidence: deterministic`, which would be a lie. A loud halt is the only honest
> behaviour.

Loading only the refs for dialects actually present is also the context-budget
mechanism: three dialects' rules loaded unconditionally would blow the phase's ~800-line
budget on their own, before the app-code, billing, RDfA, and live fragments are counted.

## Step 3: Canonicalize every type

Every extracted resource's type is translated to its canonical `Microsoft.*` ARM
string via `references/shared/arm-type-canonicalization.md`. Nothing downstream ever
sees an `azurerm_*` string.

**`azapi_resource` skips this step.** It carries the canonical ARM type in its own `type`
argument, so it is canonical on arrival — see `extract-terraform.md` § Step 2a. It is part
of the **terraform** dialect, not a fourth dialect: a `.tf` file containing only
`azapi_resource` blocks is still Terraform, still sets `source: "terraform"`, and must not
be reported as an unreadable dialect by the halt guard. Emit the spelling that file uses; the mapping tables
compare types with case FOLDED, so a mis-cased type still routes (see that file's
§ Casing is a convention, not a fact) — but `azure_id` strings are joined by exact
match, so one resource must always produce one string.

A type absent from that table is **derived, not skipped** — see
`arm-type-canonicalization.md` § Deriving a type that is not listed, and
`extract-terraform.md` § Step 2b. Derive the resource segment from the Terraform suffix,
supply the namespace, then **cross-check the namespace against `fast-path-services.json`
→ `namespace_routing`**:

- **Namespace recognised** → `azure_type_provenance: "derived"`.
- **Namespace NOT recognised** → `azure_type_provenance: "derived_uncorroborated"` and a
  `type_derived_uncorroborated` warning. **Still keep the resource.** Design routes it to a
  model-chosen category rather than halting.

Either way, keep the full `config` — including `sku` / `tier` / `capacity`, which Design's
cost-bearing test reads — and record the Terraform type in `iac_metadata.derived_types`.

**The cross-check is a signal, not a veto.** It records whether a second artefact agreed.
Only record a type in `iac_metadata.untranslated_types` when you genuinely cannot say what
the service is — a type you can NAME is never untranslated. What must never happen is a
_silent_ guess: every derived type is recorded with its provenance, so a reviewer can see
which were looked up and which were reasoned about.

## Step 4: Write the contribution

Append to `azure-resource-inventory.json`'s `resources[]` and write `iac_metadata`:

```jsonc
"iac_metadata": {
  "dialects_found": ["terraform"],          // detected, not merely scanned for
  "dialects_extracted": ["terraform"],      // produced ≥1 resource
  "files_scanned": 0,
  "modules_unresolved": [],                 // registry/git modules whose content is absent
  "untranslated_types": [],
  "subscription_id_source": "unresolved"    // "unresolved" when it came from a variable or the environment
}
```

`dialects_found` and `dialects_extracted` are separate because the phase's
`_postconditions` assert per dialect: if `.tf` / `.bicep` / ARM files were **found**,
`resources[]` must contain at least one entry sourced from each dialect that was
found. "The fragment ran" proves nothing — it always runs and may exit empty.

## Step 4.5: Contribute the IaC-inferred AI profile

After extraction, inspect the canonical inventory contribution. A **strong Azure AI
infrastructure signal** is any resource whose case-folded `azure_type` is:

- `Microsoft.CognitiveServices/accounts`
- `Microsoft.CognitiveServices/accounts/deployments`
- `Microsoft.MachineLearningServices/workspaces`

`Microsoft.Search/searchServices` alone is not a strong signal: a search service may be a
keyword-only index. Include it in `infrastructure[]` only when at least one strong signal is
present.

When no strong signal is present, contribute no AI profile. When one is present, contribute a
minimal `ai-workload-profile.json` payload conforming to
`references/shared/schema-discover-ai.md`:

1. Set `metadata.profile_source: "iac_cognitive"` and
   `metadata.sources_analyzed.terraform: true`; all unavailable source flags are `false`.
2. Set `summary.inferred_from_iac: true`. Use `summary.ai_source: "azure_openai"` when an
   account has `config.kind` equal to `OpenAI` (case-insensitive) OR a deployment's model
   format is `OpenAI`; otherwise use `"other"`. Never infer `openai`, `anthropic`, or `both`
   from Azure infrastructure alone.
3. Copy every strong-signal resource, plus supporting Search resources, into
   `infrastructure[]` as `{ address, type, file, role, config }`. `address` and `file` come
   from `config.tf_address` and `config.tf_file`; `type` is the original Terraform type when
   available, otherwise the canonical Azure type. `role` is `account`, `deployment`,
   `ml_workspace`, or `search`.
4. For each Cognitive Services deployment whose extracted `config.model.name` is a literal,
   add one deduplicated `models[]` row. Use the model name as `model_id`, service
   `azure_openai`, `detected_via: ["terraform"]`, evidence naming the Terraform file and
   address, and capabilities derived only from an unambiguous model family:
   `text-embedding-*` -> `embeddings`; `dall-e-*` / `gpt-image-*` -> `image_generation`;
   `whisper-*` -> `speech_to_text`; `tts-*` -> `text_to_speech`; otherwise
   `text_generation`. An expression or unknown model name produces no model row; do not turn
   a deployment name into a base model.
5. Set `integration.primary_sdk: null`, `sdk_version: null`, `frameworks: []`,
   `languages: []`, `pattern: "unknown"`, `gateway_type: null`, and a
   `capabilities_summary` derived from the model rows. IaC proves deployed infrastructure,
   not which SDK or language calls it.
6. Set `workloads: []`. A workload requires a call site and SDK method; infrastructure alone
   cannot supply either. Omit `current_costs`, `agentic_profile`, and `tool_manifest`.
7. Add one `detection_signals[]` entry per strong resource with `method: "terraform"`,
   `confidence: 0.95` for a deployment or an account whose kind is OpenAI, otherwise `0.85`,
   and evidence naming its Terraform address and file. Set
   `summary.overall_confidence` to the highest signal and derive `confidence_level`
   (`high` at >=0.90, otherwise `medium`).

The assembler is still the single writer of the final file. This fragment contributes the
payload. If the app-code fragment also contributes one, merge per
`discover-app-code.md` Step 8: code wins on conflict, union `infrastructure[]` by address,
set both source flags, and set `metadata.profile_source: "merged"`.

## Step 5: Never emit a secret

App settings and connection strings contribute **names only**. Storage account keys,
Key Vault secret values, passwords, and tokens are discarded — not redacted in place,
because a redaction placeholder still discloses that the field existed and roughly how
long it was. A Key Vault _reference_ is kept as a `secret_ref` edge, because the
reference is architecture and the secret is not.

Do not read `terraform.tfstate`, `*.tfstate.backup`, or any `*.tfstate` under any
circumstance. State carries resolved values the configuration only references.

**`.terraform/modules/` is the one readable path inside `.terraform/`** — it holds
downloaded module SOURCE, which is exactly as safe as a local module path and carries no
resolved values. Reading it is what stops a repo built on Azure Verified Modules from
producing a nearly empty inventory. See `extract-terraform.md` Step 3.

## Status - build steps 2 and 3 (partial)

**Terraform is implemented**, via `extract-terraform.md` plus
`arm-type-canonicalization.md`. It is exercised by the `azure-iac-terraform` fixture
and its asserter. The minimal `iac_cognitive` AI-profile producer is implemented for
Terraform-discovered Cognitive Services and Azure Machine Learning resources.

| Lands in | What                                                            |
| -------- | --------------------------------------------------------------- |
| step 2   | `extract-bicep.md` and `extract-arm.md`                         |
| done     | Minimal `iac_cognitive` producer for `ai-workload-profile.json` |

Until those two refs exist, a workspace containing `.bicep` or ARM templates **halts**
per Step 2 rather than partially discovering. That is deliberate: a partial inventory
presented as complete is worse than a stop, because the estimate that follows is
confidently wrong about the size of the estate.
