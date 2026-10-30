# Clarify — Compliance & Regulatory Requirements (canonical)

> Canonical compliance question for Clarify's Global/Strategic category,
> vendored into each skill that runs a full-migration Clarify phase
> (`references/vendored/clarify/clarify-compliance.md`) and kept
> byte-identical by `shared:sync`. This question is **source-cloud-agnostic**
> — the compliance regime a customer is under does not depend on whether they
> are leaving GCP, Azure, or Heroku, so the question, its options, and its
> defaulting semantics are identical everywhere. **This question ALWAYS
> FIRES for a full-infrastructure migration** — no skill may skip it, default
> it silently to "none", or gate it behind a detected signal. Compliance gates
> the entire service catalog and region choice; it is exactly the kind of
> requirement that cannot be inferred from Terraform/ARM/Bicep.

## Why this file exists

`gcp-to-aws` asks this question as an always-fires ESSENTIAL (its Q2). Before
this file, `azure-to-aws`'s infrastructure Clarify flow asked no compliance
question at all — its Estimate phase had to carry a permanent
`compliance: null` (never confirmable) special case and a permanently-true
condition in its complexity-tier logic as a result. That is a product gap, not
a design choice: an Azure customer with HIPAA or PCI obligations got no
compliance gate on their infrastructure migration. Promoting GCP's question
into this shared file and wiring it into Azure's `clarify-global.md` closes
that gap without inventing new wording.

## The question

> Compliance requirements determine which AWS services, regions, and configurations are
> available to you. This gates the entire architecture.
>
> 1. None — No specific compliance requirements
> 2. SOC 2 / ISO 27001 — Security and availability standards
> 3. PCI DSS — Payment card data handling
> 4. HIPAA — Healthcare data
> 5. FedRAMP / Government — Federal compliance
> 6. GDPR / Data residency — EU data sovereignty requirements
> 7. CCPA / CPRA — California Consumer Privacy Act / California Privacy Rights Act
> 8. I don't know
>
> _(Multiple selections allowed)_

| Answer            | Recommendation Impact                                                                                                                                                                                                                                                                                                                                          |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| None              | Full service catalog available, any region                                                                                                                                                                                                                                                                                                                     |
| SOC 2 / ISO 27001 | CloudTrail, Config, Security Hub enabled by default; encryption at rest required                                                                                                                                                                                                                                                                               |
| PCI DSS           | CloudTrail, Config, Security Hub + PCI DSS standard enabled by default; dedicated VPC with strict segmentation; WAF required; no shared tenancy for cardholder data; specific RDS encryption config                                                                                                                                                            |
| HIPAA             | CloudTrail, Config, Security Hub (FSBP only — Security Hub does not provide a HIPAA-specific standard) enabled by default; BAA-eligible services only; encryption in transit and at rest mandatory; specific logging requirements; us-east-1/us-west-2 preferred; engage a qualified HIPAA auditor for end-to-end posture validation                           |
| FedRAMP           | CloudTrail, Config, Security Hub (FSBP only — NIST 800-53 is the target control set but is not directly subscribable in Security Hub the way PCI DSS is; engage your AWS account team for agency-level attestation) enabled by default; GovCloud regions required (us-gov-east-1, us-gov-west-1); GovCloud-specific service endpoints; limited service catalog |
| GDPR              | EU regions required (eu-west-1, eu-central-1), data residency constraints, no cross-region replication outside EU without explicit consent                                                                                                                                                                                                                     |
| CCPA / CPRA       | Consumer privacy posture: data inventory, access/deletion workflows, opt-out of sale/sharing where applicable, retention minimization, encryption and audit logging (CloudTrail); prefer documenting data flows and subprocessors — confirm target regions with legal/compliance (often US)                                                                    |

### Interpret

```
1 -> compliance: [] (no constraint written — user explicitly confirmed no requirements; full service catalog, any region)
2 -> compliance: ["soc2"] — CloudTrail, Config, Security Hub enabled; encryption at rest required
3 -> compliance: ["pci"] — Dedicated VPC, WAF required, strict segmentation
4 -> compliance: ["hipaa"] — BAA-eligible services only, encryption mandatory, us-east-1/us-west-2 preferred
5 -> compliance: ["fedramp"] — GovCloud regions required (us-gov-east-1, us-gov-west-1)
6 -> compliance: ["gdpr"] — EU regions required (eu-west-1, eu-central-1), data residency constraints
7 -> compliance: ["ccpa"] — CCPA/CPRA: logging, retention, consumer-request readiness; document data flows; align region/subprocessor choices with legal review
8 -> compliance: ["unknown"] — not confirmed; verify with compliance team before production
```

**Defaulted / "I don't know" semantics:** When this question resolves without an explicit
user selection — answer 8, or "use defaults for the rest" — write `compliance: ["unknown"]`
(`chosen_by: "user"` for 8, `"default"` with a `source` naming this question for defaults).
**Never silently record "no requirements".** Downstream, `["unknown"]` behaves exactly like
"none" for architecture and service selection (no speculative BAA-only stack), but it
triggers the report's compliance caveat and counts as unverified in decision confidence.

**Default:** `compliance: ["unknown"]` — unconfirmed, with report caveat. Only reachable via
an explicit skip ("use defaults for the rest"); this question is otherwise always asked and
never silently defaulted to "none".

## What a consuming skill supplies

Each skill's `clarify-global.md` (or equivalent) supplies:

1. **Firing rule** — for a full-infrastructure migration this question is
   **always ESSENTIAL, no exceptions**. A skill's AI-only path may reuse this
   same file (as `gcp-to-aws`'s `clarify-ai-only.md` already does for its Q1.5)
   with skill-specific framing about where compliance applies when the
   customer's infrastructure stays on the source cloud and only AI calls move
   to Bedrock — see that fragment for the Bedrock-specific impact table
   pattern, which supplements (does not replace) the impact table above.
2. **Cross-check with other answers** — e.g. GCP's flow cross-checks a GDPR
   answer against the region-geography question jointly.
