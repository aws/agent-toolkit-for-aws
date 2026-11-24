# Spaces and memory strategies

## Overview

Create, inspect, update and delete OpenSearch Memory spaces, and choose the memory strategies that decide what is extracted.

## Create a space

```bash
aws opensearchmemory create-space --region <region> \
  --name <name> \
  --memory-strategies '[{"type":"SEMANTIC","name":"user-facts"},{"type":"SUMMARY","name":"session-summaries"}]' \
  [--event-expiry-days 90] [--memory-expiry-days <days>] \
  [--encryption-configuration '{"kmsKeyArn":"<key-arn>"}'] \
  [--tags '[{"key":"team","value":"support"}]'] \
  [--client-token <token>]
aws opensearchmemory wait space-active --region <region> --space-id <space-id>
```

**Rules:**

| Field | Rule |
|---|---|
| `name` | 1-128 chars, `^[a-zA-Z][a-zA-Z0-9 _-]*$`, unique per account and Region. A duplicate name returns `ConflictException` |
| `memoryStrategies` | 0-10 entries; strategy names unique within the space. Omit it or send `[]` for a space that stores events only: it extracts no memories, and `search-memories`/`list-memories` on it return `ResourceNotFoundException` "No searchable memory strategies exist for this space." |
| `eventExpiryDays` | 1-365; default 90. How long raw events are kept |
| `memoryExpiryDays` | 0-3650 days. Omit it or send 0 and memories never expire |
| `clientToken` | 1-512 printable ASCII characters, no spaces |

- The response is `spaceId, arn, name, status, createdAt`. A new space returns `CREATING`; a `clientToken` retry returns the existing space's current status.
- Wait for `ACTIVE` before writing events. The waiter fails if the space reaches `FAILED`; then read `statusReason` from `get-space`.
- `clientToken` behavior:
  - Same token and same request within 2 hours returns the existing space instead of a duplicate.
  - Same token with a different request returns `ConflictException`.
- The KMS key can only be set here and cannot be changed later. See [security-and-encryption.md](security-and-encryption.md).
- Creating a space with `--tags` needs both `osm:CreateSpace` and `osm:TagResource`.

## Choose strategies

| Type | Extracts | Use when |
|---|---|---|
| `SEMANTIC` | Durable facts about the actor ("lives in Porto", "vegetarian") | The agent must recall user facts and preferences across sessions |
| `SUMMARY` | Summaries of a session | The agent needs the gist of past conversations |
| `CUSTOM` | Whatever your `extractionPrompt` asks for | A domain record such as open support issues or orders |

A strategy `name` is optional: 1-64 chars, `^[A-Za-z0-9][A-Za-z0-9_.-]*$` (no spaces). Omitted names are generated as `semantic_1`, `summarization_1`, `custom_1`. Name strategies explicitly, because search selectors and `create-memory` refer to them by name.

**Per-strategy `configuration` (all optional):**

| Member | Range | Default | Effect |
|---|---|---|---|
| `extractEveryNMessages` | 1-1,000 | 12 | Extract once this many messages accumulate |
| `extractEveryNTokens` | 1-80,000 | no token bound | Extract once this many tokens accumulate |
| `idleTimeoutSeconds` | 1-86,400 | 60 | Extract after the conversation is silent this long. This is the only trigger that fires when a conversation simply stops |
| `extractionPrompt` | up to 30,720 chars | — | Your extraction instructions. Required on CUSTOM strategies (`update-space` keeps the stored one if you omit it). SEMANTIC and SUMMARY use built-in instructions and reject an `extractionPrompt` |
| `consolidationEnabled` | true / false | on for every type | true: a new memory adds to, updates or skips similar stored ones. false: append-only history |

- The three triggers are ceilings on the same batch: whichever is reached first fires extraction.
- The serialized strategy list may be at most 384 KiB.

**Example: a custom strategy:**

