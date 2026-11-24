# Events and memories

## Overview

Write conversation turns as events, read them back, write or edit memories directly, and delete a user's data.

## Write events

Build the payload with `jq` so any text, including quotes, apostrophes and newlines, is escaped (`$USER_TEXT` and `$ASSISTANT_TEXT` hold the turns):

```bash
PAYLOAD=$(jq -n --arg user "$USER_TEXT" --arg assistant "$ASSISTANT_TEXT" \
  '{conversational:{unified:{source:{object:{messages:[
    {role:"USER",content:{text:$user}},
    {role:"ASSISTANT",content:{text:$assistant}}]}}}}}')
aws opensearchmemory create-event --region <region> --space-id <space-id> \
  --actor-id <actor-id> --session-id <session-id> \
  --payload "$PAYLOAD" \
  [--metadata '{"channel":"web"}'] [--client-token <token>] [--no-infer]
```

**Fields:**

| Field | Rule |
|---|---|
| `actorId`, `sessionId` | 1-255 chars, `^[a-zA-Z0-9][a-zA-Z0-9-_]*$` (must start alphanumeric) |
| messages | 1-100 per event, in order; `role` is `USER`, `ASSISTANT` or `SYSTEM`; text non-empty; total text ≤ 5 MiB, no per-message limit |
| `metadata` | Up to 15 keys per event, and at most 50 distinct keys per space. Key `^[a-zA-Z0-9_-]{1,128}$` (no dots); value ≤ 256 chars of letters, digits, whitespace and `._:/=+@-` (no commas, quotes, emoji or non-ASCII). Reserved keys are rejected: keys starting `x-amz-`, `documentS3Source`, `documentS3Url`, and other service-internal keys |
| `eventTimestamp` | RFC 3339; defaults to server time |
| `clientToken` | 1-512 printable ASCII characters, no spaces. Same token and same content within 2 hours returns the same `eventId`; different content → `ConflictException`. A retry must repeat the same `sessionId` |

- **`sessionId`:** always send a stable value per conversation. When omitted, the service generates one, and derived-memory quality suffers.
- **Metadata:** copied into every memory extracted from the event, so you can filter on it later. See [search.md](search.md).
- **`--no-infer`** (`infer=false`): stores the event and indexes it for `search-events`, but strategies skip its turns or structured data, so no memories are extracted from them. A document submitted in a `blob` payload is still processed.
- **Payload:** set exactly one of:
  - `conversational.unified.source.object.messages`: conversation turns (above). A conversational event can't carry a document.
  - `structuredData.source.json`: a JSON object (not a top-level array or scalar), at most 1 MiB and 10 levels deep, such as `{"structuredData":{"source":{"json":{"service":"checkout","result":"rolled back"}}}}`.
  - `blob`: a document in Amazon S3, `{"blob":{"contentType":"application/pdf","source":{"s3Location":{"uri":"s3://<bucket>/<key>.pdf"}}}}`. `contentType` is `application/pdf`, `image/png` or `image/jpeg`. The object can be at most 25 MiB, and inline bytes are not supported. The service reads the object with the caller's credentials (`s3:GetObject`, plus `kms:Decrypt` for an SSE-KMS object); the bucket must be in the space's Region and the object not in an archive storage class.
- **Space state:** events are refused until the space is provisioned and once it is being deleted. `ResourceNotFoundException` "...collection is not provisioned yet" means the space isn't ready yet, including briefly after it reports ACTIVE: wait for ACTIVE and retry with backoff.

## Read events (short-term memory)

| Command | Use |
|---|---|
| `get-event --space-id --event-id` | The full event, immediately after it is written |
| `batch-get-event --space-id --event-ids` | Up to 10 events by ID; per-ID failures come back in `errors` |
| `list-events --space-id --actor-id --session-id` | One actor's session, newest first by default. Optional time bounds (`--event-timestamp-after/--before`, inclusive) and exact-match `--metadata-filters`. Returns metadata, not payloads |
| `search-events --space-id --actor-id --search-query` | Searches verbatim event text. Same query rules as memories, but on fields `text` / `vector`. Each result is the matching chunk of an event; call `get-event` for the whole event. Filter on `event_ids` with `term`/`terms` (up to 10 IDs) to search specific events |

