#!/usr/bin/env python3
"""
ElastiCache Migration Preflight Check

Connects to a source Redis/Valkey instance and evaluates migration readiness:
- Engine version compatibility
- Module detection (RedisJSON, RediSearch, RedisTimeSeries, etc.)
- Key count and memory usage
- Persistence configuration
- Cluster mode detection
- Unsupported command sampling

Usage:
  # Check a source Redis instance (plain)
  python migration_preflight.py --host redis.example.com --port 6379

  # With TLS
  python migration_preflight.py --host redis.example.com --port 6379 --tls

  # With auth
  python migration_preflight.py --host redis.example.com --password mypassword

  # JSON output
  python migration_preflight.py --host redis.example.com --json

  # Via tunnel (local port forward)
  python migration_preflight.py --host localhost --port 6379

Requires: valkey (pip install valkey)
"""

import argparse
import json
import sys

# ---------------------------------------------------------------------------
# Dependency check -- fail early with an actionable message instead of a
# raw ImportError traceback.
# ---------------------------------------------------------------------------
try:
    import valkey as redis
except ImportError:
    print(
        "Error: the 'valkey' package is required for this script.\n"
        "Install with:\n"
        "  pip install valkey"
    )
    sys.exit(1)


# Commands not available on ElastiCache (restricted or modified)
ELASTICACHE_RESTRICTED_COMMANDS = {
    "BGSAVE", "BGREWRITEAOF", "CONFIG", "DEBUG", "MIGRATE",
    "SAVE", "SHUTDOWN", "SLAVEOF", "REPLICAOF", "SYNC",
}

# Known Redis modules and their ElastiCache availability
MODULE_COMPATIBILITY = {
    "search": {"name": "RediSearch", "elasticache": False, "note": "Not available on ElastiCache. Valkey 8.2 provides native vector search (FT.* commands) on node-based clusters."},
    "ReJSON": {"name": "RedisJSON", "elasticache": False, "note": "The ReJSON module cannot be loaded on ElastiCache. However, ElastiCache provides native JSON support (JSON.* commands) in Valkey 7.2+ and Redis OSS 6.2.6+. Verify command compatibility before migration."},
    "timeseries": {"name": "RedisTimeSeries", "elasticache": False, "note": "Not available on ElastiCache. Consider CloudWatch or Timestream."},
    "bf": {"name": "RedisBloom", "elasticache": False, "note": "No (module) / Yes (native BF.* commands in Valkey 8.1+)."},
    "graph": {"name": "RedisGraph", "elasticache": False, "note": "Deprecated. Consider Neptune or OpenSearch."},
    "ai": {"name": "RedisAI", "elasticache": False, "note": "Not available on ElastiCache. Use SageMaker for ML inference."},
}


