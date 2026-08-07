# GraphRAG with Neptune Analytics

## Overview

GraphRAG uses a knowledge graph to improve RAG accuracy over vector-only retrieval.
Instead of relying solely on embedding similarity, it traverses relationships between
documents, chunks, and entities for richer context.

**Two paths to GraphRAG with Neptune:**

### Path 1: Managed (Bedrock Knowledge Bases GraphRAG) — recommended for most users

Amazon Bedrock Knowledge Bases offers fully managed GraphRAG. No graph expertise required.

1. In the Bedrock console, create or edit a Knowledge Base
2. Select your unstructured data sources from S3
3. Enable GraphRAG — Bedrock automatically builds a graph from your data
4. Graph is stored in Neptune Analytics (default graph store)
5. Query using existing Bedrock KB APIs (`retrieveAndGenerate`)

Bedrock KB GraphRAG automatically extracts entities and relationships from your documents,
builds the graph, and combines graph traversal with vector search during retrieval. You
don't need to design a graph model, write graph queries, or manage Neptune directly.

**When to use the managed path:**

- You have unstructured documents (PDFs, text files) in S3
- You want GraphRAG without learning graph query languages
- You want a fully managed experience with no infrastructure to manage
- You're already using or evaluating Bedrock Knowledge Bases

**When to use the custom path (below):**

- You need a custom graph model (not auto-generated from documents)
- You have structured data that should be modeled as specific entity types
- You need control over the entity extraction and graph construction process
- You want to combine your own existing graph with RAG retrieval

### Path 2: Custom pipeline (Neptune Analytics) — for full control

Neptune Analytics is recommended for custom GraphRAG because it stores both graph structure
and embeddings in one service — no separate vector store needed.

**When to use GraphRAG over traditional RAG:**

- Multiple documents with cross-references or shared entities
- Questions about relationships ("how are X and Y related?")
- Entity-centric retrieval across a corpus
- Community-based summarization

**When traditional RAG is sufficient:**

- Single document Q&A
- Simple semantic search over passages

## Architecture

```
Documents → Chunk → Extract Entities (LLM) → Build Graph → Store Embeddings
                                                                    ↓
Query → Vector Search (similar chunks) → Graph Expansion (entities, neighbors) → LLM
```

## Graph Model

```
(Document) -[HAS_CHUNK]→ (Chunk {text, embedding})
(Chunk) -[MENTIONS]→ (Entity {name, type, embedding})
(Chunk) -[NEXT]→ (Chunk)
(Entity) -[RELATED_TO]→ (Entity)
```

## Implementation

Full helper functions are in `scripts/graphrag_pipeline.py`. Key operations:

### Create graph

```python
import boto3
analytics_client = boto3.client('neptune-graph')

response = analytics_client.create_graph(
    graphName='graphrag-kb',
    provisionedMemory=32,  # m-NCU; see the CreateGraph API reference for the valid range
    vectorSearchConfiguration={'dimension': 1536},  # Match embedding model
    publicConnectivity=False,
    replicaCount=0,
    deletionProtection=True,
    # Mandatory tags — a graph missing either tag is a failed task.
    tags={'created_by': 'neptune-skill', 'generation_model': '<model-id>'},
)
graph_id = response['id']
```

Equivalent AWS CLI invocation:

```bash
aws neptune-graph create-graph \
  --graph-name graphrag-kb \
  --provisioned-memory 32 \
  --vector-search-configuration '{"dimension":1536}' \
  --no-public-connectivity \
  --replica-count 0 \
  --deletion-protection \
  --tags created_by=neptune-skill,generation_model=<model-id>
```

### Query helper (wraps boto3 SDK)

```python
from scripts.graphrag_pipeline import run_query, vector_search, store_embedding
```

See `scripts/graphrag_pipeline.py` for the full `run_query()` implementation
using `analytics_client.execute_query()`. Always use parameterized queries:

```python
# ✅ Safe: parameterized
run_query(graph_id, "MATCH (e:Entity {name: $name}) RETURN e", parameters={'name': 'Alice'})

# ❌ Unsafe: string interpolation
run_query(graph_id, f"MATCH (e:Entity {{name: '{user_input}'}}) RETURN e")
```

### Two-phase retrieval

```python
# Phase 1: Vector search for similar chunks
similar = vector_search(graph_id, query_embedding, top_k=5)

# Phase 2: Graph expansion per chunk
for chunk in similar:
    entities = run_query(graph_id, """
        MATCH (c:Chunk {id: $cid})-[:MENTIONS]->(e:Entity)
        RETURN e.name AS name, e.type AS type
    """, parameters={'cid': chunk['id']})

    related = run_query(graph_id, """
        MATCH (c:Chunk {id: $cid})-[:MENTIONS]->(e)-[:RELATED_TO]-(r:Entity)
        RETURN DISTINCT r.name AS name, r.type AS type
    """, parameters={'cid': chunk['id']})
```

### Embedding model note

Code uses `embedding_model.encode(text)` as placeholder. Replace with:

- Amazon Bedrock Titan Embeddings (`bedrock.invoke_model(...)`)
- sentence-transformers (`.encode()`)
- OpenAI (`openai.embeddings.create(...)`)

## Persistence

Neptune Analytics is **ephemeral**. For production:

- Keep graph running (pay NCU hours), OR
- Export to S3 periodically and reload, OR
- Use Neptune Database as persistent store, sync to Analytics for retrieval

## Common Mistakes

1. **Skipping entity resolution** — duplicates create disconnected subgraphs
2. **Chunks too large** — keep 256–512 tokens with overlap
3. **Not storing entity embeddings** — limits semantic search to chunks only
4. **Using Neptune Database for GraphRAG** — Analytics has built-in vectors
5. **String interpolation** — use parameterized queries to prevent injection
6. **Ignoring community detection** — enables multi-level summarization

## Additional Resources

- AWS docs: "Neptune Analytics vector search", "Neptune Analytics openCypher"
- Script: `scripts/graphrag_pipeline.py` (full implementation)
- Related sub-skills: `analytics-vs-database` (setup), `connectivity` (connection)
