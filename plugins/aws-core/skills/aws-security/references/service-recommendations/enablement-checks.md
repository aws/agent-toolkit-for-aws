# Pass 2 — Security Service Enablement Checks

All commands are read-only. Run relevant sections in the assessed scope, reusing complete
observations. External-access analyzers need regional evidence; unused-access findings do
not vary by region. Preserve evidence states as defined in ../service-recommendations.md, including validated
not-enabled responses. Parent-service enablement does not prove effective workload coverage.
If a pass condition has no available read evidence, report it UNKNOWN or seek focused manual
evidence; do not invent a check or label it passed. Apply the parent Skill's encryption,
destination-policy and notification-recipient requirements to every logging, export,
notification, publishing, trail and delivery-channel destination below. Record KMS, TLS,
resource-policy, recipient, retention and successful-delivery evidence separately; any
unverified control remains UNKNOWN.

Only with an explicit request for detailed account-level enumeration, reconcile complete
member IDs/status with scoped ACTIVE IDs from inventory, following all pages. Broad
coverage audits or service recommendations alone do not authorize member enumeration.
Prefer available statistics/counts; mark unrequested detail NOT ASSESSED. Apply this gate
to every member read below and any Security Lake per-member source checks or account-bearing
source listings. Do not run unbounded source listings for org-wide member discovery.
Missing permissions/pages in authorized reads leave the remainder UNKNOWN. Membership and
central-policy association are separate evidence; listing policies proves neither coverage
nor successful application.

## Contents

