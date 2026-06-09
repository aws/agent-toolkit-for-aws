#!/usr/bin/env python3
"""
ElastiCache CloudWatch Dashboard and Alarm Generator

Emits CloudFormation JSON for dashboards and alarms, parameterized by
deployment type (serverless vs node-based) and cache identifier.

Usage:
  # Serverless dashboard + alarms
  python generate_dashboards.py --serverless my-cache --region us-east-1

  # Node-based dashboard + alarms
  python generate_dashboards.py --replication-group my-cluster --region us-east-1

  # Dashboard only (no alarms)
  python generate_dashboards.py --serverless my-cache --no-alarms

  # Alarms only (no dashboard)
  python generate_dashboards.py --serverless my-cache --no-dashboard

  # Write to file
  python generate_dashboards.py --serverless my-cache --output elasticache-observability.json

  # Set SNS topic for alarm notifications
  python generate_dashboards.py --serverless my-cache --sns-topic arn:aws:sns:us-east-1:123456789012:alerts
"""

import argparse
import json
import re
import sys

# ---------------------------------------------------------------------------
# Dependency check
# This script uses only the Python standard library (no pip install needed).
# It generates CloudFormation JSON locally and does not call AWS APIs.
# ---------------------------------------------------------------------------


def serverless_dashboard_body(cache_name, region):
    """CloudWatch dashboard body for a serverless cache.

    Note: CacheHitRate and some command-family metrics are only available for
    Valkey/Redis OSS serverless caches, not Memcached serverless caches.
    """
    return {
        "widgets": [
            _metric_widget("Cache Hit Rate", region, "ServerlessCacheName", cache_name,
                           [["AWS/ElastiCache", "CacheHitRate", "ServerlessCacheName", cache_name]],
                           period=300),
            _metric_widget("ECPU Consumption", region, "ServerlessCacheName", cache_name,
                           [["AWS/ElastiCache", "ElastiCacheProcessingUnits", "ServerlessCacheName", cache_name]],
                           period=60),
            _metric_widget("Throttled Commands", region, "ServerlessCacheName", cache_name,
                           [["AWS/ElastiCache", "ThrottledCmds", "ServerlessCacheName", cache_name]],
                           period=60, stat="Sum"),
            _metric_widget("Read / Write Latency", region, "ServerlessCacheName", cache_name,
                           [["AWS/ElastiCache", "SuccessfulReadRequestLatency", "ServerlessCacheName", cache_name],
                            ["AWS/ElastiCache", "SuccessfulWriteRequestLatency", "ServerlessCacheName", cache_name]],
                           period=60),
            _metric_widget("Current Connections", region, "ServerlessCacheName", cache_name,
                           [["AWS/ElastiCache", "CurrConnections", "ServerlessCacheName", cache_name]],
                           period=300),
            _metric_widget("New Connections", region, "ServerlessCacheName", cache_name,
                           [["AWS/ElastiCache", "NewConnections", "ServerlessCacheName", cache_name]],
                           period=300, stat="Sum"),
            _metric_widget("Bytes Used For Cache", region, "ServerlessCacheName", cache_name,
                           [["AWS/ElastiCache", "BytesUsedForCache", "ServerlessCacheName", cache_name]],
                           period=300),
            _metric_widget("Command-Family Breakdown", region, "ServerlessCacheName", cache_name,
                           [["AWS/ElastiCache", "StringBasedCmds", "ServerlessCacheName", cache_name],
                            ["AWS/ElastiCache", "HashBasedCmds", "ServerlessCacheName", cache_name],
                            ["AWS/ElastiCache", "SortedSetBasedCmds", "ServerlessCacheName", cache_name],
                            ["AWS/ElastiCache", "StreamBasedCmds", "ServerlessCacheName", cache_name],
                            ["AWS/ElastiCache", "PubSubBasedCmds", "ServerlessCacheName", cache_name]],
                           period=300, stat="Sum"),
            _metric_widget("Total Commands Count", region, "ServerlessCacheName", cache_name,
                           [["AWS/ElastiCache", "TotalCmdsCount", "ServerlessCacheName", cache_name]],
                           period=300, stat="Sum"),
            _metric_widget("Item Counts", region, "ServerlessCacheName", cache_name,
                           [["AWS/ElastiCache", "CurrVolatileItems", "ServerlessCacheName", cache_name],
                            ["AWS/ElastiCache", "CurrItems", "ServerlessCacheName", cache_name]],
                           period=300),
        ]
    }


