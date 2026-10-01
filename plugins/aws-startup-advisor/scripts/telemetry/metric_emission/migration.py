#!/usr/bin/env python3
"""Migration telemetry — a placeholder, not implemented yet.

`migrationActivity: MigrationActivityDetails` is the third member of the
PluginTelemetryEvent union and is owned by CASK (see migration-telemetry.smithy).
It wants a migration run's identity, the source cloud provider, and which phase
started or completed; nothing in this plugin tracks phases today.

So this is a seam rather than a stub that pretends. `skill_invoked.py` already
calls it, which is the call site a real implementation needs.

TODO(StartupEngBlend-3621): implement with CASK. Expect the signature to grow — a
skill invocation alone cannot supply a run ID or a phase. Applies to AZURE_TO_AWS,
GCP_TO_AWS, HEROKU_TO_AWS and LLM_TO_BEDROCK.
"""


def emit_migration_metric(install_id, skill_id, url):
    """Does nothing. Returns False, meaning nothing was sent.

    Arguments mirror `client.emit_skill_invocation_metric` so the hook calls both
    the same way.
    """
    return False
