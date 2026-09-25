# Publishing CloudEvents

Load this when publishing or consuming CloudEvents on a bus, or when writing a filter, transformer, or
target parameter that reads CloudEvents attributes.

A CloudEvent travels as an ordinary JSON payload, so **you MUST publish it with `PutRawEvents`**: that is
the only operation carrying a payload and a `ContentType` you supply, whereas `PutEvents` builds its own
envelope and sets `ContentType` server-side. **You SHOULD publish the whole event in the CloudEvents
JSON format's structured mode**, meaning one JSON object holding the attributes and the `data` member,
because the binary mode splits the attributes away from the payload and a filter then has no attribute to
match. **You MUST declare `ContentType: application/json`** in the entry's `SystemMetadata`; the full set
of accepted content types is in [schema-registries.md](schema-registries.md).

`Data` is a blob, so the CLI takes it base64-encoded:

```bash
CE='{"specversion":"1.0","id":"A234-1234-1234","source":"/example/orders","type":"com.example.order.placed","time":"2026-09-15T22:00:00Z","subject":"order-42","datacontenttype":"application/json","dataschema":"https://example.com/schemas/order/v1","comexampleextension1":"ext-value","data":{"orderId":"order-42","amount":99.5,"items":["a","b"]}}'

B64=$(printf '%s' "$CE" | base64 -w0)

aws eventsv2 put-raw-events --event-bus-arn "$BUS_ARN" \
  --entries "[{\"Data\":\"$B64\",\"SystemMetadata\":{\"ContentType\":\"application/json\"}}]"
```

**The bytes are stored and delivered unchanged.** A subscriber with `Transformer: { Type: RAW }` receives
the CloudEvent as published, with attribute order preserved and every optional and extension attribute
intact, so a consumer can pass the payload straight to a CloudEvents SDK. **A subscriber whose consumer
hands the payload to a CloudEvents SDK MUST use `Type: RAW`**, because `WITH_METADATA` and `JSONATA`
reshape what is delivered and the envelope no longer round-trips.

## Filtering on CloudEvents attributes

Each attribute is a top-level key of the payload, so a `DATA`-scoped filter names it directly:

```json
{"type": ["com.example.order.placed"], "specversion": ["1.0"]}
```

`subject`, `source`, `dataschema`, and any extension attribute work the same way, and `data` is a nested
member, so `{"data":{"orderId":[{"exists":true}]}}` addresses the payload inside it. A JSONata
transformer and a target parameter read the same paths
([filters-and-expressions.md](filters-and-expressions.md)).

## Batching, provenance, and binary data

**You SHOULD publish one CloudEvent per entry.** The CloudEvents batch format is a JSON array of events,
and an array published as one entry is one event to this service. Filtering, deduplication, ordering, and
billing all apply per entry, so a batched array is routed as a single unit and cannot be filtered per
event. Batch with the `Entries` list instead.

**A CloudEvent's `source` attribute carries no provenance guarantee, and you MUST NOT treat it as one.**
Neither `PutEvents` nor `PutRawEvents` carries a system-metadata member for the service-set `aws:Source`
key, so no caller can supply it and a CloudEvent published this way arrives with no `aws:Source` at all; the payload's `source`
is ordinary data any publisher can set to any value. A subscriber that needs the trusted pair has to read
forwarded traffic, where the service writes it ([authorization.md](authorization.md)).

**Binary `data` arrives base64-encoded inside the JSON.** The CloudEvents JSON format carries binary
payloads in `data_base64` rather than `data`, and a filter cannot inspect a base64 string, so a pattern
written against it silently matches nothing. **You SHOULD filter on the attributes instead**, or publish
the raw bytes as `application/octet-stream`, which carries no attributes at all.
