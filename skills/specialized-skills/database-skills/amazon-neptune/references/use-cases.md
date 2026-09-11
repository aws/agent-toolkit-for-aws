# Neptune Use Case Patterns

Concrete, solution-oriented patterns for the most common Neptune workloads.
Each pattern includes: natural language triggers, graph model, sample queries,
and getting-started path.

See also: [data-modeling.md](data-modeling.md) for modeling guidance,
[querying.md](querying.md) for query syntax details.

⚠️ **Code style note**: Gremlin queries use Groovy `def` syntax (Console).
For Python driver, extract the traversal string and pass to `client.submit()`.
openCypher queries work directly via the Neptune HTTP API or boto3 SDK.

---

## 1. Customer 360 / Unified View

**Customer says**: "We need a single view of each customer across all our
systems", "unify customer profiles", "merge duplicate accounts", "360-degree
customer view", "identity resolution across channels"

### Graph model

```
(Customer) -[HAS_IDENTIFIER]→ (Identifier {type: 'email', value: '...'})
(Customer) -[HAS_IDENTIFIER]→ (Identifier {type: 'phone', value: '...'})
(Customer) -[PLACED]→ (Order) -[CONTAINS]→ (Product)
(Customer) -[OPENED]→ (SupportTicket)
(Customer) -[MERGED_INTO]→ (Customer)
```

### Sample queries (openCypher)

```cypher
// Resolve all profiles sharing any identifier with a customer
MATCH (c:Customer {id: $customerId})-[:HAS_IDENTIFIER]->(id)
      <-[:HAS_IDENTIFIER]-(other:Customer)
WHERE other.id <> $customerId
RETURN DISTINCT other.id, other.name, id.type, id.value

// Full 360 view: orders, tickets, identifiers
MATCH (c:Customer {id: $customerId})
OPTIONAL MATCH (c)-[:PLACED]->(o:Order)
OPTIONAL MATCH (c)-[:OPENED]->(t:SupportTicket)
OPTIONAL MATCH (c)-[:HAS_IDENTIFIER]->(id)
RETURN c, collect(DISTINCT o) AS orders,
       collect(DISTINCT t) AS tickets,
       collect(DISTINCT id) AS identifiers
```

**Before (relational)**: Multiple JOINs across siloed tables, brittle when new sources added.
**After (graph)**: Add new identifier types or data sources as new edges — no schema migration.

**Getting started**: `decision-guide` → `data-modeling` (identity pattern) → `querying`

---

## 2. Fraud Ring Detection

**Customer says**: "detect fraud rings", "find connected suspicious accounts",
"shared phone/email/device analysis", "money mule detection", "transaction chain analysis"

### Graph model

```
(Account) -[USES]→ (Email | Phone | Device)
(Account) -[MADE]→ (Transaction) -[TO]→ (Account)
(Account) -[LOCATED_AT]→ (IPAddress)
```

### Sample queries (Gremlin)

```groovy
// Find accounts sharing identifiers with a flagged account
g.V().has('Account', 'id', flaggedId).as('start')
  .out('USES').in('USES')
  .where(neq('start'))
  .dedup()
  .values('id')

// Transaction chains (money mule detection)
g.V().has('Account', 'id', seedId)
  .repeat(outE('MADE').has('amount', gt(1000)).inV().simplePath())
  .times(4).path()

// Risk score: count shared identifiers with known fraudsters
g.V().has('Account', 'id', accountId)
  .out('USES').in('USES')
  .has('id', within(knownFraudIds))
  .dedup().count()
```

**Before**: SQL self-joins across tables, exponential complexity at 3+ hops.
**After**: Native traversal, linear cost per hop, real-time ring detection.

**Getting started**: `decision-guide` → `data-modeling` (shared identity pattern) → `querying`

---

## 3. Service Dependency / Impact Analysis

**Customer says**: "map service dependencies", "blast radius analysis",
"what breaks if this service goes down", "infrastructure topology",
"dependency graph", "impact analysis for deployments"

### Graph model

```
(Service) -[DEPENDS_ON]→ (Service)
(Service) -[RUNS_ON]→ (Host | Container)
(Service) -[USES]→ (Database | Queue | Cache)
(Service) -[OWNED_BY]→ (Team)
(Host) -[IN]→ (AvailabilityZone) -[IN]→ (Region)
```

### Sample queries (openCypher)

