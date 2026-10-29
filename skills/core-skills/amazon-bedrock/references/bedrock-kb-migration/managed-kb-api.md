# Managed Knowledge Base — API Reference

> **Purpose.** The explicit request shapes and the parameters a Managed KB (`MANAGED`) expects vs. rejects
> for the calls the **agent** makes — creates and read-only probes — so it can build correct calls and
> recover from errors. Read this whenever a `create-*` or `get-*` call returns a `ValidationException`, a
> "not supported" error, or behaves unexpectedly. It carries only the migration-specific call shapes; for
> the destination's general create/retrieve mechanics see
> [managed KB setup](references/managed-knowledge-bases-setup.md) and
> [managed KB retrieval](references/managed-knowledge-bases-retrieval.md).
>
> **Public only.** Uses the public `aws bedrock-agent` commands. Always pass `--region <REGION>` and
> `--profile <PROFILE>`. ARNs are references, not secrets; never print secret values. Read public docs per
> [safety-and-iam](references/bedrock-kb-migration/safety-and-iam.md) (curl + the `.md` endpoint, never
> `web_fetch`).
>
> **Ingestion and retrieval are user-run steps, and this file gives no interface for either.** The agent
> provisions only. Afterwards the **user** starts ingestion and runs the retrieval comparison against the
> new (owned) data sources, never the original. §3 and §5 describe those surfaces well enough to explain
> them, plan around them and report what changes for callers — for request shapes the user goes to the AWS
> API reference. The shapes in this file are the ones the **agent itself** issues: creates and read-only
> probes.
>
> **Never invent a request shape, supported model, or dimension count.** Confirm parameter names against
> the public docs and/or `aws bedrock-agent <command> --generate-cli-skeleton`, preferring the user's
> Region. If it isn't confirmed, say so and re-verify against the docs. **The one exception is
> `connectorParameters`** — free-form in the API model, so the skeleton renders it as `{}` and proves
> nothing. For the connector body this file and the per-connector doc page (§2b/§2c) are the authority;
> never infer a connector field from the self-managed shape, which differs deliberately.

## Contents

