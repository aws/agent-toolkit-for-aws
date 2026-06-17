# DocumentDB — Compatibility Assessor

Assess whether an existing MongoDB workload will run on Amazon DocumentDB. Clone the `amazon-documentdb-tools` repo, run the compat tool and index tool, triage findings, and produce `artifacts/{app-name}/compatibility-report.md`.

## What to ask upfront

- `app_name` (lowercase with hyphens, used for `artifacts/{app-name}/`)
- One of: MongoDB connection string, log files path, or source code directory
- `target_version` (default: `8.0`)

## Workflow

### Step 0: Clone tools and create artifact directory

```bash
if [ ! -d "amazon-documentdb-tools" ]; then
  git clone https://github.com/awslabs/amazon-documentdb-tools amazon-documentdb-tools
  (cd amazon-documentdb-tools/index-tool && python3 -m pip install -r requirements.txt -q)
fi
mkdir -p artifacts/<app-name>
```

If git clone fails, tell the user and ask them to clone it manually.

### Step 1: Run the compat tool

Pick one input mode:

**A — Live MongoDB URI (most accurate):**

```bash
python3 amazon-documentdb-tools/compat-tool/compat.py \
  --uri "mongodb://<user>:<pass>@<host>:<port>/admin?directConnection=true" \
  --version 8.0
```

**B — Source directory:**

```bash
python3 amazon-documentdb-tools/compat-tool/compat.py \
  --version 8.0 --directory /path/to/app/src \
  --excluded-extensions txt,md
```

**C — MongoDB log file:**

```bash
python3 amazon-documentdb-tools/compat-tool/compat.py \
  --file /path/to/mongod.log --version 8.0
```

Capture the full output. If URI auth fails, retry with `--directory` or `--file` mode. `directConnection=true` is needed for replica-set members.

### Step 2: Run the index tool (URI mode only)

```bash
cd amazon-documentdb-tools/index-tool
python3 migrationtools/documentdb_index_tool.py \
  --dump-indexes --dir ../index-export \
  --uri "mongodb://<user>:<pass>@<host>:<port>"

python3 migrationtools/documentdb_index_tool.py \
  --show-issues --dir ../index-export
```

If no URI provided, skip this step and note "Index analysis skipped — no MongoDB URI provided" in the report.

### Step 3: Verify operator support against live docs

**Mandatory — do this BEFORE stating any operator is unsupported.** DocumentDB adds operator support across versions; hardcoded lists go stale. Always check live status.

For every operator the compat tool flags, call `web_fetch(url="https://docs.aws.amazon.com/documentdb/latest/developerguide/mongo-apis.html")` and search for the operator name. The page has Yes/No tables per version (3.6 / 4.0 / 5.0 / 8.0 / Elastic). If the aws-documentation plugin is available, prefer `aws___search_documentation` for the same page.

State support as: "`$operator` is [supported / not supported] on DocumentDB 8.0 per the checked compatibility reference. Verify at the MongoDB API compatibility page for the latest status."

If `web_fetch` is unavailable, add to the report: "Operator support status based on bundled reference data — may not reflect recent additions. Verify current status at https://docs.aws.amazon.com/documentdb/latest/developerguide/mongo-apis.html".

### Step 4: Triage every finding

- **BLOCKER** — not supported in target version (verify via Step 3 first); app code must change before migration
- **WARNING** — supported with behavioral differences; test before cutover
- **SAFE** — fully supported, no changes needed

### Step 5: Write the compatibility report

Write `artifacts/{app-name}/compatibility-report.md` with this structure:

```markdown
# Compatibility Report: {app-name}
**Date:** {today}
**Target:** DocumentDB 8.0
**Method:** [live URI / source scan / log analysis]

## Summary
- Blockers: N
- Warnings: N
- Safe: N

## Blockers (must fix before migration)
### {operator or feature}
- **Found in:** {file:line or query pattern}
- **Issue:** {why it doesn't work}
- **Workaround:** {concrete alternative with code}

## Warnings (test carefully)
### {operator or feature}
- **Found in:** ...
- **Behavioral difference:** ...
- **Recommendation:** ...

## Index Issues
- **Incompatible indexes:** {list from --show-issues}
- **Action:** Use `--skip-incompatible` during restore; recreate equivalents manually

## Safe
{list of confirmed-supported operators}
```

