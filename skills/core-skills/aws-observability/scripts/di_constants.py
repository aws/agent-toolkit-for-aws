"""Shared constants for dynamic instrumentation support."""

SNAPSHOT_SIGNAL_TYPE = "SNAPSHOT"

# Dynamic instrumentation snapshots are written to a per-service CloudWatch Logs
# group. ``{service_name}`` is substituted with the target service name at query
# time via ``resolve_snapshot_log_group``.
SNAPSHOT_LOG_GROUP_TEMPLATE = "/aws/service-events/{service_name}"


def resolve_snapshot_log_group(service_name: str) -> str:
    """Resolve the per-service snapshot log group name."""
    return SNAPSHOT_LOG_GROUP_TEMPLATE.format(service_name=service_name)
