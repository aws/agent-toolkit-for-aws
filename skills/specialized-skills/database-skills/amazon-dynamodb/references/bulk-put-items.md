# Bulk put items and `StartBulkPutItems`

DynamoDB **bulk put items** loads data from Amazon S3 into a table that already exists. You call
`StartBulkPutItems` (CLI `start-bulk-put-items`) with an S3 prefix of DynamoDB JSON or Amazon Ion
files. DynamoDB reads every object under the prefix, writes each record as a whole-item put, and
reports what it couldn't write to an S3 location you choose. The writes consume none of the
table's capacity. `ImportTable` (Import from S3) creates only new tables.

Read this file when a task loads, backfills, refreshes, migrates, restores or reshapes data in an
existing table from S3, or someone proposes a custom loader (Glue, Step Functions, Lambda, a
`BatchWriteItem` script).

## Good fits

- **Recurring refreshes**: ML features, recommendation scores, catalogs, prices, configs, partner
  feeds. Each record replaces the whole item: load full items the job owns (its own sort key, for
  example); send only-some-attributes feeds for items others write to `UpdateItem` with
  `attribute_exists(<pk>)`. Items the input omits stay: delete them or set TTL.
- **Warehouse activation**: results from a data lake, Redshift, EMR or Spark, served online. Write
  typed `{"Item": ...}` records, or convert CSV, Parquet or plain JSON first.
- **Upstream accounts and migrations**: data from another account, database, table or Region via
  S3.
- **Backfills**: history into a live table with `attribute_not_exists(<pk>)` on each record, minus
  keys deleted or erased since.
- **Non-key schema changes**: add, split, normalize or flatten attributes, or give older items a new
  GSI's keys (create the GSI before or after the load, not during): export, transform and bulk put
  whole items under the reload guard (*Reshaping a live table*); not increments.
- **Restores, reloads and seeding** of tables CloudFormation, CDK or Terraform own (*Infrastructure
  as code*). A reload isn't a restore: items created since stay (delete them for an exact restore),
  items changed since are overwritten (`attribute_not_exists(<pk>)` restores only missing keys), and
  deleted keys return unless dropped from the input.

## Route the load first

