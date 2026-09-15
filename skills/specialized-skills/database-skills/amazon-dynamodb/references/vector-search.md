# Vector indexes and `SearchVectors`

DynamoDB supports native vector similarity search. A **vector index** is a third index type
alongside GSIs and LSIs: you declare it on `CreateTable` or `UpdateTable`, store embeddings as
an attribute on your items, and query it with the `SearchVectors` API using approximate
nearest neighbour (ANN) search. The vectors live on the same items as your operational data —
there is no second datastore and no replication pipeline.

Read this file when a design involves semantic similarity, RAG retrieval, recommendations,
AI-agent memory, or anomaly detection over data in DynamoDB. Skip it otherwise.

Every error string quoted below is reproduced verbatim from the service, so you can match on
it when diagnosing.

## What belongs here, and what does not

Vector search changed where *semantic* similarity belongs. It changed nothing about lexical
search. When a request bundles several kinds of "search," split it:

| Requirement | Where it goes |
|---|---|
| Semantic / "find similar" / "more like this" / RAG retrieval | **Vector index on the DynamoDB table** |
| Full-text, keyword, typo-tolerant / fuzzy matching, faceting, aggregations | Zero-ETL to Amazon OpenSearch Service (Integration #8) |
| Geospatial / radius search | Zero-ETL to Amazon OpenSearch Service |
| SQL analytics and BI | Zero-ETL to Amazon Redshift |

Do **not** route lexical or geo search to a vector index — ANN over embeddings does not do
substring, prefix or edit-distance matching. A workload needing both semantic and lexical
search legitimately uses both systems.

## Requirements and limits

- **On-demand capacity is mandatory.** Vector indexes are not supported on provisioned
  tables. A provisioned table must be switched to `PAY_PER_REQUEST` first — and note the
  24-hour capacity-mode cooldown (Fact #3).
- **A minimum SDK/CLI version applies.** The operations ship in **botocore/boto3 ≥ 1.43.64**
  and **AWS CLI v2 ≥ 2.36.16**. Below those versions the operations are absent from the client
  entirely: `aws dynamodb search-vectors` fails with `Found invalid choice`, and
  `hasattr(client, "search_vectors")` is `False`. Prefer that `hasattr` probe over a version
  comparison — it tests the thing you actually need and cannot go stale. **A stale SDK is not
  evidence the feature does not exist** — check before concluding anything, and tell the user
  to upgrade rather than reporting the feature as unavailable.
- Up to **5 vector indexes per table**. Maximum **4,096 dimensions**. `TopK` must be
  **1–100**. At most **one** `HASH` search-schema element per index, and up to **18** inline
  filters. Responses cap at 16 MB with **no pagination**. These values are subject to change and
  quotas of this kind generally rise rather than fall, so treat them as the design envelope to
  stay inside, not as a fact to quote back to a user who is near a limit — confirm the current
  figure in AWS Service Quotas or the DynamoDB developer guide before telling anyone their design
  is impossible.
- **One online index operation at a time per table**, shared with GSI creation. Two `Create`
  actions in a single `UpdateTable` fail with `LimitExceededException: Subscriber limit
  exceeded: Only 1 online index can be created or deleted simultaneously per table`.
- `Query`, `Scan`, PartiQL and DAX do **not** work against a vector index. `Query` is
  rejected with `ValidationException: Query operation not supported on this index type.`
- Vectors are stored in the index at 32-bit float (f32) precision. Higher-precision values
  are accepted and lose precision on the way into the index.

## Creating an index

Every attribute named in `SearchSchema` must **also** appear in the table's
`AttributeDefinitions`, exactly as a GSI key attribute must. Omitting it fails with
`ValidationException: One or more parameter values were invalid: One element in SearchSchema
is not defined in attribute definitions`.

On a new table, use `CreateTable` with `--vector-indexes`:

```bash
aws dynamodb create-table \
    --table-name Products \
    --attribute-definitions AttributeName=ProductId,AttributeType=S \
                            AttributeName=Category,AttributeType=S \
                            AttributeName=Brand,AttributeType=S \
    --key-schema AttributeName=ProductId,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --vector-indexes '[{
        "IndexName": "ProductEmbeddingIndex",
        "VectorAttribute": {"AttributeName": "Embedding"},
        "SearchSchema": [
            {"AttributeName": "Category", "SearchSchemaElementType": "HASH"},
            {"AttributeName": "Brand",    "SearchSchemaElementType": "INLINE_FILTER"}
        ],
        "Projection": {"ProjectionType": "INCLUDE", "NonKeyAttributes": ["Title"]},
        "Dimensions": 1024,
        "DistanceFunction": "COSINE"
    }]'
```

On an existing table, use `UpdateTable` with `--vector-index-updates`:

```bash
aws dynamodb update-table \
    --table-name Products \
    --vector-index-updates '[{"Create": {
        "IndexName": "ProductEmbeddingIndex",
        "VectorAttribute": {"AttributeName": "Embedding"},
        "Projection": {"ProjectionType": "ALL"},
        "Dimensions": 1024,
        "DistanceFunction": "COSINE"
    }}]'
```

Delete with `--vector-index-updates '[{"Delete": {"IndexName": "ProductEmbeddingIndex"}}]'`.
Deleting an index does not touch the base table or its items. A vector index is removed with
its base table, so a table teardown needs no separate index step.

`VectorAttribute` is an **object** carrying `AttributeName`, not a bare string. The distance
function key is `DistanceFunction`. There is no `VectorIndexConfig`, no `VectorAttributeName`,
no `DistanceMetric`, and no way to configure a vector index through a GSI.

### SearchSchema: the partition key is a scaling decision

A `HASH` search-schema element partitions the index so each `SearchVectors` call examines
only one partition-key value's vectors. That lowers latency and cost and scales throughput
horizontally — the per-partition-key limits (1 GBps search, 10 MBps write) multiply across
distinct values. Choose low-to-medium cardinality that matches how you query: a tenant id, a
category, a region. Avoid a unique per-item id (each partition has no neighbours, so recall
collapses) and avoid a boolean (no spread).

If you define a `HASH` element you **must** supply its value on every search. Omitting it
fails with `ValidationException: SearchConditionExpression must be provided when SearchSchema
has a HASH key`. Defining no `SearchSchema` at all is simpler and needs no
`SearchConditionExpression`, but every search then examines the whole index.

`INLINE_FILTER` elements are optional at search time and are filtered at the storage layer.

## Waiting for the index — get this right or your code is environment-dependent

The correct readiness predicate is **`IndexStatus == "ACTIVE"` and `Backfilling` is not
true**. There is no `BACKFILLING` index status value.

Both obvious shortcuts are wrong, because the two creation paths report `Backfilling`
differently:

| Wait condition | Inline `CreateTable` | `UpdateTable` on existing data |
|---|---|---|
| "until the `Backfilling` key disappears" | **wrong** — already absent while still `CREATING` | works |
| "until `Backfilling == false`" | works by accident | **wrong** — true immediately, minutes early |
| **`IndexStatus == ACTIVE and not Backfilling`** | correct | correct |

Searching too early fails with `ValidationException: Cannot search backfilling vector index:
<indexName>`.

**Backfill duration is driven by index construction, not item count.** Adding an index to a
table holding six items took **8m33s** in testing, against **20s** for an inline
`CreateTable` on a new table. Poll; do not assume a small table is quick.

**`ACTIVE` is not sufficient on its own.** `SearchVectors` is served by a dedicated search
endpoint, separate from the one serving `DescribeTable`, and it can lag briefly after the
index reports `ACTIVE`. During that window searches fail with `ValidationException: The table
does not have the specified index: <indexName>` — the *same message* you get for a genuinely
wrong index name. Treat a `ValidationException` on the first searches as **retryable** and
take the first successful `SearchVectors` response as the real readiness signal. Code that
searches immediately after observing `ACTIVE` works in one account and fails in another.

## Writing vectors

Store the embedding as a **list (`L`) of numbers (`N`)** on the item, written with the
ordinary `PutItem` / `UpdateItem` / `BatchWriteItem` / `TransactWriteItems` APIs. Because a
vector is long, write it from a file rather than inline on the command line.

| Condition | Behaviour |
|---|---|
| Vector length ≠ index `Dimensions` | Rejected: `ValidationException: ... Invalid size for parameter Embedding, Expected: 1024, Actual: 512. IndexName: ...` |
| Vector sent as a Number Set (`NS`) instead of `L` | Rejected, but with a **misleading** message: `ValidationException: Input collection contains duplicates` — the set collapsed repeated values. Nothing mentions the type mistake. |
| Search-schema `HASH` attribute missing from the item | **Write succeeds. Item is silently excluded from the index.** |
| Search-schema `HASH` attribute wrong type or empty string | Rejected |
| `INLINE_FILTER` attribute missing | Write succeeds and the item **is** indexed |
| Vector attribute deleted from an item | Index entry removed |

### Silent de-indexing — the sharpest edge here

If a vector index defines a `HASH` search-schema element, an item written **without** that
attribute — or with it later removed via `UpdateItem ... REMOVE` — is accepted on the base
table with no error and is never replicated into the index. It will not appear in
`SearchVectors` results even though the item and its embedding are intact and `GetItem`
returns them normally.

This is expected behaviour, not a defect — it is the same semantics as a sparse GSI, where an
item lacking the index key simply is not in the index. It bites harder here because the
attribute is usually one every item is *supposed* to have, and the symptom is retrieval
quality quietly degrading rather than a visible error.

**Symptom signature.** Items absent from similarity search; `GetItem` returns them; embeddings
valid; `IndexStatus` `ACTIVE`; nothing in CloudWatch; no failed writes. When you see that
combination, go straight to "which items are missing the search-schema partition key" — not
to corruption, not to replication lag.

**Fix.** Re-write the affected items with the attribute restored, **preserving the existing
embedding**. Re-creating an item without its vector leaves it permanently unsearchable, which
is worse than the original bug. Do **not** drop and recreate the index: backfill re-derives
from the same base-table items, so nothing changes.

**Prevent it on the write path.** Treat a search-schema `HASH` attribute as mandatory on every
item that must be searchable — guard it at write time in the same spirit as the
`attribute_exists` / `attribute_not_exists` guards in Patterns #2 — or define no partition key
at all if you cannot guarantee the attribute is always present.

### Embeddings go stale silently

DynamoDB does not recompute embeddings. Change the source content and the stored vector still
reflects the old text, so the index keeps returning matches against content that no longer
exists. Regenerate the embedding with the same model and write it back whenever the source
changes — capturing content changes with DynamoDB Streams and re-embedding downstream is the
usual shape (Integration #1 applies: make that consumer idempotent).

## Searching

```bash
aws dynamodb search-vectors \
    --table-name Products \
    --index-name ProductEmbeddingIndex \
    --search-vector file://query-vector.json \
    --top-k 10 \
    --search-condition-expression "Category = :cat AND Brand = :brand" \
    --expression-attribute-values '{":cat": {"S": "Electronics"}, ":brand": {"S": "Acme"}}' \
    --projection-expression "ProductId, Title"
```

`SearchVector` is a **plain JSON array** of number objects — `[{"N": "0.1234"}, ...]` — not
wrapped in a DynamoDB `L`. The `L` wrapper is only for the stored item attribute. Wrapping it
is rejected client-side before any API call: `Invalid type for parameter SearchVector ...
valid types: <class 'list'>, <class 'tuple'>`.

The query vector must come from the **same embedding model** and have the same dimensionality
as the index. A mismatch fails with `ValidationException: Input search vector dimension 3 does
not match vector index dimension 4`.

`SearchConditionExpression` supports the **equality operator only**. Comparison, range and
set-membership operators (`<>`, `<`, `<=`, `>`, `>=`, `IN`) are rejected with
`ValidationException: Invalid SearchConditionExpression: Invalid comparator used in
SearchConditionExpression`. There is no `FilterExpression` or `Filter` parameter on
`SearchVectors`.

`TopK` outside 1–100 is rejected — above the range server-side (`Provided TopK value '101' is
out of valid range. The value must be between 1 and 100 inclusive`), below it client-side.

### What comes back

Results arrive sorted most-similar-first, each with the projected attributes and a `Score`.
Two things surprise people:

- **The vector attribute is excluded by default**, even under `ProjectionType: ALL`. Request
  it explicitly with `ProjectionExpression` if you want it — and note it is large.
- **Only attributes projected into the index can be returned.** Asking for one that is not
  projected is **silently ignored**: no error, the attribute is simply absent from the
  result. If you need more attributes, either recreate the index with a wider projection or
  hydrate from the base table with `GetItem`/`BatchGetItem` after searching.

## Distance functions and score direction

| Function | Direction | Notes |
|---|---|---|
| `COSINE` | **Lower is more similar** (0 identical → 2 opposite) | Ignores magnitude. The safe default for text embeddings. |
| `EUCLIDEAN` | **Lower is more similar** | Sensitive to magnitude. Good for near-duplicate detection, image/audio embeddings. |
| `DOT_PRODUCT` | **Higher is more similar** | Sensitive to magnitude, and **scores can be negative**. |

Do not assume "higher score is a better match" — that is true only for `DOT_PRODUCT`, and it
is the reverse for the other two. Do not assume scores are non-negative when applying a
threshold. The simplest safe approach is to rely on the returned ordering rather than
re-sorting by raw score.

The choice is a real ranking decision, not a formality. Measured on identical data with the
identical query vector `[1,0,0,0]`, the stored vector `[10,0,0,0]` ranks **tied-first under
`COSINE` (0.0)** and **last under `EUCLIDEAN` (9.0)** — because `COSINE` ignores its magnitude
and `EUCLIDEAN` does not. If you use `DOT_PRODUCT` and want direction-based similarity,
normalise embeddings to unit length first; normalised, it ranks the same as `COSINE`.

## What you cannot change after creation

`Dimensions`, `DistanceFunction`, `SearchSchema` (partition key and inline filters) and
`Projection` are all fixed when the index is created. `UpdateTable` cannot alter any of them.
Changing one means creating a **new** index under a new name, waiting for it to backfill,
cutting reads over, then deleting the old one — the same additive-migration shape as a GSI
key change (Fact #9). Because only one index operation runs at a time per table, this is
sequential and slow.

Choose the embedding model **before** creating the index, since the model fixes the
dimensionality. Validate the distance function against a representative dataset first. You can
run up to 5 indexes on one table, which is the supported way to A/B two embedding models over
the same data: store each model's vectors in a different attribute, index each, and compare
relevance before migrating.

## Security

IAM controls vector operations as follows:

- Creating/deleting an index: `dynamodb:CreateTable` or `dynamodb:UpdateTable` on the table.
- Searching: **`dynamodb:SearchVectors` on the index resource**, ARN shape
  `arn:aws:dynamodb:<region>:<account-id>:table/<table-name>/index/<index-name>`.
- Writing items with vectors: the ordinary write permissions. Nothing extra.

**Fine-grained access control does not apply to `SearchVectors`.** The `dynamodb:` condition
keys that enforce FGAC — `dynamodb:LeadingKeys`, `dynamodb:Attributes`, `dynamodb:Select` —
are absent from the `SearchVectors` request context. A policy statement whose `Condition`
references one of them therefore **does not match**, and the result is denial rather than a
grant. Adding `dynamodb:SearchVectors` to an existing FGAC-conditioned statement silently
breaks vector search while the statement's other actions keep working normally — which makes
it look like a broken index rather than a policy problem.

Grant `dynamodb:SearchVectors` in **its own statement**, scoped to the index ARN, with no
`dynamodb:` FGAC conditions attached:

```json
{
  "Effect": "Allow",
  "Action": "dynamodb:SearchVectors",
  "Resource": "arn:aws:dynamodb:us-east-1:<account-id>:table/Products/index/ProductEmbeddingIndex",
  "Condition": {
    "StringEquals": { "aws:PrincipalOrgID": "o-XXXXXXXXXX" }
  }
}
```

Note what that `Condition` is and is not. `aws:PrincipalOrgID` is a **global** condition key, so it
evaluates normally and the statement still matches. The keys that must stay out of this statement are
the `dynamodb:` FGAC ones above. Scope the `Resource` to the specific index rather than
`.../index/*` — a wildcard grants search over every index on the table, including ones added later.

**"No `dynamodb:` conditions" does not mean "no conditions".** Only the FGAC keys are missing
from the request context; the standard global condition keys still evaluate normally and should
be used, particularly on a multi-tenant index. `aws:PrincipalOrgID` and `aws:PrincipalTag/*`
restrict *who* may search, `aws:SourceVpce` and `aws:SourceIp` restrict *from where*, and
`aws:RequestedRegion` bounds the region. What none of them can do is restrict *which
partition-key values* a permitted principal reaches — that is the gap, and it is narrower than
"this statement cannot be conditioned at all".

**A search-schema partition key is not a security boundary.** Scoping searches to one tenant's
partition-key value is a data-locality and performance optimisation. Any principal holding
`dynamodb:SearchVectors` on the index can search any partition-key value, and because FGAC
condition keys do not apply you cannot restrict which values they reach at the IAM layer. If
the workload requires strict tenant isolation at the data layer, use **separate tables or
separate indexes with distinct IAM grants per tenant**. An application layer that injects the
caller's tenant value and never accepts it from the client is a useful complement, not a
substitute.

**Log the searches, because IAM cannot gate them.** Preventive controls have a known hole
here, so the detective control carries more weight than it normally would: enable **CloudTrail
data-event logging** on any table whose vector index serves more than one tenant. It is the
only record of *which* partition-key value each principal searched, which is exactly the
dimension IAM cannot constrain — so without it a cross-tenant search caused by a compromised
principal or a bug in the application-layer injection leaves no trace at all. Pair it with a
CloudWatch alarm on `VectorSearchRequestBytes` per principal: a caller enumerating other
tenants' partitions shows up as a volume anomaly before it shows up anywhere else. Encrypt the
trail's S3 bucket and any log group with a customer-managed KMS key when the logged
partition-key values are themselves sensitive.

**Rate-limit `SearchVectors` per principal at the application layer.** Because every call returns
similarity scores, a caller with legitimate search access can probe the embedding space of a
partition through repeated targeted queries and infer relationships it was never shown directly.
That makes the throttle a **confidentiality control as well as a cost one** — which matters,
because a throttle filed under "cost" gets dropped from any design where cost is not a concern,
and multi-tenant indexes holding valuable content are exactly where it should not be.

Encryption at rest is inherited from the base table — AWS-owned, AWS-managed or a customer
managed KMS key. There is no separate vector index encryption setting.

**Treat the embeddings themselves as sensitive data.** An embedding is a lossy but real
encoding of the content it was derived from, and similarity results leak information about
neighbouring items even when no raw text is returned — an attacker with search access can
learn that two records are semantically close without ever reading either. Two consequences
worth acting on: the vector attribute being excluded from results by default is a **security
default, not just a bandwidth one**, so do not add it to `ProjectionExpression` without a
reason; and anything that logs a full item — Lambda consumers, debug traces, DLQ payloads —
should be treated as handling sensitive data, with KMS encryption on the log group.

## Cost

Vector index usage is metered in **bytes**, separately from base-table RCU/WCU, across three
dimensions. Rates below are us-east-1 Standard; confirm against the DynamoDB pricing page for
your region before quoting a figure.

| Dimension | Usage type | Rate | Derivable from a design? |
|---|---|---|---|
| Index storage | rolls into table storage | $0.25 / GB-month | **Yes** — `dimensions × 4 bytes × indexed items`, plus the projected-attribute share |
| Writes | `VectorWriteRequest` | $0.52 / GB | **Yes** — per write touching the vector attribute |
| Searches | `VectorSearch` | $0.002 / GB | **No** — bills on bytes *examined inside the index* |

Standard-IA is 125% on both request dimensions and 40% on storage.

Two things make search cost unmodellable from a design alone: it scales with the volume of
vector data the search *examines*, which depends on index size and partition layout rather
than on your query vector; and **there is a 1 KB minimum per request** for both writes and
searches. That minimum is per *request*, not per index — one write touching several of a
table's indexes incurs it once. It also means low-dimension vectors do not meter
proportionally lower: a 4-dimension vector holds 16 bytes of f32 data and still meters at
1,024 bytes.

So do **not** estimate search cost from dimension count. Get `VectorSearchRequestBytes` and
`VectorWriteRequestBytes` from `ReturnConsumedCapacity` on your own workload, or from the
CloudWatch metrics of the same names (dimensioned by `TableName` and `VectorIndexName`), and
validate against a representative dataset before sizing.

## Interaction with other DynamoDB features

- **Global tables** — the index definition replicates automatically to a new replica Region;
  you do not create it there. Replication into the index is asynchronous **even under
  multi-region strong consistency (MRSC)**, so a vector written in one Region may not appear
  in another Region's search results yet. Each replica's index backfills independently. ANN
  means ranking can differ slightly between Regions over identical data.
- **Streams** — work normally and are the recommended way to trigger re-embedding.
- **TTL** — an expired item's index entry is removed like any delete.
- **PITR / backups** — the index definition is restored and rebuilt from base-table data, so
  it backfills before it is searchable.
- **Export / import** — exports contain the vector attributes; on import, define the index in
  the import request as you would for `CreateTable`.
- **DAX** — does not support `SearchVectors`. Send searches directly to DynamoDB.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `SearchConditionExpression must be provided when SearchSchema has a HASH key` | Index defines a partition key; the search omitted its value | Add the equality condition and a matching `ExpressionAttributeValues` entry |
| `One element in SearchSchema is not defined in attribute definitions` | Search-schema attribute not in `AttributeDefinitions` | Declare it with its type, as for a GSI key |
| `Invalid comparator used in SearchConditionExpression` | An operator other than `=` | Rewrite with equality only |
| `Provided TopK value '<n>' is out of valid range` | `TopK` outside 1–100 | Clamp to 1–100 |
| `Cannot search backfilling vector index: <name>` | Index still `CREATING` / backfilling | Wait for `ACTIVE and not Backfilling`, then retry |
| `The table does not have the specified index: <name>` **while `DescribeTable` says `ACTIVE`** | Search endpoint lagging `ACTIVE` | Retry — treat as transient right after creation. Only suspect a typo if it persists |
| `Input search vector dimension N does not match vector index dimension M` | Query vector wrong length | Use the same model and dimensionality as the index |
| `Invalid size for parameter <attr>, Expected: N, Actual: M` | Stored vector wrong length | Match the index `Dimensions` |
| `Input collection contains duplicates` on a write | Vector sent as a Number Set (`NS`); duplicates collapsed | Send it as a List (`L`) of Numbers (`N`) |
| `Query`/`Scan` rejected: `... operation not supported on this index type` | Wrong read API | Use `SearchVectors` |
| Item absent from search, `GetItem` fine, no errors | Missing search-schema `HASH` attribute — silent de-indexing | Re-write the item with the attribute, preserving its embedding |
| An attribute missing from results, no error | Not projected into the index | Widen the projection (new index) or hydrate from the base table |
| Ranking looks inverted; threshold checks misbehave | Score direction assumed wrong, or negative `DOT_PRODUCT` scores | Rely on the returned order; see the distance-function table |
| `AccessDenied` on search while other actions work | `dynamodb:SearchVectors` sits in an FGAC-conditioned statement | Move it to its own condition-free statement scoped to the index ARN |
| `aws dynamodb search-vectors` → `Found invalid choice` | CLI older than 2.36.16 | Upgrade the CLI; the feature exists |
