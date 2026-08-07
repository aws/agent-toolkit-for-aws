#!/usr/bin/env python3
"""
Neptune Skill — GraphRAG Pipeline Helpers

Provides the core functions for building and querying a GraphRAG pipeline
with Neptune Analytics. Used by references/graphrag.md.

Usage:
    pip install boto3
    Set GRAPH_ID environment variable to your Neptune Analytics graph ID.
"""

import hashlib
import json
import os
from typing import Any, Dict, List, Optional

import boto3

# Neptune Analytics client
analytics_client = boto3.client("neptune-graph")
GRAPH_ID = os.environ.get("GRAPH_ID", "g-xxxxxxxxxx")


# =============================================================================
# Core SDK Helper
# =============================================================================


def run_query(graph_id: str, query: str, parameters: Optional[Dict[str, Any]] = None) -> List[Dict]:
    """
    Execute an openCypher query against a Neptune Analytics graph.

    Uses boto3 neptune-graph client (not WebSocket, not port 8182).

    Args:
        graph_id: Neptune Analytics graph identifier (e.g., 'g-xxxxxxxxxx')
        query: openCypher query. Use $param_name for parameterized values.
        parameters: Query parameters dict (prevents injection).

    Returns:
        List of result dictionaries.
    """
    import re

    if not re.match(r"^g-[a-z0-9]{10,}$", graph_id):
        raise ValueError(
            f"Invalid graph_id format: {graph_id}. Expected 'g-' followed by lowercase alphanumeric."
        )

    kwargs: Dict[str, Any] = {
        "graphIdentifier": graph_id,
        "queryString": query,
        "language": "OPEN_CYPHER",
    }
    if parameters:
        kwargs["parameters"] = parameters

    response = analytics_client.execute_query(**kwargs)
    payload = json.loads(response["payload"].read())
    return payload.get("results", [])


def escape_cypher_string(value: str) -> str:
    """
    Escape a string for openCypher. Prefer parameterized queries ($param) instead.
    Use only when parameters are not supported (e.g., dynamic label names).
    """
    return value.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')


# =============================================================================
# Graph Creation
# =============================================================================


def create_graphrag_graph(
    graph_name: str,
    memory_gb: int = 32,
    embedding_dimension: int = 1536,
    generation_model: str = "unknown",
) -> str:
    """Create a Neptune Analytics graph with vector search enabled.

    Secure defaults: deletionProtection=True and the mandatory skill tags. See
    the CreateGraph API reference for the valid provisionedMemory range.
    """
    response = analytics_client.create_graph(
        graphName=graph_name,
        provisionedMemory=memory_gb,
        publicConnectivity=False,
        vectorSearchConfiguration={"dimension": embedding_dimension},
        replicaCount=0,
        deletionProtection=True,
        tags={"created_by": "neptune-skill", "generation_model": generation_model},
    )
    return response["id"]


# =============================================================================
# Document Processing
# =============================================================================


