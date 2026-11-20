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
  vertexFilter: {equals: {property: '~label', value: 'Chunk'}}
})
YIELD node, score
RETURN node, score
```

Pass `vertexFilter` as an openCypher map, not a quoted JSON string. Neptune
Analytics rejects a string with `Type mismatch: ... Expected MAP`. Use `$`
parameters for dynamic values inside the map, for example
`{equals: {property: '~label', value: $label}}`.

Do not apply the label filter with `WHERE` after `YIELD`. That filters an
already-selected global `topK` result and can return fewer matching vertices
than requested.

| Old (deprecated) | Replacement |
|---|---|
| `vectors.topKByEmbedding($embedding, {topK: $top_k})` | `vectors.topK.byEmbedding({embedding: $embedding, topK: $top_k})` |

`score` is the squared Euclidean distance between the input embedding and the
node's embedding, so **lower scores are nearer**. The documentation does not
guarantee result order, so add `ORDER BY score ASC` when callers need
nearest-first results. `ORDER BY score DESC` returns the farthest of the `topK`
results first. Call the procedure directly:
prefixing it with `MATCH (n)` or `WITH` is forbidden. Pass a static embedding
(a literal or a query parameter), not the output of another query.

`vectors.upsert(node, embedding)` is unchanged.
