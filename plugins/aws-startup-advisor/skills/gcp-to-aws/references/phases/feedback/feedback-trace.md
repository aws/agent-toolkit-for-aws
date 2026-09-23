# Feedback Trace Builder

Builds an anonymized telemetry trace from migration artifacts in `$MIGRATION_DIR/`. The trace never includes resource names, file paths, account IDs, IPs, variable values, or secrets.

**Execute ALL steps in order. Do not skip or deviate.**

## Step 1: Initialize Trace Object

Create an empty `trace` object with `migration_id` from `.phase-status.json`.

## Step 2: Extract Phase Metadata

Read `$MIGRATION_DIR/.phase-status.json` and add to `trace`:

```json
{
  "migration_id": "<from .phase-status.json>",
  "phases_completed": ["<list of phases with value 'completed'>"]
}
```

Only include phases with value `"completed"`.

## Step 3: Extract Discovery Summary

IF `$MIGRATION_DIR/gcp-resource-inventory.json` exists, add:

```json
{
  "discovery": {
    "total_resources": "<summary.total_resources>",
    "primary_resources": "<summary.primary_resources>",
    "secondary_resources": "<summary.secondary_resources>",
    "resource_type_counts": { "<type>": "<count>" },
    "has_ai_workload": "<ai_detection.has_ai_workload>"
  }
}
```

For `resource_type_counts`: group `resources[]` by `type` and count each. Do NOT include resource names or addresses.

## Step 4: Extract Cluster Count

IF `$MIGRATION_DIR/gcp-resource-clusters.json` exists, add:

```json
{ "cluster_count": "<clusters array length>" }
```

## Step 5: Extract AI Profile Summary

IF `$MIGRATION_DIR/ai-workload-profile.json` exists, add:

```json
{
  "ai_profile": {
    "ai_source": "<summary.ai_source>",
    "total_models_detected": "<summary.total_models_detected>",
    "languages_found": "<summary.languages_found>",
    "integration_pattern": "<integration.pattern>",
    "gateway_type": "<integration.gateway_type>",
    "capabilities_summary": "<integration.capabilities_summary>"
  }
}
```

## Step 6: Extract Billing Summary

IF `$MIGRATION_DIR/billing-profile.json` exists, add:

```json
{
  "billing": {
    "total_monthly_spend": "<summary.total_monthly_spend>",
    "service_count": "<summary.service_count>"
  }
}
```

## Step 7: Extract Preferences Metadata

IF `$MIGRATION_DIR/preferences.json` exists, add:

```json
{
  "preferences": {
    "questions_asked_count": "<metadata.questions_asked array length>",
    "questions_defaulted_count": "<metadata.questions_defaulted array length>",
    "questions_skipped_count": "<sum of questions_skipped_extracted + questions_skipped_early_exit + questions_skipped_not_applicable lengths>",
    "category_e_enabled": "<metadata.category_e_enabled>",
    "constraint_values": "<enum values only from design_constraints — e.g., region string, compliance array, availability string>"
  }
}
```

Include only the `value` field from each constraint. Do NOT include `chosen_by` or any free-text fields.

## Step 8: Extract Design Summary

IF `$MIGRATION_DIR/aws-design.json` exists, add each resource mapping as:

```json
{
  "design_mappings": [
    { "gcp_type": "<gcp_type>", "aws_service": "<aws_service>", "confidence": "<confidence>" }
  ],
  "unmapped_count": "<count of resources with no aws_service>"
}
```

IF `$MIGRATION_DIR/aws-design-ai.json` exists, add:

```json
{
  "design_ai": {
    "honest_assessment": "<ai_architecture.honest_assessment>",
    "bedrock_model_count": "<metadata.bedrock_models_selected>"
  }
}
```

## Step 9: Extract Estimation Summary

For each `estimation-*.json` file that exists in `$MIGRATION_DIR/`, add:

```json
{
  "estimation_<type>": {
    "pricing_source": "<pricing_source.status or pricing_mode>",
    "accuracy_confidence": "<accuracy_confidence>",
    "monthly_cost": "<projected optimized or mid monthly cost>"
  }
}
```

Where `<type>` is `infra`, `ai`, or `billing` based on the filename.

## Step 10: Extract Generation Summary

For each `generation-*.json` file that exists in `$MIGRATION_DIR/`, add:

```json
{
  "generation_<type>": {
    "generation_source": "<generation_source>",
    "total_weeks": "<migration_plan.total_weeks when present (legacy artifacts), else null — field retained for trace-contract stability; owner note: replace with duration-driver signal in a future trace rev>",
    "risk_count": "<risks array length>"
  }
}
```

## Step 11: Count Generated Artifacts

Count files in generated artifact directories (if they exist):

```json
{
  "artifacts": {
    "terraform_file_count": "<count of files in $MIGRATION_DIR/terraform/>",
    "scripts_file_count": "<count of files in $MIGRATION_DIR/scripts/>",
    "ai_migration_file_count": "<count of files in $MIGRATION_DIR/ai-migration/>"
  }
}
```

Only include keys for directories that exist. Use 0 if directory exists but is empty.

## Step 12: Write Trace

Write the assembled `trace` object to `$MIGRATION_DIR/trace.json`.

Output: "Trace built. Extracted anonymized data from N artifacts."
