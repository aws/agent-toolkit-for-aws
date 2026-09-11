#!/usr/bin/env python3
"""
Neptune Skill — Agentic Memory Helpers

Core functions for implementing AI agent memory with Neptune (Database and
Analytics) plus DynamoDB for short-term memory. Used by references/agentic-memory.md.

Usage:
    pip install boto3 gremlinpython
    Set NEPTUNE_ENDPOINT (for Database) or GRAPH_ID (for Analytics).
"""

import json
import os
import time
from typing import Any, Dict, List, Optional

import boto3

# =============================================================================
# Short-Term Memory (DynamoDB)
# =============================================================================

dynamodb = boto3.resource("dynamodb")
SHORT_TERM_TABLE = os.environ.get("SHORT_TERM_TABLE", "agent-short-term-memory")


def get_short_term_table():
    return dynamodb.Table(SHORT_TERM_TABLE)


def store_message(session_id: str, role: str, content: str):
    """Store a message in short-term memory with 24h TTL."""
    get_short_term_table().put_item(
        Item={
            "session_id": session_id,
            "timestamp": int(time.time() * 1000),
            "role": role,
            "content": content,
            "ttl": int(time.time()) + 86400,
        }
    )


def get_recent_messages(session_id: str, limit: int = 20) -> List[Dict]:
    """Retrieve recent messages (most recent first, then reversed)."""
    response = get_short_term_table().query(
        KeyConditionExpression="session_id = :sid",
        ExpressionAttributeValues={":sid": session_id},
        ScanIndexForward=False,
        Limit=limit,
    )
    return list(reversed(response["Items"]))


# =============================================================================
# Long-Term Memory — Neptune Database (Gremlin)
# =============================================================================

NEPTUNE_ENDPOINT = os.environ.get("NEPTUNE_ENDPOINT", "localhost")
NEPTUNE_PORT = int(os.environ.get("NEPTUNE_PORT", "8182"))


def get_gremlin_client():
    """Create a Gremlin client for Neptune Database."""
    from gremlin_python.driver import client, serializer

    return client.Client(
        f"wss://{NEPTUNE_ENDPOINT}:{NEPTUNE_PORT}/gremlin",
        "g",
        message_serializer=serializer.GraphSONSerializersV2d0(),
    )


def remember_entity_gremlin(gremlin_client, name: str, entity_type: str, **properties):
    """Store or update an entity in Neptune Database."""
    bindings = {"entity_name": name, "entity_type": entity_type}
    query = """
        g.V().has('Entity', 'name', entity_name).fold()
        .coalesce(unfold(), addV('Entity').property('name', entity_name))
        .property('type', entity_type)
        .property('updated_at', new Date().getTime())
    """
    for key, value in properties.items():
        binding_key = f"prop_{key}"
        query += f"        .property('{key}', {binding_key})\n"
        bindings[binding_key] = value
    gremlin_client.submit(query, bindings=bindings).all().result()


def remember_relationship_gremlin(
    gremlin_client, entity_a: str, entity_b: str, rel_type: str, confidence: float = 1.0
):
    """Store a relationship between entities in Neptune Database."""
    bindings = {
        "name_a": entity_a,
        "name_b": entity_b,
        "rel_type": rel_type,
        "confidence": confidence,
    }
    query = """
        g.V().has('Entity', 'name', name_a).as('a')
        .V().has('Entity', 'name', name_b).as('b')
        .coalesce(
            select('a').outE('RELATED_TO').where(inV().as('b')),
            select('a').addE('RELATED_TO').to(select('b'))
        )
        .property('type', rel_type)
        .property('confidence', confidence)
        .property('updated_at', new Date().getTime())
    """
    gremlin_client.submit(query, bindings=bindings).all().result()


