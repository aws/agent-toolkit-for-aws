# Authorization

What a caller needs to reach the API, and what a bus owner can control about callers reaching their bus.

This is the caller's side. For the role EventBridge assumes to invoke your target, see chapter 13 of the
skill body.

**Before anything else: every action name is `events:`.** Three different names identify this service, and
only one of them belongs in a policy:

| Where it appears | Name | Example |
|---|---|---|
| IAM actions and ARNs | `events` | `events:PutEvents`, `arn:aws:events:{region}:{account}:event-busv2/{name}/{id}` |
| CLI command | `eventsv2` | `aws eventsv2 create-event-bus` |
| Every SDK client | `eventbridgev2` | `boto3.client("eventbridgev2")` |
| Endpoint host | `eventsv2` | `eventsv2.{region}.amazonaws.com` |

A policy granting `eventbridgev2:PutEvents`, or `eventsv2:PutEvents`, names an action that does not exist,
and it fails closed: the policy is accepted and grants nothing. The IAM namespace is shared with classic
EventBridge, and the resource type distinguishes the new buses.

---

## Publishing

Publishing is authorized against the bus ARN you named in the request, using `events:PutEvents` or
`events:PutRawEvents` to match the API you called.

**Authorization runs per entry**, so entry-scoped conditions are evaluated independently for each event
in a batch. The condition keys available depend on which API you used:

| Condition key | Available on |
|---|---|
| `events:source`, `events:detail-type` | `PutEvents` only |
| `events:SystemMetadata/ContentType` | `PutRawEvents` only |
| `events:Metadata/<key>` | `PutRawEvents`, one key per metadata entry |
| `events:eventBusInvocation` | both: `false` on a direct publish, `true` on a forwarded delivery. An event source populates no key |

There is no partial authorization. **If one entry fails its condition check, the whole request is
denied**, including the entries that would have passed. So a batch is only as authorized as its least
authorized entry, and a bus owner's condition applied to a mixed batch rejects all of it. You
**SHOULD** keep batches small enough that losing one to a condition failure is cheap.

One related input rule: two metadata keys differing only in case are rejected, because condition keys
fold case-insensitively and the two would collapse into one. You get `InvalidInputException` naming both
spellings.

---

## Forwarding into a bus

Forwarding means events arriving on a bus from somewhere other than a direct publish. There are two
authorization models, and the difference is **when** the check happens.

| How the events arrive | When authorization happens | What is checked |
|---|---|---|
| An event source you create | once, at create time | the `CreateEventSource` call, with an `events:source` condition key naming what may be forwarded |
| A non-managed classic rule targeting a new custom event bus | at ingestion, per event | the destination bus's resource policy, plus the identity policy of the role it carries |
| A subscriber targeting another new custom event bus | at ingestion, per event | the same |

**For an event source, consent is given once when it is created, and nothing is re-checked at
ingestion.** So a bus policy cannot filter that traffic afterwards. The control point is
`CreateEventSource`, whose `events:source` condition key names the AWS service or partner source being
forwarded, which lets a bus owner constrain what may be forwarded and not merely who may forward. Decide
that governance before the event source exists, because there is no second gate later. If a source turns
out to be misbehaving after the fact, the bus owner's remedy is `RevokeResource`, which stops it without
needing the other account's cooperation and cannot be undone. See below.

**For the other two, authorization happens at ingestion under the role you supplied, and every event is
authorized individually** against the destination bus's resource policy, exactly as a direct publish
would be. The IAM action is chosen per event:

* `events:PutEvents` when the event's **system metadata** carries both a forwarded source and a forwarded
  detail-type, **and** the forwarded source value sits in the reserved `aws.` namespace. That is a genuine
  AWS service or partner event. `events:source` and `events:detail-type` are populated from those two
  system metadata values.
* `events:PutRawEvents` for everything else, meaning any event you originated.

Both the presence check and the `aws.` check read the forwarded source and detail-type from system
metadata. **Nothing in the event body affects which action is required.** So a `source` field inside your
payload has no bearing on it, including the `source` field that sits inside `Data` on an event originally
published with `PutEvents`. Only the system metadata values decide the branch.

The prefix match is exact and case-sensitive. `AWS.foo` and a source with a leading space are customer
data, not reserved, so they take the `PutRawEvents` branch.

**The consequence for a non-managed forwarder: a mixed stream needs both actions.** If your forwarder
carries AWS service events and your own events through the same path, and you grant only
`events:PutEvents`, your own events are denied. Grant only `events:PutRawEvents` and the AWS service
events are denied. You **MUST** grant both, on the forwarding role's identity policy and on the
destination bus's resource policy when the bus is in another account:

```json
{
  "Effect": "Allow",
  "Action": ["events:PutEvents", "events:PutRawEvents"],
  "Resource": "arn:aws:events:us-east-1:111122223333:event-busv2/my-bus/exampleid0123456789abcdef"
}
```

You cannot choose the branch yourself. The forwarded source and detail-type are written by the service
and are never accepted on public input, and the source value is checked rather than merely its presence,
so an event you originated cannot be promoted into the `PutEvents` branch.

