#!/usr/bin/env bash
# Execute SSM command on a HyperPod node using a pre-resolved target
# Usage:
#   Execute:  ./ssm-exec.sh --target TARGET 'command' [--region REGION]
#   Upload:   ./ssm-exec.sh --target TARGET --upload LOCAL_PATH REMOTE_PATH [--region REGION]
#   Read:     ./ssm-exec.sh --target TARGET --read REMOTE_PATH [--region REGION]
#
# Target format: sagemaker-cluster:<CLUSTER_ID>_<GROUP_NAME>-<INSTANCE_ID>
# Build target from parts: use --cluster-id, --group, --instance-id instead of --target
set -euo pipefail

command -v jq >/dev/null 2>&1 || { echo "Error: jq is required but not installed" >&2; exit 1; }

# --region is passed only when given. Otherwise the AWS CLI picks the Region the usual way:
# AWS_REGION, then AWS_DEFAULT_REGION, then the profile.
REGION=""
TARGET="" ; CLUSTER_ID="" ; GROUP="" ; INSTANCE_ID=""
MODE="exec" ; CMD="" ; LOCAL_PATH="" ; REMOTE_PATH=""

# An option without its value stops with a clear message, not set -u's "unbound variable".
require_args() { [[ $1 -ge $2 ]] || { echo "Error: $3" >&2; exit 1; }; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)      require_args $# 2 "--target needs TARGET"; TARGET="$2"; shift 2 ;;
    --cluster-id)  require_args $# 2 "--cluster-id needs CLUSTER_ID"; CLUSTER_ID="$2"; shift 2 ;;
    --group)       require_args $# 2 "--group needs GROUP_NAME"; GROUP="$2"; shift 2 ;;
    --instance-id) require_args $# 2 "--instance-id needs INSTANCE_ID"
                   INSTANCE_ID="$2"; shift 2 ;;
    --upload)      require_args $# 3 "--upload needs LOCAL_PATH and REMOTE_PATH"
                   MODE="upload"; LOCAL_PATH="$2"; REMOTE_PATH="$3"; shift 3 ;;
    --read)        require_args $# 2 "--read needs REMOTE_PATH"
                   MODE="read"; REMOTE_PATH="$2"; shift 2 ;;
    --region)      require_args $# 2 "--region needs REGION"; REGION="$2"; shift 2 ;;
    -*)            echo "Unknown option: $1" >&2; exit 1 ;;
    *)             [[ -n "$CMD" ]] && { echo "Error: Unexpected argument: $1 (command already set)" >&2; exit 1; }
                   CMD="$1"; shift ;;
  esac
done

# Build target from parts if --target not provided
if [[ -z "$TARGET" ]]; then
  [[ -z "$CLUSTER_ID" || -z "$GROUP" || -z "$INSTANCE_ID" ]] && \
    echo "Error: Provide --target or all of --cluster-id, --group, --instance-id" >&2 && exit 1
  TARGET="sagemaker-cluster:${CLUSTER_ID}_${GROUP}-${INSTANCE_ID}"
fi

# No suffix after the Xs: BSD and macOS mktemp replace only trailing Xs.
TMPFILE=$(mktemp "${TMPDIR:-/tmp}/ssm-cmd-XXXXXXXXXX")
chmod 600 "$TMPFILE"
trap 'rm -f "$TMPFILE"' EXIT

