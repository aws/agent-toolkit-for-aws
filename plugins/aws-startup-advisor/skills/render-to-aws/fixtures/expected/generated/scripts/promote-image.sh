#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || $# -gt 4 ]]; then
  echo "usage: promote-image.sh ECR_REPOSITORY_URL SHA256_DIGEST TARGET_ENVIRONMENT [--execute]" >&2
  exit 2
fi
repository_url=$1
digest=$2
target_environment=$3
mode=${4:-}
if [[ ! $repository_url =~ ^([0-9]{12})\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com/([a-z0-9][a-z0-9._/-]*)$ ]]; then
  echo "repository must be an ECR repository URL" >&2
  exit 2
fi
registry_id=${BASH_REMATCH[1]}
region=${BASH_REMATCH[2]}
repository_name=${BASH_REMATCH[3]}
if [[ ! $digest =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "digest must be an immutable lowercase sha256 value; tags such as latest are rejected" >&2
  exit 2
fi
if [[ ! $target_environment =~ ^[a-z0-9][a-z0-9-]{0,31}$ ]]; then
  echo "target environment must use lowercase letters, digits, and hyphens" >&2
  exit 2
fi
if [[ -n $mode && $mode != "--execute" ]]; then
  echo "unknown argument: $mode" >&2
  exit 2
fi

image_reference="${repository_url}@${digest}"
digest_short=${digest#sha256:}
digest_short=${digest_short:0:12}
promotion_tag="deploy-${target_environment}-${digest_short}"
if [[ $mode != "--execute" ]]; then
  printf 'PROMOTION_DRY_RUN environment=%s image=%s immutable_tag=%s\n' \
    "$target_environment" "$image_reference" "$promotion_tag"
  printf 'Re-run with --execute to verify the source digest and create the immutable environment tag without rebuilding.\n'
  exit 0
fi

command -v aws >/dev/null 2>&1 || {
  echo "aws CLI is required for --execute" >&2
  exit 1
}
mutability=$(aws ecr describe-repositories \
  --registry-id "$registry_id" \
  --region "$region" \
  --repository-names "$repository_name" \
  --query 'repositories[0].imageTagMutability' \
  --output text)
if [[ $mutability != "IMMUTABLE" ]]; then
  echo "target ECR repository must enforce immutable tags" >&2
  exit 1
fi
IFS=$'\t' read -r resolved_digest image_manifest < <(
  aws ecr batch-get-image \
    --registry-id "$registry_id" \
    --region "$region" \
    --repository-name "$repository_name" \
    --image-ids "imageDigest=$digest" \
    --accepted-media-types application/vnd.oci.image.manifest.v1+json application/vnd.docker.distribution.manifest.v2+json \
    --query 'images[0].[imageId.imageDigest,imageManifest]' \
    --output text
)
if [[ $resolved_digest != "$digest" || -z $image_manifest || $image_manifest == "None" ]]; then
  echo "source digest was not found exactly in the target ECR repository" >&2
  exit 1
fi
aws ecr put-image \
  --registry-id "$registry_id" \
  --region "$region" \
  --repository-name "$repository_name" \
  --image-manifest "$image_manifest" \
  --image-tag "$promotion_tag" \
  --output json >/dev/null
printf 'PROMOTION_COMPLETE environment=%s image=%s immutable_tag=%s\n' \
  "$target_environment" "$image_reference" "$promotion_tag"