Two extra condition keys exist for forwarded events, and they are how a bus owner writes rules about
forwarded traffic specifically:

| Condition key | Populated from |
|---|---|
| `events:SystemMetadata/AwsSource` | the forwarded event's original source |
| `events:SystemMetadata/AwsDetailType` | the forwarded event's original detail-type |

**Neither key exists on a direct publish.** Both values are service-written on the forwarding ingestion
path, and neither public API accepts a member that could carry one: `PutEvents` takes `Source` and
`DetailType` at the top level, and `PutRawEvents` system metadata carries only `ContentType`,
`EventGroupId`, and `DeduplicationId`. So a condition written on these two keys constrains forwarded
traffic and permits everything published directly, with no signal that it did not apply.

They bind on the non-managed forwarding paths, because those are the paths whose events are evaluated
against the destination bus's resource policy per event. An event source is not one of them: its consent
is given once at create time, so a per-event condition never runs against it.

On those paths the IAM action is chosen per entry: `events:PutEvents` when the forwarded source is
`aws.*`, and `events:PutRawEvents` for anything else. `events:source` and `events:detail-type` are
populated only under the first choice. The `SystemMetadata` pair is populated under both. So a bus owner
writing one condition that must cover all forwarded traffic **SHOULD** use the `SystemMetadata` keys.

---

## Creating things on a bus

Creating a subscriber or an event source is authorized against **the bus**, not only against the thing
being created. This is the cross-account grant point: it is where a bus owner decides whether another
account may attach anything to their bus.

`CreateSubscriber` runs up to four separate checks, and **every one must allow**. They are combined with
AND, so any single denial denies the create.

| Check | Action | Resource | Present |
|---|---|---|---|
| bus | `events:CreateSubscriber` | the bus ARN | always. The only check carrying the bus's resource policy |
| subscriber | `events:CreateSubscriber` | the pending subscriber ARN | always |
| pass role | `iam:PassRole` | the invoke role ARN | when `InvokeConfiguration.RoleArn` is set |
| tagging | `events:TagResource` | the pending subscriber ARN | when the request carries tags |

Two practical points. The `iam:PassRole` check names the bus as the associated resource, not the
subscriber, because the subscriber ARN does not exist yet. And the pending subscriber ARN ends in a
wildcard for the same reason, so an identity policy scoped to a subscriber matches by name prefix rather
than exactly.

`CreateEventSource` is similar, with two differences. It carries an `events:source` condition key so the
bus owner can constrain what is forwarded rather than only who forwards it. And there is no
`iam:PassRole` check, because an event source has no role.

Every other operation that takes a bus or subscriber ARN is same-account only, with one exception: the
caller must own the resource named in the request, except for `DescribeEventBus`, which a bus owner can
grant across accounts and which both the `PublishOnly` and `SubscribeOnly` managed permissions include.
One addition rather than an exception: `UpdateSubscriber` authorizes in
the subscriber's own account, and a request that carries a `FilterConfiguration` is **additionally**
authorized against the parent bus and its resource policy, so a filter the bus owner conditioned on
cannot be widened after create. That second check is why `events:UpdateSubscriber` belongs in a
cross-account bus grant.

### Revocation

**`RevokeResource` authorizes against the bus too, and only the bus owner can call it.** The subscriber or
event source named in the request is the thing being acted upon; the party allowed to act is whoever owns
the bus it is attached to. A cross-account caller is denied. If the named resource does not exist, the
request is denied rather than returning a not-found, so do not read a denial as proof of a permissions
problem.

**Revocation is terminal.** No operation clears it, and the flag never returns to false. A revoked
subscriber or event source refuses mutating operations with `InvalidStateException`, and a revoked
subscriber stops delivering regardless of its `State`. `DeleteSubscriber` and `DeleteEventSource` stay
available so the owner of the revoked resource can still clean it up. `DescribeSubscriber`,
`DescribeEventSource`, and both list operations return a `Revoked` field that is present only when true,
so an absent field means not revoked, and a bus owner can see at a glance which resources they revoked.

**Revoking an event source stops it ingesting events.** Each event it would have forwarded is refused as
it arrives, so the event source keeps existing while its traffic stops. That refusal is checked ahead of
the state check, so it applies whatever state the event source is in, and no state change can restore
forwarding.

So revocation is the only unilateral control a bus owner has over a resource attached to their bus, and
it cannot be walked back.

**Revocation covers one resource, not the caller who created it.** A revoked subscriber or event source
stays revoked, and nothing stops the same account creating another one and carrying on. So a bus owner
revoking to stop a misbehaving account **MUST** also deny that account `events:CreateSubscriber` and
`events:CreateEventSource` in the bus resource policy, because the bus policy is what the create checks
above evaluate. Revoking without that denial stops the resources you named and leaves the account able
to replace them.

Denying the bare action stops that account attaching any event source at all. To stop one kind while
allowing others, condition the `events:CreateEventSource` denial on the `events:source` key: its value is
the AWS service for a first-party source and the partner event source name for a third-party one. A
create whose source cannot be derived from the request carries no such key, and validation rejects that
request before anything is created, so omitting the source is not a way around a conditioned denial.

