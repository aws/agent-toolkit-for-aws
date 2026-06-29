# Knowledge retrieval recipe — topic → tool → URL

When a `[verify]` tag remains in a draft, this file says where to look.

The skill draft has stable-core embedded. ONLY hit external retrieval for **version-volatile** values. Resolve all `[verify]` tags in ONE batched pass — never per-claim.

## Three retrieval primitives

The first two primitives are AWS-MCP-server-specific. They're convenient when the MCP server is loaded, but they are NOT required — every retrieval below has a non-MCP fallback (column 3).

| Primitive | When | Non-MCP fallback |
|---|---|---|
| **`aws___read_documentation`** (AWS MCP) | AWS-domain URLs only (`docs.aws.amazon.com/*`, `aws.amazon.com/*`) | `WebFetch` (or `curl <url>`) |
| **`WebFetch`** | Non-AWS hosts (`docs.opensearch.org`, `solr.apache.org`, `elastic.co`, `github.com`, etc.) | `curl <url>` |
| **`aws___get_regional_availability`** (AWS MCP) | Confirm an AWS service or instance class is available in a target region | `aws opensearch list-instance-type-details --region <region>` (CLI) or `aws ec2 describe-instance-type-offerings --region <region>` |

Per-domain routing rules:

| Domain | Tool |
|---|---|
| `docs.aws.amazon.com/*` | `aws___read_documentation` |
| `aws.amazon.com/blogs/*` | `aws___read_documentation` (or WebFetch as fallback) |
| `aws.amazon.com/opensearch-service/*` | `aws___read_documentation` |
| `docs.opensearch.org/*` | WebFetch |
| `opensearch.org/blog/*` | WebFetch |
| `solr.apache.org/*` | WebFetch |
| `elastic.co/*` | WebFetch |
| `github.com/opensearch-project/*` | `gh` CLI (Bash) or WebFetch |
| `lucene.apache.org/*` | WebFetch |

## Batched verification recipe

After drafting Steps 3–7 with `[verify]` tags, do this in ONE pass:

1. **Gather** all `[verify]` markers
2. **Group by domain** (one call per domain when possible)
3. **Run independent retrievals concurrently** (multiple tool calls in a single message)
4. **Resolve each tag**: replace `[verify]` with confirmed value + source URL + retrieval timestamp in Citations

## Topic → URL map

### Amazon OpenSearch Service (Managed)

| Topic | URL |
|---|---|
| Service overview | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/what-is.html |
| Best practices index | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/bp.html |
| Storage best practices | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/bp-storage.html |
| Sharding best practices | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/bp-sharding.html |
| Instance best practices | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/bp-instances.html |
| Petabyte-scale | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/petabyte-scale.html |
| Supported instance types | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/supported-instance-types.html |
| OR1 / OR2 | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/or1.html |
| Multi-AZ with Standby | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/managedomains-multiaz.html |
| Auto-Tune | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/auto-tune.html |
| CloudWatch metrics | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/managedomains-cloudwatchmetrics.html |
| CloudWatch alarms | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/cloudwatch-alarms.html |
| Handling errors | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/handling-errors.html |
| UltraWarm | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/ultrawarm.html |
| Cold storage | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/cold-storage.html |
| Index State Management (ISM) | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/ism.html |
| Snapshots | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/managedomains-snapshots.html |
| Version migration | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/version-migration.html |
| Pricing | https://aws.amazon.com/opensearch-service/pricing/ |

### Amazon OpenSearch Serverless

| Topic | URL |
|---|---|
| Serverless overview | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-overview.html |
| Serverless scaling | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-scaling.html |
| NextGen vs Classic | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-vector-search.html |
| Serverless general reference | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-genref.html |

### OpenSearch Ingestion (OSI)

| Topic | URL |
|---|---|
| OSI overview | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/ingestion.html |
| Features | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/osis-features-overview.html |

### Migration Assistant for Amazon OpenSearch Service