def node_based_dashboard_body(rg_id, region, node_ids=None):
    """CloudWatch dashboard body for a node-based replication group.

    Args:
        node_ids: List of CacheClusterId values (e.g., ["my-cluster-001", "my-cluster-002"]).
            If provided, per-node metrics are shown. If None, falls back to ReplicationGroupId
            which only works for a subset of metrics.
    """
    if node_ids:
        # Per-node metrics using CacheClusterId dimension
        def _node_metrics(metric_name):
            return [["AWS/ElastiCache", metric_name, "CacheClusterId", nid] for nid in node_ids]

        return {
            "widgets": [
                _metric_widget("Cache Hit Rate", region, "CacheClusterId", node_ids[0],
                               _node_metrics("CacheHitRate"), period=300),
                _metric_widget("Engine CPU Utilization", region, "CacheClusterId", node_ids[0],
                               _node_metrics("EngineCPUUtilization") + _node_metrics("CPUUtilization"),
                               period=60),
                _metric_widget("Database Memory Usage", region, "CacheClusterId", node_ids[0],
                               _node_metrics("DatabaseMemoryUsagePercentage"), period=300),
                _metric_widget("Read / Write Latency", region, "CacheClusterId", node_ids[0],
                               _node_metrics("SuccessfulReadRequestLatency") + _node_metrics("SuccessfulWriteRequestLatency"),
                               period=60),
                _metric_widget("Current Connections", region, "CacheClusterId", node_ids[0],
                               _node_metrics("CurrConnections"), period=300),
                _metric_widget("Replication Lag", region, "CacheClusterId", node_ids[0],
                               _node_metrics("ReplicationLag"), period=60),
                _metric_widget("Network Bytes In/Out", region, "CacheClusterId", node_ids[0],
                               _node_metrics("NetworkBytesIn") + _node_metrics("NetworkBytesOut"),
                               period=300, stat="Sum"),
                _metric_widget("Evictions", region, "CacheClusterId", node_ids[0],
                               _node_metrics("Evictions"), period=300, stat="Sum"),
                _metric_widget("Command-Family Breakdown", region, "CacheClusterId", node_ids[0],
                               _node_metrics("StringBasedCmds") + _node_metrics("HashBasedCmds") +
                               _node_metrics("SortedSetBasedCmds") + _node_metrics("StreamBasedCmds") +
                               _node_metrics("SearchBasedCmds"),
                               period=300, stat="Sum"),
            ]
        }
    else:
        # Fallback: ReplicationGroupId (limited metrics available)
        dim_name = "ReplicationGroupId"
        return {
            "widgets": [
                _metric_widget("Cache Hit Rate", region, dim_name, rg_id,
                               [["AWS/ElastiCache", "CacheHitRate", dim_name, rg_id]], period=300),
                _metric_widget("Engine CPU Utilization", region, dim_name, rg_id,
                               [["AWS/ElastiCache", "EngineCPUUtilization", dim_name, rg_id],
                                ["AWS/ElastiCache", "CPUUtilization", dim_name, rg_id]], period=60),
                _metric_widget("Database Memory Usage", region, dim_name, rg_id,
                               [["AWS/ElastiCache", "DatabaseMemoryUsagePercentage", dim_name, rg_id]], period=300),
                _metric_widget("Read / Write Latency", region, dim_name, rg_id,
                               [["AWS/ElastiCache", "SuccessfulReadRequestLatency", dim_name, rg_id],
                                ["AWS/ElastiCache", "SuccessfulWriteRequestLatency", dim_name, rg_id]], period=60),
                _metric_widget("Current Connections", region, dim_name, rg_id,
                               [["AWS/ElastiCache", "CurrConnections", dim_name, rg_id]], period=300),
                _metric_widget("Replication Lag", region, dim_name, rg_id,
                               [["AWS/ElastiCache", "ReplicationLag", dim_name, rg_id]], period=60),
                _metric_widget("Evictions", region, dim_name, rg_id,
                               [["AWS/ElastiCache", "Evictions", dim_name, rg_id]], period=300, stat="Sum"),
            ]
        }


