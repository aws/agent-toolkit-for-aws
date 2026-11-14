#!/usr/bin/env bash
set -euo pipefail

execute=false
if [[ ${1:-} == "--execute" ]]; then
  execute=true
  shift
fi
if [[ $# -ne 0 ]]; then
  echo "usage: migrate-postgres.sh [--execute]" >&2
  exit 2
fi
: "${SOURCE_DATABASE_URL:=}"
: "${TARGET_DATABASE_URL:=}"
printf '%s\n' "Stages: privilege preflight, rehearsed full load, CDC, lag check, writer quiescence, final delta, integrity checks, connection switch, source retention."
if [[ $execute != true ]]; then
  echo "DRY_RUN: no database command executed"
  exit 0
fi
if [[ -z $SOURCE_DATABASE_URL || -z $TARGET_DATABASE_URL || ${WRITERS_QUIESCED:-false} != true ]]; then
  echo "execution requires endpoint variables and WRITERS_QUIESCED=true; credentials are never printed" >&2
  exit 1
fi
echo "EXECUTION_GATE_OK: run the reviewed DMS or pg_dump/pg_restore procedure without logging credentials"
