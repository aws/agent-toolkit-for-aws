---
name: aws-secrets-manager
description: >
  Prevents AI agents from directly fetching secret values via AWS Secrets Manager
  API calls. Teaches agents to use dynamic references that are resolved at runtime
  by a wrapper script, ensuring secret values never enter the LLM context window.
version: 1
---

# Using Secrets Safely with Agents

## Overview

When AI agents have shell or AWS API access, they can call
`aws secretsmanager get-secret-value` and receive plaintext secrets in their
context window. This creates risk: secrets may leak into logs, conversation
history, or downstream tool calls.

This skill teaches a safer pattern: **dynamic references** resolved at runtime
by a wrapper script (`asm-exec`), so the agent never sees the secret value.

> **Best-effort defense, not a security boundary.** This prevents the most common
> leakage path but cannot stop all evasion vectors. Combine with IAM
> least-privilege, CloudTrail monitoring, and VPC endpoint policies.

## Rules

You MUST follow these rules when working with secrets:

1. **MUST NOT call `get-secret-value` or `batch-get-secret-value`** -- not via AWS
   CLI, SDK, MCP tools, curl, or any other mechanism.
2. **MUST NOT attempt to read secret values** from the Secrets Manager Agent (SMA)
   daemon directly (localhost:2773 or any loopback variant).
3. **MUST use `{{resolve:secretsmanager:...}}` references** -- these are
   resolved at runtime by `asm-exec` without exposing values to you.

## The `{{resolve:...}}` Syntax

```
{{resolve:secretsmanager:<secret-id>:<field-type>:<json-key>:<version-stage>}}
```

| Component | Required | Default | Example |
|-----------|----------|---------|---------|
| `secret-id` | Yes | -- | `prod/db-creds` or full ARN |
| `field-type` | No | `SecretString` | `SecretString` |
| `json-key` | No | (full value) | `password` |
| `version-stage` | No | `AWSCURRENT` | `AWSPENDING` |

## Using `asm-exec`

`asm-exec` is a wrapper that resolves `{{resolve:...}}` references in command
arguments and environment variables, then `exec`s the target command. The secret
value exists only in the child process -- never in the agent's context.

### Usage

```bash
# Pass a database password to psql without exposing it
asm-exec -- psql \
  "host=mydb.example.com \
   user={{resolve:secretsmanager:prod/db-creds:SecretString:username}} \
   password={{resolve:secretsmanager:prod/db-creds:SecretString:password}}" \
  -c "SELECT * FROM users LIMIT 10"

# Use default field-type (SecretString) and full value (no json-key)
asm-exec -- curl -H "Authorization: Bearer {{resolve:secretsmanager:prod/api-token}}" \
  https://api.example.com/data

# Multiple secrets in one command
asm-exec -- mysql \
  -h {{resolve:secretsmanager:prod/mysql:SecretString:host}} \
  -u {{resolve:secretsmanager:prod/mysql:SecretString:username}} \
  -p{{resolve:secretsmanager:prod/mysql:SecretString:password}} \
  -e "SHOW TABLES"
```

### How It Works

1. Scans all command arguments for `{{resolve:...}}` patterns
2. Resolves each reference via the Secrets Manager Agent (SMA) on localhost:2773,
   falling back to AWS CLI if SMA is unavailable
3. Substitutes resolved values using `re.sub` with a callable (single-pass --
   prevents re-scan injection if a secret value contains `{{resolve:...}}`)
4. Runs the target command via `subprocess.run` -- secret values exist only in the
   asm-exec process, never in the agent's context window

### Prerequisites

- **AWS Secrets Manager Agent (SMA)** running on localhost:2773 (recommended), OR
- **AWS CLI** configured with credentials that have `secretsmanager:GetSecretValue`
  permission

See [SMA setup guide](https://docs.aws.amazon.com/secretsmanager/latest/userguide/secrets-manager-agent.html).

## Common Patterns

### Database connections

```bash
asm-exec -- psql "postgresql://{{resolve:secretsmanager:prod/db:SecretString:username}}:{{resolve:secretsmanager:prod/db:SecretString:password}}@db.example.com:5432/mydb"
```

### Docker with secrets

```bash
asm-exec -- docker run -e "DB_PASSWORD={{resolve:secretsmanager:prod/db:SecretString:password}}" myapp:latest
```

### Configuration file templating

```bash
# Generate config with resolved secrets, write to file
asm-exec -- sh -c 'echo "password={{resolve:secretsmanager:app/db:SecretString:password}}" > /tmp/app.conf'
```

## Structural Enforcement (Plugin Hook)

When the `aws-core` plugin is enabled, a `PreToolUse` hook automatically blocks
any attempt to call `get-secret-value` or `batch-get-secret-value` -- via AWS CLI,
MCP tools, or direct SMA access. No manual configuration needed.

The hook is defined at `plugins/aws-core/hooks/hooks.json` and activates
automatically when the plugin is installed.

## Troubleshooting

### "Secret not found" errors

Verify the secret exists and your IAM role has `secretsmanager:GetSecretValue`
permission. Check the secret name matches exactly (case-sensitive).

### SMA connection refused

The Secrets Manager Agent may not be running. Start it or ensure AWS CLI
credentials are configured as fallback.

### Resolution produces empty string

The JSON key may not exist in the secret value. Verify the secret structure
in the AWS Console or ask the secret owner to confirm the available keys.