def serverless_alarms(cache_name, sns_topic=None, max_storage_gb=None,
                      storage_alarm_pct=80,
                      hit_rate_threshold=80, throttle_threshold=None,
                      read_latency_threshold=None, write_latency_threshold=None,
                      ecpu_threshold=None, evictions_threshold=None):
    """CloudFormation alarm resources for a serverless cache.

    Alarms are controlled via threshold parameters. Pass None to disable
    an alarm. CacheHitRate is enabled by default at 80%.
    """
    alarms = {}
    dim = [{"Name": "ServerlessCacheName", "Value": cache_name}]

    if hit_rate_threshold is not None:
        alarms["CacheHitRateAlarm"] = _alarm(
            f"{cache_name}-low-hit-rate",
            f"Cache hit rate below {hit_rate_threshold}% for {cache_name}",
            "AWS/ElastiCache", "CacheHitRate", dim,
            threshold=hit_rate_threshold, comparison="LessThanThreshold",
            period=300, eval_periods=6, datapoints_to_alarm=4, stat="Average",
            sns_topic=sns_topic
        )
    if throttle_threshold is not None:
        alarms["ThrottledCmdsAlarm"] = _alarm(
            f"{cache_name}-throttled-cmds",
            f"Throttled commands above {throttle_threshold} on {cache_name}",
            "AWS/ElastiCache", "ThrottledCmds", dim,
            threshold=throttle_threshold, comparison="GreaterThanThreshold",
            period=60, eval_periods=3, datapoints_to_alarm=2, stat="Sum",
            sns_topic=sns_topic
        )
    if max_storage_gb is not None:
        storage_threshold_bytes = int(max_storage_gb * (storage_alarm_pct / 100) * 1073741824)
        alarms["StorageLimitAlarm"] = _alarm(
            f"{cache_name}-storage-approaching-limit",
            f"Storage approaching {storage_alarm_pct}% of configured limit ({max_storage_gb} GB) on {cache_name}",
            "AWS/ElastiCache", "BytesUsedForCache", dim,
            threshold=storage_threshold_bytes, comparison="GreaterThanThreshold",
            period=300, eval_periods=3, datapoints_to_alarm=2, stat="Maximum",
            sns_topic=sns_topic
        )
    if read_latency_threshold is not None:
        alarms["ReadLatencyAlarm"] = _alarm(
            f"{cache_name}-high-read-latency",
            f"Read latency above {read_latency_threshold}us on {cache_name}",
            "AWS/ElastiCache", "SuccessfulReadRequestLatency", dim,
            threshold=read_latency_threshold, comparison="GreaterThanThreshold",
            period=60, eval_periods=5, datapoints_to_alarm=3, stat="Average",
            sns_topic=sns_topic
        )
    if write_latency_threshold is not None:
        alarms["WriteLatencyAlarm"] = _alarm(
            f"{cache_name}-high-write-latency",
            f"Write latency above {write_latency_threshold}us on {cache_name}",
            "AWS/ElastiCache", "SuccessfulWriteRequestLatency", dim,
            threshold=write_latency_threshold, comparison="GreaterThanThreshold",
            period=60, eval_periods=5, datapoints_to_alarm=3, stat="Average",
            sns_topic=sns_topic
        )
    if ecpu_threshold is not None:
        alarms["ECPUSpikeAlarm"] = _alarm(
            f"{cache_name}-ecpu-spike",
            f"ECPU consumption above {ecpu_threshold} on {cache_name}",
            "AWS/ElastiCache", "ElastiCacheProcessingUnits", dim,
            threshold=ecpu_threshold, comparison="GreaterThanThreshold",
            period=300, eval_periods=3, datapoints_to_alarm=2, stat="Sum",
            sns_topic=sns_topic
        )
    if evictions_threshold is not None:
        alarms["EvictionsAlarm"] = _alarm(
            f"{cache_name}-evictions",
            f"Evictions above {evictions_threshold} on {cache_name}",
            "AWS/ElastiCache", "Evictions", dim,
            threshold=evictions_threshold, comparison="GreaterThanThreshold",
            period=300, eval_periods=3, datapoints_to_alarm=2, stat="Sum",
            sns_topic=sns_topic
        )
    return alarms


