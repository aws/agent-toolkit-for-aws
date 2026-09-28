"""Generate a least-privilege IAM policy for Bedrock model invocation.

Pure module: takes model IDs, region, and account ID — returns a policy dict.
Handles the dual-ARN pattern (foundation-model + inference-profile) required
when cross-region inference profile IDs (us./eu./apac. prefixed) are in use.
"""
import json
import re
import sys

_GEO_PREFIX = re.compile(r"^(us|eu|apac|global)\.")


def is_inference_profile(model_id: str) -> bool:
    """True when the model ID uses a geo-prefix (cross-region inference profile)."""
    return bool(_GEO_PREFIX.match(model_id))


def is_mantle_model(model_id: str) -> bool:
    """True for OpenAI's proprietary GPT models, which are served only on the
    bedrock-mantle endpoint. They need `bedrock-mantle:*` actions — a policy
    granting only `bedrock:InvokeModel` against a foundation-model ARN cannot
    authorize them, and they have no inference profile to scope to either.
    The open-weight gpt-oss models DO use bedrock-runtime and must not match."""
    mid = model_id.lower()
    return mid.startswith("openai.gpt-5") and "oss" not in mid


def mantle_project_arn(region: str, account_id: str) -> str:
    """ARN scope for mantle inference. Mantle authorizes at project granularity,
    not per model, so this cannot be narrowed to specific model IDs — use a
    service control policy to restrict the model set."""
    return f"arn:aws:bedrock-mantle:{region}:{account_id}:project/*"


def foundation_model_arn(model_id: str) -> str:
    """ARN for a plain foundation-model ID (no geo prefix)."""
    return f"arn:aws:bedrock:*::foundation-model/{model_id}"


def inference_profile_arn(model_id: str, region: str, account_id: str) -> str:
    """ARN for a cross-region inference profile."""
    return f"arn:aws:bedrock:{region}:{account_id}:inference-profile/{model_id}"


def generate_policy(model_ids: list[str], region: str, account_id: str) -> dict:
    """Build a scoped IAM policy covering exactly the given model IDs.

    Emits up to three statements, depending on which endpoints the targets use:
    - `bedrock:InvokeModel*` scoped to foundation-model ARNs (plain IDs) and
      inference-profile ARNs (geo-prefixed IDs), for bedrock-runtime targets
    - `bedrock-mantle:CreateInference` / `Get*` / `List*` scoped to the account's
      mantle projects, for mantle-only targets (SigV4 auth)
    - `bedrock-mantle:CallWithBearerToken` on `*`, for Bedrock API-key auth

    A statement is omitted entirely when no target needs it — notably, an
    all-mantle run must not emit an InvokeModel statement with an empty Resource
    list, which is an invalid policy.
    """
    runtime_ids = [m for m in model_ids if not is_mantle_model(m)]
    mantle_ids = [m for m in model_ids if is_mantle_model(m)]

    statements = []

    resources = []
    for mid in sorted(set(runtime_ids)):
        if is_inference_profile(mid):
            resources.append(inference_profile_arn(mid, region, account_id))
            base_id = _GEO_PREFIX.sub("", mid)
            resources.append(foundation_model_arn(base_id))
        else:
            resources.append(foundation_model_arn(mid))

    # Emit unless the ONLY reason there are no resources is that every target is
    # mantle-only. A genuinely empty model list keeps the legacy shape (a statement
    # with an empty Resource) so existing callers and tests see no behaviour change.
    if resources or not mantle_ids:
        statements.append({
            "Sid": "BedrockInvokeModelScoped",
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream",
            ],
            "Resource": sorted(set(resources)),
        })

    if mantle_ids:
        statements.append({
            "Sid": "BedrockMantleInference",
            "Effect": "Allow",
            "Action": [
                "bedrock-mantle:CreateInference",
                "bedrock-mantle:Get*",
                "bedrock-mantle:List*",
            ],
            "Resource": mantle_project_arn(region, account_id),
        })
        # CallWithBearerToken must be scoped to "*" — AWS does not support
        # narrowing it. Required for Bedrock API-key (bearer token) auth, which is
        # how the rewriter's generated client authenticates. Omit only if the app
        # uses SigV4 exclusively.
        statements.append({
            "Sid": "BedrockMantleCallWithBearerToken",
            "Effect": "Allow",
            "Action": ["bedrock-mantle:CallWithBearerToken"],
            "Resource": "*",
        })

    return {"Version": "2012-10-17", "Statement": statements}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate scoped Bedrock IAM policy")
    parser.add_argument("--models", required=True, help="Comma-separated model IDs")
    parser.add_argument("--region", required=True, help="AWS region")
    parser.add_argument("--account-id", required=True, help="AWS account ID")
    parser.add_argument("--output", help="Output file (default: stdout)")
    args = parser.parse_args()

    model_ids = [m.strip() for m in args.models.split(",") if m.strip()]
    policy = generate_policy(model_ids, args.region, args.account_id)

    output = json.dumps(policy, indent=2) + "\n"
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Policy written to {args.output}", file=sys.stderr)
    else:
        print(output)
