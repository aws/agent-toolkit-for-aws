# Search recipes — query DSL for app developers

The summary is in `SKILL.md` (§ Build a search feature). This file owns the recipes — copy-paste DSL for every common search pattern.

## Index design 101

Always define a mapping before first ingest. Dynamic mapping creates bloated `text` + `keyword` multi-fields you'll regret.

### Standard mapping for a search-driven app

```json
PUT my-app
{
  "settings": {
    "number_of_shards": 3,
    "number_of_replicas": 1,
    "analysis": {
      "analyzer": {
        "default": { "type": "standard" },
        "english_with_synonyms": {
          "type": "custom",
          "tokenizer": "standard",
          "filter": ["lowercase", "stop", "english_stemmer", "synonyms_filter"]
        }
      },
      "filter": {
        "english_stemmer": { "type": "stemmer", "language": "english" },
        "synonyms_filter": {
          "type": "synonym",
          "synonyms": [
            "tv, television",
            "couch, sofa, settee"
          ]
        }
      }
    }
  },
  "mappings": {
    "properties": {
      "id":          { "type": "keyword" },
      "title":       { "type": "text", "analyzer": "english_with_synonyms", "fields": { "keyword": { "type": "keyword" }, "completion": { "type": "search_as_you_type" } } },
      "description": { "type": "text", "analyzer": "english_with_synonyms" },
      "tags":        { "type": "keyword" },
      "category":    { "type": "keyword" },
      "price":       { "type": "scaled_float", "scaling_factor": 100 },
      "in_stock":    { "type": "boolean" },
      "released_at": { "type": "date" },
      "rating":      { "type": "half_float" }
    }
  }
}
```

Key choices:

- `text` for fields you search; `keyword` for facets/sort/exact-match
- Multi-fields `"title": {"type":"text", "fields": {"keyword": {"type":"keyword"}}}` to support both
- `search_as_you_type` for autocomplete
- `scaled_float` for currency (better than `float` for known precision)
- Avoid `nested` unless you actually need it — it's expensive

## Full-text search

### Single-field match

```json
GET my-app/_search
{
  "query": { "match": { "title": "wireless headphones" } }
}
```

### Multi-field with field boosting

```json
GET my-app/_search
{
  "query": {
    "multi_match": {
      "query": "wireless headphones",
      "type": "best_fields",
      "fields": ["title^3", "description^1", "tags^2"]
    }
  }
}
```

`type` options:

- `best_fields` (default) — score = highest single-field score (good for unique-content queries)
- `most_fields` — score = sum of all matching fields (good when same content in multiple fields)
- `cross_fields` — treats fields as one big field (good for entity searches like "first_name last_name")
- `phrase` — must match as phrase
- `phrase_prefix` — phrase + last token can be a prefix

### Boolean (combine queries)

```json
GET my-app/_search
{
  "query": {
    "bool": {
      "must":     [{ "match": { "title": "headphones" } }],
      "should":   [{ "match": { "tags": "noise-cancelling" } }],
      "filter":   [{ "term": { "in_stock": true } }, { "range": { "price": { "lte": 200 } } }],
      "must_not": [{ "term": { "category": "discontinued" } }]
    }
  }
}
```

`filter` doesn't affect score and is cached — use for non-relevance constraints (in-stock, price range, category).

### Phrase queries

```json
{ "match_phrase": { "title": { "query": "machine learning", "slop": 1 } } }
```

`slop=N` allows N word movements within the phrase.

### Operator override (Solr `q.op=AND` equivalent)

OpenSearch defaults to OR. To replicate Solr's `q.op=AND`:

```json
{
  "query": {
    "match": {
      "title": {
        "query": "wireless headphones bluetooth",
        "operator": "AND"
      }
    }
  }
}
```

Or for `query_string`:

```json
{ "query_string": { "query": "wireless AND headphones", "default_operator": "AND" } }
```

This is the **most common cause of result divergence** when migrating from Solr.

## Faceted search (aggregations)

```json
GET my-app/_search
{
  "size": 20,
  "query": { "match": { "title": "headphones" } },
  "aggs": {
    "by_category":  { "terms": { "field": "category", "size": 10 } },
    "by_brand":     { "terms": { "field": "tags", "size": 10 } },
    "price_ranges": {
      "range": {
        "field": "price",
        "ranges": [
          { "to": 50 },
          { "from": 50, "to": 100 },
          { "from": 100, "to": 200 },
          { "from": 200 }
        ]
      }
    },
    "avg_rating":   { "avg": { "field": "rating" } }
  }
}
```

