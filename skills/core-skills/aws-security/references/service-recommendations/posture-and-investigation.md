# Posture, correlation and investigation decisions

Use the parent skill’s focused-recommendation rules. Load the [full workflow](references/service-recommendations.md) only for collection, broad review or cost reduction.
Existing [enablement checks](references/service-recommendations/enablement-checks.md) retain collection and scoped negative-state rules.

## Hub capability and producer coverage

| Evidence | Selection consequence / overlap trap |
|---|---|
| Unified Hub state, linked regions, policy targets/application and source-service state | Separate aggregation, intended policy and deployed producer coverage. Hub presence does not establish that GuardDuty/Inspector/Macie are effectively covering a workload. |
| Actual missing reachability-assessment capability, eligible targets, existing exclusions and owner authorization | Consider Network Scanning only for that need; inventory is not permission to probe. Unresolved resource support prevents an eligibility conclusion. |
| Missing partner capability, connector health, Marketplace subscription and terms | Evaluate Extended coverage for that capability. A connector alone neither proves an active subscription nor justifies duplicate tooling. |
| Confirmed Azure use and supplied subscription/federation/app-permission metadata | Check integration scope and health without secrets or a cross-cloud crawl. Unknown permissions remain an integration question, not evidence that Azure is unprotected. |
| Routing order, connector state, ticket/update consumer and delivery evidence | Recommend closing a demonstrated ownership/delivery gap. A rule or connector's existence does not prove response coverage; preserve findings severity and visibility. |

