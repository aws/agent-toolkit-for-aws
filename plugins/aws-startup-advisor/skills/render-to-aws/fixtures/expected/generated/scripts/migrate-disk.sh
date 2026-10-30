#!/usr/bin/env bash
set -euo pipefail

execute=false
if [[ ${1:-} == "--execute" ]]; then
  execute=true
  shift
fi
if [[ $# -ne 2 ]]; then
  echo "usage: migrate-disk.sh [--execute] SOURCE_ROOT TARGET_ROOT" >&2
  exit 2
fi
source_root=$1
target_root=$2
printf 'Plan pre-copy and checksum manifest from %s to %s; never delete source data.\n' "$source_root" "$target_root"
if [[ $execute != true ]]; then
  echo "DRY_RUN: no files copied"
  exit 0
fi
if [[ ${WRITERS_QUIESCED:-false} != true ]]; then
  echo "final delta requires WRITERS_QUIESCED=true" >&2
  exit 1
fi
rsync -aH --numeric-ids --checksum -- "$source_root/" "$target_root/"
find "$target_root" -type f -print0 | sort -z | xargs -0 shasum -a 256
