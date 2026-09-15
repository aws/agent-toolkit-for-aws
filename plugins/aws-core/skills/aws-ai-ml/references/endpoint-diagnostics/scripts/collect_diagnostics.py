"""Collect diagnostic information from a SageMaker endpoint.

Usage:
    from collect_diagnostics import collect_endpoint_diagnostics, TimeRange

    # Default: last 5 minutes
    results = collect_endpoint_diagnostics("my-endpoint", "us-east-1")

    # Last 60 minutes
    results = collect_endpoint_diagnostics("my-endpoint", "us-east-1", time_range=TimeRange.last(60))

    # Absolute UTC window
    from datetime import datetime, timezone
    results = collect_endpoint_diagnostics(
        "my-endpoint", "us-east-1",
        time_range=TimeRange.between(
            datetime(2024, 3, 15, 14, 0, tzinfo=timezone.utc),
            datetime(2024, 3, 15, 15, 0, tzinfo=timezone.utc),
        ),
    )

Note: Log collection retrieves up to 100 events without pagination.
This provides a representative sample, not exhaustive logs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

os.environ.setdefault("AWS_SDK_UA_APP_ID", "AWSSkill-SageMaker")


@dataclass(frozen=True)
class TimeRange:
    """Time window for data collection. Use factory methods to construct.

    Either specify an absolute window (start + end) or a relative lookback
    (minutes from now). Do not mix — if start is set, minutes is ignored.
    """

    start: datetime | None = None
    end: datetime | None = None
    minutes: int = 5

    @classmethod
    def last(cls, minutes: int) -> TimeRange:
        """Relative window: collect the last N minutes of data."""
        return cls(minutes=minutes)

    @classmethod
    def between(cls, start: datetime, end: datetime) -> TimeRange:
        """Absolute window: collect data between two UTC timestamps."""
        return cls(start=start, end=end)

    def resolve(self) -> tuple[datetime, datetime]:
        """Resolve to concrete (start, end) datetimes."""
        now = datetime.now(timezone.utc)
        if self.start is not None:
            return self.start, self.end if self.end is not None else now
        return now - timedelta(minutes=self.minutes), now


def collect_endpoint_diagnostics(
    endpoint_name: str,
    region: str,
    time_range: TimeRange | None = None,
) -> dict[str, Any]:
    """Collect endpoint status, CloudWatch metrics, and recent logs.

    Args:
        endpoint_name: The SageMaker endpoint name.
        region: AWS region where the endpoint is deployed.
        time_range: Time window for metrics and logs. Defaults to last 5 min.
            Use TimeRange.last(N) for relative or TimeRange.between(s, e)
            for absolute UTC windows.

    Returns:
        Dict with keys: endpoint_status, metrics, recent_logs, errors,
        reference_docs.
    """
    if not endpoint_name or not region:
        raise ValueError("endpoint_name and region are required")

    if time_range is None:
        time_range = TimeRange()

    window_start, window_end = time_range.resolve()

    sm_client = boto3.client("sagemaker", region_name=region)
    cw_client = boto3.client("cloudwatch", region_name=region)
    logs_client = boto3.client("logs", region_name=region)

    errors: list[str] = []
    endpoint_status: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    recent_logs: list[dict[str, Any]] = []
    first_variant_name: str = ""

    # Step 1: DescribeEndpoint
    try:
        resp = sm_client.describe_endpoint(EndpointName=endpoint_name)
        endpoint_status = {
            "status": resp.get("EndpointStatus"),
            "failure_reason": resp.get("FailureReason"),
            "creation_time": str(resp.get("CreationTime")),
            "last_modified_time": str(resp.get("LastModifiedTime")),
            "production_variants": [
                {
                    "name": v.get("VariantName"),
                    "instance_type": v.get("InstanceType"),
                    "current_instance_count": v.get("CurrentInstanceCount"),
                    "current_weight": v.get("CurrentWeight"),
                }
                for v in resp.get("ProductionVariants", [])
            ],
        }
        variants = resp.get("ProductionVariants", [])
        if variants:
            first_variant_name = variants[0].get("VariantName", "")
    except ClientError as e:
        errors.append(f"DescribeEndpoint failed: {e.response['Error']['Message']}")

    # Step 2: GetMetricData
    try:
        # SageMaker publishes invocation metrics with {EndpointName, VariantName} dimensions.
        # CloudWatch requires an exact dimension-set match, so we must include VariantName.
        variant_name = first_variant_name or "AllTraffic"
        endpoint_variant_dim = [
            {"Name": "EndpointName", "Value": endpoint_name},
            {"Name": "VariantName", "Value": variant_name},
        ]

        if not first_variant_name:
            errors.append(
                f"Variant name unavailable from DescribeEndpoint; defaulting to 'AllTraffic' for metrics"
            )

        # Invocation metrics (require EndpointName + VariantName)
        metric_queries = [
            {
                "Id": "invocations",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/SageMaker",
                        "MetricName": "Invocations",
                        "Dimensions": endpoint_variant_dim,
                    },
                    "Period": 60,
                    "Stat": "Sum",
                },
            },
            {
                "Id": "errors_4xx",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/SageMaker",
                        "MetricName": "Invocation4XXErrors",
                        "Dimensions": endpoint_variant_dim,
                    },
                    "Period": 60,
                    "Stat": "Sum",
                },
            },
            {
                "Id": "errors_5xx",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/SageMaker",
                        "MetricName": "Invocation5XXErrors",
                        "Dimensions": endpoint_variant_dim,
                    },
                    "Period": 60,
                    "Stat": "Sum",
                },
            },
            {
                "Id": "invocation_model_errors",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/SageMaker",
                        "MetricName": "InvocationModelErrors",
                        "Dimensions": endpoint_variant_dim,
                    },
                    "Period": 60,
                    "Stat": "Sum",
                },
            },
            {
                "Id": "model_latency_avg",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/SageMaker",
                        "MetricName": "ModelLatency",
                        "Dimensions": endpoint_variant_dim,
                    },
                    "Period": 60,
                    "Stat": "Average",
                },
            },
            {
                "Id": "model_latency_p99",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/SageMaker",
                        "MetricName": "ModelLatency",
                        "Dimensions": endpoint_variant_dim,
                    },
                    "Period": 60,
                    "Stat": "p99",
                },
            },
            {
                "Id": "overhead_latency",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/SageMaker",
                        "MetricName": "OverheadLatency",
                        "Dimensions": endpoint_variant_dim,
                    },
                    "Period": 60,
                    "Stat": "Average",
                },
            },
        ]

        # Instance-level metrics (CPU/Memory/GPU) use /aws/sagemaker/Endpoints namespace
        if first_variant_name:
            variant_dim = [
                {"Name": "EndpointName", "Value": endpoint_name},
                {"Name": "VariantName", "Value": first_variant_name},
            ]
            metric_queries.extend(
                [
                    {
                        "Id": "cpu_util",
                        "MetricStat": {
                            "Metric": {
                                "Namespace": "/aws/sagemaker/Endpoints",
                                "MetricName": "CPUUtilization",
                                "Dimensions": variant_dim,
                            },
                            "Period": 60,
                            "Stat": "Average",
                        },
                    },
                    {
                        "Id": "memory_util",
                        "MetricStat": {
                            "Metric": {
                                "Namespace": "/aws/sagemaker/Endpoints",
                                "MetricName": "MemoryUtilization",
                                "Dimensions": variant_dim,
                            },
                            "Period": 60,
                            "Stat": "Average",
                        },
                    },
                    {
                        "Id": "gpu_util",
                        "MetricStat": {
                            "Metric": {
                                "Namespace": "/aws/sagemaker/Endpoints",
                                "MetricName": "GPUUtilization",
                                "Dimensions": variant_dim,
                            },
                            "Period": 60,
                            "Stat": "Average",
                        },
                    },
                    {
                        "Id": "gpu_memory_util",
                        "MetricStat": {
                            "Metric": {
                                "Namespace": "/aws/sagemaker/Endpoints",
                                "MetricName": "GPUMemoryUtilization",
                                "Dimensions": variant_dim,
                            },
                            "Period": 60,
                            "Stat": "Average",
                        },
                    },
                ]
            )
        else:
            errors.append(
                "Variant name unavailable; skipped instance-level metrics (CPU/Memory/GPU)"
            )

        # Warn if multiple variants exist — metrics are only for the first
        variants = endpoint_status.get("production_variants", [])
        if len(variants) > 1:
            variant_names = [v["name"] for v in variants]
            errors.append(
                f"Multiple variants detected: {variant_names}. "
                f"Metrics shown are for '{variant_name}' only. "
                f"Ask the user which variant to diagnose if needed."
            )

        cw_resp = cw_client.get_metric_data(
            MetricDataQueries=metric_queries,
            StartTime=window_start,
            EndTime=window_end,
        )
        for result in cw_resp.get("MetricDataResults", []):
            metrics[result["Id"]] = result.get("Values", [])
    except ClientError as e:
        errors.append(f"GetMetricData failed: {e.response['Error']['Message']}")

    # Step 3: FilterLogEvents — use a wider window for logs
    try:
        log_group = f"/aws/sagemaker/Endpoints/{endpoint_name}"
        if time_range.start is not None:
            # Respect user-specified absolute window boundaries
            log_window_start = max(window_start, window_end - timedelta(minutes=15))
        else:
            # For relative windows, always use 15-minute log window per SKILL.md
            log_window_start = window_end - timedelta(minutes=15)
        log_resp = logs_client.filter_log_events(
            logGroupName=log_group,
            startTime=int(log_window_start.timestamp() * 1000),
            endTime=int(window_end.timestamp() * 1000),
            limit=100,
        )
        recent_logs = [
            {
                "message": e.get("message"),
                "timestamp": datetime.fromtimestamp(
                    e.get("timestamp", 0) / 1000, tz=timezone.utc
                ).isoformat(),
            }
            for e in log_resp.get("events", [])
        ]
    except ClientError as e:
        errors.append(f"FilterLogEvents failed: {e.response['Error']['Message']}")

    return {
        "endpoint_status": endpoint_status,
        "metrics": metrics,
        "recent_logs": recent_logs,
        "errors": errors,
        "reference_docs": {
            "metrics_definitions": "https://docs.aws.amazon.com/sagemaker/latest/dg/monitoring-cloudwatch.html",
            "troubleshooting": "https://docs.aws.amazon.com/sagemaker/latest/dg/deploy-model-troubleshoot.html",
        },
    }