```json
{"type":"CUSTOM","name":"open-tickets","configuration":{"extractionPrompt":"Extract each unresolved support issue the user mentions, with the product name.","idleTimeoutSeconds":120}}
```

**Extraction model:** `--extraction-model-id` accepts `anthropic.claude-opus-5-5` or `anthropic.claude-haiku-5-5` (no inference-profile prefix). Omit it to use the service default.

## Inspect spaces

```bash
aws opensearchmemory get-space --region <region> --space-id <space-id>
aws opensearchmemory list-spaces --region <region>
```

- `get-space` returns the strategies with their generated names, the retention and any customer managed key. A strategy's `configuration` shows only the members you set; omitted members use the defaults above.
- An absent `eventExpiryDays` means 90 days; an absent `memoryExpiryDays` means memories never expire.

## Update a space

```bash
aws opensearchmemory wait space-active --region <region> --space-id <space-id>
aws opensearchmemory get-space --region <region> --space-id <space-id> --query memoryStrategies
aws opensearchmemory update-space --region <region> --space-id <space-id> \
  --memory-strategies '<every strategy to keep, plus the new one>'
aws opensearchmemory wait space-active --region <region> --space-id <space-id>
```

**What gets changed:**

- Only the fields you send change.
- `memoryStrategies` replaces the whole set, so include the existing strategies you want to keep. It needs at least one strategy: you can't remove every strategy from a space.
- Within a strategy you resend, configuration members you omit keep their current values; you can't clear them.
- Strategies are matched by type and name, and names are case-sensitive.
- Removing a strategy stops extraction for it. It does not delete the memories it already created; adding back the same type and name makes them available again.
- Once set, the extraction model can't be cleared.

**Status and timing:**

- Changing strategies, `eventExpiryDays`, `memoryExpiryDays` or the extraction model moves the space to `UPDATING`. While it is UPDATING, `get-space` shows the previous configuration.
- While the space is CREATING, UPDATING or DELETING, `update-space` returns `ConflictException`. Wait for ACTIVE and retry; a DELETING space can't be updated.

**Retention:**

- To return `memoryExpiryDays` to the default (never expire), send `0`. Omitting it leaves the value unchanged.
- A `memoryExpiryDays` change applies to memories written after it. Memories already stored keep their expiry.

## Delete a space

Confirm with the user first; this is permanent.

```bash
aws opensearchmemory delete-space --region <region> --space-id <space-id>
aws opensearchmemory wait space-deleted --region <region> --space-id <space-id>
```

- Deletes the space and its memories.
- Returns `ConflictException` while the space is CREATING or UPDATING.
- When deletion finishes, `get-space` returns `ResourceNotFoundException`: treat that as deleted.
- When asked to delete "unused" spaces:
  1. List them first.
  2. Show the user which ones match.
  3. Delete only the confirmed IDs.

## Common errors

| Error | Cause | Fix |
|---|---|---|
| `ConflictException` "A Space named ... already exists" | Duplicate name | Choose another name or reuse the existing space |
| `ConflictException` "...cannot be updated until that finishes" | Space is CREATING/UPDATING/DELETING | `wait space-active`, then retry (a DELETING space can't be updated) |
| `ValidationException` "Unsupported memory strategy type" | Type not SEMANTIC/SUMMARY/CUSTOM | Use a supported type |
| `ValidationException` "Duplicate memory strategy name" | Two strategies share a name | Rename one |
| `ValidationException` "... requires an extractionPrompt" | A CUSTOM strategy without `extractionPrompt` | Add the extraction instructions |
| `ServiceQuotaExceededException` | Space or strategy quota reached | Delete unused spaces or request an increase |
| Waiter fails on `FAILED` | Provisioning failed | `get-space` and read `statusReason` |
| `ConflictException` "Space has no provisioned collection yet" on update | The space failed before it was provisioned | Delete it and create a new space |
| `ThrottlingException` on space operations | Control-plane rate limits: 5/s for create, update, delete and tagging; 10/s for `list-spaces`; 20/s for `get-space` | Retry with backoff |