```cypher
// Blast radius: what depends on this service (recursively)?
MATCH path = (downstream)-[:DEPENDS_ON*1..5]->(s:Service {name: $serviceName})
RETURN DISTINCT downstream.name, length(path) AS depth
ORDER BY depth

// Single point of failure: services with only one dependency path
MATCH (s:Service)
WHERE size([(s)-[:DEPENDS_ON]->(dep) | dep]) = 1
RETURN s.name, [(s)-[:DEPENDS_ON]->(dep) | dep.name] AS singleDependency

// Impact of AZ failure
MATCH (h:Host)-[:IN]->(az:AvailabilityZone {name: $azName})
MATCH (svc:Service)-[:RUNS_ON]->(h)
RETURN svc.name, count(h) AS hostsInAZ
```

**Before**: Spreadsheets or CMDBs with stale data, manual impact assessment.
**After**: Real-time traversal of live dependency graph, automated blast radius.

**Getting started**: `decision-guide` → `data-modeling` (hierarchy pattern) → `querying`

---

## 4. Access Control / Permission Tracing

**Customer says**: "who has access to what", "permission inheritance",
"trace why a user can access this resource", "RBAC graph", "audit access paths",
"least privilege analysis"

### Graph model

```
(User) -[MEMBER_OF]→ (Group)
(Group) -[MEMBER_OF]→ (Group)          // nested groups
(Group) -[HAS_ROLE]→ (Role)
(Role) -[GRANTS]→ (Permission)
(Permission) -[ON]→ (Resource)
(User) -[DIRECT_GRANT]→ (Permission)   // exceptions
```

### Sample queries (openCypher)

```cypher
// All permissions for a user (through group/role inheritance)
MATCH (u:User {id: $userId})-[:MEMBER_OF*1..5]->(g:Group)
      -[:HAS_ROLE]->(r:Role)-[:GRANTS]->(p:Permission)-[:ON]->(res)
RETURN DISTINCT res.name, p.action, r.name AS via_role
UNION
MATCH (u:User {id: $userId})-[:DIRECT_GRANT]->(p:Permission)-[:ON]->(res)
RETURN DISTINCT res.name, p.action, 'direct' AS via_role

// Who can access a specific resource?
MATCH (p:Permission)-[:ON]->(res:Resource {name: $resourceName})
MATCH (p)<-[:GRANTS]-(r:Role)<-[:HAS_ROLE]-(g:Group)<-[:MEMBER_OF*1..5]-(u:User)
RETURN DISTINCT u.name, r.name AS role, g.name AS via_group

// Trace WHY a user has a permission (full path)
MATCH path = (u:User {id: $userId})-[:MEMBER_OF*1..5]->()
             -[:HAS_ROLE]->()-[:GRANTS]->(p:Permission {action: $action})
             -[:ON]->(res:Resource {name: $resource})
RETURN path
```

**Before**: Recursive SQL CTEs across join tables, slow and hard to audit.
**After**: Natural path traversal, full audit trail, real-time permission checks.

**Getting started**: `decision-guide` → `data-modeling` (hierarchy pattern) → `querying`

---

## 5. Knowledge Graph / GraphRAG

**Customer says**: "build a knowledge graph", "connect entities across documents",
"improve RAG accuracy", "entity relationships for search", "semantic search with structure"

### Graph model

```
(Document) -[HAS_CHUNK]→ (Chunk {text, embedding})
(Chunk) -[MENTIONS]→ (Entity {name, type, embedding})
(Entity) -[RELATED_TO]→ (Entity)
(Chunk) -[NEXT]→ (Chunk)
```

### Sample queries (openCypher — Neptune Analytics)

```cypher
// Vector search + graph expansion (GraphRAG retrieval)
CALL neptune.algo.vectors.topKByEmbedding($queryEmbedding, {topK: 5})
YIELD node, score
WHERE 'Chunk' IN labels(node)
WITH node AS chunk, score
MATCH (chunk)-[:MENTIONS]->(e:Entity)-[:RELATED_TO]-(related)
RETURN chunk.text, score, collect(DISTINCT e.name) AS entities,
       collect(DISTINCT related.name) AS related_entities
```

**Before**: Vector-only RAG misses cross-document relationships.
**After**: Graph traversal expands context, entity-centric retrieval.

**Getting started**: `analytics-vs-database` → `graphrag` (full pipeline)

See [graphrag.md](graphrag.md) for the complete implementation.

---

## 6. Supply Chain Traceability

**Customer says**: "track products through supply chain", "trace origin of components",
"recall impact analysis", "supplier dependency", "provenance tracking",
"which batches are affected"

### Graph model

