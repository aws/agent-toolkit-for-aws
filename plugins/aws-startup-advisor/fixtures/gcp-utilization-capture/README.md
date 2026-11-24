# GCP utilization-capture fixtures (Cloud Monitoring reduction)

Canned Cloud Monitoring `projects.timeSeries.list` pages plus the `gce.json` /
`sql.json` / MIG captures they join to, for testing
`skills/gcp-to-aws/scripts/summarize-monitoring.py` (the reduction step of
`references/phases/discover/discover-live.md` rows 21a-21n) without a GCP
project. The synthetic project is `acme-prod` (same as `gcp-live-capture`),
everything in `us-central1-a`. It lives in its own directory because the
`gcp-live-capture` replay has an empty `gce.json` on purpose and adding eight
VMs there would break `expected-drift.json`.

The raw pages were seeded from a real capture (shapes, units, point layout, the
`db-f1-micro` values) with the project name, numeric instance ids and every
address redacted; instance ids are synthetic 19-digit strings.

## Window

`2026-11-13T00:00:00Z` -> `2026-11-20T00:00:00Z`: 7 days, 168 expected hourly
samples. The live phase captures 30 days; the script derives `samples_expected`
and `window_days` from `--window-start/--window-end`, so every rule is exercised
identically while the committed raw files stay around 1 MB instead of ~5 MB.
Points are newest-first with `startTime == endTime`, as the API returns aligned
GAUGE series.

## What each resource exercises

Compute Engine (`gce.json`, `monitoring-gce-*`):

- **web-steady** (n2-standard-8) — the ordinary case: cpu p95 ~0.12, memory p95
  ~0.15, `coverage: sufficient`, `burst: false`, `idle: false`. ONE hour has
  `max` 0.9 with an ordinary mean, proving `max` never drives `burst`. Its
  `ALIGN_MEAN` cpu series is split across `-p1.json` (first 100 points plus
  `nextPageToken`) and `-p2.json` (remaining 68 points plus every other VM):
  the page merge must yield one 168-point series.
- **api-lowload** (n2-standard-8) — low but not idle: cpu ~0.08, memory ~0.08.
- **cache-heavy** (n2-standard-8) — cpu ~0.12 with memory p95 ~0.63 (the
  memory-bound sizing case for PR 2).
- **batch-bursty** (n2-standard-8) — two consecutive hourly means of 0.6 on a
  p95 ~0.10 baseline -> `burst: true`. It has NO memory series (no Ops Agent)
  -> `memory: {"status": "unavailable"}`.
- **new-vm** (e2-standard-2) — only the newest 100 of 168 hours -> no zero-fill,
  `samples_present: 100`, `coverage: insufficient`.
- **idle-vm** (n2-standard-2) — cpu ~0.01, memory ~0.10 -> `idle: true`.
- **web-mig-7f3k** (e2-medium) — listed in `mig-members-web-mig.json` (row 22a
  output for the `web-mig` group; the live phase writes one
  `mig-members-<group>.json` per group and the script globs `mig-members*.json`)
  -> `mig_member: true`.
- **ops-small** (e2-small) — shared-core CPU: p95 ~1.2 and `max` 1.965 are kept,
  never clamped. Its Ops Agent memory has all FIVE `state` series (used, free,
  cached, buffered, slab) and each carries a per-series `"unit": "%"`, while the
  other VMs rely on the response-level `unit`; only `state == "used"` reaches
  the summary.

Cloud SQL (`sql.json`, `monitoring-sql-*`):

- **orders-db** (POSTGRES_15, db-f1-micro) — the live `db-f1-micro` numbers:
  cpu ~0.10, memory 0.999-1.0, `disk/bytes_used` a constant 87293952 bytes
  (`int64Value` under `ALIGN_MAX`, `doubleValue` under `ALIGN_MEAN`, reduced to
  ints). `num_backends` has four `database` series (`orders` 0..3,
  `cloudsqladmin` 2, `postgres` 0, `template1` 0), one series per page
  (`-p1`..`-p4`, `nextPageToken` on p1-p3), summed hour by hour before the
  reduction. Its `monitoring-sql-cpu-ALIGN_MEAN-p1.json` series carries a 169th
  point with `endTime == 2026-11-13T00:00:00Z`, the partial bucket of an
  unaligned window that the script must drop. It has no `network/connections`
  series, so connections come from `sql-pgconn`.
- **reports-db** (MYSQL_8_0, db-custom-2-8192) — `network/connections` series in
  `sql-conn` only (MySQL has no `num_backends`), cpu ~0.3, memory ~0.5, disk
  ~12 GiB.

Other captures: `monitoring-api.json` (row 21), `mig-groups.json` (row 22) and
`manifest.json` with one `captures[]` entry per row 7, 2, 21, 21a-21n, 22, 22a,
all `status: "ok"`; each 21a-21n entry names its `-p1` file and its `note`
carries the page count, page span and total byte size, as discover-live.md
Step 2d requires.

## Files

- `make_fixture.py` — the deterministic generator (`random.Random(20261120)`,
  compact JSON for the raw pages). Writes everything under `live-capture/`.
- `live-capture/` — the raw capture directory as rows 2, 7, 21-22a leave it.
- `expected-utilization-summary.json` — the golden `utilization-summary.json`
  the script must reproduce byte-for-byte (`tests/test_gcp_summarize_monitoring.py`).
- `after-discover/gcp-resource-inventory.json` — the inventory-with-`utilization`
  golden for `lint:artifacts`: three resources (`web_steady`, `batch_bursty`
  with memory `unavailable`, `orders_db`) whose `utilization` blocks are copied
  verbatim from the expected summary.

## How to regenerate

From `plugins/aws-startup-advisor/`:

```bash
python3 fixtures/gcp-utilization-capture/make_fixture.py
python3 skills/gcp-to-aws/scripts/summarize-monitoring.py \
  --capture-dir fixtures/gcp-utilization-capture/live-capture \
  --project acme-prod \
  --window-start 2026-11-13T00:00:00Z --window-end 2026-11-20T00:00:00Z \
  --output fixtures/gcp-utilization-capture/expected-utilization-summary.json
```

Both steps are deterministic: a second run must leave `git status` clean. If the
expected summary changes, update the `utilization` blocks in
`after-discover/gcp-resource-inventory.json` to match.
