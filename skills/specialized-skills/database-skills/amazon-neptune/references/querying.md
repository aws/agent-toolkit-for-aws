# Neptune Querying

Covers Gremlin (primary), openCypher, and SPARQL query patterns.
Includes pagination — the most common agent mistake.

## Gremlin

### Connection

```python
from gremlin_python.driver import client, serializer

neptune_client = client.Client(
    'wss://your-cluster.cluster-xxxx.us-east-1.neptune.amazonaws.com:8182/gremlin',
    'g',
    message_serializer=serializer.GraphSONSerializersV2d0()
)

# Execute a query
results = neptune_client.submit("g.V().limit(10).valueMap(true)").all().result()
```

### Common traversal patterns

```groovy
// Get all vertices with a label
g.V().hasLabel('Person').valueMap(true)

// Filter by property
g.V().has('Person', 'age', gt(25)).values('name')

// Traverse an edge
g.V().has('Person', 'name', 'Alice').out('KNOWS').values('name')

// Multi-hop traversal: friends of friends
g.V().has('Person', 'name', 'Alice')
  .out('KNOWS')      // Alice's friends
  .out('KNOWS')      // their friends
  .dedup()           // remove duplicates
  .values('name')

// Edge properties
g.V().has('Person', 'name', 'Alice')
  .outE('PURCHASED')
  .has('amount', gt(50))
  .inV()
  .values('name')

// Count
g.V().hasLabel('Product').count()

// Path (full traversal path with all vertices and edges)
g.V().has('Person', 'name', 'Alice')
  .repeat(out('KNOWS'))
  .times(3)
  .path()
```

### Pagination — agents get this wrong

Neptune does not have SQL-style `LIMIT/OFFSET` keywords. Use Gremlin's
**`range(start, end)`** step to paginate results. This is functionally
offset-based — it skips `start` elements and returns up to `end - start`.

⚠️ `range()` still scans and discards skipped elements internally (O(n) cost).
For large datasets with deep pagination, prefer a **property-based cursor**
(e.g., filter by a timestamp or sequential ID greater than the last seen value).

```python
# ❌ Wrong: no pagination — will time out or truncate on large graphs
results = neptune_client.submit("g.V().hasLabel('Person').valueMap(true)").all().result()

# ✅ Correct: paginate with range() — simple but O(n) for deep pages
PAGE_SIZE = 100

def get_page(offset: int, page_size: int = PAGE_SIZE):
    query = f"g.V().hasLabel('Person').range({offset}, {offset + page_size}).valueMap(true)"
    return neptune_client.submit(query).all().result()

# Iterate all pages
offset = 0
while True:
    page = get_page(offset)
    if not page:
        break
    process(page)
    offset += PAGE_SIZE

# ✅ Better for large datasets: cursor-based pagination using a property
def get_page_cursor(last_seen_id: str = None, page_size: int = 100):
    """Use a sequential property as cursor for O(1) page access."""
    if last_seen_id:
        query = f"g.V().hasLabel('Person').has('id', gt('{last_seen_id}')).order().by('id').limit({page_size}).valueMap(true)"
    else:
        query = f"g.V().hasLabel('Person').order().by('id').limit({page_size}).valueMap(true)"
    return neptune_client.submit(query).all().result()
```

### repeat() / until() — graph traversal loops

```groovy
// Find all ancestors (walk up a hierarchy until root)
g.V().has('Category', 'name', 'Smartphones')
  .repeat(__.in('PARENT_OF'))
  .until(__.inE('PARENT_OF').count().is(0))
  .path()
  .by('name')

// BFS up to 5 hops, collect all reachable nodes
g.V().has('Person', 'name', 'Alice')
  .repeat(out('KNOWS').simplePath())
  .times(5)
  .dedup()
  .values('name')
```

### Limit early for performance

```groovy
// ❌ Slow: traverses everything, then limits
g.V().hasLabel('Person').out('KNOWS').out('KNOWS').limit(10)

// ✅ Fast: limits at each step
g.V().hasLabel('Person').limit(100).out('KNOWS').limit(100).out('KNOWS').limit(10)
```

## openCypher

Neptune supports openCypher at the `/openCypher` endpoint.

