"""Contained atomic JSON output."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes


class PathBoundaryError(ValueError):
    pass


def require_absolute(path: Path, label: str) -> None:
    if not path.is_absolute():
        raise PathBoundaryError(f"{label}_not_absolute")


def require_contained(path: Path, root: Path, label: str) -> None:
    require_absolute(path, label)
    require_absolute(root, "root")
    root_resolved = root.resolve(strict=True)
    parent_resolved = path.parent.resolve(strict=True)
    try:
        parent_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise PathBoundaryError(f"{label}_outside_root") from exc
    current = path.parent
    while current != root_resolved:
        if current.is_symlink():
            raise PathBoundaryError(f"{label}_symlink_ancestor")
        current = current.parent
    if path.exists() and path.is_symlink():
        raise PathBoundaryError(f"{label}_symlink")


def write_json_atomic(path: Path, root: Path, value: Any) -> None:
    require_contained(path, root, "output")
    payload = canonical_bytes(value)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary_name = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
