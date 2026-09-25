# Filters, transformers, and expressions

Load this when writing a filter pattern, a JSONata expression, or a target parameter that reads from the
event. It carries the full addressing model that chapter 6 of the skill body summarizes, then the filter
and transformer rules that depend on it.

## The delivered event, in full

Every event, whichever API published it, is delivered under three top-level names:

```
Data            the payload
Metadata        your own key-value pairs (PutRawEvents only; empty object otherwise)
SystemMetadata  service-assigned and ordering fields
```

The difference is what `Data` contains.

An event published with **`PutRawEvents`** has `Data` equal to the payload you sent, and nothing else:

```json
{
 "Data": { "m": "RAW", "n": 7 },
 "Metadata": { "mykey": "myval" },
 "SystemMetadata": {
  "ContentType": "application/json",
  "DeduplicationId": "a1b2c3d4-5678-90ab-cdef-EXAMPLE11111",
  "EventGroupId": "orders-1001",
  "aws:DeliveryType": "LIVE",
  "aws:EventId": "a1b2c3d4-5678-90ab-cdef-EXAMPLE22222",
  "aws:IngestionTime": "2026-08-31T07:23:38.826Z",
  "aws:SequenceNumber": "10000000000000012000"
 }
}
```

An event published with **`PutEvents`** has `Data` equal to the whole classic-style envelope, with your
payload nested one level down under `detail`:

```json
{
 "Data": {
  "version": "0",
  "id": "a1b2c3d4-5678-90ab-cdef-EXAMPLE33333",
  "source": "com.example.orders",
  "detail-type": "MyType",
  "account": "111122223333",
  "region": "us-east-1",
  "time": "2026-08-31T07:23:37Z",
  "resources": [ "arn:aws:s3:::example" ],
  "detail": { "m": "PE", "n": 7 }
 },
 "Metadata": {},
 "SystemMetadata": {
  "ContentType": "application/eventbridge+json",
  "DeduplicationId": "a1b2c3d4-5678-90ab-cdef-EXAMPLE44444",
  "EventGroupId": "a1b2c3d4-5678-90ab-cdef-EXAMPLE55555",
  "aws:DeliveryType": "LIVE",
  "aws:DetailType": "MyType",
  "aws:EventId": "a1b2c3d4-5678-90ab-cdef-EXAMPLE66666",
  "aws:IngestionTime": "2026-08-31T07:23:37.890Z",
  "aws:SequenceNumber": "10000000000000011000",
  "aws:Source": "com.example.orders"
 }
}
```

So, concretely:

* Your field `m` is at **`$events.Data.m`** for a raw-published event and at **`$events.Data.detail.m`**
  for a `PutEvents` event.
* `$events.Data.m` against `PutEvents` traffic resolves to nothing. It does not error. A filter matches
  nothing, a transformer emits nothing, and a target parameter arrives empty.
* **`aws:Source` and `aws:DetailType` exist only for `PutEvents` events.** A `SYSTEM_METADATA` filter on
  `aws:Source` will never match raw-published traffic, because the field is absent.
* `ContentType` differs by API, and the `PutEvents` value is `application/eventbridge+json`, not
  `application/json`. A filter looking for `application/json` will not match `PutEvents` traffic.
* `EventGroupId` is returned on the delivered event. When you supply none, the service generates one, so
  the field is always present even if you never set it.
* `aws:DeliveryType` is `LIVE` for normal delivery and `REPLAY` for an event delivered by a replaying
  subscriber. This is how a consumer tells the two apart (see chapter 17).

If you publish through both APIs onto one bus, you MUST write filters and expressions that work for both,
or give each traffic type its own subscribers, because there is no addressing form that spans both.

## Filter rules

A subscriber's `FilterConfiguration` holds a list of `Filters`, and an event must match every filter in
the list to be delivered. The filters are ANDed, not ORed.

Each filter has a `Pattern` and a `Scope`:

| Scope | Matches against |
|---|---|
| `DATA` | exactly what `$events.Data` holds, so the shape depends on the publish API |
| `METADATA` | your own `Metadata` keys |
| `SYSTEM_METADATA` | the service-assigned and ordering fields |

A `DATA` pattern is written against the shape above, so one pattern cannot serve both publish APIs. For
the event `{"orderId":"123","region":"eu"}`:

| `DATA` pattern | Matches |
|---|---|
| `{"detail":{"orderId":["123"]}}` | `PutEvents` events only |
| `{"orderId":["123"]}` | `PutRawEvents` events only |

Neither pattern is wrong. Each is correct for exactly one publish API, and silently matches
nothing for the other.

`Language` defaults to `EVENT_BRIDGE_PATTERN`, the classic pattern syntax, and the model defines no other
value. Omitting the field selects that default. Setting it with the older spelling `EventBridgePattern` is
rejected, because the enum value is upper snake case.

### Pattern operators

`EVENT_BRIDGE_PATTERN` is the classic pattern language, so a `DATA` or `SYSTEM_METADATA` pattern accepts
the classic operator set apart from `wildcard`:

| Operator | Example |
|---|---|
| exact value list (OR within the list) | `{"state": ["running", "stopped"]}` |
| `prefix`, `suffix` | `{"region": [{"prefix": "eu-"}]}` |
| `equals-ignore-case` | `{"state": [{"equals-ignore-case": "Running"}]}`; also nests under `prefix` and `suffix` |
| `anything-but` | a literal, a list, or nested `prefix`/`suffix`/`equals-ignore-case` |
| `numeric` | `{"n": [{"numeric": [">", 0, "<=", 5]}]}` with `=`, `<`, `<=`, `>`, `>=` |
| `cidr` | `{"sourceIp": [{"cidr": "10.0.0.0/24"}]}` |
| `exists` | `{"orderId": [{"exists": true}]}`; `false` matches absence |
| `$or` | ORs groups of field conditions that are otherwise ANDed |

