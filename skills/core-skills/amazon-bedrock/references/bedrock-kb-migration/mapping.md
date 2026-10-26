# Self-managed ↔ Managed Capability Map

> **Validation source:** live testing against the service (the service is ground truth). This file is the
> structured capability map; request shapes live in [managed-kb-api](references/bedrock-kb-migration/managed-kb-api.md).
>
> **Authoritative source.** This file captures a validated capability map, not a complete specification.
> The authoritative source for current create-time behavior, accepted enums, chunking/parsing, and
> embedding-model rules is the Amazon Bedrock User Guide — chiefly
> [Create a managed knowledge base](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-create.html),
> [Customize ingestion for a data source](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-customize-ingestion.html)
> (parsing and chunking strategies for managed KBs), and
> [How content chunking works for knowledge bases](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-chunking-parsing.html).
> **Check those pages before quoting specific enums, token/overlap figures, or model rules** — accepted
> values change, and the service, not this file, is the final authority.

## Contents

- Key validated findings
- Managed-only capabilities — what MANAGED adds
- 1:1 mapping
- Adjusted mapping (`adjusted` tier)
- Handled differently on managed (no direct knob) — incl. the closed blocker list
- Gap coverage — how managed handles each difference, and what covers it
- Background — self-managed KB building blocks
- Public reference links

## Key validated findings

- **Chunking on MANAGED depends on the embedding-model type — this is the governing rule.**
  - **Managed embedding model (the default): emit NO `chunkingConfiguration` at all.** Specifying *any*
    chunking strategy — including `FIXED_SIZE` or `NONE` — is rejected at create time with
    `ValidationException: "A chunking strategy cannot be specified with a managed embedding model"`
    (observed on a live create). Omit the block; the managed default (fixed-size, honoring sentence
    boundaries; size and overlap on the Customize ingestion page) applies. **This restriction is
    not stated in the AWS user guide** (the [Customize ingestion](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-customize-ingestion.html)
    page lists `DEFAULT`/`FIXED_SIZE`/`NONE` as accepted and does not mention the managed-embedder
    exception) — so do **not** "correct" this rule from the docs page; the live create is the authority.
  - **Custom embedding model on a MANAGED KB: `FIXED_SIZE` or `NONE` may be carried over** (values are
    retained); `DEFAULT`, `HIERARCHICAL` and `SEMANTIC` are still rejected server-side, so for a
    `SEMANTIC`/`HIERARCHICAL` source omit `chunkingConfiguration` and let the default apply.
- **`CUSTOM` data sources ARE supported on MANAGED — via the connector, not the top-level type.** The
  self-managed `dataSourceConfiguration.type: CUSTOM` is rejected (`"Unsupported data source type for
  MANAGED knowledge base type."`), but `type: MANAGED_KNOWLEDGE_BASE_CONNECTOR` with
  `connectorParameters.type: CUSTOM` is accepted (the data source goes straight to `AVAILABLE`) and gives
  direct document ingestion via `IngestKnowledgeBaseDocuments` — no S3 staging. See
  `managed-kb-api.md` §2d.
- **`Retrieve` is `HYBRID`-only** on MANAGED (`overrideSearchType` does not exist on the managed wrapper);
  self-managed accepts both. **Scores are on different, non-portable scales**, and on MANAGED the scale also
  depends on the reranking mode — re-tune any threshold after migration (full caller list:
  `managed-kb-api.md` §3 "What changes for existing `Retrieve` callers"). **`Retrieve` is not the only query surface:** MANAGED also
  exposes `AgenticRetrieveStream`, a planning-loop retrieval API that does not exist on `VECTOR` at all —
  see "Managed-only capabilities" below and `managed-kb-api.md` §3.
- **`numberOfMetadataDocumentsScanned` is not a health signal.** Do not expect a particular value; metadata
  filtering works either way.
- **Auth-based connectors (Confluence/SharePoint/OneDrive/GoogleDrive)** need a Secrets Manager secret;
  SharePoint `siteUrls` must be a JSON array. See `managed-kb-api.md` §2b.
- **Embedding output has one fixed dimension and data type on MANAGED** (the create page states them;
  validated live — other values are rejected, not silently defaulted): a smaller `dimensions` value →
  `"MANAGED knowledge base type supports only 1024 embedding dimensions"`; `embeddingDataType: BINARY` →
  `"... supports only FLOAT32 embedding data type"`. A source KB on a reduced dimension or BINARY must be
  re-embedded at the managed dimension and data type.
- **Embedding on MANAGED: default service-managed, or a `CUSTOM` bring-your-own model (text OR
  multimodal).** **Don't hardcode the supported set — it changes; fetch it at create time** from
  `kb-managed-create.md#kb-managed-embedding-models` (+ `knowledge-base-supported.md` /
  `kb-managed-regions.md` for Region) via `curl` + `.md`. Always-true constraints: a `CUSTOM` **text**
  model must use the dimension and data type the create page requires (the errors above name them), and
  `CUSTOM` **disables the managed reranker** (the default keeps it). A `CUSTOM` **multimodal** model is
  different: it takes no `dimensions`, takes a `modelConfiguration` block (`version` `"1"`) and a required
  `supplementalDataStorageConfiguration` S3 location (a different bucket from the data source), ingests only
  with the `MULTI_MODAL_EMBEDDINGS` parsing strategy (no text chunking), and is queried only with
  `Retrieve` and text queries ([kb-managed-native-multimodal](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-native-multimodal.html)).
  Read the supported multimodal models from the create page. This is documented, not migration-tested:
  say so, and check the CloudFormation / Terraform schema for the multimodal fields before emitting IaC.
  An unlisted model → `"The specified embedding model ... is not supported"`.
- **Environment caveat:** ingestion can be healthy in one region/environment and broken in another —
  validate in the actual target environment.

**Retrieval accuracy:** roughly on par with self-managed on rank-1 retrieval; forced `SMART_PARSING` makes
MANAGED beat self-managed's default parser on image-bearing PDFs; parity on pure text; tables weakest on
both. A **text** embedding model does not cover image/audio/video-only answers, whereas a **multimodal
`CUSTOM`** model (if the docs list one) embeds that content directly. State this as a capability difference
if the user asks — **do not assess, classify, or advise on what the user's corpus contains**; corpus content
type is out of scope for this tool.

> **These are single-shot `Retrieve` comparisons.** Agentic retrieval is a *different surface* with its own
> documented gains on a different benchmark (below). **Never blend the two sets of numbers** — "on par with
> self-managed" and the agentic benchmark gains describe different APIs answering different question
> shapes, and quoting them together implies a comparison neither measurement made.

## Managed-only capabilities — what MANAGED adds