def chunk_document(text: str, chunk_size: int = 512, overlap: int = 50) -> List[str]:
    """Split document into overlapping chunks."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


# =============================================================================
# Vector Operations
# =============================================================================


def store_embedding(graph_id: str, vertex_id: str, embedding: List[float]):
    """Store embedding on a vertex in Neptune Analytics."""
    run_query(
        graph_id,
        """
        MATCH (n {id: $vertex_id})
        CALL neptune.algo.vectors.upsert(n, $embedding)
        YIELD node
        RETURN node.id
    """,
        parameters={"vertex_id": vertex_id, "embedding": embedding},
    )


def vector_search(
    graph_id: str, query_embedding: List[float], top_k: int = 5, vertex_label: str = "Chunk"
) -> List[Dict]:
    """Neptune Analytics vector similarity search."""
    return run_query(
        graph_id,
        """
        CALL neptune.algo.vectors.topKByEmbedding($embedding, {topK: $top_k})
        YIELD node, score
        WHERE $label IN labels(node)
        RETURN node.id AS id, node.text AS text, score
        ORDER BY score DESC
    """,
        parameters={"embedding": query_embedding, "top_k": top_k, "label": vertex_label},
    )


# =============================================================================
# Graph Construction
# =============================================================================


def ingest_document(graph_id: str, doc_id: str, title: str, source: str):
    """Create a Document vertex."""
    run_query(
        graph_id,
        """
        CREATE (d:Document {id: $doc_id, title: $title, source: $source})
    """,
        parameters={"doc_id": doc_id, "title": title, "source": source},
    )


def ingest_chunk(
    graph_id: str,
    chunk_id: str,
    doc_id: str,
    text: str,
    sequence: int,
    embedding: List[float],
    prev_chunk_id: Optional[str] = None,
):
    """Create a Chunk vertex, link to document, optionally link to previous chunk."""
    run_query(
        graph_id,
        """
        CREATE (c:Chunk {id: $chunk_id, text: $text, sequence: $seq})
    """,
        parameters={"chunk_id": chunk_id, "text": text, "seq": sequence},
    )

    store_embedding(graph_id, chunk_id, embedding)

    run_query(
        graph_id,
        """
        MATCH (d:Document {id: $doc_id}), (c:Chunk {id: $chunk_id})
        CREATE (d)-[:HAS_CHUNK]->(c)
    """,
        parameters={"doc_id": doc_id, "chunk_id": chunk_id},
    )

    if prev_chunk_id:
        run_query(
            graph_id,
            """
            MATCH (prev:Chunk {id: $prev_id}), (curr:Chunk {id: $curr_id})
            CREATE (prev)-[:NEXT]->(curr)
        """,
            parameters={"prev_id": prev_chunk_id, "curr_id": chunk_id},
        )


def ingest_entity(
    graph_id: str, name: str, entity_type: str, description: str, embedding: List[float]
):
    """Merge an Entity vertex with embedding."""
    entity_id = hashlib.sha256(name.encode()).hexdigest()[:32]
    run_query(
        graph_id,
        """
        MERGE (e:Entity {name: $name})
        ON CREATE SET e.type = $type, e.description = $desc, e.id = $entity_id
    """,
        parameters={"name": name, "type": entity_type, "desc": description, "entity_id": entity_id},
    )
    store_embedding(graph_id, entity_id, embedding)


def link_chunk_entity(graph_id: str, chunk_id: str, entity_name: str):
    """Link a chunk to an entity it mentions."""
    run_query(
        graph_id,
        """
        MATCH (c:Chunk {id: $chunk_id}), (e:Entity {name: $name})
        CREATE (c)-[:MENTIONS]->(e)
    """,
        parameters={"chunk_id": chunk_id, "name": entity_name},
    )


def link_entities(graph_id: str, source: str, target: str, rel_type: str):
    """Create a relationship between two entities."""
    run_query(
        graph_id,
        """
        MATCH (s:Entity {name: $source}), (t:Entity {name: $target})
        MERGE (s)-[:RELATED_TO {type: $rel_type}]->(t)
    """,
        parameters={"source": source, "target": target, "rel_type": rel_type},
    )


# =============================================================================
# Retrieval
# =============================================================================


def graphrag_retrieve(graph_id: str, query_embedding: List[float], top_k: int = 5) -> List[Dict]:
    """
    Two-phase retrieval:
    1. Vector search for similar chunks
    2. Graph traversal to expand context
    """
    similar_chunks = vector_search(graph_id, query_embedding, top_k=top_k)

    expanded_context = []
    for chunk in similar_chunks:
        chunk_id = chunk["id"]

        entities = run_query(
            graph_id,
            """
            MATCH (c:Chunk {id: $cid})-[:MENTIONS]->(e:Entity)
            RETURN e.name AS name, e.type AS type, e.description AS description
        """,
            parameters={"cid": chunk_id},
        )

        related = run_query(
            graph_id,
            """
            MATCH (c:Chunk {id: $cid})-[:MENTIONS]->(e:Entity)-[:RELATED_TO]-(r:Entity)
            RETURN DISTINCT r.name AS name, r.type AS type, r.description AS description
        """,
            parameters={"cid": chunk_id},
        )

        neighbors = run_query(
            graph_id,
            """
            MATCH (c:Chunk {id: $cid})-[:NEXT]-(n:Chunk)
            RETURN n.text AS text, n.id AS id
        """,
            parameters={"cid": chunk_id},
        )

        expanded_context.append(
            {
                "chunk_text": chunk["text"],
                "score": chunk["score"],
                "entities": entities,
                "related_entities": related,
                "neighboring_chunks": [n["text"] for n in neighbors],
            }
        )

    return expanded_context
