# IAM Permissions

Every permission in this skill is read-only. No pass requires a write action, and the
skill must not perform one.

## Pass 1 — Inventory

| Domain | Actions |
|---|---|
| Compute | `ec2:DescribeInstances`, `ec2:DescribeVolumes`, `ssm:DescribeInstanceInformation`, `lambda:ListFunctions` |
| AI workloads | `bedrock:GetModelInvocationLoggingConfiguration`, `bedrock:ListCustomModels`, `bedrock:ListAgents`, `bedrock-agentcore:ListAgentRuntimes`, `sagemaker:ListEndpoints` |
| Containers | `ecr:DescribeRepositories`, `ecs:ListClusters`, `ecs:ListServices`, `ecs:DescribeServices`, `ecs:DescribeCapacityProviders`, `ecs:ListTasks`, `ecs:DescribeTasks`, `eks:ListClusters`, `eks:DescribeCluster`, `eks:ListFargateProfiles`, `eks:ListNodegroups` |
| Data | `s3:ListAllMyBuckets`, `s3:GetBucketLocation`, `rds:DescribeDBClusters`, `rds:DescribeDBInstances`, `backup:ListBackupVaults` |
| Network | `cloudfront:ListDistributions`, `elasticloadbalancing:DescribeLoadBalancers`, `apigateway:GET`, `wafv2:GetWebACLForResource`, `ec2:DescribeVpcs`, `ec2:DescribeFlowLogs`, `ec2:DescribeSubnets` |
| Certificates | `acm:ListCertificates`, `acm:DescribeCertificate`, `acm-pca:ListCertificateAuthorities` |
| Logging | `cloudtrail:DescribeTrails`, `cloudtrail:GetEventSelectors` |
| Org | `organizations:DescribeOrganization`, `organizations:ListAccounts`, `organizations:ListDelegatedAdministrators`, `account:ListRegions` |

## Pass 2 — Enablement checks

| Service | Actions |
|---|---|
| GuardDuty | `guardduty:ListDetectors`, `guardduty:GetDetector`, `guardduty:ListCoverage`, `guardduty:ListOrganizationAdminAccounts`, `guardduty:DescribeOrganizationConfiguration`, `guardduty:ListMembers`, `guardduty:ListMalwareProtectionPlans` |
| Security Hub | `securityhub:DescribeHub`, `securityhub:GetEnabledStandards`, `securityhub:DescribeStandards`, `securityhub:ListFindingAggregators`, `securityhub:GetFindingAggregator`, `securityhub:ListConfigurationPolicies`, `securityhub:ListOrganizationAdminAccounts`, `securityhub:DescribeOrganizationConfiguration`, `securityhub:ListMembers` |
| Inspector | `inspector2:BatchGetAccountStatus`, `inspector2:ListCoverage`, `inspector2:GetConfiguration`, `inspector2:GetEc2DeepInspectionConfiguration`, `inspector2:ListDelegatedAdminAccounts`, `inspector2:DescribeOrganizationConfiguration`, `inspector2:ListMembers` |
| Macie | `macie2:GetMacieSession`, `macie2:GetAutomatedDiscoveryConfiguration`, `macie2:GetClassificationExportConfiguration`, `macie2:GetFindingsPublicationConfiguration`, `macie2:ListOrganizationAdminAccounts`, `macie2:DescribeOrganizationConfiguration`, `macie2:ListMembers` |
| Detective | `detective:ListGraphs`, `detective:ListOrganizationAdminAccount`, `detective:DescribeOrganizationConfiguration`, `detective:ListMembers` |
| Security Lake | `securitylake:ListDataLakes`, `securitylake:GetDataLakeSources`, `securitylake:ListLogSources`, `securitylake:GetDataLakeOrganizationConfiguration`, `securitylake:GetDataLakeExceptionSubscription` |
| Access Analyzer | `accessanalyzer:ListAnalyzers`, `accessanalyzer:ListFindings` |
| Config | `config:DescribeConfigurationRecorders`, `config:DescribeConfigurationRecorderStatus`, `config:DescribeDeliveryChannels`, `config:DescribeConfigurationAggregators` |
| Security Hub (unified) | `securityhub:DescribeSecurityHubV2`, `securityhub:ListAggregatorsV2` |
| Security IR | `security-ir:ListMemberships`, `security-ir:GetMembership`, `security-ir:ListCases` (`organizations:ListDelegatedAdministrators` is covered under Org) |
| ACM / expiry routing | `acm:ListCertificates`, `acm:DescribeCertificate`, `acm:GetAccountConfiguration`, `acm-pca:ListCertificateAuthorities`, `events:ListRules`, `events:ListTargetsByRule` |
| Network Firewall | `network-firewall:ListFirewalls`, `network-firewall:DescribeFirewall`, `network-firewall:DescribeLoggingConfiguration`, `network-firewall:DescribeFirewallPolicy` |
| DNS Firewall | `route53resolver:ListFirewallRuleGroupAssociations`, `route53resolver:ListFirewallRuleGroups`, `route53resolver:GetFirewallConfig`, `route53resolver:ListResolverQueryLogConfigs`, `route53resolver:ListResolverQueryLogConfigAssociations` |
| Firewall Manager | `fms:GetAdminAccount`, `fms:ListPolicies` |

