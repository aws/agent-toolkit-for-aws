# Setup walkthroughs: from nothing to a delivered event

Load this when setting up a working bus from scratch, in one account or across accounts. Each
walkthrough is ordered: every step depends on the ones before it, and teardown runs in the reverse
order of creation. Individual calls are explained in [code-samples.md](code-samples.md); this file is
the sequence around them.

## Single account: bus, subscriber, delivered event, teardown

### Prerequisites

* The service must be available in your region; `aws eventsv2 list-event-buses` failing to resolve an
  endpoint means it is not.
* Your caller MUST have the `events:` actions used below (chapter 14; the namespace is `events:`, never
  `eventsv2:`), plus `sqs:CreateQueue`, `iam:CreateRole`, `iam:PutRolePolicy`, and `iam:PassRole` for
  the delivery role.

### 1. Create the target queue and the dead-letter queue

The targets exist before anything references them:

```bash
QUEUE_URL=$(aws sqs create-queue --queue-name my-target --query QueueUrl --output text)
DLQ_URL=$(aws sqs create-queue --queue-name my-dlq --query QueueUrl --output text)
QUEUE_ARN=$(aws sqs get-queue-attributes --queue-url "$QUEUE_URL" --attribute-names QueueArn --query Attributes.QueueArn --output text)
DLQ_ARN=$(aws sqs get-queue-attributes --queue-url "$DLQ_URL" --attribute-names QueueArn --query Attributes.QueueArn --output text)
```

### 2. Create the delivery role

The role trusts the `events.amazonaws.com` service principal and **MUST be able to write both**
queues. Granting
the target but not the dead-letter queue turns every delivery failure into silent loss (chapter 13):

```bash
ROLE_ARN=$(aws iam create-role --role-name my-delivery-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "events.amazonaws.com"},
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {"aws:SourceAccount": "111122223333"},
        "ArnLike": {"aws:SourceArn": "arn:aws:events:us-east-1:111122223333:subscriber/*"}
      }
    }]
  }' --query Role.Arn --output text)

aws iam put-role-policy --role-name my-delivery-role --policy-name deliver \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": "sqs:SendMessage",
      "Resource": ["'"$QUEUE_ARN"'", "'"$DLQ_ARN"'"]
    }]
  }'
```

### 3. Create the bus and wait for ACTIVE

```bash
BUS_ARN=$(aws eventsv2 create-event-bus --name my-bus --query EventBusArn --output text)
aws eventsv2 wait event-bus-active --event-bus-arn "$BUS_ARN"
```

### 4. Create the subscriber

Filter, target, delivery role, and dead-letter queue in one call; the exact shape is the first sample
in [code-samples.md](code-samples.md):

```bash
SUBSCRIBER_ARN=$(aws eventsv2 create-subscriber --name orders-to-queue \
  --event-bus-arn "$BUS_ARN" \
  --filter-configuration '{"Filters":[{"Scope":"DATA","Pattern":"{\"detail\":{\"orderId\":[{\"exists\":true}]}}"}]}' \
  --invoke-configuration '{"TargetArn":"'"$QUEUE_ARN"'","RoleArn":"'"$ROLE_ARN"'"}' \
  --on-failure-configuration '{"Arn":"'"$DLQ_ARN"'"}' \
  --query SubscriberArn --output text)
```

### 5. Allow the activation delay, then publish a test event

A subscriber published to immediately after creation can miss the first event, so you SHOULD allow a
short delay
(see [provisioning-and-state.md](provisioning-and-state.md)). Then publish something the filter
matches:

```bash
aws eventsv2 put-events --event-bus-arn "$BUS_ARN" --entries '[{
  "Source": "com.example.orders",
  "DetailType": "OrderPlaced",
  "Detail": "{\"orderId\":\"walkthrough-1\"}"
}]'
```

### 6. Confirm arrival at the target

You SHOULD read the queue and delete what you read, or counts lie to you
([delivery-troubleshooting.md](delivery-troubleshooting.md)):

```bash
aws sqs receive-message --queue-url "$QUEUE_URL" --wait-time-seconds 20
```

If nothing arrives promptly, something is wrong; you SHOULD work the ordered procedure in
[delivery-troubleshooting.md](delivery-troubleshooting.md) rather than waiting longer.

### 7. Teardown, in reverse order of creation

The bus rejects deletion while any subscriber or event source still exists (chapter 15), so you MUST
delete the subscriber before the bus. The delivery role's policy names the queue ARNs, so the role goes
before the queues to keep the teardown a strict reverse of the creation order.

