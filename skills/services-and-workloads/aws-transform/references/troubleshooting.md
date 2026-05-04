# Troubleshooting

## Quick Reference

| Issue | Resolution |
|-------|------------|
| `atx` not found | Install: `curl -fsSL https://transform-cli.awsstatic.com/install.sh` piped to `bash` |
| AWS credentials error or expiry | Run `aws sts get-caller-identity`. Check `AWS_PROFILE` or access key env vars |
| Permission denied | Local mode: need `transform-custom:*` — see Prerequisites → IAM Permissions in SKILL.md. Remote mode: generate and attach policies via `npx ts-node generate-caller-policy.ts` — see remote-execution.md |
| Network error | Resolve region: `REGION=${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region 2>/dev/null)}}; REGION=${REGION:-us-east-1}`. Check access to `transform-custom.${REGION}.api.aws` |
| Build fails during transform | Verify build command works locally first. Try interactive mode for debugging |
| Transform not found | Run `atx custom def list --json` to check available TDs |
| Configuration fails with commas | Do not use commas inside `additionalPlanContext` values — they break the CLI parser. Rephrase to avoid commas |
| Conversation expired | Conversations expire after 30 days. Start a new one |
| Windows not supported | Tell user to use Windows Subsystem for Linux (WSL) |
| Git clone fails in remote container | See "Private Repo Credential Issues" section below |
| Timeout | Set `export ATX_SHELL_TIMEOUT=1800` (default: 900s) |
| Stale .exit file | The `.exit` file in `atx-agent-session/` may be left over from a previous run. Always use `kill -0 <pid>` to check if the process is still running — do not rely solely on the `.exit` file |
| Poor quality results | See Improving Quality section below |

## Private Repo Credential Issues

If a git clone fails in the remote container (job status FAILED, logs show
authentication or 403 errors), work through these steps with the user:

**1. Is the PAT/key stored?**

```bash
aws secretsmanager describe-secret --secret-id "atx/github-token" --region "$REGION" 2>/dev/null && echo "EXISTS" || echo "MISSING"
aws secretsmanager describe-secret --secret-id "atx/ssh-key" --region "$REGION" 2>/dev/null && echo "EXISTS" || echo "MISSING"
```

If missing, guide the user through setup — see Step 1 in SKILL.md.

**2. Does the PAT have the right scope?**
GitHub fine-grained PATs can be scoped to specific repos. If the user created a
PAT for repos A and B but is now transforming repo C, the clone will fail with 403.
Ask: "Does your GitHub PAT have access to [repo name]? Fine-grained PATs need
each repo explicitly listed."

Resolution: the user updates their PAT on GitHub to include the new repo, then
updates the stored secret:

```bash
aws secretsmanager put-secret-value --secret-id "atx/github-token" --region "$REGION" --secret-string "<updated-token>"
```

**3. Has the PAT expired?**
GitHub PATs can have expiration dates. Ask: "When did you create this PAT? It may
have expired." Resolution: create a new PAT on GitHub, then update the secret:

```bash
aws secretsmanager put-secret-value --secret-id "atx/github-token" --region "$REGION" --secret-string "<new-token>"
```

**4. Is it the right credential type for the URL?**

- HTTPS URLs (`https://github.com/...`) need `atx/github-token` (PAT)
- SSH URLs (`git@github.com:...`) need `atx/ssh-key` (SSH private key)
If the user provided SSH URLs but only has a PAT stored (or vice versa), guide
them to set up the correct credential type.

**5. Classic vs fine-grained PAT?**
Classic PATs with `repo` scope work for all repos the user has access to.
Fine-grained PATs need each repo explicitly added. If the user is unsure, suggest
a classic PAT with `repo` scope as the simpler option.

## Local Mode Debugging

| Log | Path |
|-----|------|
| Developer logs | `~/.aws/atx/logs/debug*.log` and `~/.aws/atx/logs/error.log` |
| Conversation log | `~/.aws/atx/custom/<conversation_id>/logs/<timestamp>-conversation.log` |

Network errors may indicate VPN/firewall issues with AWS endpoints.

## Remote Mode Debugging

- CloudWatch logs: `/aws/batch/atx-transform`
- Check log streams for the failed conversation ID in AWS Console
- S3 output bucket contains artifacts even for failed jobs
- Check batch job status for error details

## Deployment Failures

CDK deployment handles most issues automatically. Common recovery:

```bash
ATX_INFRA_DIR="$HOME/.aws/atx/custom/remote-infra"
cd "$ATX_INFRA_DIR" && ./teardown.sh
cd "$ATX_INFRA_DIR" && ./setup.sh
```

Common causes: insufficient IAM permissions, service quota limits, no default VPC, Docker not running (only needed when using a custom container image, not the pre-built image).

## Improving Quality

Diagnose in this order:

1. **Reference materials**: Provide migration guides or API specs via `additionalPlanContext`.
2. **Complexity**: Decompose very complex transforms into smaller steps.
3. **Knowledge items**: Review learnings from previous runs. Enable good ones, disable irrelevant ones.

## Network Requirements

| Endpoint | Purpose |
|----------|---------|
| `transform-cli.awsstatic.com` | CLI installation and updates |
| `transform-custom.${REGION}.api.aws` | Transformation service API |

## Pre-built Container Image

The default pre-built image URI is `public.ecr.aws/d9h8z6l7/aws-transform:latest`.
This is configured via `prebuiltImageUri` in `cdk.json`.

## Remote Infrastructure Repo Issues

If `git pull`, `git commit`, or any other step on the remote-infra repo fails
(merge conflicts, corrupted state, detached HEAD, permission errors, etc.), rename
the existing directory and re-clone from scratch. This is safe — the repo is just
a working copy of the infrastructure scripts, and all deployed AWS resources are
unaffected.

```bash
ATX_INFRA_DIR="$HOME/.aws/atx/custom/remote-infra"
if [ -d "$ATX_INFRA_DIR" ]; then
  mv "$ATX_INFRA_DIR" "$ATX_INFRA_DIR.broken-$(date +%Y%m%d-%H%M%S)"
fi
git clone -b atx-remote-infra --single-branch https://github.com/aws-samples/aws-transform-custom-samples.git "$ATX_INFRA_DIR"
```

After re-cloning, continue with the normal flow (e.g., `cd "$ATX_INFRA_DIR" && ./setup.sh`).
The renamed directory can be deleted once you confirm the new clone works.
