# Index Template Skeleton — Elasticsearch / OpenSearch source

Use this when the source is Elasticsearch or OpenSearch. Most ES/OS mappings carry over 1:1; this skeleton is the audit target for the handful of constructs that need action (see the *ES field/mapping → OpenSearch* table in [source-elasticsearch.md](../references/source-elasticsearch.md)). For Solr sources use [solr-index-template-skeleton.md](solr-index-template-skeleton.md) instead.

> **Migration Assistant for Amazon OpenSearch Service does this for you.** Historical Data Migration's metadata-migration phase translates the source mappings + index templates into OpenSearch-compatible form (stripping `_type`, converting `dense_vector`→`knn_vector`, `flattened`→`flat_object`) and reindexes documents. This skeleton is for **auditing** Migration Assistant for Amazon OpenSearch Service's output and for the rare override — NOT a manual step in the migration plan.

```json
{
  "index_patterns": ["<index-name>-*"],
  "template": {
    "settings": {
      "number_of_shards": "<from Step 5 sizing>",
      "number_of_replicas": 1,
      "refresh_interval": "30s",
      "analysis": {
        "analyzer": {
          "<custom_analyzer>": {
            "type": "custom",
            "tokenizer": "<tokenizer>",
            "filter": ["lowercase", "<filter>"]
          }
        }
      }
    },
    "mappings": {
      "properties": {
        "<keyword_field>": { "type": "keyword" },
        "<text_field>": {
          "type": "text",
          "fields": { "keyword": { "type": "keyword", "ignore_above": 256 } }
        },
        "<int_field>": { "type": "integer" },
        "<date_field>": { "type": "date", "format": "strict_date_optional_time||epoch_millis" },
        "<geo_field>": { "type": "geo_point" },
        "<vector_field>": {
          "type": "knn_vector",
          "dimension": "<dim>",
          "method": { "name": "hnsw", "engine": "faiss", "space_type": "l2" }
        }
      }
    }
  }
}
```

## Fill-in checklist

- [ ] `index_patterns` matches the target index / alias name.
- [ ] `number_of_shards` / `number_of_replicas` come from Step 5 (Estimate Sizing); `refresh_interval` defaults to `30s` for prod per [`sizing.md`](../references/sizing.md), not `1s`.
- [ ] **`_type` removed.** Multi-type (ES 6.x) or `_doc`-placeholder (ES 7.x) mappings are flattened — types do not exist in OpenSearch (nugget #9).
- [ ] **`fielddata: true` stripped** from text fields and replaced with a `.keyword` subfield + `doc_values` (nugget #8) or the node OOMs on first aggregation.
- [ ] **`dense_vector` → `knn_vector`** with an explicit `method`/`engine` chosen per the k-NN engine table in [`vector-knn.md`](../references/vector-knn.md); recall validated against source. `[verify]` the current default engine for the target version.
- [ ] **`flattened` → `flat_object`.**
- [ ] **Runtime fields** are pre-computed at ingest (no `runtime` mapping equivalent); reindex required.
- [ ] **`_source: {enabled: false}`** indexes are migrated via Migration Assistant for Amazon OpenSearch Service Historical Data Migration only (nugget #22), and `_source` is re-enabled on the target.
- [ ] Field aliases (`alias` type) carry over unchanged.
- [ ] Painless scripts re-tested; inline scripts noted as a Serverless NextGen blocker if that target is in play.
- [ ] Custom analyzers replicated under `analysis`; filter order preserved (`lowercase` before `synonym_graph`/`stop`).
- [ ] Domain-level security verified before deployment: encryption at rest with a customer-managed KMS key (`EncryptionAtRestOptions`); node-to-node encryption (`NodeToNodeEncryptionOptions`); HTTPS enforced (`EnforceHTTPS: true`, `TLSSecurityPolicy: Policy-Min-TLS-1-2-2019-07`); fine-grained access control with IAM/SAML/OIDC; access policy scoped by principal and source ARN/account. You MUST NOT use `0.0.0.0/0`.
- [ ] If using a custom domain endpoint, an ACM-managed certificate ARN is configured (`CustomEndpoint.CertificateArn`). You MUST NOT use a self-managed certificate.

## What goes where in the final report

You MUST embed the filled-in template in section **2. Schema / Mapping** of the report. You MUST cite the source `_mapping` field name for each non-trivial mapping decision in the table.
