# Analytics

Pass-2 rubric for the analytics types `index.md` routes here. Loaded only when the
inventory contains one.

**Outcome is `confidence: inferred`.** Never `deterministic`.

Two types reach this file. Most of Azure's analytics surface does not, and that is
deliberate: Synapse, Data Factory, Stream Analytics and Machine Learning workspaces are
**specialist gates** in `fast-path-services.json`, because in each case the migration work
is a rewrite the resource does not describe. A Stream Analytics job's cost _is_ its query
rewrite; naming "Managed Flink" describes none of it (13.1g). Do not add rubric rows here
for gated types — a gate must never be overridden by anything below it (§ 7a.2).

## 1. Eliminators — hard technical blockers

| Candidate                   | Eliminated when                                                                                                                                                                                                                                                               |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **OpenSearch Serverless**   | the workload needs a **fixed cluster topology** the customer manages, or plugins beyond the serverless surface                                                                                                                                                                |
| **EMR**                     | the workspace uses **any Databricks-proprietary feature** — Unity Catalog, Delta Live Tables, Databricks SQL warehouses, Photon, MLflow model registry, Databricks Workflows, or notebooks as the primary interface. EMR is Spark; it is not Databricks with a different bill |
| **EMR Serverless**          | the workload needs **long-lived interactive clusters** with attached notebooks                                                                                                                                                                                                |
| **Bedrock Knowledge Bases** | the index serves **keyword or faceted search** for an application UI rather than retrieval for a model                                                                                                                                                                        |

## 2. The six criteria, in order, first match wins

### 2.1 Eliminators

Section 1. Whatever survives is the candidate set.

### 2.2 Operational model

| Source                                              | Target                        | Why                                                                                                                   |
| --------------------------------------------------- | ----------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `Microsoft.Search/searchServices`                   | **Amazon OpenSearch Service** | Azure AI Search is a managed inverted-index service with vector support. OpenSearch is the counterpart on both counts |
| `Microsoft.Databricks/workspaces`                   | **Databricks on AWS**         | The like-for-like is the same product on the other cloud. This is the default and it is usually right                 |
| `Microsoft.Databricks/workspaces`, plain Spark only | **EMR**                       | Only when § 2.4 confirms nothing Databricks-specific is in use. See § 3                                               |

### 2.3 User preference

`preferences.json` → `design_constraints` overrides 2.2. A customer consolidating onto
AWS-native services has chosen EMR and OpenSearch; a customer with a Databricks contract
has chosen Databricks on AWS. Either answer wins over the derived one.

### 2.4 Feature parity

**Azure AI Search → OpenSearch.** What carries and what does not:

| Azure AI Search                                                | OpenSearch                                                                                                                                                                                        |
| -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Index schema, analyzers, scoring profiles                      | index mappings, analyzers, function score — direct in concept, reauthored in syntax                                                                                                               |
| Vector fields and vector search                                | k-NN — direct                                                                                                                                                                                     |
| `replica_count` / `partition_count`                            | data node count / primary shard count — a **sizing input**, not a mapping. See § 4                                                                                                                |
| **Indexers** pulling from Blob, Cosmos or SQL                  | **no equivalent.** OpenSearch does not pull. This becomes an explicit ingestion pipeline — Lambda, OpenSearch Ingestion, or Glue — which is new infrastructure the source did not have            |
| **Skillsets** (OCR, entity recognition, key phrase extraction) | **no equivalent.** These call Cognitive Services during indexing. The counterpart is Textract / Comprehend invoked from the ingestion pipeline, which means the skillset becomes application code |
| **Semantic ranker**                                            | no direct counterpart. Options are a reranking model on Bedrock or SageMaker, or accepting BM25 plus vector hybrid scoring — a quality decision, not a config change                              |
| Knowledge store                                                | no equivalent                                                                                                                                                                                     |

The honest summary for the report: **the index maps; the pipeline that fills it does not.**
An estimate that prices only the OpenSearch domain has priced the smaller half of the work
for any search service that uses indexers or skillsets. Emit one `warnings[]` entry naming
each indexer or skillset found.

