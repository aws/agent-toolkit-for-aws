# IAM and encryption

## Overview

Write least-privilege IAM policies for OpenSearch Memory and set up a customer managed KMS key.

## IAM basics

- **Action prefix:** `osm:` (for example `osm:CreateSpace`, `osm:SearchMemories`).
- **Space ARN:** `arn:aws:osm:<region>:<account-id>:space/<space-id>`.
- **Resource-based policies:** not supported. Use identity-based policies.

**Dependent actions:**

- `create-space` with tags also needs `osm:TagResource`.
- `create-event` with a `blob` document in S3 needs `s3:GetObject` on that object, and `kms:Decrypt` on its key if the object uses SSE-KMS.
- Creating a space with a customer managed key, and the event and memory operations on it, need KMS permissions (below).

**Condition keys** (multivalued; use `ForAllValues`/`ForAnyValue`, plus a `Null` check to require the key):

| Key | Supported by |
|---|---|
| `osm:actorId` | All event and memory operations |
| `osm:sessionId` | CreateEvent, GetEvent, BatchGetEvent, ListEvents, SearchEvents, DeleteEvent |
| `osm:strategyName` | CreateMemory, GetMemory, ListMemories, SearchMemories, UpdateMemory, DeleteMemory |

Tags: `aws:ResourceTag/<key>` on spaces; `aws:RequestTag/<key>` and `aws:TagKeys` on CreateSpace and TagResource; `aws:TagKeys` on UntagResource.

## Example policies

**Read-only agent on one space:**

```json
{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
 "Action":["osm:SearchMemories","osm:GetMemory","osm:ListMemories"],
 "Resource":"arn:aws:osm:<region>:<account-id>:space/<space-id>"}]}
```

- To also read events, add `osm:GetEvent`, `osm:BatchGetEvent`, `osm:ListEvents` and `osm:SearchEvents`.
- Do not include any `Create*`, `Update*` or `Delete*` action.

**One end user only:** add to the statement above:

```json
"Condition":{"ForAllValues:StringEquals":{"osm:actorId":["user-123"]},"Null":{"osm:actorId":"false"}}
```

The `Null` condition denies requests that omit the actor, which would otherwise read every actor in the space.

**Writer for an application:** `osm:CreateEvent` (and `osm:CreateMemory` if it writes memories directly) on the space ARN.

**Space administration:** `osm:CreateSpace`, `osm:GetSpace`, `osm:ListSpaces`, `osm:UpdateSpace`, `osm:DeleteSpace`, `osm:TagResource`, `osm:UntagResource`, `osm:ListTagsForResource` on `arn:aws:osm:<region>:<account-id>:space/*`.

## Customer managed KMS key

**Setting it:**

- Set `--encryption-configuration '{"kmsKeyArn":"<key-arn>"}'` on `create-space`. It cannot be changed later.
- Without it, data is encrypted with an AWS owned key.

**Key requirements:**

- A symmetric encryption key.
- Enabled.
- Specified by its key ARN, not an alias.
- In the same Region as the space. For a multi-Region key, use the replica ARN in that Region.

**How access works:**

- OpenSearch Memory calls KMS with the caller's own credentials. The key policy needs no service principal, but the calling principal must be allowed to use the key.
- On create, the service creates grants named `osm-space-<space-id>` and `osm-space-<space-id>-worker`. It retires them when the space is deleted.
- Disabling the key makes the space's data unreadable. Revoking the grants stops memory extraction; API calls keep working while the caller can use the key.

**KMS permissions per operation:**

| Operation | KMS permissions |
|---|---|
| CreateSpace | `kms:CreateGrant` |
| CreateEvent, CreateMemory | `kms:Decrypt`, `kms:GenerateDataKey`, `kms:GenerateDataKeyWithoutPlaintext`, `kms:ReEncryptFrom`, `kms:ReEncryptTo` |
| UpdateMemory | `kms:Decrypt`, `kms:GenerateDataKey` |
| GetEvent, BatchGetEvent, ListEvents, SearchEvents, DeleteEvent, GetMemory, ListMemories, SearchMemories, DeleteMemory | `kms:Decrypt` |

**Limiting the key to OpenSearch Memory:**

- Add the condition `"StringEquals":{"kms:ViaService":"osm.<region>.amazonaws.com"}`.
- On `kms:CreateGrant`, also add `"ForAllValues:StringEquals":{"kms:GrantOperations":["Decrypt","GenerateDataKey","DescribeKey","CreateGrant"]}`.
- Put these in the IAM policy or the key policy.

## Errors

| Error | Cause | Fix |
|---|---|---|
| `AccessDeniedException` "Caller is not authorized to create a grant on the KMS key" | Principal lacks `kms:CreateGrant` on the key | Grant it in IAM or the key policy |
| `ValidationException` "KMS key is not usable" | Key disabled, missing, wrong type | Use an enabled symmetric key ARN |
| `ValidationException` "KMS key must be in the Space's region" | Key in another Region | Use a key, or MRK replica, in the space's Region |
| Requests fail only on a CMK space | Principal lacks the data-operation KMS permissions | Grant the permissions in the table above |
