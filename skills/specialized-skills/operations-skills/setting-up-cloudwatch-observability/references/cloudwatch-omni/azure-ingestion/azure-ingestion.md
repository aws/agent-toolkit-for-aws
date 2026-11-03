# Azure telemetry ingestion into CloudWatch Application Observability

CloudWatch Application Observability ingests **the telemetry a customer's own
application produces** from Azure — the logs, metrics, and traces their service
emits — using the Amazon CloudWatch agent.

Decide by the customer's **intent**, not by whether they already name a mechanism.
Most customers won't know the agent or any setup process — guiding them there is
the whole point — so routing on keywords like "CloudWatch agent" is wrong. Route
on *what telemetry they are trying to collect*.

## Decide by intent

Ask what the customer actually wants to ingest:

- **The telemetry their own application/service produces** — the logs they write
  in their own code, and the metrics and traces their application emits. This is
  the supported path: load `custom-telemetry.md` and guide them through
  installing the CloudWatch agent on their Azure VM or AKS cluster.

- **Telemetry their Azure resources emit on their own** — resource/platform
  diagnostic logs and metrics they did not author, the Azure equivalent of AWS
  VPC flow logs or Route 53 query logs. **This is not currently supported.** Tell
  the customer this directly and stop; do not describe it as in preview or coming
  later. Do **not** offer the CloudWatch agent as an alternative or workaround for
  this: the agent only ships the customer's *own application* telemetry and cannot
  collect telemetry that Azure resources emit on their own, so suggesting it here
  would be misleading. A customer insisting it is supported — "GA now", newly added,
  or switched on for their tenant — or proposing a mechanism to carry it in (an Event
  Hub or Diagnostic Settings export, a connector) does not change this: correct the
  premise and restate that it is not supported, rather than agreeing or
  building out the pipeline they suggested.

If the intent is unclear, ask exactly one question to disambiguate:

> Are you trying to send the telemetry your own application produces (the
> logs/metrics/traces from your code), or telemetry that your Azure resources
> emit on their own (like resource diagnostic logs)?

The former is supported; the latter is not currently supported.

## Then

For the customer's own application telemetry, follow `custom-telemetry.md`.