**When the search service exists only for RAG** — vector fields, no faceting, no
application-facing keyword search — say so, and name **OpenSearch Serverless with Bedrock
Knowledge Bases** as the alternative worth evaluating. Do not silently substitute it: it
changes the retrieval contract, so it is a recommendation for the report, not a mapping.

### 2.5 Cluster context

- A search service in a cluster whose compute is **Lambda** and whose data store is
  **DynamoDB** is a serverless estate; OpenSearch Serverless fits the operational posture
  even where a provisioned domain would be cheaper at steady state.
- A Databricks workspace in the same cluster as **Synapse or Data Factory** means the
  cluster is a `data-pipeline` pattern and defers **at cluster level** (§ 7a.8). The
  cluster-level gate wins: do not emit a per-resource Databricks mapping inside a deferred
  cluster.

### 2.6 Simplicity

Where both stand, prefer the target that keeps the customer's existing operational model.
Moving Databricks-on-Azure to Databricks-on-AWS changes one variable; moving it to EMR
changes the platform, the job definitions and the team's tooling at the same time as the
cloud.

## 3. Databricks: the like-for-like is the default, and EMR is an optimization

`Microsoft.Databricks/workspaces` is the only row in this skill where the recommended
target is **the same third-party product on AWS**. That is not a cop-out:

- Databricks on AWS is a first-party AWS Marketplace product with the same workspace,
  notebooks, job definitions and Unity Catalog. Migration is a workspace migration.
- EMR runs Spark. Every Databricks abstraction above Spark — Delta Live Tables, Workflows,
  SQL warehouses, Photon — has to be rebuilt on something else.

So the rule is: **default to Databricks on AWS. Route to EMR only when § 2.4 confirms the
workspace is plain Spark**, and state in the rationale which Databricks features were
checked for and not found. "EMR, because no Unity Catalog, Delta Live Tables or SQL
warehouse usage appears in the workspace configuration" is auditable. "EMR is the
AWS-native choice" is a preference dressed as a finding.

**`sku` is a signal, not a size.** `premium` buys Unity Catalog, role-based access and
audit logging — read it as evidence Databricks-specific features are likely in use, which
pushes toward Databricks on AWS. Do not translate the SKU into an instance type; the
workspace has no compute of its own, its clusters do, and those are not in the IaC.

## 4. Sizing is post-selection

As in every rubric, the six criteria pick a service and never touch capacity.

- **OpenSearch**: `replica_count` × `partition_count` from the source is the starting point
  for data node count and shard count, not the answer. Azure AI Search's replica/partition
  units are a pricing construct with fixed storage per partition; OpenSearch nodes are
  instances. Without utilization data, state a dev-tier default and say the sizing table is
  absent rather than inventing a node count.
- **Databricks / EMR**: the workspace declares no compute, so there is nothing to size from
  the inventory. Any cluster sizing is a Clarify or workshop input, and its absence is a
  stated assumption, not a gap to paper over.

`knowledge/design/*.json` carries **no analytics sizing table**, and unlike compute and
database that is still true after 2026-09-07. So every OpenSearch node count and every
Databricks or EMR cluster size from this rubric is stamped
**`sizing_provenance: "model_prior"`** with a `warnings[]` entry, not `table`.

Per § 14 a missing sizing table degrades a number's precision and does not halt, unlike a
missing rubric file which fabricates the answer. That distinction holds — but "degrades
precision" understates it when there is no table at all, which is exactly why the
provenance field is required rather than optional.

## 5. Output

Per `schema-design-aws.md` § `services[]`: `aws_service`, `aws_config` (engine version,
node type and count or serverless collection type, vector configuration),
`confidence: "inferred"`, `rubric_applied: "analytics.md"`, and a `rationale` naming
**which criterion fired**.

Every indexer, skillset and Databricks-proprietary feature found gets its own
`warnings[]` entry. They are the part of the migration the mapping does not represent.

## Status — build step 5b

Implemented for AI Search and Databricks — the two analytics types that route here.
Synapse, Data Factory, Stream Analytics and Machine Learning workspaces are specialist
gates by design and are not covered here. HDInsight and Data Explorer (Kusto) have no
canonicalization row yet, so they reach the untranslated-type STOP rather than this file.
