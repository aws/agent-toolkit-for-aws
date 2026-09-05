#!/usr/bin/env python3
"""
Neptune Skill — Test Data Seeder

Seeds the Neptune test cluster with sample data for eval runs.
Covers: social graph, fraud detection graph, product catalog.

Usage:
    pip install gremlinpython boto3

    # Seeding wipes the graph first (g.V().drop()), which requires explicit
    # confirmation — pass --confirm-wipe or set NEPTUNE_SEED_CONFIRM_WIPE=1.
    NEPTUNE_ENDPOINT=your-cluster.xxxx.neptune.amazonaws.com python seed_test_data.py --confirm-wipe
"""

import os
import sys
import time

from gremlin_python.driver import client, serializer

NEPTUNE_ENDPOINT = os.environ.get("NEPTUNE_ENDPOINT", "localhost")
NEPTUNE_PORT = 8182


def get_client():
    return client.Client(
        f"wss://{NEPTUNE_ENDPOINT}:{NEPTUNE_PORT}/gremlin",
        "g",
        message_serializer=serializer.GraphSONSerializersV2d0(),
    )


def clear_graph(c, confirmed: bool = False):
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
    c.submit("g.V().drop()").all().result()
    time.sleep(1)


def seed_social_graph(c):
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
        c.submit(
            "g.addV('Person').property('id', uid).property('name', name).property('age', age)",
            {"uid": uid, "name": name, "age": age},
        ).all().result()

    # Create follows edges
    follows = [("U1", "U2"), ("U1", "U3"), ("U2", "U4"), ("U3", "U4"), ("U4", "U5")]
    for src, dst in follows:
        c.submit(
            "g.V().has('Person','id',src).addE('FOLLOWS').to(g.V().has('Person','id',dst))",
            {"src": src, "dst": dst},
        ).all().result()

    print(f"  Created {len(users)} users, {len(follows)} follows edges")


def seed_fraud_graph(c):
    """Fraud detection graph for DEC-02 eval."""
    print("Seeding fraud graph...")

    # Accounts
    accounts = [("A1", "clean"), ("A2", "flagged"), ("A3", "unknown"), ("A4", "clean")]
    for aid, status in accounts:
        c.submit(
            "g.addV('Account').property('id', aid).property('status', status)",
            {"aid": aid, "status": status},
        ).all().result()

    # Shared identifiers
    identifiers = [
        ("E1", "email", "shared@example.com"),
        ("P1", "phone", "+15551234567"),
        ("D1", "device", "device-abc-123"),
    ]
    for iid, itype, value in identifiers:
        c.submit(
            "g.addV('Identifier').property('id', iid).property('type', itype).property('value', value)",
            {"iid": iid, "itype": itype, "value": value},
        ).all().result()

    # Account → Identifier edges (shared identifiers create fraud ring)
    uses = [("A1", "E1"), ("A2", "E1"), ("A2", "P1"), ("A3", "P1"), ("A4", "D1")]
    for aid, iid in uses:
        c.submit(
            "g.V().has('Account','id',aid).addE('USES').to(g.V().has('Identifier','id',iid))",
            {"aid": aid, "iid": iid},
        ).all().result()

    print(
        f"  Created {len(accounts)} accounts, {len(identifiers)} identifiers, {len(uses)} USES edges"
    )


def seed_product_graph(c):
    """Product recommendation graph."""
    print("Seeding product graph...")

    products = [("P1", "Widget", 29.99), ("P2", "Gadget", 49.99), ("P3", "Doohickey", 9.99)]
    for pid, name, price in products:
        c.submit(
            "g.addV('Product').property('id', pid).property('name', name).property('price', price)",
            {"pid": pid, "name": name, "price": price},
        ).all().result()

    # User purchases (links social and product graphs)
    purchases = [("U1", "P1"), ("U2", "P1"), ("U2", "P2"), ("U3", "P3")]
    for uid, pid in purchases:
        c.submit(
            "g.V().has('Person','id',uid).addE('PURCHASED').to(g.V().has('Product','id',pid))",
            {"uid": uid, "pid": pid},
        ).all().result()

    print(f"  Created {len(products)} products, {len(purchases)} PURCHASED edges")


def verify_seed(c):
    """Quick verification of seeded data."""
    print("\nVerifying seeded data...")
    v_count = c.submit("g.V().count()").all().result()[0]
    e_count = c.submit("g.E().count()").all().result()[0]
    print(f"  Vertices: {v_count}")
    print(f"  Edges: {e_count}")

    # Test a fraud ring query
    ring = (
        c.submit(
            "g.V().has('Account','id','A2').out('USES').in('USES').dedup().values('id').toList()"
        )
        .all()
        .result()
    )
    print(f"  Accounts sharing identifiers with A2: {ring}")
    assert len(ring) >= 2, "Fraud ring query returned unexpected results"

    # Test a 2-hop social traversal
    fof = (
        c.submit(
            "g.V().has('Person','id','U1').out('FOLLOWS').out('FOLLOWS').dedup().values('name').toList()"
        )
        .all()
        .result()
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
    c = get_client()

    try:
        clear_graph(c, confirmed=wipe_confirmed)
        seed_social_graph(c)
        seed_fraud_graph(c)
        seed_product_graph(c)
        verify_seed(c)
    finally:
        c.close()

    print("\nSeed complete. Neptune test cluster is ready for eval runs.")
    print(f"Endpoint: wss://{NEPTUNE_ENDPOINT}:{NEPTUNE_PORT}/gremlin")