For AI-related exposure, use [AI and malware scope](references/service-recommendations/detection-and-vulnerability.md#ai-and-malware-scope)
only when producer eligibility is in question. Exposure traits/trends do not establish
producer completeness or justify invented score transformations. Source: [Hub traits,
policies, integrations and Extended guidance][HU].

Where findings are produced but no verified triage or escalation owner exists, AWS Security
Incident Response is the service to evaluate for that gap. Two boundaries keep it honestly
scoped: it is not a detection service and must never be offered as a substitute for GuardDuty
or Security Hub CSPM, and it triages threat detection findings only. Posture and compliance
findings are not triaged: they describe a state in the environment, not an active threat
under investigation. It
deploys suppression rules only by agreement with its engineering team, and surfaces them in
the GuardDuty or Security Hub CSPM console; report any such rule as observed service
behaviour and still never recommend suppression. Enablement and coverage evidence is in
[enablement checks](references/service-recommendations/enablement-checks.md#aws-security-incident-response). Not guide-sourced;
sources: [service boundaries](https://docs.aws.amazon.com/security-ir/latest/userguide/what-is.html),
[onboarding prerequisites](https://docs.aws.amazon.com/security-ir/latest/userguide/onboarding-prerequisites.html).

## Standards and recorder context

Match standards to business obligations and confirmed AI workloads using the current catalog.
Compare control coverage during transition: simultaneous old/new standards are not themselves
a gap. Retirements/version claims need current evidence before recommending a migration.

Resolve standalone CSPM versus unified Hub plus CSPM before advising on Config. The
standalone recorder check in [enablement checks](references/service-recommendations/enablement-checks.md) owns status and scope
validation; the service-linked recorder case must not become a missing customer-recorder gap.
For other Config uses, establish CMDB, rule, conformance-pack, remediation and audit consumers
before considering scope reduction. This is supplemental Config context, not a separate audit.

Coexistence of Hub and CSPM is not duplicate ingestion evidence. Compare the actual findings
paths and EventBridge/SIEM/ticketing/Lambda consumers first. Retain Macie publication and the
finding aggregator required for central configuration. Under central configuration,
false/NONE auto-enable values are expected; policy association/application and member coverage
still need separate evidence under the workflow's organization review.

A demonstrated duplicate path with no dependent consumer may support consolidation advice;
unknown consumer ownership does not. Sources: [CSPM standards, duplicate aggregation and
Config guidance][CS], [Hub policies versus deployments][HU].

## Investigation fit

Compare the analyst's question with existing tooling before recommending Detective: quick
triage, entity timelines, cross-account/EKS context and deep raw-log reconstruction are
different needs. Use graph/package/member state, publishing freshness and analyst access
to judge whether a proposed capability would be usable. Graph and Lake presence alone do
not establish correlation; integration/source availability and query permissions matter.

An analyst who already has the required timelines may not need another investigation tool.
If EKS context is missing, evaluate relevant packages and access rather than claiming any
new graph would solve it. Use existing entity/time-scoped results to choose a handoff;
no new investigation or hunt follows from this assessment.

GuardDuty is not a Detective prerequisite. The current prerequisites are the required IAM
permissions and a recent AWS CLI version (confirm the current minimum from the Detective prerequisites documentation), so the pinned guide's prerequisite claim is
superseded. What remains is the recommendation to align the administrator account across
GuardDuty, Security Hub CSPM and Detective so the finding pivot and the archive-from-Detective
integration work; do not recommend enabling GuardDuty solely to satisfy a prerequisite gate.
Sources: [Detective fit, packages and integration guidance](https://github.com/aws/aws-security-services-best-practices/blob/f2b28d7c31c490ad676273307cbdb900c16daed8/docs/en/guides/detective/index.md),
[current prerequisites](https://docs.aws.amazon.com/detective/latest/userguide/detective-prerequisites.html),
[current recommendations](https://docs.aws.amazon.com/detective/latest/userguide/detective-recommendations.html).

## Lake sources and consumers

Two centralized stores are in scope and the decision is which one each consumer reads. The
Security Reference Architecture names Amazon CloudWatch the recommended primary option for
centralized log collection and analytics, with Amazon Security Lake remaining the secondary
option for organizations with existing investments or subscriber-based access requirements.
Security Lake is not deprecated; an existing deployment stays on the rows below. Recommend a
store, not a pipeline build. Route CloudWatch pipeline configuration and query authoring to
the observability owner or an installed CloudWatch skill. Any recommended centralized log
store MUST use KMS encryption at rest for its CloudWatch Logs log groups and S3 storage
sinks, and TLS in transit for delivery and consumer access. Report encryption configuration
as UNKNOWN unless current scoped evidence verifies the key and transport settings.

| Evidence | Recommendation consequence |
|---|---|
| Which store each existing consumer actually reads, and whether both collect the same AWS vended logs | Establish the consumer before changing either store. CloudWatch pipelines and Security Lake can both collect CloudTrail management events, CloudTrail S3 and Lambda data events, VPC Flow Logs, WAF logs, Route 53 resolver logs and EKS audit logs, and CloudWatch can also ingest Security Hub CSPM findings, so overlap is a stated-reason question, not an automatic gap. |
| Required source/account/region, trail selectors where relevant, ingestion exceptions and delivery | Recommend a missing source only for the investigation need and verified eligibility. Configured source presence is not proof of healthy delivery. |
| AWS-source `sourceVersion`, custom/partner source ownership, OCSF version, normalization and parser compatibility | Resolve schema and downstream compatibility before selecting an ingestion path or upgrade. A newer version is not automatically safe for current consumers, and a selected Security Lake source version needs a matching subscriber update before those consumers can read it. |
| CloudWatch Region eligibility, and whether normalization is acceptable to the forensic consumer | CloudWatch pipelines are available only in listed Regions, and adding a processor mutates the log event without retaining the raw original. Confirm an OCSF-normalized copy meets the evidence requirement before treating it as the only retained path. |
| Consumer's data versus query need, subscriber source scope and permissions | Choose the access model from the actual consumer requirement. Subscriber existence alone does not establish useful or appropriately scoped access. |
| Actual local/rollup retention and S3 lifecycle, native-log consumers and incident recovery objective | Compare recoverable history before cost advice. Do not remove the only usable source because a lake is enabled; cold-tier retrieval behavior and current charges need evidence. |

The two capabilities that otherwise make an agent default to Security Lake are matched on the
CloudWatch path: supported AWS sources are normalized to OCSF by a built-in OCSF processor,
and long-term storage routes to S3 Tables in Apache Iceberg format in the Log Archive
account, with Object Lock and Glacier policies for immutability. There the Log Archive
account is a storage sink only and runs no analytics workloads. CloudWatch pipelines carry no
separate processing charge, but standard CloudWatch Logs ingestion and storage rates still
apply and the metering point differs by source: CloudWatch Logs sources are metered before
processing, third-party and S3 sources are classified as custom logs and metered after.

Known source conflict. Disclose it; do not resolve it silently. The SRA's Log Archive page
places the CloudWatch delegated administrator in a dedicated Monitoring account within the
Security OU and names the capability Unified Data Experience, while its Security Tooling page
places it in the Security Tooling account and names it Unified Data Store. Present the
dedicated Monitoring account, disclose the divergence, and take component names from the
CloudWatch developer guide (pipelines, the OCSF processor, centralization rules). CloudWatch
is not a service in the pinned guide, so CloudWatch rows cite `n/a (not guide-sourced)` with
the SRA as placement context only.

For example, an enabled source with failed ingestion supports a delivery investigation;
it does not prove the SIEM has that data or justify retiring its working native-log path.
Sources: [Security Lake sources, subscribers, schema updates and retention][SL],
[SRA centralized log collection](https://docs.aws.amazon.com/prescriptive-guidance/latest/security-reference-architecture/log-archive.html),
[CloudWatch pipelines](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/cloudwatch-pipelines.html).

## Identity-analysis context

Use [IAM Access Analyzer's current overview](https://docs.aws.amazon.com/IAM/latest/UserGuide/what-is-access-analyzer.html)
for analyzer types and scope, not as a guide-sourced service recommendation. External-access
analyzers need relevant-region evidence; unused-access findings do not vary by region, so
repeating analyzers by region is not coverage expansion. Verify internal-access scope separately.
Compare the actual access question with the analyzer type and resource scope: an existing
unused-access analyzer cannot by itself answer an external-sharing question. Policy presence
or aggregation likewise does not establish an identity boundary; route Lattice-specific advice
to [segmentation](references/service-recommendations/network-protection.md#segmentation-and-identity) only when that path is relevant.

[HU]: https://github.com/aws/aws-security-services-best-practices/blob/f2b28d7c31c490ad676273307cbdb900c16daed8/docs/en/guides/security-hub/index.md
[CS]: https://github.com/aws/aws-security-services-best-practices/blob/f2b28d7c31c490ad676273307cbdb900c16daed8/docs/en/guides/security-hub-cspm/index.md
[SL]: https://github.com/aws/aws-security-services-best-practices/blob/f2b28d7c31c490ad676273307cbdb900c16daed8/docs/en/guides/security-lake/index.md
