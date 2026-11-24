# Searching memories and events

## Overview

Build `search-memories` and `search-events` requests. The query is a clause of the OpenSearch query DSL, restricted to an allowlist; anything outside it returns `ValidationException` with a `reason`.

## Request shape

```bash
aws opensearchmemory search-memories --region <region> --space-id <space-id> \
  --actor-id <actor-id> \
  [--memory-strategies '[{"memoryType":"SEMANTIC","memoryStrategyNames":["user-facts"]}]'] \
  --search-query '<query clause>' [--sort '<sort clause>'] [--max-items <n>]
```

**`--search-query`:** the CLI option for the API member `query`. Pass the query clause itself, for example `{"match":{"memory_text":"vegetarian"}}`, not an object wrapped in `"query"`. In boto3, pass `query=` and `sort=`.

**`actorId`:** required. Every search is scoped to one actor.

**Sessions:** `search-memories` does not take `--session-ids`; it searches all of the actor's sessions. `search-events` accepts `--session-ids` (1-10) to narrow a search of raw turns, and `list-memories --session-ids` browses one session's memories.

**`memoryStrategies` selector:**

- 1-5 entries, each `{memoryType, memoryStrategyNames?}`. Omit it to search every strategy.
- Naming a type or strategy the space does not declare is a `ValidationException`, not an empty result.
- To select by type, use this selector. `memory_type` inside the query is rejected.

**Paging:** there are no `size`, `from`, aggregation or highlight parameters. The CLI paginates for you; the API uses `maxResults` (1-100, default 20) and `nextToken`. The result window is 10,000.

**Results:**

- Each memory has `memoryId`, `memoryType`, `content`, `score`, `systemMetadata`, `metadata` and `sourceEventIds` (the events it was derived from; absent for a memory written with `create-memory`).
- Only current memories are returned; a memory that consolidation replaced, or that has expired, is left out.
- Scores are not normalized and can exceed 1. Use them only to order results.

## Fields you can query

| | Memories | Events |
|---|---|---|
| Text (`match`, `match_phrase`) | `memory_text` | `text` |
| Vector (`neural` only) | `memory_vector` | `vector` |
| Both | `system_metadata.created_at`, `system_metadata.updated_at`, `metadata.<key>` | same, plus `event_ids` |

**Response vs query field names:** the response field is `content`, but you query `memory_text`. Querying `content` fails with "Unknown or non-searchable field 'content'". Responses use camelCase (`systemMetadata.createdAt`); queries use snake_case (`system_metadata.created_at`).

**Fields you cannot query:**

- `system_metadata.actor_id` and `system_metadata.session_id` fail with `nonFilterableField`. Use `--actor-id` (and, for `search-events`, `--session-ids`) instead.
- A vector field outside `neural` fails with `nonFilterableField`; the other operation's text or vector field fails with `fieldIndexMismatch`; any other field fails with `unknownField`.

**Metadata tags:** filter on `metadata.<key>`. A `term` or `terms` query on a tag matches the whole value exactly, including capitals, spaces and S3 URIs.

**Neural queries:**

- Send text, not vectors; the service embeds `query_text` itself. `model_id` is rejected.
- One `neural` query text per request, at most 2,048 characters.
- `k` is the number of nearest neighbors each vector search graph returns, not the number of results. Limit results with `maxResults`.

## Allowed queries

| Kind | Types |
|---|---|
| Leaf | `match_all`, `match`, `match_phrase` (slop ≤ 10), `term`, `terms` (≤ 100 values, ≤ 10 on `event_ids`, inline only), `ids` (≤ 100), `exists`, `range` (time fields only), `neural` |
| Compound | `bool` (nesting ≤ 5), `constant_score`, `boosting`, `function_score` (only `gauss`/`linear`/`exp` decay on time fields, ≤ 3), `hybrid` |

**`hybrid`:**

- Only as the top-level query, with exactly 2 sub-queries, such as one `match` and one `neural`. An optional `filter` is allowed.
- Sort it by `_score` alone (descending, the default) or by time fields alone. Results sorted by time have no `score`.

**`sort`:** on `_score`, `system_metadata.created_at` or `system_metadata.updated_at`, `asc` or `desc`.

**Rejected query types** (`disallowedQueryType`): `prefix`, `wildcard`, `regexp`, `fuzzy`, `knn`, `script`, `nested` and anything else not listed.

**Limits:**

- Query and sort ≤ 64 KiB together, nested at most 64 JSON levels.
- ≤ 32 clauses in total.
- Query text ≤ 2,048 chars.
- A response larger than 5 MiB fails with `queryBodyTooLarge`; lower `maxResults`.

## Examples

Build a query that carries user text with `jq`, then pass it as `--search-query "$QUERY"`.

**Semantic recall for one user** (`$QUERY_TEXT`, for example "food the user cannot eat"):

```bash
QUERY=$(jq -n --arg q "$QUERY_TEXT" '{neural:{memory_vector:{query_text:$q,k:5}}}')
```

**Hybrid (keyword + semantic)** (`$KEYWORDS`, for example "live"; `$QUERY_TEXT`, for example "where does the user live"):

```bash
QUERY=$(jq -n --arg kw "$KEYWORDS" --arg q "$QUERY_TEXT" '{hybrid:{queries:[
  {match:{memory_text:$kw}},
  {neural:{memory_vector:{query_text:$q,k:10}}}]}}')
```

**Newest first, last 7 days:** query and sort are separate parameters.

```bash
--search-query '{"range":{"system_metadata.created_at":{"gte":"now-7d"}}}' \
--sort '[{"system_metadata.created_at":"desc"}]'
```

**Filter on event metadata copied into memories** (metadata key `channel`). To trace a memory to its source document, use its `sourceEventIds`:

```json
{"bool":{"must":[{"match":{"memory_text":"recipes"}}],"filter":[{"term":{"metadata.channel":"web"}}]}}
```

## Reason codes

The AWS CLI prints only the error message. The `reason` and `fieldList` are in the response body: read them from the SDK exception (in boto3, `e.response["reason"]`) or with `--debug`.

| `reason` | Meaning |
|---|---|
| `disallowedQueryType` | Query type not allowed, or `hybrid` not at the top level |
| `unknownField` | Field is not queryable |
| `nonFilterableField` | Field exists but must not be filtered here (actor, session, type, or a vector field outside `neural`) |
| `fieldIndexMismatch` | `match`/`match_phrase` not on the text field, `neural` not on the vector field, or a field of the other operation |
| `queryNestingTooDeep` | `bool` nesting over 5, or more than 64 JSON levels |
| `queryBodyTooLarge` | Size, clause, value, sub-query, function or embedding limit exceeded |
| `malformedQueryBody` | Not a valid JSON object, or a required part is missing |
| `invalidNextToken` | Malformed page token, or past the 10,000 window |
| `fieldValidationFailed` | A value is out of range (e.g. `k`, text length), a field the clause or sort doesn't allow, or an undeclared strategy |
| `unsupportedParameter` | Parameter not allowed in a clause (e.g. `model_id`, `fuzziness`, a terms lookup) |