**Multi-select facets** (a user clicked one filter but should still see counts for other facets):

- Use `post_filter` for the clicked facet so other aggs still see all matches
- Use a `filter` aggregation per facet to apply ALL filters EXCEPT this one

## Autocomplete / search-as-you-type

### Option 1: `search_as_you_type` field

```json
{
  "query": {
    "multi_match": {
      "query": "wirele",
      "type": "bool_prefix",
      "fields": ["title.completion", "title.completion._2gram", "title.completion._3gram"]
    }
  }
}
```

Best for general autocomplete on existing fields.

### Option 2: completion suggester

```json
PUT my-app/_doc/1
{
  "title": "Sony WH-1000XM5 Wireless Headphones",
  "title_completion": {
    "input": ["Sony WH-1000XM5", "Sony Wireless Headphones", "Noise Cancelling"]
  }
}

POST my-app/_search
{
  "suggest": {
    "title_suggest": {
      "prefix": "wirele",
      "completion": { "field": "title_completion", "size": 5 }
    }
  }
}
```

Best for product/entity name autocomplete with curated alternatives.

### Option 3: edge_ngram (legacy / rarely needed)

For non-native scripts where prefix matters character-by-character.

## Spell correction (Did You Mean)

```json
{
  "suggest": {
    "spell_check": {
      "text": "wirless headfones",
      "phrase": {
        "field": "title",
        "size": 1,
        "gram_size": 3,
        "direct_generator": [{
          "field": "title",
          "suggest_mode": "always"
        }],
        "highlight": { "pre_tag": "<em>", "post_tag": "</em>" }
      }
    }
  }
}
```

## Fuzzy search (typo tolerance)

```json
{
  "query": {
    "match": {
      "title": {
        "query": "wireles",
        "fuzziness": "AUTO"
      }
    }
  }
}
```

`fuzziness: AUTO` (recommended): 0 edits for ≤2 char terms, 1 edit for 3–5 chars, 2 edits for ≥6 chars.

## "More like this" / similar items

```json
{
  "query": {
    "more_like_this": {
      "fields": ["title", "description"],
      "like": [{ "_index": "my-app", "_id": "12345" }],
      "min_term_freq": 1,
      "max_query_terms": 12
    }
  }
}
```

## Function score (custom relevance)

Boost recent items, popular items, in-stock items:

```json
{
  "query": {
    "function_score": {
      "query": { "match": { "title": "headphones" } },
      "functions": [
        {
          "filter": { "term": { "in_stock": true } },
          "weight": 1.5
        },
        {
          "field_value_factor": {
            "field": "rating",
            "factor": 0.5,
            "modifier": "log1p",
            "missing": 0
          }
        },
        {
          "gauss": {
            "released_at": {
              "origin": "now",
              "scale": "30d",
              "decay": 0.5
            }
          }
        }
      ],
      "score_mode": "sum",
      "boost_mode": "multiply"
    }
  }
}
```

## Sorting

```json
{
  "query": { "match": { "title": "headphones" } },
  "sort": [
    { "rating": { "order": "desc" } },
    { "price":  { "order": "asc" } },
    "_score"
  ]
}
```

To sort on a `text` field, sort on its `.keyword` subfield.

## Highlighting

```json
{
  "query": { "match": { "title": "headphones" } },
  "highlight": {
    "fields": {
      "title":       { "pre_tags": ["<em>"], "post_tags": ["</em>"] },
      "description": { "fragment_size": 150, "number_of_fragments": 3 }
    }
  }
}
```

## Pagination

### Standard `from`/`size` (works up to ~10K results)

```json
{ "from": 100, "size": 20, "query": { "match_all": {} } }
```

### `search_after` for deep pagination

```json
{
  "size": 20,
  "query": { "match_all": {} },
  "sort": [{ "_id": "asc" }],
  "search_after": ["last_doc_id_from_previous_page"]
}
```

### `point_in_time` (PIT) for consistent paging across long sessions

```bash
POST my-app/_search/point_in_time?keep_alive=1m
# returns "pit_id"

POST _search
{
  "size": 20,
  "pit": { "id": "<pit_id>", "keep_alive": "1m" },
  "sort": [{ "_id": "asc" }],
  "search_after": [...]
}
```

## Synonyms

### Index-time synonyms (slower indexing, faster queries, larger index)

Define in mapping `analysis.filter.synonyms_filter` and apply analyzer to text fields.

### Search-time synonyms (faster indexing, slower queries, smaller index)

