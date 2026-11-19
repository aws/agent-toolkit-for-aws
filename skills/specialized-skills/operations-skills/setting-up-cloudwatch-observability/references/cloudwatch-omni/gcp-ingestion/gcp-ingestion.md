# Google Cloud telemetry ingestion into CloudWatch Application Observability

CloudWatch Application Observability ingests **the telemetry a customer's own
application produces** from Google Cloud — the logs, metrics, and traces their
service emits — using the Amazon CloudWatch agent.

Decide by the customer's **intent**, not by whether they already name a mechanism.
Most customers won't know the agent or any setup process — guiding them there is
the whole point — so routing on keywords like "CloudWatch agent" is wrong. Route
on *what telemetry they are trying to collect*.

## Decide by intent

Ask what the customer actually wants to ingest:

- **The telemetry their own application/service produces** — the logs they write
  in their own code, and the metrics and traces their application emits. This is
  the supported path: load `custom-telemetry.md` and guide them through
  installing the CloudWatch agent on their GCE instance or GKE cluster.

- **Telemetry their Google Cloud resources emit on their own** — resource and
  platform logs and metrics they did not author, the Google Cloud equivalent of
  AWS VPC flow logs or Route 53 query logs (Cloud Audit Logs and the VPC flow
  logs Google Cloud emits for them). **This is not supported.** Tell the customer this directly and stop. Do **not** offer the
  CloudWatch agent as an alternative or workaround for this: the agent only ships
  the customer's *own application* telemetry and cannot collect telemetry that
  Google Cloud resources emit on their own, so suggesting it here would be
  misleading regardless of what else the feature list gains.

If the intent is unclear, ask exactly one question to disambiguate:

> Are you trying to send the telemetry your own application produces (the
> logs/metrics/traces from your code), or telemetry that your Google Cloud
> resources emit on their own (like Cloud Audit Logs)?

The former is supported; the latter is not.

## Then

For the customer's own application telemetry, follow `custom-telemetry.md`.
