# Snapshot retrieval and parsing

Snapshot data captured by a breakpoint lives in CloudWatch Logs
(`/aws/service-events/{service}`). Two host scripts wrap the Logs Insights queries; this file
is the recipe for analyzing what they return.

> **Reminder:** the snapshot log group (`/aws/service-events/{service}`) **must be encrypted
> at rest** with a KMS CMK (`aws logs associate-kms-key`) before capturing — captured snapshots
> may contain credentials, PII, or secrets. See Security Considerations in
> `dynamic-instrumentation.md`.

## Retrieval commands

Both require a host with `python3` + `boto3`. Region resolves as `--region` flag > `AWS_REGION` >
`AWS_DEFAULT_REGION` > `us-east-1` default (the same precedence as `di_instrumentation.py`) — it
MUST be the same region the breakpoint was created in, or searches return
empty even when the breakpoint is ACTIVE. Pass arguments via `--json-file` (or `--json -` on
stdin) so values stay off the shell command line.

- **Discover the snapshot structure first** (Step 3 rule — always do this before searching).
  Write the arguments to a file, then:

  ```bash
  # args.json:
  # {"service": "<svc>", "environment": "<env>",
  #  "location_hash": "<16-hex>", "status_timestamp": "<ACTIVE-event-ISO8601>"}
  python3 scripts/di_snapshots.py sample --json-file args.json
  ```

  Returns one nearby snapshot as JSON plus per-attribute `field_documentation`. Read the
  field paths from this sample — they are authoritative; do not rely on canned paths that may
  be stale.

- **Search a batch** near a status-event timestamp, narrowing with `custom_filters` when you
  can name the target:

  ```bash
  # args.json:
  # {"service": "<svc>", "environment": "<env>",
  #  "location_hash": "<16-hex>", "status_timestamp": "<ISO8601>",
  #  "limit": 20, "custom_filters": ["..."]}
  python3 scripts/di_snapshots.py search --json-file args.json --out /tmp/snaps.json
  ```

  `custom_filters` are raw Logs Insights fragments appended with `and`; an unbalanced double
  quote is rejected. `--out` writes the result with owner-only (0600) permissions because
  snapshots may contain PII/secrets.

`--print-contract` lists both ops and their exact argument schema.

## Parsing the saved output (never hand-transcribe; never `cat` a large file into context)

Large results are written to a file (use `--out`, or redirect stdout). Parse the file with
`jq`/`python` and extract only the fields you need. **Do not** retype values you see in tool
output into a script literal — a single mistyped `orderId`/`paymentRef` silently corrupts the
aggregation.

> **Encryption at rest for the saved file.** `--out` already restricts the file to owner-only
> (`0600`), but the snapshot may still contain credentials/PII. Write it only to a private
> location on an encrypted volume (e.g. an encrypted EBS volume or encrypted tmpfs), avoid
> world-readable shared temp directories, and delete it as soon as analysis is done.

The retrieval output is JSON. Snapshot records are under `results[*]`, each with an
`@message` that is itself a JSON string — `json.loads` it again to reach `body.captures.*`.
The parser already extracts the common debugging fields; key ones from a parsed snapshot:

| Field | Meaning |
| --- | --- |
| `entry_argument_names` / `entry_arguments` | method/function-entry argument names + values |
| `entry_local_names` / `entry_locals` | locals captured at entry |
| `return_value` / `throwable` | method return value or thrown exception |
| `line_numbers` / `line_locals` | line-level captured locals, keyed by line |
| `stack_preview` / `stack_frame_count` | call stack (frames use `file_path`/`line_number`) |
| `trace` | traceId/spanId for correlation |
| `duration_ms` | method duration (method-level only) |

**Java `Map`/`HashMap`** values appear as key/value `entries` (not flat `fields`); raise object
depth / collection width if map contents are truncated.

Write the jq/python against the **actual field paths from your live sample snapshot**, group by
a domain identifier (e.g. `orderId`), and surface anomalies (duplicates, outliers). When
combining results from multiple queries, deduplicate by snapshot `id` before aggregating.

After analysis, do not retain the saved snapshot file — it may contain PII/secrets.
