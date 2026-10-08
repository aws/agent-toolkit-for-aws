# Pass 3 — Inventory to Service Recommendation Matrix

Workload rows require discovered resources or confirmed use; baseline and organization
rows require their stated conditions. Apply gaps only to validated negative evidence,
not UNKNOWN or NOT ASSESSED checks. Record NOT APPLICABLE when irrelevance is verified.

The priority column is conditional, not descriptive. No value in it may be emitted for a
requirements-only or ADVISORY answer, or for any recommendation whose gap is not established by
validated negative evidence. Reading a trigger row for its recommendation carries no priority
with it. Every recommendation that creates or selects a logging, export, notification,
publishing, trail or delivery-channel destination inherits the parent Skill's encryption,
destination-policy and notification-recipient requirements. Inline clauses are reminders;
unverified KMS, TLS, policy, recipient, retention or delivery controls remain UNKNOWN.

Centralized log store rows: the Security Reference Architecture names Amazon CloudWatch the
recommended primary option for centralized log collection and analytics, with Amazon Security
Lake the secondary option for organizations with existing investments or subscriber-based
access requirements. The Security Lake source rows below stay correct for an existing
deployment and no row here implies the service is going away. Read the
[log-store decision](references/service-recommendations/posture-and-investigation.md#lake-sources-and-consumers) before
recommending either store.

## Contents

- [Baseline: account activity and stated conditions](#baseline-account-activity-and-stated-conditions)
- [Triggered by compute](#triggered-by-compute)
- [Triggered by containers](#triggered-by-containers)
- [Triggered by data](#triggered-by-data)
- [Triggered by network and edge](#triggered-by-network-and-edge)
- [Triggered by certificates](#triggered-by-certificates)
- [Triggered by organization context](#triggered-by-organization-context)
  - [Standards hygiene](#standards-hygiene)
  - [Organization posture](#organization-posture)
- [Priority assignment](#priority-assignment)
- [Report format](#report-format)
- [Focused suitability beyond enablement](#focused-suitability-beyond-enablement)

## Baseline: account activity and stated conditions

These use account activity plus the row-specific conditions rather than a workload trigger.

| Recommendation | Priority | Rationale |
|---|---|---|
| GuardDuty foundational (CloudTrail, VPC flow, DNS analysis) | **Critical** | Threat detection with no data-source configuration; pulls streams directly |
| AWS Config recorder, **when Security Hub CSPM runs standalone** | **Critical** | Standalone CSPM uses your recorder for most controls. Require its delivery channel's S3 destination and any SNS topic to use KMS encryption at rest and TLS in transit, with parent destination-policy and recipient controls and separate retention/delivery evidence. With unified Security Hub also enabled, CSPM manages the service-linked recorder `AWSConfigurationRecorderForSecurityHubCSPM` and this row does not apply |
| Security Hub CSPM with FSBP | **Critical** | Baseline posture standard; the guide's starting point |
| IAM Access Analyzer external-access analyzer | **High** | Surfaces unintended external access to resources |
| Cross-region finding aggregation, when more than one region is in use | **High** | Regional services produce fragmented findings otherwise |
| AWS Security Incident Response, where GuardDuty or Security Hub CSPM produces findings and validated evidence shows no triage or escalation owner | Medium (verified gap only) | Sits downstream of detection: it ingests and triages threat detection findings from GuardDuty and Security Hub, and never substitutes for either. It triages threat detection findings only — posture and compliance findings are not triaged. Evaluate and hand off; unverified ownership is UNKNOWN, not a gap. Read [producer coverage](references/service-recommendations/posture-and-investigation.md#hub-capability-and-producer-coverage) for the boundaries |

## Triggered by compute

| Trigger from pass 1 | Recommend | Priority |
|---|---|---|
| Any EC2 instance | GuardDuty `EBS_MALWARE_PROTECTION` | High |
| Any EC2 instance | Inspector `EC2` scanning through Enhanced EC2 Scanning (the VM Scanner), not the legacy SSM plugin | High |
| EC2 instance, SSM-managed | GuardDuty `RUNTIME_MONITORING` with `EC2_AGENT_MANAGEMENT` | High |
| EC2 instance, **not** SSM-managed, Runtime Monitoring wanted | Default Host Management Configuration via SSM Quick Setup first; GuardDuty EC2 agent management requires SSM | High |
| Any EC2 instance on a platform documented as supported for Deep Inspection, verified against the latest Inspector documentation | Inspector Deep Inspection with Enhanced EC2 Scanning | Medium |
| Any Lambda function | Inspector `LAMBDA` **and** `LAMBDA_CODE` | High |
| Any Lambda function | GuardDuty `LAMBDA_NETWORK_LOGS` | Medium |
| Any AI service documented as covered by GuardDuty AI Protection in use, after verifying the latest service and event-type eligibility | GuardDuty `AI_PROTECTION` | High |

For scanner/coverage nuances, read [runtime and workload coverage](references/service-recommendations/detection-and-vulnerability.md#runtime-and-workload-coverage).

## Triggered by containers

| Trigger from pass 1 | Recommend | Priority |
|---|---|---|
| Any ECR repository | Inspector `ECR` scanning, continuous | High |
| ECR repository with images | ECR rescan duration tuned to build cadence | Medium |
| Any EKS cluster | GuardDuty `EKS_AUDIT_LOGS` | High |
| EKS cluster on EC2 nodegroups | GuardDuty `RUNTIME_MONITORING` with `EKS_ADDON_MANAGEMENT` | High |
| EKS cluster, Fargate profiles only | **Do not** recommend Runtime Monitoring — unsupported | n/a |
| ECS cluster on Fargate | GuardDuty `RUNTIME_MONITORING` with `ECS_FARGATE_AGENT_MANAGEMENT` | High |
| ECS cluster on EC2 | GuardDuty `RUNTIME_MONITORING`; the agent on the container instances follows the EC2 path per the guide's linked prerequisites, not an automated ECS setting | High |
| Any EKS cluster | Security Lake `EKS_AUDIT` source | Medium |
| EKS cluster | Detective for cross-account container visibility | Medium |

For agent rollout or image relevance, read [runtime and workload coverage](references/service-recommendations/detection-and-vulnerability.md#runtime-and-workload-coverage).

## Triggered by data

| Trigger from pass 1 | Recommend | Priority |
|---|---|---|
| Any S3 bucket | GuardDuty `S3_DATA_EVENTS` | High |
| Any S3 bucket | Macie automated sensitive data discovery | High |
| Macie enabled | Classification export to S3 before Macie's retention period for discovery results ends; require KMS encryption at rest and TLS in transit for delivery and consumer access, and verify retention and successful delivery separately | High |
| Macie enabled, sensitive data findings not published to Security Hub CSPM | Enable publishing so Security Hub exposure scoring and GuardDuty attack sequences see sensitive-data traits | High |
| S3 bucket taking untrusted or third-party uploads | GuardDuty S3 Malware Protection, **per bucket** | High |
| Many or large S3 buckets | Automated discovery over discovery jobs | Medium |
| Dataset requiring full coverage, not sampling | Targeted discovery job in addition | Medium |
| RDS / Aurora database meeting current supported engine/version and applicable prerequisites | GuardDuty `RDS_LOGIN_EVENTS` | High |
| Backup vaults protecting recovery-critical workloads (EBS snapshots, AMIs, S3 recovery points) | Malware Protection for AWS Backup, those vaults first | Medium |

For RDS eligibility or selective malware scope, read [AI and malware scope](references/service-recommendations/detection-and-vulnerability.md#ai-and-malware-scope).
For discovery completeness or export evidence, read the relevant [Macie decision](references/service-recommendations/data-discovery.md#assurance-and-scanability).

## Triggered by network and edge

| Trigger from pass 1 | Recommend | Priority |
|---|---|---|
| Internet-facing ALB **not** behind CloudFront, no WebACL | AWS WAF — route to the `waf` skill | **Critical** |
| CloudFront distribution with application logic behind it, no WebACL | AWS WAF at the CloudFront layer — route to the `waf` skill | **Critical** |
| ALB behind CloudFront with a distribution WebACL and verified origin access restrictions | Distribution protection may suffice; do not automatically duplicate WAF on the ALB | n/a |
| CloudFront serving only static cached content, no WebACL | Informational; the guide calls WAF here uncommon and low value | Low |
| Internal ALB, no WebACL | n/a unless it indirectly handles unfiltered traffic from a network you do not control | n/a |
| API Gateway REST API not behind CloudFront, no WebACL | AWS WAF — route to the `waf` skill | High |
| Internet-facing NLB or non-HTTP ingress with an established traffic-inspection requirement | Evaluate Network Firewall for that requirement; presence alone is not a gap. Shield Advanced follows its own row | Medium |
| Confirmed public or private application needing AppSec assessment | Evaluate AWS Security Agent (part of AWS Continuum) through [application fit and scope](references/service-recommendations/application-security.md#application-fit-and-scope); conditional AppSec-owner handoff | Low |
| VPC with no DNS Firewall rule group association | Route 53 Resolver DNS Firewall with AWS-managed lists — route to the `route53` skill | High |
| DNS Firewall associated, no query logging | Enable Resolver query logging to a destination that uses KMS encryption at rest and TLS in transit for delivery and consumer access; verify retention and delivery separately | Medium |
| DNS Firewall associated, Advanced rules off | DNS Firewall Advanced for tunneling and DGA detection | Medium |
| Any VPC | Security Lake default sources `VPC_FLOW` and `ROUTE53`; no flow-log or query-log prerequisite | Medium |
| Revenue-generating internet-facing workload on CloudFront, ALB, EIP, Global Accelerator, or Route 53, where downtime cost exceeds the subscription | Shield Advanced, verifying current WAF/Firewall Manager bundled eligibility — route to the `shieldadvanced` skill. CloudFront L3/L4 volumetric protection is already AWS's responsibility | Medium |
| Egress traffic needing L3-L7 inspection | Network Firewall | Medium |
| Network Firewall deployed, observed rule order conflicts with the verified intended policy strategy | Review strict-order suitability and rule dependencies with the firewall owner; establish the intended strategy before recommending a change | High (verified gap only) |
| Network Firewall deployed, default actions do not meet demonstrated enforcement or logging requirements under the selected compatible strategy | Review application-aware versus custom defaults and observed verdict/log evidence; do not universally pair drop and alert defaults or infer enforcement from configuration | High (verified gap only) |
| Network Firewall deployed, stream-exception behavior conflicts with application recovery requirements | Review the selected policy against application recovery, active connections and idle-flow evidence; assess planned change impact with the owner rather than assuming a universal restart | High (verified gap only) |
| Network Firewall deployed, endpoint coverage does not meet the verified deployment mode and traffic-path requirements | Review topology-specific endpoint/AZ coverage for inspection-VPC, native TGW or multi-endpoint mode; recommend changes only for a demonstrated path requirement | High (verified gap only) |
| Network Firewall deployed, no logging configuration | Enable ALERT and FLOW logs to separate destinations that use KMS encryption at rest and TLS in transit for delivery and consumer access; verify retention and delivery separately | Medium |
| 10+ accounts with **distributed** WAF, DNS Firewall, or Network Firewall deployments (per account or per VPC) | Firewall Manager for policy rollout and enforcement; requires Organizations and AWS Config; verify current pricing and Shield Advanced bundled eligibility. Limited value for a centralized single-firewall design | Medium |

For the conditional Network Firewall rows, unresolved topology, intent or compatibility
is an UNKNOWN evidence disposition, not a recommendation priority. Assign High only
to a verified gap; unassessed or advisory-only decisions have no gap priority.

For origin bypass, read [endpoint coverage](references/service-recommendations/web-protection.md#endpoint-coverage-and-bypass); for inspection paths, read [routed inspection](references/service-recommendations/network-firewall.md#routed-inspection-and-policy).

## Triggered by certificates

| Trigger from pass 1 | Recommend | Priority |
|---|---|---|
| Certificate estate with demonstrated unmet monitoring coverage, delivery or lead-time needs after evaluating the chosen monitoring method | Close the verified monitoring gap; EventBridge expiry routing to SNS is an option only when event applicability and unmet needs justify it. If SNS is selected, require KMS encryption at rest, TLS in transit, the parent topic-policy and authorized-recipient controls, and separate successful-delivery evidence. Adequate CloudWatch alarms or issuer-side checks require no duplicate route; unknown monitoring or destination protection stays UNKNOWN | High (verified gap only) |
| Certificate with `Type: IMPORTED` | Renewal automation (the guide's pattern is an AWS Config rule plus Lambda); ACM does not renew imports. Verify expiration monitoring separately | High |
| Certificate issued via Private CA `IssueCertificate` | Separate renewal and expiration monitoring; verify ACM representation and event applicability before proposing ACM event routing | High |
| ACM-requested public/private certificate with renewal eligibility or state unresolved | Record renewal evidence as UNKNOWN; verify issuance path, `RenewalEligibility` and available renewal status; do not infer failure from `Type: PRIVATE` | n/a |
| Email-validated certificate | Migrate to DNS validation for automatic renewal | Medium |
| Certificate with `InUse: false` | Review and remove — unused certs count against quota | Low |
| `DaysBeforeExpiry` at its default | Confirm the configured value suits the renewal process (check the allowed range in the ACM documentation) | Low |
| Private CA present or PKI architecture requested | Assess [trust domains and root isolation](references/service-recommendations/certificates.md#trust-domains-and-root-isolation) against issuing requirements; no fixed depth gate | Medium (verified gap only) |
| Internal hostnames in a public certificate | Consider disabling Certificate Transparency logging | Low |

ACM cannot be "enabled" — it is always available. These are monitoring gaps rather than
enablement gaps, and the priority reflects that an unmonitored expiry is an outage, not a
breach.

## Triggered by organization context

### Standards hygiene

Triggered by pass 2 rather than pass 1 — these are findings about how enabled standards
are configured.

| Observed in pass 2 | Recommend | Priority |
|---|---|---|
| Unified Security Hub enabled **and** CSPM still ingesting AWS service or third-party findings that Security Hub already aggregates | Duplicate ingestion — audit EventBridge, SIEM, ticketing, and Lambda consumers first, then disable that ingestion in CSPM. Keep Macie publishing to CSPM (it is how sensitive-data traits reach Security Hub) and keep the cross-region finding aggregator, which central configuration requires | Medium |
| Unified Security Hub enabled, Threat Analytics off | Consider Threat Analytics for production so GuardDuty detections appear beside the misconfigurations that enabled them | Medium |
| Unified Security Hub not enabled, CSPM only | Evaluate unified Security Hub for exposure findings and attack path analysis | Medium |
| PCI DSS on a superseded version | Migrate to the current supported PCI DSS version; confirm the available versions with `aws securityhub describe-standards`. The PCI SSC's retirement of older versions is external context, not guide-sourced | High |
| PCI DSS enabled on two versions at once | Retire the superseded version once coverage is compared; verify pricing before claiming duplicate charges | Medium |
| CIS AWS Foundations below the latest supported version | Plan migration to the latest version confirmed via `describe-standards`; both may run during transition | Medium |
| FSBP as the only enabled standard | Layer standards per business requirement | Low |
| `AutoEnableStandards: NONE` under **local** configuration | New accounts get no standards — set to `DEFAULT` | High |
| Central configuration `ENABLED` with `AutoEnable: false` or `AutoEnableStandards: NONE` | Expected field values under central configuration; verify policy association/application and member coverage separately, or report those UNKNOWN | n/a |
| Security Hub CSPM enabled, Security Lake in use without `SH_FINDINGS` | Security Lake `SH_FINDINGS` source | Medium |

The guide's transition guidance is to enable both versions simultaneously to compare
coverage, then retire the old one. Flag a long-lived overlap, not the overlap itself.

### Organization posture

| Trigger from pass 1 | Recommend | Priority |
|---|---|---|
| More than one member account | Delegated administrator per service in the security tooling account | **Critical** |
| Security Lake in use | Delegated administrator in the **Log Archive** account | High |
| Centralized log collection and analytics in use or being selected | CloudWatch delegated administrator in a dedicated **Monitoring** account in the Security OU, the SRA's recommended primary option. Log Archive stays a storage sink and runs no analytics workloads. The SRA's own pages diverge on this placement; disclose the conflict with the [log-store decision](references/service-recommendations/posture-and-investigation.md#lake-sources-and-consumers) | High |
| CloudWatch pipelines and Security Lake both collecting the same AWS vended logs with no stated reason | Audit which store each consumer actually reads before changing either. Both can collect CloudTrail management events, CloudTrail S3 and Lambda data events, VPC Flow Logs, WAF logs, Route 53 resolver logs and EKS audit logs, and CloudWatch can also ingest Security Hub CSPM findings, so overlap alone is not a gap | Medium |
| Members enrolled, auto-enable off under local configuration | Auto-enable for new accounts | **Critical** |
| Inspector config drift concern | AWS Organizations Inspector policy | High |
| Per-account Security Hub setup | Central configuration policy | High |
| Multi-region organization trail present | Security Lake `CLOUD_TRAIL_MGMT` | Medium |
| No multi-region org trail | Create one before recommending the Security Lake CloudTrail source. Require log file validation, KMS encryption at rest and TLS in transit for its S3 destination and any CloudWatch Logs delivery, with parent destination-policy controls and separate retention/delivery evidence | High |
| GuardDuty enabled, no log-correlation tooling | Detective | Medium |
| Account count near the Detective behavior graph member-account quota (confirm the current value) | Note the quota | Medium |

Delegated administrator placement per the Security Reference Architecture: GuardDuty,
Security Hub, Inspector, Macie, Detective and Security Incident Response in one security
tooling account; Security Lake in the Log Archive account; CloudWatch in a dedicated
Monitoring account in the Security OU. With Control Tower, the security tooling account is
the existing Audit or Security account. Flag any divergence.

## Priority assignment

- **Critical** — no threat detection or posture baseline at all; org-wide coverage gap
  that grows with every new account; internet-facing HTTP resource with application logic
  and no L7 protection
- **High** — a deployed resource type has no corresponding detection; a prerequisite for
  an enabled service is missing; findings are fragmented across regions
- **Medium** — coverage exists but is untuned; a defense-in-depth service is absent;
  cost optimization available without losing visibility
- **Low** — configuration polish; documentation of accepted risk

## Report format

Summarize scope, evidence completion, and limitations first. Use counts and masked
identifiers by default; identifier disclosure requires an explicit request, and raw
responses require an explicit raw-output request. Never include credentials, account
emails, target payloads, or secret origin headers, even in requested raw output.
Recommendation priorities below are workflow-authored; preserve source findings severity
and AttackSequence/Exposure-first ordering in separate findings summaries.

For each recommendation:

```
[PRIORITY] <Service or plan>
  Justified by:  <resource/count or verified account/activity condition; account/region scope>
  Current state: OBSERVED <configuration/coverage> | NOT ENABLED (validated) | UNKNOWN <reason> | NOT ASSESSED | NOT APPLICABLE | ADVISORY
  Guide section: <guide page> | n/a (not guide-sourced)
  Cost note:     <verified pricing/usage implication, or UNKNOWN with needed evidence>
  Advisory action: <proposed change in prose>
  Handoff:       <separate implementation workflow for an accepted recommendation>
```

`Guide section: n/a` is correct and expected for IAM Access Analyzer, AWS Security Incident
Response, CloudWatch, the `AutoEnableOrganizationMembers: ALL` pass condition, the DNS
Firewall fail-open check, the PCI DSS v3.2.1 retirement fact, and the priority ranking
itself. AWS Config cites the CSPM guide's standalone case. Do not invent a citation to fill the field — an unsourced
recommendation labelled as such is more useful than a fabricated reference.

## Focused suitability beyond enablement

For a confirmed need below, read the linked file and relevant section **before resolving
that decision**. Load only relevant sections, not every domain. Existing protections and
planned workloads can trigger these decisions; inventory alone cannot establish the need.
Use the workflow's bounded evidence and handoff rules. Requirements-only advice is ADVISORY.

| Confirmed need | Decision / read when relevant |
|---|---|
| Runtime health, scanner paths or image cadence | [Resolve effective workload coverage](references/service-recommendations/detection-and-vulnerability.md#runtime-and-workload-coverage) |
| AI or bucket/vault malware coverage | [Match protection to use and eligibility](references/service-recommendations/detection-and-vulnerability.md#ai-and-malware-scope) |
| Repositories, CI/CD, CIS or SBOM | [Identify the missing assurance stage](references/service-recommendations/detection-and-vulnerability.md#repository-and-benchmark-suitability) |
| Macie sampling or unscannable data | [Match discovery depth to assurance](references/service-recommendations/data-discovery.md#assurance-and-scanability) |
| Macie export or publication | [Separate retained evidence from correlation](references/service-recommendations/data-discovery.md#evidence-delivery-and-use) |
| Hub reachability, partner, Azure or response need | [Validate capability and producer coverage](references/service-recommendations/posture-and-investigation.md#hub-capability-and-producer-coverage) |
| Standards, Config or ingestion overlap | [Resolve obligations, recorder and consumers](references/service-recommendations/posture-and-investigation.md#standards-and-recorder-context) |
| Detective or investigation tooling | [Compare analyst need with usable context](references/service-recommendations/posture-and-investigation.md#investigation-fit) |
| Lake ingestion, subscribers or retention | [Validate useful, recoverable consumer data](references/service-recommendations/posture-and-investigation.md#lake-sources-and-consumers) |
| Identity-analysis scope | [Choose the relevant analyzer question](references/service-recommendations/posture-and-investigation.md#identity-analysis-context) |
| SG/NACL or endpoint boundaries | [Compare effective permissions with required flows](references/service-recommendations/network-protection.md#flow-boundaries-and-endpoints) |
| TGW, Cloud WAN or Lattice segmentation | [Verify connectivity and identity separately](references/service-recommendations/network-protection.md#segmentation-and-identity) |
| DNS filtering effectiveness | [Establish the actual query path](references/service-recommendations/network-protection.md#dns-path-and-enforcement) |
| Shield Advanced or Firewall Manager | [Justify DDoS or fleet-management value](references/service-recommendations/network-protection.md#ddos-and-fleet-policy) |
| Network Firewall routing, order or defaults | [Compare intended inspection with actual paths](references/service-recommendations/network-firewall.md#routed-inspection-and-policy) |
| Network Firewall TLS | [Resolve content need and client compatibility](references/service-recommendations/network-firewall.md#tls-eligibility-and-trust) |
| Network Firewall Proxy | [Check explicit client path and current eligibility](references/service-recommendations/network-firewall.md#proxy-suitability) |
| Network Firewall verdicts, streams or logs | [Distinguish configuration from enforcement](references/service-recommendations/network-firewall.md#verdicts-and-operational-evidence) |
| Web endpoint association or origin bypass | [Establish where filtering applies](references/service-recommendations/web-protection.md#endpoint-coverage-and-bypass) |
| Existing WAF or application abuse | [Select controls from observed harm and compatibility](references/service-recommendations/web-protection.md#rules-and-application-abuse) |
| WAF order, labels or logs | [Validate evaluation and retained evidence](references/service-recommendations/web-protection.md#evaluation-and-evidence-limits) |
| Certificate renewal or monitoring | [Resolve issuance and existing monitoring adequacy](references/service-recommendations/certificates.md#renewal-and-monitoring) |
| Private PKI hierarchy | [Require root-isolation and issuing evidence](references/service-recommendations/certificates.md#trust-domains-and-root-isolation) |
| CA sharing, revocation, connectors or export | [Match issuer boundaries and client needs](references/service-recommendations/certificates.md#sharing-and-client-compatibility) |
| Certificate Transparency or dated PKI claims | [Check disclosure and current-source limits](references/service-recommendations/certificates.md#disclosure-and-source-limits) |
| Public/private AppSec assessment | [Establish application assurance and authorized scope](references/service-recommendations/application-security.md#application-fit-and-scope) |
| Private AppSec target | [Resolve target and dependency reachability](references/service-recommendations/application-security.md#private-connectivity) |
| AppSec authentication, permissions or data | [Check identity and data readiness](references/service-recommendations/application-security.md#identity-and-data-readiness) |
| Existing AppSec test results | [Limit conclusions to evidenced tested paths](references/service-recommendations/application-security.md#interpreting-existing-results) |
