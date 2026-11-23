#!/usr/bin/env python3
"""
Neptune Skill — Test Data Seeder

Seeds the Neptune test cluster with sample data for eval runs.
Covers: social graph, fraud detection graph, product catalog.

Usage:
    pip install gremlinpython==3.7.3 boto3==1.43.124
    # gremlinpython is pinned to 3.7.3, the newest TinkerPop version Neptune engine
    # 1.3.2.0+ supports (AWS: "Accessing a Neptune graph with Gremlin").

    # Seeding wipes the graph first (g.V().drop()), which requires explicit
    # confirmation — pass --confirm-wipe or set NEPTUNE_SEED_CONFIRM_WIPE=1.
    # The handshake is SigV4-signed (IAM auth), so AWS credentials and a region are required:
    # set AWS_REGION, or NEPTUNE_REGION to override it for Neptune only.
    AWS_REGION=us-east-1 NEPTUNE_ENDPOINT=your-cluster.xxxx.neptune.amazonaws.com python seed_test_data.py --confirm-wipe
"""

import os
import sys
import time
from typing import Dict

NEPTUNE_ENDPOINT = os.environ.get("NEPTUNE_ENDPOINT", "localhost")
NEPTUNE_PORT = 8182


def _sigv4_headers(url: str) -> Dict[str, str]:
    """SigV4-sign the Gremlin WebSocket handshake for IAM database auth.

    The test cluster (cdk_test_env.py) enables IAM auth, so an unsigned
    handshake is refused with 403. Sign the request; never disable IAM auth.
    """
    import boto3
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


def get_gremlin_traversal():
    """Create a bytecode-based Gremlin traversal source for Neptune Database.

    Returns ``(g, connection)``. Neptune does not support Gremlin ``bindings``,
    so values are passed as traversal arguments. Close the connection when
    finished.
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


def clear_graph(g, confirmed: bool = False):
    """Wipe ALL vertices and edges. Destructive and irreversible.

    `g.V().drop()` is on the skill's Never-Auto-Execute list (see
    references/action-safety.md). It runs ONLY when the caller passes an
    explicit confirmation — either --confirm-wipe on the command line or
    NEPTUNE_SEED_CONFIRM_WIPE=1 in the environment.
    """
    if not confirmed:
        raise RuntimeError(
            "Refusing to wipe the graph: g.V().drop() requires explicit "
            "confirmation. Re-run with --confirm-wipe or set "
            "NEPTUNE_SEED_CONFIRM_WIPE=1. Never run this against a graph "
            "holding data you need."
        )
    print(f"Clearing ALL graph data at {NEPTUNE_ENDPOINT}...")
    g.V().drop().iterate()
    time.sleep(1)


def seed_social_graph(g):
    """Social network for QUERY and DEC evals."""
    print("Seeding social graph...")

    # Create users
    users = [
        ("U1", "Alice", 30),
        ("U2", "Bob", 28),
        ("U3", "Carol", 35),
        ("U4", "Dave", 25),
        ("U5", "Eve", 32),
    ]

    for uid, name, age in users:
        g.addV("Person").property("id", uid).property("name", name).property("age", age).iterate()

    # Create follows edges
    follows = [("U1", "U2"), ("U1", "U3"), ("U2", "U4"), ("U3", "U4"), ("U4", "U5")]
    anonymous = _anonymous_traversal()
    for src, dst in follows:
        (
            g.V()
            .has("Person", "id", src)
            .addE("FOLLOWS")
            .to(anonymous.V().has("Person", "id", dst))
            .iterate()
        )

    print(f"  Created {len(users)} users, {len(follows)} follows edges")


def seed_fraud_graph(g):
    """Fraud detection graph for DEC-02 eval."""
    print("Seeding fraud graph...")

    # Accounts
    accounts = [("A1", "clean"), ("A2", "flagged"), ("A3", "unknown"), ("A4", "clean")]
    for aid, status in accounts:
        g.addV("Account").property("id", aid).property("status", status).iterate()

    # Shared identifiers
    identifiers = [
        ("E1", "email", "shared@example.com"),
        ("P1", "phone", "+15551234567"),
        ("D1", "device", "device-abc-123"),
    ]
    for iid, itype, value in identifiers:
        (
            g.addV("Identifier")
            .property("id", iid)
            .property("type", itype)
            .property("value", value)
            .iterate()
        )

    # Account → Identifier edges (shared identifiers create fraud ring)
    uses = [("A1", "E1"), ("A2", "E1"), ("A2", "P1"), ("A3", "P1"), ("A4", "D1")]
    anonymous = _anonymous_traversal()
    for aid, iid in uses:
        (
            g.V()
            .has("Account", "id", aid)
            .addE("USES")
            .to(anonymous.V().has("Identifier", "id", iid))
            .iterate()
        )

    print(
        f"  Created {len(accounts)} accounts, {len(identifiers)} identifiers, {len(uses)} USES edges"
    )


def seed_product_graph(g):
    """Product recommendation graph."""
    print("Seeding product graph...")

    products = [("P1", "Widget", 29.99), ("P2", "Gadget", 49.99), ("P3", "Doohickey", 9.99)]
    for pid, name, price in products:
        g.addV("Product").property("id", pid).property("name", name).property(
            "price", price
        ).iterate()

    # User purchases (links social and product graphs)
    purchases = [("U1", "P1"), ("U2", "P1"), ("U2", "P2"), ("U3", "P3")]
    anonymous = _anonymous_traversal()
    for uid, pid in purchases:
        (
            g.V()
            .has("Person", "id", uid)
            .addE("PURCHASED")
            .to(anonymous.V().has("Product", "id", pid))
            .iterate()
        )

    print(f"  Created {len(products)} products, {len(purchases)} PURCHASED edges")


def verify_seed(g):
    """Quick verification of seeded data."""
    print("\nVerifying seeded data...")
    v_count = g.V().count().next()
    e_count = g.E().count().next()
    print(f"  Vertices: {v_count}")
    print(f"  Edges: {e_count}")

    # Test a fraud ring query
    ring = g.V().has("Account", "id", "A2").out("USES").in_("USES").dedup().values("id").toList()
    print(f"  Accounts sharing identifiers with A2: {ring}")
    assert len(ring) >= 2, "Fraud ring query returned unexpected results"

    # Test a 2-hop social traversal
    fof = (
        g.V()
        .has("Person", "id", "U1")
        .out("FOLLOWS")
        .out("FOLLOWS")
        .dedup()
        .values("name")
        .toList()
    )
    print(f"  Friends-of-friends for Alice: {fof}")
    assert len(fof) >= 1, "Friends-of-friends query returned unexpected results"

    print("\n✅ Seed data verified successfully")


if __name__ == "__main__":
    # g.V().drop() is destructive and requires explicit confirmation.
    wipe_confirmed = (
        "--confirm-wipe" in sys.argv or os.environ.get("NEPTUNE_SEED_CONFIRM_WIPE") == "1"
    )

    print(f"Connecting to Neptune at {NEPTUNE_ENDPOINT}:{NEPTUNE_PORT}...")
    g, connection = get_gremlin_traversal()

    try:
        clear_graph(g, confirmed=wipe_confirmed)
        seed_social_graph(g)
        seed_fraud_graph(g)
        seed_product_graph(g)
        verify_seed(g)
    finally:
        connection.close()

    print("\nSeed complete. Neptune test cluster is ready for eval runs.")
    print(f"Endpoint: wss://{NEPTUNE_ENDPOINT}:{NEPTUNE_PORT}/gremlin")
