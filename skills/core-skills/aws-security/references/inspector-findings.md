# Summarizing Inspector Findings

## Overview

Produces structured summaries of Amazon Inspector findings — severity distribution, finding type breakdown, and affected resources. Does NOT perform remediation prioritization or patching recommendations.

Works from both standalone accounts and delegated administrator accounts.

## Classify the Request

| User intent | Workflow |
|---|---|
| Summarize my Inspector findings | A: Account Findings Summary |
| What vulnerabilities does Inspector see | A: Account Findings Summary |
| Show vulnerability posture across org | B: Organization Findings Overview |
| Which accounts have most critical vulns | B: Organization Findings Overview |

## Workflow A: Account Findings Summary

1. Get aggregated counts by severity:

   ```bash
   aws inspector2 list-finding-aggregations --aggregation-type ACCOUNT
   ```

2. Get aggregated counts by finding type:

   ```bash
   aws inspector2 list-finding-aggregations --aggregation-type FINDING_TYPE
   ```

3. Get aggregated counts by resource type:

   ```bash
   aws inspector2 list-finding-aggregations --aggregation-type AWS_EC2_INSTANCE
   aws inspector2 list-finding-aggregations --aggregation-type AWS_LAMBDA_FUNCTION
   aws inspector2 list-finding-aggregations --aggregation-type AWS_ECR_CONTAINER
   ```

4. For ECR context, aggregate by repository:

   ```bash
   aws inspector2 list-finding-aggregations --aggregation-type REPOSITORY
   ```

5. For EC2 context, aggregate by AMI:

   ```bash
   aws inspector2 list-finding-aggregations --aggregation-type AMI
   ```

6. Present summary:

   | Severity | Count |
   |---|---|
   | Critical | N |
   | High | N |
   | Medium | N |
   | Low | N |

   | Finding Type | Count | Highest Severity |
   |---|---|---|
   | PACKAGE_VULNERABILITY | N | CRITICAL |
   | CODE_VULNERABILITY | N | HIGH |
   | NETWORK_REACHABILITY | N | MEDIUM |

   | Resource Type | Count | Critical+High |
   |---|---|---|
   | AWS_EC2_INSTANCE | N | N |
   | AWS_ECR_CONTAINER_IMAGE | N | N |
   | AWS_LAMBDA_FUNCTION | N | N |

   SHOULD include top 5 AMIs/repositories/functions by finding count when relevant.

## Workflow B: Organization Findings Overview

1. Aggregate by account:

   ```bash
   aws inspector2 list-finding-aggregations --aggregation-type ACCOUNT
   ```

2. Present per-account summary:

   | Account ID | Critical | High | Medium | Low | Total |
   |---|---|---|---|---|---|
   | 111111111111 | N | N | N | N | N |

   MUST identify the top 5 accounts by critical+high findings count.

3. Get overall finding type distribution:

   ```bash
   aws inspector2 list-finding-aggregations --aggregation-type FINDING_TYPE
   ```

## Constraints

- MUST use list-finding-aggregations for counts (not list-findings + manual counting)
- MUST NOT perform remediation prioritization or patching recommendations
- MUST NOT make suppression or exception recommendations
- SHOULD present accounts sorted by critical+high count descending
- MUST paginate aggregation results if response includes nextToken

## Troubleshooting

| Symptom | Resolution |
|---|---|
| list-finding-aggregations returns empty | No active findings — report zero findings |
| Only sees own account | Not a delegated admin — note: single-account view only |
| ACCOUNT aggregation shows one entry | Standalone account — use Workflow A |

## Output Sensitivity

Finding aggregations contain EC2 instance IDs, AMI IDs, ECR repository names, Lambda function ARNs, package names with CVE identifiers, and CVSS scores. Present the severity/type aggregation table first. Display full finding details only when the caller explicitly requests raw output.