def run_preflight(host, port, password=None, use_tls=False, username=None):
    """Run all preflight checks against a source Redis/Valkey instance."""
    findings = []
    info = {"host": host, "port": port}

    try:
        r = redis.Redis(
            host=host, port=port,
            password=password, username=username,
            ssl=use_tls,
            decode_responses=True,
            socket_timeout=10,
            socket_connect_timeout=10,
        )
        r.ping()
        findings.append({"check": "Connectivity", "status": "PASS", "detail": f"Connected to {host}:{port}"})
    except (redis.ConnectionError, redis.TimeoutError) as e:
        return {"error": f"Cannot connect to {host}:{port}: {e}", "info": info, "findings": [
            {"check": "Connectivity", "status": "FAIL", "detail": str(e)}
        ]}
    except redis.AuthenticationError as e:
        return {"error": f"Authentication failed: {e}", "info": info, "findings": [
            {"check": "Connectivity", "status": "FAIL", "detail": f"Auth failed: {e}"}
        ]}

    # Server info
    try:
        server_info = r.info()
    except Exception as e:
        findings.append({"check": "Server info", "status": "ERROR", "detail": f"Could not retrieve INFO: {e}"})
        r.close()
        return {"info": info, "findings": findings}

    # Engine and version
    redis_version = str(server_info.get("redis_version", "unknown"))
    info["redis_version"] = redis_version
    info["os"] = server_info.get("os", "unknown")
    info["uptime_days"] = round(server_info.get("uptime_in_seconds", 0) / 86400, 1)

    parts = redis_version.split(".")
    try:
        version_tuple = tuple(int(p) for p in parts[:2]) if len(parts) >= 2 else (int(parts[0]), 0)
    except (ValueError, IndexError):
        version_tuple = (0, 0)

    if version_tuple >= (7, 0):
        findings.append({"check": "Engine version", "status": "PASS",
                         "detail": f"Redis {redis_version} can migrate to Valkey 7.2 (direct in-place switch) or Redis OSS 7+ on ElastiCache"})
    elif version_tuple >= (6, 0):
        findings.append({"check": "Engine version", "status": "WARN",
                         "detail": f"Redis {redis_version} standard support ends January 31, 2027. Extended Support charges begin February 1, 2027. Recommend upgrading to Valkey before then."})
    elif version_tuple >= (5, 0):
        findings.append({"check": "Engine version", "status": "FAIL",
                         "detail": f"Redis {redis_version} standard support ended January 31, 2026. Extended Support charges are now active (since Feb 1, 2026). Upgrade to Valkey to eliminate surcharges."})
        findings.append({"check": "Extended Support", "status": "FAIL",
                         "detail": f"Redis {redis_version} is enrolled in Extended Support. Year 1-2 premium: 80% surcharge. Year 3 premium: 160% surcharge. Run scripts/price_calculator.py --extended-support to see costs."})
    else:
        findings.append({"check": "Engine version", "status": "FAIL",
                         "detail": f"Redis {redis_version} standard support ended January 31, 2026. Extended Support charges are now active. Upgrade to Valkey to eliminate surcharges."})
        findings.append({"check": "Extended Support", "status": "FAIL",
                         "detail": f"Redis {redis_version} is enrolled in Extended Support. Year 1-2 premium: 80% surcharge. Year 3 premium: 160% surcharge. Run scripts/price_calculator.py --extended-support to see costs."})

    # Cluster mode
    cluster_enabled = server_info.get("cluster_enabled", 0)
    info["cluster_mode"] = bool(cluster_enabled)
    if cluster_enabled:
        findings.append({"check": "Cluster mode", "status": "INFO",
                         "detail": "Cluster mode enabled — target must also be cluster mode enabled"})
    else:
        findings.append({"check": "Cluster mode", "status": "INFO",
                         "detail": "Standalone or replica mode — can target cluster mode disabled or enabled"})

    # Connected replicas
    connected_replicas = server_info.get("connected_slaves", 0)
    info["connected_replicas"] = connected_replicas
    findings.append({"check": "Replication", "status": "INFO",
                     "detail": f"{connected_replicas} connected replica(s)"})

    # Memory
    used_memory_mb = round(server_info.get("used_memory", 0) / (1024 * 1024), 1)
    used_memory_gb = round(used_memory_mb / 1024, 2)
    peak_memory_mb = round(server_info.get("used_memory_peak", 0) / (1024 * 1024), 1)
    info["used_memory_mb"] = used_memory_mb
    info["used_memory_gb"] = used_memory_gb
    info["peak_memory_mb"] = peak_memory_mb
    findings.append({"check": "Memory usage", "status": "INFO",
                     "detail": f"Current: {used_memory_mb} MB ({used_memory_gb} GB), Peak: {peak_memory_mb} MB"})

    # Key count
    try:
        db_info = {k: v for k, v in server_info.items() if k.startswith("db")}
        total_keys = sum(v.get("keys", 0) for v in db_info.values() if isinstance(v, dict))
        info["total_keys"] = total_keys
        info["databases_in_use"] = len(db_info)
        findings.append({"check": "Key count", "status": "INFO",
                         "detail": f"{total_keys:,} keys across {len(db_info)} database(s)"})

        if len(db_info) > 1:
            findings.append({"check": "Multiple databases", "status": "WARN",
                             "detail": f"{len(db_info)} databases in use — ElastiCache cluster mode uses only db0. Plan key migration."})
    except Exception:
        info["total_keys"] = "unknown"

    # Persistence
    rdb_enabled = server_info.get("rdb_last_save_time", 0) > 0
    aof_enabled = server_info.get("aof_enabled", 0) == 1
    info["rdb_enabled"] = rdb_enabled
    info["aof_enabled"] = aof_enabled
    persistence_detail = []
    if rdb_enabled:
        persistence_detail.append("RDB snapshots active")
    if aof_enabled:
        persistence_detail.append("AOF enabled")
    if not persistence_detail:
        persistence_detail.append("No persistence")
    findings.append({"check": "Persistence", "status": "INFO",
                     "detail": ", ".join(persistence_detail)})

    # Modules
    try:
        modules = r.execute_command("MODULE", "LIST")
        loaded_modules = []
        for mod in modules:
            if isinstance(mod, list):
                mod_name = mod[1] if len(mod) > 1 else str(mod)
            elif isinstance(mod, dict):
                mod_name = mod.get("name", str(mod))
            else:
                mod_name = str(mod)
            loaded_modules.append(mod_name)

        info["modules"] = loaded_modules

        if not loaded_modules:
            findings.append({"check": "Modules", "status": "PASS", "detail": "No modules loaded"})
        else:
            for mod_name in loaded_modules:
                compat = MODULE_COMPATIBILITY.get(mod_name)
                if compat:
                    if compat["elasticache"]:
                        findings.append({"check": f"Module: {compat['name']}", "status": "INFO",
                                         "detail": str(compat["note"])})
                    else:
                        findings.append({"check": f"Module: {compat['name']}", "status": "FAIL",
                                         "detail": str(compat["note"])})
                else:
                    findings.append({"check": f"Module: {mod_name}", "status": "WARN",
                                     "detail": f"Unknown module '{mod_name}' — verify compatibility with ElastiCache"})
    except redis.ResponseError:
        info["modules"] = []
        findings.append({"check": "Modules", "status": "INFO",
                         "detail": "MODULE LIST not available (may be restricted or old version)"})

    # Commandstats — check for restricted command usage
    cmdstats = {}
    try:
        cmdstats = r.info("commandstats")
        for cmd_name in ELASTICACHE_RESTRICTED_COMMANDS:
            stat_key = f"cmdstat_{cmd_name.lower().replace(' ', '|')}"
            if stat_key in cmdstats:
                calls = cmdstats[stat_key].get("calls", 0)
                if calls > 0:
                    findings.append({"check": "Restricted command usage", "status": "WARN",
                                     "detail": f"Command {cmd_name} called {calls} times. This command is restricted on ElastiCache. Review usage before migration."})
    except redis.ResponseError:
        findings.append({"check": "Restricted command usage", "status": "INFO",
                         "detail": "INFO COMMANDSTATS not available (may be restricted by ACL or unsupported on this engine version)"})
    except (redis.ConnectionError, redis.TimeoutError) as e:
        findings.append({"check": "Restricted command usage", "status": "INFO",
                         "detail": f"Could not retrieve commandstats: {e}"})

    # Lua script detection
    lua_detected = False
    try:
        eval_calls = 0
        for key in ("cmdstat_eval", "cmdstat_evalsha"):
            if key in cmdstats:
                eval_calls += cmdstats[key].get("calls", 0)
        if eval_calls > 0:
            lua_detected = True
            findings.append({"check": "Lua scripts", "status": "WARN",
                             "detail": f"Lua scripts detected ({eval_calls} eval calls). Test all Lua scripts against the target engine. Scripts using module commands or hardcoded key names may break."})
    except (KeyError, TypeError, AttributeError):
        findings.append({"check": "Lua scripts", "status": "INFO",
                         "detail": "Unable to detect Lua script usage from commandstats"})
    info["lua_scripts_detected"] = lua_detected

    # Large key sampling
    try:
        large_keys_found = []
        for _ in range(20):
            key = r.randomkey()
            if key is None:
                break
            try:
                usage = r.memory_usage(key)
                if usage is not None and usage > 1048576:
                    size_mb = round(usage / (1024 * 1024), 2)
                    large_keys_found.append((key, size_mb))
            except Exception:
                findings.append({"check": "Large key sampling", "status": "INFO",
                                 "detail": "MEMORY USAGE command not available, skipping large key check"})
                break
        for key, size_mb in large_keys_found:
            key_type = r.type(key) if key else "unknown"
            findings.append({"check": "Large key sampling", "status": "WARN",
                             "detail": f"Large key detected ({key_type}, {size_mb}MB). Large keys can cause replication timeouts and event loop blocking during migration."})
    except Exception:
        pass

    # Maxmemory policy
    # CONFIG GET is restricted on ElastiCache managed endpoints. Detect them by
    # hostname and skip CONFIG in that case, advising the user to check via the
    # AWS API (describe-cache-parameters) instead.
    is_elasticache = host.endswith(".cache.amazonaws.com")
    if is_elasticache:
        info["maxmemory_policy"] = "unknown (ElastiCache source)"
        findings.append({"check": "Eviction policy", "status": "INFO",
                         "detail": "CONFIG command is restricted on ElastiCache. "
                         "Check the eviction policy via: aws elasticache describe-cache-parameters "
                         "--cache-parameter-group-name <param-group> "
                         "--query \"Parameters[?ParameterName=='maxmemory-policy']\""})
    else:
        try:
            config = r.config_get("maxmemory-policy")
            policy = config.get("maxmemory-policy", "unknown")
            info["maxmemory_policy"] = policy
            if policy in ("noeviction",):
                findings.append({"check": "Eviction policy", "status": "WARN",
                                 "detail": f"Policy is '{policy}' -- writes will fail when memory is full. Consider volatile-lru or allkeys-lru."})
            else:
                findings.append({"check": "Eviction policy", "status": "INFO",
                                 "detail": f"Policy: {policy}"})
        except redis.ResponseError:
            info["maxmemory_policy"] = "unknown"

    # Data tiering advisory
    findings.append({"check": "Data tiering advisory", "status": "INFO",
                     "detail": "If targeting r6gd node types (data tiering), note: online migration is not supported for r6gd clusters. "
                     "Use backup/restore instead. Data tiering only supports volatile-lru, allkeys-lru, volatile-lfu, allkeys-lfu, and noeviction eviction policies."})

    # Sizing recommendation
    findings.append({"check": "Sizing recommendation", "status": "INFO",
                     "detail": f"Source dataset: {used_memory_gb} GB. Use scripts/price_calculator.py to estimate serverless and node-based costs for your workload."})

    try:
        r.close()
    except Exception:
        pass
    return {"info": info, "findings": findings}


