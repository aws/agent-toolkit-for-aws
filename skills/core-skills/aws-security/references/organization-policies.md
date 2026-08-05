# Organization Policies

## Overview

AWS Organizations supports service-specific policy types for centralized configuration enforcement across member accounts. Multiple security services use this mechanism, each with its own policy type. Organization policies allow administrators to define and enforce service configurations from the management account or delegated administrator, ensuring consistent security posture across the organization.

## Available Policy Types

| Policy Type | Service | Documentation |
|---|---|---|
| `SECURITYHUB_POLICY` | Security Hub | https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_security_hub.html |
| `INSPECTOR_POLICY` | Inspector | https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_inspector.html |

## Common Discovery Pattern

The same CLI pattern applies to all policy types — substitute the appropriate `POLICY_TYPE` value:

```bash
# List policies of a given type
aws organizations list-policies --filter <POLICY_TYPE>

# Get policy document details
aws organizations describe-policy --policy-id <id>

# Check which roots, OUs, or accounts a policy targets
aws organizations list-targets-for-policy --policy-id <id>
```

These are `organizations` namespace APIs — not service-specific APIs like `securityhub` or `inspector2`.

> **Execution environment:** The AWS MCP server is recommended for running these API calls but is not required — standard AWS CLI access is sufficient.

## Read-Only APIs

| API | Purpose |
|-----|---------|
| `organizations:ListPolicies` | List policies by type |
| `organizations:DescribePolicy` | Get policy document and metadata |
| `organizations:ListTargetsForPolicy` | List OUs/accounts a policy applies to |
| `organizations:ListPoliciesForTarget` | List policies applied to a specific OU/account |

## Operator Prerequisites

Organization policy APIs are `organizations` namespace APIs. Access requires one of:

- A role in the Organizations **management account** with `organizations:List*` and `organizations:Describe*` permissions, OR
- A role in a **delegated administrator** account where the management account has configured the delegation policy to grant Organization policy API access to the service's delegated administrator. The standard service onboarding flow configures this delegation.

If `list-policies` returns `AccessDeniedException`, the current role lacks Organizations access. This typically means either:

- The account is not the management account or delegated administrator
- The delegation policy has not been configured to grant these permissions

Report policy status as `Not checked - Organizations access unavailable` and continue with service-specific checks that do not require Organizations permissions.

## Output Sensitivity

Policy documents may reveal organizational structure (OU hierarchy, account assignments), security configuration enforcement rules, and service-specific settings applied across the organization. Present policy summary first; offer full policy document JSON on request.