These are IAM action names, resolved per operation from the Service Authorization Reference. Most match the
operation name; some do not, for example `detective:ListOrganizationAdminAccount` for the
`ListOrganizationAdminAccounts` operation. The Security Hub V2 exceptions are listed in [Security Hub](references/security-hub.md).

Identity confirmation uses `sts:GetCallerIdentity`. Optional simulation uses
`iam:SimulatePrincipalPolicy`; it is not required for the assessment. Request only the
reads selected for the workflow; `apigateway:GET` includes REST API stage reads.

## Diagnosing gaps

`AccessDenied` and "not enabled" are different answers, and several of these APIs return
the same error for both. Distinguish them before reporting:

```bash
aws iam simulate-principal-policy \
  --policy-source-arn <resolved-iam-user-or-role-arn> \
  --action-names macie2:GetMacieSession \
  --query 'EvaluationResults[].EvalDecision'
```

Resolve an IAM user/role ARN before optional simulation; do not pass an STS assumed-role
session ARN. If identity cannot be resolved, skip simulation. An `allowed` decision does
not prove live authorization or service disablement. Ambiguous failures remain UNKNOWN;
retain documented, validated not-enabled responses as negative evidence.

## Managed policies

`SecurityAudit` and `ViewOnlyAccess` cover most of the above. Neither is complete for
this skill — `SecurityAudit` omits some newer `inspector2` and `securitylake` read
actions. Verify with `simulate-principal-policy` rather than assuming coverage.

Admin/FullAccess policies grant more than this assessment needs. For an accepted
recommendation, hand off implementation separately for operation-specific least-privilege
permission design. Do not provide write commands or expand this assessment's permissions;
do not use admin policies as a default.

## Organization scope

Permission availability does not authorize enumeration. `ListAccounts`, service member
reads, and per-member reconciliation require an explicit request for detailed account-level
information. Otherwise prefer counts/statistics and mark unrequested detail NOT ASSESSED.

Member accounts cannot read `describe-organization-configuration` for these services. Run
pass 2's org checks from the delegated administrator account, or the management account to
identify who the delegated admins are. From a member account, report the scope limitation
explicitly rather than presenting single-account results as organization-wide.

## Focused evidence and scoped coverage

The [matrix](references/service-recommendations/recommendation-matrix.md) adds focused customer-evidence paths, not blanket new permissions.
Existing `inspector2:ListCoverage` and `guardduty:ListCoverage` authorize reads whose API
requests must still use the account predicates in [enablement checks](references/service-recommendations/enablement-checks.md).
An allowed IAM result or delegated-admin role does not widen the approved collection scope.
Verify exact new action/resource permissions separately before any future read is added;
manual configuration excerpts do not justify granting provisioning or scan permissions.