def node_based_alarms(rg_id, sns_topic=None, engine_cpu_threshold=90,
                      memory_threshold=80, hit_rate_threshold=80,
                      replication_lag_threshold=None,
                      read_latency_threshold=None, write_latency_threshold=None,
                      evictions_threshold=None, new_connections_threshold=None,
                      node_ids=None):
    """CloudFormation alarm resources for a node-based replication group.

    Alarms are controlled via threshold parameters. Pass None to disable
    an alarm. EngineCPU (90%), memory (80%), and hit rate (80%) are enabled
    by default. If node_ids are provided, alarms are created for each node
    using CacheClusterId. Otherwise falls back to ReplicationGroupId
    (limited metric availability).
    """
    alarms = {}
    if node_ids:
        targets = [("CacheClusterId", nid) for nid in node_ids]
    else:
        targets = [("ReplicationGroupId", rg_id)]

    for dim_name, dim_value in targets:
        dim = [{"Name": dim_name, "Value": dim_value}]
        prefix = dim_value
        safe = re.sub(r'[^a-zA-Z0-9]', '', dim_value)

        if hit_rate_threshold is not None:
            alarms[f"CacheHitRateAlarm{safe}"] = _alarm(
                f"{prefix}-low-hit-rate",
                f"Cache hit rate below {hit_rate_threshold}% on {dim_value}",
                "AWS/ElastiCache", "CacheHitRate", dim,
                threshold=hit_rate_threshold, comparison="LessThanThreshold",
                period=300, eval_periods=6, datapoints_to_alarm=4, stat="Average",
                sns_topic=sns_topic
            )
        if engine_cpu_threshold is not None:
            alarms[f"EngineCPUAlarm{safe}"] = _alarm(
                f"{prefix}-high-engine-cpu",
                f"Engine CPU above {engine_cpu_threshold}% on {dim_value}",
                "AWS/ElastiCache", "EngineCPUUtilization", dim,
                threshold=engine_cpu_threshold, comparison="GreaterThanThreshold",
                period=60, eval_periods=5, datapoints_to_alarm=3, stat="Maximum",
                sns_topic=sns_topic
            )
        if memory_threshold is not None:
            alarms[f"MemoryAlarm{safe}"] = _alarm(
                f"{prefix}-high-memory",
                f"Memory usage above {memory_threshold}% on {dim_value}",
                "AWS/ElastiCache", "DatabaseMemoryUsagePercentage", dim,
                threshold=memory_threshold, comparison="GreaterThanThreshold",
                period=60, eval_periods=5, datapoints_to_alarm=3, stat="Maximum",
                sns_topic=sns_topic
            )
        if replication_lag_threshold is not None:
            alarms[f"ReplicationLagAlarm{safe}"] = _alarm(
                f"{prefix}-high-replication-lag",
                f"Replication lag above {replication_lag_threshold}s on {dim_value}",
                "AWS/ElastiCache", "ReplicationLag", dim,
                threshold=replication_lag_threshold, comparison="GreaterThanThreshold",
                period=60, eval_periods=5, datapoints_to_alarm=3, stat="Maximum",
                sns_topic=sns_topic
            )
        if read_latency_threshold is not None:
            alarms[f"ReadLatencyAlarm{safe}"] = _alarm(
                f"{prefix}-high-read-latency",
                f"Read latency above {read_latency_threshold}us on {dim_value}",
                "AWS/ElastiCache", "SuccessfulReadRequestLatency", dim,
                threshold=read_latency_threshold, comparison="GreaterThanThreshold",
                period=60, eval_periods=5, datapoints_to_alarm=3, stat="Average",
                sns_topic=sns_topic
            )
        if write_latency_threshold is not None:
            alarms[f"WriteLatencyAlarm{safe}"] = _alarm(
                f"{prefix}-high-write-latency",
                f"Write latency above {write_latency_threshold}us on {dim_value}",
                "AWS/ElastiCache", "SuccessfulWriteRequestLatency", dim,
                threshold=write_latency_threshold, comparison="GreaterThanThreshold",
                period=60, eval_periods=5, datapoints_to_alarm=3, stat="Average",
                sns_topic=sns_topic
            )
        if evictions_threshold is not None:
            alarms[f"EvictionsAlarm{safe}"] = _alarm(
                f"{prefix}-evictions",
                f"Evictions above {evictions_threshold} on {dim_value}",
                "AWS/ElastiCache", "Evictions", dim,
                threshold=evictions_threshold, comparison="GreaterThanThreshold",
                period=300, eval_periods=3, datapoints_to_alarm=2, stat="Sum",
                sns_topic=sns_topic
            )
        if new_connections_threshold is not None:
            alarms[f"NewConnectionsAlarm{safe}"] = _alarm(
                f"{prefix}-new-connections",
                f"New connections above {new_connections_threshold}/min on {dim_value}",
                "AWS/ElastiCache", "NewConnections", dim,
                threshold=new_connections_threshold, comparison="GreaterThanThreshold",
                period=60, eval_periods=3, datapoints_to_alarm=2, stat="Sum",
                sns_topic=sns_topic
            )
    return alarms