Deleting is not an alternative for a bus owner. `DeleteSubscriber` and `DeleteEventSource` authorize
against the resource named in the request, so only the account that owns that subscriber or event source
can delete it. When the resource belongs to another account, the bus owner's options are to revoke it or
to ask its owner to remove it. Nothing in between.

That makes confirming the target the whole safeguard. You **MUST** read the resource with
`DescribeSubscriber` or `DescribeEventSource` and check its ARN, its bus, and its target before
revoking, because there is no undo and no substitute control.

---

## Governing what a subscriber may do

A bus owner can constrain the filters a subscriber declares, using condition keys that `CreateSubscriber`
supplies:

| Condition key | Value |
|---|---|
| `events:Metadata/<key>` | the exact-match value from each `METADATA`-scope filter field |
| `events:Metadata/<key>/Matcher` | `exact` |
| `events:ContentFilterPresent` | `true` when the subscriber declares a `DATA`-scope filter |

`METADATA` filters are exact-match only, which is why the value is a plain literal. A `DATA` filter
matches arbitrary JSON with no decomposable structure, so only its presence is exposed, not its content.

These keys are supplied on `CreateSubscriber`.

---

## Cross-account: a bus holds two policies

An event bus is the only resource type that takes a resource policy. Other resource ARNs are rejected.

Each bus holds two named policies:

| Policy name | Written by | Contents |
|---|---|---|
| `default` | you | full IAM policy language, including `Deny` |
| `AWS_RAM` | AWS RAM only | reflects your resource shares |

**Both are evaluated on a cross-account authorization, and an explicit `Deny` in either overrides an
`Allow` in the other.** So a share created through RAM can be blocked by a `Deny` you wrote in `default`,
and a grant you wrote in `default` can be blocked by RAM. When a cross-account caller is denied and the
policy you wrote appears to allow them, you **SHOULD** check the other policy.

Operations that omit `PolicyName` act on `default`. An `events:PolicyName` condition key lets you restrict
which policy a principal may modify.

A worked `default` policy for the common shape, one external account that publishes and runs its own
subscribers, attached with `PutResourcePolicy`:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "TenantPublishAndSubscribe",
    "Effect": "Allow",
    "Principal": { "AWS": "arn:aws:iam::444455556666:root" },
    "Action": [
      "events:PutEvents", "events:PutRawEvents",
      "events:CreateSubscriber", "events:UpdateSubscriber",
      "events:DescribeEventBus"
    ],
    "Resource": "arn:aws:events:us-east-1:111122223333:event-busv2/company-events/exampleid0123456789abcdef"
  }]
}
```

The action list mirrors what the `PublishOnly` and `SubscribeOnly` managed permissions grant. What it
deliberately omits is the enforcement: no `UpdateEventBus`, `DeleteEventBus`, `PutResourcePolicy`, or
`DeleteResourcePolicy`, so the tenant cannot reconfigure the bus or rewrite this policy.

**Isolation between tenant accounts needs no policy condition, because it follows from ownership.** A
subscriber is created in, and owned by, the account that calls `CreateSubscriber`, and its delivery role
MUST belong to that account, so one tenant cannot read, point, or delete another tenant's subscriber
through this policy. There is no condition key that scopes subscriber actions to their creator.
`UpdateSubscriber` and `DeleteSubscriber` on the subscriber itself authorize in the
subscriber's own account; `UpdateSubscriber` appears in the bus grant because an update that carries a
`FilterConfiguration` is additionally authorized against the bus, so the bus owner's filter conditions
cannot be widened after create. Cutting one resource off later is `RevokeResource`, which is the bus
owner's, rather than a policy edit.

`GetResourcePolicy` on a bus with no policy returns `ResourceNotFoundException` rather than an empty
document, so treat that as "no policy" rather than an error.

---

## `aws:ResourceTag` on create resolves separately per check

`aws:ResourceTag/<key>` resolves separately for each of the checks above, against that check's own
resource. On `CreateSubscriber` that means the bus's tags for the bus check, and the subscriber's tags for
the subscriber check. A statement whose `Resource` matches both, such as `"*"`, is therefore evaluated
against both sets of tags.

So this policy, intended to allow a create only when the subscriber is tagged `team=payments`:

```json
{ "Effect": "Allow", "Action": "events:CreateSubscriber", "Resource": "*",
  "Condition": { "StringEquals": { "aws:ResourceTag/team": "payments" } } }
```

denies a request that tags the subscriber `team=payments` on a bus tagged `team=ads`. The subscriber check
matches and allows. The bus check does not match and denies. The two are ANDed, so the create is denied.

This only ever over-restricts. A conditioned allow starts requiring both tag sets to match, and a
conditioned deny fires if either matches, but a denial never becomes an allow. To gate on one resource,
you **SHOULD** scope `Resource` to that resource's ARN instead of `"*"`.

Two related details. An untagged create carries no `aws:ResourceTag` on the subscriber check at all, so a
`StringEquals` allow will not match while a `StringNotEquals` deny will. And the pending subscriber ARN is
wildcard-suffixed, so scoping `Resource` to a subscriber matches by name prefix.
