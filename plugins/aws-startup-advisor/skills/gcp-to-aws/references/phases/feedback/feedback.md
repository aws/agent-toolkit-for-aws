# Phase 6: Feedback (Optional)

Builds an anonymized usage trace and directs the user to the Pulse survey form.

**Execute ALL steps in order. Do not skip or deviate.**

## Prerequisites

Read `$MIGRATION_DIR/.phase-status.json`. Verify `phases.discover == "completed"`. If not: **STOP**. Output: "Feedback requires at least the Discover phase to be completed."

## Step 0: Detect IDE Type and Plugin Version

Detect the IDE type and plugin version for the survey URL. These are passed as hidden fields — the user never sees or enters them.

### IDE Detection

Determine which IDE is running:

- **Claude Code**: Check if the environment indicates Claude Code (e.g., the `CLAUDE_CODE` environment variable is set, or the skill was invoked via `/skill` or Claude Code CLI). Set `ide` to `claude-code`.
- **Cursor**: Check if the environment indicates Cursor (e.g., the `CURSOR_TRACE_ID` environment variable is set, or the editor context is Cursor). Set `ide` to `cursor`.
- **Fallback**: If detection fails, set `ide` to `unknown`.

### Plugin Version Detection

Read the plugin version from the plugin manifest:

- **Claude Code**: Read `.claude-plugin/plugin.json` → `version` field (relative to the plugin install root).
- **Cursor**: Read `.cursor-plugin/plugin.json` → `version` field (relative to the plugin install root).
- **Fallback**: If the manifest cannot be read, set `version` to `0.0.0`.

### Sanitization

Values must use only Pulse-safe characters: letters, numbers, dots (`.`), tildes (`~`), hyphens (`-`), and underscores (`_`). Strip or replace any other characters.

Store the detected values as `$IDE_TYPE` and `$PLUGIN_VERSION` for use in Step 2.

## Step 1: Build Trace

Load `references/phases/feedback/feedback-trace.md` and execute it. This produces `$MIGRATION_DIR/trace.json`.

If trace building fails: log the error, set `trace_included` to `false`, and skip to Step 3.

## Step 2: Show Trace and Provide Instructions

Read `$MIGRATION_DIR/trace.json` and display it pretty-printed so the user can see exactly what data is included:

```
--- Anonymized Trace (what will be shared) ---

<pretty-printed trace.json>

--- End Trace ---

This trace contains only aggregate counts, enum values, and timing data.
No resource names, file paths, account IDs, or secrets are included.
```

Then output the single-line minified version for copy-paste:

```
--- Copy the line below and paste it into the "Migration trace (optional)" field ---

<trace.json as single-line minified JSON — no newlines, no extra whitespace>

--- End ---
```

### Step 2.5: Decision check (chat only — optional, before the survey link)

Ask three quick questions in chat. All are skippable — any non-answer means skip; skipping never blocks the phase. **Do NOT write the answers to `trace.json` or `feedback.json`** — the trace contract is unchanged; these exist so the conversation itself can close the loop on the plugin's core purpose:

```
Before the survey link — three quick questions (all optional):

1. Could you make your migrate/stay decision from this assessment? (yes / partly / no)
2. If you decided: which way are you leaning? (migrate / stay / defer)
3. If you couldn't decide: what evidence was missing?
4. If you've completed a cloud migration before: how long did it actually take,
   start to cutover? (helps us calibrate — the plugin deliberately avoids
   quoting week/hour estimates because it has no real-world duration data yet)
```

Respond briefly to whatever they share (e.g. point at the relevant artifact or the what-if workshop for missing-evidence answers), then continue to the survey link below.

Then provide the survey link with IDE and version as hidden field query parameters:

```
Open the feedback form in your browser:
https://pulse.amazon/survey/MY0ZY7UA?ide=$IDE_TYPE&version=$PLUGIN_VERSION

Answer the 5 quick questions in the form, then paste the trace line above
into the "Migration trace (optional)" field and submit.
```

Replace `$IDE_TYPE` and `$PLUGIN_VERSION` with the actual values detected in Step 0. Example: `https://pulse.amazon/survey/MY0ZY7UA?ide=claude-code&version=1.0.0`

## Step 3: Write feedback.json

Write `$MIGRATION_DIR/feedback.json`:

```json
{
  "timestamp": "<ISO 8601>",
  "survey_url": "https://pulse.amazon/survey/MY0ZY7UA?ide=$IDE_TYPE&version=$PLUGIN_VERSION",
  "phases_completed_at_feedback": ["<list of completed phases>"],
  "trace_included": true
}
```

If trace building failed: set `"trace_included": false`.

## Step 4: Update Phase Status

Before status update, enforce output gate:

- `feedback.json` must exist.
- If `trace_included` is true, `trace.json` must exist.

If output gate fails: STOP and output: "Feedback outputs are incomplete. Fix feedback artifacts before completion."

Use the Phase Status Update Protocol (read-merge-write) to update `.phase-status.json` with `phases.feedback` set to `"completed"` — **in the same turn** as the output message below.

Output to user: "Thank you for helping improve this tool."

After feedback completes, return control to the workflow execution in SKILL.md. The calling sidebar determines whether to advance to the next phase or end the migration.
