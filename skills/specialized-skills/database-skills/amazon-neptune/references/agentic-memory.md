# Agentic Memory with Neptune

## Routing: size the answer to the ask

When a user asks about persistent agent memory or chatbot context across sessions, first classify the ask, then pick the layer:

| Ask shape | Primary answer | Why |
|---|---|---|
| **Generic conversation continuity** — "remember what we discussed", last-N messages, session summaries, TTL | **Amazon Bedrock AgentCore Memory** (fully managed) or **DynamoDB with TTL** for a lightweight custom store | These are session/short-term stores; adding Neptune for a simple recall requirement is over-engineering |
| **Relationship-heavy / multi-hop memory** — entity → entity traversal, cross-session facts, GraphRAG over the memory graph | **Amazon Neptune** property-graph memory (User → Conversation → Entity → Fact) | Structured relationships compound over time; graph traversal beats flat logs |
| **Hybrid** — short-term recall + long-term structured memory | **Both**: AgentCore/DynamoDB for last-N and TTL + Neptune for the entity/fact graph | Layered memory stack |

The rest of this document covers the **Neptune property-graph pattern** — how to model, store, and retrieve entity/fact memory when the ask is relationship-heavy or when you need the long-term layer of a hybrid stack. Do not apply this pattern for generic conversation continuity alone.

Complementary layers of the memory stack:

| Service | Role in the stack |
|---|---|
| Bedrock AgentCore Memory | Fully managed short-term + session-summary recall |
| Bedrock Agents `memoryId` | Session summaries within a single agent workflow |
| DynamoDB | Session state store, TTL-based expiry, short-term transcript |
| LangChain `ConversationBufferMemory` | In-process buffer for the in-flight conversation |

## Overview

AI agents need memory to maintain context across interactions:

- **Short-term memory** (session, recent messages) → DynamoDB (TTL auto-expire)
- **Long-term memory** (entities, relationships, knowledge) → Neptune

Neptune excels at long-term memory because agent knowledge is a graph — entities
relate to entities, conversations reference topics, knowledge compounds through connections.

**Neptune Database** — persistent, always-on, millisecond reads. Production agents.
**Neptune Analytics** — built-in vector search (graph + vectors, no separate store). Prototyping or agents needing semantic recall.

**Security:** Agent memory graphs may contain sensitive entity relationships and embedding vectors. Neptune Analytics is always encrypted at rest (AWS-managed or customer-managed KMS key). DynamoDB tables are already encrypted at rest by default (AWS-owned key); for sensitive agent memory, upgrade to KMS-managed encryption (`SSESpecification: {SSEEnabled: true, SSEType: 'KMS'}`) to gain key-rotation control and CloudTrail key-usage logging. Also enable KMS encryption on any CloudWatch Logs groups that store agent-memory data and any SNS topics used for notifications — these can contain sensitive context (entity relationships, embeddings, facts) and must be protected with the same care as the graph itself.

### Neptune MCP Servers for Agent Integration

Neptune provides two MCP (Model Context Protocol) servers that give agents direct
access to Neptune capabilities:

- **Neptune MCP Query Server** — lets agents run openCypher and Gremlin queries against
  Neptune Database and Neptune Analytics, and fetch graph schema. Use this when your agent
  needs to query an existing graph as part of its workflow.
- **Neptune MCP Memory Server** — provides persistent memory to agents, storing knowledge
  graphs against Neptune. Use this when your agent needs to remember entities, relationships,
  and facts across sessions.

These MCP servers integrate with agent frameworks like Strands AI Agents SDK and other
MCP-compatible tools. They complement this skill: the skill provides guidance on *what*
to build, the MCP servers provide runtime tools for agents to *use* what's built.

## Architecture

```
┌─────────────────────────────────────────────┐
│  AI Agent                                   │
│  ┌─────────────┐  ┌──────────────────────┐ │
│  │ Short-Term  │  │ Long-Term Memory     │ │
│  │ (DynamoDB)  │  │ (Neptune)            │ │
│  │ • Session   │  │ • Entity graph       │ │
│  │ • Last N    │  │ • Episodic memory    │ │
│  │ • TTL 24h   │  │ • Vector index (Ana) │ │
│  └─────────────┘  └──────────────────────┘ │
└─────────────────────────────────────────────┘
```

