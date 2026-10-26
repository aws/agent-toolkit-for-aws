# IaC Schema Reference — Bedrock Knowledge Bases (CloudFormation + Terraform)

> Schema facts for the Infrastructure-as-Code that describes a Bedrock Knowledge Base, in both supported
> formats: **CloudFormation** (`AWS::Bedrock::KnowledgeBase` + `AWS::Bedrock::DataSource`) and **Terraform**
> (`aws_bedrockagent_knowledge_base` + `aws_bedrockagent_data_source`). The single source of truth for
> **resource types, how to verify the live schema, the accepted Managed KB (`MANAGED`) vs self-managed KB
> (`VECTOR`; the host skill calls this a Customer-managed KB) shapes per format, and the public doc links.**
> Both the KB path's discovery templates (the Discover phase emits `source-config.yaml` +
> `managed-target.yaml`) and the IaC path's output (the Implement phase emits `managed-target.<ext>`) are
> built from these facts.
>
> Use this file for **schema/shape** facts; use [mapping](references/bedrock-kb-migration/mapping.md) for the
> *substitution* rules (what each setting becomes) and
> [managed KB API](references/bedrock-kb-migration/managed-kb-api.md) for the camelCase API field names and
> accepted/rejected values that the IaC properties wrap.
>
> **Reading the public docs.** Read every AWS/CloudFormation and Terraform doc read-only, per
> [safety-and-iam](references/bedrock-kb-migration/safety-and-iam.md). AWS/CloudFormation: `curl` the `.md`
> endpoint. Terraform: the authoritative source of record is the **HashiCorp Terraform Registry** page for
> the AWS provider (links in §3–§4), but it is JS-rendered, so `curl` its plain-text twin — the provider's
> raw GitHub Markdown, identical content — instead. Do not download the Terraform provider to check
> it (§0); if the user runs `terraform providers schema -json` themselves, its output wins on any conflict.

## Contents

