# Cassandra capture commands

All commands needed to produce the diagnostic files that Mode 2 and Mode 3 consume. Put every file in the same working directory and pass it as `--dir` to `parse-cassandra.ts` — the filename detectors will classify each file automatically.

## `<auth>` shorthand

Throughout this page, `<auth>` stands for the optional Cassandra authentication flags:

```
# Preferred: SigV4 authentication (no password, uses IAM roles)
# Fallback: cqlshrc credentials file (chmod 600)
# Discouraged: [-u <user>] [-p <password>] (visible in process list)
```

Omit when the cluster has no authentication or TLS. When the workload is already on Amazon Keyspaces itself (producing a self-comparison), always use SigV4 authentication:

```
cassandra.<region>.amazonaws.com 9142 --ssl
```

and see [security-considerations.md](security-considerations.md) for SigV4 plugin setup.

## Node-level captures

### `nodetool tablestats` (ID `tablestats`) — mandatory

Run on any one node (a single representative file is sufficient; throughput is scaled by node count from `--info` files):

```bash
nodetool tablestats > tablestats.txt
```

Parser accepts one tablestats file. If multiple are found in `--dir`, only the first is used.

### `nodetool info` (ID `info`) — mandatory

Run on every node:

```bash
nodetool info > info-<node>.txt
```

Repeat `--info` once per node when passing files explicitly. The parser derives reads/writes per second from the cumulative counters in `nodetool tablestats` divided by the uptime from each `info` file.

### `nodetool status` (ID `status`) — recommended

Run on any one node:

```bash
nodetool status > status.txt
```

If omitted, the parser falls back to grouping `info` files by datacenter, or to user-supplied topology.

## Cluster-level captures

### Schema DDL (ID `schema`) — recommended

Run once from any node:

```bash
cqlsh <host> <port> <auth> -e 'DESCRIBE SCHEMA' > schema.cql
```

Feeds both compatibility (Mode 3) and replication-factor signal for pricing (Mode 2).

### Row-size sample (ID `rowsize`) — optional

When absent, the parser defaults to 1024 bytes per row. If you have a row-size sampling tool or can estimate average row sizes from your schema, provide the output as `rowsize.txt` in the diagnostics directory.

### Prepared statements (ID `prepared`) — recommended

Run once:

```bash
./scripts/prepared-statements-sampler.sh <host> <port> <auth> > prepared_statements.ndjson
```

One JSON object per line. Exports `system.prepared_statements`. Drives:

- Compatibility (LWT-in-unlogged-batch, aggregates, UDF calls when schema is also supplied).
- Pricing (marks tables as TTL-driven when `INSERT/UPDATE … USING TTL` is seen).

**Privacy warning:** prepared statements can include literal values the application bound into queries — email addresses, account IDs, customer PII. Treat the file as sensitive. See [security-considerations.md](security-considerations.md).

> **Security note:** Avoid passing passwords directly on the command line — the expanded value is visible in the process argument list (`ps aux`, `/proc/<pid>/cmdline`) regardless of whether you use a variable (`-p "$CASS_PASSWORD"`) or a literal. For process-list safety, use a `cqlshrc` credentials file (with `chmod 600`) or retrieve credentials at runtime from AWS Secrets Manager. For Amazon Keyspaces, use SigV4 authentication (no password needed) — this is the preferred approach and sidesteps the issue entirely.

## Capture sequencing

Work through this checklist end-to-end:

1. Confirm the user is running Cassandra (or a compatible fork). If not, switch to Mode 1.
2. Gather connection details once: host, port, `-u`/`-p`, `--ssl`. Reuse for every `cqlsh` and `./scripts/...` command.
3. Capture `tablestats` and `info` on every node (mandatory).
4. Capture `status` once from any node (recommended).
5. Capture `schema` and `prepared` if the user will allow it — `prepared` may contain PII.
6. Put every file in one directory and pass it as `--dir` to `parse-cassandra.ts`.

## Multi-cluster

For two or more separate clusters, repeat the capture set once per cluster into its own directory. Then run `parse-cassandra.ts` once per directory with distinct `/tmp/keyspaces-<name>.json` outputs, and consolidate into a single PDF per [pdf-reporting.md](pdf-reporting.md).