> **Three source tiers, kept distinct.** "Key validated findings" above is **live-tested** (the service is
> ground truth). This section mixes two lower tiers, and the difference matters when you quote it:
>
> 1. **Contract-verified** — the retrieval request members that differ between self-managed and
>    managed, checked against the botocore `bedrock-agent-runtime` model with
>    client-side parameter validation plus a live `us-west-2` call, and the applied managed chunking/parsing
>    config read back from live managed KBs. The caller-impact consequences are in
>    `managed-kb-api.md` §3. **Neither this file nor `managed-kb-api.md` carries runtime request
>    shapes** — for those the user goes to the AWS API reference or `--generate-cli-skeleton`, never to an
>    example.
> 2. **Documented only** — the capability narrative and every benchmark or limit figure (MuSiQue gains,
>    parsing size ceilings, the number of KBs one agentic call can route across, per-call prices, real-time ACL checks,
>    incremental sync). Read, not measured. Quote these as documented and re-verify anything load-bearing.
>
> Never present a documented figure as something this tool measured. If a doc you fetch disagrees with a
> finding recorded here about a **shape or an error you can reproduce**, prefer the recorded finding and say
> the documentation differs. A page that documents a connector or capability this file does not list wins:
> absence here is not evidence. Re-check either way, because
> **a verified contract is still a snapshot**: the model ships per botocore
> release, server-side validation is stricter than client-side, and quotas move independently of shapes, so
> **check the docs whenever a call errors** rather than assuming these files are current.

A `VECTOR` KB is a set of parts the customer assembles and operates: a store, an embedding model, a parser,
a chunker, retrieval logic. `MANAGED` collapses them into one primitive. Five sections below say why the
result is not merely simpler but frequently *more accurate*: three capabilities (§1–§3), the scale and quota
differences (§4), and the capabilities that have no self-managed equivalent at all (§5). Each pairs with a
configuration difference in "Gap coverage" below, which is where the two are matched up explicitly.

### 1. Smart Parsing — the ingestion model

Managed forces `SMART_PARSING` (there is no `parsingConfiguration` — `managed-kb-api.md` §2). It is not one parser
but a per-content-type strategy selected automatically, built from three documented pieces:

- **Connector-specific data models.** Each connector preserves the structure its source actually has: the
  `WEB` connector keeps HTML structure *including embedded images and tables*; SharePoint keeps document
  hierarchy and the relationships between files. This is why the connector choice affects retrieval quality,
  not just where documents come from.
- **Multimodal processing.** It identifies bounding boxes within documents and sends those regions to
  foundation models for data extraction, captioning, and — in video — scene description. Tables, charts,
  diagrams and mixed layouts are handled with no configuration.
- **FM-driven, structure-aware chunking.** Documented as using foundation models to understand document
  structure so complex mixed-format documents index correctly, with defaults balancing retrieval accuracy
  against performance per document type and content structure.

**Documented ingestion ceilings:** the per-file size limits for visual documents, audio and video are on the
managed KB docs and the enterprise-search blog (links at the end); fetch them before quoting a figure, and if
the page you fetch does not state one, say so.

**Default chunking.** The *applied* managed default is **fixed-size** chunking (its size and overlap are on
the Customize ingestion page, and matched measured chunks), with only `[FIXED_SIZE, NONE]` accepted as an explicit strategy — **and only on a
custom-embedding KB; a managed-embedding KB rejects every strategy, so you omit the config there** (see Key
findings). Structure awareness lives in
**parsing**, upstream of the chunker — which is why the default can be fixed-size without the ingestion being
structure-blind. Two details govern how to describe it:

- On a managed data source created **without** `chunkingConfiguration`, `vectorIngestionConfiguration` reads
  back as **`null`** — the service stores and echoes **nothing**. So the managed default is not a readable
  setting: quote its size from the docs page, **not as a config value you can verify with
  `get-data-source`.** Say it that way.
- On a managed data source created **with** an explicit `FIXED_SIZE` config, the values **are** retained: a
  live source built with an explicit `maxTokens` and `overlapPercentage` reads those values back unchanged. Explicit
  `FIXED_SIZE` is genuinely supported, not silently discarded — **but only on a KB using a custom embedding
  model.** On a managed-embedding KB, an explicit `FIXED_SIZE` (or any strategy) is rejected outright
  (see Key findings); you cannot set or read a chunking config there at all.
- The rejection of `DEFAULT`/`HIERARCHICAL`/`SEMANTIC` is **server-side only**. The API model's enum is the
  full `[FIXED_SIZE, NONE, HIERARCHICAL, SEMANTIC]` (shared with self-managed), so `SEMANTIC` passes
  client-side validation and fails only on the live create. Independently, on a **managed-embedding** KB the
  server rejects *every* strategy including `FIXED_SIZE`/`NONE` — also invisible client-side. Both are why
  live testing, not the schema, is the authority here (`managed-kb-api.md` §6).

**Do not tell a user their `SEMANTIC` chunking is replaced by something semantically equivalent.** State the
substitution (managed default chunking, not customer-readable) and, if it matters to them, that the structure
awareness lives in *parsing* rather than in the chunker.

**Two cases beyond the plain fixed-size default, both embedding-model-driven.** (1) **Managed embedding
model:** no chunking config is accepted at all — omit it (see Key findings). (2) **Native multimodal
embedding model** (parsing strategy `MULTI_MODAL_EMBEDDINGS`): files are sent straight to the embedding
model instead of being parsed into text, so the text chunking strategy is ignored for that content — you
control audio/video segmentation instead. Only a **custom text** embedding model actually carries a
`FIXED_SIZE`/`NONE` chunking config. Confirm against
[Customize ingestion for a data source](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-customize-ingestion.html)
before quoting specifics — note that page does not document the managed-embedder rejection (case 1).

### 2. Agentic Retrieval — a second retrieval surface, and MANAGED-only

