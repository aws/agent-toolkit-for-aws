"""Operation entrypoints for CloudWatch snapshot search and sampling."""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from di_constants import resolve_snapshot_log_group
from di_snapshot_parsing import _escape_logs_insights_string
from di_snapshot_queries import _execute_cloudwatch_query
from di_snapshot_rendering import (
    render_get_sample_snapshot_for_breakpoint_output,
    render_search_snapshots_for_status_event_output,
)
from di_validation import is_valid_location_hash


def _build_base_filters(location_hash: str, service_name: str, environment: str) -> str:
    """Build the resource-matching Logs Insights filter shared by both snapshot tools.

    All three values are escaped for double-quoted string-literal context so a
    caller-supplied quote cannot break out of the literal and inject query
    syntax (which, for ``service_name``/``environment``, could otherwise widen
    the match across services). ``location_hash`` is additionally validated as
    16-char hex by the callers before reaching here.

    Tolerant resource matching:
      - For Java snapshots ``resource.attributes.*`` is populated; require an exact match.
      - For Python snapshots the SDK currently emits an empty resource block, so we accept
        records where the field is absent (``not ispresent(...)``). location_hash by itself
        uniquely identifies (service, environment, location), so this fallback does not
        widen the match across services.
      - Assumption: location_hash collisions across services are negligible. If a future
        SDK bug ever produces records with both a colliding hash and missing resource
        attributes, this filter could return cross-service results.
    """
    location_hash_esc = _escape_logs_insights_string(location_hash)
    service_name_esc = _escape_logs_insights_string(service_name)
    environment_esc = _escape_logs_insights_string(environment)
    return (
        f'attributes.aws.di.location_hash = "{location_hash_esc}"'
        f' and (resource.attributes.service.name = "{service_name_esc}"'
        f"      or not ispresent(resource.attributes.service.name))"
        f' and (resource.attributes.deployment.environment = "{environment_esc}"'
        f'      or resource.attributes.deployment.environment.name = "{environment_esc}"'
        f"      or not ispresent(resource.attributes.deployment.environment))"
    )


def search_snapshots_for_status_event(
    service: str,
    environment: str,
    location_hash: str,
    status_timestamp: str,
    limit: int = 10,
    max_timeout: int = 30,
    custom_filters: Optional[List[str]] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> str:
    """Search CloudWatch Logs snapshots near a known instrumentation status timestamp.

    This helper builds a Logs Insights query around the supplied status event time,
    searches for records containing the `location_hash`, and returns a JSON string
    with query metadata, parsed snapshot summaries, and raw results.

    Args:
        service: Service label echoed back in the response for operator context.
        environment: Environment label echoed back in the response for operator context.
        location_hash: 16-character lowercase hex instrumentation location hash used to filter snapshot records.
        status_timestamp: ISO 8601 status-event timestamp used as the default search anchor.
        limit: Maximum number of matching log records to return.
        max_timeout: Maximum polling time in seconds for the Logs Insights query.
        custom_filters: Optional raw Logs Insights filter fragments appended with `and`.
            Accepts a JSON array of strings, e.g. ["@message like /ORD-123/"]. A single
            bare string is also accepted and treated as a one-element list.
        start_time: Optional ISO 8601 lower bound for the search window. When provided
            with `end_time`, overrides the default `status_timestamp`-anchored window so
            the caller can sweep an arbitrary span (e.g. the full breakpoint lifetime) in
            one query. Both must be supplied together.
        end_time: Optional ISO 8601 upper bound for the search window. See `start_time`.

    Notes:
        - The default search window is `status_timestamp - 5 seconds` through
          `status_timestamp + 1 minute`. Pass `start_time`/`end_time` to widen it.
        - The response is JSON text, not a human-formatted prose summary.
        - Custom filters should already be valid Logs Insights expressions.

    Returns:
        A JSON string containing query status, query metadata, parsed snapshot
        summaries, duration hints, and raw CloudWatch query results.
    """
    if not is_valid_location_hash(location_hash):
        return "ERROR: location_hash must be a 16-character hex string"

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return "ERROR: limit must be an integer"

    # A single filter passed as a bare string is the natural shape; the op documents a
    # list, so coerce string -> [string] rather than mis-iterating the string per character
    # (which would validate the first quote char and emit a misleading 'unbalanced quotes').
    if isinstance(custom_filters, str):
        custom_filters = [custom_filters]

    try:
        event_time = datetime.fromisoformat(status_timestamp.replace("Z", "+00:00"))
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)
    except ValueError:
        return 'ERROR: status_timestamp must be ISO 8601 format like "2025-02-03T18:42:00Z"'

    # Window resolution: explicit start_time/end_time override the anchored default. Both
    # must be supplied together so the window is never half-specified.
    if (start_time is None) != (end_time is None):
        return (
            "ERROR: start_time and end_time must be provided together "
            "(both ISO 8601), or both omitted to use the status_timestamp-anchored window"
        )
    if start_time is not None and end_time is not None:
        try:
            window_start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            if window_start.tzinfo is None:
                window_start = window_start.replace(tzinfo=timezone.utc)
            window_end = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            if window_end.tzinfo is None:
                window_end = window_end.replace(tzinfo=timezone.utc)
        except ValueError:
            return (
                'ERROR: start_time and end_time must be ISO 8601 format like "2025-02-03T18:42:00Z"'
            )
        if window_end <= window_start:
            return "ERROR: end_time must be after start_time"
        start_time_dt = window_start
        end_time_dt = window_end
    else:
        start_time_dt = event_time - timedelta(seconds=5)
        end_time_dt = event_time + timedelta(minutes=1)

    start_time_utc = start_time_dt.astimezone(timezone.utc)
    end_time_utc = end_time_dt.astimezone(timezone.utc)
    start_epoch = int(start_time_utc.timestamp())
    end_epoch = int(end_time_utc.timestamp())

    base_filters = _build_base_filters(location_hash, service, environment)
    if custom_filters:
        for custom_filter in custom_filters:
            custom_filter = custom_filter.strip()
            if not custom_filter:
                continue
            # custom_filters are documented as raw Logs Insights fragments the
            # caller appends on purpose, so they are passed through rather than
            # escaped. Reject only the realistic corruption vector: an unbalanced
            # double-quote that would leak into (or truncate) the rest of the query.
            if (custom_filter.count('"') - custom_filter.count('\\"')) % 2 != 0:
                return f"ERROR: custom_filters has unbalanced quotes: {custom_filter!r}"
            base_filters += f" and {custom_filter}"

    query_string = (
        "fields @timestamp, @message\n"
        f"| filter {base_filters}\n"
        "| sort @timestamp asc\n"
        f"| limit {limit}"
    )
    query_result = _execute_cloudwatch_query(
        query_string=query_string,
        start_epoch=start_epoch,
        end_epoch=end_epoch,
        log_group_name=resolve_snapshot_log_group(service),
        max_timeout=max_timeout,
    )

    return render_search_snapshots_for_status_event_output(
        service_name=service,
        environment=environment,
        location_hash=location_hash,
        custom_filters=custom_filters,
        start_time_utc=start_time_utc.isoformat().replace("+00:00", "Z"),
        end_time_utc=end_time_utc.isoformat().replace("+00:00", "Z"),
        start_epoch=start_epoch,
        end_epoch=end_epoch,
        query_string=query_string,
        query_result=query_result,
    )


