# Security, encryption, sharing, and tagging

Load this when encrypting a bus, sharing a bus with another account, writing or reading a bus resource
policy, or tagging resources.

## Encryption

A bus takes `EncryptionConfiguration.KmsKeyIdentifier`: a key ID, a key ARN, an alias name, or an alias
ARN. When it is absent, events are encrypted with an AWS owned key and nothing below applies.

**A customer managed key is recommended for a bus carrying regulated or tenant data.** Events at rest are
encrypted either way, so the difference is control rather than whether encryption happens: a customer
managed key is the only form whose policy you write, whose use is auditable in your own CloudTrail, and
which you can disable to cut access to the bus's events.

**Your caller MUST hold `kms:DescribeKey` on the key.** At create and update the service resolves the key
with `DescribeKey` under your own credentials, so you find out immediately if you cannot use it. An alias
resolves to its backing key, and the resolved key ARN is stored and compared, never the alias ARN. A key
that is disabled, deleted, pending deletion, of an incompatible spec, or denied to you returns
`AccessDeniedException`. A malformed key id returns `InvalidInputException` instead, because that is an
input problem rather than a key condition.

**Every caller-driven operation on a CMK bus also runs a `kms:Decrypt` check against the bus key, under
your credentials, before the service does its own encryption.** That covers publishing as well as the
control-plane reads and writes, and a denied caller fails the whole call with `AccessDeniedException`. So
**a publisher to a CMK bus MUST hold `kms:Decrypt` on that key**, and the reason is deliberate: a caller
who cannot read the bus's events back is not allowed to write them either.

A bus encrypted with an AWS owned key runs none of these checks.

Separately from your own access, the service needs its own. If the key policy does not permit the service,
the bus settles at `CREATE_FAILED` with `StateReason: KMS_ACCESS_DENIED`. So the two kinds of key problem
arrive at different times: your own access fails the call synchronously, and the service's access fails the
bus asynchronously. Reads on an `ACTIVE` encrypted bus return the `EncryptionConfiguration`.

**The key policy MUST grant `events.amazonaws.com` these five actions**, and a bus create fails without
them:

```json
{ "Sid": "EventBridgeEventBus",
  "Effect": "Allow",
  "Principal": { "Service": "events.amazonaws.com" },
  "Action": [
    "kms:Decrypt",
    "kms:Encrypt",
    "kms:GenerateDataKeyWithoutPlaintext",
    "kms:ReEncrypt*",
    "kms:DescribeKey"
  ],
  "Resource": "*" }
```

A bus in `CREATE_FAILED` cannot be updated, only deleted, so a key policy problem at create time means
fixing the policy and creating the bus again (chapter 15).

## Sharing a bus with another account: use AWS RAM

AWS Resource Access Manager is the recommended path for granting another account access to a bus.
You SHOULD
share the bus as a RAM resource and let RAM manage the grant, because RAM gives you one place to see and
revoke what you have shared, and it works with AWS Organizations.

Which mechanism, by situation:

| Situation | Use |
|---|---|
| consumer accounts inside your AWS Organization | a RAM share; an in-Org principal associates automatically, with no invitation |
| a consumer account outside your Organization | a RAM share still works, through an invitation the consumer MUST accept within 12 hours, one account at a time; a resource policy is the alternative when that handshake does not fit |
| a grant narrower than a managed permission expresses, or an explicit `Deny` | a resource policy, alone or alongside a share |

Whichever grants the bus-side access, **cross-account access also needs the caller's own identity policy
to allow the same actions**. The bus-side grant and the consumer's identity policy are evaluated
together, and access exists only where they intersect, so a consumer whose administrator has not granted
`events:PutRawEvents` cannot publish to a bus that allows it.

Four AWS managed permissions exist for the bus resource type, each at
`arn:{partition}:ram::aws:permission/{name}`:

| Managed permission | Grants a consumer account |
|---|---|
| `AWSRAMEventBridgeEventBusV2PublishOnly` | publishing; `events:PutRawEvents` is its signature action |
| `AWSRAMEventBridgeEventBusV2SubscribeOnly` | attaching subscribers; `events:CreateSubscriber` is its signature action |
| `AWSRAMEventBridgeEventBusV2FullAccess` | the full consumer surface, including `events:CreateSubscriber`, `events:CreateEventSource`, and `events:UpdateEventSource` |
| `AWSRAMEventBridgeEventBusV2EventSourceAccess` | attaching managed forwarding and nothing else: `events:CreateEventSource`, `events:UpdateEventSource`, `events:DescribeEventBus` |

No managed permission grants an owner-only action such as `events:DeleteEventBus`. The granted action
lists can change, so you SHOULD read a permission back with RAM's `GetPermission` rather than assume its
exact contents. A bus owner can also author a customer-managed RAM permission for a narrower grant; RAM
rejects one that names an owner-only action.

## Resource policies are the fallback

Use them when RAM cannot express what you need. `PutResourcePolicy`, `GetResourcePolicy`,
`DeleteResourcePolicy`, and `ListResourcePolicies` manage a bus policy directly.

Two details:

* `GetResourcePolicy` on a bus with no policy returns `ResourceNotFoundException` rather than an empty
  document, so you SHOULD treat that as "no policy" and not as an error.
* A bus policy you write by hand is invisible to RAM, so you then own tracking it.

Cross-account access rests on two policies per bus: `default`, which you write, and `AWS_RAM`, which AWS RAM
writes. Both are evaluated, and an explicit `Deny` in either overrides an `Allow` in the other. For the
condition keys and the per-operation checks, see [authorization.md](authorization.md).

## Tagging

`TagResource`, `UntagResource`, `ListTagsForResource`, and tags on create. The cap is per resource, not per
call, so a create with tags plus a later `TagResource` share one budget. Character rules are enforced but not
fully documented; non-BMP characters such as emoji are rejected while accented and CJK characters are
accepted.

Tagging on create interacts with authorization in a way that looks like a broken policy. See
[authorization.md](authorization.md) for the `events:TagResource` and `aws:ResourceTag` behaviour.

## Bus-owner-only operations

Some operations are restricted to the account that owns the bus, including revoking a shared
resource. You
MUST NOT assume a permission grant alone is sufficient, because owner-only operations refuse a non-owner
even when the grant is present. Revocation semantics are in
[authorization.md](authorization.md).
