---
_assemble: assemble-inventory
_of_phase: discover
_reads:
  - terraform (fragment contribution)
  - live (fragment contribution)
  - billing (fragment contribution)
_produces:
  - heroku-resource-inventory.json
---

# Discover — Assemble Inventory

> **Assembler unit.** Runs after the discover fragments (`discover-terraform.md`,
> `discover-live.md`, `discover-billing.md`) have produced their contributions. It combines them into
> the single `heroku-resource-inventory.json` artifact and owns that artifact's
> final contract. See `discover.md` for how this unit is composed into the phase.

After all sub-discoveries complete, assemble `heroku-resource-inventory.json` in `$MIGRATION_DIR/`.

**Schema reference**: `shared/schema-discover-heroku.md` — consult for complete field definitions, per-type config schemas, and validation checklist.

## Assembly Rules

1. Merge all discovered resources into a flat array (no clustering, no dependency graphs).
2. Each resource entry MUST have: `resource_id`, `resource_type`, `heroku_app`, `config`.
3. Resources grouped by `heroku_app` field. Unassociable resources (spaces, pipelines) get `heroku_app: "unassociated"`.
4. Include `metadata` section: `discovery_timestamp`, `total_apps_discovered`, `discovery_sources`, `confidence`.
5. Include `apps[]` section with per-app entries containing:
   - `app_name`, `app_id`, `discovery_status` (success/discovery_failed), `failure_reason`
   - `heroku_generation` (cedar/fir/unknown), `generation_action` (always `detect_only`), `generation_diagnostics` (array of diagnostic reasons)
   - `space` (Private Space name or null)
   - `procfile_parse_warning`, `app_json_parse_warning` (per-app parse warnings or null)
6. Include `billing_profile` section (if billing data available, with `available`, `total_monthly_cost`, `currency`, `billing_period`, `line_items`).
7. Include `terraform_metadata` section only when `.tf` files with `heroku_*` resources were actually FOUND (the terraform fragment always runs but may exit empty — an empty run contributes no section and no `"terraform"` discovery source).
8. Include `live_metadata` section (if the live fragment ran, with `found`, `captured_at`, `apps_captured`, `apps_failed`, `capture_warnings`, `limitations` — and `drift` per the Merge & Drift Rules below).

## Merge & Drift Rules (when BOTH terraform and live fragments contributed)

Resource identity is `resource_id` (both fragments use the same deterministic ID
formats). Merge into ONE entry per `resource_id`. Never resolve a disagreement
silently — every conflict is recorded as drift. For `addon` resources, pairing
across sources additionally requires Rule 1a/1b because `addon_name` is sourced
differently per discovery method (see `schema-discover-heroku.md`).

1. **Same `resource_id` from both:** keep one entry. Live values win field-by-field
   in `config` (live reflects current account state; Terraform may be stale). Keep
   Terraform provenance fields (`tf_file`, `tf_resource_name`). Set
   `source: "live+terraform"`. If any config field disagreed, record it in
   `live_metadata.drift.config_conflicts[]` as
   `{ "resource_id", "field", "terraform_value", "live_value" }`.

   1a. **Add-on plan changes are conflicts, not add/remove pairs — but only
   when the pairing is unambiguous.** Add-on `resource_id`s embed the plan
   and the discriminator `addon_name`, which is sourced differently per
   discovery method (live: Heroku-assigned add-on name; Terraform: HCL `name`
   or `tf_resource_name` fallback) and will almost never match textually for
   the same real add-on. So before applying rules 2–3, pair any live-only and
   terraform-only addon entries that share the same `heroku_app` +
   `addon_service` + `plan` **only when exactly one live-sourced and one
   terraform-sourced entry share that triple** (ignoring `addon_name` for the
   match). This covers the normal case — one database, discovered twice —
   exactly as before. Treat such a pair as ONE resource with a `plan` config
   conflict (rule 1) if the plans actually differ, else a plain merge: keep
   the live entry (its `resource_id`, which carries live's `addon_name`),
   record `{ "resource_id": <live id>, "field": "plan", "terraform_value",
   "live_value" }` in `config_conflicts[]` only when the plans disagree, and
   do not count the pair in `resources_live_only` / `resources_terraform_only`.

   1b. **Ambiguous same-plan groups are reported, never guessed.** When more
   than one live-sourced **or** more than one terraform-sourced entry share
   the same `heroku_app` + `addon_service` + `plan` (the same-plan-collision
   case Rule 1a cannot disambiguate without a shared discriminator
   namespace), do **not** pair heuristically. Keep every entry separate, each
   retaining its own source's `resource_id` (now unique per `addon_name` —
   see `schema-discover-heroku.md`). Mark every live-sourced entry in the
   group `unmanaged_by_terraform: true` and every terraform-sourced entry
   `not_found_live: true` (even though a real pairing may exist), and add one
   entry per ambiguous group to
   `live_metadata.drift.ambiguous_addon_groups[]`:
   `{ "heroku_app", "addon_service", "plan", "live_resource_ids": [...], "terraform_resource_ids": [...] }`.
   This honestly reports an unresolvable identity gap rather than silently
   collapsing the group into one entry.
2. **Live only:** keep the entry (`source: "live"`) and set
   `unmanaged_by_terraform: true` — this is click-ops drift the migration plan must
   include.
3. **Terraform only:** keep the entry (`source: "terraform"`) and set
   `not_found_live: true` — defined but not deployed (or not in the selected app
   set). Detect-only: downstream phases decide how to treat it.
4. **Formation gap-fill:** process types that live discovery cannot see (scaled to
   zero, i.e. Terraform `quantity: 0`) but Terraform/Procfile declares are kept from
   the Terraform contribution — this is the expected complement, not a conflict. Do
   NOT set `not_found_live` on them and do NOT count them in
   `resources_terraform_only`.
5. **Apps section:** live `apps[]` entries win (they carry the real `app_id` UUID);
   merge in Terraform-only apps with `not_found_live: true`.
6. **Drift summary:** set `live_metadata.drift` to
   `{ "resources_live_only": N, "resources_terraform_only": M, "config_conflicts": [...] }`,
   plus `"ambiguous_addon_groups": [...]` (per Rule 1b) whenever any group was
   ambiguous; omit that key when no ambiguous group was found.

When only ONE of the two fragments contributed, no merge occurs and no `drift` key
is written.

**If assembly fails** (no valid resources from any source after sub-discoveries ran):
this is an unrecoverable error (`INTERPRETER.md` § `_on_error` — `_unrecoverable`).
STOP and output: "Discovery ran but produced no valid resources. Check that your
input files contain valid Heroku resources and try again."

(The phase's `_postconditions` separately enforce that no forbidden clustering
fields — `cluster_id`, `creation_order_depth`, `edges`, `dependencies`,
`must_migrate_together` — appear in the assembled artifact.)
