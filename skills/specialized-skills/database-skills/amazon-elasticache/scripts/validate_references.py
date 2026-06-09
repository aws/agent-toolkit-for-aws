#!/usr/bin/env python3
"""
ElastiCache Reference Validator

Validates that all reference files have required metadata and follow
project conventions. Also checks scripts for module docstrings and
CLI entrypoints.

Usage:
  python scripts/validate_references.py              # normal output
  python scripts/validate_references.py --verbose    # show all PASS results too
  python scripts/validate_references.py --quiet      # summary counts only

Exit codes:
  0 -- all checks passed (warnings are OK)
  1 -- one or more FAIL results
"""

import argparse
import os
import re
import sys

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REFERENCES_DIR = os.path.join(BASE_DIR, "references")
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
SKILL_MD = os.path.join(BASE_DIR, "SKILL.md")

# Minimum number of non-whitespace characters (beyond the title line) for a
# reference file to be considered non-empty.
MIN_CONTENT_CHARS = 50

# Pattern for kebab-case filenames: lowercase letters, digits, hyphens.
KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\.md$")


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

class Result:
    """A single validation result."""

    def __init__(self, level, filepath, message):
        self.level = level       # "PASS", "WARN", or "FAIL"
        self.filepath = filepath  # relative to BASE_DIR
        self.message = message

    def __str__(self):
        return f"[{self.level}] {self.filepath}: {self.message}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _relative(path):
    """Return a path relative to BASE_DIR for display."""
    return os.path.relpath(path, BASE_DIR)


def _read_skill_md_references():
    """Extract all reference file paths mentioned in SKILL.md."""
    if not os.path.isfile(SKILL_MD):
        return set()
    with open(SKILL_MD, "r", encoding="utf-8") as fh:
        content = fh.read()
    # Match backtick-quoted paths like `references/setup/engine-selection.md`
    return set(re.findall(r"`(references/[a-zA-Z0-9/_-]+\.md)`", content))


# ---------------------------------------------------------------------------
# Reference file checks
# ---------------------------------------------------------------------------

def validate_reference_file(filepath, skill_refs):
    """Validate a single .md reference file. Returns a list of Result objects."""
    results = []
    rel = _relative(filepath)
    filename = os.path.basename(filepath)

    # 1. Kebab-case filename
    if not KEBAB_RE.match(filename):
        results.append(Result("FAIL", rel,
                              f"Filename '{filename}' does not follow kebab-case convention "
                              "(expected lowercase letters, digits, and hyphens only)"))
    else:
        results.append(Result("PASS", rel, "Filename follows kebab-case convention"))

    # 2. Read file content
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            content = fh.read()
    except Exception as exc:
        results.append(Result("FAIL", rel, f"Could not read file: {exc}"))
        return results

    lines = content.split("\n")
    non_blank_lines = [ln for ln in lines if ln.strip()]

    # 3. Has a title (first non-blank line starts with #)
    if not non_blank_lines:
        results.append(Result("FAIL", rel, "File is completely empty"))
        return results  # no point checking further

    first_line = non_blank_lines[0].strip()
    if first_line.startswith("#"):
        results.append(Result("PASS", rel, f"Has title: {first_line[:60]}"))
    else:
        results.append(Result("FAIL", rel,
                              "Missing title -- first non-blank line should start with '#'"))

    # 4. Has meaningful content beyond the title
    # Strip the title line and count remaining non-whitespace characters
    body = "\n".join(lines[1:]) if len(lines) > 1 else ""
    body_chars = len(re.sub(r"\s", "", body))
    if body_chars < MIN_CONTENT_CHARS:
        results.append(Result("FAIL", rel,
                              f"File body has only {body_chars} non-whitespace chars "
                              f"(minimum {MIN_CONTENT_CHARS}) -- appears empty or stub"))
    else:
        results.append(Result("PASS", rel,
                              f"File has meaningful content ({body_chars} body chars)"))

    # 5. Referenced in SKILL.md (non-critical)
    # Build the expected reference path from the relative path (e.g. references/setup/foo.md)
    if rel in skill_refs:
        results.append(Result("PASS", rel, "Referenced in SKILL.md"))
    else:
        results.append(Result("WARN", rel, "Not referenced in SKILL.md"))

    return results


