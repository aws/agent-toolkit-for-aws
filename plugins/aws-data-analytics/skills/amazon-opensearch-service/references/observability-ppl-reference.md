# PPL language reference (observability)

> The AWS MCP server is recommended for executing these commands but is not required — all steps use standard `awscurl` / AWS CLI syntax.

Shared PPL reference for the `log-analytics` and `trace-analytics` capabilities.
Queries follow pipe-delimited syntax: `source=<index> | command1 | command2 ...`.
Grammar is sourced from [opensearch-project/sql](https://github.com/opensearch-project/sql) under `docs/user/ppl/`.

Loaded from: [`log-analytics-guide.md`](log-analytics-guide.md), [`trace-analytics-trace-queries.md`](trace-analytics-trace-queries.md).

## Query discipline (MUST follow)

1. **Unknown command or function — you MUST consult the upstream grammar before answering.** If a
   command, function, or parameter is not in this reference, you MUST fetch the raw markdown from
   `opensearch-project/sql` (URLs below). You MUST NOT invent PPL syntax and you MUST NOT claim a
   command does not exist without checking first, because OpenSearch PPL includes many commands
   (for example `graphLookup`, `explain`, `append`, `join`) that do not exist in other query systems.
2. **You MUST verify emitted queries when a cluster endpoint is reachable.** When the AOS domain or
   AOSS collection endpoint is available, every emitted PPL query MUST be validated with a best-effort
   cascade before you return it:
   1. Execute it against `_plugins/_ppl` and capture the row count and any error.
   2. If it succeeds but returns 0 rows, run `_plugins/_ppl/_explain` to confirm the plan parses and
      resolves field references, then surface the empty-result observation.
   3. If `_plugins/_ppl` errors, fix the query (consult the upstream grammar as needed) and re-validate.
   When no endpoint is reachable, you MUST state explicitly that the query is unverified, because an
   untested PPL query can silently reference a non-existent field or use version-specific syntax.

## Field name escaping

Dotted field names MUST be backtick-quoted, because an unquoted dot is parsed as a path separator and
fails: `` `attributes.gen_ai.operation.name` ``, `` `status.code` ``,
`` `resource.attributes.service.name` ``.

Field names beginning with a special character (e.g. the `@`-prefixed `` `@timestamp` ``) must also be
backtick-quoted, because the leading character is not a valid bare identifier.

## API endpoints

Query (AOS uses `--service es`; AOSS uses `--service aoss`):

The endpoint URL MUST use HTTPS (not HTTP). `awscurl` will not upgrade an HTTP URL to HTTPS, so verify
`$OPENSEARCH_ENDPOINT` starts with `https://` before executing any command below, because an
unencrypted data-plane request exposes the query and results in transit.

Source the SigV4 signing credentials from an IAM role (instance profile, ECS task role, or SSO session)
rather than static access keys, because static access keys are a standing exfiltration risk.

    awscurl --service es --region $AWS_REGION \
      -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
      -H 'Content-Type: application/json' \
      -d '{"query": "source=otel-v1-apm-span-* | stats count() by serviceName"}'

Explain (query-plan debugging):

    awscurl --service es --region $AWS_REGION \
      -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl/_explain" \
      -H 'Content-Type: application/json' \
      -d '{"query": "source=otel-v1-apm-span-* | where `status.code` = 2 | stats count() by serviceName"}'

`_explain` accepts an optional `mode` (`standard` / `simple` / `cost` / `extended`). `simple`, `cost`,
and `extended` require the v3 engine (`plugins.calcite.enabled=true`); `standard` works on v2 and v3.
Engine requirements are version-specific — verify whether the v3 engine is available and enabled on the
target domain/collection by checking `GET _cluster/settings` for `plugins.calcite.enabled`, or consult the
upstream `opensearch-project/sql` docs rather than assuming these constraints are fixed.

## Core commands

| Command | Syntax | Description |
|---|---|---|
| `source` | `source=<index>` | Start query from index pattern |
| `search` | `search source=<index> [<expr>]` | Alternative first command; search-expression syntax (`field=value`, `AND/OR/NOT`, time modifiers) |
| `where` | `where <condition>` | Filter rows |
| `regex` | `regex <field> = '<pattern>'` (or `!=`) | Filter rows by Java regex on a field |
| `fields` | `fields [+\|-] <list>` | Select / exclude fields |
| `table` | `table [+\|-] <list>` | Alias for `fields` |
| `stats` | `stats <agg>... [by <field>]` | Aggregate data |
| `sort` | `sort [+\|-] <field>` | Order results (+ asc, - desc) |
| `reverse` | `reverse` | Reverse result order (no-op without a preceding `sort`/`@timestamp`; collation-destroying ops such as `stats`/`join` make it a no-op) |
| `head` | `head [N]` | Limit results (default 10) |
| `tail` | `tail [N]` | Return the last N results (default 10) |
| `eval` | `eval <new> = <expr>` | Compute new fields |
| `fieldformat` | `fieldformat <field>=[(prefix).]<expr>[.(suffix)]` | `eval` alias with prefix/suffix string concat for display |
| `dedup` | `dedup [N] <field>` | Remove duplicates |
| `rename` | `rename <old> AS <new>` | Rename fields |
| `replace` | `replace '<pat>' WITH '<repl>' IN <field>` | Literal/wildcard string replace (supports `*`) |
| `convert` | `convert <fn>(<field>) [AS <field>]` | Type-coerce (`auto()`, `num()`, `mktime()`, `ctime()`, `dur2sec()`, `mstime()`, `memk()`, `rmcomma()`, `rmunit()`, `none()`) |
| `top` | `top [N] <field>` | Most frequent values |
| `rare` | `rare <field>` | Least frequent values |

## Time-series commands

| Command | Syntax | Description |
|---|---|---|
| `bin` | `bin <field> [span=<int>] [bins=<n>] [minspan=<int>] [aligntime=...] [start=<v>] [end=<v>]` | Bucket numeric/time values (`bins=` on timestamps requires `plugins.calcite.pushdown.enabled=true` and the binned field inside a `stats` aggregation; otherwise use `span=`; verify v3 engine availability on the target domain/collection before relying on this flag) |
| `timechart` | `timechart span=<interval> <agg> [by <field>]` | Time-bucketed aggregation |
| `chart` | `chart <agg> [by <row> <col>] \| [over <row> [by <col>]] [limit=topN] [useother=<bool>] [usenull=<bool>]` | Aggregate + pivot for 2D charts |
| `span()` | `span(<field>, <interval>)` | Bucket numeric/date values |
| `trendline` | `trendline sort <field> sma(<N>, <field>)` | Moving average |
| `streamstats` | `streamstats <agg> [by <field>]` | Running statistics (memory-intensive) |
| `eventstats` | `eventstats <agg> [by <field>]` | Add agg as field without collapsing rows (memory-intensive) |

Span time units: `ms`, `s`, `m`, `h`, `d`, `w`, `M`, `q`, `y` (`bin` also accepts `us`, `cs`, `ds` and
longhand forms). Timechart rate functions: `per_second()`, `per_minute()`, `per_hour()`, `per_day()`.

## Parse / extract commands

| Command | Syntax | Description |
|---|---|---|
| `parse` | `parse <field> '<regex>'` | Regex extraction (may drop fields on some versions) |
| `grok` | `grok <field> '<pattern>'` | Grok pattern extraction (memory-intensive) |
| `rex` | `rex field=<field> '<regex>'` | Named capture groups |
| `patterns` | `patterns <field>` | Auto-discover log patterns |
| `spath` | `spath input=<field> [output=<field>] [path=<path>]` | Extract from structured JSON (runs on the coordinator node; prefer indexing fields directly on large datasets) |

## Join / lookup / set commands

| Command | Syntax | Description |
|---|---|---|
| `join` | `join left=a right=b ON a.f = b.f <index>` | Cross-index join |
| `lookup` | `lookup <index> <field> [OUTPUT <fields>]` | Enrich from another index |
| `subquery` | `where <f> IN [source=<idx> \| ... \| fields <f>]` | Nested query filter |
| `union` | `union [maxout=<n>] <ds1> <ds2> [...]` | UNION ALL across datasets; auto type-coerces conflicting schemas |
| `multisearch` | `multisearch [<sub1>] [<sub2>] [...]` | Run + merge subsearches; supports timestamp interleaving |
| `append` | `append [source=<idx> \| ...]` | Append results from another query |
| `appendcol` | `appendcol [override=<bool>] [<subsearch>]` | Append subsearch result as additional columns |
| `appendpipe` | `appendpipe [<subpipeline>]` | Append subpipeline results (runs lazily) |
| `graphLookup` | `graphLookup <idx> start=<expr> edge=<from><op><to> [maxDepth=<n>] ... as <out>` | (Experimental) recursive BFS graph traversal |

Cross-index `join` reliability varies by engine version, so you MUST test the join on the target
domain/collection (per the query-discipline cascade above) rather than assuming it works. If it returns 0 rows
unexpectedly, fall back to separate queries correlated by `traceId`.

## Transform commands

| Command | Description |
|---|---|
| `fillnull` | Replace nulls (backtick fields not supported in field list) |
| `flatten` | Flatten nested fields to top level |
| `expand` | Expand arrays into separate rows |
| `mvexpand` | `mvexpand <field> [limit=<n>]` — expand each multivalue element into its own row |
| `mvcombine` | Combine a target field into a multivalue array across otherwise-identical rows |
| `nomv` | Convert a multivalue field to a single string (joined by `\n`) |
| `transpose` | Pivot rows into columns |
| `addtotals` | `addtotals [field-list] [row=<bool>] [col=<bool>] [label=<s>] [labelfield=<f>] [fieldname=<f>]` — row/column totals (numeric only) |
| `addcoltotals` | Column-only totals; equivalent to `addtotals row=false col=true` |

## Function families

- **Aggregation:** `count()`, `sum(f)`, `avg(f)`, `max(f)`/`min(f)`, `distinct_count(f)`, `percentile(f, pct)`, `var_samp(f)`/`stddev_samp(f)`, `earliest(f)`/`latest(f)`, `values(f)`.
- **Statistical (eval-context, scalar):** `MAX(x, y, ...)`, `MIN(x, y, ...)` — these return a single value across their arguments and do NOT aggregate across rows, because they are scalar; use aggregate `max(field)`/`min(field)` inside `stats` instead.
- **Condition:** `isnull(f)`/`isnotnull(f)`, `if(cond, t, f)`, `case(c1, v1, ..., else)`, `coalesce(v1, v2, ...)`, `like`/`in`/`between`.
- **Conversion:** `cast(f AS type)`, `tostring()`, `toint()`, `tolong()`, `tofloat()`, `todouble()` (types: STRING, INT, LONG, FLOAT, DOUBLE, BOOLEAN, DATE, TIMESTAMP).
- **Datetime:** `now()`, `date_format(date, fmt)`, `date_add(date, INTERVAL n unit)`, `date_sub(date, INTERVAL n unit)`, `datediff(d1, d2)`, `day()`/`month()`/`year()`/`hour()`/`minute()`/`second()`.
- **String:** `concat()`, `length()`/`lower()`/`upper()`/`trim()`, `substring(s, start, len)`, `replace(s, from, to)`, `regexp_extract(s, pat, grp)`, `regexp_replace(s, pat, repl)`.
- **Relevance:** `match(field, query)`, `match_phrase(field, phrase)`, `multi_match([f1, f2], query)`, `query_string([f1, f2], query)`, `wildcard_query(field, pattern)`.
- **Math:** `abs()`, `ceil()`, `floor()`, `round(val, decimals)`, `sqrt()`, `pow()`, `mod()`, `log()`, `log10()`, `exp()`.
- **Collection (multivalue):** `array(...)`, `array_length(arr)`, `mvjoin(arr, sep)`, `mvfilter(expr)`, `mvindex(arr, start [, end])`, `mvappend(...)`.
- **JSON** (path notation `<key>{<idx>}...`; `{}` = all elements): `json(value)`, `json_extract(json, path)`, `json_array(...)`, `json_object(...)`, `json_keys(json)`.
- **IP:** `cidrmatch(ip, cidr)`, `geoip(ip)`.
- **Cryptographic:** `md5(str)`, `sha1(str)`, `sha2(str, bits)` (hex-encoded STRING digests).
- **System:** `typeof(expr)`.

## Operators

Arithmetic: `+`, `-`, `*`, `/`, `%`; use parentheses for precedence. Division behavior depends on the
cluster setting `plugins.ppl.syntax.legacy.preferred`: when `true` integer/integer is truncated; when
`false` operands are promoted to floating point. Do not assume a default — read the effective value on
the target domain/collection with `GET _cluster/settings?include_defaults=true` (inspect
`defaults.plugins.ppl.syntax.legacy.preferred` unless overridden under `persistent`/`transient`) before
relying on the division semantics. Division by zero returns `NULL`, not an error. Modulo (`%`) is
integer-only and raises a type error on floats, because the operator has no float overload.

## ML commands

| Command | Description |
|---|---|
| `ad` | Anomaly detection (auto-detects input fields from the pipeline) |
| `kmeans` | K-means clustering (operates on all numeric fields) |

`ml action=rcf` support varies by cluster version — prefer the `ad` command directly, and if you need
`ml action=rcf`, verify it against the target domain/collection (test the command) or the upstream
`opensearch-project/sql` docs for that version rather than assuming a fixed constraint.

## System / inspection commands

| Command | Description |
|---|---|
| `describe <index>` | Inspect index mapping and field types (use a concrete index name, not a wildcard) |
| `show datasources` | List configured data sources |
| `explain [<mode>] <query>` | Display the execution plan (MUST be the first command); `mode` ∈ `standard` (default) / `simple` / `cost` / `extended`; non-`standard` modes require the v3 engine |

## Looking up PPL documentation

When a command/function is missing here, a query fails with a syntax error, or the user's cluster
version may differ, you MUST fetch the canonical grammar from `opensearch-project/sql`:

- Commands: `https://raw.githubusercontent.com/opensearch-project/sql/main/docs/user/ppl/cmd/<command>.md`
- Functions: `https://raw.githubusercontent.com/opensearch-project/sql/main/docs/user/ppl/functions/<category>.md`
  (categories: `aggregations`, `collection`, `condition`, `conversion`, `cryptographic`, `datetime`,
  `expressions`, `ip`, `json`, `math`, `relevance`, `statistical`, `string`, `system`)

Prefer the `opensearch-project/sql` source over `opensearch.org` documentation pages, because the docs
site MAY trail the SQL repository by one or more releases.

## Security Considerations

- **Authenticate every query with SigV4 (IAM auth), never open access.** PPL queries hit the data plane
  (`_plugins/_ppl`), so requests MUST be SigV4-signed — AOS uses `--service es`, AOSS uses `--service aoss`.
  Do NOT rely on public/unauthenticated endpoints, because an open data plane exposes all indexed data.
- **PPL results can expose sensitive data.** A query returns whatever fields the caller's index-level
  permissions allow. Callers MUST have appropriately scoped access via FGAC (AOS domains) or the collection's
  data access policy (AOSS), because a broad grant lets a query surface PII or other restricted fields.
- **Enable audit logging.** Turn on CloudTrail for the management-plane API calls and OpenSearch audit logs
  for data-plane access so you can attribute who ran which queries, because an unaudited data plane makes
  misuse undetectable.
- **Do not log full query results to CloudWatch if they may contain PII** unless the log group is encrypted
  with a customer-managed KMS key, because query output can carry sensitive document fields into logs.
- **Rate-limit, time-bound, and monitor the PPL endpoint.** Enforce rate limits on `_plugins/_ppl` traffic
  (via a fronting API gateway/proxy or AWS WAF rate-based rules) and set query timeouts so a runaway
  aggregation or `join` cannot exhaust cluster resources; alarm on CloudWatch `_plugins/_ppl` call volume and
  error rates to catch abuse. This matters most for agentic search, where each query invokes a Bedrock model —
  an unthrottled path there drives both resource exhaustion and unbounded per-call cost.