def format_report(result):
    """Format preflight results as a human-readable report."""
    if "error" in result:
        info = result.get("info", {})
        lines = [f"ERROR: {result['error']}"]
        if info:
            lines.append(f"  Host: {info.get('host', '?')}:{info.get('port', '?')}")
        return "\n".join(lines)

    info = result["info"]
    findings = result["findings"]

    lines = []
    lines.append("=" * 72)
    lines.append("ElastiCache Migration Preflight Report")
    lines.append("=" * 72)
    lines.append("")
    lines.append(f"  Source:          {info['host']}:{info['port']}")
    lines.append(f"  Redis version:   {info.get('redis_version', 'unknown')}")
    lines.append(f"  OS:              {info.get('os', 'unknown')}")
    lines.append(f"  Uptime:          {info.get('uptime_days', '?')} days")
    lines.append(f"  Cluster mode:    {'enabled' if info.get('cluster_mode') else 'disabled'}")
    lines.append(f"  Memory:          {info.get('used_memory_mb', '?')} MB ({info.get('used_memory_gb', '?')} GB)")
    lines.append(f"  Keys:            {info.get('total_keys', '?')}")
    lines.append(f"  Replicas:        {info.get('connected_replicas', '?')}")
    lines.append(f"  Modules:         {', '.join(info.get('modules', [])) or 'none'}")
    lines.append("")

    fail_count = sum(1 for f in findings if f["status"] == "FAIL")
    warn_count = sum(1 for f in findings if f["status"] == "WARN")
    pass_count = sum(1 for f in findings if f["status"] == "PASS")

    if fail_count == 0:
        lines.append(f"  Verdict: READY TO MIGRATE ({pass_count} passed, {warn_count} warnings)")
    else:
        lines.append(f"  Verdict: BLOCKERS FOUND ({fail_count} failures, {warn_count} warnings)")
    lines.append("")
    lines.append("-" * 72)

    status_order = {"FAIL": 0, "WARN": 1, "ERROR": 2, "PASS": 3, "INFO": 4}
    sorted_findings = sorted(findings, key=lambda f: status_order.get(f["status"], 5))

    for f in sorted_findings:
        icon = {"PASS": "[OK]  ", "FAIL": "[FAIL]", "WARN": "[WARN]", "INFO": "[INFO]", "ERROR": "[ERR] "}
        lines.append(f"  {icon.get(f['status'], '[?]   ')} {f['check']}")
        lines.append(f"         {f['detail']}")
        lines.append("")

    if fail_count > 0:
        lines.append("=" * 72)
        lines.append("MIGRATION BLOCKERS")
        lines.append("=" * 72)
        lines.append("")
        for f in sorted_findings:
            if f["status"] == "FAIL":
                lines.append(f"  - {f['check']}: {f['detail']}")
        lines.append("")
        lines.append("  Resolve blockers before starting migration.")
        lines.append("  See references/migration/instructions.md for guidance.")

    lines.append("")
    lines.append("  Next steps:")
    lines.append("  1. Resolve any blockers above")
    lines.append("  2. Run: python scripts/price_calculator.py to estimate target cost")
    lines.append("  3. Use the AWS CLI test-migration command to validate connectivity to the target cluster")
    lines.append("  4. See references/migration/instructions.md for the full migration workflow")
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ElastiCache Migration Preflight Check")
    parser.add_argument("--host", required=True, help="Source Redis/Valkey hostname")
    parser.add_argument("--port", type=int, default=6379, help="Port (default: 6379)")
    parser.add_argument("--password", default=None, help="AUTH password")
    parser.add_argument("--username", default=None, help="Username (for ACL-based auth)")
    parser.add_argument("--tls", action="store_true", help="Use TLS")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    result = run_preflight(args.host, args.port, args.password, args.tls, args.username)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(format_report(result))

    if "error" in result:
        sys.exit(1)
    fail_count = sum(1 for f in result.get("findings", []) if f["status"] == "FAIL")
    sys.exit(1 if fail_count > 0 else 0)