## Graph Model

```
(Entity {name, type, description, confidence, updated_at})
(Conversation {id, user_id, date, summary})
(Fact {content, confidence, created_at})

(Entity) -[RELATED_TO {type, confidence}]→ (Entity)
(Conversation) -[ABOUT]→ (Entity)
(Fact) -[LEARNED_IN]→ (Conversation)
```

## Implementation

Full helpers in `scripts/agentic_memory.py`. Key patterns:

### Short-term (DynamoDB)

```python
from scripts.agentic_memory import store_message, get_recent_messages

store_message(session_id='sess-123', role='user', content='Tell me about Alice')
messages = get_recent_messages(session_id='sess-123', limit=20)
```

### Long-term — Neptune Database (Gremlin, persistent)

```python
from scripts.agentic_memory import (
    get_gremlin_client, remember_entity_gremlin,
    remember_relationship_gremlin, recall_entity_gremlin
)

client = get_gremlin_client()
remember_entity_gremlin(client, 'Alice', 'Person')
remember_relationship_gremlin(client, 'Alice', 'Acme Corp', 'WORKS_AT')
memory = recall_entity_gremlin(client, 'Alice')
```

Uses Gremlin bindings (parameterized) — no string interpolation.

### Long-term — Neptune Analytics (openCypher + vector)

```python
from scripts.agentic_memory import (
    remember_with_embedding, semantic_recall, hybrid_recall
)

# Store with embedding
remember_with_embedding(graph_id, 'Alice', 'Engineer at Acme', embedding_vector)

# Recall by similarity
results = semantic_recall(graph_id, query_embedding, top_k=10)

# Hybrid: graph traversal + vector search
context = hybrid_recall(graph_id, 'Alice', query_embedding)
```

### Memory consolidation

```python
from scripts.agentic_memory import consolidate_memories
consolidate_memories(graph_id)  # Decay old facts, remove low-confidence
```

## Persistence Strategy (Critical for Analytics)

Neptune Analytics is **ephemeral**. For production agents:

| Strategy | Tradeoff |
|---|---|
| Periodic S3 export | Cost-efficient, some data loss risk |
| Dual-write to Neptune Database | Zero loss, higher cost |
| Database as source, sync to Analytics | Best durability |
| Event-sourced (log to DynamoDB/S3) | Full audit trail, rebuild from scratch |

**Recommended**: Neptune Database for persistence + Analytics only if you need vector search.

## Common Mistakes

1. **Storing everything** — use LLM extraction to filter noise
2. **No memory decay** — implement confidence decay + periodic cleanup
3. **Vector-only recall** — graph traversal finds structural connections vectors miss
4. **Separate vector store with Analytics** — Analytics has built-in vectors
5. **No timestamps** — agents need temporal context for relevance
6. **No persistence strategy** — Analytics memory is lost on graph deletion
7. **String interpolation** — use parameterized queries (bindings or `$param`)

## Memory Framework Integrations

Neptune is the graph backend for three major agent memory frameworks. These provide
higher-level abstractions over Neptune for teams that want memory capabilities without
building from scratch:

- **Mem0** — self-improving memory layer for AI agents. Neptune as graph store for
  entity relationships and knowledge accumulation.
- **Cognee** — agentic memory framework. Neptune as graph store for structured
  knowledge that agents build over time.
- **Zep** — long-term interaction history for agents. Neptune as graph store for
  conversation-derived entity relationships.

These frameworks handle entity extraction, relationship management, and memory
consolidation. Use them when you want production-ready agent memory without building
the graph ingestion pipeline yourself. Use the custom implementation (above) when you
need full control over the graph model and memory architecture.

## Additional Resources

- Script: `scripts/agentic_memory.py` (full implementation)
- AWS docs: "Neptune Analytics vector search", "DynamoDB TTL"
- Related sub-skills: `analytics-vs-database` (choosing), `connectivity` (setup)
- Related skills: DynamoDB (short-term memory table design)
