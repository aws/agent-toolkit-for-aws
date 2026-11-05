#!/usr/bin/env bash
# Get HyperPod cluster ID and metadata
# Usage: ./get-cluster-info.sh CLUSTER_NAME [--region REGION]
# Output: JSON with cluster_id extracted from ARN
set -euo pipefail

command -v jq >/dev/null 2>&1 || { echo "Error: jq is required but not installed" >&2; exit 1; }

[[ $# -ge 1 && "$1" != -* ]] || { echo "Usage: get-cluster-info.sh CLUSTER_NAME [--region REGION]" >&2; exit 1; }
CLUSTER="$1"; shift
# --region is passed only when given. Otherwise the AWS CLI picks the Region the usual way:
# AWS_REGION, then AWS_DEFAULT_REGION, then the profile.
REGION=""
# An option without its value stops with a clear message, not set -u's "unbound variable".
require_args() { [[ $1 -ge $2 ]] || { echo "Error: $3" >&2; exit 1; }; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --region) require_args $# 2 "--region needs REGION"; REGION="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

FAILED="Error: Could not retrieve cluster ARN for '$CLUSTER' (cluster not found or permission denied)"
# Under set -e a failed AWS call would end the script before this message, so catch it here.
# The AWS CLI's own error still goes to stderr.
ARN=$(aws sagemaker describe-cluster --cluster-name "$CLUSTER" ${REGION:+--region "$REGION"} \
  --query 'ClusterArn' --output text) || { echo "$FAILED" >&2; exit 1; }
[[ -z "$ARN" || "$ARN" == "None" ]] && { echo "$FAILED" >&2; exit 1; }
CLUSTER_ID=$(echo "$ARN" | cut -d'/' -f2)
# Report the cluster's own Region, from its ARN (arn:aws:sagemaker:REGION:ACCOUNT:cluster/ID).
REGION=$(echo "$ARN" | cut -d':' -f4)

jq -n --arg id "$CLUSTER_ID" --arg arn "$ARN" --arg name "$CLUSTER" --arg region "$REGION" \
  '{cluster_id: $id, cluster_arn: $arn, cluster_name: $name, region: $region}'
