#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Launch with AWS — CLI entry point.

Subcommands mirror the migration workflow steps. Each prints JSON to stdout
on success, exits non-zero with error message on stderr on failure.

Dependencies:
    pip install boto3
"""

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

# The scripts use PEP 604 union syntax (`str | None`) in signatures, which
# fails at definition time on Python < 3.10; boto3 also requires 3.10+.
if sys.version_info < (3, 10):
    print(
        f"Error: Python 3.10+ required "
        f"(found {sys.version_info.major}.{sys.version_info.minor})",
        file=sys.stderr,
    )
    sys.exit(2)

try:
    import boto3  # noqa: F401
except ImportError:
    print(
        "Error: missing required package: boto3\n" "Install it with:\n" "  pip install boto3",
        file=sys.stderr,
    )
    sys.exit(2)

# Ensure sibling modules are importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).parent))

import launch_api_client as api
from archive import ArchiveError, parse_github_url, zip_local_repo
from auth import SessionExpiredError, start_auth, wait_for_auth
from launch_config import load_config


def _ok(value) -> None:
    """Print a JSON result and exit 0."""
    print(json.dumps(value, indent=2, default=str))
    sys.exit(0)


def _fail(message: str) -> None:
    """Print error to stderr and exit 1."""
    print(json.dumps({"error": message}), file=sys.stderr)
    sys.exit(1)


def _default_repo_name(source: str) -> str:
    github = parse_github_url(source)
    if github:
        return github[1]
    cleaned = source.rstrip("/").rstrip(os.sep)
    return os.path.basename(cleaned) or "uploaded-app"


# ── Subcommands ──────────────────────────────────────────────────────────


def cmd_auth_start() -> None:
    """Start authentication (non-blocking)."""
    config = load_config()
    result = start_auth()
    result["baseUrl"] = config.base_url
    _ok(result)


def cmd_auth_wait(pid: str) -> None:
    """Wait for interactive authentication to complete."""
    config = load_config()
    result = wait_for_auth(pid=int(pid))
    result["baseUrl"] = config.base_url
    _ok(result)


def cmd_create_launch(source: str, name: str | None = None) -> None:
    """Create a launch from a local path or GitHub URL.

    For local paths, zips and uploads first. For GitHub URLs, passes directly.
    """
    display_name = (name or "").strip() or _default_repo_name(source)

    github = parse_github_url(source)
    if github:
        # GitHub URL — pass as gitHub source directly.
        launch_source = {"gitHub": {"repositoryUrl": source}}
    elif urlparse(source).scheme in ("http", "https"):
        _fail(
            f"Unsupported repository URL: {source}. Provide a "
            "https://github.com/owner/name URL or a local directory path."
        )
        return
    else:
        # Local directory — zip, upload, then pass as s3Upload source.
        archive = zip_local_repo(source, display_name)
        target = api.create_upload_url()
        api.put_archive(target["uploadUrl"], archive)
        launch_source = {"s3Upload": {"uploadId": target["uploadId"]}}

    result = api.create_launch(name=display_name, source=launch_source)
    _ok(result.get("launch", result))


def cmd_get_launch(launch_id: str, include: str | None = None) -> None:
    """Get launch details, optionally including specific sections."""
    result = api.get_launch(launch_id, include=include)
    _ok(result.get("launch", result))


def cmd_list_launches() -> None:
    """List all launches for the current user."""
    _ok(api.list_launches())


def cmd_delete_launch(launch_id: str) -> None:
    """Delete a launch."""
    api.delete_launch(launch_id)
    _ok({"deleted": True, "id": launch_id})


def cmd_refine_plan(launch_id: str, *context_pairs: str) -> None:
    """Refine a launch plan with context answers (key=value pairs)."""
    context_answers = {}
    for pair in context_pairs:
        if "=" in pair:
            key, value = pair.split("=", 1)
            context_answers[key.strip()] = value.strip()
    _ok(api.refine_plan(launch_id, context_answers=context_answers or None).get("launch", {}))


def cmd_start_launch_execution(launch_id: str) -> None:
    """Start execution of a launch's deployment plan."""
    _ok(api.start_launch_execution(launch_id).get("launch", {}))


def cmd_get_launch_status(launch_id: str) -> None:
    """Poll launch status including execution progress."""
    raw = api.get_launch(launch_id, include="execution,cost_estimate")
    result = raw.get("launch", raw)
    status = result.get("status")
    execution = result.get("execution")

    output = {
        "id": result.get("id"),
        "status": status,
        "isComplete": status == "completed",
        "isFailed": status == "failed",
    }

    if execution:
        output["completedTasks"] = execution.get("completedTasks")
        output["totalTasks"] = execution.get("totalTasks")
        output["currentPhase"] = execution.get("currentPhase")

    if result.get("costEstimate"):
        output["costEstimate"] = result["costEstimate"]

    if result.get("failureReason"):
        output["failureReason"] = result["failureReason"]

    if result.get("contextInputs"):
        output["contextInputs"] = result["contextInputs"]

    _ok(output)


def cmd_get_launch_download_url(launch_id: str) -> None:
    """Get the download URL for a completed launch."""
    raw = api.get_launch(launch_id, include="download_url")
    result = raw.get("launch", raw)
    download_url = result.get("downloadUrl")
    if not download_url:
        _fail("Download URL not available yet. Ensure the launch execution has completed.")
        return
    _ok({"downloadUrl": download_url})


# ── CLI dispatcher ───────────────────────────────────────────────────────

# (func, min_required_args)
from typing import Any, Callable

COMMANDS: dict[str, tuple[Callable[..., Any], int]] = {
    "auth-start": (cmd_auth_start, 0),
    "auth-wait": (cmd_auth_wait, 1),
    "create-launch": (cmd_create_launch, 1),
    "get-launch": (cmd_get_launch, 1),
    "list-launches": (cmd_list_launches, 0),
    "delete-launch": (cmd_delete_launch, 1),
    "refine-plan": (cmd_refine_plan, 1),
    "start-launch-execution": (cmd_start_launch_execution, 1),
    "get-launch-status": (cmd_get_launch_status, 1),
    "get-launch-download-url": (cmd_get_launch_download_url, 1),
}


def _usage() -> str:
    return "Usage: launch_with_aws.py <command> [args...]\n\n" "Commands:\n" + "\n".join(
        f"  {name}" for name in COMMANDS
    )


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(_usage())
        sys.exit(0)

    command = args[0]
    if command not in COMMANDS:
        print(f"Unknown command: {command}\n\n{_usage()}", file=sys.stderr)
        sys.exit(1)

    func, min_args = COMMANDS[command]
    cmd_args = args[1:]

    if len(cmd_args) < min_args:
        _fail(f"Missing required argument for {command}")

    try:
        func(*cmd_args)
    except SessionExpiredError as err:
        _fail(str(err))
    except ArchiveError as err:
        _fail(str(err))
    except api.ApiError as err:
        hint = ""
        if err.status == 401:
            hint = (
                " Hint: the backend rejected the Bearer token. Ensure you "
                "signed in successfully."
            )
        _fail(f"{err}{hint}")
    except Exception as err:
        _fail(str(err))


if __name__ == "__main__":
    main()
