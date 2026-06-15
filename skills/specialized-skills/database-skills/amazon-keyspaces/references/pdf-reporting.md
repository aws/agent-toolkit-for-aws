# PDF reporting

PDF generation is optional and never automatic. Ask the user after showing the JSON estimate. Skip for Mode 3 (compatibility-only) because there is no pricing data to render; direct the user to Mode 2 for a combined report.

## Command

```bash
cd scripts
npx ts-node --project tsconfig.scripts.json generate-pdf.ts \
  --input <path.json> [--label <name>] [--output <path.pdf>]
```

## Flags

- `--input <path>` — path to a `calculate.ts` or `parse-cassandra.ts` JSON file. Repeatable for multi-estimate reports.
- `--label <name>` — display label for the most recent `--input`. Optional; defaults to `Estimate 1`, `Estimate 2`, … in command-line order. Used in the comparison summary table and in per-estimate section headers.
- `--output <path>` — PDF output path. Defaults to `./keyspaces-pricing-estimate.pdf` in the current working directory.

## Modes

**Single estimate** — one `--input` (or JSON on stdin, for backwards compatibility):

```bash
# From a file
npx ts-node --project tsconfig.scripts.json generate-pdf.ts \
  --input /tmp/keyspaces-calc.json --output /tmp/keyspaces.pdf

# From stdin (single estimate only)
cat /tmp/keyspaces-calc.json \
  | npx ts-node --project tsconfig.scripts.json generate-pdf.ts \
  --output /tmp/keyspaces.pdf
```

Renders a single-estimate report — title page, inputs summary, cost tables (on-demand + provisioned + Savings Plan), per-keyspace breakdown if present, and a compatibility section if the JSON contains one.

**Multiple estimates** — two or more `--input` flags:

```bash
npx ts-node --project tsconfig.scripts.json generate-pdf.ts \
  --input /tmp/a.json --label "Option A — Denorm" \
  --input /tmp/b.json --label "Option B — Normalized" \
  --input /tmp/c.json --label "Option C — Reverse Index" \
  --output /tmp/keyspaces-comparison.pdf
```

Renders a consolidated comparison report — a side-by-side summary table (storage, reads/s, writes/s, on-demand/mo, OD+SP/mo, provisioned/mo, prov+SP/mo), followed by a per-estimate section for each input.

## When to use multi-input vs one-at-a-time

Always use a single multi-input invocation when the user has more than one estimate to report:

- **Mode 4** always has three estimates (Denorm / Normalized / Reverse Index).
- **Mode 1 sensitivity runs** — when the user wants to compare two or three traffic scenarios.
- **Mode 2 multi-cluster** — when the user is migrating two or more separate Cassandra clusters.

Avoid generating one PDF per estimate — the consolidated comparison table is the entire point.

## `EAGAIN` on stdin

If `generate-pdf.ts` throws `EAGAIN: resource temporarily unavailable, read`, the upstream `ts-node` process closed stdin before this process read it. Write the JSON to a file and pass `--input <path>` instead of piping. This is a Node.js timing behavior, not a bug in the script.

## Saving the intermediate JSON

The scripts print pricing JSON to stdout. Always `tee` or redirect into `/tmp/keyspaces-*.json`:

```bash
npx ts-node --project tsconfig.scripts.json calculate.ts \
  us-east-1 1000 500 1024 100 0 false \
  | tee /tmp/keyspaces-calc.json
```

Then PDF generation can reuse the same file without rerunning pricing. This is also how you produce multi-input comparisons — one `calculate.ts` or `parse-cassandra.ts` call per scenario, each to its own `/tmp/*.json`, then one `generate-pdf.ts` pulling them all.

## Output path conventions

- Default filename: `keyspaces-pricing-estimate.pdf` in the current directory.
- For Mode 4: `keyspaces-sql-comparison.pdf` or similar descriptive name.
- For cluster comparisons: include cluster names or dates in the filename so the user can distinguish reports later.

Prefer an absolute path in `--output` when running inside a skill so the user knows where to find the file afterward.

## What the PDF contains

Every PDF includes:

1. **Title page** — skill name, date, input summary.
2. **Cost summary** — on-demand vs provisioned vs Savings Plan tiers, line-item breakdown.
3. **Per-keyspace / per-datacenter breakdown** (Mode 2 only).
4. **Compatibility findings** — when the source JSON includes a `compatibility` block.
5. **Recommendation** — implicit (whichever total is lowest), reinforced by the table formatting.

The PDF does not include raw capture files, node hostnames, or credentials. If the user wants a deeper audit trail, keep the intermediate JSON alongside the PDF.

## Non-goals

- The PDF renderer does not fetch live pricing. All rates come from `assets/data/*.json`, which is a snapshot. When prices drift, the skill owner refreshes these files from AWS Pricing APIs.
- The PDF does not run the pricing calculation — it only renders pre-computed JSON. If the JSON is stale, regenerate it first.
- PDF generation does not modify any AWS resources. It is an output-only operation.
