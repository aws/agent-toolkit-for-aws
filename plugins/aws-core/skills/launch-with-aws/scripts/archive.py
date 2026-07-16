# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Build the repo zip the backend expects."""

import io
import logging
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from typing import Optional, Set, Tuple

from launch_config import GITHUB_ZIPBALL_TIMEOUT_SECS, MAX_ARCHIVE_BYTES

logger = logging.getLogger(__name__)

_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".next",
        ".nuxt",
        ".turbo",
        ".cache",
        ".parcel-cache",
        "dist",
        "build",
        "out",
        "coverage",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
        # Credential/secret directories
        ".aws",
        ".ssh",
        ".gnupg",
        ".gcp",
        ".azure",
        ".docker",
        ".kube",
    }
)

_SKIP_FILES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        ".env.test",
        ".env.staging",
        "credentials",
        "credentials.json",
        ".git-credentials",
        ".netrc",
        ".pypirc",
        ".npmrc",
        ".htpasswd",
    }
)

# Best-effort filtering of common credential files, not a security boundary.
# A filtered archive is not guaranteed to be secret-free.
_SKIP_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore")

_SKIP_NAME_PREFIXES = ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa")

_GITHUB_URL_RE = re.compile(
    r"^https?://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$",
)


class ArchiveError(Exception):
    """Raised when a repo archive cannot be produced."""


def _decode_git_paths(output: bytes) -> Set[str]:
    """Decode NUL-delimited Git paths using the filesystem encoding."""
    return {os.fsdecode(path) for path in output.split(b"\0") if path}


def _run_git(root: str, args: list[str]) -> subprocess.CompletedProcess:
    """Run a Git file-enumeration command with consistent safeguards."""
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        timeout=30,
    )


def _has_gitignore(root: str) -> bool:
    """Return whether the source tree contains an applicable .gitignore file."""
    for _, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        if ".gitignore" in filenames:
            return True
    return False


def _gitignore_files_without_repo(root: str) -> Set[str]:
    """Apply Git ignore rules to a directory that is not a Git worktree."""
    with tempfile.TemporaryDirectory(prefix="launch-with-aws-git-") as git_dir:
        initialized = _run_git(root, ["init", "--bare", "--quiet", git_dir])
        if initialized.returncode != 0:
            raise ArchiveError("Git could not initialize temporary metadata to apply ignore rules.")

        result = _run_git(
            root,
            [
                f"--git-dir={git_dir}",
                f"--work-tree={root}",
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
            ],
        )
        if result.returncode != 0:
            raise ArchiveError(
                "Git could not determine which files are safe to upload. "
                "Resolve the Git error and try again."
            )
        return _decode_git_paths(result.stdout)


def _git_included_files(root: str) -> Optional[Set[str]]:
    """Return paths selected by Git ignore rules, or None when no rules apply.

    NUL-delimited output preserves unusual filenames. Tracked files are combined
    with untracked-but-not-ignored files so new local files are included.
    """
    try:
        result = _run_git(
            root,
            [
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ],
        )
        if result.returncode == 0:
            ignored_tracked = _run_git(
                root,
                [
                    "ls-files",
                    "--cached",
                    "--ignored",
                    "--exclude-standard",
                    "-z",
                ],
            )
            if ignored_tracked.returncode != 0:
                raise ArchiveError(
                    "Git could not determine which tracked files match ignore rules."
                )
            return _decode_git_paths(result.stdout) - _decode_git_paths(ignored_tracked.stdout)
        if not _has_git_metadata(root):
            if _has_gitignore(root):
                return _gitignore_files_without_repo(root)
            return None
        raise ArchiveError(
            "Git could not determine which files are safe to upload. "
            "Resolve the Git error and try again."
        )
    except subprocess.TimeoutExpired as err:
        raise ArchiveError(
            "Git timed out while determining which files are safe to upload."
        ) from err
    except OSError as err:
        if _has_git_metadata(root) or _has_gitignore(root):
            raise ArchiveError(
                "Git is required to apply this source directory's ignore rules before upload."
            ) from err
        return None


