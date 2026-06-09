# Key-Space Distribution by Prefix

**When to use:** User wants to understand what is in their cache grouped by key prefix. Typical questions: "which prefix is using the most memory?", "how many keys per tenant?", "is session:*growing faster than cache:*?", "who owns orphan keys?". Also used for cost attribution, tenant onboarding/offboarding, and pre-migration audits.
**When not needed:** Already knows which specific keys are big or hot (use big-key-hunter.md or hot-key-detection.md). Wants a full memory map including overhead (requires MEMORY USAGE, node-based only).

## Preconditions

| Deployment | Available Tiers |
|---|---|
| Serverless | Tier A + Tier B only. MEMORY USAGE blocked; estimate from cardinality x element size. |
| Node-based | All tiers. Must fan out SCAN across all primary endpoints. |

### Command availability

| Command | Node-based | Serverless | Purpose |
|---|---|---|---|
| SCAN \<cursor\> MATCH \<pattern\> COUNT \<n\> | Yes | Yes | Cursor-based keyspace iteration |
| TYPE \<key\> | Yes | Yes | Data type per key |
| STRLEN, HLEN, LLEN, ZCARD, SCARD, XLEN | Yes | Yes | Per-type cardinality |
| DBSIZE | Yes | Yes | Fast total count |
| CLUSTER SHARDS | Yes (Redis OSS 7.0+ / Valkey 7.2+). For Redis OSS 6.x and earlier, use CLUSTER SLOTS. | Yes (virtual shard) | Topology discovery |
| MEMORY USAGE \<key\> | Yes | Blocked | Exact byte footprint |
| KEYS \<pattern\> | Yes (never use) | Blocked | Blocking enumeration. Use SCAN. |

---

## Tier A: Triage with CloudWatch and scope the scan

### Step 1: CloudWatch signal check

Query `BytesUsedForCache` and `CurrItems` trend. If both flat and within range, analysis may not be urgent. If memory-per-key is rising or both climbing together, proceed.

**Stop condition:** If CloudWatch shows no growth and concern is theoretical, consider a sampled scan only.

### Step 2: Get a size estimate

```bash
valkey-cli -h <endpoint> -p 6379 --tls DBSIZE
```

Node-based cluster mode: run DBSIZE against each primary, sum results.

### Step 3: Decide scan strategy

| Total DBSIZE | Strategy |
|---|---|
| < 1M keys | Full scan, 1-3 minutes, low impact |
| 1M-10M keys | Full scan with COUNT 500, off-peak or against replica |
| > 10M keys | Sampled scan (stop after 100k keys) or offline RDB analysis |

### Step 4: Identify delimiter and prefix depth

Common conventions: `:` (app:module:id), `/` (URL-shaped), `|` (legacy). Start with depth 1.

**Stop condition:** If a sample of 100 keys shows no consistent separator, aggregate by first N characters and flag "no structured naming" as output.

---

## Tier B: Narrow with client-side sampling

### Minimal shell pattern (prefix-depth 1, `:` delimiter)

```bash
valkey-cli -h <endpoint> -p 6379 --tls --scan --pattern '*' \
  | awk -F: '{ prefix=$1; count[prefix]++ } END { for (p in count) print count[p]"\t"p }' \
  | sort -rn | head -50
```

For richer aggregation (per-type counts, cardinality sum), use a Python or Bash script that calls TYPE per sampled key with proper key escaping. The minimal awk pipeline above is safe for prefix counting; per-type aggregation with shell pipelines breaks on keys containing spaces, quotes, or special characters.

Run against a replica endpoint on node-based clusters.

### Cost and impact

| Signal | Typical value |
|---|---|
| Runtime on 1M keys | 2-4 minutes |
| Runtime on 10M keys | 20-40 minutes |
| Throughput impact | 0.5% to 2% |
| EngineCPU impact | Minimal (reads only) |

