# Cost analysis — self-managed vector store vs. Managed KB

The cost procedure for the Discover phase's optional cost analysis and for any direct cost question in
any phase. It is a **fixed sequence of steps, run in order**: scope → input gate → inputs → measurement →
plausibility → rates → script → output table → verdict. Each step says what it needs from the previous
one. Do not skip to a number; the inputs decide what can be said. Every read here is read-only
(`Get*`/`List*`/`Describe*`/`BatchGet*`) and pre-approved: display each labeled READ-ONLY and run it
without waiting. Read any public AWS page per
[safety-and-iam](references/bedrock-kb-migration/safety-and-iam.md).

**This file carries no prices, quotas or capacity figures.** Each one is read live, in this conversation,
from the page or API named next to it. If a fetch fails or a page comes back cut off, say the figure is
unavailable and give the link; never fill it from memory.

## Contents

Procedure (run in order):

- [Step 0. Scope and the cost gate](#step-0-scope-and-the-cost-gate)
- [Step 1. The input gate](#step-1-the-input-gate)
- [Step 2. Gather the inputs](#step-2-gather-the-inputs)
- [Step 3. Measure what can be measured](#step-3-measure-what-can-be-measured)
- [Step 4. Plausibility check](#step-4-plausibility-check)
- [Step 5. Fetch every rate live](#step-5-fetch-every-rate-live)
- [Step 6. Compute with a script](#step-6-compute-with-a-script)
- [Step 7. The required output](#step-7-the-required-output)
- [Step 8. Verdict](#step-8-verdict)
- [Step 9. When an input is missing](#step-9-when-an-input-is-missing)

Reference (not steps):

- [A. How the two pricing models differ](#a-how-the-two-pricing-models-differ)
- [B. Modeling errors seen in practice](#b-modeling-errors-seen-in-practice)
- [C. Price List field map and fallbacks](#c-price-list-field-map-and-fallbacks)
- [D. Read-only command quick reference](#d-read-only-command-quick-reference)
- [E. Output record](#e-output-record)
- [F. Procedural mistakes](#f-procedural-mistakes)

## Step 0. Scope and the cost gate

**The gate.** The unprompted cost analysis is **asked exactly once, at the Identify phase**, and is
**opt-out, not automatic**. Enabling it is the recommended answer, but it still needs an **explicit yes**,
never inferred from the request or from the fact that the user asked about migration.

- **enabled** — the Discover phase runs Steps 1-9 for each KB.
- **declined** — no cost probe runs. Record one declined outcome per KB ([E](#e-output-record)); it is an
  absence of work, not a finding about the store.

The gate governs only the *unprompted* run. A user who declined and later asks a cost question **has
requested it**: answer it in full with Steps 1-9. The gate can be re-enabled later.

**Scope by vector store.** Decide it from the source KB's `storageConfiguration.type` and say it once:

| Source store | Comparison | Formula block used in Step 6 |
|---|---|---|
| `OPENSEARCH_SERVERLESS` | two-sided | self-managed on OpenSearch Serverless + Managed |
| `S3_VECTORS` | two-sided | self-managed on S3 Vectors + Managed |
| any other store (Pinecone, Redis, Aurora pgvector, MongoDB, Neptune, provisioned OpenSearch) | one-sided | Managed only; say the self-managed side is not modeled here, carry over none of the OpenSearch Serverless reasoning, `in_scope: false` |

## Step 1. The input gate

**No dollar figure, range, break-even or statement of which side costs less is given as this customer's
cost until every input marked REQUIRED in Step 2 is recorded as measured or customer-supplied, and the set
has passed Step 4.** Before that, two kinds of figure are allowed, each labelled in the reply itself and
computed by the script on rates fetched in this conversation:

- **On numbers the customer stated**, labelled as resting on them ("if the search OCUs you gave are a
  30-day average, ..."), while you ask them to confirm those numbers (in that reply or already asked).
- **What-if rows at values you pick**, labelled as illustrations and not as the customer's figures.

A verdict drawn from either is stated as conditional on those figures, never flat. Still never: a value
you chose presented as theirs, a projected peak presented as traffic, a rate not fetched live, an OCU count
used in a total before it passes Step 4, or a shared pool's bill charged to one KB (Step 3.1).

**One exception: a single volume missing.** When every other REQUIRED input is measured or
customer-supplied and has passed Step 4, and only one volume is missing (most often retrieval calls per
month, row 9), do not stop at "no verdict". The script computes the volume at which the two totals are
equal, from the customer's own figures, and Step 8 turns it into a recommendation and one question. That
threshold is not an estimate of their traffic; it asks them which side of it they are on. The exception
applies only when the self-managed total belongs to this KB alone. On a shared OCU pool (Step 3.1), the
shared-pool rule in Step 8 decides instead.

Until the gate is passed (and outside that exception), the answer to a cost question gives these three,
plus any labelled figures allowed above:

1. how the two pricing models differ ([A](#a-how-the-two-pricing-models-differ)), each point from the page
   named there, fetched in this conversation, with its link;
2. the Step 2 list of inputs still missing, asked for in one message;
3. the offer to measure them now with the read-only calls in Step 3.

Never estimate the customer's traffic from corpus size or document count, never present a volume you
chose as theirs, and never tell them flatly that either side will cost them less: not Managed, and not
self-managed.
When their setup is one where self-managed can cost less (for example a collection group with a zero
minimum that sits idle much of the day), say that it is possible, that their own numbers decide it, and
offer to measure them now (for a zero-minimum group, the hourly series in Step 3.2). Always make that
offer. If this session's credentials do not reach the account the KB is in, make it conditional: name the
read-only calls you would run and offer to run them once the customer provides a read-only profile for
that account. Say also what Managed includes that a self-managed bill does not show (Step 7, item 5).

## Step 2. Gather the inputs

One checklist. Collect every row, each recorded as **measured** (metric, dimension set and window),
**customer-supplied** (and where they got it), or **unavailable** (and why). Anything the customer
supplies is customer-supplied, never measured.

| # | Input | Side | Needed for | Where it comes from |
|---|---|---|---|---|
| 1 | Collection architecture (Classic, or a NextGen collection group), its capacity settings, `standbyReplicas`, KMS key, how many collections share its OCU pool | self-managed | REQUIRED (every self-managed figure is read against it) | Step 3.1 |
| 2 | Search OCU, 30-day Average and Maximum | self-managed | REQUIRED for the self-managed total | Step 3.2, or the bill line (3.5) |
| 3 | Indexing OCU, 30-day Average and Maximum | self-managed | REQUIRED for the self-managed total | Step 3.2, or the bill line (3.5) |
| 4 | Vector-acceleration OCU | self-managed | when the metric reports | Step 3.2 |
| 5 | Indexed storage GB (and hot storage GB on NextGen) | self-managed | REQUIRED for the self-managed total | Step 3.3 |
| 6 | Raw corpus GB | Managed | REQUIRED for the Managed total | Step 3.3, or the customer |
| 7 | **Vector count** of the KB's index | self-managed sizing | REQUIRED for Step 4 | Step 3.4 |
| 8 | **Embedding model and dimension** | self-managed sizing | REQUIRED for Step 4 | Step 3.4 |
| 9 | Retrieval calls per month, and the source of the number | Managed | REQUIRED for the Managed total | Step 3.6, app telemetry, or the customer |
| 10 | Whether agentic retrieval is wanted; expected agentic calls per month | Managed | when wanted | the customer |
| 11 | Embedding token volume per ingest, and how often the corpus is re-ingested | self-managed (Managed only with a custom model) | when known; omitted from **both** sides when unknown | ingest bill, Cost Explorer model line, or the customer |
| 12 | Parser in use (default, foundation-model, or Bedrock Data Automation) and its volume (tokens or pages) | self-managed | when not the default parser | `GetDataSource` parsing configuration; the customer |
| 13 | Reranker in use and queries per month | self-managed | when implemented | the customer, app telemetry |
| 14 | Whether a foundation model generates answers, which, and its token volume | both, symmetric | when known; omitted from **both** sides when unknown | the customer |
| 15 | Corpus growth per month and the horizon to compare over | both | optional | the customer |

**The one rule for a stated OCU count.** A number of OCUs that the customer states, or that a
collection's capacity settings show, counts as usage **only if** (a) it is a 30-day CloudWatch Average
or a line on the bill, **and** (b) it passes Step 4. Otherwise it is a floor or a setting: record it as
`capacity_setting`, do not price it as usage, and ask for the series (3.2) or the bill (3.5). A figure on
it that passed Step 4 is allowed only labelled as resting on their stated count, with that ask (Step 1).
"We run one search OCU and one indexing OCU" is a configuration statement until the series or the bill
confirms it.

**`S3_VECTORS` source.** Rows 1-5 do not apply; there are no OCUs. In their place these are REQUIRED for
the self-managed total: logical vector storage GB **including keys and metadata** (the bill's S3 Vectors
storage line, or the customer's figure; vector count × dimension × bytes per dimension is only the
vector-data part, a floor, not this input); write (PUT) volume per month; query requests per month and the
data they process and return, as the S3 pricing page defines them (the bill, or the customer). A floor, a
bound or a range that stands in for one of these is not the input: record it `unavailable`, price only the
lines whose inputs you have, and omit the total (Step 9).

Ask for everything still missing in **one message**, grouped Capacity / Data / Traffic / Models / Bill,
only the unanswered rows, in plain words. Rows 2, 3, 5, 6 and 9 are enough for a defensible comparison
once rows 7 and 8 have passed Step 4; lead with those.

## Step 3. Measure what can be measured

Run in this order. Every call is READ-ONLY. The Region is the KB's Region unless stated.

### 3.1 Collection config: architecture, redundancy, sharing scope

```bash
aws opensearchserverless batch-get-collection --ids <COLLECTION_ID> --region <REGION> --profile <READ_ONLY_PROFILE>
aws opensearchserverless list-collections   --region <REGION> --profile <READ_ONLY_PROFILE>   # page with --next-token until it is absent; count only the full list
# If collectionGroupName is set:
aws opensearchserverless batch-get-collection-group --names <COLLECTION_GROUP_NAME> --region <REGION> --profile <READ_ONLY_PROFILE>
```

Capture `type` (expect `VECTORSEARCH`), `standbyReplicas`, `kmsKeyArn`, `collectionGroupName`.

- **Collection group (NextGen).** The collection runs on the group's OCUs; read the group's
  `capacityLimits` (minimum and maximum search and indexing OCUs). Collections in one group share its
  OCUs whatever their KMS key. A group with a zero minimum can scale compute to zero when the whole group
  is idle ([collection groups](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-collection-groups.html),
  [scale to zero](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-scale-to-zero.html)).
- **Classic (no group).** Capacity is set at the account level and OCUs are shared among collections that
  use the same KMS key ([scaling](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-scaling.html)).
  Read the minimum that applies from that page and the pricing page in this conversation.
- **`standbyReplicas: DISABLED`** is a dev-test redundancy setting. If a customer's figure assumed it for a
  production workload, flag that rather than adopting it.
- **Shared pool: state it, never divide it.** `AWS/AOSS` never emits OCU per KB. The OCU figures below are
  the pool's total; report the total, name how many collections share it, and never invent a per-KB share.
  Migrating one KB off a shared pool may free almost nothing until the pool empties, so plan the pool's KBs
  together. When other KBs share the pool, the comparison is run for the **whole pool** (every KB on it
  moved together: the sum of their Managed lines against the pool's total) as well as for this KB alone
  (its Managed lines are added while the pool's cost stays until its last collection leaves). Ask for the
  other KBs' raw GB and retrieval volume in the same Step 2 message.

### 3.2 OCU series, search **and** indexing, over at least 30 days

Resolve the scope first: `aws cloudwatch list-metrics --namespace AWS/AOSS --metric-name SearchOCU`.
`SearchOCU` and `IndexingOCU` are each published in two dimension sets that *partition* the account: a
group scope (`ClientId`, `CollectionGroupId`, `CollectionGroupName`) covering that group's OCUs, and an
account scope (`ClientId`) covering **only collections in no group**. A grouped collection is invisible to
the account scope.

```bash
# Group scope. Indexing: same call with --metric-name IndexingOCU.
# Account scope (ungrouped collections only): drop the two CollectionGroup dimensions.
aws cloudwatch get-metric-statistics --namespace AWS/AOSS --metric-name SearchOCU \
  --dimensions Name=ClientId,Value=<ACCOUNT_ID> \
               Name=CollectionGroupId,Value=<COLLECTION_GROUP_ID> \
               Name=CollectionGroupName,Value=<COLLECTION_GROUP_NAME> \
  --start-time <ISO8601_30D_AGO> --end-time <ISO8601_NOW> \
  --period 86400 --statistics Average Maximum --region <REGION> --profile <READ_ONLY_PROFILE>
```

- CloudWatch matches dimension sets exactly: a partial set returns no datapoints, not an aggregate. An
  empty account-scope result on a grouped collection means the wrong scope, **not** zero usage.
- `Average` is the billed figure; `Maximum` shows whether capacity sits flat or bursts. Never `Sum` at a
  daily period: OCU is a gauge, and summing per-minute samples overstates it about 1,440 times.
- **A zero-minimum collection group** (NextGen, minimum search OCU 0): a daily average does not show when
  the group is at zero. Read `SearchOCU` again over the same 30 days at `--period 3600` (`Average` and
  `Maximum`) and count the hours a day it sits at zero. A group that is active most hours is billed at its
  active OCUs, not near zero. How long the group takes to scale down after traffic stops is read from this
  series, never assumed.
- Zero datapoints on a new collection means metrics have not published yet: a note, not a zero.
- `VectorIndexBuildAccelerationOCU` (`ClientId`, `CollectionId`) is a third OCU line. If it reports,
  capture it; search plus indexing alone understates spend.

### 3.3 Storage: indexed bytes and raw corpus bytes are different numbers

`StorageUsedInS3` (and, on NextGen, `StorageUsedInHot`) is published per index with the compound set
`ClientId`, `CollectionId`, `CollectionName`, `IndexId`, `IndexName`, never at `ClientId` alone. Discover
the sets with `list-metrics --metric-name StorageUsedInS3 --dimensions Name=CollectionId,Value=<ID>`,
then query at a one-minute period (the metric is accurate only there) and take the latest value:

```bash
aws cloudwatch get-metric-statistics --namespace AWS/AOSS --metric-name StorageUsedInS3 \
  --dimensions Name=ClientId,Value=<ACCOUNT_ID> Name=CollectionId,Value=<COLLECTION_ID> \
               Name=CollectionName,Value=<COLLECTION_NAME> Name=IndexId,Value=<INDEX_ID> Name=IndexName,Value=<INDEX_NAME> \
  --start-time <ISO8601_1H_AGO> --end-time <ISO8601_NOW> --period 60 --statistics Maximum ...

# Raw corpus (what Managed bills for): sum over each S3 data source's inclusionPrefixes
aws s3api list-objects-v2 --bucket <BUCKET> --prefix <INCLUSION_PREFIX> --query 'sum(Contents[].Size)'
```

Record **both** and label which is which. Report the expansion ratio (indexed ÷ raw) on its own: vectors,
the graph, filterable metadata and any lexical index multiply raw bytes. Non-S3 connectors have no bucket
to sum; raw size comes from the customer. If indexed storage is unavailable, say so; raw size does not
stand in for it.

### 3.4 Vector count and embedding dimension

These two inputs size the self-managed side; raw GB does not. A Bedrock KB writes one document per chunk
into its index, so the index's document count is its vector count.

```bash
# Which index the KB writes to, and the embedding model and dimension it uses
aws bedrock-agent get-knowledge-base --knowledge-base-id <SOURCE_KB_ID> --region <REGION> --profile <READ_ONLY_PROFILE> \
  --query 'knowledgeBase.{index: storageConfiguration.opensearchServerlessConfiguration.vectorIndexName,
                          model: knowledgeBaseConfiguration.vectorKnowledgeBaseConfiguration.embeddingModelArn,
                          dims:  knowledgeBaseConfiguration.vectorKnowledgeBaseConfiguration.embeddingModelConfiguration.bedrockEmbeddingModelConfiguration.dimensions}'

# Vector count: SearchableDocuments for that index (same compound dimension set as 3.3; one-minute period, latest value)
aws cloudwatch list-metrics --namespace AWS/AOSS --metric-name SearchableDocuments --dimensions Name=CollectionId,Value=<COLLECTION_ID> ...
aws cloudwatch get-metric-statistics --namespace AWS/AOSS --metric-name SearchableDocuments \
  --dimensions <the full set returned for the KB's IndexName> --period 60 --statistics Maximum \
  --start-time <ISO8601_1H_AGO> --end-time <ISO8601_NOW> ...
```

- Use the KB's index only; other indexes in the collection are not this KB.
- If `dimensions` is absent, the model's default applies; read it from the model's page in this
  conversation and record the source.
- `S3_VECTORS` source: `aws s3vectors get-index --vector-bucket-name <B> --index-name <I>` gives the
  dimension; the vector count comes from the customer or their ingestion records.

### 3.5 The bill

Read the actual spend from Cost Explorer (READ-ONLY; endpoint `us-east-1` whatever the KB's Region; one
call per account, the API is charged and not real-time):

```bash
aws ce get-cost-and-usage --region us-east-1 --profile <READ_ONLY_PROFILE> \
  --time-period Start=<YYYY-MM-DD_30D_AGO>,End=<YYYY-MM-DD_TODAY> --granularity MONTHLY \
  --metrics UnblendedCost --group-by Type=DIMENSION,Key=USAGE_TYPE \
  --filter '{"Dimensions":{"Key":"SERVICE","Values":["Amazon OpenSearch Service"]}}'
```

- OpenSearch Serverless bills as **`Amazon OpenSearch Service`**. Keep only the KB Region's Serverless usage
  types (`<REGION_PREFIX>-SearchOCU`, `<REGION_PREFIX>-IndexingOCU`, `<REGION_PREFIX>-StorageUsedInS3ByteHour`,
  and `<REGION_PREFIX>-StorageUsedInHotByteHour` on NextGen); exclude provisioned-domain types
  (`ESInstance:*`, `ES:*-Storage`) and data transfer (`*-Bytes`).
- The figure is **account-level**, never per KB; report it with the collection count from 3.1.
- For the model lines (embedding, reranking, FM) repeat with `"Values":["Amazon Bedrock"]`; for an
  `S3_VECTORS` store repeat with `"Values":["Amazon Simple Storage Service"]` and keep the usage types that
  name vectors.

The bill is the real number. Prefer it over the derived OCU × rate figure and reconcile any large gap
rather than presenting both without comment.

### 3.6 Retrieval volume

Managed retrieval cost is set entirely by monthly call count. Prefer the source that exists; **never stand
up new telemetry** (a trail, a workgroup, a log pipeline) to size a migration. In order:

1. **The vended metric.** Bedrock publishes `Invocations` under `AWS/Bedrock/KnowledgeBases` when the
   KB's service role may call `cloudwatch:PutMetricData` on that namespace. Check first whether this KB
   publishes: `list-metrics --namespace AWS/Bedrock/KnowledgeBases`. Then:

   ```bash
   aws cloudwatch get-metric-statistics --namespace AWS/Bedrock/KnowledgeBases --metric-name Invocations \
     --dimensions Name=KnowledgeBaseId,Value=knowledge-base/<SOURCE_KB_ID> Name=Operation,Value=Retrieve \
     --start-time <ISO8601_30D_AGO> --end-time <ISO8601_NOW> --period 2592000 --statistics Sum \
     --region <REGION> --profile <READ_ONLY_PROFILE>
   ```

   The dimension value carries the `knowledge-base/` prefix. A KB with no series is either unqueried or
   not publishing, and the metric cannot tell you which. **When the series is empty, the reply must say
   all three, in so many words: the count is missing, not zero; the likely cause is that the KB's service
   role lacks `cloudwatch:PutMetricData` on `AWS/Bedrock/KnowledgeBases`; and if the customer adds that
   permission, counting starts from then on (calls made before it are not counted).** Saying only
   "missing, not zero" is not enough. Never add the permission yourself. Documented `Operation` values are
   `Retrieve` and `AgenticRetrieveStream`; ask about `RetrieveAndGenerate` separately.
2. **Application telemetry**: the calling service's request metrics or logs.
3. **The customer's own count** (a legitimate, common outcome). Record it as customer-supplied with their
   source; a forecast is labeled a forecast.
4. **Existing CloudTrail data events, only if already captured.** `Retrieve` is a `bedrock-agent-runtime`
   **data event**; `lookup-events` searches management events only and returns zero regardless of traffic
   ([CloudTrail for Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/logging-using-cloudtrail.html)).
   Count in the customer's existing event data store or query engine over 30 days; ask them to run it if
   the read-only profile cannot reach it.

Convert only what you were given: `monthly_calls = sustained_qps × 86,400 × 30`. Never substitute a
projected peak for measured volume.

## Step 4. Plausibility check

Run before any figure from Step 2 is used. Inputs: vector count (row 7), embedding dimension (row 8),
every OCU count that was stated or configured (row 1, and any customer statement), `standbyReplicas`.

1. **Fetch AWS's own capacity guidance in this conversation** and give the links: the OpenSearch
   Serverless [scaling page](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-scaling.html)
   (what one OCU provides and how OCUs scale with data and traffic), the
   [vector search page](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-vector-search.html),
   and the AWS post that gives the number of vectors one OCU handles at stated dimensions
   ([vector engine GA](https://aws.amazon.com/blogs/aws/vector-engine-for-amazon-opensearch-serverless-is-now-generally-available/)).
   If a page fails to load or the figure is not on it, say the check could not be completed and treat
   every stated OCU count as a floor.
2. **Read the vectors-per-OCU figure for the dimension nearest the KB's.** When AWS gives it only at a
   different dimension, scale it to the KB's dimension by the ratio of the two (vector memory grows with
   dimension), feed both the fetched figure and the ratio to the script, and say the result is an estimate.
   A different dimension is not a reason to skip the check. Read from the scaling page how
   OCUs divide between active and standby capacity when `standbyReplicas` is `ENABLED`, and compare
   against the active share. Then let the Step 6 script evaluate, with the fetched figure as an input:
   `stated_search_ocu_active × vectors_per_ocu_at_dimension ≥ vector_count`. Report the result as fits or
   does not fit, never as a price. If you still cannot complete the check, say why.
3. **Does not fit** → the stated capacity cannot hold this index. Say which three figures conflict (vector
   count, dimension, stated OCUs) and the fetched figure they conflict with, with its link. Drop the
   stated OCU count as a cost input, record it as `capacity_setting`, and ask for the 30-day series (3.2)
   or the bill (3.5). **Fits** → the stated count is a plausible floor; it is still usage only under the
   Step 2 rule.
4. **Throughput.** AWS publishes no figure for retrievals per second per OCU, nor documents per second per
   indexing OCU. Say exactly that when asked. The only evidence is this customer's own `SearchOCU` and
   `SearchRequestRate` series under their own traffic; offer to read them.
5. **Internal consistency.** Indexed GB below raw GB, a vector count far below a document count, or a
   dimension that does not match the model's page each mean a figure is wrong; name it and ask, do not
   average.
6. **`S3_VECTORS` source.** There are no OCUs; the check is whether the stated logical vector storage is
   consistent with `vector_count × dimension × bytes_per_dimension` as the
   [S3 pricing page](https://aws.amazon.com/s3/pricing/) (Vectors tab) states it in this conversation.

A capacity figure that fails this step is never priced, and a "but if it did hold" table is never built.

## Step 5. Fetch every rate live

Fetch each rate in this conversation, with its unit, source and timestamp. Field map and fallbacks are in
[C](#c-price-list-field-map-and-fallbacks).

| Component | Price List `--service-code` → what to match | Page |
|---|---|---|
| Managed KB storage (raw GB-month) | `AmazonBedrockAgentCore` → `usagetype` ending `Knowledge-Base:Consumption-based:Storage` | [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/), Managed Knowledge Bases |
| Managed KB retrieval (per call unit) | `AmazonBedrockAgentCore` → `...Knowledge-Base:Consumption-based:Retrieval` | same |
| Managed KB agentic retrieval | `AmazonBedrockAgentCore` → `...Knowledge-Base:Consumption-based:AgenticRetrieval` | same; note it is charged **plus** the underlying `Retrieve` calls |
| OpenSearch Serverless OCU-hours | `AmazonES` → `usagetype` ending `-SearchOCU` / `-IndexingOCU` | [OpenSearch Service pricing](https://aws.amazon.com/opensearch-service/pricing/), Serverless |
| OpenSearch Serverless storage | `AmazonES` → `usagetype` ending `-StorageUsedInS3ByteHour` (plus `-StorageUsedInHotByteHour` for NextGen hot storage); not `ES:*-Storage` (provisioned domains) and not `OpenSearch-Vectors-TimedStorage-ByteHrs` (a different product) | same |
| S3 Vectors storage, PUT, query request, query data | `AmazonS3` → the S3 Vectors usage types the bill shows (3.5) | [S3 pricing](https://aws.amazon.com/s3/pricing/), Vectors |
| Embedding, reranking, parsing and FM models | `AmazonBedrockFoundationModels` → match `servicename` client-side; embedding meter is the `usagetype` ending `_InputTokenCount-Units`; BDA parsing per page under its own section | Bedrock pricing, model sections |

- **The pricing pages render their rate tables in JavaScript.** A `curl` of the page returns the worked
  examples at best and no model rates at all. For every rate the path is the Price List API, then the
  credential-free offer file ([C](#c-price-list-field-map-and-fallbacks)); the page is a last resort for a
  figure that is literally in its text.
- Bedrock model IDs are not in the pricing catalog; match `servicename`. Check the token unit the record
  states and convert before use.
- The Managed Knowledge Bases section also lists what is **included** (parser, embedding model, reranker,
  agentic planning model). Record that list from the page in this conversation; Step 7 uses it.
- **Credit an inclusion only to a source you read in this conversation that states it.** A Price List
  API result lists meters, not inclusions: never credit it, or a page you did not fetch or that came back
  without that section, for what Managed includes. If the page did not show the list, give the
  [mapping](references/bedrock-kb-migration/mapping.md) reference as the source and say the pricing page
  was not read.

## Step 6. Compute with a script

Arithmetic is done by a script, never by reasoning in prose. Write `cost_compare.py` to `output_dir`,
feed it every input with its source tag and every rate with its unit, run it, and copy its output into
the reply. Every number the customer sees comes from the script's output. A row whose input is missing
prints `not included: <reason>` and the total that depends on it is omitted (Step 9).

```
hours_in_month = 730

Self-managed on OpenSearch Serverless (monthly):
  search_ocu_avg        × ocu_rate_per_hour × hours_in_month
+ indexing_ocu_avg      × ocu_rate_per_hour × hours_in_month
+ acceleration_ocu_avg  × ocu_rate_per_hour × hours_in_month        # only if the metric reports
+ indexed_gb            × aoss_storage_rate_per_gb_month
+ embedding_tokens_per_ingest × embedding_rate × ingests_per_month   # omitted from both sides when unknown
+ parsing_units         × parsing_rate                                # FM tokens or BDA pages; default parser = 0
+ rerank_queries        × rerank_rate                                 # only if implemented
+ generation_tokens     × fm_rate                                     # only if counted; symmetric with Managed

Self-managed on S3 Vectors (monthly):
  logical_vector_gb     × s3v_storage_rate_per_gb_month
+ put_gb_per_month      × s3v_put_rate_per_gb
+ queries_per_month     × s3v_query_request_rate
+ query_data_processed  × s3v_processed_rate (tier chosen by vector count, as the page states)
+ query_data_returned   × s3v_returned_rate (above the free allowance the page states)
+ embedding, parsing, reranking, generation as above

Managed KB (monthly):
  raw_gb                × managed_storage_rate_per_gb_month
+ retrieve_calls        × retrieve_rate
+ agentic_calls         × agentic_rate
+ agentic_underlying_retrieve_calls × retrieve_rate                   # agentic retrieval is charged plus its Retrieve calls
+ custom_embedding_tokens × model_rate                                # only with a custom embedding model; the managed model is included
+ generation_tokens     × fm_rate                                     # only if counted; symmetric

vectors_per_ocu_at_dimension = fetched_vectors_per_ocu × (fetched_dimension ÷ kb_dimension)   # Step 4; an estimate when the dimensions differ
plausibility: stated_search_ocu_active × vectors_per_ocu_at_dimension ≥ vector_count   # Step 4, when a capacity figure was supplied
delta  = managed_total − self_managed_total          # negative ⇒ Managed costs less
ratio  = managed_total ÷ self_managed_total

One volume missing (Step 1 exception, Step 8; not on a shared pool, where self_managed_total is the pool's):
threshold_retrieve_calls = (self_managed_total − managed_total_without_retrieval) ÷ retrieve_rate_per_call
threshold_qps            = threshold_retrieve_calls ÷ (86,400 × 30)       # the same volume, sustained around the clock
# Any other single missing volume: solve the same equality for that line, every other line as measured.
```

Rules the script enforces: the storage basis is **raw** GB on Managed and **indexed** GB on self-managed;
the OCU lines are the pool's when `ocu_pool_shared_collections > 1` and are labeled so, and the script
then also prints the whole-pool comparison (`pool_managed_total = Σ managed_total over every KB on the
pool`, against the pool's self-managed total); a line that is
unknown on one side is omitted on **both** (embedding, generation); redundancy is whatever the collection
runs, never a dev-test setting standing in for production; a break-even is computed only across the range
the inputs cover.

## Step 7. The required output

Every component appears on its side with a value and a source tag, or `not included: <reason>`. Nothing is
silently absent.

| Component | Self-managed | source | Managed | source |
|---|---|---|---|---|
| Compute (search OCU / indexing OCU / acceleration; or S3 Vectors query charges) | | | none to size or pay for | source read (Step 5) |
| Storage (indexed GB on self-managed; raw GB on Managed) | | | | |
| Embedding (ingest and re-ingest) | | | included with the managed model, or custom-model rate | source read (Step 5) |
| Parsing | | | included with the managed parser | source read (Step 5) |
| Reranking | | | included with the managed reranker | source read (Step 5) |
| Retrieval calls | none per call | | | |
| Agentic retrieval (plus underlying Retrieve calls) | not offered | | | |
| Answer generation | symmetric | | symmetric | |
| Data transfer | state it; not priced | | state it; not priced | |
| Operating the store (patching, scaling, capacity, index maintenance) | customer | qualitative | AWS | qualitative |
| **Monthly total** | | | | |

Then, in this order:

1. **Dominant line item** on each side.
2. **What the figures rest on**: each input with its tag, the window, the dimension set, the fetched rate
   sources and timestamps.
3. **What the self-managed figure reflects**: Classic or NextGen, `standbyReplicas`, the configured
   minimum and whether the series sits at it, how many collections share the pool.
4. **The Step 4 result** whenever a capacity figure was supplied: fits or does not, with the fetched figure
   and link.
5. **What Managed includes that the self-managed total does not**, read from the pricing page's Managed
   Knowledge Bases section in this conversation (the items it lists as included) and from
   [mapping](references/bedrock-kb-migration/mapping.md) for limits: stated as facts with links, not as a
   recommendation, each credited only to a source you read (Step 5).

## Step 8. Verdict

Only from the Step 6 output, and only after Step 7 is on the screen.

- **Both totals present**: lead with the recommendation in one sentence (which side costs this customer
  less), then the delta and ratio, the line item that drives each side, and what would change it (Managed
  grows per call as traffic grows; self-managed OCUs grow with data and traffic and fall with idleness only
  as far as the configured minimum or, on a zero-minimum group, to zero). Close with what Managed includes
  that the self-managed total does not (Step 7, item 5).
- **One volume missing** (Step 1 exception; on a shared pool use the shared-pool bullet instead): lead
  with a one-sentence recommendation built on the Step 6
  threshold, for example "Managed costs you less unless you average more than N Retrieve calls a month
  (about X per second around the clock)", then ask one yes/no question: "Is your traffic above or below
  that?" Say that N is a floor: self-managed capacity only grows with traffic, so above N it may need more
  OCUs too and the real crossover can only be higher. When the missing volume is on the self-managed side
  (for example S3 Vectors writes or queries), say how large the unpriced lines would have to be to change
  the answer. A threshold of zero or below means Managed costs more at any traffic: say so plainly, as the
  self-managed rule below says. Either way, offer to measure the missing volume.
- **The result favours self-managed**: say so plainly, as a finding about the bill. Then name what the
  total leaves out (item 5 of Step 7: operations work, re-ingestion, OCU growth under load, the parsing,
  embedding and reranking that Managed includes) and offer to measure what could change the result. Do
  not soften the number and do not argue with it.
- **The result favours Managed**: report the delta and the dominant line items the same way.
- **Shared pool** (Step 3.1): lead with the whole-pool result and recommend planning the pool's KBs
  together. For this KB alone, say that moving it adds its Managed lines while the pool's cost stays until
  the pool empties, and what the pool would cost with this KB gone, if the series shows it. This rule wins
  over the one-volume threshold: give no break-even or verdict that charges the pool's bill to this KB,
  labelled or not, including "if this KB were the pool's only tenant". A labelled what-if that prices this
  KB on capacity of its own, at a size you state and read from the docs in this conversation, is allowed
  (Step 1).
- **Either total missing for any other reason** (more than one volume, or a capacity or storage input):
  no flat verdict, no "likely", no "typically". Say which input removed which total (Step 9) and offer to
  measure. There is no typical crossover to quote. A verdict conditional on Step 1's labelled figures is
  allowed.
- **A break-even** is a result of the script over the range the inputs cover, never a starting point, and
  never computed on a capacity figure that failed Step 4. Apart from Step 1's labelled figures, the
  one-volume threshold above is the only one computed on a missing input, and only because every other
  input is the customer's own.

## Step 9. When an input is missing

An unreadable or denied figure is an expected outcome, **never a blocker**; the analysis is part of the
summary and does not gate the migration.

| Situation | Attempts | Then | Record as |
|---|---|---|---|
| Query succeeded, nothing usable (new collection, wrong scope tried, no series) | up to 3 varied (widen window, other dimension set, other service code) | omit the field, name the gap, ask the customer | `unavailable: <reason>` |
| Retrieval `Invocations` series empty (3.6) | 1 | say missing, not zero; name the likely cause and that adding the permission starts the count (3.6); ask the customer for their count | `unavailable: no Invocations series; KB service role likely lacks cloudwatch:PutMetricData` |
| Query refused (`AccessDenied`, `AccessDeniedException`, `UnauthorizedOperation`) | 1 | record the denied IAM action, continue with everything else | `denied: <iam action> on the read-only profile` |
| `pricing:GetProducts` denied | 1 | credential-free offer file first ([C](#c-price-list-field-map-and-fallbacks)), pricing page last | source `offer-file` or `pricing-page` |
| Customer cannot or will not supply a figure | ask once | record it; the total that needs it is omitted | `unavailable: not supplied` |
| Figure failed Step 4 | — | record as `capacity_setting`; ask for the series or the bill | `capacity_setting` |

Which missing input removes which total:

| Missing | Effect |
|---|---|
| search OCU average, or indexing OCU average | self-managed total omitted (quote rates and the figures you have) |
| indexed GB | self-managed storage line omitted; total omitted |
| raw GB | Managed total omitted |
| retrieval calls per month, everything else in hand | Managed total omitted; the threshold (Step 6, Step 8) replaces the verdict |
| retrieval calls per month and another input | Managed total omitted (quote the storage line and the retrieval rate) |
| vector count or dimension | Step 4 cannot run; every stated OCU count is a floor |
| `S3_VECTORS` logical storage (with keys and metadata), write volume, or query volume | S3 Vectors total omitted (quote the lines you can price from supplied figures) |
| embedding or generation volume | that line omitted on **both** sides, said in one sentence |
| either total | the delta, ratio, break-even and verdict go with it; never a partial comparison, except the one-volume threshold |

**Denial wording.** A read-only profile that excludes the cost probes is a normal, supported posture. Name
the action, not the symptom (`cloudwatch:GetMetricStatistics denied on the read-only profile; OCU figures
omitted`), attribute it to the profile, report all denials once together at the end, never ask for write
or admin access, and point at the optional read-only statement with the Step 2 questions as the by-hand
equivalent. The analysis still counts as **performed**; only a no at the gate is `declined`.

**A denial still gets a comparison.** After a denied read, still give the Step 7 table with everything
that can be priced: every per-unit rate you fetched, with its source, and every line whose quantity you
have (for example Managed storage on the raw bytes you measured). Omit only the lines and totals the
denied figure fed, each marked `not included: denied <iam action>`. Never call the comparison blocked,
not possible, or on hold.

---

## A. How the two pricing models differ

Use this whenever cost comes up and Step 1's gate is not passed. Take each point from the page named,
fetched in this conversation, and give its link.

| | Self-managed (OpenSearch Serverless `VECTOR` KB) | Managed KB | Where to read it live |
|---|---|---|---|
| What you pay for | **Capacity**: search OCU-hours and indexing OCU-hours, plus indexed storage | **Consumption**: raw data stored, plus retrieval calls (and agentic retrieval calls if used) | [OpenSearch Service pricing](https://aws.amazon.com/opensearch-service/pricing/) (Serverless); [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/) (Managed Knowledge Bases) |
| Vector store compute | You size it and pay for it; OCUs scale with vectors, dimension and traffic | None to size or pay for | [OpenSearch Serverless scaling](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-scaling.html) |
| Parsing, embedding, reranking | You pay the models you call, on every ingest and re-ingest, and per query for reranking | Included with the managed parser, embedding model and reranker (a model of your choice is charged) | Bedrock pricing, Managed Knowledge Bases and model sections |
| Storage basis | **Indexed** GB | **Raw** GB | both pricing pages |
| When idle | Down to the configured minimum; a NextGen group with a zero minimum can scale compute to zero | Storage only | [Scale to zero](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-scale-to-zero.html); [collection groups](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-collection-groups.html) |
| As traffic grows | OCUs grow (replicas for throughput, memory for data) | Retrieval charges grow per call | both pricing pages |
| S3 Vectors as the self-managed store | Logical vector storage, PUT volume, per-query request and data charges; no compute to size | as above | [S3 pricing](https://aws.amazon.com/s3/pricing/), Vectors |

Two consequences: **neither side is flat** (never hold one side constant across traffic the inputs do not
cover), and **the configured minimum is not the bill** (the bill is the OCU series or the Cost Explorer
line; a minimum says only the lowest it can go).

## B. Modeling errors seen in practice

- **Pricing a stated OCU count as usage** ("we run one search and one indexing OCU", then OCUs × rate × 730).
  A stated or configured count is a floor until the series or the bill confirms it (Step 2 rule) and it
  passes Step 4.
- **Sizing OCUs from GB.** Vector count and dimension set the memory an index needs; raw GB does not. A
  configuration that cannot hold the index is not costed (Step 4).
- **Counting only retrieval.** Self-managed has no per-call charge, so a retrieval-only comparison always
  favours it; the OCU-hours, storage, embedding, parsing and reranking lines are the comparison.
- **Counting search OCUs but not indexing OCUs**, or omitting the acceleration metric when it reports.
- **Applying the Managed per-GB rate to indexed GB** inflates Managed by the whole expansion ratio.
- **Scoring embedding, reranking and parsing as free on both sides.** They are included on Managed and real
  charges or missing capabilities on self-managed.
- **Pricing agentic retrieval without its underlying `Retrieve` calls.**
- **Holding one side flat across traffic levels.**
- **A projected peak presented as traffic**, or volumes the agent chose presented as the customer's.
- **Comparing production Managed against a `standbyReplicas: DISABLED` configuration.**
- **Attributing a shared OCU pool to one KB**, or promising the pool's cost disappears when one KB leaves,
  including a break-even worked out as if this KB were the pool's only tenant.
- **Arithmetic in prose**: a total that was never computed by the script in `output_dir`.
- **Accepting a generated cost model without the bill**: anchor on CloudWatch and Cost Explorer (3.5).

## C. Price List field map and fallbacks

```bash
aws pricing get-products --service-code AmazonBedrockAgentCore --region us-east-1 \
  --filters "Type=TERM_MATCH,Field=regionCode,Value=<REGION>" --profile <READ_ONLY_PROFILE>
aws pricing get-products --service-code AmazonES --region us-east-1 \
  --filters "Type=TERM_MATCH,Field=regionCode,Value=<REGION>" --profile <READ_ONLY_PROFILE>
aws pricing get-products --service-code AmazonBedrockFoundationModels --region us-east-1 \
  --filters "Type=TERM_MATCH,Field=regionCode,Value=<REGION>" --profile <READ_ONLY_PROFILE>
```

- **Managed KB rates are under `AmazonBedrockAgentCore`**, not `AmazonBedrock`; an empty result under
  `AmazonBedrock` is expected.
- **OpenSearch Serverless rates are under `AmazonES`**, the legacy code. Guessed codes return an empty
  `PriceList`, not an error, so an empty result proves nothing. Filter on `regionCode` or the exact
  `usagetype` (for example `USW2-SearchOCU`); page with `NextToken`. Match `usagetype` by exact suffix: the
  Region also publishes `SemanticSearchOCU`, `DirectQueryOCU` and `IngestionOCU`, and the indexed-storage
  meter is `-StorageUsedInS3ByteHour` (`-StorageUsedInHotByteHour` for NextGen hot storage).
- **Model rates**: there is no `modelId` attribute; match `servicename` client-side. The on-demand embedding
  meter is the `usagetype` ending `_InputTokenCount-Units`. Convert the unit the record states.
- **If `pricing:*` is denied**, the credential-free bulk offer file serves the same data:
  `curl -sSL "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/<SERVICE_CODE>/current/<REGION>/index.json"`.
- **Pricing-page sections are rendered by JavaScript.** A fetched page with the heading but not the number
  is not a source; use the API or the offer file.
- Quote every rate with its unit, its source and the time you fetched it.

## D. Read-only command quick reference

| Task | Command |
|---|---|
| Collection config / redundancy / KMS key / group | `aws opensearchserverless batch-get-collection --ids <ID>` (3.1) |
| Collection group capacity settings | `aws opensearchserverless batch-get-collection-group --names <GROUP_NAME>` (3.1) |
| List collections (sharing scope) | `aws opensearchserverless list-collections` |
| Which OCU scope carries the collection | `aws cloudwatch list-metrics --namespace AWS/AOSS --metric-name SearchOCU` (3.2) |
| Search / indexing OCUs, 30-day Average and Maximum | `aws cloudwatch get-metric-statistics --namespace AWS/AOSS --metric-name SearchOCU ...` with the dimension set from 3.2; `--metric-name IndexingOCU` for the other half |
| Indexed storage | `list-metrics --metric-name StorageUsedInS3 --dimensions Name=CollectionId,Value=<ID>`, then `get-metric-statistics` with the full set at `--period 60` (3.3) |
| Raw corpus size | `aws s3api list-objects-v2 --bucket <B> --prefix <P> --query 'sum(Contents[].Size)'` |
| Vector count | `get-metric-statistics --namespace AWS/AOSS --metric-name SearchableDocuments` for the KB's index (3.4) |
| Embedding model and dimension, and the KB's index name | `aws bedrock-agent get-knowledge-base --knowledge-base-id <ID>` (3.4) |
| S3 Vectors index dimension | `aws s3vectors get-index --vector-bucket-name <B> --index-name <I>` (3.4) |
| The bill | `aws ce get-cost-and-usage ... --group-by Type=DIMENSION,Key=USAGE_TYPE --filter '{"Dimensions":{"Key":"SERVICE","Values":["Amazon OpenSearch Service"]}}'` (3.5) |
| Retrieval volume | `get-metric-statistics --namespace AWS/Bedrock/KnowledgeBases --metric-name Invocations --dimensions Name=KnowledgeBaseId,Value=knowledge-base/<ID> Name=Operation,Value=Retrieve`, 30-day `Sum` (3.6); then app telemetry, then the customer |
| Rates | `aws pricing get-products --service-code <AmazonBedrockAgentCore \| AmazonES \| AmazonS3 \| AmazonBedrockFoundationModels> --region us-east-1 --filters "Type=TERM_MATCH,Field=regionCode,Value=<REGION>"` (C) |
| Rates without IAM | `curl -sSL "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/<SERVICE_CODE>/current/<REGION>/index.json"` |

## E. Output record

One record per KB. Read `analysis_status` first. Every value is a placeholder naming where the real value
comes from. **Omit, never `null`**: a field a bounded search cannot resolve is dropped and the gap named in
`scope_note`. On `declined`, keep only `source_kb_id`, `vector_store`, `analysis_status` and `scope_note`.
USD throughout; identifiers and ARNs only, never a secret value.

```yaml
source_kb_id: <live KB id>      # an IaC-only KB uses logical_id instead — exactly one
vector_store: <OPENSEARCH_SERVERLESS | S3_VECTORS | other>
analysis_status: performed      # performed | declined  (declined = the user said no at the gate; never means AWS said no)
in_scope: true                  # true for OPENSEARCH_SERVERLESS and S3_VECTORS; false ⇒ omit current_self_managed, name why in scope_note
pricing_source: { method: pricing:GetProducts, service_codes: [<AmazonES | AmazonBedrockAgentCore | AmazonS3 | AmazonBedrockFoundationModels>], region_endpoint: us-east-1, retrieved_at: <ts> }
corpus:
  total_size_bytes: <measured: s3:ListObjectsV2 sum(Size)>
  object_count: <measured>
  measured_via: s3:ListObjectsV2 sum(Size) over inclusionPrefixes
index:
  vector_count: <measured: SearchableDocuments for the KB's index, or customer-supplied>
  embedding_model_arn: <GetKnowledgeBase>
  embedding_dimension: <GetKnowledgeBase, or the model's page>
  plausibility: { checked: <true|false>, stated_search_ocu: <n or none>, fits: <true|false>, guidance_source: <url>, note: <text> }   # omit when no capacity figure was supplied
current_self_managed:           # omit the whole block when not in_scope
  architecture: <CLASSIC | NEXTGEN_GROUP | S3_VECTORS>
  collection_arn: <arn>
  standby_replicas: <ENABLED | DISABLED>
  collection_group: <name, or none>
  capacity_limits: <the group's capacityLimits as returned; omit for Classic>
  ocu_pool_shared_collections: <count>   # > 1 ⇒ OCU figures are the pool's, not this KB's
  search_ocu_avg: <measured: AWS/AOSS SearchOCU 30d Average>
  search_ocu_max: <measured: 30d Maximum>
  indexing_ocu_avg: <measured>
  indexing_ocu_max: <measured>
  acceleration_ocu_avg: <measured: VectorIndexBuildAccelerationOCU>   # omit with reason when no series
  indexed_storage_gb: <measured: StorageUsedInS3 (+ StorageUsedInHot on NextGen)>
  expansion_ratio: <derived: indexed ÷ raw>
  capacity_setting: <a stated or configured OCU count that is a floor, not usage>   # omit when none was stated
  usage_source: <how the OCU and storage figures were obtained, incl. dimension set and window>
  bill_line_usd: <measured: Cost Explorer, account-level, Region and usage types kept>
  rates: { ocu_per_hour: <fetched>, storage_per_gb_month: <fetched>, embedding: <fetched + unit>, rerank: <fetched + unit>, parsing: <fetched + unit> }
  line_items_usd: { compute: <script>, storage: <script>, embedding: <script | not included: reason>, parsing: <...>, reranking: <...>, generation: <...> }
  estimated_monthly_usd: <script>    # omit if any REQUIRED input is absent
retrieval:                      # omit when no volume was established
  calls_monthly: <measured or customer-supplied>
  effective_qps: <derived>
  source: <measured | customer_supplied | forecast>
  measured_via: <metric and window, app telemetry, or the existing data-event store>
  agentic_calls_monthly: <customer-supplied>   # omit unless agentic retrieval is wanted
estimated_managed:
  embedding_model_type: <MANAGED | CUSTOM>   # MANAGED ⇒ embedding, parsing, reranking included
  raw_corpus_gb: <measured>
  rates: { storage_per_gb_month: <fetched>, retrieve: <fetched + unit>, agentic: <fetched + unit> }
  line_items_usd: { storage: <script>, retrieval: <script>, agentic: <script | not included: reason>, generation: <...> }
  included: [<items the pricing page lists as included, read in this conversation>]
  estimated_monthly_usd: <script>    # omit when raw GB or retrieval volume is absent
  managed_pricing_source: { method: <pricing:GetProducts | offer-file | pricing-page>, url: <url>, retrieved_at: <ts> }
comparison:                     # omit unless BOTH totals are present
  delta_monthly_usd: <script: managed − self-managed; negative ⇒ Managed costs less>
  ratio: <script>
  cheaper: <MANAGED | SELF_MANAGED | COMPARABLE>
  self_managed_dominant_line_item: <e.g. search OCUs>
  managed_dominant_line_item: <e.g. retrieval calls>
  rests_on: <the inputs, each measured or customer-supplied>
  script_path: <output_dir>/cost_compare.py
scope_note: <specific reason>   # required on in_scope:false, declined, any omitted field, or a denied permission (name the IAM action)
```

## F. Procedural mistakes

- **Giving a figure before the Step 1 gate is passed** that Step 1 does not allow: a total on a guessed
  rate, an assumed input presented as theirs, or a table at volumes you chose presented as their usage.
- **Quoting a rate without fetching it in this conversation**, or naming a page you did not fetch.
- **Skipping Step 4** when the customer stated an OCU count, or pricing a count that failed it.
- **Computing in prose** instead of in `cost_compare.py` in `output_dir`.
- **An output table with a row missing** rather than marked `not included: <reason>`.
- **Concluding OpenSearch Serverless pricing "isn't published"**: it is, under `AmazonES` (C). Empty results
  from guessed codes, an unfiltered single page, or a `ClientId`-only `StorageUsedInS3` query prove nothing.
- **Blocking the migration because a figure was unavailable or denied**: Step 9, then move on.
- **Mishandling a denial**: spending the 3-attempt ladder on it, writing "OCUs unavailable" instead of the
  IAM action, recording it as `declined`, or asking for broader or write credentials.
- **Running the analysis on a declined session**, or offering a "rough idea" instead.
- **Writing cost or price files outside `output_dir`**.