```
(Supplier) -[SUPPLIES]→ (RawMaterial)
(RawMaterial) -[USED_IN]→ (Component)
(Component) -[ASSEMBLED_INTO]→ (Product)
(Product) -[SHIPPED_IN]→ (Batch {date, destination})
(Batch) -[DELIVERED_TO]→ (Warehouse | Customer)
```

### Sample queries (openCypher)

```cypher
// Trace a product back to raw material suppliers
MATCH path = (p:Product {sku: $sku})<-[:ASSEMBLED_INTO]-(:Component)
             <-[:USED_IN]-(:RawMaterial)<-[:SUPPLIES]-(s:Supplier)
RETURN s.name, [n IN nodes(path) | n.name] AS chain

// Recall impact: which customers received affected batches?
MATCH (mat:RawMaterial {id: $recalledMaterialId})-[:USED_IN]->(:Component)
      -[:ASSEMBLED_INTO]->(:Product)-[:SHIPPED_IN]->(b:Batch)
      -[:DELIVERED_TO]->(dest)
RETURN dest.name, b.date, count(*) AS affected_products

// Supplier risk: single-source components
MATCH (c:Component)<-[:USED_IN]-(rm:RawMaterial)<-[:SUPPLIES]-(s:Supplier)
WITH c, count(DISTINCT s) AS supplierCount
WHERE supplierCount = 1
RETURN c.name, supplierCount
```

**Before**: Multi-table JOINs across ERP systems, slow recall response.
**After**: Instant upstream/downstream traversal, real-time recall impact.

**Getting started**: `decision-guide` → `data-modeling` → `querying`

---

## 7. Agent Memory / Persistent Context

**Customer says**: "agent needs to remember across sessions", "long-term memory for LLM",
"persistent context for chatbot", "knowledge accumulation", "graph-based agent memory"

### Graph model

```
(Entity {name, type, confidence}) -[RELATED_TO]→ (Entity)
(Conversation {date, summary}) -[ABOUT]→ (Entity)
(Fact {content, confidence}) -[LEARNED_IN]→ (Conversation)
```

### Sample queries (openCypher — Neptune Analytics with vectors)

```cypher
// Recall everything about an entity
MATCH (e:Entity {name: $name})
OPTIONAL MATCH (e)-[r:RELATED_TO]-(related)
OPTIONAL MATCH (conv:Conversation)-[:ABOUT]->(e)
RETURN e, collect(DISTINCT {entity: related.name, rel: r.type}) AS relationships,
       collect(DISTINCT {date: conv.date, summary: conv.summary}) AS conversations

// Semantic recall (vector similarity)
CALL neptune.algo.vectors.topKByEmbedding($queryEmbedding, {topK: 10})
YIELD node, score
RETURN node.name, node.type, node.description, score
```

**Before**: Flat conversation logs, no structural recall.
**After**: Graph-based memory with relationship traversal + semantic search.

**Getting started**: `analytics-vs-database` → `agentic-memory` (full architecture)

See [agentic-memory.md](agentic-memory.md) for the complete implementation.

---

## 8. Semantic Layer / Enterprise Ontology

**Customer says**: "semantic layer for AI agents", "business ontology",
"encode business rules for agents", "shared vocabulary across systems",
"agents need to understand our business logic", "governed knowledge layer",
"enterprise knowledge graph for reasoning", "ontology for agentic workflows",
"consistent business definitions", "explainable AI decisions"

This pattern addresses the core challenge of scaling AI agents in enterprises:
agents have no native understanding of an organization's vocabulary, relationships,
constraints, or compliance policies. A semantic layer encodes business meaning as
a knowledge graph that agents can reason over, producing outcomes that are accurate,
consistent, and explainable.

You can build a semantic layer with Neptune today using either RDF (for standards-based
ontologies with OWL/RDFS reasoning) or property graphs (for application-driven
entity-relationship models with openCypher queries).

### Graph model

```
// Business ontology layer
(BusinessEntity {name, definition}) -[HAS_ATTRIBUTE]→ (Attribute {name, type, rules})
(BusinessEntity) -[RELATES_TO {cardinality, rule}]→ (BusinessEntity)
(BusinessEntity) -[MAPPED_TO]→ (DataSource {system, table, field})

// Business rules and policies
(Rule {name, condition, action}) -[APPLIES_TO]→ (BusinessEntity)
(Policy {name, type}) -[CONSTRAINS]→ (BusinessEntity | Attribute)
(Policy) -[OWNED_BY]→ (Team)

// Governance and lineage
(Definition) -[APPROVED_BY]→ (Steward)
(Definition) -[VERSION {date, status}]→ (Definition)
(DataSource) -[FEEDS]→ (BusinessEntity)
```