def get_sample_snapshot_for_breakpoint(
    service: str,
    environment: str,
    location_hash: str,
    status_timestamp: str,
    max_timeout: int = 30,
    include_raw: bool = False,
) -> str:
    """Fetch one nearby snapshot to inspect the structure of captured data.

    This is a discovery helper intended to show the shape of one snapshot record
    before building narrower CloudWatch queries or deciding which capture fields
    matter.

    Args:
        service: Service label echoed back in the response for operator context.
        environment: Environment label echoed back in the response for operator context.
        location_hash: 16-character lowercase hex instrumentation location hash used to filter snapshot records.
        status_timestamp: ISO 8601 status-event timestamp used as the search anchor.
        max_timeout: Maximum polling time in seconds for the Logs Insights query.
        include_raw: When True, always include the full raw snapshot in the response.
            When False (default), raw snapshots larger than 10 KB are replaced with a
            compact parsed summary produced by _parse_snapshot_fields(). Small snapshots
            are returned in full regardless of this flag.

    Notes:
        - The search window is currently `status_timestamp - 30 seconds` through
          `status_timestamp + 90 seconds` (wider than search to accommodate
          CloudWatch Logs ingestion delay).
        - This helper requests only one result, sorted by most recent timestamp first.
        - The response is JSON text, not a human-formatted prose summary.

    Returns:
        A JSON string containing query metadata plus one parsed sample snapshot,
        or a structured timeout/error response when the query fails.
    """
    if not is_valid_location_hash(location_hash):
        return "ERROR: location_hash must be a 16-character hex string"

    try:
        event_time = datetime.fromisoformat(status_timestamp.replace("Z", "+00:00"))
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)
    except ValueError:
        return 'ERROR: status_timestamp must be ISO 8601 format like "2025-02-03T18:42:00Z"'

    start_time = event_time - timedelta(seconds=30)
    end_time = event_time + timedelta(seconds=90)

    start_time_utc = start_time.astimezone(timezone.utc)
    end_time_utc = end_time.astimezone(timezone.utc)
    start_epoch = int(start_time_utc.timestamp())
    end_epoch = int(end_time_utc.timestamp())

    query_string = (
        "fields @timestamp, @message\n"
        f"| filter {_build_base_filters(location_hash, service, environment)}\n"
        "| sort @timestamp desc\n"
        "| limit 1"
    )

    query_result = _execute_cloudwatch_query(
        query_string=query_string,
        start_epoch=start_epoch,
        end_epoch=end_epoch,
        log_group_name=resolve_snapshot_log_group(service),
        max_timeout=max_timeout,
    )

    return render_get_sample_snapshot_for_breakpoint_output(
        service_name=service,
        environment=environment,
        location_hash=location_hash,
        start_time_utc=start_time_utc.isoformat().replace("+00:00", "Z"),
        end_time_utc=end_time_utc.isoformat().replace("+00:00", "Z"),
        max_timeout=max_timeout,
        query_string=query_string,
        query_result=query_result,
        include_raw=include_raw,
    )