```json
{
  "settings": {
    "analysis": {
      "filter": {
        "search_synonyms": {
          "type": "synonym_graph",
          "synonyms": ["tv, television", "couch, sofa"]
        }
      },
      "analyzer": {
        "search_with_synonyms": {
          "type": "custom",
          "tokenizer": "standard",
          "filter": ["lowercase", "search_synonyms"]
        }
      }
    }
  },
  "mappings": {
    "properties": {
      "title": {
        "type": "text",
        "analyzer": "standard",
        "search_analyzer": "search_with_synonyms"
      }
    }
  }
}
```

**Recommendation**: Start with search-time synonyms — easier to update without reindexing.

## Boost recent items in relevance

Use `function_score` with `gauss` decay (above) — natural log decay over time.

## Geo search

```json
{
  "query": {
    "bool": {
      "must": { "match": { "name": "coffee" } },
      "filter": {
        "geo_distance": {
          "distance": "5km",
          "location": { "lat": 47.6062, "lon": -122.3321 }
        }
      }
    }
  }
}
```

Field type: `geo_point` or `geo_shape`.

## Solr → OpenSearch query translation reference

| Solr | OpenSearch DSL |
|---|---|
| `q=headphones` | `{"multi_match": {"query": "headphones", "fields": ["title", "description"]}}` (no `_all` in OpenSearch — list fields explicitly) |
| `q=title:headphones` | `{"match": {"title": "headphones"}}` |
| `q.op=AND` | `"default_operator": "AND"` on `query_string` OR `"operator": "AND"` on `match` |
| `qf=title^3 description` (eDisMax) | `multi_match` `type: best_fields` with `fields: ["title^3", "description"]` |
| `pf=title^5` (phrase boost) | `should` clause with `multi_match type:phrase` (approximation only) |
| `tie=0.3` (eDisMax) | `tie_breaker: 0.3` on `multi_match` `type: best_fields` |
| `mm=2<-25%` | `minimum_should_match: "2<-25%"` (passes UNCHANGED) |
| `fq=in_stock:true` | `filter` clause in `bool` query: `{"term": {"in_stock": true}}` |
| `sort=rating desc, price asc` | `sort: [{"rating": "desc"}, {"price": "asc"}]` |
| `start=20&rows=20` | `from: 20, size: 20` |
| `facet=true&facet.field=category` | `aggs: {"by_category": {"terms": {"field": "category"}}}` |
| `hl=true&hl.fl=title` | `highlight: {"fields": {"title": {}}}` |
| `mlt=true` | `more_like_this` query |
| `bf=recip(...)` (boost function) | `function_score` with `field_value_factor` |
| `defType=edismax` | `multi_match` (closest equivalent) |
| `wt=json` | `Accept: application/json` header (OpenSearch defaults JSON) |

## Common gotchas

1. **Dynamic mapping** — first doc creates field types. A field like `"id": "12345"` becomes `text` (not `keyword`) and `text` can't be used for sort/facet without `fielddata: true` (OOM-prone). **Always pre-define mappings.**
2. **Cannot change field type** without reindex. Add new field, dual-write, switch reads, drop old.
3. **`text` vs `keyword`** — text is analyzed (lowercased, tokenized, stemmed). Keyword is stored as-is. For an ID field that should be exact-match, use `keyword`.
4. **`refresh_interval`** is 1s default. New documents not searchable for up to 1s. Force with `?refresh=true` (slow — use sparingly).
5. **`_id` is automatic by default** (random UUID). Set explicit `_id` in `_bulk` to ensure idempotent writes.
6. **`max_result_window`** defaults to 10,000. To page beyond, use `search_after` or `point_in_time`. Don't blindly raise the setting.
7. **Aggregations on `text` fields require `fielddata: true`** (OOM risk). Use `keyword` subfields for aggs/sort.
8. **`null` ≠ missing** — explicitly handle null with `"null_value"` in mapping or use `exists` query.
9. **Reserved field names** like `_id`, `_source`, `_index`, `_doc`. Don't try to redefine them.
10. **`copy_to`** is the OpenSearch native equivalent of Solr `copyField`. Don't replicate via external pipeline.

## Performance tuning for queries

- **Cache `filter` clauses** — they're cached by default, faster than `must`.
- **`doc_values: true`** is default for keyword/numeric/date — required for sort/agg.
- **Use `_source` filtering** to return only needed fields: `"_source": ["title", "id"]`.
- **Avoid `term` on analyzed `text` fields** — use `match` instead.
- **Avoid `keyword` mapping for very high-cardinality string fields** if you don't need exact match (slower aggs).
- **Use `index: false`** on fields you store but never search.
- **Profile slow queries** with the `_search?profile=true` flag.
