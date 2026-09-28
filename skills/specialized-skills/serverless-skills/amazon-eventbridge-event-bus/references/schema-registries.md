# Publishing Avro, Protobuf, and other open formats

Load this when publishing anything that is not JSON, or when setting up a schema registry for a publisher.

`PutRawEvents` takes any bytes, and `ContentType` declares what they are. It accepts exactly four
values:

| `ContentType` | Meaning | Needs a schema registry |
|---|---|---|
| `application/json` | JSON, routed and filtered on its content | no |
| `application/avro` | Avro binary, decoded against a registry | yes |
| `application/protobuf` | Protobuf binary, decoded against a registry | yes |
| `application/octet-stream` | opaque bytes, not inspected; route on metadata | no |

Anything else is rejected per entry with `Unsupported contentType: <value>. Supported types:
application/json, application/avro, application/protobuf, application/octet-stream.` That includes
`application/eventbridge+json`, which is the value the service stamps on `PutEvents` traffic and is not
accepted as input on `PutRawEvents`.

Avro and Protobuf are **open formats**: the service decodes them against a schema registry. Name that
registry **on the publish request**, which is the only place the API accepts one. An open-format entry
published without it is rejected per entry.

## The request-level field

When you supply `SchemaRegistryConfiguration`, **it MUST sit on the `PutRawEvents` call itself**, as a
sibling of `Entries` rather than inside an entry; one registry serves every entry in the request:

```bash
aws eventsv2 put-raw-events --event-bus-arn "$BUS_ARN" \
  --schema-registry-configuration '{"RegistryUri":"arn:aws:glue:us-east-1:111122223333:registry/orders"}' \
  --entries "[{\"Data\":\"$AVRO_B64\",\"SystemMetadata\":{\"ContentType\":\"application/avro\"}}]"
```

The Python and Java forms of the same call are in [code-samples.md](code-samples.md).

**The registry is read with your own credentials.** No role is passed on the request, so the identity
publishing the events **MUST** be allowed to read the registry it names.

### Where the registry cannot go

`SchemaRegistryConfiguration` appears on `PutRawEvents` and nowhere else in the API, so **you MUST NOT
configure decoding on the bus, on the subscriber, or on the transformer**. Each of the following is
**absent rather than accepted and ignored**, so looking for it only costs time:

| What you might reach for | What the API actually has |
|---|---|
| a registry on the bus | `CreateEventBus` and `UpdateEventBus` take `EncryptionConfiguration` and `StorageConfiguration`, and no registry member |
| a registry or decode setting on the subscriber | neither `CreateSubscriber` nor `UpdateSubscriber` has one |
| a decode setting on the transformer | `Transformer` has `Type` and `JsonataConfiguration` only |
| a per-entry registry, so one request could span registries | `PutRawEventsRequestEntry` has `Data`, `Metadata`, and `SystemMetadata` only |
| a registry on `PutEvents` | `PutEvents` has none; an open format reaches a bus only through `PutRawEvents` |

So the publisher decides decoding, once per request. A subscriber cannot ask for a different registry, and
a bus owner cannot impose one.

## The two registry kinds

`RegistryUri` accepts two forms:

| Registry | Form | Also required |
|---|---|---|
| AWS Glue Schema Registry | `arn:aws:glue:{region}:{account}:registry/{name}` | nothing further; the caller's credentials must allow reading it |
| Confluent Cloud Schema Registry | an `https://` URL | `SchemaRegistryConfiguration.ConfluentPublicRegistryConfiguration.ConnectionArn` |

**A Confluent registry needs an EventBridge Connection.** The `ConnectionArn` points at a connection holding
the API key or OAuth credentials for that registry, and you **MUST** provide it whenever `RegistryUri`
is an HTTPS URL. The connection keeps that credential in AWS Secrets Manager and hands you back only the
connection ARN, so **you MUST NOT put the registry credential in your own configuration** or in the
publish request. Create the connection before the first publish; a Glue ARN needs no connection because
the caller's own credentials cover the access.

## When the field is required

`SchemaRegistryConfiguration` is **required for open-format entries and ignored for JSON entries**, so
always sending it is harmless.

## Rejection messages

An open-format entry published without the registry block is rejected with
`SchemaRegistryConfiguration is required for open-format events`, and a payload whose frame does not match the
declared format is rejected with a message naming the format.

Schema deserialization is an enriched operation, billed per event
(see [cost-and-quotas.md](cost-and-quotas.md)).

## Running alongside Kafka

During an incremental move to AWS the bus complements a Kafka estate rather than replacing it, and the
format support above is the bridge. A producer already encoding Avro against a Confluent registry
publishes the same bytes with `PutRawEvents`, because `RegistryUri` takes the Confluent Cloud URL, and
consumers on the bus side receive decoded JSON without holding the schema or reaching the registry.
Crossing the other way, a subscriber delivers to whatever fronts the Kafka estate.

The behavioural difference to plan around is the delivery model. The bus **pushes** each event to a
subscriber's configured target; nothing polls. There are no consumer groups, no offsets to commit or
seek, and no log compaction. The nearest equivalents are one subscriber per consumer in place of a
consumer group, replay from retained history in place of an offset seek
([replay-and-recovery.md](replay-and-recovery.md)), and publish-time deduplication (chapter 11) in
place of compaction.
