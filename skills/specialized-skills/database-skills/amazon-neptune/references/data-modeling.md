# Neptune Data Modeling

Graph data modeling is fundamentally different from relational modeling.
The most common mistake agents make is modeling a graph like a relational
table — normalizing everything into entities with foreign keys.

## Core principle: model for traversal

In a graph database, **the query pattern drives the model**. Ask first:
"What relationships will I traverse?" Then model edges to support those traversals.

## Property graph concepts

```
Vertex (node): An entity with a label and properties
  Example: vertex with label "Person", properties {name: "Alice", age: 30}

Edge: A directed relationship between two vertices, with a label and properties
  Example: edge with label "PURCHASED", properties {date: "2024-01-15", amount: 99.99}
         from vertex "Person:Alice" to vertex "Product:Widget"
```

## Modeling patterns

### Pattern 1: Entity-relationship as graph

Relational model:

```
customers(id, name) — orders(id, customer_id, date) — products(id, name)
```

Graph model:

```
(Customer {name:"Alice"}) -[PLACED {date:"2024-01-15"}]-> (Order {id:"O1"})
(Order {id:"O1"}) -[CONTAINS {qty:2}]-> (Product {name:"Widget"})
```

The graph model enables: "Find all products bought by Alice's friends"
in a single traversal. The relational model requires multiple joins.

### Pattern 2: Time-based edges

Add temporal properties to edges rather than creating time-based vertices:

```groovy
// Good: date on edge
g.addE('PURCHASED').from(customer).to(product)
  .property('date', '2024-01-15')
  .property('amount', 99.99)

// Avoid: intermediate time vertex (adds traversal hops without benefit)
// customer -[ON]-> Date -[PURCHASED]-> product
```

### Pattern 3: Shared identity (fraud detection)

Model shared identifiers (email, phone, device) as vertices, entities as
edges to those identifiers:

```
(Account:A1) -[USES]-> (Email:alice@example.com) <-[USES]- (Account:A2)
(Account:A1) -[USES]-> (Device:iPhone-XYZ) <-[USES]- (Account:A3)
```

Query: find all accounts sharing identifiers with a flagged account:

```groovy
g.V().has('Account', 'id', 'A1')
  .out('USES').in('USES')
  .dedup()
  .values('id')
```

### Pattern 4: Hierarchies and trees

```
(Category:Electronics) -[PARENT_OF]-> (Category:Phones)
                       -[PARENT_OF]-> (Category:Laptops)
(Category:Phones)      -[PARENT_OF]-> (Category:Smartphones)
```

Query full path from root:

```groovy
g.V().has('Category', 'name', 'Smartphones')
  .repeat(__.in('PARENT_OF'))
  .until(__.inE('PARENT_OF').count().is(0))
  .path()
```

## Anti-patterns to avoid

### ❌ Supernode: vertex with millions of edges

```
// Bad: one "USA" vertex connected to every US customer
(Country:USA) <-[LIVES_IN]- (all 10M US customers)
```

Supernodes degrade traversal performance. The vertex becomes a bottleneck.

Fix: denormalize the property onto the customer vertex instead.

```groovy
// Good: filter by property, avoid the hub vertex
g.V().hasLabel('Customer').has('country', 'USA').limit(100)
```

If the hub is unavoidable (e.g., social media influencer with 1M followers),
partition traversals and use `sample()` or `limit()` early.

### ❌ Modeling relationships as properties

```
// Bad: storing connections as a list property
vertex: {friends: ["Bob", "Carol", "Dave"]}
```

This forces application-side joins and makes traversal impossible in Neptune.
Model connections as edges.

### ❌ Deep nesting with unnecessary intermediate vertices

Every extra hop adds latency. Only create intermediate vertices when the
intermediate entity has its own properties or relationships you'll query.

## RDF / SPARQL modeling

RDF models data as triples: `subject predicate object`

```turtle
:Alice rdf:type :Person .
:Alice :name "Alice" .
:Alice :knows :Bob .
:Alice :worksFor :AcmeCorp .
```

Use RDF when:

- Your ontology integrates with external vocabularies (FOAF, Schema.org)
- You need OWL reasoning (inferring new facts from rules)
- Data exchange between systems using W3C standards matters

For application backends, property graph is almost always simpler.

## Neptune schema on read

Neptune is **schema-free**. There is no DDL. Vertex labels, edge labels, and
property keys are defined by your first write. This is flexible but requires
discipline:

- Document your vertex labels, edge labels, and required properties
- Enforce schema constraints in your application layer
- Use a consistent naming convention (PascalCase for labels, camelCase for properties)

## Common Mistakes

1. **Modeling like relational** — graph models optimize for traversal, not normalization.
2. **Supernodes** — avoid hub vertices with millions of edges; denormalize instead.
3. **Relationships as properties** — list properties prevent traversal; use edges.
4. **No naming convention** — use PascalCase labels, camelCase properties consistently.
5. **Unnecessary intermediate vertices** — each hop adds latency.

## Additional Resources

- AWS docs: "Neptune data modeling best practices"
- Related sub-skills: `querying` (query the model), `use-cases` (concrete patterns)
- Book: "Graph Databases" by Robinson, Webber, Eifrem (O'Reilly)
