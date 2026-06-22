"""
Tests for compatibility.py.

Run from the skill root:
    python3 -m pytest scripts/tests/

Each test exercises one pillar (or one rule within a pillar) with a minimal
cluster-config dict matching the discovery contract. The fixture `base_cfg`
is the smallest config that passes every pillar with INFO; tests mutate it
field-by-field to drive specific verdicts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make scripts importable when running pytest from the skill root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import compatibility as c  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def base_cfg() -> dict:
    """Minimal cluster-config that passes every pillar with INFO."""
    return {
        "cluster_name": "test-cluster",
        "kafka": {
            "version": "3.9.0",
            "coordination_mechanism": "KRaft",
        },
        "topology": {
            "num_brokers": 3,
            "num_azs": 3,
        },
        "topics": [
            {
                "name": "orders",
                "num_partitions": 6,
                "replication_factor": 3,
                "configs": {},
            },
        ],
        "broker_configs": {},
        "security": {
            "encryption_in_transit": "TLS",
            "authentication": "SASL_SCRAM",
        },
        "metrics": {
            "peak_bytes_in_per_broker_mbps": 10,
            "peak_bytes_out_per_broker_mbps": 20,
            "peak_partitions_per_broker": 100,
            "peak_connections_per_broker": 100,
        },
    }


def codes(evidence: list[dict]) -> list[str]:
    return [e["code"] for e in evidence]


# ---------------------------------------------------------------------------
# Verdict helpers
# ---------------------------------------------------------------------------


class TestVerdictHelpers:
    def test_worst_orders_correctly(self):
        assert c.worst(c.INFO, c.ADVISORY) == c.ADVISORY
        assert c.worst(c.ADVISORY, c.INFO) == c.ADVISORY
        assert c.worst(c.ADVISORY, c.ACTION_REQUIRED) == c.ACTION_REQUIRED
        assert c.worst(c.ACTION_REQUIRED, c.ADVISORY) == c.ACTION_REQUIRED
        assert c.worst(c.INFO, c.INFO) == c.INFO

    def test_roll_up_picks_worst(self):
        assert c.roll_up([c.INFO, c.INFO]) == c.INFO
        assert c.roll_up([c.INFO, c.ADVISORY, c.INFO]) == c.ADVISORY
        assert c.roll_up([c.INFO, c.ADVISORY, c.ACTION_REQUIRED]) == c.ACTION_REQUIRED
        assert c.roll_up([]) == c.INFO


class TestParseVersion:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("3.6", (3, 6)),
            ("3.6.0", (3, 6, 0)),
            ("3.9.1", (3, 9, 1)),
            ("  3.8  ", (3, 8)),
        ],
    )
    def test_parses_valid(self, raw, expected):
        assert c.parse_version(raw) == expected

    def test_rejects_malformed(self):
        with pytest.raises(ValueError):
            c.parse_version("garbage")


class TestCoerceInt:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (10, 10),
            ("10", 10),
            ("604800000", 604_800_000),
            ("not-a-number", None),
            (None, None),
            (True, None),
        ],
    )
    def test_coerce(self, value, expected):
        assert c._coerce_int(value) == expected


class TestIsDefault:
    def test_matching_string(self):
        assert c._is_default("compression.type", "producer", {"compression.type": "producer"})

    def test_matching_int_vs_str(self):
        # Discovery may serialize ints as strings.
        assert c._is_default("num.partitions", "1", {"num.partitions": 1})

    def test_matching_bool_vs_str(self):
        assert c._is_default(
            "auto.create.topics.enable", "true", {"auto.create.topics.enable": True}
        )

    def test_mismatching(self):
        assert not c._is_default("min.insync.replicas", "3", {"min.insync.replicas": 1})

    def test_unknown_key_treated_as_not_default(self):
        # Unknown defaults: cannot tell, treat as not-default so rules still fire.
        assert not c._is_default("some.exotic.config", "anything", {})


# ---------------------------------------------------------------------------
# Pillar 1 — Topology
# ---------------------------------------------------------------------------


class TestTopologyPillar:
    def test_baseline_is_info(self, base_cfg):
        verdict, ev = c.assess_topology(base_cfg)
        assert verdict == c.INFO
        assert ev == []

    def test_az_count_unknown_is_advisory(self, base_cfg):
        del base_cfg["topology"]["num_azs"]
        verdict, ev = c.assess_topology(base_cfg)
        assert verdict == c.ADVISORY
        assert "AZ_COUNT_UNKNOWN" in codes(ev)

    @pytest.mark.parametrize("az", [1, 2, 4])
    def test_az_not_3_is_advisory(self, base_cfg, az):
        base_cfg["topology"]["num_azs"] = az
        verdict, ev = c.assess_topology(base_cfg)
        assert verdict == c.ADVISORY
        assert "AZ_COUNT_NOT_3" in codes(ev)

    def test_broker_count_below_3_is_advisory(self, base_cfg):
        base_cfg["topology"]["num_brokers"] = 2
        verdict, ev = c.assess_topology(base_cfg)
        assert verdict == c.ADVISORY
        assert "BROKER_COUNT_LT_3" in codes(ev)

    def test_kraft_required_for_3_9_when_zk(self, base_cfg):
        base_cfg["kafka"]["coordination_mechanism"] = "ZooKeeper"
        verdict, ev = c.assess_topology(base_cfg)
        assert verdict == c.ADVISORY
        assert "KRAFT_REQUIRED_FOR_VERSION" in codes(ev)


# ---------------------------------------------------------------------------
# Pillar 2 — Kafka version
# ---------------------------------------------------------------------------


class TestKafkaVersionPillar:
    @pytest.mark.parametrize("ver", ["3.6.0", "3.8.0", "3.9.0", "3.6", "3.9.1"])
    def test_supported_is_info(self, base_cfg, ver):
        base_cfg["kafka"]["version"] = ver
        verdict, ev = c.assess_kafka_version(base_cfg)
        assert verdict == c.INFO
        assert "VERSION_SUPPORTED" in codes(ev)

    def test_newer_than_express_is_advisory(self, base_cfg):
        base_cfg["kafka"]["version"] = "4.0.0"
        verdict, ev = c.assess_kafka_version(base_cfg)
        assert verdict == c.ADVISORY
        assert "VERSION_NOT_IN_EXPRESS_SET" in codes(ev)

    @pytest.mark.parametrize("ver", ["2.8.1", "3.0.0", "3.5.0", "3.7.0", "4.0.0"])
    def test_older_newer_or_gap_is_advisory(self, base_cfg, ver):
        base_cfg["kafka"]["version"] = ver
        verdict, ev = c.assess_kafka_version(base_cfg)
        assert verdict == c.ADVISORY
        assert "VERSION_NOT_IN_EXPRESS_SET" in codes(ev)

    def test_below_replicator_min_notes_mirrormaker(self, base_cfg):
        base_cfg["kafka"]["version"] = "2.7.0"
        verdict, ev = c.assess_kafka_version(base_cfg)
        assert verdict == c.ADVISORY
        msg = next(e["detail"] for e in ev if e["code"] == "VERSION_NOT_IN_EXPRESS_SET")
        assert "MirrorMaker" in msg
        assert "2.8.1" in msg

    def test_at_replicator_min_no_mirrormaker_note(self, base_cfg):
        base_cfg["kafka"]["version"] = "2.8.1"
        verdict, ev = c.assess_kafka_version(base_cfg)
        msg = next(e["detail"] for e in ev if e["code"] == "VERSION_NOT_IN_EXPRESS_SET")
        assert "MirrorMaker" not in msg


# ---------------------------------------------------------------------------
# Pillar 3 — Configs (broker- and topic-level), with default-value filtering
# ---------------------------------------------------------------------------


class TestConfigsPillar:
    def test_baseline_is_info(self, base_cfg):
        verdict, ev = c.assess_configs(base_cfg)
        assert verdict == c.INFO
        assert ev == []

    # --- default-value filtering ---

    def test_broker_config_at_default_emits_no_evidence(self, base_cfg):
        # Apache default for min.insync.replicas is 1; not Express's 2.
        # Source value matching the Apache default should still emit no evidence
        # even though Express forces 2 — discovery sent the default.
        base_cfg["broker_configs"]["min.insync.replicas"] = "1"
        verdict, ev = c.assess_configs(base_cfg)
        assert verdict == c.INFO
        assert ev == []

    def test_full_dump_of_defaults_emits_no_evidence(self, base_cfg):
        # Simulate discovery dumping every config at default.
        base_cfg["broker_configs"] = {
            "compression.type": "producer",
            "auto.create.topics.enable": "true",
            "num.partitions": "1",
            "min.insync.replicas": "1",
            "default.replication.factor": "1",
            "unclean.leader.election.enable": "false",
        }
        verdict, ev = c.assess_configs(base_cfg)
        assert verdict == c.INFO
        assert ev == []

    def test_topic_config_at_default_emits_no_evidence(self, base_cfg):
        base_cfg["topics"][0]["configs"]["retention.ms"] = "604800000"  # default
        verdict, ev = c.assess_configs(base_cfg)
        assert verdict == c.INFO

    # --- broker-level evidence ---

    def test_broker_isr_override_to_3_is_advisory(self, base_cfg):
        base_cfg["broker_configs"]["min.insync.replicas"] = "3"
        verdict, ev = c.assess_configs(base_cfg)
        assert verdict == c.ADVISORY
        assert "BROKER_CONFIG_FORCED_VALUE" in codes(ev)

    def test_broker_unclean_leader_election_override_is_advisory(self, base_cfg):
        base_cfg["broker_configs"]["unclean.leader.election.enable"] = "true"
        verdict, ev = c.assess_configs(base_cfg)
        assert verdict == c.ADVISORY
        assert "BROKER_CONFIG_FORCED_VALUE" in codes(ev)

    def test_broker_read_only_override_is_advisory(self, base_cfg):
        # num.io.threads is RO; default is 8. 16 is non-default.
        base_cfg["broker_configs"]["num.io.threads"] = "16"
        verdict, ev = c.assess_configs(base_cfg)
        assert verdict == c.ADVISORY
        assert "BROKER_CONFIG_READ_ONLY" in codes(ev)

    def test_broker_unknown_config_is_advisory(self, base_cfg):
        base_cfg["broker_configs"]["log.segment.bytes"] = "536870912"
        verdict, ev = c.assess_configs(base_cfg)
        assert verdict == c.ADVISORY
        assert "BROKER_CONFIG_NOT_EXPOSED" in codes(ev)

    def test_broker_rw_out_of_range_is_action(self, base_cfg):
        # log.cleaner.max.compaction.lag.ms minimum is 1 day.
        base_cfg["broker_configs"]["log.cleaner.max.compaction.lag.ms"] = "43200000"
        verdict, ev = c.assess_configs(base_cfg)
        assert verdict == c.ACTION_REQUIRED
        assert "BROKER_CONFIG_OUT_OF_RANGE" in codes(ev)

    # --- per-topic evidence ---

    def test_topic_rf_not_3_is_advisory(self, base_cfg):
        base_cfg["topics"][0]["replication_factor"] = 2
        verdict, ev = c.assess_configs(base_cfg)
        assert verdict == c.ADVISORY
        assert "TOPIC_RF_NOT_3" in codes(ev)

    def test_topic_max_compaction_lag_below_min_is_action(self, base_cfg):
        base_cfg["topics"][0]["configs"]["max.compaction.lag.ms"] = "43200000"
        verdict, ev = c.assess_configs(base_cfg)
        assert verdict == c.ACTION_REQUIRED
        assert "TOPIC_CONFIG_OUT_OF_RANGE" in codes(ev)

    def test_topic_min_isr_override_is_advisory(self, base_cfg):
        base_cfg["topics"][0]["configs"]["min.insync.replicas"] = "3"
        verdict, ev = c.assess_configs(base_cfg)
        assert verdict == c.ADVISORY
        assert "TOPIC_CONFIG_FORCED_VALUE" in codes(ev)

    def test_topic_unknown_config_is_advisory(self, base_cfg):
        base_cfg["topics"][0]["configs"]["segment.bytes"] = "1073741824"
        verdict, ev = c.assess_configs(base_cfg)
        assert verdict == c.ADVISORY
        assert "TOPIC_CONFIG_NOT_EXPOSED" in codes(ev)


# ---------------------------------------------------------------------------
# Pillar 4 — Auth
# ---------------------------------------------------------------------------


class TestAuthPillar:
    def test_baseline_is_info(self, base_cfg):
        verdict, ev = c.assess_auth(base_cfg)
        assert verdict == c.INFO
        assert ev == []

    def test_unauthenticated_is_info(self, base_cfg):
        # Express supports unauthenticated access; it is INFO (no evidence).
        base_cfg["security"]["authentication"] = "UNAUTHENTICATED"
        verdict, ev = c.assess_auth(base_cfg)
        assert verdict == c.INFO
        assert ev == []

    def test_unauthenticated_plaintext_is_info(self, base_cfg):
        # Plaintext is permitted with unauthenticated access, so no encryption
        # finding fires (the TLS requirement is coupled to authenticated mechs).
        base_cfg["security"]["authentication"] = "UNAUTHENTICATED"
        base_cfg["security"]["encryption_in_transit"] = "PLAINTEXT"
        verdict, ev = c.assess_auth(base_cfg)
        assert verdict == c.INFO
        assert ev == []

    def test_plaintext_with_authenticated_mech_is_action_required(self, base_cfg):
        # base_cfg auth is SASL_SCRAM (authenticated) -> TLS required.
        base_cfg["security"]["encryption_in_transit"] = "PLAINTEXT"
        verdict, ev = c.assess_auth(base_cfg)
        assert verdict == c.ACTION_REQUIRED
        assert "ENCRYPTION_NOT_TLS" in codes(ev)

    def test_tls_plaintext_with_authenticated_mech_is_action_required(self, base_cfg):
        base_cfg["security"]["encryption_in_transit"] = "TLS_PLAINTEXT"
        verdict, ev = c.assess_auth(base_cfg)
        assert verdict == c.ACTION_REQUIRED
        assert "ENCRYPTION_NOT_TLS" in codes(ev)

    @pytest.mark.parametrize("auth", ["TLS", "SASL_SCRAM", "SASL_IAM"])
    def test_authenticated_mechanisms_are_info(self, base_cfg, auth):
        base_cfg["security"]["authentication"] = auth
        verdict, ev = c.assess_auth(base_cfg)
        assert verdict == c.INFO
        assert ev == []

    def test_oauthbearer_is_action_required(self, base_cfg):
        # OAUTHBEARER from a self-managed source means a custom OAuth provider
        # that Express does not support.
        base_cfg["security"]["authentication"] = "SASL_OAUTHBEARER"
        verdict, ev = c.assess_auth(base_cfg)
        assert verdict == c.ACTION_REQUIRED
        assert "AUTH_OAUTHBEARER_NOT_SUPPORTED" in codes(ev)

    def test_other_mechanism_is_action_required(self, base_cfg):
        # OTHER captures unsupported mechanisms (SASL/GSSAPI, SASL/PLAIN, ...).
        base_cfg["security"]["authentication"] = "OTHER"
        verdict, ev = c.assess_auth(base_cfg)
        assert verdict == c.ACTION_REQUIRED
        assert "AUTH_MECHANISM_NOT_SUPPORTED" in codes(ev)

    def test_unknown_auth_is_advisory(self, base_cfg):
        base_cfg["security"]["authentication"] = "UNKNOWN"
        verdict, ev = c.assess_auth(base_cfg)
        assert verdict == c.ADVISORY
        assert "AUTH_UNKNOWN" in codes(ev)

    def test_unknown_encryption_is_advisory(self, base_cfg):
        base_cfg["security"]["encryption_in_transit"] = "UNKNOWN"
        verdict, ev = c.assess_auth(base_cfg)
        assert verdict == c.ADVISORY
        assert "ENCRYPTION_UNKNOWN" in codes(ev)

    def test_missing_security_block_is_advisory_unknowns(self, base_cfg):
        # B1 fix: an absent security block yields calm UNKNOWN advisories,
        # not a false ENCRYPTION_NOT_TLS.
        del base_cfg["security"]
        verdict, ev = c.assess_auth(base_cfg)
        assert verdict == c.ADVISORY
        assert "AUTH_UNKNOWN" in codes(ev)
        assert "ENCRYPTION_UNKNOWN" in codes(ev)
        assert "ENCRYPTION_NOT_TLS" not in codes(ev)


# ---------------------------------------------------------------------------
# Pillar 5 — Quotas
# ---------------------------------------------------------------------------


class TestQuotasPillar:
    def test_baseline_is_info(self, base_cfg):
        verdict, ev = c.assess_quotas(base_cfg)
        assert verdict == c.INFO
        assert ev == []

    def test_metrics_missing_is_advisory(self, base_cfg):
        del base_cfg["metrics"]
        verdict, ev = c.assess_quotas(base_cfg)
        assert verdict == c.ADVISORY
        assert "METRICS_MISSING" in codes(ev)

    def test_ingress_above_limit_is_advisory(self, base_cfg):
        base_cfg["metrics"]["peak_bytes_in_per_broker_mbps"] = 800
        verdict, ev = c.assess_quotas(base_cfg)
        assert verdict == c.ADVISORY
        assert "INGRESS_OVER_MAX_BROKER" in codes(ev)

    def test_partitions_above_limit_is_advisory(self, base_cfg):
        base_cfg["metrics"]["peak_partitions_per_broker"] = 33_000
        verdict, ev = c.assess_quotas(base_cfg)
        assert verdict == c.ADVISORY
        assert "PARTITIONS_OVER_MAX_BROKER" in codes(ev)

    @pytest.mark.parametrize("iam_auth", ["SASL_IAM", "SASL_OAUTHBEARER"])
    def test_iam_connections_above_limit_is_advisory(self, base_cfg, iam_auth):
        # IAM connection cap applies to both IAM-resolving mechanisms.
        base_cfg["security"]["authentication"] = iam_auth
        base_cfg["metrics"]["peak_connections_per_broker"] = 4_000
        verdict, ev = c.assess_quotas(base_cfg)
        assert verdict == c.ADVISORY
        assert "CONNECTIONS_OVER_IAM_LIMIT" in codes(ev)

    def test_non_iam_connections_above_3000_does_not_trigger(self, base_cfg):
        base_cfg["security"]["authentication"] = "SASL_SCRAM"
        base_cfg["metrics"]["peak_connections_per_broker"] = 4_000
        verdict, ev = c.assess_quotas(base_cfg)
        assert "CONNECTIONS_OVER_IAM_LIMIT" not in codes(ev)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_accepts_well_formed(self, base_cfg):
        c.validate_input(base_cfg)

    def test_rejects_missing_top_level(self, base_cfg):
        del base_cfg["topology"]
        with pytest.raises(ValueError):
            c.validate_input(base_cfg)

    def test_rejects_missing_kafka_version(self, base_cfg):
        del base_cfg["kafka"]["version"]
        with pytest.raises(ValueError):
            c.validate_input(base_cfg)

    def test_rejects_topics_not_a_list(self, base_cfg):
        base_cfg["topics"] = {}
        with pytest.raises(ValueError):
            c.validate_input(base_cfg)

    def test_rejects_unknown_encryption_value(self, base_cfg):
        base_cfg["security"]["encryption_in_transit"] = "TLS_only"
        with pytest.raises(ValueError, match="encryption_in_transit"):
            c.validate_input(base_cfg)

    def test_rejects_unknown_authentication_value(self, base_cfg):
        base_cfg["security"]["authentication"] = "SASL/SCRAM-SHA-512"
        with pytest.raises(ValueError, match="authentication"):
            c.validate_input(base_cfg)

    def test_accepts_other_authentication(self, base_cfg):
        # OTHER is a valid enum value (catch-all). Validation passes; the
        # auth pillar is what flags it as ACTION_REQUIRED.
        base_cfg["security"]["authentication"] = "OTHER"
        c.validate_input(base_cfg)  # no raise

    def test_accepts_unknown_security_values(self, base_cfg):
        # UNKNOWN is a valid enum value for both fields; the auth pillar emits
        # ADVISORY findings for it rather than failing validation.
        base_cfg["security"]["authentication"] = "UNKNOWN"
        base_cfg["security"]["encryption_in_transit"] = "UNKNOWN"
        c.validate_input(base_cfg)  # no raise


# ---------------------------------------------------------------------------
# End-to-end via assess() — including the bucketing-bug fix
# ---------------------------------------------------------------------------


class TestAssess:
    def test_baseline_overall_is_info(self, base_cfg):
        doc = c.assess(base_cfg)
        assert doc["overall"] == c.INFO
        assert set(doc["pillars"]) == {
            "topology",
            "kafka_version",
            "configs",
            "auth",
            "quotas",
        }

    def test_action_required_one_pillar_drives_overall(self, base_cfg):
        base_cfg["security"]["authentication"] = "OTHER"  # auth ACTION_REQUIRED
        doc = c.assess(base_cfg)
        assert doc["overall"] == c.ACTION_REQUIRED

    def test_evidence_carries_severity(self, base_cfg):
        base_cfg["topology"]["num_azs"] = 2
        doc = c.assess(base_cfg)
        topo_ev = doc["pillars"]["topology"]["evidence"]
        assert all("severity" in ev for ev in topo_ev)

    def test_summary_buckets_per_finding_not_per_pillar(self, base_cfg):
        # A finding is bucketed by its OWN severity, not its pillar's rolled-up
        # verdict. The auth pillar emits BOTH severities at once:
        #   authentication=OTHER       -> AUTH_MECHANISM_NOT_SUPPORTED (ACTION_REQUIRED)
        #   encryption_in_transit=UNKNOWN -> ENCRYPTION_UNKNOWN (ADVISORY)
        # The pillar rolls up to ACTION_REQUIRED, so this exercises the bug
        # where an ADVISORY finding could be mis-bucketed as ACTION_REQUIRED
        # because of its pillar's verdict.
        base_cfg["security"]["authentication"] = "OTHER"
        base_cfg["security"]["encryption_in_transit"] = "UNKNOWN"
        doc = c.assess(base_cfg)
        assert doc["pillars"]["auth"]["verdict"] == c.ACTION_REQUIRED
        assert "ENCRYPTION_UNKNOWN" in doc["summary"]["advisory_codes"]
        assert "AUTH_MECHANISM_NOT_SUPPORTED" in doc["summary"]["action_required_codes"]
        # The bug we're guarding against: the ADVISORY finding must NOT land in
        # action_required_codes just because its pillar rolled up to ACTION_REQUIRED.
        assert "ENCRYPTION_UNKNOWN" not in doc["summary"]["action_required_codes"]


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


class TestCLI:
    def test_main_writes_expected_file(self, base_cfg, tmp_path):
        in_path = tmp_path / "cluster-config.json"
        in_path.write_text(json.dumps(base_cfg))
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        rc = c.main([str(in_path), "--out-dir", str(out_dir)])
        assert rc == 0
        out_path = out_dir / "compatibility.test-cluster.json"
        assert out_path.exists()
        doc = json.loads(out_path.read_text())
        assert doc["overall"] == c.INFO


# ---------------------------------------------------------------------------
# _check_range — bound rendering and trigger logic
#
# Open bounds (None) render as INT_MIN / INT_MAX in the customer-facing detail
# string, while the machine-readable `limit` field keeps the raw [lo, hi]
# (with None) untouched. The comparison itself is inclusive at both ends.
# ---------------------------------------------------------------------------

DAY_MS = 24 * 60 * 60 * 1000  # 86_400_000


class TestCheckRangeBounds:
    def test_min_only_below_renders_int_max_upper(self):
        r = c._check_range(
            "log.cleaner.max.compaction.lag.ms", "43200000", (DAY_MS, None), "Your cluster"
        )
        assert r is not None
        assert f"[{DAY_MS}, INT_MAX]" in r["detail"]
        assert "+∞" not in r["detail"] and "None" not in r["detail"]
        assert "outside that range" in r["detail"]
        assert "can't be migrated as-is" in r["detail"]
        # machine-readable limit keeps the raw bound (None, not INT_MAX)
        assert r["limit"] == [DAY_MS, None]
        assert r["observed"] == 43200000

    def test_min_only_at_boundary_is_ok(self):
        # Inclusive lower bound: a value exactly at the minimum is in range.
        assert c._check_range("k", str(DAY_MS), (DAY_MS, None), "Your cluster") is None

    def test_min_only_above_is_ok(self):
        assert c._check_range("k", "99999999999", (DAY_MS, None), "Your cluster") is None

    def test_max_only_above_renders_int_min_lower(self):
        r = c._check_range("k", "500", (None, 100), "Your cluster")
        assert r is not None
        assert "[INT_MIN, 100]" in r["detail"]
        assert "-∞" not in r["detail"] and "None" not in r["detail"]
        assert r["limit"] == [None, 100]

    def test_max_only_at_boundary_is_ok(self):
        assert c._check_range("k", "100", (None, 100), "Your cluster") is None

    def test_both_bounds_render_literally(self):
        below = c._check_range("k", "5", (10, 100), "Your cluster")
        above = c._check_range("k", "500", (10, 100), "Your cluster")
        assert below is not None and "[10, 100]" in below["detail"]
        assert above is not None and "[10, 100]" in above["detail"]
        assert c._check_range("k", "50", (10, 100), "Your cluster") is None

    def test_non_integer_uses_integer_form_message(self):
        r = c._check_range("k", "1.5", (DAY_MS, None), "Your cluster")
        assert r is not None
        assert "to be an integer within" in r["detail"]
        assert f"[{DAY_MS}, INT_MAX]" in r["detail"]
        assert "not a valid integer" in r["detail"]
        assert r["observed"] == "1.5"

    def test_negative_value_below_min_fires(self):
        r = c._check_range("k", "-5", (DAY_MS, None), "Your cluster")
        assert r is not None
        assert "outside that range" in r["detail"]
        assert r["observed"] == -5

    def test_subject_is_substituted(self):
        broker = c._check_range("k", "1", (DAY_MS, None), "Your cluster")
        topic = c._check_range("k", "1", (DAY_MS, None), "Topic 'orders'")
        assert broker["detail"].count("Your cluster sets it to") == 1
        assert topic["detail"].startswith("MSK Express accepts")
        assert "Topic 'orders' sets it to" in topic["detail"]
