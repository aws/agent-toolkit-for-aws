#!/usr/bin/env python3
"""
Neptune Skill — Agentic Memory Helpers

Core functions for implementing AI agent memory with Neptune (Database and
Analytics) plus DynamoDB for short-term memory. Used by references/agentic-memory.md.

Usage:
    pip install boto3==1.43.124 gremlinpython==3.7.3
    # gremlinpython is pinned to 3.7.3, the newest TinkerPop version Neptune engine
    # 1.3.2.0+ supports (AWS: "Accessing a Neptune graph with Gremlin").
    Set NEPTUNE_ENDPOINT (for Database) or GRAPH_ID (for Analytics).
    Optional: NEPTUNE_PORT (Database port, default 8182) and SHORT_TERM_TABLE
    (DynamoDB short-term memory table, default "agent-short-term-memory").
    Gremlin connections are SigV4-signed (IAM auth); set AWS_REGION or NEPTUNE_REGION.
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


def _sigv4_headers(url: str) -> Dict[str, str]:
    """SigV4-sign the Gremlin WebSocket handshake for IAM database auth.

    The test cluster (cdk_test_env.py) enables IAM auth, so an unsigned
    handshake is refused with 403. Sign the request; never disable IAM auth.
    """
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    session = boto3.Session()
    region = os.environ.get("NEPTUNE_REGION") or session.region_name
    if not region:
        raise RuntimeError("Set AWS_REGION or NEPTUNE_REGION to sign Neptune requests.")
    credentials = session.get_credentials()
    if credentials is None:
        raise RuntimeError("No AWS credentials found to sign Neptune requests.")
    request = AWSRequest(method="GET", url=url)
    SigV4Auth(credentials.get_frozen_credentials(), "neptune-db", region).add_auth(request)
    return dict(request.headers)


def _anonymous_traversal():
    """Load Gremlin's anonymous traversal builder without importing it globally."""
    from gremlin_python.process.graph_traversal import __

    return __


def _single_cardinality():
    """Load Gremlin's ``single`` cardinality without importing it globally.

    Neptune defaults vertex properties to ``set`` cardinality, so updating a
    property without ``single`` adds a value instead of replacing it.
    """
    from gremlin_python.process.traversal import Cardinality

    return Cardinality.single


def get_gremlin_traversal():
    """Create a bytecode-based Gremlin traversal source for Neptune Database.

    Returns ``(g, connection)``. The traversal source has no ``close()``;
    close the returned connection when finished.
    """
    from gremlin_python.driver import serializer
    from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
    from gremlin_python.process.anonymous_traversal import traversal

    url = f"wss://{NEPTUNE_ENDPOINT}:{NEPTUNE_PORT}/gremlin"
    connection = DriverRemoteConnection(
        url,
        "g",
        message_serializer=serializer.GraphSONSerializersV2d0(),
        headers=_sigv4_headers(url),
    )
    return traversal().with_remote(connection), connection


def remember_entity_gremlin(g, name: str, entity_type: str, **properties):
    """Store or update an entity using Gremlin bytecode."""
    anonymous = _anonymous_traversal()
    single = _single_cardinality()
    traversal = (
        g.V()
        .has("Entity", "name", name)
        .fold()
        .coalesce(
            anonymous.unfold(),
            anonymous.addV("Entity").property("name", name),
        )
        .property(single, "type", entity_type)
        .property(single, "updated_at", int(time.time() * 1000))
    )
    for key, value in properties.items():
        traversal = traversal.property(single, key, value)
    traversal.iterate()


def remember_relationship_gremlin(
    g, entity_a: str, entity_b: str, rel_type: str, confidence: float = 1.0
):
    """Store a relationship between entities using Gremlin bytecode."""
    anonymous = _anonymous_traversal()
    (
        g.V()
        .has("Entity", "name", entity_a)
        .as_("a")
        .V()
        .has("Entity", "name", entity_b)
        .as_("b")
        .coalesce(
            anonymous.select("a").outE("RELATED_TO").where(anonymous.inV().as_("b")),
            anonymous.select("a").addE("RELATED_TO").to(anonymous.select("b")),
        )
        .property("type", rel_type)
        .property("confidence", confidence)
        .property("updated_at", int(time.time() * 1000))
        .iterate()
    )


def recall_entity_gremlin(g, entity_name: str) -> List:
    """Recall everything about an entity using Gremlin bytecode."""
    from gremlin_python.process.traversal import Order

    anonymous = _anonymous_traversal()
    return (
        g.V()
        .has("Entity", "name", entity_name)
        .project("entity", "relationships", "conversations")
        .by(anonymous.valueMap())
        .by(
            anonymous.bothE("RELATED_TO")
            .project("type", "target", "confidence")
            .by(anonymous.values("type"))
            .by(anonymous.otherV().values("name"))
            .by(anonymous.values("confidence"))
            .fold()
        )
        .by(
            anonymous.in_("ABOUT")
            .hasLabel("Conversation")
            .order()
            .by("date", Order.desc)
            .limit(5)
            .valueMap("summary", "date")
            .fold()
        )
        .toList()
    )


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
        CALL neptune.algo.vectors.topK.byEmbedding({
            embedding: $embedding,
            topK: $top_k,
            vertexFilter: {equals: {property: '~label', value: 'Entity'}}
        })
        YIELD node, score
        RETURN node.name AS name, node.type AS type,
               node.description AS description, score
        ORDER BY score ASC
    """,
        parameters={
            "embedding": query_embedding,
            "top_k": top_k,
        },
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
        CALL neptune.algo.vectors.topK.byEmbedding({
            embedding: $embedding,
            topK: 10,
            vertexFilter: {andAll: [
                {equals: {property: '~label', value: 'Entity'}},
                {notEquals: {property: 'name', value: $name}}
            ]}
        })
        YIELD node, score
        RETURN node.name AS name, node.type AS type, score
        ORDER BY score ASC
    """,
        parameters={
            "embedding": query_embedding,
            "name": entity_name,
        },
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