- [Amazon GuardDuty](#amazon-guardduty)
- [AWS Security Hub CSPM](#aws-security-hub-cspm)
- [AWS Security Hub (unified)](#aws-security-hub-unified)
- [AWS Certificate Manager](#aws-certificate-manager)
- [AWS Network Firewall](#aws-network-firewall)
- [Route 53 Resolver DNS Firewall](#route-53-resolver-dns-firewall)
- [AWS Firewall Manager](#aws-firewall-manager)
- [Account-scoped coverage interpretation](#account-scoped-coverage-interpretation)
- [Amazon Inspector](#amazon-inspector)
- [Amazon Macie](#amazon-macie)
- [Amazon Detective](#amazon-detective)
- [Amazon Security Lake](#amazon-security-lake)
- [AWS Security Incident Response](#aws-security-incident-response)
- [IAM Access Analyzer](#iam-access-analyzer)
- [AWS Config](#aws-config)
- [Summary table to produce](#summary-table-to-produce)

## Amazon GuardDuty

```bash
# Detector presence. Empty list = not enabled in this region.
aws guardduty list-detectors --region <region>

# Per-feature status. Checking the detector alone is not sufficient — protection plans
# are individually toggled.
aws guardduty get-detector --detector-id <id> --region <region>
```

`get-detector` returns `Features[]` with a `Name` and `Status` per plan.

`Features[]` also includes the foundational sources `CLOUD_TRAIL`, `DNS_LOGS`, and
`FLOW_LOGS`. These are always `ENABLED` on an active detector and are not protection plans;
they cannot be toggled, so do not report them as gaps. VPC flow and DNS analysis are still
metered per GB; apply the parent workflow cost rules.

Discover the current optional protection-plan names and covered resource/service set from
`get-detector` `Features[]` and the current GuardDuty documentation. Report every returned
feature name, including new or unrecognized names, and mark supported-but-unreturned
completeness UNKNOWN if current documentation cannot be read. The rows below are
applicability examples, not a closed feature catalog:

| Feature example | Covers | Applies when inventory shows |
|---|---|---|
| `S3_DATA_EVENTS` | CloudTrail S3 data events | Any S3 bucket |
| `EKS_AUDIT_LOGS` | EKS audit logs | Any EKS cluster |
| `EBS_MALWARE_PROTECTION` | EBS volume malware scanning | EC2 instances with EBS volumes |
| `RDS_LOGIN_EVENTS` | Supported RDS / Aurora login activity | Engine/version and prerequisites verified against the current [supported-database table](https://docs.aws.amazon.com/guardduty/latest/ug/rds-protection.html#rds-pro-supported-db); unresolved eligibility is UNKNOWN |
| `LAMBDA_NETWORK_LOGS` | Lambda network activity | Any Lambda function |
| `RUNTIME_MONITORING` | EC2, ECS, EKS runtime | EC2, ECS, or EKS on EC2 |
| `EKS_RUNTIME_MONITORING` | EKS runtime (superseded by `RUNTIME_MONITORING`) | EKS on EC2 |
| `AI_PROTECTION` | AI workload activity documented as covered by GuardDuty; confirm the latest covered services and event types before assessing it | Any documented covered AI service in use; unresolved service eligibility is UNKNOWN |
| `AI_ANALYST` | GuardDuty Investigation, AI-powered finding analysis. Check its preview status, console name, and Region eligibility in the GuardDuty documentation before proposing it | Optional; requires an active detector in the same Region |

Runtime Monitoring has an `AdditionalConfiguration` array for agent management:
`EC2_AGENT_MANAGEMENT`, `ECS_FARGATE_AGENT_MANAGEMENT`, `EKS_ADDON_MANAGEMENT`. The guide
recommends letting GuardDuty manage agents so new resources are covered automatically.

```bash
# Runtime Monitoring agent coverage — enabled but uncovered is a silent gap.
# Returns null Resources when RUNTIME_MONITORING is DISABLED; that is expected,
# not an error. Check the feature status first and skip this call if disabled.
aws guardduty list-coverage --detector-id <id> --region <region> \
  --filter-criteria '{"FilterCriterion":[{"CriterionKey":"ACCOUNT_ID","FilterCondition":{"Equals":["<caller-account-id>"]}}]}' \
  --query 'Resources[].{Account:AccountId,Resource:ResourceId,Type:ResourceDetails.ResourceType,Status:CoverageStatus,Issue:Issue}'

# S3 Malware Protection plans — enabled per bucket, not per detector. Malware Protection
# for AWS Backup has no read API; confirm it in the console.
aws guardduty list-malware-protection-plans --region <region>

# Organization posture. Both calls raise BadRequestException / InvalidInputException
# from a non-admin account — see Troubleshooting in ../service-recommendations.md.
aws guardduty list-organization-admin-accounts --region <region>
aws guardduty describe-organization-configuration --detector-id <id> --region <region>
# ONLY when detailed account-level enumeration is explicitly requested.
aws guardduty list-members --detector-id <id> --only-associated false \
  --query 'Members[].{Id:AccountId,Status:RelationshipStatus}' --region <region>
```

`describe-organization-configuration` returns `AutoEnableOrganizationMembers` with values
`NEW`, `ALL`, or `NONE`. `ALL` covers existing and new accounts and is what the guide's
reference Terraform uses; the guide itself presents the three options without ranking them,
so this skill's pass condition of `ALL` is its own design. `NEW` leaves existing accounts
uncovered; `NONE` means manual management.

**Pass conditions:** detector exists; every feature whose triggering resource is present
is `ENABLED`; `AutoEnableOrganizationMembers` is `ALL` in an org; finding publishing
frequency tightened from the 6-hour default (15 minutes if Detective is in use; AWS states
that changing this setting has no effect on the cost of using GuardDuty, a statement scoped
to `FindingPublishingFrequency` alone and not to any consumer's own charges); S3 Malware
Protection plans exist for the buckets identified as taking untrusted uploads.

## AWS Security Hub CSPM

```bash
# Not enabled raises ResourceNotFoundException
aws securityhub describe-hub --region <region>

# Which standards are on. FSBP is the baseline; layer others per requirement.
aws securityhub get-enabled-standards --region <region>

# Cross-region aggregation
aws securityhub list-finding-aggregators --region <region>
aws securityhub get-finding-aggregator --finding-aggregator-arn <arn> --region <region>

# Central configuration — preferred over per-account setup
aws securityhub list-configuration-policies --region <region>

# Organization posture
aws securityhub list-organization-admin-accounts --region <region>
aws securityhub describe-organization-configuration --region <region>
# ONLY when detailed account-level enumeration is explicitly requested.
aws securityhub list-members --no-only-associated \
  --query 'Members[].{Id:AccountId,Status:MemberStatus}' --region <region>
```

Standard names, versions and ARNs change as AWS adds and retires them: read the current set
with `aws securityhub describe-standards` and name only versions that call returns. New adopters
should start at the latest version of a benchmark. The PCI SSC's retirement of PCI DSS v3.2.1
(external context, not guide-sourced) is why in-scope orgs need the current PCI DSS version.
NIST SP 800-171 applies to CUI handling. The AI Security Best Practices standard and the AWS
Resource Tagging Standard are also offered; confirm availability from `describe-standards`.

**Pass conditions:** hub enabled; FSBP enabled at minimum; a finding aggregator exists if
more than one region is in use; central configuration policy in place for orgs; a
customer-managed AWS Config recorder present **only if CSPM runs standalone** (see AWS
Config below).

## AWS Security Hub (unified)

Distinct from CSPM. The older product was rebranded Security Hub CSPM; the unified Security
Hub is a platform that correlates GuardDuty, Inspector, Macie, and CSPM signals
into exposure findings and attack paths. Both can be enabled at once, and both live in the
`securityhub` API namespace — the unified service uses the `*V2` operations.

```bash
# Unified Security Hub. ResourceNotFoundException / ResourceConflictException = not enabled.
aws securityhub describe-security-hub-v2 --region <region>

# Unified aggregation
aws securityhub list-aggregators-v2 --region <region>
```

**Cross-cutting finding:** if unified Security Hub is enabled **and** CSPM is still
ingesting AWS service or third-party findings that Security Hub already aggregates, you may
be paying for the same aggregation twice. The guide's lever is disabling that finding
ingestion in CSPM, not removing the cross-region finding aggregator, which central
configuration requires. Before recommending it, the guide is explicit that you must audit
EventBridge rules, SIEM feeds, ticketing workflows, and custom Lambda functions and confirm
each reads from Security Hub, because disabling ingestion without checking dependencies
"breaks alerting quietly". Keep Macie publishing to CSPM: that is how sensitive-data traits
reach Security Hub exposure scoring.

Verify current plans, pricing and inclusion using the parent cost-review rules.

**Policies vs deployments:** Organizations policies exist for Security Hub and Inspector
and auto-apply to new accounts, preventing drift. GuardDuty and CSPM use one-time
deployments that cannot be viewed or edited and do **not** cover newly enabled accounts —
so GuardDuty and locally configured CSPM still need auto-enable for new members. Under
CSPM central configuration, false/NONE auto-enable fields are expected; verify policy
association/application and member coverage separately, or report them UNKNOWN.

**Pass conditions:** enabled in the delegated admin's home region; no duplicate finding
ingestion in CSPM once consumers are confirmed on Security Hub; Threat Analytics considered
for production accounts.

## AWS Certificate Manager

ACM is always available rather than something you enable, so the checks here are
monitoring and configuration hygiene.

```bash
# Certificate inventory across the current documented ACM key-type set. Read the current
# ListCertificates Includes keyTypes values from ACM documentation and substitute all of them
# below. If that set cannot be read, an unfiltered call is partial evidence only: ACM's default
# key-type filter can omit whole certificate classes, including EC and non-default RSA types.
# Report returned certificates, but treat non-default key types as potentially present and
# unenumerated; monitoring coverage and fleet completeness remain UNKNOWN.
aws acm list-certificates \
  --includes keyTypes=<comma-separated-current-key-types> \
  --query 'CertificateSummaryList[].{Arn:CertificateArn,Domain:DomainName,Status:Status,NotAfter:NotAfter,InUse:InUse,Type:Type}' \
  --region <region>

# Expiry notification window. ACM emits daily EventBridge events starting
# DaysBeforeExpiry out (check the allowed range and default in the ACM documentation).
aws acm get-account-configuration --region <region>

# Per-certificate detail — renewal eligibility and Certificate Transparency preference
aws acm describe-certificate --certificate-arn <arn> \
  --query 'Certificate.{Arn:CertificateArn,Type:Type,Status:Status,RenewalEligibility:RenewalEligibility,RenewalStatus:RenewalSummary.RenewalStatus,Validation:DomainValidationOptions[].ValidationMethod,Options:Options,InUseBy:InUseBy,NotBefore:NotBefore,NotAfter:NotAfter}' \
  --region <region>

# Inspect default-bus expiry rules and selected SNS target ARNs, without target payloads
aws events list-rules --event-bus-name default \
  --query 'Rules[].{Name:Name,State:State,EventPattern:EventPattern}' --region <region>
aws events list-targets-by-rule --rule <rule-name> --event-bus-name default \
  --query 'Targets[].{Id:Id,Arn:Arn}' --region <region>

# Private CA
aws acm-pca list-certificate-authorities \
  --query 'CertificateAuthorities[].{Arn:Arn,Type:Type,Status:Status}' --region <region>
```

**Pass conditions:** the chosen monitoring method demonstrates coverage of the relevant
certificate estate, successful notification delivery and adequate renewal lead time
(see the [matrix](references/service-recommendations/recommendation-matrix.md#triggered-by-certificates)). Accept adequate CloudWatch expiry alarms or scheduled
issuer-side checks; missing EventBridge/SNS routing alone is not a gap. Where an unmet
need is demonstrated and ACM event applicability is verified, EventBridge expiry routing
is an option: inspect the enabled rule's `aws.acm` source and "ACM Certificate Approaching
Expiration" detail-type, relevant certificate scope and notification target. If the target is
SNS, require KMS encryption at rest and TLS in transit for publication and subscriber access,
apply the parent topic-policy and authorized-recipient requirements, and verify successful
delivery separately. Rule/target existence proves configuration, not delivery. Missing
monitoring, destination-protection or delivery evidence stays UNKNOWN, not absent protection.
Prefer DNS validation where applicable.

ACM-requested public and private certificates may qualify for managed renewal: inspect
`RenewalEligibility`, available `RenewalSummary` status, and the issuance/management path.
`Type` or eligibility alone does not prove successful renewal. Imported certificates and
certificates issued directly through Private CA `IssueCertificate` need separate renewal
handling. Do not assume ACM expiry events for direct issuance: verify ACM representation
and documented event applicability; otherwise require issuer/deployment-side expiration
monitoring and report monitoring UNKNOWN. Missing issuance history needs manual confirmation.

**Notes:** Inspect actual `NotBefore`/`NotAfter` dates, certificate type, and current
issuer/service documentation, including [ACM certificate characteristics](https://docs.aws.amazon.com/acm/latest/userguide/acm-certificate-characteristics.html).
Do not assume public, private, and imported certificates share one validity period; missing
dates remain UNKNOWN. CloudFront
certificates must be issued in `us-east-1` regardless of the distribution's origin region.
Certificate Transparency logging cannot be toggled from the console, cannot change once
the renewal period starts (confirm the current window in the ACM managed-renewal
documentation), and failures there are silent.

## AWS Network Firewall

These reads establish presence, logging and policy settings. `list-firewalls`,
`describe-firewall` and `describe-logging-configuration` cover the firewall resource itself;
policy-level settings (stateless/stateful rule groups, default actions, rule order) live on the
policy, not on the firewall, and are read with `describe-firewall-policy`. Continue with the selected
[network suitability guidance](references/service-recommendations/recommendation-matrix.md#focused-suitability-beyond-enablement) for deployment, HOME_NET/rule
applicability, TLS/trust suitability using focused evidence. Do not author or
execute Suricata rules, mutation recipes, scans or analyses. Configuration alone does not
prove symmetric routing, enforcement or client compatibility.

```bash
aws network-firewall list-firewalls --region <region>
aws network-firewall describe-firewall --firewall-name <name> --region <region>
aws network-firewall describe-logging-configuration --firewall-name <name> --region <region>
# Policy-level settings live on the policy, not the firewall
aws network-firewall describe-firewall-policy --firewall-policy-arn <arn> --region <region>
```

**Assessment conditions:** first establish the actual deployment mode, intended traffic
paths and compatible policy strategy (see the [matrix](references/service-recommendations/recommendation-matrix.md#focused-suitability-beyond-enablement)). Assess endpoint/AZ coverage against that topology;
do not apply an inspection-VPC rule universally to native TGW or multi-endpoint designs.
Record observed rule order, stateless forwarding, default actions and logging destinations
separately from evidence of effective blocking and log delivery. Any recommended ALERT/FLOW
destination MUST use KMS encryption at rest for its CloudWatch Logs log group or S3 sink and
TLS in transit for delivery and consumer access. Verify encryption, transport, retention and
delivery separately; destination configuration alone proves none of them. Evaluate strict order,
application-aware versus custom defaults and required ALERT/FLOW visibility in that
context; do not require every drop default to have a paired alert default. Unresolved
topology, intent, compatibility or effectiveness remains UNKNOWN rather than a gap.

Assess `StreamExceptionPolicy` against application recovery requirements and existing
connection/idle-flow evidence. Recommend a change only
for a demonstrated incompatibility, with owner-reviewed planned impact and validation;
do not assert a universal firewall restart or change requirement.

## Route 53 Resolver DNS Firewall

```bash
# Rule group to VPC associations — an unassociated rule group protects nothing
aws route53resolver list-firewall-rule-group-associations \
  --query 'FirewallRuleGroupAssociations[].{Vpc:VpcId,Status:Status,Priority:Priority}' \
  --region <region>

aws route53resolver list-firewall-rule-groups --region <region>

# Per-VPC fail-open setting (own design, not guide-sourced; report it, do not fail on it)
aws route53resolver get-firewall-config --resource-id <vpc-id> --region <region>

# Query logging — required for DNS threat hunting
aws route53resolver list-resolver-query-log-configs --region <region>
aws route53resolver list-resolver-query-log-config-associations \
  --query 'ResolverQueryLogConfigAssociations[].{Vpc:ResourceId,Config:ResolverQueryLogConfigId,Status:Status,Error:Error}' \
  --region <region>
```

**Pass conditions:** at least one rule group associated with each VPC; AWS-managed domain
lists attached as the first layer; DNS Firewall Advanced enabled for DNS tunneling and
domain-generation-algorithm detection; query-log association `CREATED` for the actual VPC;
and its CloudWatch Logs log group or S3 sink uses KMS encryption at rest and TLS in transit
for delivery and consumer access, with a deliberate retention policy. A query-log
configuration alone does not prove VPC coverage, encryption, transport, retention or delivery;
missing evidence for any of those remains UNKNOWN.

DNS Firewall is the earliest filter in the chain — blocking at the DNS layer stops traffic
before it reaches Network Firewall, which reduces downstream processing cost.

## AWS Firewall Manager

Relevant for distributed deployments: 10 or more accounts with per-account or per-VPC WAF,
DNS Firewall, or Network Firewall that need policy rollout and enforcement as accounts and
VPCs are added. Requires AWS Organizations and AWS Config; verify current pricing/bundling.
It adds limited value to a centralized single-firewall design.

```bash
# ResourceNotFoundException = no FMS administrator designated
# The FMS default administrator is an organization-wide setting; query it in us-east-1
aws fms get-admin-account --region us-east-1
# Policies are Regional: list them in each Region in scope (CloudFront policies live in us-east-1)
aws fms list-policies --region <region>
```

**Pass conditions:** an FMS administrator account exists if the org has 10 or more accounts
with distributed firewall deployments; not required for a centralized design.

## Account-scoped coverage interpretation

For both coverage examples, substitute only the account established by caller identity,
not an account discovered through admin visibility. For an explicitly approved multi-account
set, run bounded per-account predicates and label each scope. Follow CLI auto-pagination;
no max-items/no-paginate for completeness claims. Retain successful pages and mark a failed
remainder UNKNOWN. Coverage rows are scan/coverage records, not unique workload counts.
The projections retain identifiers for scoped reconciliation; mask them in reports.
GuardDuty's resource type is nested under `ResourceDetails.ResourceType`. Inspector's
account predicate is `filterCriteria.accountId` with `comparison: EQUALS`. A client-side
projection/filter does not constrain collection. Do not use unfiltered GuardDuty coverage
statistics from a delegated administrator as evidence about the caller account; if a
verified scoped statistics request is unavailable, use the filtered list or mark UNKNOWN.

## Amazon Inspector

```bash
# Per-scan-type activation status
aws inspector2 batch-get-account-status --region <region>

# Coverage — which resources are actually being scanned
aws inspector2 list-coverage --region <region> \
  --filter-criteria '{"accountId":[{"comparison":"EQUALS","value":"<caller-account-id>"}]}' \
  --query 'coveredResources[].{Account:accountId,Resource:resourceId,Type:resourceType,ScanType:scanType,Status:scanStatus}'

# Organization posture
aws inspector2 list-delegated-admin-accounts --region <region>
aws inspector2 describe-organization-configuration --region <region>
# ONLY when detailed account-level enumeration is explicitly requested.
aws inspector2 list-members --no-only-associated \
  --query 'members[].{Id:accountId,Status:relationshipStatus}' --region <region>
```

`batch-get-account-status` returns `resourceState` entries for scan types in the reviewed
account and Region. Use the current Amazon Inspector documentation as the source of truth for
supported scan types, compare that documented set with the returned states, and report every
returned scan type including new or unrecognized names. The API response is account status,
not a complete supported-type catalog. If current documentation cannot be read, mark
supported-scan-type completeness UNKNOWN rather than comparing against a remembered list.

`LAMBDA` and `LAMBDA_CODE` are separate toggles and the guide says both should be on —
`LAMBDA` covers package vulnerabilities, `LAMBDA_CODE` covers custom application code.

`CODE_REPOSITORY` is Inspector Code Security (repository SAST, SCA, and IaC scanning).
A confirmed repository or CI/CD use case selects the [matrix guidance](references/service-recommendations/recommendation-matrix.md#focused-suitability-beyond-enablement),
with focused integration/language/gate evidence and an AppSec handoff. Account inventory
alone neither triggers this recommendation nor establishes absence of repositories.

```bash
# ECR rescan duration and EC2 scan mode.
# Returns ecrConfiguration.rescanDurationState and ec2Configuration.scanModeState.
aws inspector2 get-configuration --region <region>

# Deep Inspection is a separate API, not part of get-configuration.
# Returns status, packagePaths (up to 5 per account), orgPackagePaths (up to 5 more).
aws inspector2 get-ec2-deep-inspection-configuration --region <region>
```

Use the current Amazon Inspector API documentation as the source of truth for allowed ECR
rescan-duration values. Report the observed `rescanDurationState` value and compare it with
current documented options; if the documentation cannot be read, mark option-set
completeness UNKNOWN rather than comparing against a remembered list.

**Pass conditions:** every scan type with corresponding resources is `ENABLED`;
`autoEnable` covers new member accounts; EC2 scanning on Enhanced EC2 Scanning (the VM
Scanner), with a legacy SSM-plugin setup flagged as a migration finding; Deep Inspection on
for supported platforms with Enhanced EC2 Scanning, after confirming the latest
platform set in Amazon Inspector documentation, and custom paths reviewed against where
software is actually installed; ECR rescan durations match build cadence (a cost lever only
for standalone Inspector).

## Amazon Macie

```bash
# Not enabled returns AccessDeniedException stating "Macie is not enabled" (match the
# substring; list-findings adds a trailing period). A denial without a not-enabled
# message is UNKNOWN, not not-enabled.
aws macie2 get-macie-session --region <region>

# Automated discovery is the guide's default recommendation over discovery jobs
aws macie2 get-automated-discovery-configuration --region <region>

# Discovery results repository — Macie keeps results only for a limited period (confirm the
# current retention in the Macie documentation), so configure it early
aws macie2 get-classification-export-configuration --region <region>

# Findings publication — by default only policy findings go to Security Hub CSPM
aws macie2 get-findings-publication-configuration --region <region>

# Organization posture
aws macie2 list-organization-admin-accounts --region <region>
aws macie2 describe-organization-configuration --region <region>
# ONLY when detailed account-level enumeration is explicitly requested.
aws macie2 list-members --only-associated false \
  --query 'members[].{Id:accountId,Status:relationshipStatus}' --region <region>
```

**Pass conditions:** session `ENABLED`; automated sensitive data discovery `ENABLED`;
classification export configured to an S3 bucket that uses KMS encryption at rest and TLS in
transit for delivery and consumer access, with retention and successful delivery verified
separately;
`securityHubConfiguration.publishClassificationFindings` is `true` (the guide calls
publishing sensitive data findings its highest-value configuration change, because Security
Hub exposure scoring and GuardDuty attack sequences use the sensitive-data trait);
`autoEnable` on for new org accounts.

**Coverage limits:** Macie monitors general purpose buckets per account up to a documented
ceiling, and coverage stops once that ceiling is reached. The limit changes, so confirm the
current value from the Macie quotas documentation rather than relying on a fixed number.
Buckets whose policy carries an explicit deny need the Macie service-linked role allowed
before they can be scanned; the resource coverage page lists them.

## Amazon Detective

```bash
# Empty list = this account administers no behavior graph in this Region. Alone that is UNKNOWN (a member
# account of an active graph also gets an empty list); it is NOT ENABLED only when the caller is
# verified as the Detective delegated administrator (list-organization-admin-accounts below)
aws detective list-graphs --region <region>

aws detective list-organization-admin-accounts --region <region>
aws detective describe-organization-configuration --graph-arn <arn> --region <region>
# ONLY when detailed account-level enumeration is explicitly requested.
aws detective list-members --graph-arn <arn> \
  --query 'MemberDetails[].{Id:AccountId,Status:Status}' --region <region>
```

**Eligibility:** GuardDuty is **not** a prerequisite. The current
[Detective prerequisites](https://docs.aws.amazon.com/detective/latest/userguide/detective-prerequisites.html)
are the required IAM permissions and a recent AWS CLI version (confirm the current minimum from the Detective prerequisites documentation); the pinned guide's
prerequisite claim is superseded. GuardDuty's actual relationship is a recommendation to
align the administrator account across GuardDuty, Security Hub CSPM and Detective so the
finding pivot and the archive-from-Detective integration work. Do not recommend enabling
GuardDuty solely to satisfy a prerequisite gate.

**Pass conditions:** graph exists; auto-enable on; administrator account aligned with
GuardDuty and Security Hub CSPM where those are in use; GuardDuty finding publishing
frequency set to 15 minutes (the 6-hour default delays recurring-finding updates in
Detective by up to 6 hours; AWS states that changing this setting has no effect on the cost
of using GuardDuty, which says nothing about Detective's own charges); source packages for
AWS security findings and EKS audit logs enabled — older deployments must turn these on
manually; where Security Lake is also in use, the Detective integration lets investigators
pull the underlying logs with a pre-built Athena query. Source:
[Detective recommendations](https://docs.aws.amazon.com/detective/latest/userguide/detective-recommendations.html).

**Quota:** a behavior graph has a maximum number of member accounts; confirm the current
value in the Amazon Detective quotas documentation before relying on it.

## Amazon Security Lake

```bash
aws securitylake list-data-lakes --regions <region>
# get-data-lake-sources filters by account, not region, and returns no source version
aws securitylake get-data-lake-sources --accounts <account-id>
# The only read here that returns sourceVersion, under sources[].sources[].awsLogSource
aws securitylake list-log-sources --regions <region>
aws securitylake get-data-lake-organization-configuration
aws securitylake get-data-lake-exception-subscription
```

Use the current Amazon Security Lake documentation as the source of truth for supported
`AwsLogSourceName` values, default-source behavior and regional availability. Prefer AWS MCP
documentation search/read when available; otherwise use the official Security Lake
documentation over HTTPS. Do not treat source names shown elsewhere in this Skill as a closed
catalog. Compare that current documented set with `get-data-lake-sources` status and
`list-log-sources` configured inventory. Report every returned source name, including new or
unrecognized names. If current documentation cannot be read, mark supported-source and
default-source completeness UNKNOWN rather than comparing against a remembered list.

Each AWS source also carries a `sourceVersion`, which matches `latest` or an `N.N` value
such as `2.0`. Security Lake ingests the latest version by default. Record the observed
`sourceVersion` per source, account and region instead of requiring a particular value: a
newer version is not automatically safe for current consumers, and selecting a version
requires a matching subscriber update before those consumers can read it. Custom sources
carry no `sourceVersion`, so mark that NOT APPLICABLE, not UNKNOWN. Do not confuse the
field value with OCSF table or S3 prefix naming such as `vpc_flow_2_0`, which cannot appear
in this field.

**Prerequisite:** `CLOUD_TRAIL_MGMT` collection requires an existing multi-region
organization trail capturing read and write management events. Verify log file validation,
KMS encryption at rest and TLS in transit for the trail's S3 destination and any CloudWatch
Logs delivery, with retention and successful delivery assessed separately.

**Delegated admin placement:** the Log Archive account, not the security tooling account
used by the other five services.

**Pass conditions:** data lake exists; every source in the current documented default set is
enabled where available and applicable; new-account collection enabled; the observed
`sourceVersion` recorded for each enabled source, with any subscriber update the selected
version still needs identified; if rollup regions are configured, contributing-region
retention matches verified investigation and recovery needs. If the current default set could
not be read, its completeness check is UNKNOWN.

## AWS Security Incident Response

Downstream of detection: it ingests and triages threat detection findings that GuardDuty and
Security Hub produce. It triages threat detection findings only — security posture and
compliance findings (misconfiguration alerts, benchmark violations) are not triaged, because
they describe a state in the environment, not an active threat. It is not a detection service,
generates no findings of its own, and never substitutes for them. Enabling
GuardDuty or Security Hub CSPM first is strongly recommended but is not required to
activate it, so absent detection coverage is a separate finding, not a blocked prerequisite.

```bash
# Membership ID and status. Run from the delegated administrator account.
aws security-ir list-memberships

# Full membership detail, including account scope and the incident response team
aws security-ir get-membership --membership-id <membership-id>

# Case inventory. Apply the parent sensitive-data rules: summarize status counts and mask
# case IDs and titles by default; case content is incident data, not configuration.
aws security-ir list-cases

# Delegated administrator registration for the service
aws organizations list-delegated-administrators \
  --service-principal security-ir.amazonaws.com
```

**Pass conditions:** membership status `Active` (`Pending` means onboarding is incomplete);
account scope covers the intended organizational units; at least two incident response team
members configured, which the service requires; the registered Region matches where the
assessed workloads run. Coverage is selected at organization or OU level, not per account,
and every account in a selected OU including child OUs is covered. A membership existing is
not account coverage: only accounts enrolled in the membership are monitored, so reconcile
the covered OUs against the assessed scope before calling coverage complete. Findings
created before onboarding are not ingested retroactively.

**Cost note:** charges are metered on findings ingested, and AWS documents a monthly
free-tier allowance plus inclusion for some support tiers. Free-tier counts and inclusion
terms change, so do not state a specific figure here: report cost UNKNOWN pending verified
ingestion volume and the account's support tier, and read the current free-tier allowance,
inclusion terms and per-finding rate from AWS pricing. No rate is recorded here.

## IAM Access Analyzer

```bash
# External-access analyzers cover supported resources in their region
aws accessanalyzer list-analyzers --region <region>
aws accessanalyzer list-findings --analyzer-arn <arn> --region <region>
```

Use the current IAM Access Analyzer documentation as the source of truth for supported
analyzer types and their scope. Treat `list-analyzers` as configured inventory rather than a
complete supported-type catalog, and report every returned `type`, including new or
unrecognized values. Compare current documented external-, unused- and internal-access
analyzer capabilities with the configured inventory. If current documentation cannot be read,
mark supported-type completeness UNKNOWN rather than comparing against a remembered list.

These are distinct analyzers, not one analyzer with modes. An account can have an
unused-access analyzer and still have no external-access analyzer — check the `type`
field rather than treating any active analyzer as coverage. Security Hub may create an
unused-access analyzer automatically (named `_AccessAnalyzerForSecurityHub*`), which is
why "an analyzer exists" is not sufficient evidence of external-access coverage.

**Pass conditions:** a current documented external-access analyzer type is configured for
each relevant region; a current documented unused-access analyzer type is configured when
the organization reviews unused permissions, without duplicating organization-wide coverage
per region. Verify internal-access scope separately before judging coverage.

## AWS Config

Check this only when Security Hub CSPM runs **standalone**. When unified Security Hub and
CSPM are both enabled, CSPM creates and manages the service-linked recorder
`AWSConfigurationRecorderForSecurityHubCSPM` in each account and region, keeps its scope
aligned to the controls, does not use your customer-managed recorder, and `Config.1` always
passes. In that state a missing customer-managed recorder or delivery channel is not a gap.

```bash
aws configservice describe-configuration-recorders --region <region>
aws configservice describe-configuration-recorder-status --region <region>
aws configservice describe-delivery-channels --region <region>
aws configservice describe-configuration-aggregators --region <region>
```

**Pass conditions (standalone CSPM):** recorder exists, `recording` is `true`, and `lastStatus`
is `SUCCESS`; delivery channel configured, with KMS encryption at rest and TLS in transit for
its S3 destination and any SNS topic, plus the parent destination-policy and recipient checks;
retention and successful delivery verified separately; recording group covers the resource
types the enabled standards evaluate; global resources recorded in one region only (the guide's
duplication-avoidance practice). The guide's standalone cost levers: record global resources in
one region, turn
off the compliance history timeline if Config serves only CSPM, and be cautious scoping the
recorder down, since new controls arrive regularly. Whichever recorder is in play, CSPM emits
`WARNING` findings for controls whose resource type is not being recorded; treat those as the
safety net.

## Summary table to produce

Summarize relationships/counts with masked identifiers unless detail was explicitly
requested. Projections are not disclosure permission; apply parent raw-output and
sensitive-field exclusions. Unrequested member detail is NOT ASSESSED.

| Service | State / evidence limits | Plans / standards on | Plans / standards off | Delegated admin | Auto-enable |
|---|---|---|---|---|---|
| GuardDuty | | | | | |
| Security Hub (unified) | | | | | |
| Security Hub CSPM | | | | | |
| Inspector | | | | | |
| Macie | | | | | |
| Detective | | | | | |
| Security Lake | | | | | |
| Security Incident Response | | | | | n/a (OU scope) |
| IAM Access Analyzer | | | | n/a | n/a |
| AWS Config | | | | | |
| ACM | always on | | | n/a | n/a |
| Network Firewall | | | | n/a | n/a |
| DNS Firewall | | | | n/a | n/a |
| Firewall Manager | | | | | n/a |
