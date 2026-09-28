# Infrastructure as code and private connectivity

Load this when writing a CloudFormation template for the new custom event bus resources, or when the
service must be reached without traversing the public internet.

## The three resource types

Three CloudFormation resource types cover the new custom event bus. They live under the `AWS::EventsV2::`
namespace, not `AWS::Events::`, which is the classic service.

| Type | Required properties |
|---|---|
| `AWS::EventsV2::EventBus` | `Name` |
| `AWS::EventsV2::Subscriber` | `Name`, `EventBusArn`, `InvokeConfiguration` (itself requiring `TargetArn` and `RoleArn`) |
| `AWS::EventsV2::EventSource` | `Name`, `EventBusArn`, `Configuration` |

The primary identifier of each is its ARN, so that is what `Ref` returns and what an import needs. `State`,
`CreationTime`, and `LastModifiedTime` are read-only on all three.

**These three are the complete set.**

A complete bus plus one SQS-targeted subscriber, with retention, encryption, retry, dead-lettering, and
delivery logging set. The target queue and the KMS key already exist and arrive as parameters; the
dead-letter queue and the delivery role are the template's own:

```yaml
Parameters:
  KmsKeyArn:
    Type: String
  TargetQueueArn:
    Type: String

Resources:
  OrdersBus:
    Type: AWS::EventsV2::EventBus
    DeletionPolicy: Retain        # the bus holds retained events, so a stack delete keeps them
    Properties:
      Name: orders-bus
      StorageConfiguration:
        RetentionPeriodInDays: 7
      EncryptionConfiguration:
        KmsKeyIdentifier: !Ref KmsKeyArn

  DeadLetterQueue:
    Type: AWS::SQS::Queue
    DeletionPolicy: Retain        # failure records outlive the stack

  DeliveryRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Principal: { Service: events.amazonaws.com }
            Action: sts:AssumeRole
            Condition:
              StringEquals:
                aws:SourceAccount: !Ref AWS::AccountId
              ArnLike:
                aws:SourceArn: !Sub arn:${AWS::Partition}:events:${AWS::Region}:${AWS::AccountId}:subscriber/*
      Policies:
        - PolicyName: deliver
          PolicyDocument:
            Version: "2012-10-17"
            Statement:
              - Effect: Allow
                Action: sqs:SendMessage
                Resource:
                  - !Ref TargetQueueArn
                  - !GetAtt DeadLetterQueue.Arn

  OrdersSubscriber:
    Type: AWS::EventsV2::Subscriber
    Properties:
      Name: orders-to-fulfilment
      EventBusArn: !Ref OrdersBus   # Ref returns the bus ARN, and the reference orders creation
      FilterConfiguration:
        Filters:
          - Scope: DATA
            Pattern: '{"detail-type":["OrderPlaced"]}'
      InvokeConfiguration:
        TargetArn: !Ref TargetQueueArn
        RoleArn: !GetAtt DeliveryRole.Arn
      RetryPolicy:
        MaxRetryAttempts: 10
        MaxEventAgeInSeconds: 3600
      OnFailureConfiguration:
        Arn: !GetAtt DeadLetterQueue.Arn
      LogConfiguration:
        Level: ERROR

Outputs:
  BusArn:
    Value: !Ref OrdersBus
  SubscriberArn:
    Value: !Ref OrdersSubscriber
```

**The subscriber MUST be created after the bus, and the `!Ref OrdersBus` in `EventBusArn` is what orders
it.** Bus creation is asynchronous and `CreateSubscriber` is refused until the bus is `ACTIVE`
([provisioning-and-state.md](provisioning-and-state.md)), so a subscriber declared without that reference
(a hard-coded bus ARN, say) also needs an explicit `DependsOn` on the bus.

## A multi-account setup is three stacks, not one

A shared-bus topology cannot be one template, because the subscriber, its delivery role, and its
target must live in the consumer's account: the role must belong to the account creating the
subscriber, and a target in another account is rejected at create. So the deployment splits along account
boundaries:

