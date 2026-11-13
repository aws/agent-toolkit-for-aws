# Snapshot management: enhanced snapshots and application snapshots (legacy)

MSF supports two snapshot types. An application uses exactly one at a time, selected by
`SnapshotMode`. The type changes which APIs work, who can restore, what survives application
deletion, and what you pay for.

- [Choose a snapshot type](#choose-a-snapshot-type)
- [Prerequisites](#prerequisites)
- [Create a new application in enhanced snapshot mode](#create-a-new-application-in-enhanced-snapshot-mode)
- [Opt in an existing application](#opt-in-an-existing-application)
- [Create and track a snapshot](#create-and-track-a-snapshot)
- [Find snapshots](#find-snapshots)
- [Restore](#restore)
- [System snapshots](#system-snapshots)
- [Delete, retention, and cost](#delete-retention-and-cost)
- [Import and export](#import-and-export)
- [IAM and AWS KMS](#iam-and-aws-kms)
- [Errors whose obvious cause is wrong](#errors-whose-obvious-cause-is-wrong)
- [Cases with no self-service path](#cases-with-no-self-service-path)
- [Reference](#reference)

## Choose a snapshot type

| | Application snapshots (legacy) | Enhanced snapshots |
|---|---|---|
| `SnapshotMode` | `APPLICATION_SNAPSHOTS_LEGACY` (default) | `ENHANCED_SNAPSHOTS` |
| Ownership | belongs to the creating application | standalone account-level resource with its own ARN |
| Restore target | only the creating application | any application in enhanced snapshot mode, same account and Region |
| Survives application deletion | no | **yes**, and keeps billing |
| Export to Amazon S3 | no | yes |
| Minimum Flink version | any | 1.20 |
| Addressed by | `SnapshotName` | `SnapshotArn` |

Recommend enhanced snapshots when the user needs any of: restore into a different application
(blue/green, A/B, clone-for-test), recovery that outlives the application, or movement of state
through S3. Otherwise legacy is adequate and requires no migration.

State the trade-off before recommending opt-in: the mode change is one-way, and enhanced snapshots
continue to accrue storage charges after the application is gone.

## Prerequisites

- Apache Flink 1.20 or later — every `RuntimeEnvironment` from `FLINK-1_20` onward. On 1.19 or
  earlier, setting `SnapshotMode` to `ENHANCED_SNAPSHOTS` returns `InvalidArgumentException`, and
  `CreateSnapshot` returns `InvalidApplicationConfigurationException`.
- A Flink runtime. `ENHANCED_SNAPSHOTS` on another runtime such as `SQL-1_0` returns
  `InvalidArgumentException`.

Read the mode from `DescribeApplication` at
`ApplicationDetail.ApplicationConfigurationDescription.ApplicationSnapshotConfigurationDescription.SnapshotMode`.
An application with no stored mode reports `APPLICATION_SNAPSHOTS_LEGACY`.

`SnapshotsEnabled` is a separate setting and keeps its meaning in both modes: it controls system
snapshots. With `SnapshotsEnabled` set to `false`, `CreateSnapshot` still works.

## Create a new application in enhanced snapshot mode

Set `ApplicationConfiguration.ApplicationSnapshotConfiguration.SnapshotMode` to
`ENHANCED_SNAPSHOTS` on `CreateApplication`. New applications do not use enhanced snapshot mode
by default, and omitting `SnapshotMode` yields `APPLICATION_SNAPSHOTS_LEGACY`. `SnapshotsEnabled`
remains mandatory in `ApplicationSnapshotConfiguration`. `CreateApplication` takes no snapshot.

```json
{
  "ApplicationSnapshotConfiguration": {
    "SnapshotsEnabled": true,
    "SnapshotMode": "ENHANCED_SNAPSHOTS"
  }
}
```

Confirm the mode in the `DescribeApplication` response before relying on it.

## Opt in an existing application

**The mode change is one-way.** No `UpdateApplication` returns the application to legacy mode;
setting `SnapshotModeUpdate` back to `APPLICATION_SNAPSHOTS_LEGACY` returns
`InvalidArgumentException`. The only reversal is `RollbackApplication` to the version before
opt-in, and it works only while the opt-in is still the most recent update. **Any later
application update closes that window permanently.** Tell the user this before they opt in, and
have them record the current `ApplicationVersionId`.

Opt in by setting
`ApplicationConfigurationUpdate.ApplicationSnapshotConfigurationUpdate.SnapshotModeUpdate` to
`ENHANCED_SNAPSHOTS`. Send `SnapshotsEnabledUpdate` in the same request — the API requires it even
when only the mode changes.

### Opt in while the application is RUNNING

`READY` and `RUNNING` are both permitted, but they behave differently and only one preserves
state.

**Opt in from `RUNNING`.** MSF takes a legacy application snapshot of the current version — the
*boundary capture* — and restarts the application in enhanced snapshot mode from it. The response
carries an `OperationId`.

**Opting in from `READY` loses state.** MSF takes no snapshot, returns no `OperationId`, and the
next `RESTORE_FROM_LATEST_SNAPSHOT` finds no enhanced snapshot and starts the application without
state. After opt-in a legacy snapshot can no longer be restored by name, so the state is
unreachable. If the application is `READY` and its state matters, start it, wait for `RUNNING`,
then opt in.

**`SnapshotsEnabled` must be `true` at opt-in.** With it `false`, MSF takes no boundary capture and
restarts from the newest **`READY`** snapshot that already exists — either a legacy application
snapshot or an enhanced one — which holds state from whenever that snapshot was taken, not current
state. A snapshot still `CREATING`, or one that `FAILED`, is not a candidate. With no `READY`
snapshot at all, the application starts with no state. Confirm `SnapshotsEnabled` is `true` in
`DescribeApplication` first, and set `SnapshotsEnabledUpdate` to `true` in the opt-in request.

Opt-in does not copy or convert snapshot data. Existing legacy snapshots are left as they are.

### Procedure

1. Record `ApplicationVersionId` and confirm
   `ApplicationSnapshotConfigurationDescription.SnapshotsEnabled` is `true`, with
   `aws kinesisanalyticsv2 describe-application --application-name MyApplication`.

2. Send the opt-in. Save the request as `opt-in.json`, setting `CurrentApplicationVersionId` to
   the version recorded in step 1. A stale value — or a stale `ConditionalToken`, if you use one —
   returns `ConcurrentModificationException`, so re-read the version rather than reusing one from
   an earlier step. Do not include a restore configuration unless the application is `RUNNING`;
   that combination returns `InvalidArgumentException`.

   ```json
   {
     "ApplicationName": "MyApplication",
     "CurrentApplicationVersionId": 3,
     "ApplicationConfigurationUpdate": {
       "ApplicationSnapshotConfigurationUpdate": {
         "SnapshotsEnabledUpdate": true,
         "SnapshotModeUpdate": "ENHANCED_SNAPSHOTS"
       }
     }
   }
   ```

   Send it with `aws kinesisanalyticsv2 update-application --cli-input-json file://opt-in.json`.

3. For a `RUNNING` application, poll the returned `OperationId` with
   `describe-application-operation` until the status is `SUCCESSFUL` or `FAILED` — note
   `CANCELLED` is also terminal. A `READY` application returns no `OperationId`; skip this step.

4. Wait for the application status to return to `RUNNING`.

5. **Create an enhanced snapshot immediately**, with `create-snapshot`. Until it reaches `READY`
   the application has no enhanced snapshot, and `RESTORE_FROM_LATEST_SNAPSHOT` would start it
   without state. Poll `describe-snapshot` until `SnapshotInfoDetails.SnapshotStatus` is `READY`.

6. Confirm `SnapshotMode` is `ENHANCED_SNAPSHOTS` with `describe-application` as in step 1.

7. Update tooling, pipelines, and IAM policies to the enhanced snapshot APIs.

### What stops working after opt-in

| Action | Result |
|---|---|
| `CreateApplicationSnapshot` | `InvalidApplicationConfigurationException`; use `CreateSnapshot` |
| Restore with `RESTORE_FROM_CUSTOM_SNAPSHOT` and `SnapshotName`, called directly | `InvalidApplicationConfigurationException` — use `SnapshotArn` |
| Export a legacy snapshot | unsupported |
| `ListApplicationSnapshots`, `DescribeApplicationSnapshot`, `DeleteApplicationSnapshot` | continue to work on existing legacy snapshots |

`ListApplicationSnapshots` returns only legacy snapshots and `ListSnapshots` returns only enhanced
snapshots. **Neither returns both**, so an inventory after opt-in requires both calls.

The `SnapshotName` row above holds for a direct API call. CloudFormation behaves differently — it
substitutes a latest-snapshot restore rather than forwarding the invalid combination, so the stack
update succeeds on unexpected state instead of failing. See
[Opt in a CloudFormation-managed application](#opt-in-a-cloudformation-managed-application).

### Recovering a failed opt-in

With system rollbacks on
(`ApplicationConfigurationUpdate.ApplicationSystemRollbackConfigurationUpdate.RollbackEnabledUpdate`
set to `true`), MSF returns the application to `RUNNING` on the pre-opt-in version in legacy mode.

With system rollbacks off, the operation status is `FAILED`, the application stays `READY`, and
`SnapshotMode` stays `ENHANCED_SNAPSHOTS`. **Call `RollbackApplication`, not `StartApplication`.**
Starting with `RESTORE_FROM_LATEST_SNAPSHOT` in this state starts the application without state.

A rollback restores the newest `READY` legacy snapshot at or below the pre-opt-in version, which
is the boundary capture when that capture is `READY`. Enhanced snapshots created after opt-in
survive the rollback, and the application can use them again — but only after it is upgraded to
enhanced snapshot mode a second time. The state is parked, not stranded, so do not tell a customer
that rolling back destroys it or that recovering it needs Support.

### Opt in a CloudFormation-managed application

**Opt in through the template, not the API, when a stack manages the application.** Set
`SnapshotMode` in `ApplicationConfiguration.ApplicationSnapshotConfiguration` alongside
`SnapshotsEnabled`:

```yaml
ApplicationConfiguration:
  ApplicationSnapshotConfiguration:
    SnapshotsEnabled: true
    SnapshotMode: ENHANCED_SNAPSHOTS
```

Four consequences to state before the stack update runs, because the one-way rule interacts badly
with normal stack behaviour:

- **The CloudFormation role needs `kinesisanalytics:RestoreFromSnapshot` and
  `kinesisanalytics:CreateSystemSnapshot`.** Without them the stack update fails with
  `AccessDenied`. This is the most common cause of a failed opt-in by template.
- Changing the template back to `APPLICATION_SNAPSHOTS_LEGACY` later fails the stack update with
  `InvalidRequest`. The mode is one-way here too.
- **A stack rollback does not return the application to legacy mode.** It stays in enhanced
  snapshot mode, so the template and the deployed application diverge until the template is
  corrected.
- **A `SnapshotName` restore fails loudly through the API but silently changes meaning through
  CloudFormation.** Called directly on an enhanced-mode application, `SnapshotName` returns
  `InvalidApplicationConfigurationException` — see
  [What stops working after opt-in](#what-stops-working-after-opt-in). CloudFormation does not
  forward that combination: if the rollback template restores by `SnapshotName`, CloudFormation
  **substitutes a restore from the latest snapshot**, so the stack update succeeds and the
  application comes up on different state than the template names. The CloudFormation path is the
  more dangerous of the two precisely because nothing errors. Use `SnapshotArn` in
  `RunConfiguration.ApplicationRestoreConfiguration` to pin a specific snapshot.

`AWS::KinesisAnalyticsV2::Snapshot` manages individual enhanced snapshots as stack resources. The
usual caution applies: a snapshot deleted by a stack update is gone, and the stack's own role needs
the snapshot permissions. General MSF IaC guidance is in
[iac-and-deployment.md](iac-and-deployment.md).

## Create and track a snapshot

`CreateSnapshot` takes `ApplicationName` and `SnapshotName`, plus optional `SnapshotDescription`
and `Tags`. The application must be `RUNNING`. Names are unique per account and Region.

**Up to 50 tags.** A request with 51–200 tags returns `TooManyTagsException`; more than 200 returns
`ValidationException`. The same limit applies to `ImportSnapshot`. Sending `Tags` also requires
`kinesisanalytics:TagResource` on the new snapshot's ARN in addition to the create or import
permission — if either is denied the request returns `AccessDeniedException` and **no snapshot is
created**.

**`CreateSnapshot` is asynchronous. A success response is not a usable backup.** The response
returns `SnapshotArn`, `SnapshotStatus` of `CREATING`, `SnapshotOperationId`, and
`SnapshotOperationStatus`. If the work fails later, no exception is raised — the snapshot moves to
`FAILED` and the failure is reported on the snapshot operation.

Poll `DescribeSnapshot` until `SnapshotStatus` is `READY` before treating the snapshot as a
backup, and before calling `UpdateApplication`.

**The operation has four terminal states, not three, and the common failures land in the one that
carries no detail.** `SnapshotOperationStatus` is `IN_PROGRESS`, `SUCCESSFUL`, `FAILED`, or
`CANCELLED`. A `CANCELLED` operation has **no `ErrorCode` and no `ErrorString`** — and MSF routes
the three most frequent `CreateSnapshot` failures there: the application was not `RUNNING`, its
version changed, or another application operation interrupted the snapshot. The snapshot itself
still ends `FAILED`; a snapshot is never `CANCELLED`.

So when a create fails, read the *operation* status first and branch on it:

- `FAILED` — call `DescribeSnapshotOperation` with the `SnapshotOperationId` and read
  `SnapshotOperationFailureDetails.ErrorInfo`, which holds `ErrorCode` and `ErrorString`. Treat
  `ErrorCode` as an open string, not an enum; handle values you do not recognise.
- `CANCELLED` — there are no failure details to read. Diagnose from the application instead:
  check its status and whether an operation ran concurrently. Do not report "unknown error" when
  the cause is almost always one of the three above.

Any polling loop written against `SUCCESSFUL` or `FAILED` alone never terminates on a cancelled
operation. The same applies to application operations, whose `OperationStatus` also includes
`CANCELLED`.

There is no `DELETED` status; after a delete completes `DescribeSnapshot` returns
`ResourceNotFoundException`. `CreateSnapshot`, `DeleteSnapshot`, `ImportSnapshot`, and
`ExportSnapshot` are all asynchronous, and imports and exports cannot be cancelled.

**Operation records expire, and deleting the snapshot destroys them.** MSF keeps a record for 90
days after the operation ends, and once the snapshot is deleted its operation records are
unreachable. The advice below to delete a `FAILED` snapshot to free its name therefore destroys the
only evidence of why it failed — capture `DescribeSnapshotOperation` output first.

`ListSnapshotOperations` lists the operations on a snapshot and is the only way to obtain an
operation ID you do not already hold. That matters for system snapshots, because CloudTrail does
not log operations MSF starts itself: to trace one, call `ListSnapshotOperations` with
`SnapshotOperation` set to `SystemCreateSnapshot`. The filter is exact-match, so a `CreateSnapshot`
filter excludes `SystemCreateSnapshot`, and as with `ListSnapshots` only one filter is allowed per
request.

A `FAILED` snapshot keeps its name until deleted, so retrying with the same name returns
`ResourceInUseException`. Delete the failed snapshot or choose a new name.

Only one snapshot per application may be in `CREATING` at a time; the next `CreateSnapshot`
returns `ResourceInUseException`.

### Names and ARNs

The ARN format is `arn:{partition}:kinesisanalytics:{region}:{account-id}:snapshot/{snapshot-name}`
and does not contain the application name. Names are **1–100** characters of letters, digits,
underscores, periods, and hyphens. (Legacy application snapshot names allow 256; do not carry that
limit over to enhanced snapshots, and do not generate a name from a long application name plus a
timestamp without checking the length.)

**`SYSTEMSNAPSHOT` is a reserved prefix.** A `CreateSnapshot` or `ImportSnapshot` name beginning
with it, in any mix of upper and lower case, returns `InvalidArgumentException` — not
`ResourceInUseException`. This is easy to hit when re-importing a savepoint that was exported from
a system snapshot and the obvious name is the original one.

A name stays reserved in every status, including `FAILED`, until the snapshot is deleted. Because
the ARN contains only the name, **a new snapshot reusing a deleted snapshot's name has the same
ARN**, so any IAM policy naming that ARN — including `kinesisanalytics:RestoreFromSnapshot` —
applies to the new, unrelated state. Tags do not carry over.

## Find snapshots

**`ListSnapshots` lists enhanced snapshots across the entire account.** Scope it to one
application with the `SourceApplicationName` filter. `ApplicationName` is not a filter for this
API; MSF ignores it and returns every snapshot in the account. Automation built on the wrong key
operates on other applications' snapshots and system snapshots as well as its own.

```bash
aws kinesisanalyticsv2 list-snapshots \
    --source-application-name MyApplication --limit 50
```

Four filters exist: `SourceApplicationName`, `SnapshotInitiator` (`USER` or `SYSTEM`),
`SnapshotInitiatorOperation` (`CreateSnapshot`, `ImportSnapshot`, or `SystemCreateSnapshot`), and
`SnapshotStatus`. **At most one per call** — two or more returns `InvalidArgumentException`, so
combine conditions in the caller. Note `SnapshotInitiator: USER` covers both created *and*
imported snapshots; `SnapshotInitiatorOperation` is the filter that separates them.

Unfiltered, the list includes snapshots you create, snapshots you import, and system snapshots.
Results come newest first by `SnapshotCreationTimestamp` with no sort parameter. `Limit` accepts
1–50; out of range returns `ValidationException`. `NextToken` is opaque, and an invalid value
returns `InvalidArgumentException`.

### Imported snapshots cannot be attributed to an application

An imported enhanced snapshot has **no source application**, so
`ListSnapshots --source-application-name` **never returns it** — it is reachable only through an
unfiltered list, or by `SnapshotInitiatorOperation: ImportSnapshot`.

This is an inventory trap for exactly the workflows imports exist to serve. Snapshot tooling that
enumerates per application — retention sweeps, DR inventories, cost attribution — will silently
omit every imported snapshot. Enumerate unfiltered and treat missing attribution as "imported"
rather than as "orphaned", and never drive a delete sweep off a per-application list alone.

### Describe and list return different fields

`DescribeSnapshot` takes `SnapshotName` only, with no `ApplicationName`, and returns
`SnapshotInfoDetails`. `ListSnapshots` returns `SnapshotInfoList` entries, which carry a **smaller
and differently named** field set. Do not expect a describe field to appear in list output.

| Attribution field | `DescribeSnapshot` | `ListSnapshots` |
|---|---|---|
| Source | `SnapshotSourceDescription` — always present, but a union: `SourceApplicationDescription` (with `ApplicationName`, `ApplicationCreationTimestamp`, `ApplicationVersionId`) for created and system snapshots, `S3PrefixLocation` for imported ones | `SourceApplicationName`, **absent for imported snapshots** |
| Runtime | `RuntimeEnvironment`, **absent for imported snapshots** | not returned |

Two consequences worth stating plainly:

- `SnapshotSourceDescription` is always present but is **not always an application name**. Code
  that reads `SourceApplicationDescription.ApplicationName` unconditionally breaks on an imported
  snapshot, where the union holds an S3 location instead. Branch on the member present.
- An imported snapshot reports **no runtime of its own**, so you cannot read its
  `RuntimeEnvironment` back to sanity-check compatibility before restoring. Combined with the fact
  that MSF does not validate an imported snapshot's runtime against the target application, there
  is no API-level check available on either side — version and operator compatibility has to be
  established out of band. See [Import](#import).

## Restore

Set `ApplicationRestoreConfiguration` on `StartApplication` or `UpdateApplication`. For an
enhanced snapshot, set `SnapshotArn`; for a legacy snapshot, set `SnapshotName`. With
`RESTORE_FROM_CUSTOM_SNAPSHOT`, set exactly one of them — both or neither returns an error.

`ApplicationRestoreType` options:

- `RESTORE_FROM_CUSTOM_SNAPSHOT` with `SnapshotArn` — a specific enhanced snapshot
- `RESTORE_FROM_LATEST_SNAPSHOT` — the newest `READY` enhanced snapshot **that this same
  application created**. The selection never includes a snapshot you imported, nor one another
  application created. **MSF does not fall back to a legacy snapshot.** With no eligible `READY`
  enhanced snapshot, the application starts without state and no error is returned.

  These two facts compose into a silent failure that is easy to walk a customer into: import a
  savepoint, then start the application with `RESTORE_FROM_LATEST_SNAPSHOT`, and it comes up with
  **no state and no error**, because the imported snapshot was never a candidate. To restore an
  imported snapshot, always use `RESTORE_FROM_CUSTOM_SNAPSHOT` with its `SnapshotArn`.
- `SKIP_RESTORE_FROM_SNAPSHOT` — start with no state, the recommended escape when state cannot be
  restored

Restoring into a different application requires the same account and Region, and state compatible
with the target's operators. Verify compatibility before restoring into a live application.

For state that does not match the current operators, set `AllowNonRestoredState` to `true` in
`FlinkRunConfiguration`. An added operator does not fault the application even when the flag is
`false`; a deleted operator faults it unless the flag is `true`. A faulted restore leaves the
application in `STARTING` or `UPDATING`.

Two preconditions MSF does enforce, and one it does not:

- the snapshot must be `READY`, or the call returns `ResourceInUseException`
- for a snapshot **an application created**, MSF validates the Flink runtime against the target and
  returns `InvalidArgumentException` on a mismatch
- for an **imported** snapshot there is no runtime check at all, in either direction — see the
  import section. Never restore an imported snapshot into an application running an *older* Flink
  version than the one that produced it: the older runtime may misread the state, and the restore
  can lose or corrupt data rather than fail cleanly.

A restore of a snapshot encrypted with a customer managed key also has KMS requirements on the
caller and on the key policy, which are a common cause of `AccessDeniedException` here; see
[IAM and AWS KMS](#iam-and-aws-kms).

For two-phase-commit sinks, prefer system snapshots over snapshots created with `CreateSnapshot`.

## System snapshots

In enhanced snapshot mode with `SnapshotsEnabled` set to `true`, MSF creates a system snapshot —
itself an enhanced snapshot — when it stops or updates a **`RUNNING`** application, and when it
adds or deletes a VPC configuration or a CloudWatch logging option on a `RUNNING` application.
Start, rollback, and delete do not create one. In legacy mode, scaling also creates one; in
enhanced snapshot mode it does not.

**A `StopApplication` request with `Force` set to `true` takes no system snapshot.** Force stop is
the usual escape for a wedged application, so say this plainly before recommending one: the stop
captures no state, and whatever has accumulated since the last snapshot is lost. If the state
matters, take a `CreateSnapshot` first and wait for `READY`, or accept the loss deliberately.

Names follow `SYSTEMSNAPSHOT-{OPERATION}-{application-id}-{timestamp-ms}`, with a 13-digit epoch
millisecond timestamp — for example `SYSTEMSNAPSHOT-STOP-18ff3b175f881462-1794548104576`. **The
middle field is an opaque hexadecimal application id, not the application name**, so a system
snapshot cannot be matched to an application by name alone; use `ListSnapshots` with
`SourceApplicationName` instead.

Fields are `SnapshotInitiator` of `SYSTEM` and `SnapshotInitiatorOperation`
of `SystemCreateSnapshot`; only the name identifies the originating operation.

List them with `ListSnapshots` and `SnapshotInitiator` set to `SYSTEM`.

A successful system snapshot produces one `SUCCESSFUL` snapshot operation. **A failed system
snapshot produces no snapshot operation at all**, so absence is not evidence of success. The
`DescribeSnapshotOperation` response for a system snapshot includes
`ApplicationOperationDescription`; pass its `ApplicationOperationId` and `ApplicationName` to
`DescribeApplicationOperation` for detail.

**A system snapshot inherits the application's tags** as they stand when MSF creates it, copied
before the snapshot appears in `ListSnapshots`. If the application has no tags, neither does the
system snapshot. You cannot pass tags for a system snapshot, since you do not make the call; adjust
them afterwards with `TagResource` on the snapshot ARN. `UntagResource` and `ListTagsForResource`
also take a snapshot ARN.

Tag inheritance is what makes tag-based retention and cost allocation work across system snapshots,
so recommend tagging the *application* if the user wants either.

## Delete, retention, and cost

`DeleteSnapshot` takes `SnapshotName` and `SnapshotCreationTimestamp`, with no `ApplicationName`.
Copy the timestamp from `DescribeSnapshot`; a mismatch returns `InvalidArgumentException`.

```bash
aws kinesisanalyticsv2 delete-snapshot \
    --snapshot-name MyApplication-snapshot-1 \
    --snapshot-creation-timestamp 1767225600.0
```

Confirm with the user before running this. The delete is permanent and the guard below does not
protect a snapshot that is merely needed later.

**Delete protection covers concurrent operations only, not operational need.** `DeleteSnapshot`
returns `ResourceInUseException` when the snapshot is not in `READY` or `FAILED` status, and while
any snapshot operation on it is in progress — an export in particular. The message names the
cause: *"Snapshot 'X' has 1 In progress snapshot operations and cannot be deleted. Use
ListSnapshotOperations to view in progress operations."* Retry once that operation reaches a
terminal status; the delete then succeeds.

A running application does **not** block the delete, and neither does an
`ApplicationRestoreConfiguration` naming the snapshot.

After deletion, a later `RESTORE_FROM_CUSTOM_SNAPSHOT` naming it fails. A later
`RESTORE_FROM_LATEST_SNAPSHOT` or `RollbackApplication` does not fail — it silently selects the
newest remaining `READY` enhanced snapshot that meets the selection rules, which may be much older
state. So a retention sweep must keep at least one qualifying snapshot, or a rollback quietly
restores further back than the user expects. Confirm with the user that the snapshot is not needed
before deleting.

The snapshot operation for a `DeleteSnapshot` request is never `FAILED`.

MSF never expires or prunes enhanced snapshots on a schedule — retention is the customer's
responsibility. **Enhanced snapshots, including system snapshots, remain after the application is
deleted** and keep accruing storage charges until each is deleted individually. Recommend a
retention process whenever an application in enhanced snapshot mode is created or decommissioned.

Storage bills at the same rate as legacy snapshots, under the usage type
`{region}-DurableApplicationBackups`. Billing starts when a snapshot reaches `READY` and stops when
it moves to `DELETING`; `CREATING` and `FAILED` are not billed. Resolve the current rate from the
documentation or the Price List API rather than quoting one from memory.

Imports and exports carry no MSF transfer charge, but **S3 charges apply to the bucket** an import
reads or an export writes, so a total-cost answer has to include them.

If a remaining snapshot uses a customer managed key, the creating application's ARN must stay in
the key policy even after that application is deleted. Without it the snapshot can be neither
restored nor exported.

## Import and export

`ExportSnapshot` writes an enhanced snapshot to S3; `ImportSnapshot` creates one from S3. Both are
asynchronous and return a `SnapshotOperationId`. An export does not change the snapshot's status,
and a failed export leaves it `READY`. Both work whether or not an application is in enhanced
snapshot mode.

**Both work within one account and one Region**: the bucket must be in the same account and Region
as the enhanced snapshot.

An exported snapshot is the application's full state, so treat the bucket as holding the
application's data. Encrypt in transit as well as at rest: deny plaintext requests with a bucket
policy condition on `aws:SecureTransport` being `false`, alongside the key choices below.

### MSF needs its own role, passed in the request

This is the step that is easy to miss, and the call fails without it. Import and export are not
authorised on the caller alone — **MSF assumes a role you supply in the request body** to reach
the bucket, as `ExportRoleArn` or `ImportRoleArn`.

Four things are required together:

1. **A role trusting `kinesisanalytics.amazonaws.com`.** MSF sets `aws:SourceAccount` (the account
   ID) and `aws:SourceArn` when it assumes the role, so condition on both. `aws:SourceArn` is the
   ARN of the snapshot being exported, or — on import — the ARN of the snapshot the request is
   about to **create**. AWS documents `ArnEquals` on one full snapshot ARN; that is the default to
   recommend, since import and export are same-account only and a `snapshot/*` wildcard leaves
   `aws:SourceArn` contributing nothing beyond `aws:SourceAccount`.
2. **One of four permissions policies on that role** — import, import-with-KMS, export, or
   export-with-KMS. The branch is whether a customer managed key is involved. Details below.
3. `iam:PassRole` on that role for the calling principal, conditioned with
   `iam:PassedToService` of `kinesisanalytics.amazonaws.com` so the role cannot be handed to
   another service.
4. `kinesisanalytics:ExportSnapshot` on the snapshot being exported, or
   `kinesisanalytics:ImportSnapshot` on the snapshot ARN the import will create. With `Tags`, also
   `kinesisanalytics:TagResource` on that ARN.

The console can create this role, which is usually the faster route than hand-authoring it.

**Do not hand-write these policies from memory — they have non-obvious shapes.** Copy them from
[Identity and access management for enhanced snapshots](https://docs.aws.amazon.com/managed-flink/latest/java/security-iam-snapshots.html),
which carries the trust policy and all four permissions policies in full. The parts most often got
wrong:

- Every S3 and KMS statement carries an `aws:ResourceAccount` condition naming the account that
  owns the bucket or key.
- Both roles need `s3:ListBucket` **and `s3:GetBucketLocation`** on the bucket — MSF uses them
  before every transfer to check the bucket exists, check its owner, and get its Region.
- Export additionally needs `s3:PutObject`, `s3:GetObject`, `s3:AbortMultipartUpload` and
  `s3:ListMultipartUploadParts` on the prefix, plus `s3:ListBucketMultipartUploads` **on the
  bucket**. It does not need `s3:DeleteObject`.
- Import needs `s3:GetObject` and `s3:GetObjectAttributes` on the source prefix.
- With a customer managed key, the role needs **two separate statements** on that key, not one.
  One covers the request S3 makes on the role's behalf and conditions `kms:ViaService` with
  `StringEquals`. The other covers the permission check MSF makes **directly** on the key and must
  use `StringEqualsIfExists` for `kms:ViaService`, because that call does not pass through S3. A
  single `StringEquals` statement denies MSF's direct check and the transfer fails.
- `kms:ViaService` takes `s3.{region}.amazonaws.com` in these role policies, and
  `kinesisanalytics.{region}.amazonaws.com` in key policies. They are not interchangeable.
- `kms:EncryptionContext:aws:s3:arn` uses `StringLike` with a trailing `*`. Written as
  `StringEquals` on the bucket ARN it denies whenever S3 Bucket Keys is off.
- The import role needs `kms:GenerateDataKey` on the source key as well as `kms:Decrypt`, which is
  counterintuitive for a read-only operation but is what MSF's direct check requires.

### Export

`ExportDestinationConfiguration` is the parameter. Three of its members are required —
`DestinationType`, `ExportRoleArn`, and `DestinationS3PrefixLocation` — and
`DestinationEncryptionConfiguration` is optional, defaulting to `AWS_OWNED_KEY`. Set it anyway;
see below. There is no flat `--destination-s3-configuration`; a request shaped that way does not
export.

```json
{
  "SnapshotName": "MyApplication-snapshot-1",
  "ExportDestinationConfiguration": {
    "DestinationType": "S3",
    "ExportRoleArn": "arn:aws:iam::ACCOUNT_ID:role/MSFSnapshotExportRole",
    "DestinationEncryptionConfiguration": {
      "KeyId": "arn:aws:kms:REGION:ACCOUNT_ID:key/KEY_ID",
      "KeyType": "CUSTOMER_MANAGED_KEY"
    },
    "DestinationS3PrefixLocation": {
      "BucketARN": "arn:aws:s3:::amzn-s3-demo-bucket",
      "KeyPrefix": "exports/my-app/"
    }
  }
}
```

Send it with `aws kinesisanalyticsv2 export-snapshot --cli-input-json file://export.json`.

The snapshot must be `READY`, or `ExportSnapshot` returns `ResourceInUseException`. A legacy
application snapshot cannot be exported.

**End `KeyPrefix` with `/`.** MSF appends the operation ID directly after the prefix, so without
the slash the objects land at a sibling prefix formed by concatenation — `exports/my-appABC123/`
rather than `exports/my-app/ABC123/`. `KeyPrefix` is 1–200 characters.

**`KeyId` must be a full KMS key ARN** on both import and export. A bare key ID or an alias returns
`InvalidArgumentException`. This is worth stating explicitly because the application-level
encryption config accepts key IDs and aliases, so the obvious generalisation is wrong here.

**Where the files land, and why it matters for a later import.** MSF writes the savepoint under
`{KeyPrefix}{SnapshotOperationId}/data/` — one level below the prefix you supplied, under a
directory named for the operation. `ExportedPrefix` holds that full path, read from
`SnapshotDestinationLocationDescription.S3PrefixLocation.ExportedPrefix` on
`DescribeSnapshotOperation`. **`SnapshotDestinationLocationDescription` is present while the export
runs, but carries only `BucketARN` and the `KeyPrefix` you supplied; `ExportedPrefix` is the member
that appears once the operation ends**, on success and on failure alike. So polling for the block
itself never resolves — poll for `ExportedPrefix` within it.

So to re-import something you exported, point the import at `ExportedPrefix` — the `.../data/`
directory — **not** at the `KeyPrefix` you handed to the export. Pointing at the original prefix
finds no `_metadata` and fails.

**Set `DestinationEncryptionConfiguration` with a customer managed key, as above, even though it
is optional.** Omit it and MSF uses `AWS_OWNED_KEY`, which `DescribeSnapshotOperation` then
reports as the destination key type — so the exported application state ends up under a key the
customer does not control, silently and without an error. `KeyId` applies only when `KeyType` is
`CUSTOMER_MANAGED_KEY`, and must be the key ARN. Where the objects land under a KMS key, the
**export role** needs `kms:GenerateDataKey` and `kms:Decrypt` on it — see
[IAM and AWS KMS](#iam-and-aws-kms) for the two-statement shape those grants require.

An export involves **two** keys, which is where encryption-context values go wrong: the
destination key protecting the written S3 objects, keyed by the snapshot ARN; and the key of the
enhanced snapshot itself, keyed by the ARN of the **application that created it** (or the snapshot
ARN if it was imported).

### Import

`ImportSourceConfiguration` requires `SourceType`, `ImportRoleArn`, and `SourceS3PrefixLocation`.
For the full request and response, see
[Enhanced snapshot API examples](https://docs.aws.amazon.com/managed-flink/latest/java/snapshots-api-examples.html).

**Three encryption parameters are in play, and two of them are easy to confuse.** On export,
`DestinationEncryptionConfiguration` nests *inside* `ExportDestinationConfiguration` and keys the
exported S3 objects. On import the parameter of the same name sits at the *top level*, beside
`ImportSourceConfiguration`, and keys the newly created snapshot instead. The asymmetry is in
placement and in what gets keyed, **not** in whether it is required: it is optional in both
directions, and omitting it in either silently falls back to an AWS owned key, so set it
explicitly on both calls. The third, `SourceEncryptionConfiguration`, nests inside
`ImportSourceConfiguration` and names the key already protecting the objects being read.

`SnapshotName` must not already exist in the account and Region, or `ImportSnapshot` returns
`ResourceInUseException`.

Source requirements, validated after the request is accepted rather than at call time:

- a savepoint, not a checkpoint
- **relocatable** — no absolute paths to its original location; otherwise the operation fails with
  `InvalidSnapshotMetadata`
- `_metadata` present under the prefix, or `ImportSnapshot` returns `InvalidArgumentException`
- a full-object `CRC64NVME` checksum on every object. Files written by `ExportSnapshot` already
  satisfy this
- the **canonical** savepoint format, which is identical across Flink state backends. MSF cannot
  import a savepoint written in the *native* format, which is specific to one backend. This is
  the one requirement a self-managed Flink cluster is most likely to miss, because native is a
  per-savepoint choice at write time — so check how the source savepoint was taken before
  planning a migration around import
- a `SnapshotName` that does not start with `SYSTEMSNAPSHOT`, in any case, or `ImportSnapshot`
  returns `InvalidArgumentException`
- a `KeyPrefix` of 1–200 characters

Unlike export, import has **no** trailing-slash requirement on `KeyPrefix`.

Do not modify or delete source objects during the import: a changed object fails with
`S3PreconditionFailed`, a deleted one with `S3NoSuchKey`.

`SnapshotFormat` is an optional request member with a single value, `CANONICAL`, so there is
nothing to choose; it appears on every snapshot in `DescribeSnapshot` and `ListSnapshots`
responses.

**Set `SourceEncryptionConfiguration` when a customer managed key encrypts the source objects.**
It is optional, but omitting it means MSF cannot validate the source key at request time, so a key
problem surfaces later as an asynchronous `KMSConfigError` on the operation instead of an immediate
`AccessDeniedException`. Note it nests **inside** `ImportSourceConfiguration`, beside `SourceType`
and `ImportRoleArn` — unlike `DestinationEncryptionConfiguration`, `SnapshotDescription`,
`SnapshotFormat`, and `Tags`, which are top-level members of the request.

**An imported snapshot carries no runtime and no source application.** `RuntimeEnvironment` is
absent from `DescribeSnapshot`, `SourceApplicationName` is absent from `ListSnapshots`, and
`SnapshotSourceDescription` holds an `S3PrefixLocation` rather than an application. So MSF does not
validate the snapshot's runtime against the target application, **and** you cannot read the
snapshot's own runtime back to check it yourself — there is no API-level check on either side. (For
a snapshot an *application* created, MSF does validate the runtime and returns
`InvalidArgumentException` on a mismatch; only the imported case is unchecked.)

**Never restore an imported snapshot into an application on an older Flink version than the one
that created it.** With no runtime check, nothing stops the call: the older runtime may misread the
state and the restore can lose or corrupt data rather than fail. Establish Flink version and
operator compatibility out of band before restoring a live application from an imported snapshot,
and see
[Imported snapshots cannot be attributed to an application](#imported-snapshots-cannot-be-attributed-to-an-application)
for the inventory consequences.

### Failure cleanup and limits

**A failed export leaves written objects and incomplete multipart uploads in the bucket, and MSF
does not clean them up.** Read `ExportedPrefix`, which is populated on failure too, and delete
what is there. Recommend an S3 lifecycle rule to abort incomplete multipart uploads, with a day
count above the longest expected export — a shorter one aborts a live export with `S3NoSuchUpload`.

Concurrency: one export in progress per snapshot across all destinations, and 10 imports and
exports combined per account per Region. Both return `LimitExceededException`. Back off rather
than retrying tightly. Neither an import nor an export can be cancelled.

## IAM and AWS KMS

Enhanced snapshot APIs are authorised on the **caller**, using actions under the
`kinesisanalytics:` prefix with no `v2`. The service execution role needs no changes.

**Nearly every action is checked on the snapshot ARN, but the two create actions are checked on the
application ARN** — `CreateSnapshot` and `CreateSystemSnapshot`. That split is the one people get
wrong; `ListSnapshots` is the other exception, requiring `"*"`. Legacy application snapshots are
not IAM resources at all, so a policy spanning a migration needs application ARNs for those.

**`kinesisanalytics:RestoreFromSnapshot` is denied by default, even for a snapshot the caller's own
application created.** It is granted on the snapshot ARN, not the application ARN, and
application-level permissions do not imply it. This is the most common cause of an `AccessDenied`
on restore.

It is checked by the application lifecycle APIs: `StartApplication` in any status;
`RollbackApplication` for a `RUNNING`, `UPDATING`, or `AUTOSCALING` application; and
`UpdateApplication`, the VPC configuration requests, and the CloudWatch logging option requests for
a `RUNNING` application. **`RollbackApplication` needing it matters**, because it is the recovery
path for a failed opt-in — a policy that omits it blocks the documented recovery.

It is not checked when `ApplicationRestoreType` is `SKIP_RESTORE_FROM_SNAPSHOT`. For
`RESTORE_FROM_LATEST_SNAPSHOT` with `SnapshotsEnabled` set to `true`, `UpdateApplication` and the
VPC and logging-option requests skip the check, because the snapshot they restore from is the
system snapshot the request itself creates, which does not exist yet at authorisation time.

With `SnapshotsEnabled` set to `false`, those APIs check the permission on the selected snapshot
**and** on any snapshot of the application still in `CREATING`. A policy scoped only to `READY`
snapshots therefore denies intermittently, depending on whether a create happens to be in flight.

`kinesisanalytics:CreateSystemSnapshot` is a different action with a different resource, and the
two are easy to conflate: it applies on the **application** ARN, and applies only to an application
in enhanced snapshot mode with `SnapshotsEnabled` set to `true`. It is required by
`StartApplication` in any status, and — for a `RUNNING` application only — by `StopApplication`,
`UpdateApplication`, and adding or deleting a VPC configuration or CloudWatch logging option. A
`StopApplication` request with `Force` set to `true` does not need it.

**`UpdateApplication` triggers it on either of two conditions, not both.** The request needs the
action if it sets or keeps enhanced snapshot mode, **and separately** if `SnapshotsEnabled` is
`true` after the update. Treating these as a conjunction produces a policy that is too narrow and
denies some updates. On an opt-in request, MSF authorises against the request's
`SnapshotsEnabledUpdate` value rather than the application's current one.

`CreateApplication` and `RollbackApplication` never check `CreateSystemSnapshot`. Note this is not
a contradiction of the rollback note above: `RollbackApplication` **does** check
`RestoreFromSnapshot` and **does not** check `CreateSystemSnapshot`, so a recovery policy needs the
former and not the latter.

`kinesisanalytics:ListSnapshots` requires `"*"` as its resource, even when called with
`SourceApplicationName`.

### Customer managed keys

MSF does not run any of these checks for an AWS owned key. With a customer managed key, the
**caller** needs `kms:Decrypt` and `kms:GenerateDataKey` on the key for every operation, plus
`kms:DescribeKey` for restore and `ExportSnapshot` but **not** for `CreateSnapshot` or
`ImportSnapshot`. Missing any returns `AccessDeniedException`. The `CreateSnapshot` exception
matters for diagnosis: a denied create is never a missing `kms:DescribeKey`.

**"Keep the existing key policy" is not sufficient.** The application's key policy already grants
the `kinesisanalytics.amazonaws.com` and `infrastructure.kinesisanalytics.amazonaws.com` service
principals — the latter only on `kms:DescribeKey` — but import, export, and cross-application
restore all need statements it does not have. Two cases to flag:

- **Import and export** need key-policy statements for the *calling* principal, plus service
  statements scoped by `aws:SourceArn`, `aws:SourceAccount`, and
  `kms:EncryptionContext:aws:kinesisanalytics:arn`. The encryption-context and source ARN value is
  the **snapshot** ARN for an import, and for an export it is the ARN of the **application that
  created** the snapshot — or the snapshot ARN if the snapshot was itself imported. Using the
  snapshot ARN for an export of an application-created snapshot is a common denial.
- **Restore** requires the key policy to allow **two** ARNs for both
  `kms:EncryptionContext:aws:kinesisanalytics:arn` and `aws:SourceArn`: the application doing the
  restoring, and the snapshot's source. Restoring into a *different* application — which this
  feature exists to enable — therefore always needs a key policy change, since the new
  application's ARN is not there.

One exception worth knowing, because it inverts the usual advice: when an export writes to a bucket
whose **default** encryption is a customer managed key, MSF sends no encryption context, so the
export role policy must condition on `kms:ViaService` and must **not** carry a
`kms:EncryptionContext:aws:kinesisanalytics:arn` condition. MSF does not check the bucket's default
key when it validates the request, so getting this wrong fails asynchronously with
`KMSConfigError` rather than at call time.

If a snapshot outlives its application, the creating application's ARN must stay in the key policy
or the snapshot can be neither restored nor exported.

**Import and export authorise differently from everything above.** They are not authorised on the
caller alone: MSF assumes a role you pass in the request body (`ExportRoleArn` / `ImportRoleArn`),
and the caller additionally needs `iam:PassRole` on it. Granting the caller
`kinesisanalytics:ExportSnapshot` or `kinesisanalytics:ImportSnapshot` is necessary but not
sufficient. See [MSF needs its own role, passed in the request](#msf-needs-its-own-role-passed-in-the-request).

### Scoping a generated policy

Scope snapshot resources by name prefix — `snapshot/MyApplication-*`. Two traps:

- A `snapshot/SYSTEMSNAPSHOT-*` pattern matches the system snapshots of **every application in the
  account and Region**, because system snapshot names are not namespaced by application. Point the
  breadth out if the user wants it.
- But **`RESTORE_FROM_LATEST_SNAPSHOT` may select a system snapshot**, so a `RestoreFromSnapshot`
  statement scoped only to `snapshot/MyApplication-*` breaks restore whenever the newest snapshot
  is a system one. Either allow both `snapshot/SYSTEMSNAPSHOT-*` and `snapshot/MyApplication-*`, or
  scope with a tag condition instead — which is the way to get the coverage without the
  account-wide wildcard.

Enhanced snapshots add **no service-specific condition keys**. Tag-based control uses the global
`aws:ResourceTag`, `aws:RequestTag`, and `aws:TagKeys`:

- `aws:RequestTag` and `aws:TagKeys` are set for `CreateSnapshot` and `ImportSnapshot` requests
  carrying `Tags`, and are usable on `CreateSnapshot`, `ImportSnapshot`, and `TagResource`.
- `aws:ResourceTag` is evaluated against the **snapshot's** tags for `RestoreFromSnapshot`,
  `DescribeSnapshot`, `DeleteSnapshot`, and `ExportSnapshot`.
- For `CreateSystemSnapshot` it is evaluated against the **application's** tags, and no request-tag
  keys are set. Combined with system snapshots inheriting application tags, this is what makes a
  tag-scoped restore policy workable.

For the full action, resource, and condition-key lists, and every policy in full, see
[Identity and access management for enhanced snapshots](https://docs.aws.amazon.com/managed-flink/latest/java/security-iam-snapshots.html).

## Errors whose obvious cause is wrong

Most exceptions here mean what they say, and the full tables are in the AWS documentation for each
operation. These are the ones where the natural diagnosis is the wrong one:

| Symptom | What it is not | What it actually is |
|---|---|---|
| `AccessDeniedException` on restore | the service execution role | `kinesisanalytics:RestoreFromSnapshot` on the **snapshot** ARN, which is denied by default; or, for a customer managed key, missing caller KMS permissions or a key policy that omits the restoring application's ARN |
| `InvalidArgumentException` on create or import | a malformed request | a name starting with `SYSTEMSNAPSHOT`, in any case — where `ResourceInUseException` would be the intuitive guess for a reserved name. A name over 100 characters is a different error: `ValidationException` |
| `TooManyTagsException` on 60 tags | the 200-tag request limit | the 50-tag resource limit. 51–200 gives `TooManyTagsException`, above 200 gives `ValidationException` |
| `InvalidArgumentException` on import or export with a key | a wrong key | `KeyId` given as a key ID or alias instead of a full key ARN. Application-level encryption accepts all four forms, so the generalisation fails only here |
| **no exception at all** | success | an asynchronous operation that failed later. Read `DescribeSnapshotOperation`, and note a `CANCELLED` operation carries no `ErrorCode` or `ErrorString` whatsoever |

`SnapshotOperationFailureDetails.ErrorInfo` holds `ErrorCode` and `ErrorString`, and `ErrorCode` is
an open string rather than an enum — handle values you do not recognise. For the complete
per-operation error tables see
[Create and manage enhanced snapshots](https://docs.aws.amazon.com/managed-flink/latest/java/snapshots-manage.html),
[Restore an application](https://docs.aws.amazon.com/managed-flink/latest/java/snapshots-restore.html),
[Import and export](https://docs.aws.amazon.com/managed-flink/latest/java/snapshots-import-export.html),
and [Monitor enhanced snapshot operations](https://docs.aws.amazon.com/managed-flink/latest/java/snapshots-monitor-operations.html).

## Cases with no self-service path

Route these to AWS Support rather than attempting a workaround:

- restoring an application snapshot (legacy) into an application already in enhanced snapshot
  mode, when the rollback window has closed
- returning to legacy mode after another application update has landed since opt-in

Both follow from the one-way mode change. Have the user gather the application ARN and Region, the
`ApplicationVersionId` before and after opt-in, and the relevant snapshot names. Do not promise a
specific remediation.

## Reference

- [Manage application backups using snapshots](https://docs.aws.amazon.com/managed-flink/latest/java/how-snapshots.html)
- [How enhanced snapshots work](https://docs.aws.amazon.com/managed-flink/latest/java/snapshots-how-it-works.html)
- [Set up enhanced snapshots for the first time](https://docs.aws.amazon.com/managed-flink/latest/java/snapshots-setup.html)
- [Upgrade existing applications to enhanced snapshots](https://docs.aws.amazon.com/managed-flink/latest/java/snapshots-upgrade.html)
- [Create and manage enhanced snapshots](https://docs.aws.amazon.com/managed-flink/latest/java/snapshots-manage.html)
- [Restore an application from an enhanced snapshot](https://docs.aws.amazon.com/managed-flink/latest/java/snapshots-restore.html)
- [Import and export enhanced snapshots](https://docs.aws.amazon.com/managed-flink/latest/java/snapshots-import-export.html)
- [Monitor enhanced snapshot operations](https://docs.aws.amazon.com/managed-flink/latest/java/snapshots-monitor-operations.html)
- [Enhanced snapshot API examples](https://docs.aws.amazon.com/managed-flink/latest/java/snapshots-api-examples.html)
- [Identity and access management for enhanced snapshots](https://docs.aws.amazon.com/managed-flink/latest/java/security-iam-snapshots.html)
  — the trust policy and all four role permissions policies in full, plus the import and
  export key policies. Copy from here rather than composing one.