```python
import urllib.parse
import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

# IAM auth (SigV4) is REQUIRED for production Neptune clusters — an unsigned
# request returns 403 when IAM auth is enabled. See connectivity.md.
def run_opencypher(query: str, endpoint: str, region: str):
    url = f"https://{endpoint}:8182/openCypher"
    body = urllib.parse.urlencode({"query": query})
    creds = boto3.Session().get_credentials().get_frozen_credentials()
    req = AWSRequest(method="POST", url=url, data=body,
                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    SigV4Auth(creds, "neptune-db", region).add_auth(req)
    response = requests.post(url, data=body, headers=dict(req.headers))
    response.raise_for_status()
    return response.json()

# Common patterns
queries = {
    "find_node": "MATCH (p:Person {name: 'Alice'}) RETURN p",
    "traverse": "MATCH (p:Person {name: 'Alice'})-[:KNOWS]->(friend) RETURN friend.name",
    "two_hop": """
        MATCH (p:Person {name: 'Alice'})-[:KNOWS]->(friend)-[:KNOWS]->(fof)
        WHERE fof <> p
        RETURN DISTINCT fof.name
    """,
    "create_edge": """
        MATCH (a:Person {name: 'Alice'}), (b:Person {name: 'Bob'})
        CREATE (a)-[:KNOWS {since: '2024-01-01'}]->(b)
    """
}
```

⚠️ Neptune openCypher does **not** support all Neo4j Cypher features:

- No `apoc` procedures
- No full-text index integration via Cypher
- `WITH` clause has limitations
- **Neptune Analytics silently drops label predicates inside `CASE` / `WHEN`.** Patterns like `CASE WHEN n:PhoneNumber THEN 'phone' WHEN n:Email THEN 'email' END` parse and run without error, but every branch evaluates to null — so downstream aggregations return 0 rows against a graph that actually matches. Use `labels(n)[0]` (returns the first label as a string) or a count-based aggregation:

  ```cypher
  // ❌ Silent fail on Neptune Analytics — returns 0 rows against a seeded graph
  MATCH (a1:Account)-[:USES]->(shared)<-[:USES]-(a2:Account)
  WHERE a1.id < a2.id
  WITH a1, a2, collect(DISTINCT CASE
      WHEN shared:PhoneNumber THEN 'phone'
      WHEN shared:Email THEN 'email'
    END) AS types
  WHERE size(types) >= 2
  RETURN a1.id, a2.id, types

  // ✅ Use labels(shared)[0] — returns the label as a string, aggregates correctly
  MATCH (a1:Account)-[:USES]->(shared)<-[:USES]-(a2:Account)
  WHERE a1.id < a2.id
  WITH a1, a2, collect(DISTINCT labels(shared)[0]) AS types
  WHERE size(types) >= 2
  RETURN a1.id, a2.id, types
  ```

`CALL { }` subqueries **are** supported (read-only; previously listed as incompatible in older migration guides).

## SPARQL (RDF graphs)

```python
import urllib.parse
import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

# IAM auth (SigV4) is REQUIRED for production clusters; see connectivity.md.
def run_sparql(query: str, endpoint: str, region: str):
    url = f"https://{endpoint}:8182/sparql"
    body = urllib.parse.urlencode({"query": query})
    creds = boto3.Session().get_credentials().get_frozen_credentials()
    req = AWSRequest(method="POST", url=url, data=body,
                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    SigV4Auth(creds, "neptune-db", region).add_auth(req)
    response = requests.post(url, data=body, headers=dict(req.headers))
    response.raise_for_status()
    return response.json()

# Example: find all people Alice knows
sparql_query = """
PREFIX : <http://example.org/>
SELECT ?friend ?name WHERE {
    :Alice :knows ?friend .
    ?friend :name ?name .
}
"""
```

## Choosing Gremlin vs. openCypher for a task

| Situation | Use |
|---|---|
| Team knows Cypher from Neo4j | openCypher |
| Complex graph algorithms, repeat/until loops | Gremlin |
| Path analysis with detailed step tracking | Gremlin |
| Simple CRUD on property graph | Either |
| New project, no prior graph experience | Gremlin (more Neptune examples) |

## Common Mistakes

1. **No pagination** — large result sets silently truncate. Always paginate.
2. **Late `limit()`** — placing limit at end still traverses everything first.
3. **Missing `dedup()`** — multi-hop traversals produce duplicates without it.
4. **Using `ws://` instead of `wss://`** — Neptune requires SSL.
5. **Assuming full Cypher support** — Neptune openCypher is a subset of Neo4j.

## Additional Resources

- AWS docs: "Neptune Gremlin implementation", "Neptune openCypher reference"
- Related sub-skills: `performance` (optimization), `troubleshooting` (query errors)
- TinkerPop reference: tinkerpop.apache.org/docs/current/reference/