- [0. Verify the live schema before generating a template](#0-verify-the-live-schema-before-generating-a-template--dont-trust-memory)
- [1. CloudFormation — resource types and the source (`VECTOR`) shape](#1-cloudformation--resource-types-and-the-source-vector-shape)
- [2. CloudFormation — the MANAGED target shape](#2-cloudformation--the-managed-target-shape)
- [3. Terraform — resource types and the source (`VECTOR`) shape](#3-terraform--resource-types-and-the-source-vector-shape)
- [4. Terraform — the MANAGED target shape](#4-terraform--the-managed-target-shape)
- [5. Cross-format notes](#5-cross-format-notes)
- [Common mistakes](#common-mistakes)

---

## 0. Verify the live schema before generating a template — don't trust memory

Both schemas evolve; do not rely on memory or a hardcoded enum. **Before writing or updating any
template, confirm the current schema** with the format-appropriate read-only command, and take the
accepted type/enum values and property/argument names from its output.

**CloudFormation** (`aws cloudformation describe-type`, read-only):

```bash
aws cloudformation describe-type --type RESOURCE \
  --type-name AWS::Bedrock::KnowledgeBase --region <region> --query 'Schema' --output text
aws cloudformation describe-type --type RESOURCE \
  --type-name AWS::Bedrock::DataSource   --region <region> --query 'Schema' --output text
```

**Terraform: do not run a local schema check.** `terraform providers schema -json` and
`terraform validate` need `terraform init`, which downloads the AWS provider (a large download) — too
heavy for a migration review, and it reads the user's global Terraform configuration. Take argument
names from the documented shapes in §3–§4 (the registry's raw GitHub Markdown, per the note above),
record `schema_valid: unverified` for the Terraform file, show the user a `diff -u` of the source file
against the migrated one, and give them the command to run before they deploy:

```bash
diff -u main.tf "$output_dir/managed-target.tf"     # the review artifact; read-only
# for the user to run before deploy, not the agent:
terraform init -backend=false && terraform validate
```

**Record the verification outcome — and never upgrade an unverified shape to a verified one.** The
result of §0 is one of exactly three states, and it is what the Implement phase reports as
`schema_valid`:

| Outcome | `schema_valid` | What it means |
|---|---|---|
| The check ran and the emitted shapes match | `verified` | Safe to present as deployable |
| The check ran and found a violation | `invalid` | Report the offending resource/property, withhold from the deployable set |
| The check **could not run** (tool absent, no credentials, no provider, region unsupported) | `unverified` | Say which command was unavailable and why. The template is **documented-shape only** — present it as needing the user's own validation before deploy. It is **not** `verified` |

If `terraform` or the AWS CLI is not installed, the honest answer is `unverified`, not `true`. And if either
live schema disagrees with this file, **trust the live schema**, generate from it, and update this reference
with the new finding.

**What the live schema cannot check.** `ConnectorParameters` / `connector_parameters` is declared free-form
in both formats (proof in §2), so `describe-type`, `cfn-lint`, `terraform validate` and
`--generate-cli-skeleton` all accept **any** content inside it. That one block is validated only by the
service at create time, and [managed KB API](references/bedrock-kb-migration/managed-kb-api.md) is its
authority — §0 verification tells you nothing about it.

---

## 1. CloudFormation — resource types and the source (`VECTOR`) shape

Both `VECTOR` and `MANAGED` knowledge bases use the same two resource types
(`AWS::Bedrock::KnowledgeBase` + `AWS::Bedrock::DataSource`) and are **CloudFormation-deployable**.
Build a source (`VECTOR`) template with `KnowledgeBaseConfiguration.Type: VECTOR` +
`VectorKnowledgeBaseConfiguration`, the discovered `StorageConfiguration` block, the matching
data-source connector block, and the chunking/parsing config — translating **camelCase API fields to
PascalCase CFN properties** (the CLI/JSON shapes in
[managed KB API](references/bedrock-kb-migration/managed-kb-api.md) are camelCase).

- AWS::Bedrock::KnowledgeBase — https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrock-knowledgebase.html
- AWS::Bedrock::DataSource — https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrock-datasource.html

---

## 2. CloudFormation — the MANAGED target shape

Set `KnowledgeBaseConfiguration.Type: MANAGED` with a `ManagedKnowledgeBaseConfiguration`, and set the
data source's `DataSourceConfiguration.Type: MANAGED_KNOWLEDGE_BASE_CONNECTOR` with a
`ManagedKnowledgeBaseConnectorConfiguration`. **Omit `StorageConfiguration`** — the managed store is
auto-provisioned, and there is no `StorageConfiguration` on a Managed KB. Apply
[mapping](references/bedrock-kb-migration/mapping.md) for the source-type substitutions and the managed
runtime limits a schema-valid template must still satisfy.

### ⚠️ The one place CloudFormation is NOT PascalCase

CloudFormation property names are PascalCase — **except inside `ConnectorParameters`, which is a
free-form pass-through whose keys are the camelCase API names.** The live schema is explicit that
nothing inside it is modelled:

```json
"ManagedKnowledgeBaseConnectorConfiguration": {
  "type": "object", "additionalProperties": false,
  "properties": {
    "DeletionProtectionConfiguration": { "$ref": "#/definitions/DeletionProtectionConfiguration" },
    "MediaExtractionConfiguration":    { "$ref": "#/definitions/MediaExtractionConfiguration" },
    "ConnectorParameters": { "type": "object", "description": "Connector-specific parameters." }
  }
}
```

`ConnectorParameters` has **no `properties` and no `additionalProperties: false`** — CloudFormation
passes the object through to `CreateDataSource` verbatim. Consequences, all verified:

- `Type: S3` / `Version: "1"` / `ConnectionConfiguration` / `BucketName` / `InclusionPrefixes` inside
  this block are **wrong**. The correct keys are `type`, `version`, `connectionConfiguration`,
  `bucketName`, `inclusionPrefixes` — from
  [managed KB API](references/bedrock-kb-migration/managed-kb-api.md) §2/§2b.
- **No tool catches the mistake.** `describe-type`, `cfn-lint`, `validate-template` and
  `--generate-cli-skeleton` (which returns `connectorParameters: {}`) all pass a PascalCased blob. It
  fails at deploy, against the live service.
- The **wrappers** around it *are* PascalCase and *are* schema-checked:
  `DeletionProtectionConfiguration` and `MediaExtractionConfiguration` are **siblings of**
  `ConnectorParameters`, inside `ManagedKnowledgeBaseConnectorConfiguration`. Putting either on the
  data source's `Properties` is a hard schema error (`additionalProperties: false`).

### Canonical managed CloudFormation shape — copy this structure

```yaml
Resources:
  MyKnowledgeBaseManaged:
    Type: AWS::Bedrock::KnowledgeBase
    Properties:
      Name: my-kb-managed
      RoleArn: !GetAtt KbExecutionRoleManaged.Arn
      # Tags is a MAP (TagsMap), not a list of Key/Value pairs:
      Tags: { Workload: docs }
      KnowledgeBaseConfiguration:
        Type: MANAGED
        ManagedKnowledgeBaseConfiguration:
          # EmbeddingModelType enum is exactly [MANAGED, CUSTOM]. "DEFAULT"/"MANAGED_DEFAULT" do not
          # exist. MANAGED = service-managed model, no ARN, keeps the reranker. For CUSTOM, add
          # EmbeddingModelArn + EmbeddingModelConfiguration.BedrockEmbeddingModelConfiguration
          # { Dimensions: <MANAGED_DIMENSION>, EmbeddingDataType: FLOAT32 } — the only accepted values
          # (the managed dimension is on the create page; see mapping Key findings).
          EmbeddingModelType: MANAGED
          ServerSideEncryptionConfiguration:
            KmsKeyArn: !Ref CorpusKmsKeyArn     # KB-level CMK; there is no per-data-source SSE
      # NO StorageConfiguration.

  MyDataSourceManaged:
    Type: AWS::Bedrock::DataSource
    Properties:
      Name: my-corpus-managed
      KnowledgeBaseId: !GetAtt MyKnowledgeBaseManaged.KnowledgeBaseId
      DataSourceConfiguration:
        Type: MANAGED_KNOWLEDGE_BASE_CONNECTOR
        ManagedKnowledgeBaseConnectorConfiguration:
          # >>> camelCase from here down — free-form pass-through to the API <<<
          ConnectorParameters:
            type: S3
            version: "1"
            connectionConfiguration:
              bucketName: !Ref CorpusBucketName
              bucketOwnerAccountId: !Ref AWS::AccountId
            filterConfiguration:
              inclusionPrefixes:
                - published/en/
          # <<< back to PascalCase: schema-checked siblings of ConnectorParameters >>>
          DeletionProtectionConfiguration:
            DeletionProtectionStatus: ENABLED       # secure default; set DISABLED only on explicit customer opt-out
            # DeletionProtectionThreshold: omitted = the service default (API reference has the range)
          # MediaExtractionConfiguration:         # the managed home for image/audio/video extraction
          #   ImageExtractionConfiguration: { ImageExtractionStatus: ENABLED }
      # VectorIngestionConfiguration: omit it entirely on a managed-embedding KB — any
      # ChunkingConfiguration (even FIXED_SIZE/NONE) is rejected with
      # "A chunking strategy cannot be specified with a managed embedding model".
      # ONLY with a CUSTOM embedding model may you carry FIXED_SIZE/NONE over, e.g.:
      #   VectorIngestionConfiguration:
      #     ChunkingConfiguration:
      #       ChunkingStrategy: FIXED_SIZE          # custom-embedding KB only; SEMANTIC/HIERARCHICAL rejected
      #       FixedSizeChunkingConfiguration: { MaxTokens: <FROM_SOURCE>, OverlapPercentage: <FROM_SOURCE> }
      # No ParsingConfiguration (managed forces SMART_PARSING), no DataDeletionPolicy, no
      # ServerSideEncryptionConfiguration at this level.
```

For a source whose original chunking was **SEMANTIC or HIERARCHICAL**, omit the whole
`ChunkingConfiguration` block — the managed default applies (see
[mapping](references/bedrock-kb-migration/mapping.md)); do not translate an unsupported strategy.
The same omission is **required** whenever the KB uses the managed embedding model, whatever the
source strategy was: a chunking block is accepted only on a custom-embedding KB.

`!GetAtt <kb>.KnowledgeBaseId` and `.KnowledgeBaseArn` are the readable attributes. `Name` is **not**
a `GetAtt` attribute — the full read-only set is `KnowledgeBaseId`, `KnowledgeBaseArn`, `CreatedAt`,
`UpdatedAt`, `FailureReasons`, `Status`.

- AWS::Bedrock::KnowledgeBase — https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrock-knowledgebase.html
- AWS::Bedrock::KnowledgeBase ManagedKnowledgeBaseConfiguration — https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-bedrock-knowledgebase-managedknowledgebaseconfiguration.html
- AWS::Bedrock::DataSource — https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrock-datasource.html

### Create-only properties (from the live schema) — why this is a new resource, not an update

A `VECTOR` KB cannot be converted to `MANAGED` in place. `AWS::Bedrock::KnowledgeBase` declares
`StorageConfiguration`, `KnowledgeBaseConfiguration/Type` and
`KnowledgeBaseConfiguration/ManagedKnowledgeBaseConfiguration` as **create-only**, and
`AWS::Bedrock::DataSource` declares `KnowledgeBaseId`, `DataSourceConfiguration/Type`,
`VectorIngestionConfiguration/ChunkingConfiguration` and `.../ParsingConfiguration` as create-only.

Changing any of them **replaces** the resource. Two consequences to state in the plan rather than
discover at deploy time: the managed KB is a new resource with a new ID (so every consumer holding the
old KB ID must be repointed), and for a template consumers instantiate themselves — a Service Catalog
product, a shared module, a nested stack — an in-place update is impossible, so **existing instances
must be re-launched, not updated**.

---

## 3. Terraform — resource types and the source (`VECTOR`) shape

The AWS Terraform provider (`hashicorp/aws`) models a KB with **`aws_bedrockagent_knowledge_base`**
and each data source with **`aws_bedrockagent_data_source`**. Argument names are **snake_case**. A source (`VECTOR`) KB looks like:

```hcl
resource "aws_bedrockagent_knowledge_base" "example" {
  name     = "example"
  role_arn = aws_iam_role.example.arn
  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = "arn:aws:bedrock:<region>::foundation-model/<model>"
    }
  }
  storage_configuration {
    type = "OPENSEARCH_SERVERLESS"           # or aurora / pinecone / s3_vectors / opensearch_managed_cluster ...
    opensearch_serverless_configuration { collection_arn = "..." vector_index_name = "..." field_mapping { ... } }
  }
}
```

A data source's chunking lives under `vector_ingestion_configuration { chunking_configuration
{ chunking_strategy = "FIXED_SIZE" fixed_size_chunking_configuration { max_tokens overlap_percentage } } }`.
There is no `parsing_configuration` to emit on managed (Smart Parsing is applied automatically). Emit a
`chunking_configuration` block **only when the KB uses a custom embedding model**; on a managed-embedding KB omit it entirely (any strategy is rejected —
see [mapping](references/bedrock-kb-migration/mapping.md)).

**Provider docs — trusted public source (Terraform Registry), plus the `curl`-able twin to fetch it:**

- **`aws_bedrockagent_knowledge_base` — Terraform Registry (authoritative source of record):** https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagent_knowledge_base
- **`aws_bedrockagent_data_source` — Terraform Registry (authoritative source of record):** https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagent_data_source
- Plain-text twin to `curl` (the Registry page is JS-rendered — this is the same content, fetchable):
  - `aws_bedrockagent_knowledge_base`: https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/main/website/docs/r/bedrockagent_knowledge_base.html.markdown
  - `aws_bedrockagent_data_source`: https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/main/website/docs/r/bedrockagent_data_source.html.markdown

---

## 4. Terraform — the MANAGED target shape

The provider supports the managed KB directly in recent `hashicorp/aws` versions: in the provider schema
`aws_bedrockagent_knowledge_base.knowledge_base_configuration` exposes
`managed_knowledge_base_configuration` and `aws_bedrockagent_data_source.data_source_configuration`
exposes `managed_knowledge_base_connector_configuration`. Read the first version that adds these blocks from the
provider's CHANGELOG (`https://github.com/hashicorp/terraform-provider-aws/blob/main/CHANGELOG.md`, search
`managed_knowledge_base`) and say that minimum version in the output — older provider versions lack it.
Suggest `terraform fmt` alongside `terraform validate` to the user. The agent does not
check the installed version (§0): the shape is `unverified`, and the user's own `terraform validate`
is what confirms it.

`managed_knowledge_base_configuration` accepts exactly: `embedding_model_arn`, `embedding_model_type`,
a nested `embedding_model_configuration { bedrock_embedding_model_configuration { dimensions,
embedding_data_type, audio { … }, video { … } } }`, and
`server_side_encryption_configuration { kms_key_arn }`. There is no `storage_configuration` inside it.

**Managed KB** — `type = "MANAGED"` with a `managed_knowledge_base_configuration` block, and **no
`storage_configuration`** (auto-provisioned). `embedding_model_type = "MANAGED"` is the service-managed
model and keeps the managed reranker. Carry the source KB's CMK forward in
`server_side_encryption_configuration.kms_key_arn` (see
[managed KB API](references/bedrock-kb-migration/managed-kb-api.md) "Encryption at rest"); omit that block
only when the customer accepts the AWS-owned default, and never silently drop a CMK the source KB was
using:

```hcl
resource "aws_bedrockagent_knowledge_base" "example" {
  name     = "example-managed-kb"
  role_arn = aws_iam_role.example.arn
  knowledge_base_configuration {
    type = "MANAGED"
    managed_knowledge_base_configuration {
      embedding_model_type = "MANAGED"
      server_side_encryption_configuration {
        kms_key_arn = var.kb_kms_key_arn
      }
    }
  }
}
```

Bring-your-own embedding uses `embedding_model_type = "CUSTOM"` with `embedding_model_arn` and
`embedding_model_configuration { bedrock_embedding_model_configuration { dimensions = <MANAGED_DIMENSION> } }`
(the managed dimension / FLOAT32 only, per the create page; `CUSTOM` disables the managed reranker — see
[mapping](references/bedrock-kb-migration/mapping.md)).

**Managed data source** — `type = "MANAGED_KNOWLEDGE_BASE_CONNECTOR"` with a
`managed_knowledge_base_connector_configuration` block. In the provider schema
`connector_parameters` is typed **`"string"`**, not a block or a map — so **`jsonencode({...})` is
mandatory**, not a style choice, and its keys are the API camelCase names (`type`, `version`,
`connectionConfiguration`, `aclEnabled`, `filterConfiguration`, `secretArn`, `siteUrls`, …) exactly as
documented in [managed KB API](references/bedrock-kb-migration/managed-kb-api.md), embedded as JSON
inside the snake_case HCL.

The other two members of `managed_knowledge_base_connector_configuration` are **nested HCL blocks,
siblings of `connector_parameters` — not keys inside the `jsonencode`**:

| Member | Form | Contents |
|---|---|---|
| `connector_parameters` | string argument (`jsonencode({...})`) | free-form camelCase connector body |
| `deletion_protection_configuration { }` | HCL block | `deletion_protection_status` (**required**), `deletion_protection_threshold` (optional number) |
| `media_extraction_configuration { }` | HCL block | `image_extraction_configuration { image_extraction_status }`, `audio_extraction_configuration { … }`, `video_extraction_configuration { … }` |

Putting `deletionProtectionConfiguration` inside the `jsonencode` blob is a silent failure: the
provider accepts the string, and the deletion-protection setting is never applied.

```hcl
resource "aws_bedrockagent_data_source" "example" {
  knowledge_base_id = aws_bedrockagent_knowledge_base.example.id
  name              = "example-s3-managed"
  data_source_configuration {
    type = "MANAGED_KNOWLEDGE_BASE_CONNECTOR"
    managed_knowledge_base_connector_configuration {
      # camelCase inside the jsonencode — this string is passed to the API verbatim.
      connector_parameters = jsonencode({
        type    = "S3"
        version = "1"
        connectionConfiguration = { bucketName = "<bucket>", bucketOwnerAccountId = "<account-id>" }
        aclEnabled          = false
        # filterConfiguration = { inclusionPrefixes = [...] }   # carry the source's prefixes/patterns; omit maxFileSizeInMegaBytes to keep the service default
      })

      # snake_case HCL blocks — SIBLINGS of connector_parameters, never keys inside it.
      deletion_protection_configuration {
        deletion_protection_status    = "ENABLED"   # secure default; set "DISABLED" only on explicit customer opt-out
        # deletion_protection_threshold omitted = the service default (API reference has the range)
      }
      # media_extraction_configuration {
      #   image_extraction_configuration { image_extraction_status = "ENABLED" }
      # }
    }
  }
  # Omit chunking on a managed-embedding KB — any chunking_configuration is rejected there.
  # A chunking_configuration is valid only with a custom embedding model.
  # No parsing_configuration on managed: Smart Parsing is applied automatically.
}
```

Auth connectors (SharePoint/Confluence/OneDrive) set their fields inside the same `jsonencode`
`connectionConfiguration` / `dataEntityConfiguration` objects (`secretArn`, `tenantId`, `authType`,
`siteUrls` as a list, `certificateS3Path`, …) exactly as in
[managed KB API](references/bedrock-kb-migration/managed-kb-api.md) §2b — the secret is referenced by
**ARN only**. `name` and `knowledge_base_configuration` **force a new resource** (create-only),
consistent with the CFN create-only note.

---

## 5. Cross-format notes

- **Same resources, two encodings.** The field *names* differ (CFN PascalCase; Terraform snake_case HCL),
  but the *values, enums, and managed rules are identical* and come from
  [managed KB API](references/bedrock-kb-migration/managed-kb-api.md) +
  [mapping](references/bedrock-kb-migration/mapping.md). Never hand-write a shape from memory in either
  format — verify with §0.
- **The connector body is the one part that is byte-identical in both formats**, because both
  `ConnectorParameters` and `connector_parameters` are free-form pass-throughs carrying the same camelCase
  API object. The surrounding convention never applies inside it.
- **MANAGED is create-only in both.** A `VECTOR` KB is never converted in place; the managed KB is a new
  resource (a new logical ID / resource address).
- **The managed store is never declared.** Omit CFN `StorageConfiguration` / Terraform
  `storage_configuration` on a managed KB.
- **Scale limits are quotas, not schema.** Data sources per KB and KBs per account per Region differ between
  self-managed and managed; read both live from Service Quotas ([mapping](references/bedrock-kb-migration/mapping.md)
  §4) before execution. Preserve topology by default; consolidation is an
  optional improvement.

## Common mistakes

- **PascalCasing the connector body.** The most common translation error on this path: it looks correct,
  every offline validator (`describe-type`, `cfn-lint`, `terraform validate`, `--generate-cli-skeleton`)
  accepts it, and only the live service rejects it at create time. Inside `ConnectorParameters` /
  `connector_parameters`, keys are camelCase API names.
- **Treating Terraform `connector_parameters` as a block/map.** It is typed `string`; `jsonencode({...})`
  is mandatory.
- **Putting `deletion_protection_configuration` / `media_extraction_configuration` inside the
  `jsonencode` blob.** They are sibling HCL blocks (Terraform) / PascalCase siblings (CFN); nesting them
  in the connector body is a silent no-op.
- **Declaring `StorageConfiguration` on a managed KB**; translating a SEMANTIC/HIERARCHICAL chunking
  strategy instead of omitting `chunkingConfiguration`; or emitting **any** `chunkingConfiguration` (even
  `FIXED_SIZE`/`NONE`) on a **managed-embedding** KB — it is rejected with "A chunking strategy cannot be
  specified with a managed embedding model"; omit the block unless the KB uses a custom
  embedding model.
- **Reporting an `unverified` shape as `verified`.** If §0 could not run, say which command was
  unavailable; the template is documented-shape only.
- **Expecting an in-place `VECTOR`→`MANAGED` update.** Create-only properties force resource replacement:
  a new KB ID and re-launched instances for consumer-instantiated templates.