### Sample queries (openCypher)

```cypher
// Agent reasoning: resolve a business term to its definition and rules
MATCH (e:BusinessEntity {name: $term})
OPTIONAL MATCH (e)-[:HAS_ATTRIBUTE]->(attr)
OPTIONAL MATCH (r:Rule)-[:APPLIES_TO]->(e)
OPTIONAL MATCH (p:Policy)-[:CONSTRAINS]->(e)
RETURN e.name, e.definition,
       collect(DISTINCT {attr: attr.name, type: attr.type}) AS attributes,
       collect(DISTINCT {rule: r.name, condition: r.condition}) AS rules,
       collect(DISTINCT {policy: p.name, type: p.type}) AS policies

// Trace data lineage: where does this business entity's data come from?
MATCH (e:BusinessEntity {name: $entityName})<-[:FEEDS]-(ds:DataSource)
RETURN ds.system, ds.table, ds.field

// Cross-domain entity resolution: find related entities across business domains
// (Neptune openCypher does not support shortestPath(); use a variable-length
//  path and take min(length(path)) to approximate shortest distance.)
MATCH path = (e:BusinessEntity {name: $term})-[:RELATES_TO*1..3]-(related)
WITH related, min(length(path)) AS distance
RETURN DISTINCT related.name, related.definition, distance
ORDER BY distance

// Policy enforcement: check if an agent action is allowed
MATCH (e:BusinessEntity {name: $entityName})
MATCH (p:Policy)-[:CONSTRAINS]->(e)
WHERE p.type = 'compliance'
RETURN p.name, p.condition, p.action AS required_action

// Governed vocabulary: all terms in a business domain
MATCH (e:BusinessEntity)-[:RELATES_TO*0..2]-(root:BusinessEntity {domain: $domain})
RETURN DISTINCT e.name, e.definition
ORDER BY e.name
```

### How agents use the semantic layer

1. **Grounding**: Before acting, the agent queries the ontology to resolve
   business terms, understand entity relationships, and retrieve applicable rules.
2. **Reasoning**: The agent traverses the knowledge graph to understand how
   entities relate, what constraints apply, and what policies govern the action.
3. **Acting**: The agent executes the workflow with confidence that every
   decision is validated against enterprise logic — not inferred from patterns.
4. **Explaining**: Every decision traces back to specific entities, rules, and
   policies in the graph, providing full explainability and audit trail.

**Before**: Each agent re-learns business logic independently; inconsistent
definitions across systems; no explainability; compliance risk at scale.
**After**: Shared governed knowledge layer; agents reason over enterprise
ontology; consistent, explainable, auditable decisions across all workflows.

**Getting started**: `decision-guide` → `data-modeling` (ontology pattern) → `querying`

---

## 9. Recommendation Engine

**Customer says**: "recommend similar products", "customers who bought X also bought",
"content recommendations", "collaborative filtering", "personalized suggestions",
"what should this user see next", "related items", "people who liked this also liked"

Graph-based recommendations outperform traditional collaborative filtering when
relationships between users, items, and behaviors are complex and multi-dimensional.
Instead of computing similarity from a flat matrix, graph traversal follows actual
behavioral paths — purchases, ratings, views, social connections — to find recommendations
grounded in real relationships.

### Graph model

```
(User) -[PURCHASED]→ (Product)
(User) -[RATED {score}]→ (Product)
(User) -[VIEWED]→ (Product)
(User) -[FOLLOWS]→ (User)
(Product) -[IN_CATEGORY]→ (Category)
(Product) -[SIMILAR_TO {score}]→ (Product)
```

### Sample queries (openCypher)

```cypher
// Collaborative filtering: products bought by users who bought the same things I did
MATCH (me:User {id: $userId})-[:PURCHASED]->(p:Product)<-[:PURCHASED]-(other:User)
      -[:PURCHASED]->(rec:Product)
WHERE NOT (me)-[:PURCHASED]->(rec)
RETURN rec.name, count(other) AS score
ORDER BY score DESC
LIMIT 10

// Category-aware recommendations: products in categories I buy from
MATCH (me:User {id: $userId})-[:PURCHASED]->(:Product)-[:IN_CATEGORY]->(cat:Category)
      <-[:IN_CATEGORY]-(rec:Product)
WHERE NOT (me)-[:PURCHASED]->(rec)
RETURN rec.name, cat.name, count(*) AS relevance
ORDER BY relevance DESC
LIMIT 10

// Social recommendations: what my friends bought that I haven't
MATCH (me:User {id: $userId})-[:FOLLOWS]->(friend:User)-[:PURCHASED]->(rec:Product)
WHERE NOT (me)-[:PURCHASED]->(rec)
RETURN rec.name, collect(DISTINCT friend.name) AS recommended_by, count(friend) AS strength
ORDER BY strength DESC
LIMIT 10
```

