---
name: amazon-opensearch-memory
description: Integrates an AI agent with Amazon OpenSearch Memory (OpenSearch Memory, CLI `aws opensearchmemory`, IAM prefix `osm:`), a managed service that stores conversation events and extracts long-term memories from them. Use only when the user names OpenSearch Memory, an OpenSearch Memory space, or `aws opensearchmemory`, for creating or updating a space and its strategies (SEMANTIC, SUMMARY, CUSTOM), writing events, searching, listing, updating or deleting memories, event and memory retention, IAM policies or customer managed KMS keys for spaces, or OpenSearch Memory errors such as ResourceNotFoundException after a space is ACTIVE, ConflictException while UPDATING, a ValidationException on a search query, or memories not appearing. Does NOT cover Amazon Bedrock AgentCore Memory (use amazon-bedrock), agent memory on Amazon Neptune (use amazon-neptune), or your own vector search on OpenSearch Service or Serverless (use amazon-opensearch-service).
version: 1
---

# Amazon OpenSearch Memory

## Overview

Amazon OpenSearch Memory gives agents durable memory. You create a **space**, declare the **memory strategies** that decide what is extracted, write conversation turns as **events**, and search the **memories** the service extracts from them asynchronously.

All commands use the AWS CLI service `opensearchmemory` (boto3 client `opensearchmemory`): each API operation is a hyphenated lowercase command, such as `aws opensearchmemory create-space`, and accepts `--cli-input-json file://request.json`. Endpoints are `https://osm.<region>.api.aws` for spaces and `https://<space-id>.osm.<region>.on.aws` for events and memories; the SDK picks them automatically. The AWS MCP server is recommended for sandboxed execution and audit logging. If its tools report that the OpenSearch Memory service or an operation is not supported, run the same AWS CLI commands in a local shell instead. Do not substitute Amazon Bedrock AgentCore Memory or OpenSearch Serverless APIs: they are different services.

## Prerequisites

