# Index Template Skeleton

You MUST fill in the placeholders during Step 3 (Translate Schema). You MUST emit one `properties` entry per Solr field. You MUST map the Solr `uniqueKey` to OpenSearch `_id` and set `_id` explicitly on every index request. You MUST NOT rely on auto-generated IDs because doing so breaks idempotent re-indexing and dedup-by-fingerprint workflows.

```json
{
  "index_patterns": ["<index-name>-*"],
  "template": {
    "settings": {
      "number_of_shards": 1,
      "number_of_replicas": 1,
      "refresh_interval": "30s",
      "analysis": {
        "analyzer": {
          "<custom_analyzer>": {
            "type": "custom",
            "tokenizer": "<tokenizer>",
            "filter": ["lowercase", "<filter>"]
          }
        },
        "filter": {
          "<filter>": {
            "type": "synonym_graph",
            "synonyms_path": "analyzers/<file>.txt"
          }
        }
      }
    },
    "mappings": {
      "dynamic_templates": [
        {
          "strings_as_keyword": {
            "match_mapping_type": "string",
            "mapping": { "type": "keyword" }
          }
        }
      ],
      "properties": {
        "<solr_uniqueKey>": { "type": "keyword" },
        "<text_field>": {
          "type": "text",
          "analyzer": "<custom_analyzer>",
          "fields": { "raw": { "type": "keyword", "ignore_above": 256 } }
        },
        "<int_field>": { "type": "integer" },
        "<long_field>": { "type": "long" },
        "<date_field>": { "type": "date", "format": "epoch_millis||strict_date_optional_time" },
        "<geo_field>": { "type": "geo_point" }
      }
    }
  }
}
```

## Fill-in checklist

- [ ] `index_patterns` matches the target index name.
- [ ] `number_of_shards` / `number_of_replicas` come from Step 5 (Estimate Sizing).
- [ ] Every Solr field has an explicit `properties` entry. You MUST NOT rely on dynamic mapping for production fields because dynamic mapping causes type conflicts.
- [ ] Solr `uniqueKey` is mapped to a `keyword` field AND set as `_id` on every index request.
- [ ] Date `"format"` matches the on-the-wire encoding — `strict_date_optional_time` for ISO-8601 strings (default), `epoch_millis` for long integers, or both (`strict_date_optional_time||epoch_millis`) per [solr-transformation-rules](../references/solr-transformation-rules.md).
- [ ] Solr geo strings (`"lat,lon"`) are converted to `geo_point` objects.
- [ ] Solr internal fields (`_version_`, `_root_`, `_nest_path_`) are stripped before indexing.
- [ ] Field names containing dots (e.g. `product.id`) are renamed to use underscores.
- [ ] Custom analyzers from `schema.xml` are replicated as `analysis.analyzer` blocks; filter order preserved.
- [ ] Domain-level security settings (configured separately from the index template, but verified before deployment): encryption at rest with a customer-managed KMS key (`EncryptionAtRestOptions`); node-to-node encryption (`NodeToNodeEncryptionOptions`); HTTPS enforced (`EnforceHTTPS: true`, `TLSSecurityPolicy: Policy-Min-TLS-1-2-2019-07`); fine-grained access control (FGAC) with IAM/SAML/OIDC authentication; access policy scoped by principal and source ARN/account. You MUST NOT use `0.0.0.0/0` because it exposes the cluster to the entire internet.
- [ ] If using a custom domain endpoint, an ACM-managed certificate ARN is configured (`CustomEndpoint.CertificateArn`) for automated rotation. You MUST NOT use a self-managed certificate because expiry will silently break TLS in production.

## What goes where in the final report

You MUST embed the filled-in template in section **2. Schema Mapping** of [report-template](report-template.md). You MUST cite the source `schema.xml` line range (or Schema API field name) for each non-trivial mapping decision in the table.