Same safety class as `valkey-cli --bigkeys`: cursor-bounded, read-only, stoppable. Stop if EngineCPU rises >10 percentage points.

**Serverless:** run off-peak. Every sampled key consumes ECPUs.

### Interpret the output

| Prefix | Count | Sum cardinality | Dominant type | Max single-key |
|---|---|---|---|---|
| session:user: | 1,245,000 | 4,980,000 | hash (5 fields avg) | hash 142 fields |
| cache:query: | 234,000 | 234,000 | string (avg 12KB) | string 4MB |
| _tmp: | 89,000 | 89,000 | string (avg 200B) | string 8KB |

- Count = volume. Over a million small session keys is normal. Tens of thousands of untracked `_tmp:` keys with no TTL is a leak.
- Sum cardinality approximates memory load.
- Max catches big-key outliers hiding in an otherwise normal prefix (route to big-key-hunter.md).

**Stop condition:** If distribution is uniform (within an order of magnitude, no type surprises, no unexpected prefixes), the keyspace is healthy.

---

## Tier C: Verify with MEMORY USAGE (node-based only)

### Step 1: Sample keys from the hot prefix

```bash
valkey-cli -h <endpoint> -p 6379 --tls --scan --pattern '<prefix>*' | head -100 > keys-sample.txt
```

### Step 2: Measure byte footprint

```bash
valkey-cli -h <endpoint> -p 6379 --tls MEMORY USAGE <key>
```

### Step 3: Extrapolate

If 100 sampled keys from a 1,245,000-key prefix average 4,200 bytes, the prefix uses ~5GB. Validate against the `BytesUsedForCacheItems` CloudWatch metric (node-based).

---

## TTL Audit Extension

Run alongside Tier B in the same SCAN loop. Adds ~10-15% runtime. TTL and EXPIRETIME are O(1).

| Command | Purpose | Notes |
|---|---|---|
| TTL \<key\> | Seconds until expiry | -1 = no TTL, -2 = key missing |
| EXPIRETIME \<key\> | Absolute Unix timestamp | Valkey 7.2+ / Redis OSS 7.0+. Prefer when available. |

### Augmented output

| Prefix | Count | Keys without TTL | Avg TTL (sec) |
|---|---|---|---|
| session:user: | 1,245,000 | 0 (good) | 1,800 |
| cache:query: | 234,000 | 12,400 | 3,600 |
| _tmp: | 89,000 | 89,000 (orphan suspects) | -1 |

### TTL hygiene signals

- Keys without TTL in a prefix that should be volatile: application lost track
- All keys without TTL in unknown prefix: strong orphan signal (deprecated feature, crashed job)
- Bimodal TTL distribution: two writers with inconsistent policy

### Remediation for TTL problems

1. **Application-level fix** (default): add EX to the SET/HSET/SADD that writes without TTL
2. **Backfill TTL**: run batched EXPIRE during off-peak
3. **Enforce conventions**: document TTL policy per prefix, review in code review
4. **Bulk cleanup**: UNLINK orphan prefixes in batches (non-blocking)

---

## Remediation for prefix distribution problems

1. **TTL hygiene** (default): shorten or enforce TTL on the bloated prefix
2. **Application cleanup**: UNLINK deprecated/orphan keys in batches
3. **Move to different tier**: large blobs that don't benefit from cache semantics belong in S3/DynamoDB
4. **Split to separate cache**: when one tenant/prefix dominates (>30% of memory). If resharding within a cluster instead, note that ElastiCache cannot migrate slots containing items with serialized size larger than 256 MB.
5. **Compression**: gzip/zstd for text-heavy values at application layer

---

## Cross-links

- Specific key in a hot prefix is oversized: `big-key-hunter.md`
- Per-shard imbalance (not prefix-based): `slot-memory-imbalance-detection.md`
- Eviction has started: `troubleshooting.md` Memory Pressure
- Alarm patterns: `alarm-packs.md`
