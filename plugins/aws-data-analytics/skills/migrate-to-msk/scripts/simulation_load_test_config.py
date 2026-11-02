#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Deterministic compute + guardrail engine for the MSK Express load-test simulation.

Three actions:
  compute  — given cluster sizing (instance_type, broker_count), emit all derived
             values: cluster capacity, auto-sized client fleet, and per-test
             default parameters + bounds. Feeds CFN parameters and test templates.
  render   — given the same sizing, write a local, ready-to-deploy copy of the
             CloudFormation template with the customer's sizing AND the computed
             fleet baked in as parameter Defaults. The source template stays static;
             this emits a derived artifact to a working-directory path so the customer
             deploys from a local file (never from the skill source). The Kafka client
             is installed post-deploy via SSM, so nothing client-related is baked here.
  validate — given a test type and a proposed config, return PASS/REJECT plus
             inline WARNINGS. The agent loops back on REJECT, surfaces WARNINGS
             as one-sentence notes and proceeds.

Run with:
  uv run <script> compute  --instance-type express.m7g.4xlarge --broker-count 12
  uv run <script> render   --instance-type express.m7g.4xlarge --broker-count 12 \
      --kafka-version 3.9.x.kraft \
      --output migrate-to-msk-skill-artifacts/simulation/simulation-stack.yaml
  uv run <script> validate --test e2e_latency   --config '{"throughput_mbps":10,...}'
  uv run <script> validate --test broker_restart --config '{...}' \
      --instance-type express.m7g.4xlarge --broker-count 12
