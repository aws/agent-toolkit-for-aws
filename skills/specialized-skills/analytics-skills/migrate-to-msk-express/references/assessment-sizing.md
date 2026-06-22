# Assessment — Sizing

Sizing is delegated to AWS's official MSK Sizing/Pricing workbook. This skill
does not implement sizing math and does not package or download the workbook.
Instead, the agent downloads the AWS-published workbook by reading the AWS
Express best-practices page and following its workbook hyperlink, and
`scripts/sizing.py` derives the workload inputs from the discovery contract and
writes them into that downloaded workbook so the workbook's own formulas pick
the recommended instance type, broker count, and monthly cost.

> **Response format**: the assessment response template that covers both
> compatibility AND sizing artifacts lives in
> [`assessment-compatibility.md`](./assessment-compatibility.md) under
> "Response Template". Do not invent a separate sizing-only response shape;
> the user gets one combined response with both artifact paths.

## What `scripts/sizing.py` does

1. Reads `migrate-to-msk-skill-artifacts/<cluster_name>/cluster-config.json` (discovery contract).
2. Computes the six workbook input values (see mapping below).
3. Writes `msk-sizing-inputs.<cluster_name>.json` — a small JSON artifact that
   records each value, the cell it maps to, and the workbook source page.
4. When given `--workbook <path>` (a workbook the agent downloaded), fills the
   six input cells on the `MSK Provisioned` sheet and writes the filled
   `MSK_Sizing_Pricing.<cluster_name>.xlsx`. Without `--workbook`, it prints a
   cell-by-cell fill-in table instead.

No sizing math, no pillar verdict, no spreadsheet library, and no network
access — the script fills a workbook the agent has already downloaded, using
only the Python standard library (`zipfile` + `re`).

## Filling the workbook (agent flow)

