# Azure telemetry ingestion into CloudWatch Application Observability

CloudWatch Application Observability ingests two different kinds of Azure telemetry, by
two different mechanisms. Both are supported, and which one the customer needs is the
first thing to settle.

Decide by the customer's **intent**, not by whether they already name a mechanism. Most
customers won't know the CloudWatch agent, a connector, or any setup process — guiding
them there is the whole point — so routing on keywords like "CloudWatch agent" or "Event
Hub" is wrong. Route on *what telemetry they are trying to collect*.

## Decide by intent

Ask what the customer actually wants to ingest:

- **The telemetry their own application/service produces** — the logs they write in their
  own code, and the metrics and traces their application emits, from an Azure VM or an AKS
  cluster. Load `custom-telemetry.md`: the **Amazon CloudWatch agent**, installed on that
  VM or cluster, forwarding over OTLP.

- **Telemetry their Azure resources emit on their own** — resource and platform diagnostic
  logs and metrics they did not author, and VNet flow logs; the Azure equivalent of AWS VPC
  flow logs or Route 53 query logs. Load `vended-telemetry.md`: a **CloudWatch Connector**
  holding trust to the tenant, a **telemetry manifest** capturing which resources they want
  telemetry from, and a **pipeline** writing into a log group in their account. No CloudWatch
  agent is involved. An `AccessDeniedException` from a connector, manifest, or pipeline
  operation is usually the connector role's trust or permission policy — diagnose it from
  `vended-telemetry.md` rather than guessing from the exception.

  Azure **Activity logs** are not delivered by this path. They are collected through the AWS
  Config connector and are not written to CloudWatch Logs, so do not list them here.

If the intent is unclear, ask exactly one question to disambiguate:

> Are you trying to send the telemetry your own application produces (the
> logs/metrics/traces from your code), or telemetry that your Azure resources emit on their
> own (like resource diagnostic logs or VNet flow logs)?

## Neither path substitutes for the other

They collect different things, so do not offer one as a workaround for the other. The
CloudWatch agent ships only the customer's own application telemetry and **cannot** collect
what Azure resources emit; the connector path carries resource-emitted telemetry and does
**not** carry an application's own OTLP. A customer who wants both needs both, set up
separately.

## Then

- Own application telemetry → `custom-telemetry.md`
- Resource-emitted telemetry → `vended-telemetry.md`