def validate_all_references():
    """Walk references/ and validate every .md file."""
    results = []
    skill_refs = _read_skill_md_references()

    if not os.path.isdir(REFERENCES_DIR):
        results.append(Result("FAIL", "references/",
                              "references/ directory not found"))
        return results, 0

    md_count = 0
    for root, _dirs, files in os.walk(REFERENCES_DIR):
        for fname in sorted(files):
            if not fname.endswith(".md"):
                continue
            md_count += 1
            filepath = os.path.join(root, fname)
            results.extend(validate_reference_file(filepath, skill_refs))

    if md_count == 0:
        results.append(Result("FAIL", "references/",
                              "No .md files found under references/"))

    return results, md_count


# ---------------------------------------------------------------------------
# Script file checks
# ---------------------------------------------------------------------------

def validate_script_file(filepath):
    """Validate a single .py script file. Returns a list of Result objects."""
    results = []
    rel = _relative(filepath)

    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            content = fh.read()
    except Exception as exc:
        results.append(Result("FAIL", rel, f"Could not read file: {exc}"))
        return results

    # 1. Has a module docstring
    # A module docstring is a triple-quoted string near the top of the file,
    # possibly preceded by a shebang, encoding declaration, or comments.
    # We use a simple heuristic: check if '"""' or "'''" appears in the first
    # 20 non-blank lines.
    lines = content.split("\n")
    top_chunk = "\n".join(lines[:30])
    has_docstring = ('"""' in top_chunk or "'''" in top_chunk)

    if has_docstring:
        results.append(Result("PASS", rel, "Has module docstring"))
    else:
        results.append(Result("FAIL", rel,
                              "Missing module docstring at top of file"))

    # 2. Has a CLI entrypoint (if __name__ == "__main__")
    has_main = ('if __name__' in content
                and ('"__main__"' in content or "'__main__'" in content))
    if has_main:
        results.append(Result("PASS", rel, "Has CLI entrypoint"))
    else:
        # This is a warning, not a fail, because some scripts are libraries
        results.append(Result("WARN", rel,
                              "No 'if __name__ == \"__main__\"' block -- "
                              "OK if this is a library, not a CLI tool"))

    return results


def validate_all_scripts():
    """Walk scripts/ and validate every .py file (excluding this script)."""
    results = []

    if not os.path.isdir(SCRIPTS_DIR):
        results.append(Result("FAIL", "scripts/",
                              "scripts/ directory not found"))
        return results, 0

    py_count = 0
    for fname in sorted(os.listdir(SCRIPTS_DIR)):
        if not fname.endswith(".py"):
            continue
        py_count += 1
        filepath = os.path.join(SCRIPTS_DIR, fname)
        results.extend(validate_script_file(filepath))

    if py_count == 0:
        results.append(Result("WARN", "scripts/",
                              "No .py files found under scripts/"))

    return results, py_count


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_results(results, verbose=False, quiet=False):
    """Print validation results to stdout."""
    fail_count = sum(1 for r in results if r.level == "FAIL")
    warn_count = sum(1 for r in results if r.level == "WARN")
    pass_count = sum(1 for r in results if r.level == "PASS")

    if not quiet:
        # Group results by level for readability
        if fail_count > 0:
            print("\n--- FAILURES ---")
            for r in results:
                if r.level == "FAIL":
                    print(f"  {r}")

        if warn_count > 0:
            print("\n--- WARNINGS ---")
            for r in results:
                if r.level == "WARN":
                    print(f"  {r}")

        if verbose and pass_count > 0:
            print("\n--- PASSED ---")
            for r in results:
                if r.level == "PASS":
                    print(f"  {r}")

    # Summary line (always printed)
    print(f"\nSummary: {pass_count} passed, {warn_count} warnings, {fail_count} failures")

    return fail_count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Validate ElastiCache reference files and scripts."
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Show PASS results in addition to WARN and FAIL"
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Show summary counts only (no individual results)"
    )
    args = parser.parse_args()

    all_results = []

    # Validate reference files
    print("Validating reference files...")
    ref_results, ref_count = validate_all_references()
    all_results.extend(ref_results)
    print(f"  Scanned {ref_count} reference .md files")

    # Validate scripts
    print("Validating scripts...")
    script_results, script_count = validate_all_scripts()
    all_results.extend(script_results)
    print(f"  Scanned {script_count} script .py files")

    # Print results
    fail_count = print_results(all_results, verbose=args.verbose, quiet=args.quiet)

    sys.exit(1 if fail_count > 0 else 0)


if __name__ == "__main__":
    main()
