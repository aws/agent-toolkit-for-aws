"""
Command classification for ElastiCache Serverless ECPU estimation.

Serverless bills ECPUs based on both vCPU time and data transferred:

  Simple commands (e.g., GET, SET, HGET):
    1 ECPU per kilobyte (KB) of data transferred, minimum 1 ECPU.
    For example, a GET returning 3.2 KB costs 3.2 ECPUs.
    These are O(1) operations with predictable cost.

  Complex commands (e.g., EVAL, SORT, MGET, HGETALL):
    The HIGHER of two dimensions: vCPU time (relative to a baseline
    GET/SET) or data transferred in KB. The two dimensions are NOT
    additive. For example, a SORT at 3x vCPU time transferring 2 KB
    costs 3 ECPUs (vCPU dimension wins).

    NOTE: This module uses a heuristic approximation for the vCPU
    dimension. AWS documentation does not publish the exact ECPU
    calculation formula. AWS states that "the number of ECPUs consumed
    by your requests depends on the vCPU time taken and the amount of
    data transferred" and that the higher dimension determines the cost.
    Actual ECPU consumption may differ from this estimate.

  Internal/service commands (e.g., REPLCONF, PSYNC, CLUSTER):
    Excluded from estimates. Includes commands that are not metered
    (AUTH, MULTI, EXEC, SUBSCRIBE, UNSUBSCRIBE, CONFIG, CLUSTER),
    replication internals (REPLCONF, PSYNC), and commands ignored by
    the metering system (INFO, PUBLISH). If your workload issues a
    high volume of commands not covered by this classifier, actual
    ECPU costs may differ from the estimate. Use CloudWatch ECPU
    metrics for precise serverless billing.

IMPORTANT: The simple/complex classification and specific ECPU formulas used
in this module are heuristic approximations based on publicly available AWS
documentation and pricing examples. AWS does not publish exact ECPU calculation
formulas. Per AWS docs, "the number of ECPUs consumed by your requests depends
on the vCPU time taken and the amount of data transferred." For accurate
billing data, use CloudWatch ElastiCacheProcessingUnits and per-command ECPU
metrics on serverless caches.

Reference: https://aws.amazon.com/elasticache/pricing/
"""

# Simple (fixed) commands - 1 ECPU per KB transferred (minimum 1 ECPU).
# Based on ElastiCache Serverless pricing documentation.
# Any command not listed here or in INTERNAL_COMMANDS falls through to
# nonfixed (complex), which uses MAX(calls, usec/3) as a conservative estimate.
FIXED_COMMANDS = frozenset([
    "get", "set", "hget", "hset",
    "incr", "decr", "incrby", "decrby", "incrbyfloat",
    "expire", "pexpire", "pexpireat", "expireat", "persist",
    "exists", "ttl", "pttl", "type", "strlen",
    "scard", "zcard", "llen", "xlen",
    "sismember", "hexists", "hlen", "hsetnx",
    "hincrby", "hincrbyfloat",
    "getbit", "setbit", "setnx", "setex", "psetex",
    "zscore",
    "ping",
    "del", "unlink",
    "select", "echo", "time", "quit", "reset",
    "watch", "unwatch", "move", "asking",
    "readonly", "readwrite",
    "acl", "client", "command",
])

# Commands not metered by serverless - excluded from ECPU estimates.
# Includes free commands (AUTH, MULTI, EXEC, pub/sub) and ignored
# commands (INFO, PUBLISH). Also includes replication/cluster internals
# and commands not available on serverless.
INTERNAL_COMMANDS = frozenset([
    "auth", "multi", "exec", "hello", "discard",
    "subscribe", "unsubscribe", "psubscribe", "punsubscribe",
    "publish", "pubsub",
    "info", "config", "cluster",
    "replconf", "psync", "replicaof",
    "slowlog", "dbsize", "wait",
    "object", "debug", "memory", "latency",
    "module", "function", "swapdb",
])


def classify_command(cmd_name: str) -> str:
    """Classify a Redis/Valkey command.

    Returns:
        'fixed'    - 1 ECPU per call (simple O(1) commands)
        'nonfixed' - estimated as MAX(calls, usec/3) ECPUs (approximation)
        'internal' - not metered, exclude from estimate
    """
    cmd = cmd_name.lower().strip()
    if cmd in INTERNAL_COMMANDS:
        return "internal"
    if cmd in FIXED_COMMANDS:
        return "fixed"
    return "nonfixed"


def estimate_ecpus_from_commandstats(commandstats: dict) -> dict:
    """Estimate ECPUs from Redis/Valkey INFO commandstats output.

    Args:
        commandstats: Dict mapping command name -> {calls: int, usec: int}
            Example:
            {"get": {"calls": 1000000, "usec": 1500000},
             "eval": {"calls": 50000, "usec": 2000000}}

    Returns:
        Dict with:
            total_ecpus:        Estimated total ECPUs
            fixed_ecpus:        ECPUs from fixed-price commands
            nonfixed_ecpus:     ECPUs from non-fixed commands
            internal_calls:     Calls excluded (internal commands)
            command_breakdown:  Per-command detail list
    """
    fixed_ecpus = 0
    nonfixed_ecpus = 0
    internal_calls = 0
    breakdown = []

    for cmd, stats in commandstats.items():
        calls = stats.get("calls", 0)
        usec = stats.get("usec", 0)
        classification = classify_command(cmd)

        if classification == "internal":
            internal_calls += calls
            breakdown.append({
                "command": cmd, "type": "internal",
                "calls": calls, "usec": usec, "ecpus": 0,
            })
        elif classification == "fixed":
            ecpus = calls
            fixed_ecpus += ecpus
            breakdown.append({
                "command": cmd, "type": "fixed",
                "calls": calls, "usec": usec, "ecpus": ecpus,
            })
        else:
            # Non-fixed: MAX(calls, usec/3) - approximation based on the
            # assumption that 1 ECPU ~ 3 microseconds of vCPU time (derived
            # from the AWS pricing blog example). Actual ECPU consumption
            # may differ. See module docstring for details.
            ecpus = max(calls, usec / 3.0)
            nonfixed_ecpus += ecpus
            breakdown.append({
                "command": cmd, "type": "nonfixed",
                "calls": calls, "usec": usec, "ecpus": round(ecpus),
            })

    return {
        "total_ecpus": round(fixed_ecpus + nonfixed_ecpus),
        "fixed_ecpus": round(fixed_ecpus),
        "nonfixed_ecpus": round(nonfixed_ecpus),
        "internal_calls": internal_calls,
        "command_breakdown": sorted(
            breakdown, key=lambda x: x["ecpus"], reverse=True
        ),
    }