- There is no way to list events across sessions. `list-events` needs both actor and session.
- By-ID commands accept optional `--actor-id` and `--session-id`. If the stored event does not match them, the call returns `ResourceNotFoundException`, as if the event did not exist; `batch-get-event` instead lists that ID in `errors` with `RESOURCE_NOT_FOUND`.

## When memories appear

**Asynchronous extraction:**

- Extraction runs per strategy when a trigger is reached (`extractEveryNMessages`, `extractEveryNTokens`) or when the conversation has been idle for `idleTimeoutSeconds`.
- After extraction the memory still has to be indexed.
- So a search right after `create-event` usually finds nothing.

**If nothing appears:**

1. Confirm the event exists (`get-event` or `list-events`).
2. Confirm it was not written with `--no-infer`.
3. Search with the same `--actor-id`.
4. Poll.

To extract sooner, lower `extractEveryNMessages` or `idleTimeoutSeconds` on the strategy.

## Write a memory directly

Pass the text in a quoted shell variable (`$MEMORY_TEXT` holds the fact, for example "user-42 is allergic to peanuts"):

```bash
aws opensearchmemory create-memory --region <region> --space-id <space-id> \
  --name <strategy-name> --actor-id <actor-id> --content "$MEMORY_TEXT"
```

**What it does:**

- Writes into an existing strategy by name and skips extraction and consolidation.
- `content` is 1-16,000 chars and must fit the embedding model's input (about 6,000 tokens; fewer characters for scripts such as Chinese, Japanese or Korean).
- Returns the final `memoryId` before the memory is searchable: indexing is asynchronous, so poll `get-memory` or `search-memories`.

**`clientToken`:** within 2 hours, the same token returns the same `memoryId`; the same token with a different name, content, metadata, actor or session returns `ConflictException`. Without a token, each call creates a new memory.

## Read, update and delete memories

| Command | Notes |
|---|---|
| `get-memory --space-id --memory-id` | Returns content, type, strategy name, timestamps, metadata |
| `list-memories --space-id [--actor-ids] [--session-ids] [--memory-strategies] [--sort-by CREATED_AT\|UPDATED_AT]` | Browse without content; no metadata filtering. Unlike `search-memories`, includes memories that consolidation replaced. Pages by position, so results can shift if memories change while you page |
| `update-memory --space-id --memory-id [--content] [--metadata] [--metadata-mode REPLACE\|MERGE]` | In place, same `memoryId`; send `content`, `metadata` or both. New `content` is re-embedded. Concurrent updates are last-writer-wins, so serialize updates to one memory |
| `delete-memory --space-id --memory-id` | Permanent. Deleting an ID that is already gone returns `ResourceNotFoundException`; on a retry, treat that as success |

**`update-memory` metadata:**

- `metadata` REPLACES the stored map by default.
- With `--metadata-mode MERGE`, an empty-string value removes that key.

**After a delete:** search results can show the deleted memory briefly.

**Expired memories:** left out of search and list, and by-ID calls return `ResourceNotFoundException`.

**Scope check:** by-ID memory commands accept optional `--actor-id` and `--strategy-name`. A mismatch returns `ResourceNotFoundException`.

## Delete a user's data

Confirm with the user first; deletes are permanent.

1. **Find their memories:** `list-memories --actor-ids <actor-id>`, collecting every page before you delete. `delete-memory` each `memoryId`. A listing stops at 10,000 results; if it reached that, list again after deleting.
2. **Find their events:** `list-events --actor-id <actor-id> --session-id <session-id>` for each session. `delete-event` each `eventId`.
3. **Remember events and memories are separate:** `delete-event` does not delete memories extracted from that event, so do step 1 as well.

To remove everything for an application, delete the space instead (see [spaces-and-strategies.md](spaces-and-strategies.md)).