1. **Resolve the workbook download from the AWS page.** Read the
   [Express best-practices page](https://docs.aws.amazon.com/msk/latest/developerguide/bestpractices-express.html#brokers-per-express-cluster)
   (section "Right-size your cluster") and follow its **MSK Sizing/Pricing
   workbook** hyperlink to download the `.xlsx` into the working directory. Do
   **not** hardcode a download URL — resolve it from the page each time so the
   skill always uses the current AWS-published workbook.
2. **Fill it.** Run `sizing.py` with `--workbook <downloaded.xlsx>`. The script
   computes the six inputs from the discovery contract, writes them into the
   `MSK Provisioned` sheet, and saves
   `migrate-to-msk-skill-artifacts/<cluster_name>/MSK_Sizing_Pricing.<cluster_name>.xlsx`.
   It also writes `msk-sizing-inputs.<cluster_name>.json` recording the
   cell-to-value mapping. The script never downloads anything itself.
3. **Read the recommendations.** Open the filled workbook in Excel,
   LibreOffice, or Google Sheets. The formulas recalculate on open (the script
   sets `fullCalcOnLoad`); then read the recommended instance type, broker
   count, and monthly cost (see "Reading the recommendations").

If the workbook download is unavailable (for example, no network access), run
`sizing.py` without `--workbook`: it writes the JSON inputs and prints a
cell-by-cell fill-in table the customer can enter into the workbook manually.

## Cell mapping

Sheet: `MSK Provisioned` (cluster design inputs section, rows 11–21).

| Cell | Workbook label | Source from `cluster-config.json` |
|---|---|---|
| `C11` | Average Data In, MB/s | `peak_in / 2` (heuristic; override via `--avg-in-mbps`) |
| `C12` | Peak Data In, MB/s | `metrics.peak_bytes_in_per_broker_mbps × topology.num_brokers` |
| `C13` | Average Data Out, MB/s | `peak_out / 2` (heuristic; override via `--avg-out-mbps`) |
| `C14` | Peak Data Out, MB/s | `metrics.peak_bytes_out_per_broker_mbps × topology.num_brokers` |
| `C17` | Retention, Hrs | max `retention.ms` over topics ÷ 3_600_000 (default 24 if absent; override via `--retention-hrs`) |
| `C20` | Partitions | sum of `topics[].num_partitions` &times; 3 (total partition replicas on the Express target, including leaders and followers; Express always uses a replication factor of 3, so the source cluster's own replication factor is not used here) |

Cells the customer does **not** change (workbook defaults are used):

- `C15` Utilization at Peak (Standard) — default 0.5
- `C16` Utilization at Peak (Express) — formula `=C15*1.5` = 0.75
- `C18` Retention in primary storage (tiered) — default 24
- `C19` Provisioned Storage Throughput — default 1000
- `C21` Replication Factor — default 3 (Express forces a replication factor of 3 anyway)
- `C24` Number of AZs — default 3 (Express requires 3)
- `C25` Nearest Replica Fetching — default true
- `C26` EBS Disk Utilization — default 0.5
- `C29–C31` EC2 comparison inputs

## Caveats

1. **Average throughput isn't in the discovery contract.** The workbook uses
   average for storage volume and cost projection (not for sizing math
   itself). The script defaults to `peak / 2` as a rough heuristic;
   over-estimates cost for steady workloads and under-estimates for spiky
   ones. For accurate cost projection, supply real averages via
   `--avg-in-mbps` and `--avg-out-mbps`.

2. **Retention is per-topic in the discovery contract; the workbook takes one
   number.** The script emits the max over topics as an upper-bound storage
   estimate. Override via `--retention-hrs` if the source has a small set of
   low-retention topics dominating the storage picture.

3. **The workbook hard-codes us-east-1 pricing.** Cell `I8` says
   `us-east-1 pricing`, so the cost figures do not reflect other AWS Regions.

## Reading the recommendations

After opening the filled workbook in a spreadsheet app:

- **Express recommendations**: rows 26–32 (express.m7g.large through
  express.m7g.16xlarge). Instance type is in column **G** (`G26:G32`),
  recommended broker count in column **H**, and monthly cost in column
  **I** (`I26:I32`).
- **Bottleneck breakdown**: rows 134–155 show, per instance, which
  constraint (ingress / egress / partitions / storage) drives the broker
  count. The Express instances occupy cells **F149:H155**, the range the
  assessment response points customers to.

The workbook does not pick a primary; the human reviewer picks based on
operational preference (fewer big brokers vs more small brokers) and cost.

## Refresh procedure

When AWS publishes an updated workbook, no change to this skill is required —
the workbook is downloaded fresh each time. If AWS shifts the input cells,
update the `CELL_*` constants in `sizing.py` and the mapping above.

## Source

The workbook download link lives on the AWS
[Express best practices — Right-size your cluster](https://docs.aws.amazon.com/msk/latest/developerguide/bestpractices-express.html#brokers-per-express-cluster)
page, under the "MSK Sizing/Pricing workbook" link. Resolve the download from
that page rather than hardcoding a direct URL — AWS may change where the
workbook is hosted.

## Security considerations

- **Sizing inputs reveal capacity and topology details.** The
  `msk-sizing-inputs.<cluster_name>.json` artifact and the filled workbook
  contain peak throughput, partition count, retention, and the recommended
  broker count and instance type for the workload. Treat them as sensitive —
  these details are useful inputs for targeted attacks. Do not share via
  unencrypted email, public channels, or public ticketing systems without
  redaction.
- **Store with restrictive permissions.** Keep the artifact inside
  `migrate-to-msk-skill-artifacts/<cluster_name>/` and apply restrictive
  permissions (e.g., `chmod 600`) appropriate for your environment.
- **Discovery input may contain credentials.** `sizing.py` only reads
  workload metrics and topic counts from `cluster-config.json`, but the
  discovery contract may also include security profile fields. Before
  processing, verify the input does not contain credential material (SASL
  passwords, API keys, private keys); redact if necessary.
