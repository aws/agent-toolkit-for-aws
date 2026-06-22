#!/usr/bin/env python3
"""
Pure file processor: reads a discovery `cluster-config.json` and emits
`compatibility.<cluster_name>.json` with the five-pillar verdict.

Five pillars: topology, kafka_version, configs, auth, quotas. No live
cluster or AWS API calls — deterministic and replayable from fixtures.

The discovery contract carries FULL Kafka config dumps (every broker- and
topic-level config the source exposed), not deltas. compatibility.py filters
against per-Kafka-version Apache defaults so values that match the default
do not produce evidence — only divergences from default are flagged.

Source of truth for every threshold and rule below is one of these AWS
public documentation pages (cited inline at the relevant constant):
- Express broker overview:
    https://docs.aws.amazon.com/msk/latest/developerguide/msk-broker-types-express.html
- Express read/write broker and topic configurations:
    https://docs.aws.amazon.com/msk/latest/developerguide/msk-configuration-express-read-write.html
- Express read-only broker configurations:
    https://docs.aws.amazon.com/msk/latest/developerguide/msk-configuration-express-read-only.html
- Express broker quotas:
    https://docs.aws.amazon.com/msk/latest/developerguide/limits.html#msk-express-quota
- Express broker best practices:
    https://docs.aws.amazon.com/msk/latest/developerguide/bestpractices-express.html

Apache Kafka defaults sourced from:
- https://kafka.apache.org/documentation/#brokerconfigs
- https://kafka.apache.org/documentation/#topicconfigs

Usage:
    compatibility.py <cluster-config.json> [--out-dir <dir>]

Output filename uses the source's `cluster_name` field:
    compatibility.<cluster_name>.json
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Verdict vocabulary and ordering
# ---------------------------------------------------------------------------

INFO = "INFO"
ADVISORY = "ADVISORY"
ACTION_REQUIRED = "ACTION_REQUIRED"

_RANK = {INFO: 0, ADVISORY: 1, ACTION_REQUIRED: 2}


def worst(a: str, b: str) -> str:
    return a if _RANK[a] >= _RANK[b] else b


def roll_up(verdicts: Iterable[str]) -> str:
    out = INFO
    for v in verdicts:
        out = worst(out, v)
    return out


# ---------------------------------------------------------------------------
# Pillar 1 — Topology
# Source: Express broker overview (3-AZ requirement; minimum 3 brokers;
# KRaft from 3.9). The target broker count is determined by the sizing
# workbook, not carried over from the source, so no per-cluster broker
# ceiling is evaluated here.
# ---------------------------------------------------------------------------

EXPRESS_AZ_COUNT = 3  # Express broker overview (Express is 3-AZ only)
EXPRESS_TARGET_MIN_BROKERS = 3  # Express broker overview (RF=3 across 3 AZs ⇒ ≥3)


def assess_topology(cfg: dict) -> tuple[str, list[dict]]:
    evidence: list[dict] = []
    verdict = INFO
    topology = cfg["topology"]
    bc = int(topology["num_brokers"])
    az = topology.get("num_azs")
    coordination = cfg["kafka"].get("coordination_mechanism", "Unknown")
    ver = parse_version(cfg["kafka"]["version"])

    # AZ count
    if az is None:
        evidence.append(
            _ev(
                "AZ_COUNT_UNKNOWN",
                ADVISORY,
                "We couldn't determine how many Availability Zones your cluster "
                "uses. MSK Express always deploys across 3 Availability Zones, "
                "so your MSK Express cluster will use 3 regardless.",
            )
        )
        verdict = worst(verdict, ADVISORY)
    elif int(az) != EXPRESS_AZ_COUNT:
        evidence.append(
            _ev(
                "AZ_COUNT_NOT_3",
                ADVISORY,
                f"Your cluster spans {az} Availability Zone(s). MSK Express "
                f"always deploys across {EXPRESS_AZ_COUNT} Availability Zones, "
                f"so your MSK Express cluster will use {EXPRESS_AZ_COUNT} "
                "regardless.",
                observed=int(az),
                required=EXPRESS_AZ_COUNT,
            )
        )
        verdict = worst(verdict, ADVISORY)

    # Broker-count floor. Express requires at least 3 brokers (RF=3 across 3
    # AZs). The target broker count is sized by the workbook, not taken from
    # the source, so this is an informational note, not a pass/fail check.
    if bc < EXPRESS_TARGET_MIN_BROKERS:
        evidence.append(
            _ev(
                "BROKER_COUNT_LT_3",
                ADVISORY,
                f"Your cluster has {bc} broker(s). MSK Express uses a minimum "
                f"of {EXPRESS_TARGET_MIN_BROKERS} brokers across 3 Availability "
                "Zones. The sizing workbook helps you choose your MSK Express "
                "broker count based on your throughput, so it isn't carried "
                "over from your current cluster.",
                observed=bc,
                required=EXPRESS_TARGET_MIN_BROKERS,
            )
        )
        verdict = worst(verdict, ADVISORY)

    # KRaft transition on 3.9 — flagged informationally.
    if ver[:2] == (3, 9) and coordination == "ZooKeeper":
        evidence.append(
            _ev(
                "KRAFT_REQUIRED_FOR_VERSION",
                ADVISORY,
                "Your cluster runs Kafka 3.9 with ZooKeeper. On Kafka 3.9, MSK "
                "Express runs in KRaft mode and is provisioned that way "
                "automatically; no action needed. If any of your tooling talks "
                "to ZooKeeper directly, see the Apache Kafka KRaft migration "
                "documentation: "
                "https://kafka.apache.org/37/operations/kraft/#zookeeper-to-kraft-migration",
            )
        )
        verdict = worst(verdict, ADVISORY)

    return verdict, evidence


# ---------------------------------------------------------------------------
# Pillar 2 — Kafka version
# Source: Express broker overview — "Express brokers are supported on the
# following Apache Kafka versions: 3.6, 3.8, and 3.9."
# ---------------------------------------------------------------------------

EXPRESS_SUPPORTED_VERSIONS: set[tuple[int, int]] = {(3, 6), (3, 8), (3, 9)}

# Minimum source Apache Kafka version that MSK Replicator can replicate from
# when migrating a self-managed source to Express. Sources older than this can
# still re-create the cluster architecture, but data migration must use a
# MirrorMaker 2 based solution instead.
# Source: "Migrate third-party and self-managed Apache Kafka clusters to Amazon
# MSK Express brokers with Amazon MSK Replicator" (version 2.8.1+).
MSK_REPLICATOR_MIN_SOURCE_VERSION: tuple[int, int, int] = (2, 8, 1)


def assess_kafka_version(cfg: dict) -> tuple[str, list[dict]]:
    evidence: list[dict] = []
    verdict = INFO
    raw = cfg["kafka"]["version"]
    mm = parse_version(raw)[:2]
    supported_sorted = sorted(EXPRESS_SUPPORTED_VERSIONS)
    supported_str = [f"{m}.{n}" for m, n in supported_sorted]

    if mm in EXPRESS_SUPPORTED_VERSIONS:
        evidence.append(
            _ev(
                "VERSION_SUPPORTED",
                INFO,
                f"Your cluster runs Apache Kafka {raw}, which MSK Express "
                "supports (3.6, 3.8, and 3.9). Your workload will run on the "
                "same Kafka version after migrating.",
            )
        )
    else:
        msg = (
            f"MSK Express supports Apache Kafka 3.6, 3.8, and 3.9. Your cluster "
            f"runs {raw}, so after migrating your workload will run on a new "
            "Kafka version. Confirm your client libraries and applications are "
            "compatible with the version you choose for Express — Kafka clients "
            "are generally compatible across minor versions, but we recommend "
            "validating in a test environment before migrating. See the Apache "
            "Kafka upgrade notes at https://kafka.apache.org/documentation/#upgrade "
            "for details."
        )
        if parse_version(raw) < MSK_REPLICATOR_MIN_SOURCE_VERSION:
            msg += (
                " If intending to migrate your data along with your cluster, "
                "please note that MSK Replicator can only copy data from "
                "clusters running Apache Kafka 2.8.1 or later. Since your "
                "cluster is older, you would need to set up a MirrorMaker 2 "
                "based solution instead."
            )
        evidence.append(
            _ev(
                "VERSION_NOT_IN_EXPRESS_SET",
                ADVISORY,
                msg,
                observed=raw,
                supported=supported_str,
            )
        )
        verdict = ADVISORY

    return verdict, evidence


# ---------------------------------------------------------------------------
# Pillar 3 — Configs (broker- and topic-level)
# Sources: Express read/write configurations page (R/W broker + topic
# configs, bounded ranges), Express read-only configurations page (forced
# read-only values).
#
# Discovery passes FULL config dumps. We compare each value to the Apache
# Kafka default for the source's version; only divergences from default are
# evaluated against Express's R/W, RO, range, and forced-value sets.
# ---------------------------------------------------------------------------

# Express R/W broker configs (source: Express read/write configurations page).
EXPRESS_BROKER_RW: frozenset[str] = frozenset(
    {
        "advertised.listeners",
        "allow.everyone.if.no.acl.found",
        "auto.create.topics.enable",
        "compression.type",
        "connections.max.idle.ms",
        "delete.topic.enable",
        "group.initial.rebalance.delay.ms",
        "group.max.session.timeout.ms",
        "leader.imbalance.per.broker.percentage",
        "log.cleaner.delete.retention.ms",
        "log.cleaner.max.compaction.lag.ms",
        "log.cleaner.min.compaction.lag.ms",
        "log.cleanup.policy",
        "log.message.timestamp.after.max.ms",
        "log.message.timestamp.before.max.ms",
        "log.message.timestamp.type",
        "log.retention.bytes",
        "log.retention.ms",
        "max.connection.creation.rate",
        "max.connections",
        "max.connections.per.ip",
        "max.connections.per.ip.overrides",
        "max.incremental.fetch.session.cache.slots",
        "message.max.bytes",
        "num.partitions",
        "offsets.retention.minutes",
        "producer.id.expiration.ms",
        "replica.fetch.max.bytes",
        "replica.selector.class",
        "socket.receive.buffer.bytes",
        "socket.request.max.bytes",
        "socket.send.buffer.bytes",
        "transaction.max.timeout.ms",
        "transactional.id.expiration.ms",
    }
)

# Express read-only broker configs (source: Express read-only configurations page).
EXPRESS_BROKER_RO: frozenset[str] = frozenset(
    {
        "broker.id",
        "broker.rack",
        "default.replication.factor",
        "fetch.max.bytes",
        "group.max.size",
        "inter.broker.listener.name",
        "inter.broker.protocol.version",
        "listeners",
        "log.message.format.version",
        "min.insync.replicas",
        "num.io.threads",
        "num.network.threads",
        "replica.fetch.response.max.bytes",
        "request.timeout.ms",
        "transaction.state.log.min.isr",
        "transaction.state.log.replication.factor",
        "unclean.leader.election.enable",
    }
)

ONE_DAY_MS = 24 * 60 * 60 * 1000  # 86_400_000

# Bounded ranges enforced by Express (source: Express read/write configurations page).
EXPRESS_BROKER_RANGES: dict[str, tuple[int | None, int | None]] = {
    "log.cleaner.max.compaction.lag.ms": (ONE_DAY_MS, None),
}

# Forced values (source: Express read-only configurations page).
EXPRESS_BROKER_FORCED: dict[str, Any] = {
    "default.replication.factor": 3,
    "min.insync.replicas": 2,
    "transaction.state.log.min.isr": 2,
    "unclean.leader.election.enable": "false",
}

# Express R/W topic configs (source: Express read/write configurations page,
# topic-level table).
EXPRESS_TOPIC_RW: frozenset[str] = frozenset(
    {
        "cleanup.policy",
        "compression.type",
        "delete.retention.ms",
        "max.compaction.lag.ms",
        "max.message.bytes",
        "message.timestamp.after.max.ms",
        "message.timestamp.before.max.ms",
        "message.timestamp.type",
        "min.compaction.lag.ms",
        "retention.bytes",
        "retention.ms",
    }
)

EXPRESS_TOPIC_RANGES: dict[str, tuple[int | None, int | None]] = {
    "max.compaction.lag.ms": (ONE_DAY_MS, None),
}

# Topic-level forced values (Express read/write configurations page,
# topic-level intro paragraph).
TOPIC_FORCED: dict[str, Any] = {
    "min.insync.replicas": 2,
    "unclean.leader.election.enable": "false",
}

EXPRESS_TOPIC_FORCED_RF = 3

# ---------------------------------------------------------------------------
# Apache Kafka defaults per supported version.
#
# Source: https://kafka.apache.org/documentation/#brokerconfigs and
# https://kafka.apache.org/documentation/#topicconfigs for each version.
#
# Only configs we actually check (above sets) need defaults here. If the
# source's value matches the default for its version, we emit no evidence.
# ---------------------------------------------------------------------------

# Defaults shared across 3.6/3.8/3.9 for the configs we evaluate.
_BROKER_DEFAULTS_COMMON: dict[str, Any] = {
    # R/W broker configs we check ranges/forced values for, plus high-traffic
    # configs that show up in dumps. Strings are normalized in _is_default.
    "auto.create.topics.enable": "true",
    "compression.type": "producer",
    "connections.max.idle.ms": 600000,
    "delete.topic.enable": "true",
    "group.initial.rebalance.delay.ms": 3000,
    "group.max.session.timeout.ms": 1800000,
    "leader.imbalance.per.broker.percentage": 10,
    "log.cleaner.delete.retention.ms": 86400000,
    "log.cleaner.max.compaction.lag.ms": 9223372036854775807,
    "log.cleaner.min.compaction.lag.ms": 0,
    "log.cleanup.policy": "delete",
    "log.message.timestamp.after.max.ms": 9223372036854775807,
    "log.message.timestamp.before.max.ms": 9223372036854775807,
    "log.message.timestamp.type": "CreateTime",
    "log.retention.bytes": -1,
    "log.retention.ms": -1,
    "max.connection.creation.rate": 2147483647,
    "max.connections": 2147483647,
    "max.connections.per.ip": 2147483647,
    "max.incremental.fetch.session.cache.slots": 1000,
    "message.max.bytes": 1048588,
    "num.partitions": 1,
    "offsets.retention.minutes": 10080,
    "producer.id.expiration.ms": 86400000,
    "replica.fetch.max.bytes": 1048576,
    "socket.receive.buffer.bytes": 102400,
    "socket.request.max.bytes": 104857600,
    "socket.send.buffer.bytes": 102400,
    "transaction.max.timeout.ms": 900000,
    "transactional.id.expiration.ms": 604800000,
    # Forced-value configs we check
    "default.replication.factor": 1,
    "min.insync.replicas": 1,
    "transaction.state.log.min.isr": 2,
    "unclean.leader.election.enable": "false",
    "num.io.threads": 8,
    "num.network.threads": 3,
    "allow.everyone.if.no.acl.found": "false",
}

BROKER_DEFAULTS_BY_VERSION: dict[tuple[int, int], dict[str, Any]] = {
    (3, 6): dict(_BROKER_DEFAULTS_COMMON),
    (3, 8): dict(_BROKER_DEFAULTS_COMMON),
    (3, 9): dict(_BROKER_DEFAULTS_COMMON),
}

_TOPIC_DEFAULTS_COMMON: dict[str, Any] = {
    "cleanup.policy": "delete",
    "compression.type": "producer",
    "delete.retention.ms": 86400000,
    "max.compaction.lag.ms": 9223372036854775807,
    "max.message.bytes": 1048588,
    "message.timestamp.after.max.ms": 9223372036854775807,
    "message.timestamp.before.max.ms": 9223372036854775807,
    "message.timestamp.type": "CreateTime",
    "min.compaction.lag.ms": 0,
    "retention.bytes": -1,
    "retention.ms": 604800000,
    "min.insync.replicas": 1,
    "unclean.leader.election.enable": "false",
}

TOPIC_DEFAULTS_BY_VERSION: dict[tuple[int, int], dict[str, Any]] = {
    (3, 6): dict(_TOPIC_DEFAULTS_COMMON),
    (3, 8): dict(_TOPIC_DEFAULTS_COMMON),
    (3, 9): dict(_TOPIC_DEFAULTS_COMMON),
}


def _coerce_int(value: Any) -> int | None:
    """Return int(value) or None if not coercible."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _normalize_value(value: Any) -> str:
    """Normalize a config value to a comparable string."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().lower()


def _is_default(key: str, value: Any, defaults: dict[str, Any]) -> bool:
    """Return True if value matches the Apache Kafka default for key."""
    if key not in defaults:
        # No known default — cannot tell, treat as not-default so the rule
        # still fires.
        return False
    return _normalize_value(value) == _normalize_value(defaults[key])


def _check_range(
    key: str,
    value: Any,
    bounds: tuple[int | None, int | None],
    subject: str,
) -> dict | None:
    """Returns evidence-style dict if out-of-range, else None.

    `subject` names whose setting it is ("Your cluster" for broker configs,
    f"Topic {name!r}" for topic configs) so the message reads in the customer's
    voice.
    """
    lo, hi = bounds
    lo_s = lo if lo is not None else "INT_MIN"
    hi_s = hi if hi is not None else "INT_MAX"
    iv = _coerce_int(value)
    if iv is None:
        return {
            "config_key": key,
            "detail": (
                f"MSK Express expects {key} to be an integer within "
                f"[{lo_s}, {hi_s}]. {subject} sets it to {value!r}, which is "
                "not a valid integer, so this configuration can't be migrated "
                "as-is."
            ),
            "observed": value,
            "limit": [lo, hi],
        }
    if (lo is not None and iv < lo) or (hi is not None and iv > hi):
        return {
            "config_key": key,
            "detail": (
                f"MSK Express accepts {key} only within [{lo_s}, {hi_s}]. "
                f"{subject} sets it to {value!r}, which is outside that range, "
                "so this configuration can't be migrated as-is."
            ),
            "observed": iv,
            "limit": [lo, hi],
        }
    return None


def _ev(
    code: str,
    severity: str,
    detail: str,
    **extra: Any,
) -> dict:
    """Build an evidence dict tagged with its own severity.

    severity is per-finding; pillar verdict is the worst across findings, but
    summary buckets each finding individually.
    """
    out: dict[str, Any] = {"code": code, "severity": severity, "detail": detail}
    out.update(extra)
    return out


def assess_configs(cfg: dict) -> tuple[str, list[dict]]:
    """Pillar 3: broker- and topic-level config compatibility.

    Reads broker_configs (full dump) and topics[].configs (full dump), filters
    against per-version Apache Kafka defaults, then evaluates non-default
    values against Express's R/W, RO, range, and forced-value sets.
    """
    evidence: list[dict] = []
    verdict = INFO

    parsed = parse_version(cfg["kafka"]["version"])
    ver: tuple[int, int] = (parsed[0], parsed[1])
    broker_defaults = BROKER_DEFAULTS_BY_VERSION.get(ver, _BROKER_DEFAULTS_COMMON)
    topic_defaults = TOPIC_DEFAULTS_BY_VERSION.get(ver, _TOPIC_DEFAULTS_COMMON)

    # 3a. Broker-level configs.
    for key, val in (cfg.get("broker_configs") or {}).items():
        # Skip values that match the Apache default for the source version.
        if _is_default(key, val, broker_defaults):
            continue

        # Range checks first — they decide ACTION_REQUIRED.
        if key in EXPRESS_BROKER_RANGES:
            problem = _check_range(key, val, EXPRESS_BROKER_RANGES[key], "Your cluster")
            if problem is not None:
                evidence.append(
                    _ev(
                        "BROKER_CONFIG_OUT_OF_RANGE",
                        ACTION_REQUIRED,
                        problem["detail"],
                        config_key=problem["config_key"],
                        observed=problem["observed"],
                        limit=problem["limit"],
                    )
                )
                verdict = worst(verdict, ACTION_REQUIRED)
                continue

        if key in EXPRESS_BROKER_FORCED:
            forced = EXPRESS_BROKER_FORCED[key]
            if _normalize_value(val) != _normalize_value(forced):
                evidence.append(
                    _ev(
                        "BROKER_CONFIG_FORCED_VALUE",
                        ADVISORY,
                        f"MSK Express manages {key} for you and sets it to "
                        f"{forced!r} to keep your cluster highly available and "
                        f"durable; your current value of {val!r} won't apply. We "
                        f"recommend confirming your workload behaves as expected "
                        f"with {key}={forced!r} in a test environment to ensure "
                        "a smooth migration.",
                        config_key=key,
                        observed=val,
                        enforced=forced,
                    )
                )
                verdict = worst(verdict, ADVISORY)
        elif key in EXPRESS_BROKER_RO:
            evidence.append(
                _ev(
                    "BROKER_CONFIG_READ_ONLY",
                    ADVISORY,
                    f"MSK Express manages {key} for you so you don't have to "
                    "tune it (for thread-related settings it's sized "
                    "automatically from the broker instance type); your current "
                    "value won't apply. No action needed.",
                    config_key=key,
                    observed=val,
                )
            )
            verdict = worst(verdict, ADVISORY)
        elif key not in EXPRESS_BROKER_RW:
            evidence.append(
                _ev(
                    "BROKER_CONFIG_NOT_EXPOSED",
                    ADVISORY,
                    f"{key} isn't a configurable property on MSK Express — "
                    "Express manages it internally, and the behavior may differ "
                    f"from your current value of {val!r}. We recommend "
                    "validating in a test environment to ensure a smooth "
                    "migration.",
                    config_key=key,
                    observed=val,
                )
            )
            verdict = worst(verdict, ADVISORY)
        # else: in EXPRESS_BROKER_RW and within range — INFO, no evidence.

    # 3b. Per-topic configs.
    for topic in cfg.get("topics", []):
        name = topic["name"]
        rf = int(topic["replication_factor"])
        cfgs = topic.get("configs") or {}

        if rf != EXPRESS_TOPIC_FORCED_RF:
            evidence.append(
                _ev(
                    "TOPIC_RF_NOT_3",
                    ADVISORY,
                    f"Topic {name!r} uses replication factor {rf}. MSK Express "
                    "creates every topic with replication factor 3 for "
                    "durability, so on MSK Express this topic will use 3. No "
                    "action needed.",
                    topic=name,
                    observed=rf,
                    enforced=EXPRESS_TOPIC_FORCED_RF,
                )
            )
            verdict = worst(verdict, ADVISORY)

        for key, val in cfgs.items():
            # Skip default-matching values.
            if _is_default(key, val, topic_defaults):
                continue

            if key in EXPRESS_TOPIC_RANGES:
                problem = _check_range(key, val, EXPRESS_TOPIC_RANGES[key], f"Topic {name!r}")
                if problem is not None:
                    evidence.append(
                        _ev(
                            "TOPIC_CONFIG_OUT_OF_RANGE",
                            ACTION_REQUIRED,
                            problem["detail"],
                            topic=name,
                            config_key=problem["config_key"],
                            observed=problem["observed"],
                            limit=problem["limit"],
                        )
                    )
                    verdict = worst(verdict, ACTION_REQUIRED)
                    continue

            if key in TOPIC_FORCED:
                forced = TOPIC_FORCED[key]
                if _normalize_value(val) != _normalize_value(forced):
                    evidence.append(
                        _ev(
                            "TOPIC_CONFIG_FORCED_VALUE",
                            ADVISORY,
                            f"Topic {name!r} sets {key}={val!r}. MSK Express "
                            f"fixes this at {forced!r} for every topic to keep "
                            "your data durable, so your current value won't "
                            "apply. We recommend confirming this topic behaves "
                            f"as expected with {key}={forced!r} in a test "
                            "environment to ensure a smooth migration.",
                            topic=name,
                            config_key=key,
                            observed=val,
                            enforced=forced,
                        )
                    )
                    verdict = worst(verdict, ADVISORY)
            elif key not in EXPRESS_TOPIC_RW:
                evidence.append(
                    _ev(
                        "TOPIC_CONFIG_NOT_EXPOSED",
                        ADVISORY,
                        f"Topic {name!r} sets {key}={val!r}, which isn't a "
                        "configurable topic property on MSK Express — Express "
                        "uses the broker default instead. We recommend "
                        "validating that the default works for this topic in a "
                        "test environment to ensure a smooth migration.",
                        topic=name,
                        config_key=key,
                        observed=val,
                    )
                )
                verdict = worst(verdict, ADVISORY)

    return verdict, evidence


# ---------------------------------------------------------------------------
# Pillar 4 — Auth
# Sources: Express read-only configurations page (REPLICATION_SECURE listener
# implies TLS), Express broker quotas page (IAM vs non-IAM connection limits).
# ---------------------------------------------------------------------------

# Closed enums for the security block. validate_input enforces membership;
# the auth pillar reads these directly without normalization beyond strict
# string comparison.
ENCRYPTION_VALUES: frozenset[str] = frozenset({"TLS", "PLAINTEXT", "TLS_PLAINTEXT", "UNKNOWN"})
AUTHENTICATION_VALUES: frozenset[str] = frozenset(
    {
        "UNAUTHENTICATED",
        "TLS",
        "SASL_SCRAM",
        "SASL_IAM",
        "SASL_OAUTHBEARER",
        # Catch-all for mechanisms that don't fit any of the above (e.g.
        # SASL/GSSAPI/Kerberos, SASL/PLAIN, custom callback handlers).
        # These are not supported on MSK Express; the auth pillar emits
        # ACTION_REQUIRED.
        "OTHER",
        # The mechanism could not be determined; the auth pillar emits
        # an ADVISORY asking the customer to verify it.
        "UNKNOWN",
    }
)
# Authentication mechanisms that resolve to an IAM principal and therefore
# share the per-broker IAM connection cap.
IAM_AUTHENTICATION_VALUES: frozenset[str] = frozenset({"SASL_IAM", "SASL_OAUTHBEARER"})
# Mechanisms MSK Express accepts that require TLS in transit (IAM, SASL/SCRAM,
# TLS; OAUTHBEARER is an IAM token transport). Plaintext is only possible with
# unauthenticated access, so a non-TLS source matters only for these.
TLS_REQUIRED_AUTH_VALUES: frozenset[str] = frozenset(
    {"TLS", "SASL_SCRAM", "SASL_IAM"}
)


def assess_auth(cfg: dict) -> tuple[str, list[dict]]:
    evidence: list[dict] = []
    verdict = INFO
    sec = cfg.get("security") or {}
    # Treat a missing or blank field as UNKNOWN rather than a hard failure, so
    # an absent security block yields a calm advisory instead of a false
    # "not TLS" finding.
    encryption = sec.get("encryption_in_transit") or "UNKNOWN"
    authentication = sec.get("authentication") or "UNKNOWN"

    # --- Authentication mechanism ---
    # MSK Express supports unauthenticated, TLS, SASL/SCRAM, and IAM. Those
    # carry over as-is (INFO, no evidence). SASL_OAUTHBEARER from a
    # self-managed source is a custom OAuth provider (not the AWS IAM path) —
    # MSK Express does not accept non-AWS OAUTHBEARER tokens. OTHER is also
    # unsupported. UNKNOWN cannot be confirmed (ADVISORY).
    if authentication == "SASL_OAUTHBEARER":
        evidence.append(
            _ev(
                "AUTH_OAUTHBEARER_NOT_SUPPORTED",
                ACTION_REQUIRED,
                "Your cluster uses SASL/OAUTHBEARER. MSK Express accepts "
                "OAUTHBEARER only as a transport for AWS IAM tokens (using the "
                "AWS MSK IAM signer libraries), so a custom OAuth identity "
                "provider isn't supported. Move your clients to IAM, "
                "SASL/SCRAM, or TLS to ensure a smooth migration.",
                observed=authentication,
            )
        )
        verdict = worst(verdict, ACTION_REQUIRED)
    elif authentication == "OTHER":
        evidence.append(
            _ev(
                "AUTH_MECHANISM_NOT_SUPPORTED",
                ACTION_REQUIRED,
                "Your cluster uses an authentication mechanism MSK Express "
                "doesn't support (for example SASL/GSSAPI/Kerberos, SASL/PLAIN, "
                "or a custom callback handler). MSK Express accepts "
                "unauthenticated, TLS, SASL/SCRAM, and IAM — move your clients "
                "to one of these to ensure a smooth migration.",
                observed=authentication,
            )
        )
        verdict = worst(verdict, ACTION_REQUIRED)
    elif authentication == "UNKNOWN":
        evidence.append(
            _ev(
                "AUTH_UNKNOWN",
                ADVISORY,
                "We couldn't determine your cluster's authentication "
                "mechanism. Confirm it's one MSK Express supports — one of "
                "unauthenticated, TLS, SASL/SCRAM, or IAM — to ensure a smooth "
                "migration. MSK Express doesn't support SASL/GSSAPI/Kerberos, "
                "SASL/PLAIN, or custom mechanisms.",
                observed=authentication,
            )
        )
        verdict = worst(verdict, ADVISORY)
    # UNAUTHENTICATED, TLS, SASL_SCRAM, SASL_IAM -> INFO (no evidence).

    # --- Encryption in transit (coupled to the auth mechanism) ---
    # Express requires TLS for every authenticated mechanism; plaintext is only
    # possible with unauthenticated access. So a non-TLS source matters only
    # when an authenticated mechanism is in use.
    if encryption == "UNKNOWN":
        evidence.append(
            _ev(
                "ENCRYPTION_UNKNOWN",
                ADVISORY,
                "We couldn't determine your cluster's encryption in transit. "
                "MSK Express requires TLS for authenticated clients (TLS, "
                "SASL/SCRAM, or IAM) and supports PLAINTEXT only for "
                "unauthenticated clients. Please confirm your clients can "
                "connect over TLS, if they are authenticated, to ensure a "
                "smooth migration.",
                observed=encryption,
            )
        )
        verdict = worst(verdict, ADVISORY)
    elif encryption != "TLS" and authentication in TLS_REQUIRED_AUTH_VALUES:
        evidence.append(
            _ev(
                "ENCRYPTION_NOT_TLS",
                ACTION_REQUIRED,
                f"Your cluster uses {encryption!r} for encryption in transit, "
                "but MSK Express requires TLS for authenticated clients (TLS, "
                "SASL/SCRAM, IAM). Update your clients to connect over TLS to "
                "ensure a smooth migration.",
                observed=encryption,
            )
        )
        verdict = worst(verdict, ACTION_REQUIRED)
    # encryption == "TLS" -> INFO. Non-TLS with UNAUTHENTICATED -> INFO
    # (Express permits unauthenticated plaintext). Non-TLS with OTHER is
    # subsumed by the ACTION_REQUIRED above.

    return verdict, evidence


# ---------------------------------------------------------------------------
# Pillar 5 — Quotas
# Source: Express broker quotas page (per-broker max-quota throughput at
# m7g.16xlarge, partition
# cap, IAM connection limits, per-partition throughput).
# ---------------------------------------------------------------------------

EXPRESS_MAX_INGRESS_MAX_QUOTA_PER_BROKER_MBPS = 750  # m7g.16xlarge max
EXPRESS_MAX_EGRESS_MAX_QUOTA_PER_BROKER_MBPS = 1875  # m7g.16xlarge max
EXPRESS_MAX_PARTITIONS_PER_BROKER = 32_000
EXPRESS_MAX_IAM_CONNS_PER_BROKER = 3_000
EXPRESS_PARTITION_THROUGHPUT_MBPS = 15


def assess_quotas(cfg: dict) -> tuple[str, list[dict]]:
    evidence: list[dict] = []
    verdict = INFO
    metrics = cfg.get("metrics")

    if metrics is None:
        evidence.append(
            _ev(
                "METRICS_MISSING",
                ADVISORY,
                "We don't have utilization metrics for your cluster, so we "
                "can't check your peak throughput, partitions, and connections "
                "against the MSK Express per-broker limits. The sizing estimate "
                "falls back to topology only. We recommend editing the sizing "
                "sheet manually once these metrics are available and reviewing "
                "the Express broker quotas to confirm your workload fits.",
            )
        )
        return ADVISORY, evidence

    pi = metrics.get("peak_bytes_in_per_broker_mbps")
    if pi is not None and pi > EXPRESS_MAX_INGRESS_MAX_QUOTA_PER_BROKER_MBPS:
        evidence.append(
            _ev(
                "INGRESS_OVER_MAX_BROKER",
                ADVISORY,
                f"Your peak ingress of {pi} MBps per broker is more than any "
                "single MSK Express broker can absorb (the maximum is "
                f"{EXPRESS_MAX_INGRESS_MAX_QUOTA_PER_BROKER_MBPS} MBps, on "
                "m7g.16xlarge). Spread the load across more brokers so each "
                "carries less ingress. Note that the sizing workbook accounts "
                "for this already and can help you select the right MSK Express "
                "broker instance type.",
                observed=pi,
                limit=EXPRESS_MAX_INGRESS_MAX_QUOTA_PER_BROKER_MBPS,
            )
        )
        verdict = worst(verdict, ADVISORY)

    po = metrics.get("peak_bytes_out_per_broker_mbps")
    if po is not None and po > EXPRESS_MAX_EGRESS_MAX_QUOTA_PER_BROKER_MBPS:
        evidence.append(
            _ev(
                "EGRESS_OVER_MAX_BROKER",
                ADVISORY,
                f"Your peak egress of {po} MBps per broker is more than any "
                "single MSK Express broker can absorb (the maximum is "
                f"{EXPRESS_MAX_EGRESS_MAX_QUOTA_PER_BROKER_MBPS} MBps, on "
                "m7g.16xlarge). Spread the load across more brokers so each "
                "carries less egress. Note that the sizing workbook accounts "
                "for this already and can help you select the right MSK Express "
                "broker instance type.",
                observed=po,
                limit=EXPRESS_MAX_EGRESS_MAX_QUOTA_PER_BROKER_MBPS,
            )
        )
        verdict = worst(verdict, ADVISORY)

    pp = metrics.get("peak_partitions_per_broker")
    if pp is not None and pp > EXPRESS_MAX_PARTITIONS_PER_BROKER:
        evidence.append(
            _ev(
                "PARTITIONS_OVER_MAX_BROKER",
                ADVISORY,
                f"Your peak of {pp} partitions per broker is above the MSK "
                f"Express maximum ({EXPRESS_MAX_PARTITIONS_PER_BROKER}, on "
                "m7g.16xlarge). Adding brokers spreads the partitions so each "
                "one carries fewer. Note that the sizing workbook accounts for "
                "this already and can help you select the right MSK Express "
                "broker instance type.",
                observed=pp,
                limit=EXPRESS_MAX_PARTITIONS_PER_BROKER,
            )
        )
        verdict = worst(verdict, ADVISORY)

    pc = metrics.get("peak_connections_per_broker")
    authentication = (cfg.get("security") or {}).get("authentication")
    if (
        pc is not None
        and authentication in IAM_AUTHENTICATION_VALUES
        and pc > EXPRESS_MAX_IAM_CONNS_PER_BROKER
    ):
        evidence.append(
            _ev(
                "CONNECTIONS_OVER_IAM_LIMIT",
                ADVISORY,
                f"Your peak of {pc} connections per broker is above the MSK "
                f"Express IAM limit of {EXPRESS_MAX_IAM_CONNS_PER_BROKER} per "
                "broker. You can spread the connections across more brokers, or "
                "use a non-IAM authentication mechanism, which MSK Express "
                "doesn't cap (monitor CPU and memory instead).",
                observed=pc,
                limit=EXPRESS_MAX_IAM_CONNS_PER_BROKER,
            )
        )
        verdict = worst(verdict, ADVISORY)

    # Per-partition throughput approximation.
    bc = int(cfg["topology"]["num_brokers"])
    total_partitions = sum(int(t["num_partitions"]) for t in cfg.get("topics", []))
    if pi is not None and total_partitions > 0:
        per_part_mbps = (pi * bc) / total_partitions
        if per_part_mbps > EXPRESS_PARTITION_THROUGHPUT_MBPS:
            evidence.append(
                _ev(
                    "PARTITION_THROUGHPUT_OVER_LIMIT",
                    ADVISORY,
                    f"Your average per-partition throughput of "
                    f"{per_part_mbps:.1f} MB/s is above the MSK Express limit "
                    f"of {EXPRESS_PARTITION_THROUGHPUT_MBPS} MB/s, where Express "
                    "begins to throttle. Individual hot partitions can throttle "
                    "your clients. We recommend spreading the busiest topics "
                    "across more partitions before migrating.",
                    observed=round(per_part_mbps, 1),
                    limit=EXPRESS_PARTITION_THROUGHPUT_MBPS,
                )
            )
            verdict = worst(verdict, ADVISORY)

    return verdict, evidence


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(r"^\s*(\d+)\.(\d+)(?:\.(\d+))?")


def parse_version(raw: str) -> tuple[int, ...]:
    """Parse '3.6', '3.6.0', '3.6.1' → (3, 6, ...)."""
    m = _VERSION_RE.match(raw)
    if not m:
        raise ValueError(f"Unparseable Kafka version: {raw!r}")
    parts = [int(g) for g in m.groups() if g is not None]
    return tuple(parts)


def _utcnow_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Input validation — discovery contract
# ---------------------------------------------------------------------------

REQUIRED_TOP_LEVEL = ("cluster_name", "kafka", "topology", "topics")
REQUIRED_KAFKA_FIELDS = ("version",)
REQUIRED_TOPOLOGY_FIELDS = ("num_brokers",)


def validate_input(cfg: dict) -> None:
    """Raise ValueError when the discovery contract lacks required fields or
    carries unknown values for closed enums (security.encryption_in_transit,
    security.authentication)."""
    missing = [k for k in REQUIRED_TOP_LEVEL if k not in cfg]
    if missing:
        raise ValueError(f"discovery contract missing top-level fields: {missing}")

    kafka_missing = [k for k in REQUIRED_KAFKA_FIELDS if k not in cfg["kafka"]]
    if kafka_missing:
        raise ValueError(f"kafka block missing required fields: {kafka_missing}")

    topo_missing = [k for k in REQUIRED_TOPOLOGY_FIELDS if k not in cfg["topology"]]
    if topo_missing:
        raise ValueError(f"topology block missing required fields: {topo_missing}")

    if not isinstance(cfg["topics"], list):
        raise ValueError("topics must be a list")

    # Strict enum validation on the security block. Both fields are required
    # if the block is present; if security is absent altogether the auth
    # pillar emits no evidence (treated as "unknown / not provided"), but
    # any value supplied must be from the closed enum.
    sec = cfg.get("security")
    if sec is not None:
        encryption = sec.get("encryption_in_transit")
        if encryption is not None and encryption not in ENCRYPTION_VALUES:
            raise ValueError(
                f"security.encryption_in_transit={encryption!r} is not in the "
                f"allowed enum {sorted(ENCRYPTION_VALUES)}"
            )
        authentication = sec.get("authentication")
        if authentication is not None and authentication not in AUTHENTICATION_VALUES:
            raise ValueError(
                f"security.authentication={authentication!r} is not in the "
                f"allowed enum {sorted(AUTHENTICATION_VALUES)}"
            )


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------

PILLARS = (
    ("topology", assess_topology),
    ("kafka_version", assess_kafka_version),
    ("configs", assess_configs),
    ("auth", assess_auth),
    ("quotas", assess_quotas),
)


def assess(cfg: dict) -> dict:
    """Run all five pillars; return the compatibility document."""
    validate_input(cfg)
    pillars: dict[str, dict] = {}
    for name, fn in PILLARS:
        verdict, evidence = fn(cfg)
        pillars[name] = {"verdict": verdict, "evidence": evidence}

    overall = roll_up(p["verdict"] for p in pillars.values())

    # Bucket each finding by ITS OWN severity, not the pillar's verdict.
    summary: dict[str, list[str]] = {
        "action_required_codes": [],
        "advisory_codes": [],
        "info_codes": [],
    }
    bucket_by_severity = {
        ACTION_REQUIRED: "action_required_codes",
        ADVISORY: "advisory_codes",
        INFO: "info_codes",
    }
    for p in pillars.values():
        for ev in p["evidence"]:
            sev = ev.get("severity", p["verdict"])  # fallback for safety
            summary[bucket_by_severity[sev]].append(ev["code"])

    return {
        "cluster_name": cfg["cluster_name"],
        "assessed_at": _utcnow_iso(),
        "overall": overall,
        "pillars": pillars,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="MSK Express compatibility assessor (file-only, deterministic)."
    )
    p.add_argument(
        "cluster_config",
        type=Path,
        help="Path to migrate-to-msk-skill-artifacts/<cluster_name>/cluster-config.json (discovery output).",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path.cwd(),
        help="Directory to write compatibility.<cluster_name>.json (default: cwd).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    cfg = json.loads(args.cluster_config.read_text())
    doc = assess(cfg)
    out_path = args.out_dir / f"compatibility.{doc['cluster_name']}.json"
    out_path.write_text(json.dumps(doc, indent=2, sort_keys=False) + "\n")
    print(out_path, file=sys.stderr)
    print(f"overall: {doc['overall']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