Summarize the key findings to the user (blocker count, warning count, critical items).

## Common blockers and workarounds

### `$where` (JS in queries)

```javascript
// BLOCKED
db.col.find({ $where: "this.price > this.cost" })
// Fix — use $expr with native operators
db.col.find({ $expr: { $gt: ["$price", "$cost"] } })
```

### MapReduce (blocked on 3.6 / 4.0 / 5.0 — works on 8.0)
Rewrite as aggregation for 5.0:

```javascript
db.orders.aggregate([
  { $group: { _id: "$category", total: { $sum: "$amount" } } },
  { $out: "category_totals" }
])
```

### `$accumulator` / `$function` (custom JS)
Rewrite with native operators: `$sum`, `$avg`, `$reduce`, `$map`, `$filter`, `$switch`.

### Hashed indexes

```javascript
// BLOCKED: db.col.createIndex({ userId: "hashed" })
db.col.createIndex({ userId: 1 })    // single-field ascending
```

### Wildcard indexes (verify current support status)
Check the [MongoDB API compatibility page](https://docs.aws.amazon.com/documentdb/latest/developerguide/mongo-apis.html) — wildcard indexes may not be supported on all DocumentDB versions, and DocumentDB adds index types across versions.

```javascript
// If unsupported: create explicit indexes for the specific fields you filter on
// db.col.createIndex({ "$**": 1 })  ← check support status before attempting
```

### 2d (legacy) geospatial indexes

```javascript
// BLOCKED: db.places.createIndex({ location: "2d" })
db.places.createIndex({ location: "2dsphere" })    // works, supports GeoJSON
```

### `$lookup` with pipeline (blocked on 5.0, works on 8.0)

```javascript
// For 5.0, rewrite as localField/foreignField:
{ $lookup: { from: "orders", localField: "_id", foreignField: "userId", as: "orders" } }
```

### `$graphLookup` (verify current support status — workaround below)
Check the [MongoDB API compatibility page](https://docs.aws.amazon.com/documentdb/latest/developerguide/mongo-apis.html) before advising. If unsupported, use the materialized path pattern — store the ancestor list at write time (this is often the better design regardless of `$graphLookup` availability):

```javascript
// Each doc carries its ancestors array
{ _id: "cat3", name: "Shoes", ancestors: ["cat1", "cat2", "cat3"] }
// All ancestors:
db.categories.find({ _id: { $in: doc.ancestors } })
// All descendants of cat1:
db.categories.find({ ancestors: "cat1" })
```

### `$facet` (verify current support status — workaround below)
Check the [MongoDB API compatibility page](https://docs.aws.amazon.com/documentdb/latest/developerguide/mongo-apis.html) before advising. If unsupported: split into separate aggregation pipelines and merge results in application code.

## Common warnings (behavioral differences)

- **`explain()` output structure differs** — do not parse it programmatically assuming MongoDB format
- **Collation support is limited** for locale-specific string comparison — test before cutover
- **`$regex` flags `x` (extended) and `s` (dotAll) not supported** — remove them
- **Transaction scope has limits** on collection and operation counts — test complex multi-collection transactions

## Index restore — skipping incompatibles

```bash
# Dry run first
python3 amazon-documentdb-tools/index-tool/migrationtools/documentdb_index_tool.py \
  --restore-indexes --skip-incompatible --dry-run \
  --dir amazon-documentdb-tools/index-export \
  --uri "mongodb://admin:<pw>@<docdb-endpoint>:27017/?tls=true&tlsCAFile=global-bundle.pem&replicaSet=rs0&retryWrites=false"

# Actual restore
python3 amazon-documentdb-tools/index-tool/migrationtools/documentdb_index_tool.py \
  --restore-indexes --skip-incompatible \
  --dir amazon-documentdb-tools/index-export \
  --uri "mongodb://admin:<pw>@<docdb-endpoint>:27017/?tls=true&tlsCAFile=global-bundle.pem&replicaSet=rs0&retryWrites=false"
```

After restore, manually recreate the skipped indexes using the DocumentDB-supported equivalents above.