| Situation | Where it goes |
|---|---|
| DynamoDB JSON or Ion in S3, existing single-Region table, caller in the table's account | **Bulk put items** |
| CSV, Parquet or incremental-export files, existing table | Convert to DynamoDB JSON or Ion, then bulk put (*Preparing the input*) |
| A new table without LSIs | `ImportTable` (it also reads CSV) |
| A new table that needs LSIs | `CreateTable` with the LSIs, then bulk put. `ImportTable` can't create LSIs |
| A global table, standard (MREC) or MRSC | The write path (*Global tables*, below) |
| A caller outside the table's account | A role in the table's account, or the write path |
| A request path, a sub-minute deadline, or a continuous stream | `PutItem` / `BatchWriteItem` |
| Increments, partial updates or deletes | `UpdateItem` / `DeleteItem`. Bulk put only writes whole items |
| Records that need several items written atomically (uniqueness sentinels) | Chunked `TransactWriteItems` (Mechanics #13, #14) |

"The write path" here means your own loader calling `PutItem` or `BatchWriteItem` against the
table's capacity, where the Mechanics #3 ceilings and the Mechanics #18 formulas apply.

`ImportTable` can't load an existing table, even through IaC: **NEVER add `ImportSourceSpecification`
to an existing stack's `AWS::DynamoDB::Table`** (or an import source to a deployed CDK `Table`).
It only applies at creation, so adding it replaces the table, and with an explicit table name the
update fails. Don't import into a new table and swap it in, or adopt it with `terraform import`:
the existing table keeps its name, ARN, tags and LSIs.

When the first row fits, **do not hand-build a loader.** The operation already is the durable job
Mechanics #14 describes: the `BulkOperationArn` is the job ID, Describe reports progress,
`ClientToken` makes the start idempotent, Cancel stops it, and per-record failures land in S3. But
it is a batch tool: it takes minutes to start even for a small input and can run for days, so
anything a caller waits on stays on the write path.

### Global tables

Bulk put rejects any table that is part of a global table, MREC or MRSC, with `ValidationException`.
Never add a replica, or convert the table to a global table, until the operation is terminal. Never
remove replicas to make a table eligible: each removed Region loses its copy until you add it back.

- **MREC.** Load through the write path in one Region; replication carries the items and consumes
  write capacity in every replica Region. If the table isn't global yet, you may instead bulk put
  while it is single-Region, wait for a terminal status, then add replicas.
- **MRSC.** Only the write path works: `PutItem` or `BatchWriteItem`, never `TransactWriteItems`
  (MRSC tables don't support transactions); retry `ReplicatedWriteConflictException`. Loading a
  single-Region table and converting it later fails, because only an empty table can become MRSC.

## Requirements and limits

- **A stale SDK or CLI is not evidence the feature is missing.** An older client lacks the
  operations: `aws dynamodb start-bulk-put-items` fails with `Found invalid choice`, and
  `hasattr(client, "start_bulk_put_items")` is `False`: prefer that probe to a version check, and
  upgrade. The AWS MCP server's `call_aws` tool bundles its own SDK, which can lag a launch; if it
  rejects the operation, run a current local CLI or SDK. With a current client, an
  `UnknownOperationException` from the service means the feature isn't in that Region or partition.
- **Table state.** The table must be `ACTIVE`, or `UPDATING` for a change that doesn't conflict. It
  can't be creating an index, restoring from a backup, or moving to or from a global table.
- **One operation per table at a time**, and index creation excludes it both ways: a start while an
  index is being created, or a GSI creation during a load, fails with `ResourceInUseException`.
  Tables with a vector index accept only `STANDARD`; `ACCELERATED` fails validation.
- **Quotas**, per account and Region: 100 GB of input per operation on `STANDARD` and 1 TB on
  `ACCELERATED` (binary units); 5 concurrent operations per tier, counted separately; 50,000 S3
  objects per operation; 5,000,000,000 bytes (decimal) per object; about 6.5 days of processing.
  Split a larger input into sequential operations on the same table, sizing compressed input by both
  its stored and uncompressed bytes.
- **Most limits are checked late.** Of the quotas, only concurrency (`LimitExceededException`) and
  one-per-table (`ResourceInUseException`) are checked at the call. Size, object-count and S3
  problems surface later, usually as `FAILED`, so check the input, permissions and keys first.
- **The caller must be in the table's account.** A caller elsewhere assumes a role there, whose
  trust policy names that principal (plus `sts:ExternalId` for a third party), not the account
  root. The input bucket may be in another account (set `S3BucketOwner`) or Region; a cross-Region
  bucket adds transfer charges and ties the run to that Region's health. Keep the output bucket in
  the table's account with `S3BucketOwner` unset, so S3 rejects a bucket another account owns.

## Preparing the input

Set `InputFormat` to `DYNAMODB_JSON` (JSON Lines: one record per line, no newline inside a record)
or `ION` (newline-delimited Ion structs), and `InputCompressionType` to `GZIP`, `ZSTD` or `NONE`
(the default). All objects under the prefix must share one format and one compression type. Each
record holds a required `Item` in DynamoDB marshalled form plus optional condition fields:

```json
{"Item":{"pk":{"S":"ORDER#1001"},"status":{"S":"PAID"},"total":{"N":"99.95"}}}
{"Item":{"pk":{"S":"ORDER#1002"},"status":{"S":"NEW"},"v":{"N":"7"}},"ConditionExpression":"attribute_not_exists(#v) OR #v < :new","ExpressionAttributeNames":{"#v":"v"},"ExpressionAttributeValues":{":new":{"N":"7"}}}
{"Item":{"pk":{"S":"ORDER#1003"},"status":{"S":"SHIPPED"},"v":{"N":"13"}},"ConditionExpression":"#v = :exported","ExpressionAttributeNames":{"#v":"v"},"ExpressionAttributeValues":{":exported":{"N":"12"}}}
```

- **Only `Item`, `ConditionExpression`, `ExpressionAttributeNames` and `ExpressionAttributeValues`
  may appear at the top level.** A missing `Item`, a misspelled or extra field, a malformed token,
  an unknown type tag, or nesting deeper than 64 levels stops DynamoDB reading the rest of that
  object (*Parse stops*, below). Item-level problems (a missing or wrongly typed key attribute, an
  item over 400 KB) skip only that record and are reported as `ERROR`. Validate a sample first.
- **The prefix is a plain S3 prefix match with no filtering.** Everything under it is read, so
  point it at a folder holding only input, and end it with `/` so `daily/1` doesn't also match
  `daily/10/`. Freeze it until the operation is terminal (no writers, no lifecycle expiration):
  changing an input object mid-run fails the operation with `ObjectModifiedInS3DuringImport`.
- **Split the input into many similarly sized objects** with evenly spread, high-cardinality keys;
  DynamoDB reads objects in parallel, so one huge object or skewed keys load slower.
- **A full DynamoDB export loads as-is** from `<prefix>/AWSDynamoDB/<export-id>/data/`, with the
  export's format and `GZIP`; the manifests beside it aren't records. As-is means unconditional, so
  it overwrites newer data: to fill in only missing keys, add `attribute_not_exists(<pk>)` to each
  record, minus keys deleted or erased since. To split an export over a size quota, copy its `data/`
  files under several new prefixes.
- **CSV, Parquet, plain JSON, JSON arrays and incremental exports are rejected.** Convert them
  first; at scale, use a Glue, EMR or Athena job that writes one `{"Item": ...}` record per line.
  For an incremental export (`Keys`, `NewImage`, `OldImage`), turn each new image into a record
  and apply its deletes separately with `DeleteItem` or `BatchWriteItem`.

## Write semantics

- **Every record is a whole-item put.** Bulk put never merges, updates in place or deletes. A record
  without a condition overwrites any item with the same key, dropping attributes it omits. Items
  the input doesn't mention stay, so a refresh that must drop rows needs a delete pass or TTL.
- **Conditions live per record, inside the file**, in `PutItem` condition syntax, checked against
  the existing item. With no request-level condition, insert-only needs `attribute_not_exists(<pk>)`
  on every line. To write only new items and newer versions, carry a version attribute and use the
  second example's `attribute_not_exists(#v) OR #v < :new`, with values marshalled like `Item`.
  It passes for a missing item, so never use it to re-apply an export; a reshape of one takes the
  third example's **reload guard**, `#v = :exported` with no `OR attribute_not_exists` branch
  (*Reshaping a live table*).
- **A failed condition is a skip, not an error.** It doesn't count in `FailedItemCount`, a run whose
  only problems are skips still ends `COMPLETED`, and skips are reported only if `OutputType`
  includes `CONDITION_CHECK_FAILURE`; without it, nothing records them. Skipped items are billed.
- **The load is not atomic.** Items are readable as they land, in no guaranteed order, so nothing
  decides which of two records with the same key lands last: deduplicate first, or use a version
  condition. Cancel and `FAILED` keep what was written; nothing rolls back.
- **Writes are at least once.** After an internal hand-off or retry, a conditional record can
  conflict with itself (the existing image equals the supplied item), and an unconditional re-put
  can overwrite a newer application write. On keys that live writers touch, use a version condition
  (insert-or-newer for a feed's own items, the reload guard for reshapes).

### Reshaping a live table

An export is a snapshot and each record replaces the whole item, so an unguarded reload overwrites
writes made since and recreates items deleted since.

1. Before the export, deploy writers that set the version attribute and write the new shape, and
   readers that accept both shapes.
2. Export, then transform only items still in the old shape; leave new-shape items out of the input.
3. Guard every record: `#v = :exported` on a version attribute that every write changes and that
   never repeats for a key, with no `OR attribute_not_exists` branch; write version + 1. Items
   exported without it use `attribute_exists(<pk>) AND attribute_not_exists(#v)`, valid only if
   writers have set it since before the export.
4. Request `CONDITION_CHECK_FAILURE` and repeat until a round reports no skips. A skip whose
   `oldImage` equals your record or is already in the new shape is done; no `oldImage` means
   deleted, so leave it; otherwise transform the `oldImage` and write it with `:exported` set to its
   version (a conditional `PutItem` suits the last few: on failure, re-read and retry). Never write
   a skip back unconditionally.

Without a version attribute, pause every writer before requesting the export until every run,
including resubmitted remainders, is terminal, and condition each record on `attribute_exists(<pk>)`
so TTL-deleted items stay deleted. Or `Scan` and `UpdateItem` each item conditioned on
`attribute_exists(<pk>)` and its source attributes still holding the values read, which consumes
table capacity.

## Effects on the table and downstream

- **No table capacity.** The load uses none of the table's provisioned or on-demand capacity, so it
  doesn't throttle the application, and the Mechanics #3 ceilings and #18 formulas don't apply.
  Bulk writes skip `ConsumedWriteCapacityUnits` and Contributor Insights: monitor the operation.
- **Throughput is best effort** on both tiers, with no completion-time SLA. It depends on warm
  throughput, item size, key distribution, GSI and LSI count, and available capacity.
- **Indexes update automatically**: GSIs, LSIs and vector indexes, each metered separately. **DAX is
  bypassed**, so items cached in DAX stay stale until their DAX TTL expires.
- **Every write emits a stream record** in DynamoDB Streams and Kinesis Data Streams, at the
  operation's write rate and indistinguishable from an application write; zero-ETL gets them too.
- **CloudTrail logs the operation, not the item writes.** The start is management event
  `StartBulkOperation` (resource type `AWS::DynamoDB::BulkOperation`). While it runs, DynamoDB
  emits several `BulkPutItems` data events on the table, each with
  `serviceEventDetails.BulkOperationArn`; a trail records them only if it logs the table's data
  events (off by default). See *Security*.

### Stream consumers

A 100-million-item load is 100 million stream records. A consumer sized for normal traffic falls
behind, and DynamoDB Streams keeps records 24 hours, so a consumer more than a day behind loses
them. Size the consumer for normal traffic plus the load, and watch `IteratorAge`. Or cap the
operation with `MaxWriteRequestUnits`, in write request units per second (at least 1,024, this
operation only); at 1,024 it writes at most about 88 million 1 KB items a day, so a low cap on a
big load ends in `Timeout`. Or pause the event source mapping and re-enable it in time to drain the
backlog within 24 hours. Integration #1 (idempotent handlers) and #5 (bounded retries) apply.

Do **not** recommend a marker attribute written only by the load and filtered out in the event
source mapping (Integration #4). The marker stays on the item, so later application updates carry
it in `NewImage` too and the filter silently drops them, leaving copies like a search index stale.

## Infrastructure as code

Bulk put has no CloudFormation resource and causes no stack drift: it changes items, which no stack
tracks. Run it from the CLI, an SDK or a pipeline step after the stack deploys.

## Running an operation

`OutputS3Configuration` is required. Always include `ERROR` in `OutputType` (the only record of
failed records and parse stops); add `CONDITION_CHECK_FAILURE` whenever records carry conditions.

```bash
ARN=$(aws dynamodb start-bulk-put-items --table-name Orders \
    --input-s3-configuration '{"S3Bucket": "example-load-input", "S3KeyPrefix": "orders/2026-10-29/",
        "InputFormat": "DYNAMODB_JSON", "InputCompressionType": "GZIP"}' \
    --output-s3-configuration '{"S3Bucket": "example-load-reports", "S3KeyPrefix": "orders",
        "OutputType": ["ERROR", "CONDITION_CHECK_FAILURE"], "S3SseAlgorithm": "KMS",
        "S3SseKmsKeyId": "arn:aws:kms:us-east-1:<account-id>:key/<key-id>"}' \
    --performance-tier STANDARD --client-token orders-2026-10-29 \
    --query BulkOperationDescription.BulkOperationArn --output text)

aws dynamodb describe-bulk-operation --bulk-operation-arn "$ARN"
aws dynamodb wait bulk-operation-completed --bulk-operation-arn "$ARN"   # gives up after 60 minutes
aws dynamodb list-bulk-operations
aws dynamodb cancel-bulk-operation --bulk-operation-arn "$ARN"
```

The same in boto3, polling in a loop because a large load outlives the waiter:

```python
import time
import boto3
ddb = boto3.client("dynamodb", region_name="us-east-1")
if not hasattr(ddb, "start_bulk_put_items"):
    raise SystemExit("boto3/botocore predates bulk put items: upgrade it")
arn = ddb.start_bulk_put_items(
    TableName="Orders",
    ClientToken="orders-2026-10-29",  # reuse on retry; kept 8 hours
    InputS3Configuration={"S3Bucket": "example-load-input", "S3KeyPrefix": "orders/2026-10-29/",
                          "InputFormat": "DYNAMODB_JSON", "InputCompressionType": "GZIP"},
    OutputS3Configuration={"S3Bucket": "example-load-reports", "S3KeyPrefix": "orders",
                           "OutputType": ["ERROR", "CONDITION_CHECK_FAILURE"],
                           "S3SseAlgorithm": "KMS",
                           "S3SseKmsKeyId": "arn:aws:kms:us-east-1:<account-id>:key/<key-id>"},
    MaxWriteRequestUnits=4096,  # optional cap; minimum 1024
)["BulkOperationDescription"]["BulkOperationArn"]
while True:
    d = ddb.describe_bulk_operation(BulkOperationArn=arn)["BulkOperationDescription"]
    if d["BulkOperationStatus"] in {"COMPLETED", "COMPLETED_WITH_ERRORS", "CANCELLED", "FAILED"}:
        break
    time.sleep(60)
print(d["BulkOperationStatus"], d.get("FailureCode"), d.get("FailedItemCount"))
```

- **Waiter.** `bulk-operation-completed` (boto3 `bulk_operation_completed`) polls every 20 seconds
  and gives up after 60 minutes. It succeeds on `COMPLETED` and
  `COMPLETED_WITH_ERRORS` and fails on `CANCELLED` and `FAILED`; the CLI exits 255 on either stop.
- **Progress.** Compare `ProcessedInputBytes` with `TotalInputBytes`: both are absent for about the
  first 60 seconds; counters refresh every 30 to 60 seconds. `ProcessedItemCount` counts records
  read, including errors and skips.
- **`ClientToken`.** A retried start with the same token returns the same operation for 8 hours,
  scoped to the caller's principal; the same token with different parameters raises
  `IdempotentParameterMismatchException`. Set your own: an SDK-generated token is new on every call.
- **Listing** covers the account and Region, newest first, up to 25 per page, with no table filter.
  Runs drop out of List and Describe 90 days after `StartTime`.
- **Cancel** returns `CANCELLING`, then reaches `CANCELLED`; it isn't instant, rolls nothing back,
  and sets `FailureCode` to `RequestCancelled`. Cancelling a terminal operation fails.
- **Tiers.** `STANDARD` is the cost-optimized default. `ACCELERATED` targets higher, more
  repeatable throughput, costs more, and isn't offered in every Region.
- **Timeout.** After about 6.5 days a run ends `FAILED` with `Timeout`, expected for a very large or
  tightly capped load (*Troubleshooting*).
- **Parse stops.** A record that stops its object writes one `ERROR` record ending `Remainder of the
  file will not be processed.`, and the manifest marks the object `PARTIALLY_PROCESSED`. Detect
  parse stops from that text and the manifest, not the status, whenever a run isn't `COMPLETED`.

| Status | Meaning |
|---|---|
| `IN_PROGRESS` | Reading input and writing items |
| `COMPLETED` | Finished with no parse or validation errors. Condition skips are allowed |
| `COMPLETED_WITH_ERRORS` | Finished, but at least one record failed parsing or validation (`FailedItemCount` > 0) |
| `CANCELLING` / `CANCELLED` | Stopping, then stopped, on request. Written items stay |
| `FAILED` | Stopped; see `FailureCode` and `FailureMessage`. Items written before it stay |

## Output, the manifest, and resubmitting the remainder

```text
<output-prefix>/AWSDynamoDB/BulkOperation/<account-id>:<operation-id>-<n>/output/errors/output-NNNNN.json.gz
<output-prefix>/AWSDynamoDB/BulkOperation/<account-id>:<operation-id>-<n>/output/condition-check-failures/...
<output-prefix>/AWSDynamoDB/BulkOperation/<account-id>:<operation-id>/manifest-files.json
```

There is one `-<n>` directory per internal job. Output is gzip JSON Lines rolled at 200 MiB, so
files appear while `IN_PROGRESS`; it's written on every terminal status. List objects under
`<output-prefix>/AWSDynamoDB/BulkOperation/` rather than building keys. Each record carries
`itemLocation` (`inputSourceArn`, `itemIndex`) and `errorMessages`; a condition-check record adds
`newImage` (your record) and `oldImage` (the existing item), so it holds table data.

The manifest has one JSON line per input object: `inputSourceArn`, `fileProcessingStatus`,
`processedRanges` (inclusive, zero-based start and end record indexes) and `etag`. The statuses are
`FULLY_PROCESSED`, `PARTIALLY_PROCESSED`, `NOT_PROCESSED` and `NOT_AVAILABLE` (ranges unknown). A
`FailureMessage` beginning `Manifest is not available.` means it couldn't be written.

To resubmit only the remainder after `Timeout`, `CANCELLED`, a parse stop or another `FAILED`:

1. From the manifest, skip `FULLY_PROCESSED` objects, take the records outside `processedRanges`
   from `PARTIALLY_PROCESSED` ones, and take `NOT_PROCESSED` objects whole. Take `NOT_AVAILABLE`
   objects whole only if their records are safe to re-apply (version conditions or identical puts).
2. Add the `ERROR` records you've fixed, found by `itemLocation`.
3. Write it all under a **new** prefix (the old one would re-read everything) and start a new
   operation with a new `ClientToken`. A conditional record the first run already wrote reports a
   self-conflict; if `oldImage` equals `newImage`, it's done.

## Security

| IAM action | Resource | Needed to |
|---|---|---|
| `dynamodb:StartBulkOperation` | `arn:aws:dynamodb:<region>:<account-id>:bulk-operation/*` | Start (with `BulkPutItems`) |
| `dynamodb:BulkPutItems` | The table ARN | Write into that table |
| `dynamodb:DescribeBulkOperation`, `dynamodb:CancelBulkOperation` | The operation ARN, so `bulk-operation/*` in practice | Monitor, cancel |
| `dynamodb:ListBulkOperations` | `arn:aws:dynamodb:<region>:<account-id>:bulk-operation/*` | List |
| `s3:ListBucket` | `arn:aws:s3:::<input-bucket>` | List the input |
| `s3:GetObject` | `arn:aws:s3:::<input-bucket>/<input-prefix>*` | Read the input |
| `s3:PutObject`, `s3:AbortMultipartUpload` | `arn:aws:s3:::<output-bucket>/<output-prefix>/*` | Write the reports |
| `kms:Decrypt`, `kms:GenerateDataKey` | A customer managed table key; an SSE-KMS output key | Use those keys |
| `kms:Decrypt` | An SSE-KMS input key | Read encrypted input |

- **Scope each grant as shown; `bulk-operation/*` is the only wildcard.** Operation ARNs belong to
  the account, not the table, and don't exist before the start, so Describe and Cancel reach every
  bulk operation in the account and Region, and Describe shows each one's table, buckets and keys.
  A loader without Describe and Cancel can't watch or stop its runs; in a shared account, give
  Cancel and List to an operator role unless a loader must stop its own. There is no
  `dynamodb:StartBulkPutItems` action. The start also checks the table's tags and resource policy.
- **S3 and KMS calls use the caller's own credentials**: bucket and key policies must allow the
  caller's principal, not a DynamoDB service principal. Unlike export to S3, output needs no
  `s3:PutObjectAcl`. To force SSE-KMS output, set `S3SseAlgorithm` to `KMS` with `S3SseKmsKeyId`,
  or rely on the bucket's default encryption; a key ID is rejected with `AES256`.
- **Existing controls don't cover it.** Denies on `dynamodb:PutItem`, `dynamodb:BatchWriteItem` or
  the read actions don't block it, `dynamodb:Put*` doesn't match it, and `dynamodb:*` grants (such
  as `AmazonDynamoDBFullAccess`) include it. It's scoped to the whole table, so write-only,
  read-restricted or tenant-scoped roles need an explicit Deny on `dynamodb:BulkPutItems`; an SCP
  or the table's resource policy can deny it too.

**`dynamodb:BulkPutItems` grants reads as well as writes.** A condition-check record includes the
existing item (`oldImage`), and the caller picks the output bucket, so treat the start actions as
read and overwrite access to every item in the table; grant them only where both are acceptable.

**Treat the buckets as copies of the table**, which TTL, deletes and erasure requests don't reach.
Keep the output bucket in the table's account under a customer managed key whose policy allows
`kms:Decrypt` only to the table's readers (`aws/s3` adds no such control). Deny requests where
`aws:SecureTransport` is false, keep Block Public Access on and ACLs disabled (bucket owner
enforced), and expire condition-check output with a lifecycle rule once reconciled. The
CloudTrail events plus the input and output are a load's only audit record: on sensitive
tables, alert on `StartBulkOperation`, log data events on the table and the output bucket, and
version the input bucket.

## Cost

Bulk put isn't billed in capacity or request units, so the Mechanics #18 formulas don't price it.
It bills per GB written, at a rate set by the performance tier and Region, counted separately for
the table and each GSI and LSI; vector index bytes are metered on their own. Failed and
condition-skipped items are billed (internal service failures aren't); reports bill at S3 rates.

`${SKILL_DIR}/scripts/calculate_costs.py` can't price a bulk load: it has no bulk operation
dimension, and it drops a preloaded corpus from storage when live writes exist.
Instead, state the basis above and send the user to the DynamoDB pricing page for their Region's
rates; never quote or invent a rate. After a run, `BulkOperationUsage` reports billed bytes per
table and index (add each `BulkPutVectorBytes` to the top-level `BulkPutBytes`, which excludes
vector indexes). For an estimate, load a sample first.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Found invalid choice 'start-bulk-put-items'`, no `start_bulk_put_items`, or MCP `call_aws` rejects it | The CLI, SDK or MCP server's bundled SDK predates the feature | Upgrade, or run from a current local CLI or SDK; the feature exists |
| `UnknownOperationException` from a current client | The feature isn't available in that Region or partition | Check the Developer Guide; use the write path there |
| `LimitExceededException` on start, or `FAILED` with `ConcurrentOperationsLimitExceeded` | 5 operations of that tier already running | Wait for one to finish, or use the other tier |
| `ResourceInUseException` on start, or on a GSI create | Another operation on the table, or an index being created | Wait; serialize loads and index work per table |
| `ValidationException` on start, Describe, or Cancel | Table is in a global table; `ACCELERATED` on a vector-indexed table or where it isn't offered; caller outside the table's account; inconsistent KMS settings; `MaxWriteRequestUnits` below 1,024 (boto3 and the CLI reject it before sending); on Cancel, the operation is already terminal | Fix the named cause (*Route the load first*); nothing to cancel |
| `ResourceNotFoundException`, or `FAILED` with `DynamoDBResourceNotFoundException` (match case-insensitively) | No such table on start, or the table was deleted mid-run; on Describe, a wrong ARN or Region, or a start over 90 days ago | Check the name, Region and account; don't delete the table mid-run |
| `AccessDeniedException` | A bulk operation action missing, a deny on `BulkPutItems`, or KMS access denied | Grant per *Security* |
| `FAILED`, `SizeLimitExceeded`, `S3ObjectsCountLimitExceeded` or `InputObjectTooLarge` | Over 100 GB on `STANDARD` or 1 TB on `ACCELERATED`; over 50,000 objects; or an object over 5,000,000,000 bytes | Split into sequential operations or use `ACCELERATED`; combine or split objects |
| `FAILED`, `Timeout` or `ObjectModifiedInS3DuringImport` | About 6.5 days elapsed, or an input object changed mid-run | Resubmit the remainder; raise the cap or split; freeze the prefix |
| `FAILED`, `ValidationException`; or `COMPLETED_WITH_ERRORS` | A record stopped its object, or records failed validation | Fix them from the `ERROR` output and manifest; resubmit the remainder |
| `FAILED`, `KmsAccessDeniedException`, `S3BucketOwnedByUnexpectedAccount` or another S3 or KMS code | The caller lacks key or bucket permissions, or `S3BucketOwner` is missing or wrong (a bucket-owner mismatch can surface under another code) | Grant access; set the bucket's account |
| `IN_PROGRESS`, counters flat for several refreshes | Output bucket owner or access, or KMS, denied | Cancel, fix, resubmit the remainder |
| `COMPLETED`, but some items unchanged | Condition skips, or duplicate keys in the input | Request `CONDITION_CHECK_FAILURE`; deduplicate |
| Waiter exits after 60 minutes while the counters still move; or stale DAX reads, `IteratorAge` climbing, flat table metrics | Expected: see *Running an operation* and *Effects on the table and downstream* | Keep polling with Describe; size consumers |
