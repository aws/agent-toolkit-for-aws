# Neptune Analytics vector API migration

Use `vectors.topK.byEmbedding` with a single configuration map for
embedding-based vector similarity queries:

```cypher
CALL neptune.algo.vectors.topK.byEmbedding({
  embedding: $embedding,
  topK: $top_k
})
YIELD node, score
RETURN node, score
```

The deprecated procedure did not expose `vertexFilter`. When migrating a
label-scoped search, move any post-`YIELD` label predicate into the supported
procedure so the algorithm selects `topK` results from the intended label:

```cypher
CALL neptune.algo.vectors.topK.byEmbedding({
  embedding: $embedding,
  topK: $top_k,
  vertexFilter: '{"equals":{"property":"~label","value":"Chunk"}}'
})
YIELD node, score
RETURN node, score
```

Do not apply the label filter with `WHERE` after `YIELD`. That filters an
already-selected global `topK` result and can return fewer matching vertices
than requested.

| Old (deprecated) | Replacement |
|---|---|
| `vectors.topKByEmbedding($embedding, {topK: $top_k})` | `vectors.topK.byEmbedding({embedding: $embedding, topK: $top_k})` |

`vectors.upsert(node, embedding)` is unchanged.
