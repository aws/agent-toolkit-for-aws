---
_fragment: collect
_of_phase: feedback
_contributes:
  - trace.json (anonymized migration trace)
  - feedback.json (survey URL, share-link state, trace_included flag)
---

# Feedback Phase: Collect

> Self-contained feedback-collection sub-file. Detects the IDE + plugin version,
> builds an anonymized trace, presents the survey link, and writes
> `feedback.json`. (Share-link generation is spec'd in Step 3 but GATED OFF until
> the landing page ships.) The final output gate + phase completion are owned by
> the assembler (`feedback-assemble.md`).

**Execute ALL steps in order. Do not skip or deviate.**

---

## Step 0: Detect IDE Type and Plugin Version

Detect IDE and plugin version for the survey URL (hidden fields — user never sees them).

- **Claude Code**: `CLAUDE_CODE` env var set → `ide = claude-code`
- **Cursor**: `CURSOR_TRACE_ID` env var set → `ide = cursor`
- **Kiro**: Kiro agent context → `ide = kiro`
- **Fallback**: `ide = unknown`

Read plugin version from nearest `plugin.json` → `version`. Fallback: `0.0.0`.
Sanitize both values to Pulse-safe chars: `[a-zA-Z0-9._~-]`.

Store as `$IDE_TYPE` and `$PLUGIN_VERSION`.

---

## Step 1: Build Trace

Build an anonymized trace from `$MIGRATION_DIR/` artifacts. Never include resource names, file paths, account IDs, or secrets.

```json
{
  "migration_id": "<from .phase-status.json>",
  "skill": "heroku-to-aws",
  "phases_completed": ["<completed phases>"],
  "discovery": {
    "total_apps": "<metadata.total_apps_discovered>",
    "total_resources": "<resources array length>",
    "resource_type_counts": { "<type>": "<count>" },
    "discovery_sources": "<metadata.discovery_sources>",
    "confidence": "<metadata.confidence>"
  },
  "preferences": {
    "questions_asked_count": "<user-sourced count>",
    "questions_defaulted_count": "<default-sourced count>"
  },
  "design": {
    "total_services": "<metadata.total_services>",
    "deferred_count": "<deferred array length>",
    "warnings_count": "<warnings array length>"
  },
  "estimation": {
    "pricing_source": "<pricing_source>",
    "projected_monthly": "<total projected cost>"
  },
  "artifacts": {
    "terraform_file_count": "<file count in terraform/>"
  }
}
```

Only include sections for artifacts that exist. Write to `$MIGRATION_DIR/trace.json`.
If trace building fails: set `trace_included = false`, skip to Step 3.

---

## Step 2: Show Trace and Provide Survey Link

Display pretty-printed `trace.json`, then single-line minified version for copy-paste, then:

```
Open the feedback form in your browser:
https://pulse.amazon/survey/MY0ZY7UA?ide=$IDE_TYPE&version=$PLUGIN_VERSION

Answer the 5 quick questions, then paste the trace into the
"Migration trace (optional)" field and submit.
```

---

## Step 3: Generate Share Link (GATED OFF — do not run)

> **This step is disabled until the share landing page ships.**
> `https://aws.amazon.com/startups/migrate/connect` currently returns 404, so a
> generated link would dead-end for the user. Skip directly to Step 4 and leave
> `share_link_presented: false` in `feedback.json`. The spec below is preserved
> so the feature can be re-enabled by removing this gate (here and in SKILL.md
> § Feedback & Sharing Sidebars) once the page is live and verified.

Required artifacts: `preferences.json`, `estimation-infra.json`. If missing, output "Cannot generate share link — required artifacts not found." and skip to Step 4.

### Payload

```json
{
  "schema_version": "1.0",
  "plugin_version": "<$PLUGIN_VERSION>",
  "generated_at": "<ISO 8601 UTC>",
  "skill": "heroku-to-aws",
  "clarify_answers": { "<question_id>": "<answer_value>" },
  "cost_summary": {
    "current_heroku_monthly": "<billing_profile total or null>",
    "projected_aws_monthly": "<from estimation-infra.json>",
    "delta": "<projected - current or null>",
    "currency": "USD"
  },
  "detected_services": ["<addon_service values from inventory>"],
  "resource_names": [{ "type": "<resource_type>", "name": "<heroku_app>" }],
  "workload_types": ["infra"],
  "spend_band": "<under-10k|10k-50k|50k-100k|over-100k|unknown>",
  "share_sidebar": "<after_estimate|after_generate>",
  "phases_completed": ["<completed phases>"]
}
```

**Secret redaction**: Scan `clarify_answers` for AWS key IDs (`AKIA...`), private key headers, passwords in connection strings, high-entropy tokens. Replace with `"[REDACTED]"`.

**Encode**: Minify JSON → gzip → Base64URL. If > 8,192 chars, truncate `resource_names`, then longest `clarify_answers`, then cap `detected_services` at 20. If still too large, skip.

**URL**: `https://aws.amazon.com/startups/migrate/connect#<base64url_payload>`

Share link generation is **non-blocking** — failures never halt the phase.

---

## Step 4: Write feedback.json

Write `$MIGRATION_DIR/feedback.json`:

```json
{
  "timestamp": "<ISO 8601>",
  "skill": "heroku-to-aws",
  "survey_url": "https://pulse.amazon/survey/MY0ZY7UA?ide=$IDE_TYPE&version=$PLUGIN_VERSION",
  "phases_completed_at_feedback": ["<completed phases>"],
  "trace_included": true,
  "share_link_presented": false,
  "share_link_generated_at": null,
  "share_sidebar": null
}
```

- If trace failed: `"trace_included": false`
- If share link generated: `"share_link_presented": true`, populate `share_link_generated_at` and `share_sidebar`

When `feedback.json` (and `trace.json`, if `trace_included`) are written, control passes to
the assembler (`feedback-assemble.md`) for the output gate and phase completion.