1. **A platform stack**, in the bus owner's account: the `AWS::EventsV2::EventBus`.
2. **A sharing stack**, also in the bus owner's account: an `AWS::RAM::ResourceShare` naming the bus
   ARN, the consumer principals, and a managed permission from
   [security-and-sharing.md](security-and-sharing.md). Keeping it separate from the platform stack
   lets consumers be added and removed without touching the bus.
3. **A consumer stack, one per consumer account**: the queue, the dead-letter queue, the delivery
   role, and the `AWS::EventsV2::Subscriber` whose `EventBusArn` is the shared bus ARN, imported as a
   parameter.

The ordered CLI form of the same setup is in [setup-walkthroughs.md](setup-walkthroughs.md).

## The property that will bite you is which ones force a replacement

On a subscriber these are create-only, so changing any of them replaces the resource:

```
Name, EventBusArn, InvokeConfiguration.TargetArn, Type, StartingPosition, PointInTimeConfiguration
```

**A subscriber replacement is delete-then-create, not create-then-delete.** The old subscriber is deleted
before the new one exists, so there is a window with no subscriber on the bus. The new subscriber then starts
from its own `StartingPosition`, and `LATEST` means it never sees anything published during that window. So
changing a target ARN, an ordering type, or a starting position in a template silently drops the events that
arrive mid-replacement.

To avoid the gap, you SHOULD add the replacement subscriber under a new logical id first, let it reach
`RUNNING`, then remove the old one in a second deployment. If a gap is unavoidable, give the new
subscriber
`StartingPosition: POINT_IN_TIME` with a `TIMESTAMP` from before the deployment, so it fills in what it
missed.

On a bus and an event source, only `Name` and (for an event source) `EventBusArn` are create-only, so
retention, encryption, description, and tags all update in place.

## Two more things before you write a template

* **A universal target cannot be expressed in CloudFormation.** The template's `InvokeConfiguration` accepts
  `LambdaParameters`, `SqsParameters`, `SnsParameters`, `KinesisParameters`, `StepFunctionsParameters`, and
  `HttpParameters`. There is no block for universal-target input and none for bus-to-bus delivery, and a
  universal target requires its input to be supplied (chapter 10). So those two subscriber kinds have to be
  created through the API.
* **You SHOULD give the KMS key as a key ARN.** The service stores and returns the key ARN. A key ID is
  accepted and is matched to the returned ARN when CloudFormation checks for drift. An alias is also
  accepted, but an alias cannot be matched to the key ARN behind it, so drift detection can report a
  difference that is not a real change.

## Deployment role and stabilization

The deploying role needs the same `events:` actions the API needs, plus `iam:PassRole` for a subscriber and,
for an encrypted bus, `kms:DescribeKey` and `kms:Decrypt` on the key. That covers the deployer. The key
policy separately has to grant the service itself, and a stack whose key policy omits it does not fail the
create call: the bus reaches `CREATE_FAILED` afterwards and the stack rolls back.
[security-and-sharing.md](security-and-sharing.md) gives the exact statement.

**A rollback plus `DeletionPolicy: Retain` blocks the retry.** The rollback deletes the stack's other
resources but retains the bus, so the fixed template then collides on the bus name and fails with
`ResourceAlreadyExistsException` ([provisioning-and-state.md](provisioning-and-state.md)). Delete the
retained bus before redeploying, and read the name in the error rather than assuming the second failure
has the same cause as the first. Bus create and update allow long stabilization windows, because the bus
lifecycle is asynchronous
(chapter 15).

A revoked event source reports that only in its `Revoked` flag, and `EventSourceState` defines no value for
revocation. So a stack cannot detect a revoked source by waiting for a state; read the `Revoked` flag
instead.

## Private connectivity

The service is available as an interface VPC endpoint, with private DNS for its endpoint hostname and
availability in every AZ of the region. Create an interface endpoint if you need to reach the service without
traversing the public internet.