| Topic | URL |
|---|---|
| Solutions overview | https://aws.amazon.com/solutions/implementations/migration-assistant-for-amazon-opensearch-service/ |
| Project documentation | https://docs.opensearch.org/latest/migration-assistant/ |
| Project repo | https://github.com/opensearch-project/opensearch-migrations |
| Solution overview detail | https://docs.aws.amazon.com/solutions/latest/migration-assistant-for-amazon-opensearch-service/solution-overview.html |

### Security

| Topic | URL |
|---|---|
| Fine-grained access control | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/fgac.html |
| Encryption at rest | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/encryption-at-rest.html |
| Node-to-node encryption | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/ntn.html |
| Cognito auth | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/cognito-auth.html |
| SAML auth | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/saml.html |
| Compliance services in scope | https://aws.amazon.com/compliance/services-in-scope/ |

### k-NN / vector search

| Topic | URL |
|---|---|
| k-NN field type (AWS) | https://docs.aws.amazon.com/opensearch-service/latest/developerguide/knn.html |
| k-NN methods and engines (project) | https://docs.opensearch.org/latest/search-plugins/knn/knn-methods-engines/ |
| Vector capabilities blog | https://aws.amazon.com/blogs/big-data/amazon-opensearch-services-vector-database-capabilities-explained/ |
| Hybrid search blog | https://opensearch.org/blog/hybrid-search/ |
| RRF blog | https://opensearch.org/blog/introducing-reciprocal-rank-fusion-hybrid-search/ |

### OpenSearch project (engine docs)

| Topic | URL |
|---|---|
| OpenSearch documentation | https://docs.opensearch.org/latest/ |
| Release notes | https://opensearch.org/lines/ |
| Community forum | https://forum.opensearch.org/ |
| OS 3.0 unveiling blog | https://opensearch.org/blog/unveiling-opensearch-3-0/ |
| OpenSearch Benchmark | https://github.com/opensearch-project/opensearch-benchmark |
| Observability platform | https://opensearch.org/platform/observability/ |

### Source-engine documentation

| Topic | URL |
|---|---|
| Apache Solr 9.x ref guide | https://solr.apache.org/guide/solr/latest/ |
| Elasticsearch 7.x reference | https://www.elastic.co/guide/en/elasticsearch/reference/7.17/ |
| Elasticsearch 8.x reference | https://www.elastic.co/guide/en/elasticsearch/reference/current/ |
| ES BM25 tuning | https://www.elastic.co/blog/practical-bm25-part-3-considerations-for-picking-b-and-k1-in-elasticsearch |

## Common verification queries

| `[verify]` value | What to check | Where |
|---|---|---|
| Current instance families | Latest AOS supported instance types | `supported-instance-types.html` |
| Regional availability of `r8g.4xlarge.search` | AOS instance availability per region | `aws___get_regional_availability` |
| Migration Assistant for Amazon OpenSearch Service supported sources | Latest Migration Assistant for Amazon OpenSearch Service matrix | `solution-overview.html` |
| OS Serverless OCU caps | Current default + max | `serverless-scaling.html` |
| OS Serverless NextGen vs Classic capabilities | Current matrix | `serverless-vector-search.html` |
| `max_clause_count` default for current OS | Search settings | `docs.opensearch.org/latest/install-and-configure/configuring-opensearch/search-settings/` |
| GovCloud Historical Data Migration shard-size cap | Latest Migration Assistant for Amazon OpenSearch Service GovCloud notes | `solution-overview.html` |
| Latest OpenSearch GA version | Release notes | `opensearch.org/lines/` |
| FAISS HNSW vs IVF on Serverless | Current vector matrix | `serverless-vector-search.html` |

## Citation format for reports

Every `[verify]`-tagged claim that's resolved must be cited in the report's Citations section:

```
- AOS Best Practices — Sharding (`bp-sharding.html`), retrieved <date>: <quoted value> — see references/sizing.md for canonical shard-cap heuristics
- Migration Assistant for Amazon OpenSearch Service solution overview, retrieved <date>: <quoted source/target matrix>
- Amazon OpenSearch Service pricing page, retrieved <date>: <quoted OCU definition> — see references/sizing.md for OCU sizing math
```

Aim for ≥ 3 unique URLs in any full assessment. Cite what you used; no arbitrary floor.