def _metric_widget(title, region, dim_name, dim_value, metrics, period=300, stat="Average"):
    """Build a CloudWatch dashboard metric widget."""
    return {
        "type": "metric",
        "properties": {
            "title": title,
            "region": region,
            "metrics": metrics,
            "period": period,
            "stat": stat,
            "view": "timeSeries",
        },
        "width": 12,
        "height": 6,
    }


def _alarm(name, description, namespace, metric, dimensions, threshold,
           comparison, period, eval_periods, stat, sns_topic=None,
           datapoints_to_alarm=None):
    """Build a CloudFormation alarm resource."""
    alarm = {
        "Type": "AWS::CloudWatch::Alarm",
        "Properties": {
            "AlarmName": name,
            "AlarmDescription": description,
            "Namespace": namespace,
            "MetricName": metric,
            "Dimensions": dimensions,
            "Threshold": threshold,
            "ComparisonOperator": comparison,
            "Period": period,
            "EvaluationPeriods": eval_periods,
            "DatapointsToAlarm": datapoints_to_alarm if datapoints_to_alarm else eval_periods,
            "Statistic": stat,
            "TreatMissingData": "notBreaching",
        }
    }
    if sns_topic:
        props = alarm["Properties"]
        assert isinstance(props, dict)
        props["AlarmActions"] = [{"Ref": "SNSTopicARN"}]
        props["OKActions"] = [{"Ref": "SNSTopicARN"}]
    return alarm


