# Retain selected cost inputs during Estimate

The optional version-2 plan export uses retained Estimate evidence. Version 1 remains the default until compatible import readers are verified. Missing retained inputs must not fail Estimate or change its selected prices.

## Before pricing

You MUST run the existing `emit-plan-json.py` with `--migration-dir "$MIGRATION_DIR" --capture-inputs <estimate-file>` before calculating this route. Locate the emitter in the plugin's scripts directory; a standalone Heroku installation uses the emitter bundled in that skill's scripts directory. Use `uv run --no-project` to execute it. `<estimate-file>` is exactly `estimation-infra.json`, `estimation-billing.json` or `estimation-ai.json`.

The command prints a JSON snapshot of the current run ID, owning skill and input digests. Retain the exact returned object for the route's output. If it prints `INPUT_SNAPSHOT_SKIP`, leave `export_inputs` absent and continue the existing estimate; do not make up a snapshot or recapture old inputs after pricing.

The snapshot covers the route's design and preferences, plus present inventory/billing/AI usage profiles. Digests use parsed JSON with sorted keys, compact separators and ASCII escapes. Preferences exclude only `workshop.active`, `workshop.active_scenario_id` and `workshop.last_sheet_at`; these change during scenario bookkeeping. Other workshop fields, including CPU architecture, remain covered. Changes to price-relevant inputs require repricing with a fresh snapshot.

## While pricing each selected row

You MUST retain the row's configuration, usage quantities/units, pricing region and upfront evidence as you price it. Keep the same granularity as the selected cost breakdown. Do not add component costs again, choose a recommended/optimized tier instead of Balanced, infer resource joins by service name, or fill missing charges with zero.

Write an optional top-level `export_inputs` object in the route's estimate:

```text
export_inputs:
  snapshot: <exact pre-pricing snapshot object>
  rows:
    <JSON Pointer to the selected amount>:
      monthlyCost: <same selected numeric amount>
      estimateInput:
        regionCode: <recorded pricing region, when known>
        upfrontCost: <explicit plain nonnegative decimal string, when known>
        pricingBasis: <retained explanation of that upfront amount, when known>
        configurationSummary: <configuration and usage used for this amount, when known>
        description: <optional existing resource rationale>
        source:
          resourceIds: <optional ordered list of explicitly priced resource IDs>
      resourceIdPointers: <JSON Pointers to those ID fields in this route's design>
      configurationPointers: <JSON Pointers to their configuration objects>
```

These are local retention fields. Only the typed `estimateInput` is added to a version-2 exported service row. Unknown context fields are omitted. `null` is not an absent value. Heroku's cost-engine fragment MUST pass `export_inputs` to its assembler unchanged.

Use the actual amount pointer: infrastructure uses the first present `monthly`, `mid` or `right_sized_monthly` field of a selected breakdown entry, or the entry itself for a bare number. Billing uses the original `/aws_projection/services/<index>/aws_mid` index before filtering. AI uses `/cost_comparison/projected_bedrock_monthly` and retains all models/usage contributing to that aggregate, not only the recommended model. Escape `~` as `~0` and `/` as `~1` in pointer keys.

When a row records `source.resourceIds`, provide matching `resourceIdPointers` and `configurationPointers` in the same order. Each pair must select the ID field and nonempty configuration object of the same design resource. For example, `/services/0/source_resource_id` and `/services/0/aws_config` bind a resource without matching its display name. Include every resource whose usage contributes to an aggregate. Controls or AI aggregates without concrete resource IDs may omit all three lists; retain their actual aggregate configuration/usage instead. Never manufacture an ID or a configuration object to satisfy validation.

For a row actually priced on GCP's Balanced on-demand baseline, retain the explicit `"0"` upfront amount with that assumption. The Balanced label alone is insufficient. Billing ratios, unknown usage/configuration, and absent upfront amounts stay unknown. A target preference does not establish the rate region when the price came from another region.

The emitter verifies the recorded amount against the selected row, validates resource/configuration pointers, and checks the pre-pricing input snapshot. It supplies `source.estimateFile` and `source.costPointer` from that verified local row. If either was explicitly retained already, it must match. A stale snapshot or malformed context is omitted from the export; the assessment remains usable without a CSV.

## Selected workshop scenario

When workshop selection exists, you MUST preserve matching selected snapshots for preferences, every contributing design and every contributing estimate. The active `scenarios/index.json.active_scenario_id` and `preferences.workshop.active_scenario_id` must agree. Copy the complete estimate, including `export_inputs`, into the scenario snapshot. Do not modify retained evidence to disguise an older estimate as the current scenario.

The emitter compares the selected snapshots with the working files, checks any recorded `workshop.scenario_id`, and copies the proven selected scenario ID into `estimateInput.source.scenarioId`. An absent/conflicting snapshot leaves that route's context unavailable. An AI track in a mixed workshop run needs its own matching design and estimate snapshots.

## Export

Keep existing automatic export commands unchanged. After compatible readers have been verified, an explicitly requested local v2 export uses:

```text
uv run --no-project <path-to-emit-plan-json.py> --migration-dir <run-directory> --schema-version 2
```

V2 preserves the selected scope, row order, `awsMonthlyBasis` and numeric monthly fields. FULL sums the selected base and AI amounts with decimal arithmetic; an exact sum that cannot round-trip through the numeric wire type falls back to the valid v1 summary. An oversized v2 file also falls back to v1. Read the produced `schemaVersion`; requesting v2 does not guarantee a v2 file or CSV eligibility.

R2 text limits are UTF-16 code units: region 64, pricing basis 1024, configuration summary 4096, optional description 1024, source pointer 1024, scenario ID 128, and up to 100 resource IDs of 256 units each. Upfront is a plain decimal string of at most 128 characters, between zero and 100,000,000 inclusive. Keep the complete file within 512 KiB and the selected breakdown within 100 rows. Missing context or inconsistent totals leave CSV unavailable; do not repair prices to make the file eligible.