"""
import argparse
import json
import math
import sys
from pathlib import Path

# The static source template lives alongside this script in the skill package.
# It is resolved internally and never surfaced to the customer — render() emits a
# derived local copy, and all customer-facing commands point at that copy instead.
SOURCE_TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "simulation-stack.yaml"

# Express per-broker INGRESS throttle limits (MB/s), from AWS Express docs:
#   (sustained, max_quota)
# sustained = recommended threshold (no performance degradation up to here);
# max_quota = hard ceiling (the cluster throttles read/write traffic beyond it).
# Full table including egress lives in references/simulation.md.
PER_BROKER_INGRESS = {
    "express.m7g.large": (15.6, 23.4),
    "express.m7g.xlarge": (31.2, 46.8),
    "express.m7g.2xlarge": (62.5, 93.7),
    "express.m7g.4xlarge": (124.9, 187.5),
    "express.m7g.8xlarge": (250.0, 375.0),
    "express.m7g.12xlarge": (375.0, 562.5),
    "express.m7g.16xlarge": (500.0, 750.0),
}

# The only valid Express version + metadata-mode combinations, as the exact CFN
# KafkaVersion strings the template's AllowedValues accepts. On Express, 3.9 is
# KRaft-only (no ZooKeeper variant) and KRaft is unavailable below 3.9, so these
# three are the whole set. Validated here so a freeform/unsupported version is
# rejected locally instead of failing ~40 min into create-stack.
SUPPORTED_KAFKA_VERSIONS = ("3.6.0", "3.8.x", "3.9.x.kraft")

# Fixed client fleet instance type -- one size for all clusters, only count varies.
# c5.2xlarge: 10 Gbps sustained baseline (no burst credits), $0.34/hr.
# 400 MB/s is a conservative per-node Kafka producer throughput target accounting
# for TLS overhead, acks=all latency, and batching inefficiency.
FLEET_INSTANCE_TYPE = "c5.2xlarge"
FLEET_NODE_THROUGHPUT_MBPS = 400


def compute(instance_type, broker_count, kafka_version=None):
    if instance_type not in PER_BROKER_INGRESS:
        raise ValueError(
            f"unknown instance_type {instance_type!r}; valid: {list(PER_BROKER_INGRESS)}"
        )
    if broker_count < 3 or broker_count % 3 != 0:
        raise ValueError("broker_count must be a multiple of 3 and >= 3")
    # Only validate the version when one is supplied; sizing math doesn't need it,
    # but rejecting an unsupported value here keeps a freeform answer from reaching
    # create-stack. 3.9 ZooKeeper (e.g. "3.9.x") is intentionally not in the set.
    if kafka_version is not None and kafka_version not in SUPPORTED_KAFKA_VERSIONS:
        raise ValueError(
            f"unsupported kafka_version {kafka_version!r}; valid: "
            f"{list(SUPPORTED_KAFKA_VERSIONS)} (3.9 is KRaft-only on Express)"
        )

    per_broker_sustained, per_broker_max = PER_BROKER_INGRESS[instance_type]
    cluster_sustained_ingress = round(per_broker_sustained * broker_count, 1)
    cluster_max_ingress = round(per_broker_max * broker_count, 1)
    fleet_bandwidth = FLEET_NODE_THROUGHPUT_MBPS
    # Provision 1.5x the cluster's MAXIMUM ingress quota so the fleet can drive the
    # cluster all the way to its throttle ceiling with headroom and never be the
    # bottleneck (even when deliberately probing past the limit).
    fleet_producer_count = max(2, math.ceil(cluster_max_ingress * 1.5 / fleet_bandwidth))
    fleet_consumer_count = fleet_producer_count
    fleet_max_mbps = fleet_producer_count * fleet_bandwidth
    default_target = round(cluster_sustained_ingress * 0.8)

    return {
        "instance_type": instance_type,
        "broker_count": broker_count,
        "supported_kafka_versions": list(SUPPORTED_KAFKA_VERSIONS),
        "cluster_sustained_ingress_mbps": cluster_sustained_ingress,
        "cluster_max_ingress_mbps": cluster_max_ingress,
        "fleet_instance_type": FLEET_INSTANCE_TYPE,
        "fleet_instance_bandwidth_mbps": fleet_bandwidth,
        "fleet_producer_count": fleet_producer_count,
        "fleet_consumer_count": fleet_consumer_count,
        "fleet_max_mbps": fleet_max_mbps,
        "default_target_throughput_mbps": default_target,
        "tests": {
            "e2e_latency": {
                "throughput_mbps": {"default": 10, "min": 1, "max": fleet_max_mbps},
                "duration_minutes": {"default": 10, "min": 5, "max": 120},
                "num_producers": {"default": 1, "min": 1, "max": fleet_producer_count},
                "num_consumers": {"default": 1, "min": 1, "max": fleet_consumer_count},
            },
            "broker_restart": {
                "target_throughput_mbps": {
                    "default": default_target,
                    "min": 1,
                    "max": fleet_max_mbps,
                },
                "duration_minutes": {"default": 15, "min": 10, "max": 120},
                "reboot_at_minute": {"default": 5, "min": 2, "max": None},  # max = duration-2
                "num_producers": {
                    "default": fleet_producer_count,
                    "min": 1,
                    "max": fleet_producer_count,
                },
            },
        },
    }


def _set_param_default(template_text, param_name, value):
    """Set the `Default:` of a top-level CloudFormation parameter in-place.

    The template is static and authored with each parameter at 2-space indent and
    its properties at 4-space indent. We locate the parameter block and rewrite its
    existing `Default:` line (every baked parameter already declares one). Raises if
    the parameter or its Default line is missing, so a template drift fails loudly
    here rather than silently producing an unsized stack.
    """
    lines = template_text.splitlines()
    out = []
    i = 0
    n = len(lines)
    replaced = False
    header = f"  {param_name}:"
    while i < n:
        line = lines[i]
        out.append(line)
        if line == header:
            # Walk this parameter's property lines (indented deeper than 2 spaces).
            i += 1
            block_done = False
            while i < n:
                prop = lines[i]
                # End of block: a line that isn't blank and is indented <= 2 spaces.
                if prop.strip() and (len(prop) - len(prop.lstrip(" "))) <= 2:
                    break
                stripped = prop.lstrip(" ")
                if stripped.startswith("Default:") and not block_done:
                    indent = " " * (len(prop) - len(stripped))
                    out.append(f"{indent}Default: {value}")
                    replaced = True
                    block_done = True
                else:
                    out.append(prop)
                i += 1
            continue
        i += 1
    if not replaced:
        raise ValueError(
            f"could not set Default for parameter {param_name!r}; the source template "
            "may have drifted (expected a 2-space-indented block with a Default line)"
        )
    # Preserve a trailing newline if the original had one.
    text = "\n".join(out)
    if template_text.endswith("\n"):
        text += "\n"
    return text


def render(instance_type, broker_count, kafka_version, output_path):
    """Write a local, ready-to-deploy copy of the template with sizing baked in.

    Reads the static source template internally, bakes the customer's sizing and the
    computed fleet counts in as parameter Defaults, and writes the result to
    output_path. The customer deploys from that local file; the skill source path is
    never exposed.

    The output path is resolved to an ABSOLUTE path (relative paths resolve against
    the current working directory) and the resolved location is returned, so the
    caller never has to guess where the file landed. As a safety rail, the resolved
    path must NOT be inside the skill package -- that both keeps the skill source
    clean and prevents the customer-facing artifact from ever pointing back at the
    install directory.
    """
    caps = compute(instance_type, broker_count, kafka_version)

    # Resolve to absolute up front so the returned path is unambiguous regardless of
    # the directory the script was launched from.
    out = Path(output_path).expanduser().resolve()
    skill_root = SOURCE_TEMPLATE.parent.parent  # .../skills/migrate-to-msk
    if out == skill_root or skill_root in out.parents:
        raise ValueError(
            f"refusing to write the rendered template inside the skill package "
            f"({skill_root}); choose an output path under the customer's working "
            f"directory instead, e.g. "
            f"$(pwd)/migrate-to-msk-skill-artifacts/simulation/simulation-stack.yaml"
        )

    template_text = SOURCE_TEMPLATE.read_text()

    baked = {
        "InstanceType": instance_type,
        "BrokerCount": broker_count,
        "KafkaVersion": kafka_version,
        "ClientInstanceType": caps["fleet_instance_type"],
        "ProducerCount": caps["fleet_producer_count"],
        "ConsumerCount": caps["fleet_consumer_count"],
    }
    for name, value in baked.items():
        template_text = _set_param_default(template_text, name, value)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(template_text)

    return {
        "output_path": str(out),
        "deploy_command": (
            f"aws cloudformation create-stack --stack-name msk-express-simulation "
            f"--template-body file://{out} --capabilities CAPABILITY_IAM "
            f"--region <region>"
        ),
        "baked_parameters": baked,
        "fleet_producer_count": caps["fleet_producer_count"],
        "fleet_consumer_count": caps["fleet_consumer_count"],
        "fleet_instance_type": caps["fleet_instance_type"],
    }


def _check_range(name, val, lo, hi, errors):
    if val < lo or (hi is not None and val > hi):
        errors.append(f"{name}={val} is outside the allowed range [{lo}, {hi}]")


def _throughput_warnings(name, tput, sustained, max_quota, warnings):
    """Tiered throughput warning. Returns True if a degradation/throttle warning fired.
    > max_quota  -> cluster THROTTLES (hard ceiling; cannot be sustained).
    > sustained  -> performance DEGRADATION (elevated latency), but no throttling yet."""
    if tput > max_quota:
        warnings.append(
            f"{name}={tput} MB/s exceeds the cluster's maximum ingress quota "
            f"({max_quota} MB/s) — MSK Express throttles read/write traffic beyond this, "
            f"so the cluster cannot actually sustain that rate."
        )
        return True
    if tput > sustained:
        warnings.append(
            f"{name}={tput} MB/s is above the cluster's sustained/recommended ingress "
            f"({sustained} MB/s); it can run but expect performance degradation "
            f"(elevated latency), with no throttling until the {max_quota} MB/s ceiling."
        )
        return True
    return False


def validate(test, config, caps):
    """caps = output of compute(). Returns {decision, errors, warnings}."""
    errors: list[str] = []
    warnings: list[str] = []
    fleet_max = caps["fleet_max_mbps"]
    sustained = caps["cluster_sustained_ingress_mbps"]
    max_quota = caps["cluster_max_ingress_mbps"]
    fleet_bw = caps["fleet_instance_bandwidth_mbps"]
    fleet_prod = caps["fleet_producer_count"]

    if test == "e2e_latency":
        tput = config["throughput_mbps"]
        dur = config["duration_minutes"]
        prod = config["num_producers"]
        cons = config["num_consumers"]
        _check_range("throughput_mbps", tput, 1, fleet_max, errors)
        _check_range("duration_minutes", dur, 5, 120, errors)
        _check_range("num_producers", prod, 1, fleet_prod, errors)
        _check_range("num_consumers", cons, 1, caps["fleet_consumer_count"], errors)
        if not _throughput_warnings("throughput_mbps", tput, sustained, max_quota, warnings):
            if tput > sustained * 0.6:
                warnings.append(
                    f"throughput_mbps={tput} is above 60% of sustained ingress; high load "
                    f"can inflate latency. For a clean signal, consider <= {round(sustained * 0.5)} MB/s."
                )
        if prod < math.ceil(tput / fleet_bw):
            warnings.append(
                f"num_producers={prod} may not sustain {tput} MB/s; "
                f"consider >= {math.ceil(tput / fleet_bw)} producers."
            )

    elif test == "broker_restart":
        tput = config["target_throughput_mbps"]
        dur = config["duration_minutes"]
        reboot = config["reboot_at_minute"]
        prod = config["num_producers"]
        _check_range("target_throughput_mbps", tput, 1, fleet_max, errors)
        _check_range("duration_minutes", dur, 10, 120, errors)
        _check_range("reboot_at_minute", reboot, 2, dur - 2, errors)
        _check_range("num_producers", prod, 1, fleet_prod, errors)
        if not _throughput_warnings("target_throughput_mbps", tput, sustained, max_quota, warnings):
            if tput > sustained * 0.6:
                warnings.append(
                    f"target_throughput_mbps={tput} is above 60% of sustained ingress; "
                    "broker-CPU headroom during the restart is limited, so recovery may take longer."
                )
        if prod < math.ceil(tput / fleet_bw):
            warnings.append(
                f"num_producers={prod} may not sustain {tput} MB/s; "
                f"consider >= {math.ceil(tput / fleet_bw)} producers."
            )
    else:
        errors.append(f"unknown test {test!r}; valid: e2e_latency, broker_restart")

    return {
        "decision": "REJECT" if errors else "PASS",
        "errors": errors,
        "warnings": warnings,
    }


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="action", required=True)

    c = sub.add_parser("compute", help="Emit derived sizing + per-test defaults/bounds.")
    c.add_argument("--instance-type", default="express.m7g.4xlarge")
    c.add_argument("--broker-count", type=int, default=12)
    c.add_argument(
        "--kafka-version",
        default=None,
        help="Optional. If given, rejected unless one of: " + ", ".join(SUPPORTED_KAFKA_VERSIONS),
    )

    r = sub.add_parser(
        "render",
        help="Write a local ready-to-deploy template with sizing baked in as Defaults.",
    )
    r.add_argument("--instance-type", required=True)
    r.add_argument("--broker-count", type=int, required=True)
    r.add_argument(
        "--kafka-version",
        required=True,
        help="Required. One of: " + ", ".join(SUPPORTED_KAFKA_VERSIONS),
    )
    r.add_argument(
        "--output",
        required=True,
        help="Path for the filled template. Resolved to an absolute path "
        "(relative paths resolve against the current directory); pass an absolute "
        "path under the customer's working directory, e.g. "
        "$(pwd)/migrate-to-msk-skill-artifacts/simulation/simulation-stack.yaml. "
        "Must not be inside the skill package.",
    )

    v = sub.add_parser("validate", help="Validate a proposed test config.")
    v.add_argument("--test", required=True, choices=["e2e_latency", "broker_restart"])
    v.add_argument("--config", required=True, help="JSON object of test parameters.")
    v.add_argument("--instance-type", default="express.m7g.4xlarge")
    v.add_argument("--broker-count", type=int, default=12)
    return p.parse_args()


def main():
    args = parse_args()
    try:
        if args.action == "render":
            result = render(args.instance_type, args.broker_count, args.kafka_version, args.output)
            print(json.dumps(result, indent=2))
            return
        # validate has no --kafka-version arg; getattr keeps the shared compute() call safe.
        caps = compute(args.instance_type, args.broker_count, getattr(args, "kafka_version", None))
        if args.action == "compute":
            print(json.dumps(caps, indent=2))
        else:
            result = validate(args.test, json.loads(args.config), caps)
            print(json.dumps(result, indent=2))
            if result["decision"] == "REJECT":
                sys.exit(1)
    except (ValueError, KeyError, json.JSONDecodeError, OSError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
