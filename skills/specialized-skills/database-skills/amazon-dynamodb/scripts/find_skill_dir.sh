#!/usr/bin/env sh
# Host-agnostic resolver for the amazon-dynamodb install directory.
#
# Prints the absolute path of the directory that contains SKILL.md (the skill
# root) and exits 0, or prints nothing to stdout and exits non-zero with a
# diagnostic on stderr. It is deliberately POSIX sh (no bashisms) so it runs
# the same under Claude Code, Kiro, Codex, Cursor, a bare terminal, or CI.
#
# Why this exists: the skill's Python scripts already locate their own siblings
# via __file__, so a caller only needs the skill ROOT once. Hosts install
# skills in different places (~/.claude, ~/.kiro, ~/.codex, ~/.cursor, a repo
# checkout, …), so a single hardcoded path is wrong. This script searches a
# host-neutral candidate list and VERIFIES each hit against a sentinel set of
# files unique to this skill, so it never silently returns the wrong directory.
#
# Resolution order (first verified match wins):
#   1. $DDB_SKILL_DIR                         (explicit override — most reliable)
#   2. the directory this script lives in's parent (when run by path)
#   3. $1, if passed                          (a hint the caller supplies)
#   4. a bounded search under common host roots + the current project
#
# Usage:
#   DDB_SKILL_DIR=/path/to/amazon-dynamodb   # optional pin
#   sh find_skill_dir.sh [hint-dir]
#   SKILL_DIR="$(sh find_skill_dir.sh)" || exit 1

# A directory is the skill root iff it carries all of these. The set is chosen
# to be specific enough that no unrelated directory matches by accident.
_sentinels='SKILL.md scripts/calculate_costs.py scripts/deploy_model.py scripts/benchmark_lambda.py'

_verify() {
  # $1 = candidate dir. Echoes the resolved absolute path on success.
  d=$1
  [ -n "$d" ] || return 1
  [ -d "$d" ] || return 1
  for s in $_sentinels; do
    [ -e "$d/$s" ] || return 1
  done
  # Normalize to an absolute path without requiring realpath (not everywhere).
  (cd "$d" 2>/dev/null && pwd) || return 1
}

# 1. Explicit override.
if [ -n "${DDB_SKILL_DIR:-}" ]; then
  if r=$(_verify "$DDB_SKILL_DIR"); then printf '%s\n' "$r"; exit 0; fi
  echo "find_skill_dir: \$DDB_SKILL_DIR=$DDB_SKILL_DIR is set but does not look like the amazon-dynamodb root (missing one of: $_sentinels)." >&2
  exit 3
fi

# 2. This script's own parent (scripts/ -> skill root). Works whenever the
#    caller invokes the script by a real path rather than via stdin.
_self=${0:-}
case "$_self" in
  */*)
    _selfdir=$(cd "$(dirname "$_self")" 2>/dev/null && pwd)
    if [ -n "$_selfdir" ]; then
      if r=$(_verify "$_selfdir/.."); then printf '%s\n' "$r"; exit 0; fi
    fi
    ;;
esac

# 3. Caller-supplied hint.
if [ -n "${1:-}" ]; then
  if r=$(_verify "$1"); then printf '%s\n' "$r"; exit 0; fi
fi

# 4. Bounded search across host-neutral candidate roots. We look for a
#    directory named like the skill that contains the sentinels. `find` is
#    depth-limited so this stays fast even on large trees.
_roots="$HOME/.claude $HOME/.kiro $HOME/.codex $HOME/.cursor $HOME/.config $HOME/.local/share $PWD"
for root in $_roots; do
  [ -d "$root" ] || continue
  # Match SKILL.md under any dir whose path mentions the skill, then verify.
  for hit in $(find "$root" -maxdepth 6 -type f -name SKILL.md 2>/dev/null); do
    cand=$(dirname "$hit")
    if r=$(_verify "$cand"); then printf '%s\n' "$r"; exit 0; fi
  done
done

echo "find_skill_dir: could not locate the amazon-dynamodb root. Set DDB_SKILL_DIR to the directory that contains SKILL.md, e.g.:" >&2
echo "  export DDB_SKILL_DIR=/path/to/amazon-dynamodb" >&2
exit 1
