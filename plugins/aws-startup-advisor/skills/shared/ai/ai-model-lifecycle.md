# Bedrock Model Lifecycle Awareness

> Canonical Bedrock model Active/Legacy/EOL registry and the 90-day exclusion
> rule. Source-cloud agnostic: it is a property of Bedrock's model catalog.
> Vendored into each consuming skill as
> `references/vendored/ai/ai-model-lifecycle.md` and kept byte-identical by
> `shared:check`; edit HERE, then run `shared:sync`.

References:

- [Models launched on or after 2026-09-07](https://docs.aws.amazon.com/bedrock/latest/userguide/model-lifecycle.html)
- [Models launched before 2026-09-07](https://docs.aws.amazon.com/bedrock/latest/userguide/model-lifecycle-legacy.html)

Models on Bedrock move through three states: **Active** → **Legacy** → **End-of-Life (EOL)**. After EOL, the model is unavailable and requests fail.

The notice period a model gets depends on when it launched:

- Models launched **before 2026-09-07** follow the original policy: at least **6 months** in Legacy before EOL. For EOL dates after February 1, 2026, a **public extended access** period begins at least 3 months into the Legacy state, and pricing may increase at the model provider's discretion.
- Models launched **on or after 2026-09-07** are governed by their model card. Each card declares an `EOL no sooner than` date and a Legacy period that is either 6 months or **45 days**. The actual EOL date appears on the card once Legacy begins.

**Do not apply the 6-month assumption to a model launched on or after 2026-09-07** — a 45-day Legacy period leaves less time than a typical migration takes to reach production.

---

## Lifecycle States (Not the Same Thing)

| State      | What it means                                                                                                                                                                                                               | Usable?                |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| **Active** | Provider is actively maintaining the model. Full feature access.                                                                                                                                                            | Yes                    |
| **Legacy** | Deprecated. Still works for existing users, but new Provisioned Throughput cannot be created, new customers cannot onboard, pricing may increase during public extended access, and the model is on a countdown to removal. | Yes, with restrictions |
| **EOL**    | Model is removed. All inference requests fail.                                                                                                                                                                              | **No**                 |

**Legacy does not mean unavailable** — it means the model still functions today but has a firm expiration date. EOL means unavailable.

---

## Selection Rules

### Rule 1: Active models only for new migrations

**New migrations must target Active models only.** Do not recommend a Legacy or EOL model as the primary selection for any new migration, even if it is cheaper.

### Rule 2: 90-day exclusion zone

**Models within 90 days of their EOL date must be excluded from all recommendation and comparison tables.** A migration takes weeks or months to plan, test, and deploy. Recommending a model that will be unavailable before the migration is production-ready is harmful.

- **Excluded** = do not list in "Best Bedrock Match" columns, tiered strategy tables, or `recommended_model` / `backup_model` fields.
- These models may still appear in the pricing cache (for reference by users already on them) but must be marked `excluded (EOL YYYY-MM-DD)` in the Status column.

### Rule 3: Legacy models outside the 90-day zone

Legacy models with >90 days until EOL may appear in comparison tables **with annotation** (`Legacy — EOL YYYY-MM-DD`), but never as `recommended_model` or "Best Bedrock Match" when an Active alternative exists.

### Applying the rules

On each run, compute `days_to_eol = EOL date − today` for every model in the Legacy/EOL table below. Then:

1. `days_to_eol ≤ 0` → EOL. Remove from all tables.
2. `0 < days_to_eol ≤ 90` → **Exclusion zone.** Remove from recommendation/comparison tables. Mark `excluded` in pricing cache.
3. `days_to_eol > 90` and Legacy → Annotate, never recommend as primary.
4. Active → No restrictions.

---

## Legacy / EOL Models (as of September 21, 2026)

For models launched before 2026-09-07, the [legacy lifecycle table](https://docs.aws.amazon.com/bedrock/latest/userguide/model-lifecycle-legacy.html) is authoritative. For models launched on or after that date, the model card and the runtime `modelLifecycle.status` field are authoritative — they will not appear in the table below. The table captures pre-policy-change models referenced elsewhere in this plugin. **Recompute the Status column on each run** using `days_to_eol = EOL date − today`.

| Model              | Model ID                                  | EOL Date   | Days to EOL | Status       | Active Replacement      |
| ------------------ | ----------------------------------------- | ---------- | ----------- | ------------ | ----------------------- |
| Nova Canvas v1     | `amazon.nova-canvas-v1:0`                 | 2026-09-30 | 9           | **excluded** | Stability AI (see note) |
| Nova Reel v1       | `amazon.nova-reel-v1:0` / `v1:1`          | 2026-09-30 | 9           | **excluded** | —                       |
| Claude Sonnet 4    | `anthropic.claude-sonnet-4-20250514-v1:0` | 2026-10-14 | 23          | **excluded** | Claude Sonnet 5 / 4.6   |
| Jamba 1.5 Large    | `ai21.jamba-1-5-large-v1:0`               | 2026-11-26 | 66          | **excluded** | —                       |
| Jamba 1.5 Mini     | `ai21.jamba-1-5-mini-v1:0`                | 2026-11-26 | 66          | **excluded** | —                       |
| Marengo Embed v2.7 | `twelvelabs.marengo-embed-2-7-v1:0`       | 2026-11-30 | 70          | **excluded** | Marengo Embed 3.0       |
| Claude Opus 4.1    | `anthropic.claude-opus-4-1-20250805-v1:0` | 2027-01-08 | 109         | legacy       | Claude Opus 4.8 / 4.6   |

**Notes (as of Sep 21, 2026):** Jamba 1.5 Large / Mini and Marengo Embed v2.7 are inside the 90-day exclusion zone (`excluded`, not `legacy`) — they must no longer appear in recommendation or comparison tables. Jamba 1.5 Large / Mini are also in public extended access, so provider pricing may increase. Claude Opus 4.1 is the only row still outside the exclusion zone.

**Removed (past EOL as of Sep 21, 2026):**

- Titan Image Generator v2 (`amazon.titan-image-generator-v2:0`) — EOL 2026-06-30
- Llama 3.2 all sizes (`meta.llama3-2-*-instruct-v1:0`) — EOL 2026-07-07
- Llama 3.1 405B Instruct (`meta.llama3-1-405b-instruct-v1:0`) — EOL 2026-07-07
- Claude 3 Sonnet (`anthropic.claude-3-sonnet-20240229-v1:0`) — EOL 2026-07-30
- Claude 3.5 Sonnet v1 (`anthropic.claude-3-5-sonnet-20240620-v1:0`) — EOL 2026-07-30
- Claude 3.5 Sonnet v2 (`anthropic.claude-3-5-sonnet-20241022-v2:0`) — EOL 2026-07-30
- Command R / R+ (`cohere.command-r-v1:0` / `cohere.command-r-plus-v1:0`) — EOL 2026-08-19
- Claude 3 Haiku (`anthropic.claude-3-haiku-20240307-v1:0`) — EOL 2026-09-10 (replacement: Claude Haiku 4.5)
- Nova Premier v1 (`amazon.nova-premier-v1:0`) — EOL 2026-09-14 (replacement: Nova 2 Pro)
- Nova Sonic v1 (`amazon.nova-sonic-v1:0`) — EOL 2026-09-14 (replacement: Nova 2 Sonic)

> **AWS page lag:** As of Sep 21, 2026, the legacy lifecycle page still lists rows whose published EOL date has already passed (Command R / R+ among them), even though the same page states that past-EOL rows are dropped. This file treats the **EOL date as authoritative** and keeps those models in Removed rather than the live table, so users already on them still see a warning. Never recommend or invoke a model listed in Removed.

**Status key:** `excluded` = ≤90 days to EOL, must not appear in any recommendation. `legacy` = >90 days to EOL, annotate but do not recommend as primary.

**⚠️ Image generation — Active successor is Stability AI:** Nova Canvas v1 is Legacy and now inside the exclusion zone (EOL 2026-09-30), so it must not appear in recommendation or comparison tables. The Active image generation models on Bedrock are **Stability AI** models:

| Model                      | Model ID                            | Pricing       | Tier     | Use case                              |
| -------------------------- | ----------------------------------- | ------------- | -------- | ------------------------------------- |
| Stable Image Ultra         | `stability.stable-image-ultra-v1:0` | ~$0.08/image  | premium  | Photorealistic, high-end visuals      |
| Stable Diffusion 3.5 Large | `stability.sd3-5-large-v1:0`        | ~$0.065/image | flagship | High volume creative assets           |
| Stable Image Core          | `stability.stable-image-core-v1:0`  | ~$0.04/image  | fast     | Rapid, affordable generation at scale |

When `image_generation` capability is detected:

1. Recommend **Stability AI** models as the primary Active target (not Nova Canvas).
2. Note the pricing model difference: Stability AI charges **per image**, not per token. Direct cost comparison with source provider (DALL-E, Imagen) requires converting to per-image equivalents.
3. If the user's source workload is DALL-E or Imagen, map to Stable Image Ultra (quality-first) or Stable Image Core (cost-first) based on `quality_vs_cost` preference in `preferences.json`.
4. Nova Canvas is inside the exclusion zone and must not appear at all — not as `recommended_model`, and not as a Legacy fallback annotation.

---

## Integration Points

### Design Phase (`design-ai.md`)

After selecting a Bedrock model for each workload:

1. Check the Legacy/EOL table above (or the lifecycle page).
2. If the model is in the **exclusion zone** (≤90 days to EOL) or EOL: reject it. Use the Active replacement.
3. If the model is Legacy but >90 days from EOL: replace with Active replacement if one exists. If no Active replacement exists, note the EOL date and recommend the user plan a follow-up migration.
4. If Active: proceed normally.
5. If `restricted` (Covered Model or gated preview — see the Status table below): do not select it as a default or as `recommended_model` / `backup_model`; name it only when the user explicitly asks for a frontier model, together with its access requirement.

### Estimate Phase (`estimate-ai.md`)

When building the model comparison table:

- **Exclusion zone models**: omit entirely from `model_comparison`. Do not include in `recommended_model` or `backup_model`.
- **Legacy (>90 days)**: include with `(Legacy — EOL YYYY-MM-DD)` annotation. Never use as `recommended_model` if an Active alternative exists.
- **Active**: no restrictions.
- **Restricted** (`restricted (…)` in the pricing-cache Status column): never `recommended_model` or `backup_model`, never a default in a mapping guide. Include in `model_comparison` only when the user explicitly asks about frontier / Covered Models, annotated with the access requirement.

### Pricing Cache (`pricing-cache.md`)

The multi-provider quick reference table includes a `Status` column:

| Status value                | Meaning                                                                                                                                                                                                                                                                                                                                     |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `active`                    | No restrictions                                                                                                                                                                                                                                                                                                                             |
| `legacy (EOL YYYY-MM-DD)`   | Legacy, >90 days from EOL. Listed for reference, annotated.                                                                                                                                                                                                                                                                                 |
| `excluded (EOL YYYY-MM-DD)` | ≤90 days from EOL. Kept for existing users but must not be selected for new migrations.                                                                                                                                                                                                                                                     |
| `restricted (<reason>)`     | Access-restricted: a Covered Model that needs an account-level data-retention opt-in (`aws_review` or `provider_data_share`), or a gated preview. Never `recommended_model` / `backup_model`, never a default; offer only on explicit user request, with the requirement stated. Claude Fable 5 / 5.1 and the Mythos line carry this value. |

When refreshing the cache, recompute `days_to_eol` and refresh the `active` / `legacy` / `excluded` values from the [model lifecycle page](https://docs.aws.amazon.com/bedrock/latest/userguide/model-lifecycle.html). **Preserve an existing `restricted (…)` value** — that page publishes only active / legacy / EOL and does not track access gating, so it can never produce `restricted`; change or remove a `restricted` value only when the model card's access requirement itself changed (data-retention mode, gated preview status).

### Mapping Guides (`ai-openai-to-bedrock.md`, `ai-anthropic-to-bedrock.md`, `ai-gemini-to-bedrock.md`, and any source-cloud-specific guide the consuming skill ships)

- "Best Bedrock Match" columns must only contain Active models.
- Exclusion-zone models must not appear in any recommendation row.
- `restricted` models never appear as a default match; they may be named only as an explicit opt-in alternative with the access requirement stated.
- Legacy models (>90 days) may appear in notes or legacy-source mapping rows but never as the primary recommendation.

---

## Refresh Cadence

**On every design run:** The agent MUST recompute `days_to_eol = EOL date − today` for every row in the table above and apply the four rules in "Applying the rules" before making any model recommendation. The static Days to EOL column in this file is a snapshot only — do not use it directly without recomputing.

**Newer models are not covered by the table.** A model launched on or after 2026-09-07 will never appear in the Legacy/EOL table above, and its absence is not evidence that it is Active. When a candidate is not in the table, verify it by calling `GetFoundationModel` (or `ListFoundationModels`) and reading `modelLifecycle.status`: `LEGACY` and `EOL` are never valid targets for a new migration. If the model is Legacy, read its model card for the actual EOL date and whether the Legacy period is 6 months or 45 days. If neither the API nor the card is reachable, treat the model's lifecycle as **unverified** and say so in the output rather than inferring `active` from a `Status` column in a pricing cache.

**Periodic table refresh:** When the table itself needs updating (new models added, EOL dates changed by AWS, or past-EOL rows to remove), update this file and `pricing-cache.md` together. Edit the canonical `skills/shared/ai/ai-model-lifecycle.md`, then copy it over every vendored copy in the same change so they stay byte-identical.

**Past-EOL rows:** Once `days_to_eol ≤ 0`, move the model out of the live table into **Removed**, and grep this plugin's skill trees for the model ID to catch any remaining reference to it as a target. Keep the Removed entry long enough that users already on the model still get a warning.
