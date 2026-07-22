# ARC Region switch — Positioning

Customer-facing framing, competitive comparison, and analyst/customer talking points for
Amazon Application Recovery Controller (ARC) Region switch. Load this when answering customer
positioning, analyst-briefing, or "how do I pitch/compare this" questions.

## Modern Framing

Use this language in all customer-facing and public contexts:

> "Region switch in ARC enables you to build comprehensive multi-Region recovery plans that include traffic shift, scaling, and database failover."

> "ARC Region switch provides centralized, observable recovery orchestration — replacing custom scripts with managed plans that execute automatically or on-demand."

> "With Region switch, you define your recovery logic once as a plan, and ARC handles execution, monitoring, and compliance reporting."

## Legacy Framing to Avoid

> ~~"Routing controls enable you to switch client traffic from one Regional replica to another."~~

> ~~"Use routing control states to manage failover."~~

> ~~"ARC clusters provide a highly available data plane for traffic management."~~

## Region switch vs Routing Controls

| Dimension | Region switch (plan-based) | Routing Controls (cluster-based) |
|-----------|----------------------|--------------------------|
| Model | Plan-based orchestration | Cluster-based traffic switching |
| Scope | Full recovery lifecycle (traffic + compute + DB + custom) | DNS traffic routing only |
| Automation | Triggers via CloudWatch alarms | Manual or API-driven state changes |
| Visibility | Dashboards, execution reports, plan evaluation | Safety rules, control panel |
| Cross-account | Native support | Not supported |

## Analyst Engagement Talking Points

For Gartner SCCPS, Forrester, and similar analyst briefings, emphasize:

1. **Plan-based orchestration** — Full recovery workflow with compute scaling, DB failover, custom logic
2. **Automatic execution** — CloudWatch alarm triggers remove human latency from recovery
3. **Compliance reporting** — Automatic PDF execution reports to S3 for audit evidence
4. **Full lifecycle** — Failover → recovery → post-recovery preparation (e.g., recreate replicas)
5. **Cross-account** — Enterprise-grade multi-account orchestration
6. **Data-plane isolation** — Per-Region endpoints; no dependency on impaired Region
7. **Continuous validation** — Plan evaluation catches drift before incidents occur

## Customer Conversation Guidance

**New to multi-Region DR** → Lead with value prop: managed, tested recovery plan vs hoping runbooks work. Focus on plan evaluation and execution reports.

**Migrating from routing controls** → Position as upgrade: same reliable data plane, now with orchestration (scaling, DB failover, custom actions alongside traffic shift).

**Compliance-focused (financial services, healthcare)** → Lead with execution reports, RTO tracking, plan evaluation, cross-account support.

**Comparing to third-party DR tools** → Differentiate on native AWS integration, data-plane-per-Region, fully managed, tight CloudWatch/EventBridge/IAM integration.

**Infrastructure-as-Code** → Reference the [Terraform provider for Region switch](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/arcregionswitch_plan) for incorporating Region switch into IaC workflows.