Three scope restrictions:

* **A subscriber filter rejects every wildcard matcher.** A pattern carrying `wildcard`, or `wildcard`
  nested under `anything-but`, is rejected at create with `InvalidInputException` and the message
  `Filter pattern must not contain wildcard matchers (wildcard, anything-but wildcard)`. The classic
  pattern language accepts both, so a pattern ported from a classic rule can fail here for that reason
  alone. Rewrite it with `prefix`, `suffix`, or an exact value list.
* **A `METADATA` pattern accepts no operators.** Each field must be a non-empty array of literal scalar
  values, and `$or` is disallowed; anything else is rejected at create with `InvalidInputException`. The
  reason is governance: metadata fields are injected as `events:Metadata/<key>` condition keys at publish
  time (see [authorization.md](authorization.md)), and only exact literals inject cleanly.
* **`numeric` compares JSON numbers.** `SYSTEM_METADATA` values are delivered as strings, as the
  envelopes above show, so a numeric operator on that scope matches nothing. On `DATA` it works wherever
  the addressed value is a number.

Heavily OR-ed patterns are bounded by a combination limit, and a pattern over that limit is rejected at
create.

Changing a subscriber's filter is itself limited, per subscriber, over a rolling 24-hour window. A
rejected update reads `The subscriber has reached its limit of filter changes for a 24-hour period. Wait
for an earlier change to pass 24 hours old and retry.` The limit is not raisable, so a workflow that
rewrites filters continuously has to batch its changes instead.

Practical rules:

* One filter per scope. A second filter on a scope already used is rejected with
  `Duplicate filter scope: DATA`.
* `FilterConfiguration` is optional on create; a subscriber without one receives every event on the bus.
  A supplied `FilterConfiguration` needs at least one filter with a non-empty pattern, so `{}` is rejected
  on create with `FilterConfiguration must contain at least one Filter`.
* On update, `FilterConfiguration: {}` clears filtering entirely. Omitting `FilterConfiguration` leaves it
  unchanged. See chapter 16; this distinction is general.
* Size is bounded on the serialized `FilterConfiguration`, not on the pattern alone, so the usable pattern
  length shrinks as you add filters. Measure it rather than assuming a number.
* A filter that matches nothing is indistinguishable from a subscriber that is not working. You SHOULD
  confirm a should-match and a should-not-match case, and confirm both by observing the target.

## Transformer types

A subscriber's `Transformer` has three types:

* **`RAW`** (the default): deliver the payload alone.
* **`WITH_METADATA`**: deliver the three-part envelope shown above. Use this when the consumer needs
  `aws:EventId`, `aws:SequenceNumber`, or `aws:DeliveryType`.
* **`JSONATA`**: deliver the result of a JSONata expression.

`Type` selects among the three, and the expression lives in `JsonataConfiguration.Expression`, not on
`Transformer` itself. The complete block on a subscriber:

```json
"Transformer": {
  "Type": "JSONATA",
  "JsonataConfiguration": {
    "Expression": "{% { \"reference\": $events.Data.bookingRef, \"city\": $events.Data.disruption.destination } %}"
  }
}
```

A top-level `Expression` member on `Transformer` does not exist and is rejected. The transformer is a
per-subscriber setting, so every other subscriber on the bus keeps receiving the untransformed event.

## Writing a JSONata expression

A JSONata expression must be wrapped in `{% %}` delimiters and is capped at 8192 characters. The
expression sees the event as `$events`, addressed exactly as above.

Beyond the transformer, **most scalar target parameters also accept a JSONata expression** in the same
`{% %}` form, so you can derive a message group id, a partition key, an execution name, or a whole
universal-target request body from the event.

Two consequences of how expressions are validated:

* An expression is checked for syntax only, and for most target parameters a literal gets no more than
  that. The target owns its value ranges and identifier grammars, so a bad value is rejected at delivery
  whichever form you used. The exception is `InvocationTimeoutSeconds`, a service-owned range: there a
  literal out of range is rejected at create, while an expression's resolved value is clamped at delivery.
  A universal target refuses an expression for that member outright.
* Message-attribute names are expressions too. For an SQS or SNS target, both an attribute's name and its
  `StringValue` are evaluated per event. Their failure modes differ: a name resolving to nothing fails the
  delivery, as do two names resolving to the same string, while a `StringValue` resolving to nothing is
  delivered as a null value. A name's syntax is checked at create only when its `{%` and `%}` delimiters
  are both present, so `{% $events.Data` is taken as a literal name instead. `DataType` and `BinaryValue`
  are never evaluated; an expression in `BinaryValue` is rejected at create, and one in `DataType` reaches
  the target as its own text.
* An expression that resolves to nothing is not always harmless. In a `JSONATA` transformer a null result
  is a customer-fault delivery failure, reported as `TRANSFORMER_EXPRESSION_RESULT_EMPTY`. In a target
  parameter it arrives at the target as an empty value, which the target then usually rejects. Either way
  you **SHOULD** test every expression against a real event, and check `details.target_input` in the
  subscriber log to see what the target actually received (chapter 18).