def generate_template(cache_type, identifier, region, sns_topic=None,
                      include_dashboard=True, include_alarms=True,
                      max_storage_gb=None, storage_alarm_pct=80, memory_threshold=80,
                      engine_cpu_threshold=90,
                      replication_lag_threshold=None, hit_rate_threshold=80,
                      throttle_threshold=None,
                      read_latency_threshold=None, write_latency_threshold=None,
                      ecpu_threshold=None, evictions_threshold=None,
                      new_connections_threshold=None, node_ids=None):
    """Generate a complete CloudFormation template."""
    resources = {}

    if include_dashboard:
        if cache_type == "serverless":
            body = serverless_dashboard_body(identifier, region)
        else:
            body = node_based_dashboard_body(identifier, region, node_ids=node_ids)

        safe_name = re.sub(r'[^a-zA-Z0-9]', '', identifier)
        resources[f"{safe_name}Dashboard"] = {
            "Type": "AWS::CloudWatch::Dashboard",
            "Properties": {
                "DashboardName": f"ElastiCache-{identifier}",
                "DashboardBody": json.dumps(body),
            }
        }

    if include_alarms:
        if cache_type == "serverless":
            alarms = serverless_alarms(identifier, sns_topic,
                                       max_storage_gb=max_storage_gb,
                                       storage_alarm_pct=storage_alarm_pct,
                                       hit_rate_threshold=hit_rate_threshold,
                                       throttle_threshold=throttle_threshold,
                                       read_latency_threshold=read_latency_threshold,
                                       write_latency_threshold=write_latency_threshold,
                                       ecpu_threshold=ecpu_threshold,
                                       evictions_threshold=evictions_threshold)
        else:
            alarms = node_based_alarms(identifier, sns_topic,
                                       memory_threshold=memory_threshold,
                                       engine_cpu_threshold=engine_cpu_threshold,
                                       replication_lag_threshold=replication_lag_threshold,
                                       hit_rate_threshold=hit_rate_threshold,
                                       read_latency_threshold=read_latency_threshold,
                                       write_latency_threshold=write_latency_threshold,
                                       evictions_threshold=evictions_threshold,
                                       new_connections_threshold=new_connections_threshold,
                                       node_ids=node_ids)
        resources.update(alarms)

    template = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": f"ElastiCache observability stack for {identifier}",
        "Resources": resources,
    }

    if sns_topic:
        template["Parameters"] = {
            "SNSTopicARN": {
                "Type": "String",
                "Default": sns_topic,
                "Description": "SNS topic ARN for alarm notifications"
            }
        }

    return template


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ElastiCache Dashboard & Alarm Generator")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--serverless", metavar="CACHE_NAME", help="Generate for a serverless cache")
    group.add_argument("--replication-group", metavar="RG_ID", help="Generate for a node-based replication group")
    parser.add_argument("--node-ids", default=None,
                        help="Comma-separated CacheClusterIds for per-node metrics (e.g., my-cluster-001,my-cluster-002). "
                             "Required for node-based dashboards to show data.")
    parser.add_argument("--region", default="us-east-1", help="AWS region for dashboard widgets")
    parser.add_argument("--sns-topic", default=None, help="SNS topic ARN for alarm notifications")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip dashboard generation")
    parser.add_argument("--no-alarms", action="store_true", help="Skip alarm generation")
    parser.add_argument("--max-storage-gb", type=float, default=None,
                        help="Serverless MaxDataStorageGB for storage alarm. If omitted, alarm is skipped.")
    parser.add_argument("--storage-alarm-pct", type=float, default=80,
                        help="Percentage of max-storage-gb to alarm at (default: 80)")
    parser.add_argument("--memory-threshold", type=float, default=80,
                        help="Node-based memory usage alarm threshold in percent (default: 80)")
    parser.add_argument("--engine-cpu-threshold", type=float, default=90,
                        help="Node-based engine CPU alarm threshold in percent (default: 90)")
    parser.add_argument("--replication-lag-threshold", type=float, default=None,
                        help="Node-based replication lag alarm threshold in seconds. If omitted, alarm is skipped.")
    parser.add_argument("--hit-rate-threshold", type=float, default=80,
                        help="Cache hit rate alarm threshold in percent (default: 80)")
    parser.add_argument("--throttle-threshold", type=float, default=None,
                        help="Serverless throttled commands alarm threshold (off by default)")
    parser.add_argument("--read-latency-threshold", type=float, default=None,
                        help="Read latency alarm threshold in microseconds (off by default)")
    parser.add_argument("--write-latency-threshold", type=float, default=None,
                        help="Write latency alarm threshold in microseconds (off by default)")
    parser.add_argument("--ecpu-threshold", type=float, default=None,
                        help="Serverless ECPU consumption alarm threshold (off by default)")
    parser.add_argument("--evictions-threshold", type=float, default=None,
                        help="Evictions alarm threshold per 5-min period (off by default)")
    parser.add_argument("--new-connections-threshold", type=float, default=None,
                        help="Node-based new connections alarm threshold per minute (off by default)")
    parser.add_argument("--output", "-o", default=None, help="Write to file instead of stdout")
    args = parser.parse_args()

    if args.serverless:
        cache_type = "serverless"
        identifier = args.serverless
    else:
        cache_type = "node-based"
        identifier = args.replication_group

    node_ids = [nid.strip() for nid in args.node_ids.split(",") if nid.strip()] if args.node_ids else None

    template = generate_template(
        cache_type, identifier, args.region,
        sns_topic=args.sns_topic,
        include_dashboard=not args.no_dashboard,
        include_alarms=not args.no_alarms,
        max_storage_gb=args.max_storage_gb,
        storage_alarm_pct=args.storage_alarm_pct,
        memory_threshold=args.memory_threshold,
        engine_cpu_threshold=args.engine_cpu_threshold,
        replication_lag_threshold=args.replication_lag_threshold,
        hit_rate_threshold=args.hit_rate_threshold,
        throttle_threshold=args.throttle_threshold,
        read_latency_threshold=args.read_latency_threshold,
        write_latency_threshold=args.write_latency_threshold,
        ecpu_threshold=args.ecpu_threshold,
        evictions_threshold=args.evictions_threshold,
        new_connections_threshold=args.new_connections_threshold,
        node_ids=node_ids,
    )

    output = json.dumps(template, indent=2)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Written to {args.output}")
        print(f"\nDeploy with:")
        print(f"  aws cloudformation deploy --template-file {args.output} --stack-name {identifier}-observability")
    else:
        print(output)