```bash
aws eventsv2 delete-subscriber --subscriber-arn "$SUBSCRIBER_ARN"
aws eventsv2 delete-event-bus --event-bus-arn "$BUS_ARN"
aws eventsv2 wait event-bus-deleted --event-bus-arn "$BUS_ARN"
aws iam delete-role-policy --role-name my-delivery-role --policy-name deliver
aws iam delete-role --role-name my-delivery-role
aws sqs delete-queue --queue-url "$QUEUE_URL"
aws sqs delete-queue --queue-url "$DLQ_URL"
```

## Multiple accounts: a central bus shared through AWS RAM

The platform account owns the bus. Each consumer account owns its own subscriber, delivery role, and
target. **Subscribers cannot be created centrally**: the delivery role must belong to the account that
creates the subscriber, and a target in another account is rejected at create, because the target ARN's
account is checked there. So the platform team shares the bus, and every consumer builds its own consumer
side.

### Prerequisites

* Decide the sharing mechanism. AWS RAM is the recommended path
  ([security-and-sharing.md](security-and-sharing.md)); a hand-written resource policy is the fallback
  for what RAM cannot express.
* If the accounts share an AWS Organization with resource sharing enabled, a share to an in-Org
  principal associates automatically and no invitation appears. Across organizations, the consumer
  MUST accept an invitation (step 3).
* If the bus will be encrypted with a customer managed key, you MUST put the key policy in place
  first; the key
  is checked at bus create time and a bad policy settles the bus at `CREATE_FAILED`
  ([security-and-sharing.md](security-and-sharing.md)).

### 1. Platform account: create the central bus

```bash
BUS_ARN=$(aws eventsv2 create-event-bus --name company-events --query EventBusArn --output text)
aws eventsv2 wait event-bus-active --event-bus-arn "$BUS_ARN"
```

### 2. Platform account: share the bus, narrowest permission per principal

One share per grant scope. A consumer that only attaches subscribers gets `SubscribeOnly`; a producer
account gets `PublishOnly`; the four managed permissions and what each grants are in
[security-and-sharing.md](security-and-sharing.md). Principals can be account ids, OU ARNs, or an
organization ARN:

```bash
aws ram create-resource-share \
  --name company-events-consumers \
  --resource-arns "$BUS_ARN" \
  --principals 444455556666 \
  --permission-arns arn:aws:ram::aws:permission/AWSRAMEventBridgeEventBusV2SubscribeOnly
```

Omitting `--permission-arns` applies the default managed permission for the resource type, which is
`SubscribeOnly`; you SHOULD name the permission anyway, so the grant is explicit.

### 3. Consumer account: accept the share (cross-Org only)

```bash
INVITATION_ARN=$(aws ram get-resource-share-invitations \
  --query 'resourceShareInvitations[?status==`PENDING`]|[0].resourceShareInvitationArn' --output text)
aws ram accept-resource-share-invitation --resource-share-invitation-arn "$INVITATION_ARN"
```

In-Org shares show no invitation; the association happens on its own.

### 4. Consumer account: build the consumer side

Steps 1, 2, 4, 5, and 6 of the single-account walkthrough, run in the consumer account, with one
change: `--event-bus-arn` is the shared bus's ARN from step 1. The queue, the dead-letter queue, the
delivery role, and the subscriber all live in the consumer account.

The grant takes time to propagate after the share is accepted, so a `CreateSubscriber` denied
immediately afterwards can be propagation rather than a missing grant; you SHOULD retry before
concluding the
share is wrong.

### 5. Verify end to end

Publish from the platform account (or from a `PublishOnly`-shared producer account) and confirm
arrival at the consumer's queue, exactly as in the single-account walkthrough.

### 6. Revoking access

Deleting the share retracts the grant RAM wrote:

```bash
aws ram delete-resource-share --resource-share-arn <share ARN>
```

Subscribers the consumer already created stop being reachable through the grant but still exist and
are owned by the consumer. To cut off one specific subscriber without touching the share, the bus
owner uses `RevokeResource`, which is terminal ([authorization.md](authorization.md)).

### 7. Teardown, consumer side first

1. Each consumer deletes its subscriber, then its role, then its queues (single-account step 7, minus
   the bus).
2. The platform account deletes the resource share.
3. The platform account deletes the bus and waits on `event-bus-deleted`.

The CloudFormation form of this split is in [infrastructure-as-code.md](infrastructure-as-code.md):
one platform stack for the bus, one sharing stack for the RAM share, and one consumer stack per
account.
