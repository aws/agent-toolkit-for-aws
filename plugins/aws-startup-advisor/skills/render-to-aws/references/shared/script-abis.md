# Render runtime script ABIs

Every command uses `uv run --project "$SKILL_BASE/scripts" --frozen python`. All path arguments are absolute. Input files must be regular, non-symlinked files contained by the declared input root. Output files must be contained by the declared migration directory, and their existing ancestors must not be symlinks. Scripts write atomically with `fsync` plus same-directory replacement; a failure leaves no new or partially replaced output.

All JSON is UTF-8, canonicalized with sorted object keys, compact separators, NFC strings, and one trailing newline. Success writes exactly one status line to stdout. Failure writes exactly one status line ending in a stable code to stderr, writes no result artifact, and uses exit 1. Argument errors use exit 2 through `argparse`. Status output never contains source text, credentials, response bodies, or remote error prose.

## `parse-render-blueprint.py`

- Caller: main window (Discover pre-dispatch); never the dispatched `rw` worker.
- Arguments: `--source ABS_PATH --workspace-root ABS_PATH --migration-dir ABS_PATH --output ABS_PATH`, followed optionally by `--semantic-evidence ABS_PATH`. Semantic evidence contains the normalized source path/digest and active manifest identity digest plus attempt/workspace/consent tuple; only `outcome: valid` with zero errors is current.
- Success: `BLUEPRINT_OK`, the absolute output path, and a lowercase SHA-256 digest. Output schema is `render-blueprint-normalized` v1.0.
- Retry: correct the input. Stale semantic evidence requires renewed consent, not an automatic retry.

## `capture-render-cli.py`

- Caller: main window (Discover pre-dispatch); never the dispatched `rw` worker.
- Arguments: `--category NAME --workspace-id ID --attempt-id UUID --consent-digest SHA256 --migration-dir ABS_PATH --output ABS_PATH`; category-specific optional arguments are `--resource-id ID`, `--ownership-index ABS_PATH`, `--workspace-root ABS_PATH`, `--blueprint ABS_PATH`, `--start UTC --end UTC`, `--limit N`, `--timeout-seconds N`, and `--max-bytes N`. Every child category requires the active attempt-bound ownership index and rejects an unowned requested parent before `Popen`; returned parent fields must match that requested parent and index.
- Success: `CLI_CAPTURE_OK`, category, and absolute output path. Output schema is `render-cli-capture` v1.0. Every activatable child envelope records a UTC RFC3339 `captured_at`, `status: ok`, `page_count: null`, and the SHA-256 digest of the exact validated ownership-index bytes.
- Retry: only explicitly classified transient process failures within the caller's bounded policy.

## `capture-render-api.py`

- Caller: main window (Discover pre-dispatch); never the dispatched `rw` worker.
- Arguments: `--category NAME --workspace-id ID --attempt-id UUID --consent-digest SHA256 --ownership-index ABS_PATH --migration-dir ABS_PATH --output ABS_PATH`; category-specific optional arguments are `--resource-id ID`, `--start UTC --end UTC`, `--event-type TYPE`, `--resolution-seconds N`, and `--limit N`. Events require a closed UTC window of at most 24 hours; every row declares exact required/allowed query keys. The ownership index parent is the fixed attempt root: every output must be contained beneath it, and the 50 MiB attempt cap recursively counts every regular attempt artifact regardless of extension or nested category directory.
- Success: `API_CAPTURE_OK`, category, and absolute output path. Output schema is `render-rest-capture` v1.0. The envelope records a UTC RFC3339 `captured_at`, the accepted status, page count, workspace, and SHA-256 digest of the exact validated ownership-index bytes; manifest activation must reproduce those fields exactly.
- Retry: two bounded retries only for 429, 5xx, or transport-transient outcomes. Never retry redirects, authentication, schema, ownership, or bounds failures.

## `scan-render-application.py`

- Caller: main window (Discover pre-dispatch); never the dispatched `rw` worker.
- Arguments: `--workspace-root ABS_PATH --migration-dir ABS_PATH --output ABS_PATH`.
- Success: `APP_SCAN_OK`, absolute output path, and lowercase SHA-256 fingerprint. Output schema is `render-application-scan` v1.0.
- Retry: input correction only.

## `parse-render-billing.py`

- Caller: main window (Discover pre-dispatch); never the dispatched `rw` worker.
- Arguments: `--source ABS_PATH --workspace-root ABS_PATH --migration-dir ABS_PATH --output ABS_PATH`. JSON inputs use exact input schema version `1.0.0`; normalized output uses `render-billing` schema version `1.0` independently.
- Success: `BILLING_OK` and the absolute output path. The source digest is recorded only inside the written artifact (`source_digest`), never on stdout. Output schema is `render-billing` v1.0.
- Retry: input correction only.

## `normalize-render-capture.py`

- Caller: main window (Discover pre-dispatch); never the dispatched `rw` worker.
- Arguments: `--migration-dir ABS_PATH --attempt-id UUID --manifest ABS_PATH --output-inventory ABS_PATH --output-clusters ABS_PATH --output-ai-profile ABS_PATH --output-ai-discovery ABS_PATH`. Every argument, including both AI output paths, is required on every invocation; the two AI paths join the same atomic output transaction as the inventory and clusters, so absent AI evidence removes both canonical AI files atomically in that transaction (a non-AI rerun never leaves stale `ai-workload-profile.json` or `render-ai-discovery.json` behind). A live manifest carries `identity_scope: live` plus the active workspace/consent/ownership tuple. A Blueprint/application/billing-only manifest carries `identity_scope: local`, a deterministic `local_identity`, null workspace/consent/ownership fields, and no CLI/REST captures.
- Success: `NORMALIZE_OK` plus absolute inventory and cluster paths. Output schemas are inventory/clusters v1.0, optional shared AI profile (#415 Draft-07 contract, `references/contracts/ai-workload-profile.schema.json`), and optional Render-internal discovery graph v1.0 (`references/shared/schema-render-ai-discovery.json`); local-only output uses an explicit `local:<digest>` identity and never claims a confirmed Render workspace.
- Retry: input correction or a new consented capture attempt. Capability drift is not retried blindly.

## `validate-render-migration-report.py`

- Caller: main window (Generate, before the completion gate); never the dispatched `rw` worker.
- Arguments: positional `REPORT_ABS`, followed by `--migration-dir ABS_PATH`.
- Success: stdout is exactly `REPORT_OK`. It creates no output artifact.
- Retry: deterministic report correction only. Content failure prints one or more `REPORT_FAIL | code=STABLE_CODE` lines and exits 1. Path/argument errors never read the report and use the same fail-closed content status after successful argument parsing.

The two capture commands additionally use error-envelope schema version `1.0` in their attempt manifest. A failure envelope contains only schema version, category, stable code, retryable boolean, attempt ID, timestamp, and bounded numeric counters. Parser, scanner, billing, and normalizer failures are status-only and persist no error body, because their caller already owns phase diagnostics.