`Retrieve` (`managed-kb-api.md` §3) is not the only query surface. **`AgenticRetrieveStream`** runs an FM-driven
planning loop instead of a single similarity search: it decomposes the query into sub-queries, retrieves per
sub-query, judges whether the evidence is sufficient, and iterates — then generates a grounded answer in the
same call by default. How it behaves, when to choose it, and its cost and permission shape:
**`managed-kb-api.md` §3** (a conceptual overview — running it is the user's step, so no request shapes there).

**This is the largest capability MANAGED adds, and it does not exist on a `VECTOR` KB at all** —
`AgenticRetrieveStream` is documented as Managed-KB-only. A team that hand-built a plan → retrieve →
evaluate loop on top of `Retrieve` is maintaining in every application what this API does natively, with its
own latency, cost and reliability risk.

Why this is an accuracy argument and not a convenience one: a multi-intent question ("compare how we talked
about hiring and long-term investment in 2020 vs 2023") has **no single point in embedding space that
represents it well**, so single-shot top-k returns an average of competing sub-intents. Decomposition is
what fixes that, and the documented benchmark gain grows with difficulty — the agentic-retrieval blog (link
at the end) reports recall gains on the public **MuSiQue** multi-hop benchmark that rise with the number of
hops, and small gains on single-hop questions. Quote the figures from the blog you fetch, attributed to
agentic retrieval. It is not a blanket upgrade — it is the right surface for multi-part, comparative,
exploratory and cross-KB questions, and the wrong one for direct lookups.

It also **routes across several knowledge bases in one request**, picking per sub-query from a
natural-language `description` attached to each retriever. That is the capability to reach for whenever a
migration splits one KB into several (the data-sources-per-KB split) — see "Gap coverage". How many KBs one
call may route across is a **server-side quota, not a contract bound** (verified: the `retrievers` list has
`min=1` and no maximum in the API model), so read it from the quotas page and don't expect client
validation to catch one too many.

### 3. Service-managed storage — the accuracy argument, not only the ops one

Dropping `storageConfiguration` is usually framed as losing control. What is gained is documented and
concrete:

- **Auto-provisioned** — no vector-dimension or similarity-metric decision to get wrong.
- **Auto-scales from gigabytes to terabytes** with no intervention.
- **Hybrid search continuously on**, keyword plus semantic, with no separate index configuration to manage.
  This is the flip side of the `HYBRID`-only finding: **the constraint and the feature are the same fact.**
- **Encrypted at rest and in transit** with AWS KMS keys, AWS-managed or customer-managed.
- **The multimodal parser, the managed embedding model and the managed re-ranker are included at no extra
  cost** on the default path — which is exactly why a cost comparison has to count those line items on the
  self-managed side (`cost-analysis.md`).

Two production behaviors round it out, neither of which is simply "the self-managed thing but managed":

- **ACL-aware retrieval** — document-level access control in two stages: **pre-retrieval filtering** (the
  connector crawls allowed/denied users and groups during ingestion, and query results are filtered against
  the user context you supply) plus **real-time ACL verification** (a live call to the source confirming the
  user still has access, catching permission changes since the last sync). Deny always overrides allow, and
  the pipeline **fails closed** — a group-resolution failure, verification timeout or internal error
  withholds the affected documents rather than returning them. Pre-filtered documents are transient for the
  life of the API call and never exposed to the model or the user. Verified details in
  `managed-kb-api.md` §3b.

  > **State the boundary every time: ACL awareness is not authorization.** The AWS documentation is explicit
  > — this is ACL-aware *filtering*, not a security boundary. Managed KB **does not authenticate end users**;
  > the application must authenticate them and pass verified identity context, and because the service cannot
  > check the authenticity of that context, **it must not be relied on as a sole access-control mechanism
  > without upstream authentication.** Presenting this as "managed handles your authorization" would be a
  > security misrepresentation, not just an overstatement.
- **Incremental sync** — subsequent syncs process only new or modified documents, which is what keeps
  re-sync time and cost proportional to change rather than to corpus size.

### 4. Scale and quota differences — the biggest gap, and the easiest to verify

**Read every limit live; never quote one from this file or from memory.** AWS's own pages disagree on
several of these (values and whether they can be raised), so the customer's account is the only source.
Whenever limits come up (Explore or Plan), run, for each quota code below (READ-ONLY, pre-approved):

```bash
aws service-quotas get-service-quota --service-code bedrock --quota-code <QUOTA_CODE> \
  --region <REGION> --profile <READ_ONLY_PROFILE>
```

Quote `Quota.Value` and `Quota.Adjustable` exactly as returned. If a call fails (denied, throttled, no
such code), say "check Service Quotas in your account" for that quota and give **no number** for it.
**Note the official terminology:** AWS calls the self-managed type a **Customer-managed Knowledge Base**;
this file says "self-managed" / `VECTOR` for the same thing.

| Quota | Self-managed (`VECTOR`) code | MANAGED code |
|---|---|---|
| Knowledge bases per account, per Region | `L-60DA3E0D` | `L-5C7643AC` |
| Data sources per knowledge base | `L-679D8304` | `L-F02D918A` |
| Concurrent ingestion jobs per knowledge base | `L-31BC8F89` | `L-D74F6A4C` |
| Query input size (characters) | `L-0495104E` | `L-08DDCA8C` (`Retrieve`) |
| `Retrieve` throughput | `L-F0D0E0B9` (requests per second, shared across the account) | `L-3FE71326` (requests per second per account) and `L-4064C85B` (requests per minute per KB) |
| Raw data storage per knowledge base (TB) | n/a — bounded by the store you run | `L-BEE3FA31` |
| `AgenticRetrieveStream` requests per minute per account | n/a | `L-315A9D5B` |

**How to frame throughput.** Self-managed `Retrieve` is one ceiling shared by every KB in the account;
managed has an account ceiling **plus** a separate per-KB allowance. State both managed numbers as
returned. Do not describe managed as slower.

Two of these change migration *design*, not just talking points (confirm the numbers live first):

- **The data-source jump reverses the usual direction of a split.** A self-managed estate is often
  fragmented *because* of its per-KB data-source limit. On managed, many more fit in one KB — so a
  migration frequently **consolidates** rather than splits.
- **The KB-count jump removes per-account KB scarcity** as a design constraint, which is what makes
  "a KB per team / per tenant" viable at all.

Report the managed storage ceiling per KB (`L-BEE3FA31`) alongside these, as returned.

### 5. Capabilities that simply do not exist on self-managed

From the AWS comparison table — these are **"Supported" vs "Not supported"** rows, not degrees:

| Capability | Self-managed | MANAGED |
|---|---|---|
| **Agentic retrieval** | **Not supported** | Supported (§2 above) |
| **AgentCore Gateway integration** | **Not supported** | Supported (native target type) |
| **Resource-based policies** (cross-account access to a KB) | **Not supported** — the docs state `VECTOR` KBs do not support resource policies | Supported: attach a JSON policy with `Allow`/`Deny` over `bedrock:Retrieve` and `bedrock:GetDocumentContent` ([kb-managed-cross-account](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-cross-account.html)) |
| **Managed embedding model** | None | Built-in, optimized for accuracy/performance, **no extra cost** |
| **Managed re-ranker** | None | Built-in semantic reranker, **no extra cost** |
| **Native connectors** | **S3 and Custom** (per the AWS comparison table) | A broad native connector suite — S3, SharePoint, Confluence (Cloud and Data Center), Web Crawler, Google Drive, OneDrive, Box, Salesforce, Zendesk, Custom (do not quote a fixed count — the set is expanding; confirm it from the connector docs) |
| **Amazon Quick integration** | Build your own | Natively associable as a Quick knowledge base |

> **The connector row needs care — do not overstate it.** AWS's comparison table lists Customer-managed as
> "S3 and Custom", and that is the line to quote. But the **shared API model still exposes `WEB`,
> `CONFLUENCE`, `SHAREPOINT` and `SALESFORCE` as `VECTOR` data-source types**, and real customer estates use
> them — this tool's own migration mapping exists precisely to translate them. So **never tell a user their
> existing self-managed Confluence, SharePoint or Salesforce connector "doesn't exist."** The defensible
> claims are: managed's native connector suite is the documented differentiator, and it is **broader than
> self-managed's** — managed **adds Google Drive, OneDrive, Box, Zendesk and Confluence Data Center**, and
> **Salesforce, Zendesk and Confluence (Cloud and Data Center) are native managed connectors** (see
> §"The managed connector set" below). There is no connector that self-managed has and managed
> lacks that still blocks a migration. Confirm the live set from the connector docs rather than reciting a
> list or a count.
>
> **Managed gain (R1), state it where connectors come up:** **new** Confluence, SharePoint, Salesforce
> and Web Crawler connectors cannot be created on customer-managed (`VECTOR`) KBs — existing ones keep
> working, but for these sources *new work goes on managed* and AWS
> recommends managed by name (https://docs.aws.amazon.com/bedrock/latest/userguide/salesforce-data-source-connector.html).

AWS states its own preference plainly on that page — managed is recommended for the combination of
ease-of-use, accuracy and cost. That is a citable position, not this tool's opinion.

### How to state the parsing and search claims

- **The parsing claim is qualitative.** What is supportable: multimodal handling, per-connector data models,
  and this tool's live finding that managed beats the self-managed **default** parser on image-bearing PDFs.
  Attach **no accuracy percentage** to parsing — the documented retrieval-accuracy figures belong to agentic
  retrieval (§2), and the correct terms for the parser are "Managed parser" / `SMART_PARSING`.
- **Hybrid *search* is a separate, verified claim** — always on, per §3. Keep it distinct from parsing; the
  shared word is not a bridge between the two.

## 1:1 mapping

| Configuration | self-managed (VECTOR) | MANAGED | Notes |
|---|---|---|---|
| Bedrock FM embedding | `vectorKnowledgeBaseConfiguration.embeddingModelArn` | `managedKnowledgeBaseConfiguration.embeddingModelArn` (with `embeddingModelType: CUSTOM`) | Same ARN works only if in the current `CUSTOM` supported set (fetch from docs, don't hardcode). Must use the managed dimension and data type (create page); `CUSTOM` disables the managed reranker |
| Inference profile embedding | `embeddingModelArn` = IP ARN | `embeddingModelArn` = IP ARN | Supported in both, but on MANAGED the profile's model must use the managed dimension and data type (create page) |
| KB-level CMK encryption | KB-level `serverSideEncryptionConfiguration` | `managedKnowledgeBaseConfiguration.serverSideEncryptionConfiguration.kmsKeyArn` | Required grant is provisioned automatically |
| KB identity (name / description / roleArn) | Same request fields | Same request fields | Identical |
| Retrieval metadata filtering | `vectorSearchConfiguration.filter` | `managedSearchConfiguration.filter` | Same syntax for most operators inside the new wrapper; `startsWith` and `stringContains` are rejected on managed (`managed-kb-api.md` §3) |
| Fixed-size chunking | `FIXED_SIZE` | `FIXED_SIZE` **only with a custom embedding model** (with the managed embedding model, chunking config is rejected — omit it) | Carry `FIXED_SIZE` over only on a custom-embedding KB. On a managed-embedding KB emit no `chunkingConfiguration`; the managed default applies |
| No chunking | `NONE` | `NONE` **only with a custom embedding model** | On a custom-embedding KB `NONE` is accepted verbatim (**recommended: switch to `FIXED_SIZE`** — `NONE` produces one oversized chunk per document, degrading retrieval and possibly exceeding the embedding model's token limit; pre-split upstream if one-chunk-per-file is genuinely required). On a managed-embedding KB even `NONE` is rejected — omit `chunkingConfiguration` |
| Data source connectors | S3, Web, Confluence, SharePoint, Salesforce, Custom | Same sources plus more, via `connectorParameters.type` (`S3`/`ONEDRIVE`/`CONFLUENCE`/`CONFLUENCEONPREM`/`SHAREPOINT`/`WEB`/`GOOGLEDRIVE`/`SALESFORCE`/`ZENDESK`/`CUSTOM`, `version` `"1"`; see "The managed connector set") | The managed connector *shape* differs: `connectionConfiguration.secretArn` (not `credentialsSecretArn`), `aclEnabled` (no `crawlAcl`), managed `authType` values — see `managed-kb-api.md` §2b. Managed names are `WEB`/`GOOGLEDRIVE` (not `WEB_CRAWLER`/`GOOGLE_DRIVE`). Managed also adds `SALESFORCE`, `ZENDESK` and `CONFLUENCEONPREM` (Confluence Data Center) connectors that self-managed does not have. `CUSTOM` is a direct-ingestion source, no crawl or secret (§2d) |
| S3 prefix / pattern filters | `s3Configuration.inclusionPrefixes` | `connectorParameters.filterConfiguration` — `inclusionPrefixes`, `exclusionPrefixes`, `inclusionPatterns`, `exclusionPatterns`, `maxFileSizeInMegaBytes` | Carry the prefixes/patterns over unchanged. A self-managed S3 data source accepts exactly **one** inclusion prefix ([S3DataSourceConfiguration](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_S3DataSourceConfiguration.html): `inclusionPrefixes`, fixed number of 1 item), so a source that lists several was never deployed as written or has drifted. Flag it and ask which prefix the deployed data source uses (`get-data-source` shows it when the KB is reachable); never pick one silently. The same applies when the prefixes the customer names differ from the ones the source declares: point out the difference and ask which is live before writing the file — never carry the customer's list, the source's, or both without asking |

## Adjusted mapping (`adjusted` tier) — managed reaches the same outcome a different way

These settings aren't passed through verbatim, but each has a supported, validated path on the managed KB
that reaches the same — often better — result. The decision-trace tier keyword is `adjusted`.

| Configuration | self-managed (VECTOR) | Best MANAGED option | Managed approach (what changes) |
|---|---|---|---|
| Vector store choice | OpenSearch (Serverless/managed), Aurora pgvector, Pinecone, MongoDB, Redis, S3 Vectors, Neptune | Accept the auto-provisioned managed store (no `storageConfiguration`) | Managed provisions and operates the store for you — auto-provisioned dimensions/metric, auto-scaling GB→TB, hybrid search always on, KMS-encrypted (see "Managed-only capabilities" §3). What changes is hands-on **store choice, index tuning, and direct index access** (document ACLs are handled via connector `aclEnabled`) |
| Multimodal (image/audio/video) embeddings | `bedrockEmbeddingModelConfiguration` (multimodal source) | A multimodal `CUSTOM` model if the docs list one (Key findings: its own configuration rules), or a text model + `SMART_PARSING` for figure/layout text | **Supported**, not a giving-up substitution: multimodal `CUSTOM` embeds non-text content directly. Caveats: `CUSTOM` disables the managed reranker, and not every model qualifies — confirm the set in the docs |
| Configurable dimensions / data type | Set on supported models (a reduced dimension, or BINARY) | Re-embed at the managed dimension and data type (create page; the only accepted values) | Managed **rejects** any other value (see Key findings). There is no dimension/data-type knob, so a reduced-dimension or BINARY source must be re-embedded |
| Parsing strategy | Default, `BEDROCK_FOUNDATION_MODEL`, `BEDROCK_DATA_AUTOMATION` | `SMART_PARSING` (standard on managed) | Managed standardizes on `SMART_PARSING` — empirically a net gain on visually-rich PDFs (tables stay weak on both); a custom parser model / BDA pipeline isn't separately selectable. It is a per-content-type strategy, not one parser: connector-specific data models, bounding-box → FM extraction/captioning/video scene description, documented per-file size ceilings (see "Managed-only capabilities" §1) |
| Semantic / hierarchical chunking | `SEMANTIC` / `HIERARCHICAL` | Managed default chunking (omit `chunkingConfiguration`) | The explicit strategies are rejected on managed regardless of embedding model, so omit the config and let the managed default apply (fixed-size, honoring sentence boundaries). On a **managed-embedding** KB no chunking config is accepted at all; on a **custom-embedding** KB `FIXED_SIZE`/`NONE` would be accepted but `SEMANTIC`/`HIERARCHICAL` are not. Structure awareness moves **upstream into parsing** — say the substitution, don't claim semantic equivalence ("Managed-only capabilities" §1) |
| Supplemental data storage (extracted media) | KB-level `supplementalDataStorageConfiguration` (an S3 location the KB writes extracted images to) | Connector `managedKnowledgeBaseConnectorConfiguration.mediaExtractionConfiguration` — `imageExtractionConfiguration` / `audioExtractionConfiguration` / `videoExtractionConfiguration`, each `{ *ExtractionStatus: ENABLED }` | **Supported, relocated.** Extraction moves from a KB-level bucket you own to a per-data-source connector switch; managed stores the extracted media itself, so the supplemental bucket, its parameter and its IAM grants all disappear. What changes: no customer-visible copy of the extracted media in your own bucket. Verified in the live CFN + Terraform schema and `kb-managed-connect-ds.md` |
| Cross-account **retrieval** by a consumer account | Consumer assumes a role with `bedrock:Retrieve`/`RetrieveAndGenerate` on the KB ARN | Identical — same actions on the new managed KB ARN | **Unchanged pattern.** Only the KB ID/ARN in the consumer's policy changes; migrating does not break cross-account retrieval |
| Cross-account **direct index** access by a consumer account | Consumer granted `aoss:APIAccessAll` (or equivalent) on the collection / direct SQL on the store | No equivalent — there is no customer-visible index or endpoint to grant | The consumer must move to the retrieval API (row above). A **consumer-side** change that does **not** block migrating the KB — migrate it, and report the specific consumer that loses direct index access so its owner can be repointed |
| Data deletion policy RETAIN | `DELETE` / `RETAIN` | `DELETE` (default); optional connector `deletionProtectionConfiguration` | Managed defaults to `DELETE` with optional `deletionProtectionConfiguration` on the connector; an explicit `RETAIN` policy isn't a managed control |
| Data-source-level SSE | DS-level `serverSideEncryptionConfiguration` | KB-level CMK only | Encrypt at the KB level with a CMK; per-data-source SSE granularity isn't configured separately |

## Handled differently on managed (no direct knob)

A few self-managed-only features have no one-to-one managed setting (decision-trace tier keyword:
`no-mapping`). For some there is a supported managed approach; for others there is **no managed path**, and
the customer must be directed to AWS Support — do **not** propose a workaround.

### The blocker list is CLOSED — exactly two features block a migration

**Only these two make a knowledge base ineligible.** Nothing else on this page, and nothing absent from
this page, is a blocker:

1. **Custom transformation (Lambda)** — no managed equivalent for an in-pipeline
   `customTransformationConfiguration` hook. Removing it would silently change what gets indexed. Contact
   AWS Support.
2. **Context enrichment / GraphRAG (Neptune Analytics)** — no managed graph store, and standard managed
   vector retrieval is a *different capability*, not a substitute for relationship-aware retrieval. Contact
   AWS Support.

**No workaround for a blocker.** Do not offer a way around it: not removing or disabling the Lambda, not
moving the transform upstream or into a pre-processing step, not a migrated file "if you drop it", and not
an offer to build on any of these. Each one changes what gets indexed, which is a decision for the customer
and AWS Support, not a migration step. Say "this KB can't move yet — contact AWS Support", and what managed
would give them once it is resolved.

Before keeping either, check the managed KB docs for an equivalent; keep it only if the docs show none
(both were re-checked against `kb-managed-connect-ds.md` and the managed KB user guide, which document no
in-pipeline transform hook and no equivalent managed graph store). **Salesforce migrates** — managed has
native Salesforce and Zendesk connectors and a native Confluence Data
Center connector, so Salesforce, Zendesk and Confluence (Cloud and Data Center)
sources all migrate. See "The managed connector set" below.

Plus, by extension: **any connector genuinely absent from the managed set.** Check the live docs before
concluding a connector is missing (plan → "Before recording a connector as blocked") — `WEB`,
`GOOGLEDRIVE`, `SALESFORCE`, `ZENDESK`, `CONFLUENCEONPREM`, `BOX` and `SERVICENOW` are all present under
those names.

### The managed connector set

The managed connector type is given by `managedKnowledgeBaseConnectorConfiguration.connectorParameters.type`
(with `version: "1"`); the wrapping `dataSourceConfiguration.type` is `MANAGED_KNOWLEDGE_BASE_CONNECTOR`.
Documented connectors and their type values (each confirmed from its own connector page — fetch the page
for the full `connectionConfiguration` shape, never invent fields):

| Source | `connectorParameters.type` | Notes (from the connector's own doc) |
|---|---|---|
| Amazon S3 | `S3` | Credential-free; `connectionConfiguration.bucketName` |
| SharePoint | `SHAREPOINT` | Secrets Manager credentials |
| Confluence (Cloud) | `CONFLUENCE` | Secrets Manager credentials |
| Confluence Data Center | `CONFLUENCEONPREM` | Secrets Manager creds (`BASIC` or `PERSONAL_TOKEN`); requires a VPC configuration; `aclEnabled` defaults to `false`, permanent after create. [kb-managed-ds-confluence-onprem.html](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-ds-confluence-onprem.html) |
| Web Crawler | `WEB` | |
| Google Drive | `GOOGLEDRIVE` | |
| OneDrive | `ONEDRIVE` | |
| Salesforce | `SALESFORCE` | `connectorType` also `SALESFORCE`; `authType: OAUTH2`; `connectionConfiguration.secretArn` + `hostUrl`; **no document-level ACL** (all authenticated KB queriers see all crawled content; the self-managed Salesforce connector has none either, see the Salesforce row under Gap coverage). [kb-managed-ds-salesforce.html](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-ds-salesforce.html) |
| Zendesk | `ZENDESK` | Crawls Zendesk articles and community posts. Confirm the exact `connectionConfiguration` fields from its connector page before writing them |
| Box | `BOX` | Secrets Manager credentials; `authType` `CCG` (Client Credentials Grant, recommended, supports ACLs) or `OAUTH2` (no ACLs). [kb-managed-ds-box](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-ds-box.html) |
| ServiceNow | `SERVICENOW` | `connectorType` also `SERVICENOW`; `authType: OAUTH2` (client credentials, 2LO); ACLs enforce ServiceNow user criteria. [kb-managed-ds-servicenow](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-ds-servicenow.html) |
| Custom | `CUSTOM` | Direct ingestion, no crawl or secret |

**Do not write a connector count** — the connect-ds overview's "Supported type values" sentence has not been
updated for the newest connectors, and the set is expanding; rely on each connector's own page and confirm
the live set from the docs. If a connector exists but its exact config shape is not documented on a page you
can fetch, state that the connector exists and mark the shape **not documented** rather than inventing it.

### An `adjusted` row is NEVER a blocker

Everything in the **Adjusted mapping** table is a **supported migration**, not an exclusion. If a setting
has an `adjusted` row the knowledge base is `READY`: apply the substitution, record the `adjusted` decision
with what changes, and emit the resource. Reduced dimensions / `BINARY`, `SEMANTIC`/`HIERARCHICAL` chunking,
a third-party vector store, a foundation-model parser, supplemental data storage, `RETAIN`,
data-source-level SSE and cross-account direct index access are all `adjusted` — refusing to migrate any of
them is a **false exclusion**, and it is the more damaging error, because the customer is told to open a
support case for something that migrates today.

**A feature that appears nowhere on this page is not a blocker either.** Absence here means "unmapped", not
"impossible". Before excluding anything not in the closed list: check the live resource schema and the
managed API/connector docs (`iac-schema.md` §0, `managed-kb-api.md`), and say what you
checked. If it has a managed home, the KB is `READY` and this file should gain a row. Only if the checks
confirm there is no managed path does it become an exclusion — reported as a **newly discovered** blocker,
named explicitly, not folded silently into the closed list above.

## Gap coverage — how managed handles each difference, and what covers it

Every `adjusted` row above is something managed **handles differently**. Most are covered by something
managed *adds*; a few genuinely are not, and saying which is which plainly is what makes the rest credible.
This is how to present any difference — use it whenever a difference comes up (including
when the user asks "what do I lose?"), when Plan lists substitutions, and when Implement reports caller
impacts.

**Frame each row as what's different and how managed does it, not as what the user gives up.** A wording
rule, not a softening of the grades: the residual on a `Partly` and an honest `No` still have to be stated.
It is also the more accurate framing — the index-tuning surface goes away *because the decisions it existed
to make go away with it*, and direct store access is replaced by an access path that still supports querying
and writing documents.

**Never name a difference without its pairing in the same breath.** A bare list of removed knobs is a
misdescription, because it reports the control and omits the capability that replaced it. Every difference
you raise carries three things: how managed does it instead, **the acceptable substitute where one exists —
stated explicitly, not left for the user to infer** — and the `Covers?` grade.

**A `Partly` row the customer says they need:** state the gap accurately, say what managed offers instead,
and say which parts of the workload can move without it. A hard requirement managed cannot meet is a
real exception (see the `SEMANTIC`-only row); say so plainly, with the fact behind it.

**The `Covers?` value is the claim you are allowed to make. Do not upgrade it.**

- **Yes** — the gap is closed. The managed capability does the same job or better; migrate and say so.
- **Partly** — the gap is narrowed and the residual is named. **State both halves**; never round up to Yes.
- **No** — no managed capability covers it. Say so plainly with its consequence, **give the real alternative
  where one exists** (for direct index access that alternative is architectural — the retrieval APIs, direct
  ingestion, or an AgentCore Gateway/MCP target), and **never offer one of the three capabilities as a
  substitute for something it doesn't actually replace.**

| Difference (what managed handles differently) | What covers it | Covers? | What to tell the user |
|---|---|---|---|
| **Vector-store choice + index tuning** (`storageConfiguration` gone) | Service-managed **auto-scaling** store | **Yes** | The tuning surface disappears because the decisions it existed for do too: dimensions and similarity metric are fixed and correct by construction, hybrid search is on with no index config, encryption is KMS-backed. AWS's own comparison is blunt — managed is an "auto-scaling datastore of embeddings, text, metadata and raw files, managed completely by Bedrock" against "customers choose, provision, scale, and update" — so what is lost is the *ability* to tune, not an outcome tuning was achieving. **State the one real ceiling: raw data storage per KB, read live from Service Quotas (§4, `L-BEE3FA31`)** |
| **`SEMANTIC`-only search** (`overrideSearchType` rejected) | Always-on hybrid + Agentic Retrieval | **Partly** | Hybrid is a superset of the *matching* — keyword *and* semantic on every query — and where semantic-only was serving multi-intent questions, `AgenticRetrieveStream` serves that intent far better by decomposing the query instead of trusting one embedding. Residual to state: hybrid is **not configurable**, so semantic-only cannot be forced and keyword matching always participates in ranking. A caller with a hard requirement to exclude lexical matching is a genuine exception, not a preference to talk them out of. Application code must drop the parameter either way |
| **Custom parser** (`BEDROCK_FOUNDATION_MODEL` / BDA not selectable) | Smart Parsing | **Yes** for a source on the default parser; **Partly** for a source that uses `BEDROCK_FOUNDATION_MODEL` or BDA parsing | Parsing isn't removed, it's standardized and automatic: per-connector data models, bounding-box → FM extraction, captioning, video scene description, documented per-file size ceilings. Beats the self-managed default parser on image-bearing PDFs. What is lost is *parser choice*, not parsing capability. **Partly residual** (FM or BDA parser on the source): compare retrieval on a sample of those documents in the target Region before cutover — scanned, image-heavy or non-English content is where results differ most. A multimodal `CUSTOM` embedding model is the managed path for figure-heavy content (it turns off the managed reranker) |
| **`SEMANTIC` / `HIERARCHICAL` chunking** (rejected on managed) | Smart Parsing's structure awareness | **Partly** | The strategies are rejected; the managed fixed-size default applies. Structure awareness moves upstream into parsing. Residual: no chunk-boundary control. Two embedding-model rules govern what you may emit: on a **managed-embedding** KB emit no `chunkingConfiguration` at all (any strategy is rejected); on a **custom-embedding** KB `FIXED_SIZE` may be carried over |
| **Multi-hop / relationship-aware retrieval** (GraphRAG — closed blocker) | Agentic Retrieval | **Partly — blocker stands** | This is where the new capability changes the answer most, and it still **does not lift the blocker**. Agentic retrieval delivers real multi-hop reasoning (the documented gains grow with hop count; agentic-retrieval blog), so a customer who adopted GraphRAG *for multi-hop question answering* now has a managed capability for that need. It provides **no graph traversal and no explicit entity-relationship structure**. GraphRAG stays on the closed list — offer this as context for the AWS Support conversation, **never as a migration path** |
| **Multimodal embeddings** (`bedrockEmbeddingModelConfiguration`) | A multimodal `CUSTOM` model, or Smart Parsing for figure/layout text | **Partly** | Directly supported, not a substitution: a multimodal `CUSTOM` model embeds image/audio/video content, and on the default path Smart Parsing covers figure and layout text via bounding-box extraction. Residual to state: `CUSTOM` **disables the managed re-ranker**, and not every model qualifies — confirm the current set in the docs rather than assuming |
| **Configurable dimensions / `BINARY`** (one managed dimension + FLOAT32 only) | Managed storage + managed re-ranker | **Partly** | The *accuracy* motive is covered: the default path keeps the managed re-ranker at no extra cost, which is often why a reduced dimension was tolerated. The **cost/footprint** motive is not — a reduced-dimension or `BINARY` index was smaller and has no managed equivalent. Say a full re-embed at the managed dimension and data type is required and the index will be larger |
| **Supplemental data storage** (KB-level bucket you own) | Connector `mediaExtractionConfiguration` + Smart Parsing | **Partly** | Extraction is supported and relocated to a per-data-source switch; managed stores the extracted media itself, so the bucket, its parameter and its IAM grants all disappear. Residual is concrete: **no customer-visible copy in your own bucket** — a downstream job reading it needs a new source |
| **Direct index access** (`aoss:APIAccessAll`, direct SQL) | AgentCore Gateway + MCP, or the retrieval APIs | **No — different access pattern** | No capability covers raw index access: there is no customer-visible index or endpoint to grant. The alternative is architectural — consumers move to `Retrieve`/`AgenticRetrieveStream`, or reach the KB as an auto-discovered MCP tool via an AgentCore Gateway target (KB id hidden behind the gateway, IAM centralized there), neither of which self-managed supports. Name the specific consumer that must be repointed; it does not block the migration |
| **Cross-account access** to the KB (previously done by granting the store directly) | **Resource-based policies** — MANAGED-only | **Yes — and self-managed cannot do this at all** | Where the direct-index grant existed *to share the KB across accounts*, managed replaces it with a first-class mechanism: a resource policy on the knowledge base with `Allow`/`Deny` over `bedrock:Retrieve` and `bedrock:GetDocumentContent`. The docs ([kb-managed-cross-account](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-cross-account.html)) state plainly that **`VECTOR` KBs do not support resource policies**, so this is a capability gained, not a workaround. Separate the two motives before answering: sharing → covered and improved; raw index queries → the row above |
| **`RETAIN` deletion policy** | Connector `deletionProtectionConfiguration` | **Partly** | Managed defaults to `DELETE` with optional deletion protection (+ threshold) on the connector. Protection exists; an explicit `RETAIN` policy does not |
| **Data-source-level SSE** | KB-level CMK | **Partly** | Encryption is covered — at rest and in transit, AWS-managed or CMK. The per-data-source *granularity* is not |
| **ACL mapping control** (`crawlAcl` / `accessControlConfiguration` gone) | `aclEnabled` + two-stage ACL-aware retrieval | **Yes — and stronger** | The knob narrows to one flag, but enforcement improves: crawled pre-retrieval filtering **plus real-time verification against the source** on SharePoint/OneDrive/Google Drive/Confluence, deny-overrides-allow, and it **fails closed**. Three caveats you must state, not one: **ACL awareness is not authorization** (your app authenticates users and passes verified identity — never present it as a security boundary); **Web Crawler cannot use ACLs at all** and S3/Custom get pre-filtering only; and enabling ACLs **can force an `authType`**, while `aclEnabled` is immutable after create on S3 and permanent on Confluence. Detail: `managed-kb-api.md` §3b |
| **One KB became several** (data-sources-per-KB split) | A much higher data-sources-per-KB limit, then Agentic Retrieval multi-KB routing | **Yes — and it usually runs the other way** | Lead with the direction of the change: read both data-sources-per-KB quotas live (§4: `L-679D8304` self-managed, `L-F02D918A` managed) — managed's is far higher, so a migration far more often **consolidates** a fragmented estate than splits it, and the split only bites at genuinely large ones. When it does apply, the usual cost is a caller-side lookup to resolve which shard holds a tenant — and `AgenticRetrieveStream` absorbs that by registering several KBs in one request and routing per sub-query from each retriever's `description`. Write those descriptions specifically; vague descriptions route vaguely |
| **Custom transformation Lambda** (closed blocker) | nothing | **No** | No in-pipeline hook exists, and the `CUSTOM` connector is **direct ingestion, not a transform substitute** (`managed-kb-api.md` §2d). Removing the hook would silently change what gets indexed. Contact AWS Support |
| **Salesforce / Zendesk / Confluence Data Center source** | Native managed connectors (`SALESFORCE` / `ZENDESK` / `CONFLUENCEONPREM`) | **Yes** | These migrate: managed has native Salesforce and Zendesk connectors and Confluence Data Center (`CONFLUENCEONPREM`). State the Salesforce ACL point as a limit both products share: the Salesforce managed connector has **no document-level ACL** (all authenticated KB queriers see all crawled content), and neither does the self-managed one, whose [connector page](https://docs.aws.amazon.com/bedrock/latest/userguide/salesforce-data-source-connector.html) says synced data "becomes available to anyone with `bedrock:Retrieve` permissions". It is not something lost by moving. **Managed gain (R1):** new VECTOR Confluence/SharePoint/Salesforce/Web Crawler connectors can no longer be created, so for these sources managed is the way forward |

### Why most of these are not really tradeoffs

A user can read the `adjusted` list as a column of losses and reasonably ask whether migrating is a
downgrade. It generally isn't, and the argument does not depend on rhetoric — it depends on noticing that
**almost every apparent loss is the removal of a control, while the gains are removals of *limits*.** Use
this framing when a user pushes back, and keep it factual:

1. **The controls being removed mostly existed to compensate for running your own store.** Index tuning,
   dimension reduction, similarity-metric choice and parser selection are all work that exists *because* the
   infrastructure is yours. Managed does not take the outcome away — it takes away the need to produce it,
   and ships a managed embedding model and managed re-ranker **at no extra cost** where self-managed offers
   **none**.
2. **The limits being removed are order-of-magnitude, and they are the ones that shape architecture:** data
   sources per KB, KBs per account, concurrent ingestion jobs and query characters. Quote the values read
   live from Service Quotas (§4), never fixed numbers. Those are not conveniences; they decide whether "a KB per team" or
   "one KB for the whole estate" is even expressible. One apparent migration cost, splitting a KB across
   several, is an artifact of self-managed limits that managed simply doesn't have.
3. **Three capabilities have no self-managed equivalent at all** — agentic retrieval, AgentCore Gateway
   integration, and resource-based policies for cross-account access are documented as "Not supported" on
   `VECTOR`. A migration that trades index tuning gains a retrieval mode, an MCP access path, and a sharing
   mechanism that were previously impossible.
4. **AWS's own recommendation is citable.** The user guide recommends managed for the combination of
   ease-of-use, accuracy and cost. Offer it as a documented position, not as this tool's enthusiasm.

**What keeps this honest — always pair it with the residuals.** The genuine, non-rhetorical residuals are: a
**per-KB raw-storage ceiling** (read live, `L-BEE3FA31`); **no customer-visible index**, so a consumer doing raw index queries must
change how it works; **no reduced-dimension or `BINARY` footprint**, so the index gets larger; **no
supplemental-media bucket you own**; **ACL awareness is filtering, not authorization**; and callers must
**change `Retrieve` request bodies and re-tune score thresholds**. Lead with the reframing, then name these
without being asked. A user who discovers an unmentioned residual later will discount everything else in the
table.

**None of this reopens the blocker list.** The same two features block: the Lambda transform and GraphRAG.
Agentic retrieval narrows the GraphRAG *use case* and must never be used to reclassify it as `READY`.

## Background — self-managed KB building blocks (orientation)

- **Vector store options (self-managed):** OpenSearch Serverless, OpenSearch managed cluster, Aurora
  PostgreSQL (pgvector), Neptune Analytics, S3 Vectors, Pinecone, MongoDB Atlas, Redis Enterprise. Appears
  under `knowledgeBase.storageConfiguration` in `get-knowledge-base`. A MANAGED KB has no customer
  `storageConfiguration` — the store is auto-provisioned.
- **Embedding model** appears under `...vectorKnowledgeBaseConfiguration.embeddingModelArn` (self-managed)
  or `...managedKnowledgeBaseConfiguration.embeddingModelArn` (MANAGED). Model and vector dimensions must be
  compatible with the store.
- **Data sources** (S3, web crawler, other connectors) are separate resources attached to a KB; chunking and
  parsing live in the data source's `vectorIngestionConfiguration`.
- **Migration reality:** a KB's vector store generally cannot be changed in place. Migration means creating
  a NEW KB on the new store/type, attaching equivalent data sources, syncing to rebuild embeddings,
  validating retrieval, then cutting over. Re-embedding is expected.

## Public reference links

> **Reading these:** fetch via `curl` + `.md` (swap `.html`→`.md`), never `web_fetch` — full rule in
> [safety-and-iam](references/bedrock-kb-migration/safety-and-iam.md) → "Reading public AWS docs". Re-verify against live docs; prefer the user's Region.

- Embedding-model options (authoritative `CUSTOM` model list — fetch, don't hardcode): https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-create.html#kb-managed-embedding-models
- Create a managed knowledge base (managed vs custom embedding rules; console parsing/chunking flow; `CreateDataSource` `vectorIngestionConfiguration`): https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-create.html
- Customize ingestion for a data source (accepted managed chunking strategies `DEFAULT`/`FIXED_SIZE`/`NONE`, `SEMANTIC` unsupported, the default chunking size; native-multimodal caveat — **note: this page does NOT yet document that the managed embedding model rejects all chunking config; see Key findings**): https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-customize-ingestion.html
- How content chunking works for knowledge bases (chunking strategy definitions): https://docs.aws.amazon.com/bedrock/latest/userguide/kb-chunking-parsing.html
- AgenticRetrieveStream API reference (the second retrieval surface — §3; **this is where request shapes come from**): https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_AgenticRetrieveStream.html
- Retrieve API reference: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_Retrieve.html
- **Managed vs Customer-managed comparison table + AWS's own recommendation** (source for "Capabilities that simply do not exist on self-managed"): https://docs.aws.amazon.com/bedrock/latest/userguide/kb-build-managed.html
- **Managed knowledge base quotas** (KBs per account, data sources per KB, concurrent ingestion jobs, raw storage per KB, query characters): https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-quotas.html
- **All Bedrock service quotas — the self-managed side of every comparison** (the same quota names for self-managed KBs): https://docs.aws.amazon.com/general/latest/gr/bedrock.html#limits_bedrock
- ACL-aware retrieval, incl. the "not authorization" boundary and the connector support matrix: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-acl.html
- ACL-aware retrieval request syntax (passing user context): https://docs.aws.amazon.com/bedrock/latest/userguide/kb-test-retrieve-acl.html
- Resource policies for managed KBs (cross-account; **`VECTOR` does not support these**): https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-cross-account.html
- AgentCore Gateway target for a knowledge base: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-gateway-target.html
- Supported models and Regions for knowledge bases: https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-supported.html
- Supported Regions for managed knowledge bases: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-regions.html
- Create a knowledge base: https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-create.html
- Sync / ingest data: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-data-source-sync-ingest.html
- StorageConfiguration API reference: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_StorageConfiguration.html
- AWS CLI bedrock-agent reference: https://docs.aws.amazon.com/cli/latest/reference/bedrock-agent/

### Capability announcements (source for "Managed-only capabilities")

> **These are `aws.amazon.com/blogs` posts, not `docs.aws.amazon.com` pages — they have no `.md` twin, so
> the `curl` + `.md` rule does not apply to them.** They are the source for the capability descriptions,
> benchmark figures and documented limits in "Managed-only capabilities" and "Gap coverage". They are
> **narrative, dated, and not an API contract**: for any request shape, parameter name, enum, quota or
> Region list, the API/user-guide pages above win, and a live-tested finding wins over both. Treat a figure
> quoted from here as documented-at-publication, and re-verify anything load-bearing.
>
> **Take capability descriptions from these posts, never request shapes.** Request shapes come from the AWS
> API reference or `--generate-cli-skeleton` — the skills carry none for the runtime surfaces, because
> querying a knowledge base is the user's step.

- Managed Knowledge Base announcement (Smart Parsing, Agentic Retriever, connectors, AgentCore Gateway target, pricing dimensions): https://aws.amazon.com/blogs/aws/introducing-amazon-bedrock-managed-knowledge-base-for-faster-more-accurate-enterprise-ai-applications/
- Enterprise search deep-dive (service-managed storage, real-time ACL checks, incremental sync, parsing size ceilings, three-call setup, Gateway/MCP): https://aws.amazon.com/blogs/machine-learning/build-enterprise-search-for-agents-with-amazon-bedrock-managed-knowledge-base/
- Agentic retrieval deep-dive (`AgenticRetrieveStream` planning loop, trace events, multi-KB routing, MuSiQue results, Retrieve-vs-Agentic comparison, per-call pricing, IAM actions): https://aws.amazon.com/blogs/machine-learning/agentic-retrieval-for-amazon-bedrock-managed-knowledge-base/
