---
_fragment: global
_of_phase: clarify
_contributes:
  - preferences.json
---

# Clarify global requirements

Load the vendored region, availability, compliance, cost-appetite, and multi-cloud questions. Resolve these facts only when discovery did not:

- AWS region, user geography, residency, compliance, blast-radius boundary, and account/environment isolation.
- Availability target, tolerated downtime, RTO, RPO, and whether source HA must be preserved.
- Management model: traditional Elastic Beanstalk, Beanstalk-managed cluster mode, direct ECS task/service control, or direct Kubernetes administration. Never offer App Runner.
- Deployment source and promotion intent: source build, Dockerfile, prebuilt image, or immutable Build Source artifact.
- Capacity-preserving versus measured right-sizing permission, cost posture, and CPU architecture compatibility.
- Preview-environment intent and production/staging isolation.

Compliance is essential and has no silent `none` default. Missing region, compliance, availability, or management-model facts remain unresolved whenever they can change a target or topology.

If `ai-workload-profile.json` exists, ask whether the user wants model migration, runtime migration, or both; preserve-versus-change acceptance; modalities, context, structured output, tools, streaming, latency, geography, golden tests, agent duration/state/concurrency/side effects/approvals/retries/compensation, and RAG compatibility. Record these for later resume only; do not choose an AI target.