def _has_git_metadata(root: str) -> bool:
    """Return whether root is at or below a directory containing Git metadata."""
    current = os.path.abspath(root)
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return True
        parent = os.path.dirname(current)
        if parent == current:
            return False
        current = parent


def parse_github_url(url: str) -> Optional[Tuple[str, str]]:
    """Return (owner, repo) for a GitHub HTTPS URL, or None."""
    match = _GITHUB_URL_RE.match(url.strip())
    if not match:
        return None
    return match.group(1), match.group(2)


def sanitize_root_name(name: str) -> str:
    segments = [s for s in re.split(r"[\\/]", name.strip()) if s]
    base = (segments[-1] if segments else "").strip().lstrip(".")
    cleaned = re.sub(r"[^\w.-]", "-", base).strip("-")
    return cleaned or "app"


def _is_secret_file(filename: str) -> bool:
    """Return True if the filename matches a known secret pattern."""
    lower = filename.lower()
    if lower in _SKIP_FILES:
        return True
    if lower.startswith(".env."):
        return True
    if lower.endswith(_SKIP_SUFFIXES):
        return True
    if any(lower.startswith(p) for p in _SKIP_NAME_PREFIXES):
        return True
    return False


def zip_local_repo(path: str, root_name: str) -> bytes:
    """Zip a local repo directory, skipping VCS/build artifacts and secrets.

    When the directory is a git repository, .gitignore rules are respected
    via `git ls-files`. The hardcoded secret exclusions still apply on top
    as a defense-in-depth measure.
    """
    root = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(root):
        raise ArchiveError(f"Not a directory: {path}")

    prefix = sanitize_root_name(root_name)
    skipped: list[str] = []
    git_files = _git_included_files(root)

    if git_files is not None:
        logger.info("Using git to determine included files (.gitignore respected)")

    buffer = io.BytesIO()
    file_count = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for filename in filenames:
                abs_path = os.path.join(dirpath, filename)
                if os.path.islink(abs_path):
                    continue
                rel = os.path.relpath(abs_path, root).replace(os.sep, "/")
                if git_files is not None and rel not in git_files:
                    continue
                if _is_secret_file(filename):
                    skipped.append(rel)
                    continue
                zf.write(abs_path, f"{prefix}/{rel}")
                file_count += 1

    if skipped:
        logger.info(
            "Excluded %d file(s) matching secret patterns: %s",
            len(skipped),
            ", ".join(skipped),
        )

    if file_count == 0:
        raise ArchiveError(f"No files found under {path}")

    data = buffer.getvalue()
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ArchiveError(
            f"Archive is {len(data) // (1024 * 1024)} MiB, exceeding the "
            f"{MAX_ARCHIVE_BYTES // (1024 * 1024)} MiB limit. Remove large "
            "files or build artifacts and try again."
        )
    return data


def download_github_zip(url: str) -> bytes:
    """Download a public GitHub repo's default-branch archive."""
    parsed = parse_github_url(url)
    if not parsed:
        raise ArchiveError(f"Not a GitHub repository URL: {url}")
    owner, repo = parsed

    zipball = f"https://api.github.com/repos/{owner}/{repo}/zipball"
    req = urllib.request.Request(zipball, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=GITHUB_ZIPBALL_TIMEOUT_SECS) as resp:
            data = resp.read()
    except urllib.error.HTTPError as err:
        if err.code in (401, 403, 404):
            raise ArchiveError(
                f"Could not download {owner}/{repo}. Only public repositories can "
                "be fetched by URL — for a private repo, clone it locally and pass "
                "the local path instead."
            ) from err
        raise ArchiveError(f"GitHub returned {err.code} downloading {owner}/{repo}.") from err
    except (urllib.error.URLError, OSError) as err:
        raise ArchiveError(f"Failed to download {url}: {err}") from err

    if len(data) > MAX_ARCHIVE_BYTES:
        raise ArchiveError(
            f"Downloaded archive is {len(data) // (1024 * 1024)} MiB, exceeding "
            f"the {MAX_ARCHIVE_BYTES // (1024 * 1024)} MiB limit."
        )
    return data