def recall_entity_gremlin(gremlin_client, entity_name: str) -> List:
    """Recall everything about an entity from Neptune Database."""
    bindings = {"entity_name": entity_name}
    query = """
        g.V().has('Entity', 'name', entity_name)
        .project('entity', 'relationships', 'conversations')
        .by(valueMap())
        .by(bothE('RELATED_TO').project('type', 'target', 'confidence')
            .by(values('type')).by(otherV().values('name')).by(values('confidence'))
            .fold())
        .by(in('ABOUT').hasLabel('Conversation')
            .order().by('date', desc).limit(5)
            .valueMap('summary', 'date').fold())
    """
    return gremlin_client.submit(query, bindings=bindings).all().result()


# =============================================================================
# Long-Term Memory — Neptune Analytics (openCypher + Vector)
# =============================================================================

analytics_client = boto3.client("neptune-graph")
GRAPH_ID = os.environ.get("GRAPH_ID", "g-xxxxxxxxxx")


def run_query(graph_id: str, query: str, parameters: Optional[Dict[str, Any]] = None) -> List[Dict]:
    """Execute openCypher query against Neptune Analytics."""
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


def create_memory_graph(
    graph_name: str = "agent-memory",
    memory_gb: int = 16,
    embedding_dim: int = 1536,
    generation_model: str = "unknown",
) -> str:
    """Create Neptune Analytics graph with vector search for agent memory.

    Secure defaults: deletionProtection=True and the mandatory skill tags.
    """
    response = analytics_client.create_graph(
        graphName=graph_name,
        provisionedMemory=memory_gb,
        publicConnectivity=False,
        vectorSearchConfiguration={"dimension": embedding_dim},
        deletionProtection=True,
        tags={"created_by": "neptune-skill", "generation_model": generation_model},
    )
    return response["id"]


def remember_with_embedding(
    graph_id: str, entity_name: str, description: str, embedding: List[float]
):
    """Store entity with embedding for semantic recall."""
    run_query(
        graph_id,
        """
        MERGE (e:Entity {name: $name})
        SET e.description = $description, e.updated_at = timestamp()
    """,
        parameters={"name": entity_name, "description": description},
    )

    run_query(
        graph_id,
        """
        MATCH (e:Entity {name: $name})
        CALL neptune.algo.vectors.upsert(e, $embedding)
        YIELD node RETURN node.name
    """,
        parameters={"name": entity_name, "embedding": embedding},
    )


def semantic_recall(graph_id: str, query_embedding: List[float], top_k: int = 10) -> List[Dict]:
    """Recall memories by vector similarity."""
    return run_query(
        graph_id,
        """
        CALL neptune.algo.vectors.topKByEmbedding($embedding, {topK: $top_k})
        YIELD node, score
        RETURN node.name AS name, node.type AS type,
               node.description AS description, score
        ORDER BY score DESC
    """,
        parameters={"embedding": query_embedding, "top_k": top_k},
    )


def hybrid_recall(graph_id: str, entity_name: str, query_embedding: List[float]) -> Dict:
    """Combine graph traversal + vector search for comprehensive recall."""
    graph_results = run_query(
        graph_id,
        """
        MATCH (e:Entity {name: $name})-[r:RELATED_TO]-(related)
        RETURN related.name AS name, related.type AS type,
               r.type AS relationship, r.confidence AS confidence
        ORDER BY r.confidence DESC LIMIT 20
    """,
        parameters={"name": entity_name},
    )

    vector_results = run_query(
        graph_id,
        """
        CALL neptune.algo.vectors.topKByEmbedding($embedding, {topK: 10})
        YIELD node, score
        WHERE node.name <> $name
        RETURN node.name AS name, node.type AS type, score
    """,
        parameters={"embedding": query_embedding, "name": entity_name},
    )

    return {"graph_recall": graph_results, "semantic_recall": vector_results}


def consolidate_memories(graph_id: str):
    """Decay old memories and remove low-confidence facts."""
    run_query(
        graph_id,
        """
        MATCH (f:Fact) WHERE f.updated_at < timestamp() - 7776000000
        SET f.confidence = f.confidence * 0.9
    """,
    )
    run_query(
        graph_id,
        """
        MATCH (f:Fact) WHERE f.confidence < 0.1
        DETACH DELETE f
    """,
    )
