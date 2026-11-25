# Troubleshooting

## Overview

Map OpenSearch Memory symptoms to causes and fixes.

## How errors arrive

- Route on the error code (the `__type`), not the HTTP status. Client errors arrive as HTTP 400 and server errors as HTTP 500.
- Search validation errors carry a `reason` and a `fieldList` (see the reason codes in [search.md](search.md)).

## Symptom to cause

| Symptom | Likely cause | Fix |
|---|---|---|
| `aws: error: argument command: Invalid choice … opensearchmemory` | AWS CLI too old | Upgrade the AWS CLI (or boto3) to a version that includes OpenSearch Memory |
| `aws opensearchmemory search-memories` treats `--query` as an output filter, or says `--search-query` is required | `--query` is the AWS CLI's global output filter | Pass the query with `--search-query` (or `query=` in boto3) |
| AWS MCP tools say the service or operation is not supported | The MCP server's SDK does not include OpenSearch Memory yet | Run the same `aws opensearchmemory` commands in a local shell |
| `ResourceNotFoundException` "…collection is not provisioned yet" | The space is not ready yet: still CREATING, or just reached ACTIVE | `wait space-active`, then retry with backoff |
| `ResourceNotFoundException` "Space is not accepting events" | The space does not exist, is not provisioned yet, or is being deleted | Check the space ID; `wait space-active`, then retry |
| Search returns nothing after `create-event` | Extraction is asynchronous; trigger not reached yet; `--no-infer` used; different `--actor-id`; strategy selector names another strategy | Confirm the event with `get-event`, check `infer` and actor, poll; lower `extractEveryNMessages`/`idleTimeoutSeconds` for faster extraction |
| `create-memory` succeeded but `get-memory` returns not found | Indexing is asynchronous | Poll |
| `ConflictException` on `update-space`/`delete-space` | Space is CREATING or UPDATING (or DELETING, for updates) | `wait space-active`, then retry |
| `ConflictException` "Space has no provisioned collection yet" | The space failed before provisioning | Delete it and create a new space |
| `ConflictException` "clientToken reused with different request content" | Same `clientToken` with a different request | Use a new token per distinct request |
| `ValidationException` (or an SDK "Unknown parameter" error) for `size`, `from`, `aggs` or `searchBody` | Searches take only `query` and `sort`; paging is a request parameter | Use `--max-items`/`maxResults` and `nextToken`; count client-side |
| `ResourceNotFoundException` "No searchable memory strategies exist for this space." | The space was created without strategies | Add a strategy with `update-space`, or use `search-events`/`list-events` |
| `ValidationException` `reason=nonFilterableField` | `system_metadata.actor_id`/`session_id` or `memory_type` in the query | Use `--actor-id` and `--memory-strategies` (`--session-ids` on `search-events`) |
| `ValidationException` "Unknown or non-searchable field 'content'" | The queryable text field is `memory_text` | Query `memory_text` |
| `ValidationException` on metadata | Dotted key, comma/quote/emoji/non-ASCII value, more than 15 keys, an `x-amz-` key, or a new key past the space's 50 distinct keys | Fix the key or value to match the rules, or reuse an existing key |
| `ValidationException` on the payload | A `conversational` payload without `unified`, a blob whose `contentType` is not `application/pdf`, `image/png` or `image/jpeg` or that has no `source.s3Location.uri`, or structured data that is not a JSON object | Send one supported payload shape (see [events-and-memories.md](events-and-memories.md)) |
| `ResourceNotFoundException` on `get-*`/`delete-*` with `--actor-id` | The record belongs to another actor, session or strategy | Drop or correct the scope parameters |
| A memory still appears after `delete-event` | Event deletes do not cascade | `delete-memory` the derived memories |
| `AccessDeniedException` "Caller is not authorized for the requested space" | Wrong space ID, account, or per-space host | Use the space's own ID and Region |
| `AccessDeniedException` (other) | Missing `osm:` action, resource ARN, condition key, or KMS permission; or the request was not signed for `osm` | See [security-and-encryption.md](security-and-encryption.md) |
| `ThrottlingException` | Rate exceeded | Retry with exponential backoff |
| `InternalServerException` | Server-side failure | Retry with backoff, reusing the same `clientToken` |