# Cross-platform base64 encode with no line wrapping (GNU: -w0, macOS: -b0)
# Usage: b64_encode FILE  or  cmd | b64_encode
b64_encode() {
  if base64 --help 2>&1 | grep -q '\-w'; then
    if [[ $# -gt 0 ]]; then base64 -w 0 "$1"; else base64 -w 0; fi
  else
    if [[ $# -gt 0 ]]; then base64 -b 0 -i "$1"; else base64 -b 0; fi
  fi
}

json_cmd() {
  local cmd="$1"
  jq -n --arg c "$cmd" '{"command":[$c]}'
}

safe_quote() {
  # Shell-safe quoting via jq @sh (handles all special characters)
  jq -n --arg s "$1" '$s | @sh' -r
}

too_large() {
  echo "Error: $LOCAL_PATH is too large to upload over SSM, which takes at most 65,535" >&2
  echo "       characters per command. Copy it through FSx, EFS or S3 instead." >&2
  exit 1
}

too_long() {
  echo "Error: the command is too long for SSM, which takes at most 65,535 characters per command." >&2
  echo "       Shorten it, or split it into several commands." >&2
  exit 1
}

# SSM Agent splits an AWS-StartNonInteractiveCommand command into words, honoring quotes, and
# runs it without a shell, so pipes, && and redirects would reach the program as arguments.
# Exec and upload run under bash -c; read needs no shell, because `cat 'path'` splits correctly.
case "$MODE" in
  exec)
    [[ -z "$CMD" ]] && echo "Error: No command specified" >&2 && exit 1
    # Checked before quoting too, because jq takes the command as one command-line argument.
    [[ ${#CMD} -gt 65535 ]] && too_long
    SESSION_CMD="bash -c $(safe_quote "$CMD")"
    ;;
  upload)
    [[ ! -f "$LOCAL_PATH" ]] && echo "Error: Local file not found: $LOCAL_PATH" >&2 && exit 1
    SAFE_REMOTE=$(safe_quote "$REMOTE_PATH")
    ENCODED=$(b64_encode "$LOCAL_PATH")
    DECODE="base64 -d"
    # Compress larger files: StartSession takes at most 65,535 characters per command
    if [[ ${#ENCODED} -gt 8000 ]]; then
      ENCODED=$(gzip -c "$LOCAL_PATH" | b64_encode)
      DECODE="base64 -d | gunzip"
    fi
    # Stop clearly when the file does not fit. The payload is checked before it is quoted too,
    # because jq takes it as one command-line argument.
    [[ ${#ENCODED} -gt 65535 ]] && too_large
    # ENCODED is base64 (only A-Za-z0-9+/=), safe inside single quotes
    SESSION_CMD="bash -c $(safe_quote "echo '${ENCODED}' | ${DECODE} > ${SAFE_REMOTE}")"
    [[ ${#SESSION_CMD} -gt 65535 ]] && too_large
    ;;
  read)
    SAFE_REMOTE=$(safe_quote "$REMOTE_PATH")
    SESSION_CMD="cat ${SAFE_REMOTE}"
    ;;
esac
# Every mode's command has to fit in one StartSession parameter.
[[ ${#SESSION_CMD} -gt 65535 ]] && too_long
json_cmd "$SESSION_CMD" > "$TMPFILE"

# The session-manager-plugin races against stdout when it writes to a pipe:
# under "Cannot perform start session: EOF" it closes before flushing, so the
# caller intermittently sees empty stdout even when the command ran. Running
# under `unbuffer` (expect) attaches a PTY, which forces line-buffered I/O
# and eliminates the race. See https://github.com/aws/amazon-ssm-agent/issues/358.
# If `unbuffer` isn't on PATH, fall back to the bare invocation.
if command -v unbuffer >/dev/null 2>&1; then
  unbuffer aws ssm start-session \
    --target "$TARGET" \
    ${REGION:+--region "$REGION"} \
    --document-name AWS-StartNonInteractiveCommand \
    --parameters "file://$TMPFILE"
else
  echo "Warning: 'unbuffer' (from the 'expect' package) is not installed." >&2
  echo "         Without it, 'aws ssm start-session' will intermittently return empty" >&2
  echo "         stdout with 'Cannot perform start session: EOF'." >&2
  echo "         Ask the user before installing it: sudo yum install expect | sudo apt install expect | brew install expect" >&2
  aws ssm start-session \
    --target "$TARGET" \
    ${REGION:+--region "$REGION"} \
    --document-name AWS-StartNonInteractiveCommand \
    --parameters "file://$TMPFILE"
fi
