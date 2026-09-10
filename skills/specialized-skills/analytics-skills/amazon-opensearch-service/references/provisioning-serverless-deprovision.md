# Amazon OpenSearch Serverless — Deprovision (Teardown)

Delete serverless resources in strict dependency order. Reversing the order fails, because a collection group cannot be deleted while it still has collections, and a security policy cannot be deleted while a collection it covers still exists.

The AWS MCP server is recommended for executing these teardown commands but is not required — all steps use standard AWS CLI syntax.

## Order (MUST follow)

1. Delete collection(s)
2. Wait until each collection is fully gone
3. Delete the collection group (NextGen only)
4. Delete the security/data access policies

> **Destructive-action rule:** before deleting anything below, list every resource that will be removed and get explicit user confirmation, because collection deletion (Step 1) is irreversible and destroys all indexed data.

## Step 1: Delete collection(s)

```bash
aws opensearchserverless delete-collection --id <collection-id>
```

A collection MUST be ACTIVE (or FAILED) before it can be deleted. If delete returns `ConflictException` about status, the collection is still being created — wait and retry, because AOSS rejects deletes on collections mid-creation.

## Step 2: Confirm deletion completed

```bash
aws opensearchserverless batch-get-collection --ids <id1> <id2>
```

Deletion is complete when EITHER the id appears in `collectionErrorDetails` with `"errorCode":"NOT_FOUND"` OR `collectionDetails` is empty. Do NOT poll for a `DELETED` status, because AOSS removes the collection entirely and returns NOT_FOUND rather than a terminal status.

## Step 3: Delete the collection group (NextGen)

```bash
aws opensearchserverless delete-collection-group --id <group-id>
```

If this returns `ValidationException` ("has collections associated"), a collection in the group is still active or still deleting — delete/await remaining collections first, because a non-empty group cannot be removed.

## Step 4: Delete policies

```bash
aws opensearchserverless delete-security-policy --type network    --name <name>-network
aws opensearchserverless delete-security-policy --type encryption --name <name>-encryption
aws opensearchserverless delete-access-policy   --type data       --name <name>-data
```

## Security Considerations

- **Verify a backup exists first, and that it is encrypted at rest.** Collection deletion is irrecoverable — confirm a snapshot or exported copy exists before proceeding if the data may still be needed, because there is no undo. Ensure the backup itself is encrypted at rest (e.g., S3 server-side encryption with a customer-managed KMS key for a manual snapshot or export), because an unencrypted copy of sensitive data is a standing exposure risk even after the collection is deleted.
- **Audit who initiated the teardown.** Confirm AWS CloudTrail is enabled so the `DeleteCollection`/`DeleteCollectionGroup`/`Delete*Policy` calls are recorded with the caller identity and timestamp.
- **Alert in real time on teardown calls.** Beyond passive CloudTrail logging, configure an EventBridge rule (or a CloudTrail → CloudWatch metric filter) on `DeleteCollection`/`DeleteCollectionGroup` from unexpected principals that notifies via SNS, because an irreversible delete warrants immediate detection rather than after-the-fact log review. Encrypt the SNS topic with a customer-managed KMS key and restrict `sns:Subscribe` to authorized principals via a topic policy, because teardown alerts carry resource identifiers that should not reach unintended recipients.
- **Use least-privilege, collection-scoped permissions.** The caller SHOULD hold only the delete actions needed on the specific collection/group ARNs rather than `aoss:*` on all resources, because a broad teardown identity can remove unrelated production collections.
- **Guard against accidental production teardown.** Assume any collection is production unless its name/tags clearly indicate otherwise, and require explicit confirmation before deleting, because an accidental delete causes an outage and permanent data loss.