- An AWS CLI v2 or boto3 version that includes OpenSearch Memory. Confirm with `aws opensearchmemory help`, and confirm that `aws opensearchmemory search-memories help` lists `--search-query`. If either is missing, upgrade the AWS CLI before continuing.
- Credentials with the `osm:` actions you need (see [references/security-and-encryption.md](references/security-and-encryption.md)).
- A Region that offers OpenSearch Memory; check [AWS Services by Region](https://aws.amazon.com/about-aws/global-infrastructure/regional-product-services/). Pass `--region` on every command.

## Concepts

| Term | What it is |
|---|---|
| Space | Container for one application's events and memories. ID `sp-` + 12 hex. States: CREATING, ACTIVE, UPDATING, DELETING, FAILED (a deleted space returns `ResourceNotFoundException`) |
| Memory strategy | Declared on the space (0-10). Types: `SEMANTIC` (facts), `SUMMARY` (session summaries), `CUSTOM` (your extraction prompt). A space with no strategies stores events only and extracts nothing |
| Event | A conversation turn or batch of turns (or a JSON object, or a document in S3) for one actor and session. Readable immediately |
| Memory | A fact or summary extracted from events asynchronously, or written directly with `create-memory` |
| Actor / session | `actorId` identifies the end user; `sessionId` groups one conversation. Every memory search is scoped to one actor |

## Choose the task

| User wants to | Read |
|---|---|
| Create a space, add or change strategies, set retention, delete a space | [references/spaces-and-strategies.md](references/spaces-and-strategies.md) |
| Write conversation turns, read events back, write or edit memories directly, delete user data | [references/events-and-memories.md](references/events-and-memories.md) |
| Search or list memories, build a search query, filter by time or metadata | [references/search.md](references/search.md) |
| IAM policies, per-user isolation, customer managed KMS key | [references/security-and-encryption.md](references/security-and-encryption.md) |
| An error, or memories not appearing | [references/troubleshooting.md](references/troubleshooting.md) |

## Rules that prevent the most common mistakes

- **Extraction is asynchronous.** `create-event` returns once the event is stored. `get-event` works immediately, but a memory search only matches after the strategy's extraction trigger fires and the result is indexed. Poll; do not report failure after one empty search.
- **Wait for ACTIVE before the first write.** Event and memory calls return `ResourceNotFoundException` ("...collection is not provisioned yet") until the space is ready, sometimes briefly after it reports ACTIVE. Wait for ACTIVE, then retry with backoff.
- **Wait for a settled state.** `update-space` and `delete-space` return `ConflictException` while the space is CREATING or UPDATING (and `update-space` also while DELETING). Run `aws opensearchmemory wait space-active --space-id <id> --region <r>` first.
- **`update-space --memory-strategies` replaces the whole set.** Read the current strategies with `get-space` and send every strategy you want to keep.
- **Search needs `--actor-id`.** Scope by actor with the request parameter, never with `system_metadata.actor_id` inside the query. `search-memories` searches all of the actor's sessions; to work with one session, use `search-events --session-ids` or `list-events` for its raw turns, or `list-memories --session-ids` to browse its memories.
- **A search takes a query clause and an optional sort.** Pass the OpenSearch query clause itself with `--search-query` (API member `query`) and an optional `--sort`. There are no `size`, `from` or aggregation parameters: the CLI pages for you, and `--max-items` caps the results (API `maxResults`/`nextToken`).
- **Deleting an event does not delete its memories.** Delete memories with `delete-memory`, or delete the whole space.
- **Route errors on the error code, not the HTTP status.** Client errors arrive as HTTP 400 and server errors as HTTP 500.

## Quick start

1. Create a space with fact and summary extraction, then wait for it.

   ```bash
   aws opensearchmemory create-space --region us-east-1 \
     --name support-bot-memory \
     --memory-strategies '[{"type":"SEMANTIC","name":"user-facts"},{"type":"SUMMARY","name":"session-summaries"}]'
   aws opensearchmemory wait space-active --region us-east-1 --space-id <space-id>
   ```

2. Write a conversation turn for one user and session. `$USER_TEXT` holds the user's message, for example "I live in Porto and I am vegetarian."

   ```bash
   PAYLOAD=$(jq -n --arg text "$USER_TEXT" \
     '{conversational:{unified:{source:{object:{messages:[{role:"USER",content:{text:$text}}]}}}}}')
   aws opensearchmemory create-event --region us-east-1 --space-id <space-id> \
     --actor-id user-42 --session-id chat-1 --payload "$PAYLOAD"
   ```

3. Later, search what was extracted for that user. `$QUERY_TEXT` holds the question, for example "where does the user live".

   ```bash
   QUERY=$(jq -n --arg q "$QUERY_TEXT" '{neural:{memory_vector:{query_text:$q,k:5}}}')
   aws opensearchmemory search-memories --region us-east-1 --space-id <space-id> \
     --actor-id user-42 --search-query "$QUERY"
   ```

Before running any command, ask the user for anything missing: Region, space ID or name, actor ID, and strategy names.

## Security considerations

- Grant least privilege: only the `osm:` actions each principal needs, scoped to specific space ARNs (`arn:aws:osm:<region>:<account-id>:space/<space-id>`). Give read-only agents only the read actions they use, such as `osm:SearchMemories`, `osm:GetMemory` and `osm:ListMemories` (plus `osm:GetEvent`, `osm:BatchGetEvent`, `osm:ListEvents` and `osm:SearchEvents` to read events).
- Isolate end users: use one `actorId` per end user and restrict principals with the `osm:actorId` condition key plus a `Null` check.
- Use IAM roles with temporary credentials rather than long-term access keys, and follow the [IAM security best practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html).
- Use a customer managed KMS key for sensitive data. It can only be set at `create-space`. Both endpoints use HTTPS, so requests are encrypted in transit.
- Do not put secrets or credentials in events, memories or metadata. Metadata is copied into every derived memory and is searchable. Redact personal data before sharing logs or support material.
- Build JSON arguments with a tool (for example `jq -n --arg`), not by pasting user text into a string, and validate IDs against the documented patterns.
- Confirm with the user before `delete-space`, `delete-memory`, `delete-event`, or an `update-space` that removes strategies or shortens retention. Deletes are permanent.
- Review API activity in AWS CloudTrail (event source `osm.amazonaws.com`). Space operations are logged as management events by default; event and memory operations are data events, which you enable with an advanced event selector on resource type `AWS::Osm::Space`.

## Not covered

- Amazon Bedrock AgentCore Memory: use the `amazon-bedrock` skill.
- Vector, semantic or hybrid search on your own OpenSearch Service domain or Serverless collection: use the `amazon-opensearch-service` skill.

## Guardrail — where this skill's own files live (MCP vs local install)

This skill can be loaded two ways, and they resolve the skill's own bundled
files from different places. Determine how the skill was loaded before reading
a reference or running a script:

- **Loaded through the AWS MCP `retrieve_skill` tool:** The skill is not
  installed on the local filesystem. You MUST fetch each reference or script
  via `retrieve_skill` with the `file` parameter (e.g.
  `file="references/architecture.md"` or `file="scripts/deploy.py"`), and
  run the script from the returned content. Do NOT `file_read` these paths
  locally — they do not exist on disk.
- **Installed locally** (e.g. `.kiro/skills/your-skill/` or
  `~/.claude/skills/your-skill/`): Read and run files from the local skill
  directory using relative paths.

This distinction applies only to the skill's own packaged files. User data and
session artifacts are always read from and written to the user's working
directory. Never fetch or write customer data through `retrieve_skill`.