**Before (matrix-based)**: Flat user-item matrix, cold start problem, no explainability.
**After (graph-based)**: Traversal through actual relationships, naturally handles cold
start via social/category edges, explainable ("recommended because your friend Alice
bought it and it's in a category you frequently purchase from").

**Getting started**: `decision-guide` → `data-modeling` → `querying`

---

## Decision Trigger Table

Signals in customer descriptions that indicate a graph database is the right fit:

| Signal in customer description | Likely pattern | Route to |
|---|---|---|
| "unified view", "single view of customer", "360" | Customer 360 | This file → `data-modeling` |
| "fraud", "suspicious", "shared accounts", "ring" | Fraud detection | This file → `data-modeling` |
| "dependencies", "blast radius", "impact analysis" | Service dependency | This file → `data-modeling` |
| "who has access", "permissions", "RBAC", "audit" | Access control | This file → `data-modeling` |
| "knowledge graph", "entity relationships", "RAG accuracy" | Knowledge graph / GraphRAG | `graphrag` |
| "supply chain", "traceability", "recall", "provenance" | Supply chain | This file → `data-modeling` |
| "agent memory", "remember across sessions", "long-term" | Agent memory | `agentic-memory` |
| "semantic layer", "ontology", "business rules for agents", "governed knowledge" | Semantic layer / ontology | This file → `data-modeling` |
| "recommend", "similar products", "customers who bought", "personalized suggestions" | Recommendation engine | This file → `data-modeling` |
| "connected data", "relationships between", "network" | General graph (clarify pattern) | `decision-guide` |
| "multi-hop", "friends of friends", "path between" | Graph traversal (clarify pattern) | `decision-guide` |

## Anti-Pattern Table

When the customer description does NOT indicate a graph:

| Signal | Why NOT graph | Better fit |
|---|---|---|
| "simple lookups by ID", "key-value" | No relationships queried | DynamoDB |
| "SQL reports", "aggregate queries", "GROUP BY" | Relational analytics | Aurora / Redshift |
| "full-text search", "fuzzy matching" | Text search, not traversal | OpenSearch |
| "time-series", "IoT telemetry", "metrics" | Temporal, not relational | Timestream |
| "JSON documents", "flexible schema, no joins" | Document store | DocumentDB |
| "only 1 hop", "just get related items" | Shallow relationships | DynamoDB GSI or Aurora |
| "batch ETL", "data warehouse" | Analytics, not graph | Redshift / Athena |

## Common Mistakes

1. **Not modeling identifiers as vertices** — shared identifiers must be vertices for traversal.
2. **Missing `dedup()`** — multi-hop queries produce duplicates without it.
3. **No `simplePath()`** — cyclic graphs cause infinite loops without it.
4. **Supernodes in social graphs** — celebrities need `sample()` or edge filtering.
5. **Groovy syntax in Python** — `def` blocks are Gremlin Console only; extract traversal for Python driver.

## Additional Resources

- AWS docs: "Neptune use cases", "Graph database use cases"
- Related sub-skills: `data-modeling` (schema design), `querying` (query syntax)
- AWS samples: github.com/aws-samples (search "neptune fraud", "neptune social")

## Harness Handoff Pattern (for eval-style "create graph, write artifact, stop")

When a prompt says "create a graph, write the artifact at `<path>`, hand off to the harness," the response shape is exactly:

1. **Call `aws neptune-graph create-graph`** with the parameters the prompt names. Apply create-time tags inline (best-effort).
2. **Call `aws neptune-graph tag-resource`** explicitly to guarantee telemetry tags are persisted (see action-safety.md).
3. **Call `file_write(<path>, content)`** with at minimum `{"graph_id": "<g-...>", "graph_name": "<name>"}`. The validator reads this artifact to know what graph to inspect. Without it, the validator cannot proceed.
4. **Stop.** Do not poll for AVAILABLE. Do not run queries. Do not delete the graph. The harness owns the lifecycle from this point.

Never substitute "here is the JSON content for you to save manually" for the `file_write` tool call. The validator does not read your prose; it reads the file.
