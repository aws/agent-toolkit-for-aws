# Template Safety Guidance

- [Cross-Stack Reference Safety](#cross-stack-reference-safety)
- [Conditional Resource Coupling](#conditional-resource-coupling)
- [Security Group Blast Radius](#security-group-blast-radius)
- [DeletionPolicy Preservation for Stateful
  Resources](#deletionpolicy-preservation-for-stateful-resources)
- [Parameter Propagation for New
  Resources](#parameter-propagation-for-new-resources)
- [Template Size Limits](#template-size-limits)

## Cross-Stack Reference Safety

**Never rename or remove an exported Output without checking for Fn::ImportValue
consumers.**

When a template has `Outputs` with `Export.Name`, other stacks may depend on
that export via `Fn::ImportValue`. Renaming or removing the export will cause
immediate deployment failures in all consuming stacks.

Before modifying any exported output:

1. Check `Metadata."com.aws.cloudformation.Context"` for documented consumers
2. If no context exists, warn the user that downstream stacks may break
3. If proceeding with a rename, update the `com.aws.cloudformation.Context`
   context to reflect the new export name
4. Recommend coordinating the rename with all importing stacks (deploy consumers
   first with the new name, then rename the export)

**Key principle:** Exported outputs are a public API contract. Treat renames as
breaking changes.

## Conditional Resource Coupling

**Resources sharing a Condition form an atomic feature toggle group.**

When multiple resources use the same `Condition`, they are intentionally coupled
— they must all be created or none created. Removing the Condition from one
resource in the group breaks the atomicity.

Before modifying or removing a Condition from a resource:

1. Check `Metadata."com.aws.cloudformation.Context"` for feature toggle group
   documentation
2. Identify all other resources that share the same Condition
3. Warn the user that breaking the coupling may cause deployment failures (e.g.,
   a resource created without its required subnet group or security group)
4. If the user intends to break the coupling, recommend removing the Condition
   from ALL resources in the group, or explain why selective removal is safe

## Security Group Blast Radius

**Assess the blast radius before modifying shared security groups.**

A single security group may be referenced by EC2 instances, RDS databases,
Lambda VPC configs, and other resources. Adding an ingress rule affects ALL
resources using that group.

Before modifying a security group:

1. Check `Metadata."com.aws.cloudformation.Context"` for documented references
   and blast radius
2. Enumerate which resources use the security group
3. Warn the user about the full impact (e.g., "opening port 443 from 0.0.0.0/0
   will also expose the RDS instance, not just the web server")
4. Recommend creating a separate, scoped security group if the ingress rule
   should only apply to a subset of resources

**Key principle:** Public ingress (0.0.0.0/0) on a shared security group is
almost always wrong — it exposes databases and internal services, not just the
intended target.

## DeletionPolicy Preservation for Stateful Resources

**Never remove or downgrade a DeletionPolicy on stateful resources without
explicit user confirmation.**

Resources with `DeletionPolicy: Retain` (DynamoDB tables, RDS instances, S3
buckets) contain data that cannot be recreated. When asked to remove such a
resource:

1. Check `Metadata."com.aws.cloudformation.Context"` for data criticality
   documentation
2. Warn about data loss risk — even with Retain, removing from the template
   orphans the resource from CloudFormation management
3. Confirm the user understands: the physical resource survives (Retain), but it
   is no longer managed by the stack
4. If removing, update the template Description and remaining resources'
   `com.aws.cloudformation.Context` context to document the orphaned resource
5. Never change DeletionPolicy from Retain to Delete without explicit user
   confirmation and documented backup verification

**Key principle:** `DeletionPolicy: Retain` exists for a reason. Respect it,
document it, and warn loudly before any operation that could result in data
loss.

## Parameter Propagation for New Resources

**When adding resources to a template with naming conventions, propagate
existing parameters.**

Many templates use Parameters (e.g., `Environment`, `Project`, `Team`) to drive
resource naming for multi-environment deployment. New resources must follow the
same convention.

When adding a resource to a template with parameterized names:

1. Check `Metadata."com.aws.cloudformation.Context"` for naming convention
   documentation
2. Examine existing resources for naming patterns (e.g., `!Sub
   "${Environment}-..."`)
3. Apply the same pattern to the new resource's name
4. Add `Metadata."com.aws.cloudformation.Context"` to the new resource,
   documenting its purpose and constraints
5. If the template has a documented convention (e.g., "all resources must use
   Environment prefix"), follow it even if not explicitly requested

**Key principle:** Consistency in naming enables multi-environment deployment. A
resource that breaks the naming convention becomes an obstacle to promotion
across environments.

## Template Size Limits

**Check the template body size before adding resources to an already-large
template.** CloudFormation enforces hard limits: a template body passed inline
(`TemplateBody`) is capped at 51,200 bytes, a template uploaded via S3
(`TemplateURL`) at 1,048,576 bytes (1 MB), and any single template at 500
resources. A template that already carries many resources or rich
`Metadata."com.aws.cloudformation.Context"` may be close to these limits, so the
addition you are about to make may not fit.

Service Quotas reports the current values for two of these — `Template Size`
(1 MB) and `Template Resources` (500), both non-adjustable — and also
`Template Description Length` (1,024 bytes), which the persist procedure
relies on. The 51,200-byte inline `TemplateBody` cap is not published as a
service quota; take it from the [CloudFormation quotas
documentation][cloudformation-quotas]. When the margin matters, confirm with:

```shell
aws service-quotas list-service-quotas --service-code cloudformation \
  --query "Quotas[?starts_with(QuotaName, 'Template')].[QuotaName,Value,Unit]"
```

[cloudformation-quotas]: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/cloudformation-limits.html

When adding or modifying resources — especially in a large template:

1. Measure the current template body size in bytes (e.g., `wc -c <template>` on
   Unix/macOS or Git Bash, or `(Get-Item <template>).Length` in PowerShell) and
   compare it against the 1,048,576-byte limit; note the remaining headroom and
   the resource count against the 500 cap.
2. Estimate the size of what you are about to add, INCLUDING the
   `Metadata."com.aws.cloudformation.Context"` you are required to attach. If
   the addition would push the template over the limit, do NOT blindly append.
3. When headroom is tight, intelligently adjust context to fit rather than
   dropping it:
   - Condense and consolidate verbose existing
     `Metadata."com.aws.cloudformation.Context"` (collapse long `why`/rationale
     prose into terse caveman shorthand; keep `must` constraints intact).
   - Prioritize the highest-value context and write concise context for the new
     resources.
4. If condensing is not enough, split the stack: move a cohesive group of
   resources into a nested stack (`AWS::CloudFormation::Stack`) or a
   CloudFormation module, or relocate bulky static content (e.g., large inline
   code) to S3. Preserve `Metadata."com.aws.cloudformation.Context"` on the
   extracted resources.
5. Never silently drop required context or exceed the limit — a template over
   the limit fails at `CreateStack`/`UpdateStack` (e.g., "Template body is too
   long" / "Template format error: number of resources exceeds maximum").

**Key principle:** Context is mandatory, but so is staying under the size limit.
When both cannot fit, *intelligently adjust* existing and new context (condense,
prioritize, or relocate) — never choose between blindly adding and dropping
context.