- [1. CreateKnowledgeBase (MANAGED)](#1-createknowledgebase-managed)
- [2. CreateDataSource (MANAGED_KNOWLEDGE_BASE_CONNECTOR)](#2-createdatasource-managed_knowledge_base_connector)
- [2b. Auth-based connectors — exact managed shapes](#2b-auth-based-connectors-sharepoint-confluence-onedrive--exact-managed-shapes)
- [2c. Doc sources](#2c--doc-sources)
- [2d. CUSTOM connector (direct ingestion)](#2d-custom-connector-direct-ingestion--no-crawl-documents-are-pushed-in)
- [3. Retrieval surfaces (runtime, user-run)](#3-retrieval-surfaces-runtime--user-run-what-they-are-and-when-each-fits)
- [3b. ACL-aware retrieval — capability and its boundary](#3b-acl-aware-retrieval-managed--capability-and-its-boundary)
- [4. Read / status commands (read-only probes)](#4-read--status-commands-pre-approved-read-only-probes)
- [5. StartIngestionJob — a user-run handoff step](#5-startingestionjob--a-user-run-handoff-step)
- [6. API error → cause → fix](#6-api-error--cause--fix)
- [7. Client tokens (idempotency)](#7-client-tokens-idempotency--attach-to-mutating-calls)
- [9. Rate limits & batching](#9-rate-limits--batching-build-with-a-script-not-rapid-one-by-one-cli)

---

## 1. CreateKnowledgeBase (MANAGED)

```bash
aws bedrock-agent create-knowledge-base --region <REGION> --profile <PROFILE> \
  --name "<KB_NAME>" \
  --role-arn "arn:aws:iam::<account-id>:role/<KB_EXEC_ROLE>" \
  --client-token "<CLIENT_TOKEN>" \
  --tags '{ "bedrock-kb-migration-id": "<MIGRATION_ID>" }' \
  --knowledge-base-configuration '{
    "type": "MANAGED",
    "managedKnowledgeBaseConfiguration": { "embeddingModelType": "<EMBEDDING_MODEL_TYPE>" }
  }'
# The inline --tags map carries the ownership tag the build policy requires on create (same
# bedrock-kb-migration-id key and the same fixed <MIGRATION_ID> value as safety-and-iam.md Policy B).
# CreateKnowledgeBase accepts tags inline; CreateDataSource does NOT (see §2).
# embeddingModelType MANAGED (the default when omitted) uses a service-managed embedding model — do NOT pass
# embeddingModelArn or embeddingModelConfiguration. To bring your own supported Bedrock model instead,
# use embeddingModelType CUSTOM, which requires BOTH embeddingModelArn and embeddingModelConfiguration
# (the managed dimension + FLOAT32, from the create page), and a model available in the KB's Region:
#   "managedKnowledgeBaseConfiguration": {
#     "embeddingModelType": "CUSTOM",
#     "embeddingModelArn": "arn:aws:bedrock:<REGION>::foundation-model/<CURRENTLY_SUPPORTED_MODEL_ID>",  # pick from the docs, do not hardcode
#     "embeddingModelConfiguration": {
#       "bedrockEmbeddingModelConfiguration": { "dimensions": <MANAGED_DIMENSION>, "embeddingDataType": "FLOAT32" }
#     }
#   }
```

| Parameter | Expected? | Notes |
|---|---|---|
| `name` | **required** | |
| `roleArn` | **required** | Execution role (needs invoke-model + the connector's S3 read perms) |
| `clientToken` | **optional to the API; required by this workflow** | Idempotency token (`--client-token`). A unique, stable value makes the create safe to re-run: AWS treats a repeat call with the same token + params as the same request instead of creating a duplicate. The API accepts the call without it, but this migration **requires** a stable per-operation token on every create for resume safety. **Must be at least 33 characters.** Record it (§7) |
| `knowledgeBaseConfiguration.type` | **required** = `MANAGED` | |
| `managedKnowledgeBaseConfiguration.embeddingModelType` | optional (default `MANAGED`) | `MANAGED` = service-managed embedding model (no model selection needed); `CUSTOM` = bring your own supported Bedrock model. **Can't be changed after creation** |
| `managedKnowledgeBaseConfiguration.embeddingModelArn` | required **only when `embeddingModelType` is `CUSTOM`**; **omit** for `MANAGED` | A supported Bedrock embedding model FM (or inference-profile) ARN — verify support/Region in the public docs linked below |
| `description` | optional | |
| `managedKnowledgeBaseConfiguration.serverSideEncryptionConfiguration.kmsKeyArn` | optional (API); **carry the source value forward** | KB-level customer-managed KMS key (CMK). Optional to the API — omit it and the KB is encrypted with an AWS-owned key you cannot see, audit, or rotate. **If the source KB used a CMK, reuse the same key ARN here so migration does not silently downgrade encryption posture.** See "Encryption at rest — carry the source CMK forward" below |
| `managedKnowledgeBaseConfiguration.embeddingModelConfiguration.bedrockEmbeddingModelConfiguration` (dimensions/dataType) | required with `CUSTOM` (**only the dimension and data type the create page lists are accepted**); omit for `MANAGED` | Managed enforces fixed values; other values are rejected, for example `dimensions` set lower → `"MANAGED knowledge base type supports only 1024 embedding dimensions"`; `embeddingDataType: BINARY` → `"MANAGED knowledge base type supports only FLOAT32 embedding data type"`. With `CUSTOM`, set exactly the managed values from the create page |
| `storageConfiguration` (top-level) | ❌ **rejected** | The store is auto-provisioned — **omit `storageConfiguration` entirely on a MANAGED KB.** There is no `StorageConfiguration`/`storage_configuration` on this target |

**Embedding model — two modes, set by `embeddingModelType` (verify support in the docs; don't guess):**

- **`MANAGED` (default):** service-managed model — omit `embeddingModelArn`/`embeddingModelConfiguration`;
  keeps the built-in managed reranker.
- **`CUSTOM`:** your own Bedrock model ARN at the managed **dimension and data type** for text models (read
  them from [Create a managed knowledge base](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-create.html);
  any other value is rejected — see table), available in the KB's Region; a multimodal model has its own
  rules ([mapping](references/bedrock-kb-migration/mapping.md) → Key findings). **Disables the managed reranker.** Text and multimodal models
  are both eligible.

**Don't hardcode the supported `CUSTOM` model set — it can change; fetch it at create time.** An unlisted
model → `"The specified embedding model ... is not supported"` (pick one the docs list). `embeddingModelType`
can't change after creation.

```bash
curl -sSL "https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-create.md"   # section: kb-managed-embedding-models; Region availability: knowledge-base-supported.md / kb-managed-regions.md
```

**Response:** `knowledgeBase.knowledgeBaseId`, `knowledgeBase.status` (`CREATING` → `ACTIVE`). Poll
`get-knowledge-base` (§4) for `ACTIVE` before creating data sources.

**Canonical API reference — check it for the current field list and limits before every call.** The API
reference governs the request/response **shape** (field names, required/optional, types); the user guide
governs **behavior and defaults**. Read the API reference for `CreateKnowledgeBase` and confirm the current
fields against it (or `--generate-cli-skeleton`) before building the call — fields and limits change:
[CreateKnowledgeBase API reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_CreateKnowledgeBase.html).

### Encryption at rest — carry the source CMK forward

A managed KB is always encrypted. `kmsKeyArn` only decides *which* key: omit it and Bedrock uses an
**AWS-owned key** (invisible to the customer — no ARN, no key policy, no CloudTrail on its use, no rotation
control); supply it and the KB uses the customer's **customer-managed key (CMK)**, which they can audit,
rotate, and revoke. Because migration is create-new-then-cut-over, a fresh `serverSideEncryptionConfiguration`
is chosen at create time — so a source KB that used a CMK **silently drops to the AWS-owned key** unless the
key is carried forward.

Discovery already records the source `encryption` value (`aws-owned | cmk-arn`). Use it:

1. **If the source used a CMK, ask the customer explicitly** which they want on the new KB: reuse the same
   key ARN (default recommendation — preserves posture), use a different CMK, or accept the AWS-owned
   default. If the source had no CMK, state plainly that the new KB will use the AWS-owned key, and offer the
   CMK path if they want to *raise* posture during the migration. Never decide silently.
2. **The same CMK can serve the source and the new KB at the same time.** A KMS key is account-level and
   referenced by ARN; passing the source's key to the new KB is normal — both run on it during the
   parallel-validation window.
3. **Bedrock creates a grant on the key — it never edits the key policy.** On `CreateKnowledgeBase` with a
   `kmsKeyArn`, Bedrock verifies it can use the key and **creates KMS grants automatically**. Grants can remain
   after the KB is deleted (observed: all of them stayed); after deleting a CMK-encrypted KB, check with
   `aws kms list-grants --key-id <KEY_ARN>` and retire the stale ones. A grant is a separate authorization object; Bedrock does **not**
   modify the key policy to do this, and neither should the agent describe it that way. The managed KB's
   own service role needs **no** permission on this KB-storage key.
4. **The customer owns the key policy — recommend, never modify.** The one prerequisite lives in the *key
   policy*, which the **customer owns and updates**: it must permit the identity that runs
   `CreateKnowledgeBase` to `kms:CreateGrant` (plus `GenerateDataKey`/`Decrypt`), scoped with
   `kms:ViaService: bedrock.<region>.amazonaws.com`. Once the key policy permits the creating identity,
   Bedrock's automatic grant covers the KB's ongoing use of the key. **Recommend the policy below for the
   customer to apply to their own key — never edit their key policy for them, and never imply Bedrock edits
   it.**

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Principal": { "AWS": "arn:aws:iam::<account-id>:role/<creating-identity>" },
         "Action": ["kms:CreateGrant"],
         "Resource": "*",
         "Condition": {
           "StringEquals": { "kms:ViaService": "bedrock.<region>.amazonaws.com" },
           "ForAllValues:StringEquals": {
             "kms:GrantOperations": ["CreateGrant","GenerateDataKey","GenerateDataKeyWithoutPlaintext","DescribeKey","Encrypt","Decrypt"]
           }
         }
       },
       {
         "Effect": "Allow",
         "Principal": { "AWS": "arn:aws:iam::<account-id>:role/<creating-identity>" },
         "Action": ["kms:GenerateDataKey","kms:Decrypt"],
         "Resource": "*",
         "Condition": { "StringEquals": { "kms:ViaService": "bedrock.<region>.amazonaws.com" } }
       }
     ]
   }
   ```

5. **If create fails with a KMS error** (`AccessDenied`/`KMSKeyNotFound`), the cause is the creating identity
   lacking `kms:CreateGrant` on the key — name it rather than burning the retry ladder guessing.

Authoritative reference for the create-time grant behavior and the exact key policy:
[Encryption of knowledge base resources](https://docs.aws.amazon.com/bedrock/latest/userguide/encryption-kb.html#encryption-kb-managed-ingestion).

---

## 2. CreateDataSource (MANAGED_KNOWLEDGE_BASE_CONNECTOR)

```bash
aws bedrock-agent create-data-source --region <REGION> --profile <PROFILE> \
  --knowledge-base-id "<NEW_OWNED_KB>" \
  --name "<DS_NAME>" \
  --client-token "<CLIENT_TOKEN>" \
  --data-source-configuration '{
    "type": "MANAGED_KNOWLEDGE_BASE_CONNECTOR",
    "managedKnowledgeBaseConnectorConfiguration": {
      "connectorParameters": {
        "type": "S3",
        "version": "1",
        "connectionConfiguration": { "bucketName": "<BUCKET>", "bucketOwnerAccountId": "<account-id>" },
        "filterConfiguration": { "maxFileSizeInMegaBytes": "<OPTIONAL_LIMIT>" }
      },
      "deletionProtectionConfiguration": {
        "deletionProtectionStatus": "ENABLED"
      },
      "syncSchedule": {
        "weekly": { "dayOfWeek": "MONDAY" }
      }
    }
  }'
```

`deletionProtectionConfiguration` is a **sibling of `connectorParameters`** and is shown **in the request
above** as the secure default: `ENABLED`, with the threshold left at the service default unless the customer
sets one. It is optional at the API level, but emit it
explicitly rather than relying on omission; set `"deletionProtectionStatus": "DISABLED"` **only** on an
explicit customer opt-out. The **CUSTOM connector (direct ingestion) does not support deletion protection**
— omit this block for a CUSTOM data source (§2d).

`syncSchedule` is also an **optional sibling of `connectorParameters`** (shown above for illustration).
It sets a recurring schedule on which Amazon Bedrock automatically syncs the data source for **all native
data source connectors**. The AWS docs
([kb-managed-connect-ds.html](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-connect-ds.html))
state you specify **exactly one** of: `daily` (an empty object — "Syncs once per day at a system-chosen
off-peak time"); `weekly` (requires `dayOfWeek`, a value `SUNDAY`–`SATURDAY`); or `monthly` (requires
`dayOfMonth`, holding either a `dayNumber` (allowed range: [DayOfMonth](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_DayOfMonth.html)) or an empty `lastDayOfMonth` object). "Omit
`syncSchedule` to sync on demand only." The schedule is **carried over from the source, not asked**:
no timer on the source means omit it (on demand, as today); a timer the schedule can express is
carried; any other timer stays the customer's own (see [plan](references/bedrock-kb-migration/plan.md)
→ "Sync schedule"). In CloudFormation it is `SyncSchedule` on `ManagedKnowledgeBaseConnectorConfiguration`
of `AWS::Bedrock::DataSource`, with exactly one of `Daily` (JSON `{}`), `Weekly` (`DayOfWeek`) or
`Monthly` (`DayOfMonth` with `DayNumber` or `LastDayOfMonth`); every one is "Update requires: No
interruption"
([SyncSchedule](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-bedrock-datasource-syncschedule.html)).
Unlike `ConnectorParameters`, these are PascalCase typed properties. For Terraform, check the provider's
schema for the attribute (see [iac-schema](references/bedrock-kb-migration/iac-schema.md)); never write
one the schema does not have.

`--vector-ingestion-configuration` is intentionally omitted above. Omitting it is **required** when the KB
uses the managed embedding model: any `chunkingConfiguration` (even `FIXED_SIZE`/`NONE`) is rejected with
`ValidationException: "A chunking strategy cannot be specified with a managed embedding model"`, and the
managed fixed-size default applies (size and overlap on the Customize ingestion page). Only when the
KB uses a CUSTOM embedding model may you pass `--vector-ingestion-configuration` to set `FIXED_SIZE` or
`NONE` explicitly; `SEMANTIC`/`HIERARCHICAL` are rejected either way, so omit for those.

**S3 filters preserved; no dedicated bucket by default.** A source S3 data source's key-prefix scoping and
size limits carry over through the managed `filterConfiguration` block (below); the managed KB reads the
**existing** bucket — a migration does **not require a dedicated bucket by default**.

| Parameter | Expected? | Notes |
|---|---|---|
| `knowledgeBaseId` | **required** | The new owned managed KB |
| `name` | **required** | |
| `clientToken` | **optional to the API; required by this workflow** | Idempotency token (`--client-token`); a stable value makes the create safe to re-run without duplicating the data source. The API accepts the call without it, but this migration requires a stable per-operation token on every create for resume safety. Record it (§7) |
| `dataSourceConfiguration.type` | **required** = `MANAGED_KNOWLEDGE_BASE_CONNECTOR` | |
| `connectorParameters.type` | **required** | `S3`, `ONEDRIVE`, `CONFLUENCE`, `CONFLUENCEONPREM` (Confluence Data Center), `SHAREPOINT`, `WEB`, `GOOGLEDRIVE`, `SALESFORCE`, `ZENDESK`, `BOX`, `SERVICENOW`, `CUSTOM` (the set grows; the connect-ds page's Topics list is current). The managed names are `WEB`/`GOOGLEDRIVE`; `WEB_CRAWLER`/`GOOGLE_DRIVE` are **rejected** with `Invalid connector type` (see §2b enum note). `CUSTOM` is a direct push/ingestion source (no crawl, no secret) — see §2d. The set is expanding — confirm the live set and each connector's exact shape from its own doc page; do not quote a fixed count |
| `connectorParameters.version` | **required** = `"1"` (string) | |
| `connectorParameters.connectionConfiguration` | **required** | S3: `bucketName` + `bucketOwnerAccountId`; auth connectors: `secretArn` + connector fields (§2b) |
| `connectorParameters.filterConfiguration` | optional | Per-connector filters. **S3: `inclusionPrefixes`, `exclusionPrefixes`, `inclusionPatterns`, `exclusionPatterns`, `maxFileSizeInMegaBytes`** (prefixes scope which S3 keys are ingested; patterns are regexes) |
| `connectorParameters.aclEnabled` | optional (auth connectors) | Document-level access-control flag. **There is no `accessControlConfiguration`/`crawlAcl` on managed connectors** |
| `managedKnowledgeBaseConnectorConfiguration.deletionProtectionConfiguration.deletionProtectionStatus` | optional (API) | `ENABLED`/`DISABLED` (+ optional `deletionProtectionThreshold`). It caps the share of indexed documents one **sync** may delete (a sync above it skips its delete phase); it does not block a `DeleteDataSource` call. Range and default: [DeletionProtectionConfiguration](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_DeletionProtectionConfiguration.html) and the connect-ds page. Sibling of `connectorParameters`. **Secure generated-request default: `ENABLED` (threshold left at the service default unless the customer sets one), where the connector supports it — emit it explicitly and set `DISABLED` only on an explicit customer opt-out.** **No `enableDeletionProtection` field.** The CUSTOM connector does **not** support it (§2d) |
| `managedKnowledgeBaseConnectorConfiguration.mediaExtractionConfiguration` | optional | Extract media (images/audio/video) from files |
| `managedKnowledgeBaseConnectorConfiguration.syncSchedule` | optional (**carried from the source**) | Recurring auto-sync for native connectors. Sibling of `connectorParameters`. Specify **exactly one** of `daily` ({}), `weekly` (`dayOfWeek` `SUNDAY`–`SATURDAY`), `monthly` (`dayOfMonth` with `dayNumber` **or** empty `lastDayOfMonth`; range: [DayOfMonth](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_DayOfMonth.html)). **Omitting it = sync on demand only.** Not asked: omit it when the source has no timer; carry a timer it can express; otherwise the customer keeps their own timer (plan → "Sync schedule"). CloudFormation: `SyncSchedule` (`Daily` / `Weekly` / `Monthly`), update without interruption |
| `vectorIngestionConfiguration.chunkingConfiguration.chunkingStrategy` | optional (**forbidden with the managed embedding model**) | **Depends on the embedding-model type.** With the **managed embedding model**, omit `chunkingConfiguration` entirely — passing any strategy, including `FIXED_SIZE`/`NONE`, is rejected with `ValidationException: "A chunking strategy cannot be specified with a managed embedding model"`. With a **custom embedding model**, `FIXED_SIZE` or `NONE` is accepted; if you pass `FIXED_SIZE`, `fixedSizeChunkingConfiguration` requires **both** `maxTokens` and `overlapPercentage` (ranges in the [FixedSizeChunkingConfiguration](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_FixedSizeChunkingConfiguration.html) API reference) and those values are retained. `DEFAULT`/`HIERARCHICAL`/`SEMANTIC` are rejected server-side in both cases — omit for those |
| `dataSourceConfiguration.type` = `CUSTOM` (top-level, self-managed shape) | ❌ **rejected** | This is the self-managed shape. For a custom/direct-push source on a managed KB, use `type: MANAGED_KNOWLEDGE_BASE_CONNECTOR` with `connectorParameters.type: CUSTOM` (§2d) — S3 staging is no longer required |
| chunking `DEFAULT` / `HIERARCHICAL` / `SEMANTIC` (explicit) | ❌ **rejected server-side** | Omit `chunkingConfiguration` to use the managed default, or (custom embedding model only) pass `FIXED_SIZE`/`NONE` explicitly. **Nothing client-side catches this:** `chunkingStrategy` is a shape shared with self-managed whose model enum is the full `[FIXED_SIZE, NONE, HIERARCHICAL, SEMANTIC]`, so `SEMANTIC`/`HIERARCHICAL` pass client validation cleanly. Same for `parsingConfiguration` and for `customTransformationConfiguration` / `contextEnrichmentConfiguration`, which exist in the model despite being managed blockers. **A skeleton, `cfn-lint` or `terraform validate` will never flag these — only a live create will.** Treat the managed restriction as live-tested behavior, not a schema fact |
| **any** chunking strategy (incl. `FIXED_SIZE`/`NONE`) **with the managed embedding model** | ❌ **rejected server-side** | `ValidationException: "A chunking strategy cannot be specified with a managed embedding model"`. On a managed-embedding KB omit `chunkingConfiguration` completely — the managed default applies. Also invisible client-side, and **not documented in the AWS user guide**, so do not "correct" it from the docs page. A chunking config is accepted only when the KB uses a **custom** embedding model |
| `accessControlConfiguration` / `crawlAcl` (self-managed field) | ❌ **not a managed field** | Use `connectorParameters.aclEnabled` (auth connectors) instead |
| `credentialsSecretArn` (self-managed field) | ❌ **not a managed field** | The managed secret is `connectionConfiguration.secretArn` |
| `serverSideEncryptionConfiguration` (DS level) | ❌ **rejected** | Use KB-level CMK instead |
| `parsingConfiguration` | n/a | Managed forces `SMART_PARSING` — there is no parser to select. It is a per-content-type strategy (bounding-box → FM extraction/captioning/video scene description), with documented per-file size ceilings (read them live; [mapping](references/bedrock-kb-migration/mapping.md) → "Documented ingestion ceilings"). Capability detail: [mapping](references/bedrock-kb-migration/mapping.md) → "Managed-only capabilities" |

**Response:** `dataSource.dataSourceId`, `dataSource.status` (`CREATING` → `AVAILABLE`).

**Canonical API reference — check it for the current field list and limits before every call.** The API
reference governs the request/response **shape**; the user guide (and the per-connector pages in §2c)
govern **behavior and defaults**. Read the API reference for `CreateDataSource` and confirm the current
fields against it (or `--generate-cli-skeleton`, remembering the `connectorParameters` body is free-form
and unmodelled — §2b) before building the call:
[CreateDataSource API reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_CreateDataSource.html).

---

## 2b. Auth-based connectors (SharePoint, Confluence, OneDrive) — exact managed shapes

**The managed connector shape differs from the self-managed connector** — the managed secret field is
`connectionConfiguration.secretArn` (not `credentialsSecretArn`), the auth-type values are different, and
fields are grouped into `connectionConfiguration` / `dataEntityConfiguration` / `filterConfiguration`
sub-objects. Auth-based connectors are the top cause of `FAILED` data sources, almost always a secret or
certificate problem. Re-verify these shapes against the per-connector doc pages (§2c) before building a call.

**Connector authentication — what carries over and who does what.**

- No documented mapping exists from a self-managed auth type to a managed one, and the managed secret's key
  set differs (each connector's section below). Choose the managed `authType` from that connector's page,
  with the customer; treat the source secret as reference only. Confluence `BASIC` was carried over in live
  testing with a new secret holding the managed key set; the SharePoint and OneDrive application paths are
  **not verified** here — say so.
- **User-managed setup (3LO), `authType: MANAGED_OAUTH2`** on SharePoint, OneDrive and Confluence, is a
  console sign-in: the customer signs in to the source from the Bedrock console, Bedrock creates the token
  secret, and the KB role refreshes it. It is the customer's step, never the agent's
  ([kb-managed-3lo-setup](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-3lo-setup.html)
  lists the console user's permissions).
- AWS publishes a sample that sets up Microsoft, Google and Atlassian connectors end to end
  ([aws-samples/sample-managed-kb-connector-setup](https://github.com/aws-samples/sample-managed-kb-connector-setup)).
  Point the customer to it as a sample, not as part of this migration: ask before suggesting any change on
  the Microsoft, Google or Atlassian side, refer to secrets by ARN only, prefer the least privilege the
  source supports (for SharePoint, `Sites.Selected`), and do not copy its code into the migration.

Common wrapper: `deletionProtectionConfiguration` (`deletionProtectionStatus`) and
`mediaExtractionConfiguration` are **siblings of `connectorParameters`**; `aclEnabled` is a flat boolean
**inside** `connectorParameters`.

### SharePoint (`connectorParameters.type` = `SHAREPOINT`)

```json
{ "type": "MANAGED_KNOWLEDGE_BASE_CONNECTOR", "managedKnowledgeBaseConnectorConfiguration": {
  "connectorParameters": {
    "type": "SHAREPOINT", "version": "1", "aclEnabled": true,
    "connectionConfiguration": {
      "secretArn": "<SECRET_ARN>", "tenantId": "<TENANT_ID>", "authType": "ENTRA_ID_APP_ONLY",
      "certificateS3Path": { "s3BucketName": "<CERT_BUCKET>", "s3KeyName": "certs/certificate.p12" } },
    "dataEntityConfiguration": { "crawlFiles": true, "crawlPages": true,
      "siteUrls": ["https://contoso.sharepoint.com/sites/engineering"] },
    "filterConfiguration": { "inclusionItemPaths": ["..."], "modifiedDateAfter": "..." } } } }
```

| Field (in `connectionConfiguration`) | Required | Notes |
|---|---|---|
| `secretArn` | Yes | ARN of the Secrets Manager secret |
| `tenantId` | Yes | Microsoft Entra (Azure AD) tenant ID |
| `authType` | Yes | `ENTRA_ID_APP_ONLY` (recommended), `OAUTH2_APP`, or `MANAGED_OAUTH2` (3LO console sign-in) |
| `certificateS3Path` (`{s3BucketName, s3KeyName}`) | Conditional | **Required for `ENTRA_ID_APP_ONLY` even with ACLs off** — a data source with this authType and no certificate FAILS. Omit for `OAUTH2_APP` |

`dataEntityConfiguration`: `siteUrls` (**JSON array**; each path begins `/sites/`, `/teams/`, or
`/personal/`), `crawlFiles` (default true), `crawlPages` (default true).
`filterConfiguration` (optional): `modifiedDateBefore`, `modifiedDateAfter`, `inclusionItemPaths`.
**Secret keys** — `ENTRA_ID_APP_ONLY`: `clientId` + `certificatePassword` (or `privateKey` for PEM);
`OAUTH2_APP`: `clientId` + `clientSecret` + `userName` + `password`.
`aclEnabled` (shown as `true` above) is **a required, explicit customer choice per data source — never a
silent default.** Disclose what each value means (ACL-aware filtering on vs off; see §3b) and that it is
**immutable after create**, then set the value the customer chose — `true` to enforce ACL filtering (as in
the example) or `false` when the customer accepts no document-level filtering. The choice **by itself is
not a blocker** — either value is a valid migration. It becomes a blocker only when the **selected mode
lacks its required auth/ACL configuration** (e.g. ACLs on for SharePoint forces `ENTRA_ID_APP_ONLY` and a
`certificateS3Path`); in that case say what is missing rather than silently flipping the flag. The `siteUrls` value `https://contoso.sharepoint.com/sites/engineering`
is an **example only** (`contoso.sharepoint.com` is a placeholder domain) — replace it with the customer's
real site URL(s).

### Confluence (`connectorParameters.type` = `CONFLUENCE`)

```json
{ "type": "MANAGED_KNOWLEDGE_BASE_CONNECTOR", "managedKnowledgeBaseConnectorConfiguration": {
  "connectorParameters": {
    "type": "CONFLUENCE", "version": "1", "aclEnabled": true,
    "connectionConfiguration": {
      "secretArn": "<SECRET_ARN>", "type": "SAAS", "authType": "BASIC",
      "hostUrl": "https://example.atlassian.net" },
    "dataEntityConfiguration": { "crawlPage": true, "crawlBlog": true,
      "crawlPageAttachment": true, "crawlBlogAttachment": true },
    "filterConfiguration": { "inclusionSpaceKeys": ["ENG", "DOCS"] } } } }
```

| Field (in `connectionConfiguration`) | Required | Notes |
|---|---|---|
| `secretArn` | Yes | Secret ARN |
| `type` | Yes | Confluence deployment type — `SAAS` only (distinct from `connectorParameters.type=CONFLUENCE`) |
| `authType` | Yes | `BASIC`, `OAUTH2`, or `MANAGED_OAUTH2` (3LO console sign-in) |
| `hostUrl` | Yes | Base URL ending `.atlassian.net` (custom domains unsupported) |

`dataEntityConfiguration`: `crawlPage`, `crawlBlog`, `crawlPageAttachment`, `crawlBlogAttachment`,
`crawlArchivedSpace`, `crawlArchivedPage`, `crawlPersonalSpace`. The connector page lists the block as
optional, but live creates without it were rejected with `Value at 'dataEntityConfiguration' failed to
satisfy constraint: Member must not be null`. **Always send it**, with the entity types the source crawled
(the page's own example sets the four `crawl*` flags shown above). Also send `hostUrl` with no trailing
slash; a carried-over trailing slash was rejected on the same call.
`filterConfiguration` (optional): `inclusionSpaceKeys`, `inclusionSpaceUrls`, `inclusionMimeTypes`,
`exclusionMimeTypes`, `maxFileSizeInMegaBytes` (numeric string; default on the connector page).
`aclEnabled` has a **documented** default that depends on `authType` (`BASIC`→true, `OAUTH2`→false) and is
**permanent** after create. Do not rely on that default silently: make it an **explicit customer choice**,
disclose the meaning (§3b) and the immutability, then set it. The choice alone is not a blocker; it blocks
only when the selected mode lacks its required auth/ACL configuration. **Secret keys** — `BASIC`: `username` (email) + `password` (Atlassian API token) + `hostUrl`
(+ `adminApiKey`, `organizationId`, `directoryId` when `aclEnabled`); `OAUTH2`: per the Confluence OAuth2
setup page.

### OneDrive (`connectorParameters.type` = `ONEDRIVE`)

```json
{ "type": "MANAGED_KNOWLEDGE_BASE_CONNECTOR", "managedKnowledgeBaseConnectorConfiguration": {
  "connectorParameters": {
    "type": "ONEDRIVE", "version": "1", "aclEnabled": true,
    "connectionConfiguration": {
      "secretArn": "<SECRET_ARN>", "tenantId": "<TENANT_ID>", "authType": "ENTRA_APP_ID",
      "certificateS3Path": { "s3BucketName": "<CERT_BUCKET>", "s3KeyName": "certs/certificate.p12" } },
    "dataEntityConfiguration": { "crawlPersonalDrives": true } } } }
```

| Field (in `connectionConfiguration`) | Required | Notes |
|---|---|---|
| `secretArn` | Yes | Secret ARN |
| `tenantId` | Yes | Microsoft Entra tenant ID |
| `authType` | Yes | `ENTRA_APP_ID` (recommended), `OAUTH2`, or `MANAGED_OAUTH2` (3LO console sign-in) |
| `certificateS3Path` (`{s3BucketName, s3KeyName}`) | Conditional | Required **only when `aclEnabled` is true** (Entra App ID). Not used for content-only or `OAUTH2` |

`dataEntityConfiguration`: `crawlPersonalDrives`, `crawlSharedWithMe` (OAUTH2 only).
**`crawlPersonalDrives` is optional — do not set it to `true` by default.** Enabling it (as the example
shows for completeness) pulls in individual users' personal OneDrive content, which frequently contains
PII; set it deliberately with the customer, not automatically. Note that with Microsoft Entra ID App
authentication only personal drives can be crawled — so on that auth type this is the crawl scope, and the
PII consideration applies directly.
`filterConfiguration` (optional): `inclusionUserEmailAddresses`, `exclusionUserEmailAddresses`,
`userFilterPath`, `inclusionDriveItems`, `exclusionDriveItems`, `includeMimeTypes`, `excludeMimeTypes`,
`absoluteDateBefore`, `absoluteDateAfter`.
`aclEnabled` (shown as `true` above, which is why the example includes the required `certificateS3Path`) is
**a required, explicit customer choice — never a silent default**; disclose its meaning (§3b) and that it is
**immutable after create**, then set the chosen value (`true` to enforce ACL filtering, or `false` to
accept none — with `false` the `certificateS3Path` is not required). The choice alone is not a blocker; it
blocks only if the selected mode lacks its required auth/ACL configuration (ACLs on requires the Entra
app-id auth type and the certificate).
**Secret keys** — `ENTRA_APP_ID`: `clientId` + `clientSecret` (+ `certificatePassword` when `aclEnabled`);
`OAUTH2`: per the OneDrive OAuth2 setup page.

### S3 and Web Crawler (no secret)

- `S3` — `connectionConfiguration: { bucketName, bucketOwnerAccountId }`; optional
  `filterConfiguration: { inclusionPrefixes, exclusionPrefixes, inclusionPatterns, exclusionPatterns, maxFileSizeInMegaBytes }`
  (key-prefix scoping + regex patterns). See §2. Optional **top-level** `connectorParameters` fields:
  `metadataFilesPrefix` (where `.metadata.json` sidecar files live), `aclEnabled` (an **explicit choice**,
  **immutable after create** — disclose its meaning per §3b and set the customer's decision, don't default
  it silently), and `aclConfiguration: { globalAccessControlListS3Uri }` — **required when `aclEnabled` is
  true**, ignored when false. Note the bucket is named by **`bucketName`, not an ARN**: a source `bucketArn`
  must be reduced to the bare name. There is **no universal default** — pick the value with the customer.

  ACL-enabled S3 (the `aclConfiguration` is mandatory here):

  ```json
  { "type": "MANAGED_KNOWLEDGE_BASE_CONNECTOR", "managedKnowledgeBaseConnectorConfiguration": {
    "connectorParameters": {
      "type": "S3", "version": "1", "aclEnabled": true,
      "connectionConfiguration": { "bucketName": "<BUCKET>", "bucketOwnerAccountId": "<account-id>" },
      "aclConfiguration": { "globalAccessControlListS3Uri": "s3://<BUCKET>/<acl-config>.json" },
      "filterConfiguration": { "inclusionPrefixes": ["published/en/"] } } } }
  ```

  When the customer chooses no document-level filtering, set `"aclEnabled": false` and **omit**
  `aclConfiguration` entirely (it is ignored when false) — the rest of the shape is unchanged.
- `WEB` — full shape below. `GOOGLEDRIVE` is secret-based like the others. (The managed connector names
  are `WEB`/`GOOGLEDRIVE` — `WEB_CRAWLER`/`GOOGLE_DRIVE` are rejected; see the enum conflict note.)

> **`--generate-cli-skeleton` does NOT reveal connector fields.** It returns `"connectorParameters": {}`.
> The field is free-form in the API model, the CloudFormation schema and the Terraform provider, so no
> skeleton, `describe-type`, `cfn-lint` or `terraform validate` will ever list or check its contents. The
> skeleton remains useful for the *wrappers* (`deletionProtectionConfiguration`,
> `mediaExtractionConfiguration`). For the connector body, this file plus the per-connector doc page (§2c)
> are the only authority. Re-verify against the docs.

#### WEB (`connectorParameters.type` = `WEB`)

Source: `kb-managed-ds-webcrawler.md`. The self-managed web crawler's `crawlerConfiguration` splits into
two managed objects: `crawlConfiguration` (behaviour) and `filterConfiguration` (URL patterns).

```json
{ "type": "MANAGED_KNOWLEDGE_BASE_CONNECTOR", "managedKnowledgeBaseConnectorConfiguration": {
  "connectorParameters": {
    "type": "WEB", "version": "1",
    "connectionConfiguration": {
      "seedUrls": ["https://docs.example.com"],
      "authType": "<AUTH_TYPE>"
    },
    "crawlConfiguration": { "syncScope": "SUB_DOMAINS", "crawlAttachments": true },
    "filterConfiguration": { "exclusionPatterns": ["https://docs.example.com/private/.*"] } } } }
```

Add `crawlDepth`, `maxLinksPerUrl` and `maxCrawledUrlsPerMinute` to `crawlConfiguration` only when the source
sets them, carrying the source's values; omitted, the service defaults apply.

| Field | Required | Notes |
|---|---|---|
| `connectionConfiguration.seedUrls` | conditional | List (maximum length on the connector page). Required unless `siteMapUrls` is given |
| `connectionConfiguration.siteMapUrls` | conditional | List (maximum length on the connector page). Required unless `seedUrls` is given |
| `connectionConfiguration.authType` | **required** | `NO_AUTH` \| `BASIC_AUTH` \| `FORM` \| `SAML`. **Never inferred** — a generic example uses `<AUTH_TYPE>`. Use `NO_AUTH` **only after the customer confirms the site is public**; otherwise it is `BASIC_AUTH` / `FORM` / `SAML` with a `secretArn`. Even a public site needs `authType` set **explicitly** |
| `connectionConfiguration.secretArn` | conditional | Required whenever `authType` ≠ `NO_AUTH` (by ARN only) |
| `crawlConfiguration.crawlDepth` | optional | Range and default on the connector page |
| `crawlConfiguration.maxLinksPerUrl` | optional | Range and default on the connector page |
| `crawlConfiguration.maxCrawledUrlsPerMinute` | optional | Range on the connector page. This is where a self-managed `rateLimit` goes |
| `crawlConfiguration.implicitWaitInSeconds` | optional | Wait after page-ready before reading; raise for JS-heavy pages |
| `crawlConfiguration.syncScope` | optional | `PATH_SPECIFIC` (same host + same initial path) \| `DOMAINS_ONLY` (same host, any path) \| `SUB_DOMAINS` (primary domain incl. subdomains). Omitted = `PATH_SPECIFIC` behaviour. A self-managed `scope: HOST_ONLY` maps to `DOMAINS_ONLY` |
| `crawlConfiguration.crawlAttachments` | optional | Crawl linked files/PDFs |
| `filterConfiguration.inclusionPatterns` / `exclusionPatterns` | optional | Regex lists over URLs |
| `filterConfiguration.maxFileSizeInMegaBytes` | optional | Numeric **string**; default on the connector page |

There is **no** `crawlScope`, `rateLimit`, `crawlerConfiguration` or `crawlerLimits` on the managed
connector — those are the self-managed names and are silently accepted into the free-form blob, then
ignored or rejected by the service. The managed connector also has **no page cap**: a self-managed
`crawlerLimits.maxPages` has nowhere to go, so the new crawl can reach more pages than the source did. Flag a
dropped `maxPages` in the plan and offer the managed controls that narrow a crawl (`inclusionPatterns` /
`exclusionPatterns`, `syncScope`, `crawlDepth`).

**`authType` is required and never inferred.** Do not default a web data source to `NO_AUTH`. Resolve it
with the customer: `NO_AUTH` only once they confirm the site is public; otherwise `BASIC_AUTH` / `FORM` /
`SAML` with a Secrets Manager `secretArn` (by ARN only). A generic example uses `<AUTH_TYPE>`, not a
concrete value. **The web crawler has no ACL support** — there is no `aclEnabled` on this connector (web
content has no permission model; see §3b), so never add one to a WEB data source.

> **Connector-name enum conflict (resolved).** `kb-managed-connect-ds.md` lists the supported types as
> `S3, ONEDRIVE, CONFLUENCE, SHAREPOINT, WEB_CRAWLER, GOOGLE_DRIVE`, but the per-connector page
> (`kb-managed-ds-webcrawler.md`) says *"specify `WEB` as the connector type"*, and live testing gets
> `Invalid connector type` for `WEB_CRAWLER`/`GOOGLE_DRIVE`. **The per-connector page and live testing win:
> use `WEB` and `GOOGLEDRIVE`.** The overview page's enum is stale — expect to see it while reading the
> docs, and do not "correct" a working `WEB` to `WEB_CRAWLER` on the strength of it.

### Secrets Manager secret rules (auth connectors)

- The secret must exist **before** `create-data-source`, in the **KB's Region**. Pass only its **ARN** in
  `connectionConfiguration.secretArn` (never the value). The managed-connector docs do **not** require an
  `AmazonBedrock-` name prefix; only require it if the KB role's policy scopes secret access to
  `AmazonBedrock-*`.
- Key/value contents depend on connector + `authType` (tables above; full detail on the connector's
  "Set up … authentication" doc page). Do not guess key names.
- The KB execution role needs `secretsmanager:GetSecretValue` on the ARN (+ `kms:Decrypt` for a CMK), and
  for the certificate methods `s3:GetObject`/`s3:ListBucket` on the `.p12` object in `certificateS3Path`
  (+ `kms:Decrypt` if SSE-KMS).

### Precondition gate — do not submit before auth is confirmed; do not loop on FAILED

**Before calling `create-data-source` (or syncing) for an auth connector, confirm ALL of these:**

1. A secret exists at the ARN, in the KB's Region, with keys matching the managed connector + `authType`.
2. For SharePoint `ENTRA_ID_APP_ONLY` (and OneDrive `ENTRA_APP_ID` with ACLs), the `.p12` certificate is
   in S3 at `certificateS3Path` and the role can read it.
3. The KB role can read the secret (`secretsmanager:GetSecretValue`, + `kms:Decrypt` for a CMK).
4. `siteUrls` (array) / `hostUrl` / `tenantId` / `aclEnabled` are present and correctly shaped.

If any precondition is unmet or unknown, **stop and ask the user (or hand off the secret-creation as a user
step) — do NOT submit the call to the live service to "see if it works."** On a `FAILED` data source, run
**one** diagnosis pass against this checklist and the error, report the specific missing item, and stop.
**Never resubmit the same call or try random variations** — auth failures are config/permission problems
that re-running cannot fix.

### §2c — Doc sources

Re-verify these pages before building an auth-connector call; read them per
[safety-and-iam](references/bedrock-kb-migration/safety-and-iam.md).

- Connect a data source (wrapper fields, S3 example; **its type enum is stale — see the conflict note in §2b**): https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-connect-ds.html
- Amazon S3 connector (filter + ACL + metadata fields): https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-ds-s3.html
- Web Crawler connector (`WEB` — connection/crawl/filter fields): https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-ds-webcrawler.html
- SharePoint connector + connect (JSON): https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-ds-sharepoint-connect.html
- SharePoint Entra setup (secret keys, certificate): https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-sharepoint-entra-setup.html
- SharePoint OAuth2 setup (secret keys): https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-sharepoint-oauth2-setup.html
- Confluence connect (JSON) + Basic setup: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-ds-confluence-connect.html
- OneDrive connect (JSON) + Entra setup: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-ds-onedrive-connect.html

### Most common FAILED-status causes for these connectors

In rough frequency order: a **self-managed field** (`credentialsSecretArn`,
`accessControlConfiguration.crawlAcl`, `hostType`, `domain`) or connector name
(`WEB_CRAWLER`/`GOOGLE_DRIVE`) used instead of the managed shape above; a missing/wrong
`connectionConfiguration.secretArn`, or **secret keys that don't match the managed `authType`**; SharePoint
`ENTRA_ID_APP_ONLY` created **without** `certificateS3Path`; a KB role lacking
`secretsmanager:GetSecretValue`/`kms:Decrypt` or S3 read on the certificate; SharePoint `siteUrls` passed as
a string rather than a JSON array; and a wrong `authType` for the connector (e.g. the self-managed
`OAUTH2_CLIENT_CREDENTIALS` instead of managed `ENTRA_ID_APP_ONLY`/`OAUTH2_APP`), or a Confluence `hostUrl`
not ending `.atlassian.net`. Each maps to a fix in §6.

---

## 2d. CUSTOM connector (direct ingestion) — no crawl; documents are pushed in

A MANAGED KB **does** support a custom data source. Not via the self-managed top-level
`dataSourceConfiguration.type: CUSTOM` (that is rejected on managed — §6), but as a **connector**:
`type: MANAGED_KNOWLEDGE_BASE_CONNECTOR` with `connectorParameters.type: CUSTOM`. This is the managed
replacement for a self-managed CUSTOM source: documents are **pushed directly** into the data source
instead of being staged to S3 for a crawl. There is **no secret and no `connectionConfiguration`** — it is
a push target, not a crawl. **A self-managed Lambda `customTransformationConfiguration` has no managed
equivalent — do not present this connector as a substitute for it;** direct the customer to AWS Support (see
[mapping](references/bedrock-kb-migration/mapping.md)).

**Create (the data source reaches `AVAILABLE` directly).** Set `aclEnabled` **explicitly** — it is a
required customer choice for CUSTOM too, not a silent default:

```bash
aws bedrock-agent create-data-source --region <REGION> --profile <PROFILE> \
  --knowledge-base-id "<NEW_OWNED_KB>" --name "<DS_NAME>" --client-token "<CLIENT_TOKEN>" \
  --data-source-configuration '{
    "type": "MANAGED_KNOWLEDGE_BASE_CONNECTOR",
    "managedKnowledgeBaseConnectorConfiguration": {
      "connectorParameters": { "type": "CUSTOM", "version": "1", "aclEnabled": true }
    }
  }'
```

The service normalizes `connectorParameters` to its defaults (a `filterConfiguration` with the default
`maxFileSizeInMegaBytes`, `aclEnabled: false`, `version: "1"`) —
and defaults `mediaExtractionConfiguration.imageExtractionConfiguration.imageExtractionStatus` to `ENABLED`.
`mediaExtractionConfiguration` remains an optional sibling of `connectorParameters`.

**CUSTOM supports ACLs, set through `aclEnabled` — make it an explicit customer choice.** Per the
[Custom data source ACL docs](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-ds-custom-acl.html),
`aclEnabled: true` turns on document-level access-control filtering for a CUSTOM source; the example above
sets it explicitly rather than relying on the `false` default. Disclose the meaning (§3b) and set the value
the customer chose (`true` to enforce ACL filtering, `false` to accept none). **Do not call the CUSTOM
`aclEnabled` immutable** — that page states it can be set **on create or update**. This provisioning
workflow still sets it **explicitly at create** and makes **no update call**, so it is fixed at create by
this workflow, but it is not immutable at the API level for CUSTOM. When `aclEnabled` is `true`, each
`IngestKnowledgeBaseDocuments` push (a user-run step) **must supply the document's ACL metadata** (allowed
/ denied principals) — a document pushed without it is not access-controlled. **Deletion protection still
does not apply to the CUSTOM connector** — it is a direct-push target, not a crawl, so do not add a
`deletionProtectionConfiguration` block to a CUSTOM data source (the secure `ENABLED` default in §2 is for
the connectors that support it).

| Create parameter | Expected? | Notes |
|---|---|---|
| `connectorParameters.type` | **required** = `CUSTOM` | |
| `connectorParameters.version` | **required** = `"1"` (string) | |
| `connectorParameters.connectionConfiguration` | ❌ omit | No crawl target and no `secretArn` — documents are pushed |
| `connectorParameters.filterConfiguration.maxFileSizeInMegaBytes` | optional | Numeric string; default on the connector page |
| `connectorParameters.aclEnabled` | optional (**explicit choice**) | Service default `false`; **set it explicitly** with the customer. `true` enables document-level ACL filtering and requires ACL metadata on every `IngestKnowledgeBaseDocuments` push. Settable on create or update (not immutable for CUSTOM); this workflow sets it at create only. See the Custom ACL doc below |
| `vectorIngestionConfiguration.chunkingConfiguration` | optional | Managed chunking rules apply (§6): **forbidden with the managed embedding model** (omit it); with a custom embedding model, `FIXED_SIZE` or `NONE` only |

**Filling it is a user-run step, and this file gives no interface for it.** A CUSTOM source is never
synced: the **user** pushes documents straight in, and they become part of both the data source and the KB
with no sync step at all. The agent creates the data source and stops there. What the agent should tell the
user about the model, without handing them a call:

- **Push, don't sync.** Never run a sync against a CUSTOM data source — pushing and syncing the same source
  is a conflict, not a belt-and-braces approach.
- **Documents can be sent inline or referenced in S3**, including multimodal content, and each carries a
  caller-chosen identifier. Re-pushing the same identifier **overwrites** that document, which is how
  updates work here.
- **Metadata travels with the document** and is what retrieval filters act on later (§3).
- **Pushes are batched and rate-limited**, so a bulk load is a script with pacing, not a loop of one-off
  commands ([mapping](references/bedrock-kb-migration/mapping.md) carries the current batch size and rate).
- **Listing, fetching and deleting pushed documents is available directly** — no console round-trip needed
  when the user wants to check or clean up what they sent.

Retrieval is unchanged (§3). The `create-data-source` shape above reaches `AVAILABLE`; the document-push
behavior described here comes from the public direct-ingestion docs, which is where the user should get the
request shapes.

**Doc sources:**

- Connect a custom data source: https://docs.aws.amazon.com/bedrock/latest/userguide/custom-data-source-connector.html
- Custom data source access control (`aclEnabled`, ACL metadata on ingest, set on create or update): https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-ds-custom-acl.html
- Ingest changes directly (custom needs no sync; S3 does): https://docs.aws.amazon.com/bedrock/latest/userguide/kb-direct-ingestion.html
- Ingest documents directly (request bodies / examples): https://docs.aws.amazon.com/bedrock/latest/userguide/kb-direct-ingestion-add.html
- IngestKnowledgeBaseDocuments API: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_IngestKnowledgeBaseDocuments.html

---

## 3. Retrieval surfaces (runtime) — user-run; what they are and when each fits

> **The agent never queries a knowledge base.** Both surfaces below return document text, so running them is
> the **user's** step — during their own validation of the new KB, and in their application code. This
> section exists so the agent can *explain* the surfaces (the Explore mode), reason about **gap coverage**,
> and report **caller impact** in a plan. It deliberately carries no request shapes, parameter tables or CLI
> invocations: the user takes those from the API reference linked at the end, or generates a skeleton from
> their own SDK. For applied *configuration* the agent uses the §4 read-only probes, which return
> configuration only, never document text.
>
> **A content-returning read needs the customer's explicit yes first** — the rule is in
> [safety-and-iam](references/bedrock-kb-migration/safety-and-iam.md) → "Content-returning reads".

A managed KB has **two** query surfaces, and the choice between them is made **per question shape, not per
knowledge base**.

### `Retrieve` — one similarity search

One search, one round trip. Lowest cost and lowest latency, ranked chunks with relevance scores in the
results, and the caller keeps full control over how — or whether — an answer is generated. This is the
surface a self-managed KB already exposes, so it is the one existing callers are migrating.

### `AgenticRetrieveStream` — an FM planning loop, MANAGED-only

Instead of a single search, a foundation model drives a loop: decompose the question into sub-queries →
retrieve for each → judge whether the evidence is sufficient → iterate if not → return deduplicated chunks,
plus a grounded answer unless the caller asks for chunks only. When passage-level context is not enough it
can expand to a **whole document**, which is what makes summarization and "list every X" questions work. The
response is always a stream, and the planning steps are visible as trace events.

It also **routes across several knowledge bases**: register a few, give each a natural-language
description, and the planner chooses per sub-query, tagging each result with the KB that answered. Those
descriptions are the routing contract — a specific one-sentence pitch per KB routes well, "internal docs"
does not. This is what keeps a data-sources-per-KB split invisible to the caller
([mapping](references/bedrock-kb-migration/mapping.md) → "Gap coverage"). How many
knowledge bases one call may route across is a **quota** — read it from `kb-managed-quotas` before quoting
it, not a fixed law.

**This surface does not exist on a self-managed (`VECTOR`) KB at all.** It is the single largest capability
the migration gains, and three rows of the mapping's "Gap coverage" table lean on it. **The agent should
note the agentic surface as an adoption opportunity whenever it explains retrieval** — net-new value, not a
like-for-like port.

### Choosing the surface

| | `Retrieve` | `AgenticRetrieveStream` |
|---|---|---|
| Best for | short, well-scoped lookups; FAQ; latency-critical paths | multi-part, comparative, exploratory, cross-KB questions |
| Output | ranked chunks + scores | deduplicated chunks (streaming) + optional grounded answer |
| Query decomposition | no | yes |
| Multiple knowledge bases | no | yes — up to a published ceiling, enforced as a quota (read it live) |
| Whole-document expansion | no | yes, when passages are insufficient |
| Streaming | no | always |
| FM cost per call | none | one planner invocation per iteration |
| Latency | lowest | highest |
| Relevance scores | in the results | in the trace events only |
| Guardrails | supported, including the masking action | supported, but effectively blocking-only |
| Self-managed (`VECTOR`) KB | yes | **no — MANAGED only** |

Reranking is optional on both. Start with `Retrieve` for direct lookups; reach for the agentic surface when
questions are multi-part or the evidence spans several knowledge bases.

### What changes for existing `Retrieve` callers — report this as a caller impact, every time

The **operation names are unchanged**, which makes repointing at the new knowledge base id look sufficient.
It is not: the request body differs, and so does the meaning of a score. Report all of the following on
**every** plan that changes the target KB, and in any answer about whether callers keep working. Give each
item's concrete before and after value as written here (the old and new URI form, the old and new key
names, the zero-result behaviour), not only that something changes:

- **The new knowledge base id.** Callers must repoint at the owned KB's id; the source id keeps working
  against the untouched source.
- **The search-configuration wrapper changes.** A self-managed call carries `vectorSearchConfiguration`; a
  managed call carries `managedSearchConfiguration`. Sending the self-managed wrapper to a managed KB
  passes client-side validation and is **rejected by the service**.
- **Semantic-only search cannot be requested at all.** `overrideSearchType` is a member of the self-managed
  wrapper only. The managed wrapper has no such member, so a semantic-only call is not "refused by the
  service" — it is **structurally inexpressible**, and fails inside the caller's own SDK before a request
  is sent (§6 carries the exact message). Managed search is hybrid, always on and not configurable; the
  constraint and the feature are the same fact.
- **Score thresholds need re-tuning.** Scores are on a different scale on the managed knowledge base, and
  the scale also depends on the reranking mode, so a ported threshold silently changes how much it admits.
  Re-tune per reranking mode; compare ranking and content, not score magnitude.
- **Reranking defaults by embedding type, and is a caller option.** `managedSearchConfiguration` takes
  `rerankingModelType`. Omitted, it means `MANAGED` on a managed-embedding KB and behaves as `NONE` on a
  `CUSTOM`-embedding KB; an explicit `MANAGED` on a `CUSTOM` KB returns `ValidationException: Managed
  reranking is not supported for knowledge bases with custom embedding models.`
- **The result location changes form.** `location.s3Location.uri` changes from `s3://<bucket>/<key>` to
  `https://<bucket>.s3.amazonaws.com/<key>`, and a new `documentId` field carries the `s3://` URI (or the
  page URL). Code that splits on `s3://` gets no error, just a wrong value.
- **The system metadata keys change.** `x-amz-bedrock-kb-*` keys (for example
  `x-amz-bedrock-kb-data-source-id`) become `_`-prefixed keys (`_data_source_id`, `_chunk_id`,
  `_source_uri`, `_document_title`, `_file_type`, `_language_code`, `_created_at`, `_last_updated_at`,
  `_data_source_type`). User metadata keys are unchanged. Code reading the old key raises `KeyError`.
- **Some filter operators are not supported.** `startsWith` returns `STARTS_WITH operation type is not
  supported for managed store.` and `stringContains` returns `STRING_CONTAINS operation type is not
  supported for managed store.`; `implicitFilterConfiguration` is not a member of
  `managedSearchConfiguration`. Other operators keep their syntax inside the new wrapper.
- **An ACL knowledge base returns nothing without a user.** With `aclEnabled`, a call with no `userContext`
  returns 0 results and no error; a non-email `userId` also returns 0 results. Matching on the email ignores
  case and surrounding spaces.
- **Overlapping data sources return duplicates.** Two data sources over the same content return each chunk
  twice (different `_chunk_id`s).

Several of these return empty or wrong results rather than errors, so a caller cannot rely on an exception
to find them. In the handoff, compare `Retrieve` against `Retrieve` with the reranking mode held constant,
and on an ACL KB query as a known in-ACL user.

- **A threshold does not port between the two query surfaces either.** `Retrieve` returns scores in the
  results; the agentic surface exposes them only in trace events, so validation built on thresholds has to
  read the trace.

Filter syntax carries over unchanged, and metadata filtering keeps working.

### If the user plans to adopt the agentic surface

- **Cost has a different shape.** It bills the agentic call **plus** the underlying retrieval calls it
  issues, times the iteration count, so an estimate from `Retrieve` volume alone understates it; the planner
  model sets the rate. Fetch current rates ([cost-analysis](references/bedrock-kb-migration/cost-analysis.md)
  rules apply: fetched rates only, never recalled).
- **It needs permissions beyond plain retrieval**, including one for fetching whole documents; without that
  last one, retrieval still works and only document-expansion fails (weak summarization answers, not an
  error). Take the current action list from the API reference at adoption time.
- **The intermediate sub-queries are an audit surface** the planner invents — log the full trace, not just
  the returned results.
- **Iterations drive both cost and latency**, so the iteration cap is the main tuning knob.

**Doc sources — the authority for request shapes, enums and bounds (this section deliberately carries none).
Check the API reference for the current fields and limits before a call — it governs the shape, while the
user guide governs behavior and defaults:**

- Retrieve API reference: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_Retrieve.html
- AgenticRetrieveStream API reference: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_AgenticRetrieveStream.html
- Quotas and limits (knowledge bases per agentic call, iteration default and maximum — quota, not contract): https://docs.aws.amazon.com/bedrock/latest/userguide/quotas.html

---

## 3b. ACL-aware retrieval (managed) — capability and its boundary

Source docs: `kb-managed-acl` and `kb-test-retrieve-acl` (re-verify against the docs). Enabled per data
source via `connectorParameters.aclEnabled` (§2).

> **ACL awareness is NOT authorization — say this whenever the feature comes up.** Per the AWS docs it is
> ACL-aware *filtering*, not a security boundary. The service **does not authenticate end users**: your
> application authenticates them and passes verified identity context, and because the service cannot verify
> that context's authenticity, **it must not be the sole access-control mechanism without upstream
> authentication.** Describing it as "managed handles authorization" is a security misrepresentation.

**Two stages.** *Pre-retrieval filtering* — permissions (allowed/denied users, allowed/denied groups) are
crawled during ingestion and results are filtered against the user context at query time. *Real-time ACL
verification* — for connectors that support it, a live call to the source confirms the user still has access
to each returned document, catching changes made since the last sync. Both stages use the same logic and
**deny always overrides allow**. The pipeline **fails closed**: group-resolution failure, verification
timeout or internal error withholds the documents.

**Identity model — the sharp edge.** The user is **always identified by email**, used as the universal
identifier, and it must match the email on that user in every connected source (the match ignores case
and surrounding spaces). There is **no
alias resolution and no cross-identity-provider mapping**. Groups, by contrast, are identified however each
connector represents them (name, id, other) and are matched against crawled memberships, which are resolved
automatically at query time but are **only as fresh as the last sync** unless real-time verification covers
that connector.

**Connector support — not uniform, and it constrains `authType`:**

| Connector | Pre-retrieval filter | Real-time ACL | Constraint to plan around |
|---|---|---|---|
| SharePoint | ✅ | ✅ | Application-level permissions (2LO); **requires `ENTRA_ID_APP_ONLY`** |
| OneDrive | ✅ | ✅ | 2LO; requires the Entra app-id auth type |
| Google Drive | ✅ | ✅ | Domain-wide delegation (2LO); **requires `SERVICE_ACCOUNT`** |
| Confluence | ✅ | ✅ | Admin API token for the live check; **requires `BASIC`** |
| Amazon S3 | ✅ | ❌ | ACLs come from a **customer-provided ACL configuration file in S3** — that file is the source of truth, so there is nothing live to verify |
| Custom | ✅ | ❌ | ACLs from customer-provided metadata, same reasoning |
| Web Crawler | ❌ | n/a | **ACL awareness cannot be enabled** — web content has no permission model |

Two planning consequences: **enabling ACLs can force an `authType`** (a SharePoint source needing real-time
ACL cannot use `OAUTH2_APP`), and **`aclEnabled` is immutable after create on S3 and permanent on
Confluence** (§2) — so the ACL decision is a create-time decision, not something to defer.

---

## 4. Read / status commands (pre-approved read-only probes)

```bash
aws bedrock-agent get-knowledge-base   --region <REGION> --profile <PROFILE> --knowledge-base-id <KB_ID>
aws bedrock-agent list-data-sources    --region <REGION> --profile <PROFILE> --knowledge-base-id <KB_ID>
aws bedrock-agent get-data-source      --region <REGION> --profile <PROFILE> --knowledge-base-id <KB_ID> --data-source-id <DS_ID>
aws bedrock-agent get-ingestion-job    --region <REGION> --profile <PROFILE> --knowledge-base-id <KB_ID> --data-source-id <DS_ID> --ingestion-job-id <JOB_ID>
```

- KB readiness: `knowledgeBase.status` → wait for `ACTIVE`.
- Data source readiness: `dataSource.status` → wait for `AVAILABLE`. These reads take **no** `--client-token`.

---

## 5. StartIngestionJob — a user-run handoff step

Ingestion is **not** an agent action, and this file gives no interface for running one. Once the agent
confirms KB `ACTIVE` and all data sources `AVAILABLE`, the **user** starts ingestion on each new (owned)
data source — never the original — and waits for `COMPLETE`. The agent's part is to sequence the handoff
and say what to expect, not to issue the call; the user takes the command from the AWS documentation.

Two things worth telling them up front, so a normal result is not read as a failure:

- The ingestion job's `numberOfMetadataDocumentsScanned` count is not a health signal: do not tell the
  customer to expect a particular value; metadata filtering works either way.
- An ingestion that ends `FAILED` having scanned 0 documents is an environment or pipeline issue, not a
  configuration problem — re-check access to the source before touching the config the agent created.

---

## 6. API error → cause → fix

| Error / message | Cause | Fix |
|---|---|---|
| `ThrottlingException` / `TooManyRequestsException` / HTTP 429 on `create-*` / `get-*` | Control-plane request rate exceeded the account/Region quota (common when firing creates one-by-one, fast) | Slow down: batch creates and add a pause; back off with jitter and retry. Use the generated provisioning script's `CONTROL_PLANE_RPS` / batch settings (§9) rather than rapid sequential CLI calls |
| `ServiceQuotaExceededException` on `create-data-source` | More data sources on one KB than its quota allows (`L-F02D918A`, read live) | Split the source set across multiple KBs |
| `ParamValidation: Unknown parameter ... managedKnowledgeBaseConfiguration` (or "Invalid type ... valid values: VECTOR, ...", or unknown type `MANAGED_KNOWLEDGE_BASE_CONNECTOR`) | The AWS CLI model is too old to know the managed-KB shapes — rejected client-side | Upgrade to a current AWS CLI version (or use a current AWS SDK), then re-run the same command. AWS service calls go through the AWS CLI or an AWS SDK — if `--generate-cli-skeleton` confirms the shape is absent, upgrade the CLI/SDK rather than routing around it |
| `ValidationException` on `chunkingStrategy` | `DEFAULT`/`HIERARCHICAL`/`SEMANTIC` on managed | Omit `chunkingConfiguration` to use the managed default chunking, or (custom embedding model only) pass `FIXED_SIZE`/`NONE` explicitly |
| `ValidationException: "A chunking strategy cannot be specified with a managed embedding model"` | Any `chunkingConfiguration` (incl. `FIXED_SIZE`/`NONE`) on a KB using the **managed** embedding model | Omit `chunkingConfiguration` entirely; the managed default applies. A chunking config is accepted only with a **custom** embedding model (not stated in the user guide) |
| `"Unsupported data source type for MANAGED knowledge base type."` | Top-level `dataSourceConfiguration.type: CUSTOM` (the self-managed shape) on a managed KB | The CUSTOM connector **is** supported — use `type: MANAGED_KNOWLEDGE_BASE_CONNECTOR` with `connectorParameters.type: CUSTOM` (§2d). No S3 staging required |
| Rejection mentioning `storageConfiguration` | Sent a customer store to a managed KB | Omit `storageConfiguration` — managed provisions its own store |
| `"Unable to verify the specified embedding model"` | Role can't invoke the model; unsupported model ARN; model not available in the KB's Region; or dims/dataType not the managed values | Use a supported FM/IP ARN available in-Region at the managed dimension and data type, and ensure the role can invoke it (§1) |
| `"MANAGED knowledge base type supports only 1024 embedding dimensions"` | `embeddingModelConfiguration...dimensions` set to another value | Use the dimension the error and the create page name; re-embed a reduced-dimension source KB at it (§1) |
| `"MANAGED knowledge base type supports only FLOAT32 embedding data type"` | `embeddingDataType: BINARY` (or non-FLOAT32) on managed | Use `FLOAT32` or omit it; a BINARY source KB must be re-embedded as FLOAT32 (§1) |
| `"The specified embedding model ... is not supported"` | Custom `embeddingModelArn` isn't one of the supported managed-KB embedding models, or that model isn't available in the KB's Region | Pick a supported model available in the KB's Region (§1 public doc links), or use `embeddingModelType: MANAGED` (default) |
| Connector ingests nothing (auth connector) | `aclEnabled` misconfigured or filters too narrow | For auth connectors set `connectorParameters.aclEnabled` intentionally; there is no managed `crawlAcl` |
| `retrieve` 400 about `vectorSearchConfiguration` | Wrong wrapper on managed | Use `managedSearchConfiguration` |
| `Unknown parameter in retrievalConfiguration.managedSearchConfiguration: "overrideSearchType"` | Ported a self-managed `SEMANTIC` call onto a managed KB | `overrideSearchType` exists **only** under `vectorSearchConfiguration`; the managed wrapper has no such member, so semantic-only is structurally inexpressible (§3). Drop the parameter |
| Data source → `FAILED`, "Failed to connect to the URL of your data source" | Wrong/missing `connectionConfiguration.secretArn`, secret keys don't match the managed `authType`, SharePoint `ENTRA_ID_APP_ONLY` missing `certificateS3Path`, wrong region, or connector app not authorized | One diagnosis pass (§2b): confirm the secret keys match the managed `authType`, the certificate is present for Entra methods, the ARN/region are correct, and the KB role can read the secret (and certificate); then report and stop |
| SharePoint data source ingests nothing / rejected on `siteUrls` | `siteUrls` passed as a string, not a JSON array | Pass `siteUrls` as a JSON array of full site URLs |
| `Value at 'dataEntityConfiguration' failed to satisfy constraint: Member must not be null` on a Confluence `create-data-source` | `dataEntityConfiguration` omitted (the page marks it optional; the service requires it) | Send the block with the entity types the source crawled (§2b Confluence), then create the data source again |
| `Value at 'connectionConfiguration.hostUrl' failed to satisfy constraint` on a Confluence create | `hostUrl` copied with a trailing slash, or not an `.atlassian.net` base URL | Use the base URL with no trailing slash |
| `AccessDeniedException` reading the secret during sync | KB role lacks `secretsmanager:GetSecretValue` / `kms:Decrypt` | Grant those to the KB execution role on the secret (and its CMK) |

---

## 7. Client tokens (idempotency) — attach to mutating calls

Every resource-creating call the agent issues (`create-knowledge-base`, `create-data-source`) accepts a
`--client-token` idempotency token. **Attach one to each such call** so a safe retry of an
interrupted/uncertain call cannot create a duplicate resource — AWS returns the original result when it sees
the same token with the same parameters.

> **`--client-token` is an idempotency value, not authentication and not a credential or secret.** It is
> safe to log, record, and reuse for a retry — it grants no access and unlocks nothing. It is also
> **independent of `--profile`**. The two answer different questions: the **ephemeral profile or assumed-role
> credentials authenticate** the caller — that is what a call needs to be allowed at all; `--client-token`
> makes a *create* **idempotent** so a retry does not duplicate the resource. You use both together on a
> create: the credentials authenticate, the client token de-duplicates. Supplying AWS credentials does
> **not** remove the need for a client token, and a client token never authenticates a call. (Read/poll
> calls need only credentials — no client token; see below.) It is **optional to the API on both
> `CreateKnowledgeBase` and `CreateDataSource`** (§1/§2) — the current API references mark it optional on
> each — **but required by this workflow**, which attaches a stable per-operation token to every create for
> resume safety. Never call it API-required; either way it is an API idempotency input, never a secret.

- **One token per logical operation, derived from the plan, never random at run time** — not one shared
  across calls. Use the form in [implement-kb](references/bedrock-kb-migration/implement-kb.md) ("Use stable
  idempotency tokens"): `mig-<prefix>-<hash>-<seq>`, minted at plan time from the migration id, resource type
  and planned name, so a re-run sends the same token. A client token must be **at least 33 characters**.
- **Reuse a token only for a deliberate retry of the same operation** (same params); changed params require
  a new token.
- **Read/poll calls carry NO client token.** `get-knowledge-base`, `list-knowledge-bases`,
  `get-data-source`, `list-data-sources`, `get-ingestion-job` and `sts get-caller-identity` do not accept
  one. Never invent a correlation token for a read.
- **Record the client token alongside the operation and the resulting resource ID** so the user can
  correlate a logged mutating call with the exact resource and safely re-issue it. The token is an input
  only — it never appears in a `get-*` response, so capture it at call time.

**`clientToken` field reference** (confirm the current requirement and constraints before a call):

- [CreateKnowledgeBase API reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_CreateKnowledgeBase.html)
- [CreateDataSource API reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_CreateDataSource.html)

---

## 9. Rate limits & batching (build with a script, not rapid one-by-one CLI)

The build-time control-plane operations used here (`CreateKnowledgeBase`, `CreateDataSource`,
`StartIngestionJob`, and the `Get*`/`List*` pollers) are **throttled per-account, per-Region**, and most
limits are adjustable. Issuing many creates back-to-back on the CLI is the usual way to hit
`ThrottlingException`, which is why the Implement phase **generates a Python provisioning script** that
creates resources in rate-limit-aware batches (spec in
[implement-kb](references/bedrock-kb-migration/implement-kb.md)).

### What the script does to stay under the limits

- **Throttles** control-plane calls to a conservative requests-per-second (`CONTROL_PLANE_RPS`).
- **Batches** `create-data-source` calls (`DATA_SOURCE_BATCH_SIZE`) with an `INTER_BATCH_PAUSE_SECONDS`
  cool-down between batches.
- **Backs off** on `ThrottlingException`/429 with exponential delay + full jitter, on top of boto3's
  `adaptive` retry mode (`Config(retries={"mode": "adaptive"})`).
- **Attaches a unique `--client-token`** to every create (§7) so a retry after a throttle or timeout can't
  duplicate a resource.

### Hard limit to design around

**Data sources per KB** (quota `L-F02D918A`, read live). The first `CreateDataSource` past it returns `ServiceQuotaExceededException`. Split a
larger source set across multiple KBs — the script's `KNOWLEDGE_BASES` is a list for exactly this.

### Verify, don't hardcode

The script's defaults (`CONTROL_PLANE_RPS`, batch size, pause, concurrency) are **conservative starting
points, not authoritative numbers.** Re-check `kb-managed-quotas`
and the current per-Region values for the user's account in the **Service Quotas console**
(`https://console.aws.amazon.com/servicequotas/home/services/bedrock/quotas`; search the relevant
`CreateDataSource` / `StartIngestionJob` / `CreateKnowledgeBase` "requests per second" quotas) and lower the
rate if throttling appears. Never assert a quota you have not verified.

### Running the script is gated

Writing the script is fine; **running it requires explicit approval of that run.** It defaults to
`DRY_RUN = True` (prints intended calls, mutates nothing); a real run needs `--execute`. It mutates **owned
resources only**, never the original KB, and **provisions only — it does not ingest**, so it manages no
ingestion-job concurrency. See [implement-kb](references/bedrock-kb-migration/implement-kb.md) for the
build → review → preview → approve → execute → confirm-`AVAILABLE` flow.
