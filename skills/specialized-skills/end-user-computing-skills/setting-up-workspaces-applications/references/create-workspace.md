# Create / Update / Tear Down an Agent Environment

An agent environment = a WorkSpaces Applications **fleet** + a **stack with `AgentAccessConfig`** + their association. This file is the provisioning verb; the values come from the resolved configuration produced by onboarding-flow.md + fleet-stack-recommendations.md. Expose **one create verb and one update verb** at the environment level — the user reasons about "the agent's environment," not about fleets vs stacks vs associations.

## Pre-create checks (gate before any mutation)

1. **Look for an earlier setup first.** Before writing the plan, describe each resource it would create, by name: `describe-image-builders`, `describe-images --names`, `describe-fleets --names`, `describe-stacks --names`, `list-associated-fleets`, and the scaling target. If the user says they're continuing an earlier setup and the names aren't known yet, list the Region's fleets, stacks and image builders and ask which are theirs. If nothing exists, continue. Otherwise, follow "Coming back to a partial setup" below.
2. **Confirm the plan.** Show the resolved configuration (or run dry-run, below) and get explicit user confirmation — creation is mutating and billable.
3. **Resolve networking.** Do not assume a default VPC exists — many accounts have none. Discover usable networking first:

   ```bash
   aws ec2 describe-vpcs
   aws ec2 describe-subnets --filters Name=vpc-id,Values=<vpc-id>
   ```

   Pick defaults yourself and present them in the plan — don't ask the user to supply IDs: prefer the default VPC if one exists (otherwise the VPC whose subnets have internet routing), choose two subnets in different Availability Zones, and use the VPC's default security group, for `VpcConfig={SubnetIds:[...],SecurityGroupIds:[...]}`. Label them in the plan ("using your default VPC, subnets in us-east-1a/1b, default security group — say the word to use different ones") so a technical user can substitute their own IDs and everyone else just confirms. The default security group allows all outbound traffic; for anything beyond a trial, recommend a security group that allows only the egress the workflow needs (creating it is the account admin's call). Only if the account has no VPC/subnets at all: stop and explain that network creation is an admin-owned prerequisite — do not create network infrastructure silently. For a non-production trial, an existing non-default VPC is fine if the agent's outbound destinations are reachable from it. **Internet access:** either set `EnableDefaultInternetAccess: true` (simple, per-instance public routing) or leave it off and rely on the subnets' NAT gateway (the production-typical pattern) — pick whichever the account's network already supports; if home folders or application settings persistence are enabled, an S3 gateway endpoint keeps that traffic off the internet path (screenshot uploads don't need it: the managed MCP service writes them, not the fleet). **If a read call is denied** (`UnauthorizedOperation` from EC2, `AccessDeniedException` from other services), name the missing action in one line, for example `ec2:DescribeVpcs`, and ask the user for the value it would have found (here the VPC and two subnet IDs in different Availability Zones). Don't guess it, and continue with the other checks. **If the workflow reaches the internet** (web mail like Gmail/Outlook.com, SaaS apps, package downloads), the fleet has no outbound internet by default and must have it enabled explicitly: set `EnableDefaultInternetAccess: true` on `CreateFleet` (Elastic IP on public subnets, capped at 100 instances), or use a NAT gateway for production/scale. Infer this from the workflow description (email, browsers, SaaS, downloads all imply it) and default it accordingly in the plan; if the destinations are genuinely unclear, ask during the workflow questions — not as an end-of-flow open item.
4. **Resolve the image.** Reference an existing or public base image by `ImageName`/`ImageArn`. If the environment summary's requirements need custom applications, build the image first via [image-setup.md](references/image-setup.md) — do not proceed as if it exists.
5. **Block only on true blockers.** Proceed on chosen defaults once the user confirms the plan. Stop only for items that cannot be defaulted — no VPC exists, or domain join is required — and explain each in plain language rather than listing bare TODOs.

## Coming back to a partial setup

List what exists: each resource by name and type, its state, and whether it bills now (a `RUNNING` fleet or image builder does). Then ask, as a numbered question with no default: "1) Finish this setup  2) Start a new one with different names  3) Exit". This picks a direction and approves nothing. A reply that hands the choice back ("use your recommendation") or an empty reply gets the same question again, however many times it comes.

To finish it:

- **Read the earlier answers back** from what exists: the builder's instance type and image, the fleet's type, instance type, image, view and timeouts, the scaling target's min and max, and the stack's `AgentAccessConfig`. Ask only for what you can't recover.
- **Plan only the missing steps** and show them as a full plan, the same as a new setup's: what will be created, started or changed, the account and Region, the network, the defaults, when billing starts and the pricing link, then the go-ahead question. Nothing is created, started or changed until the user approves that plan. For example: a builder with no image means installing and capturing; an `AVAILABLE` image with its builder still running means stopping the builder; a fleet with no stack, or a stack whose create failed, means the stack and the association.
- **Never create a second resource for the same purpose.** Reuse what exists, and converge on `ResourceAlreadyExistsException`.
- **Stopping or deleting anything is its own confirmed step,** even a builder left running.

## Plan first (read-only review)

Before any mutating call: run the pre-create checks, then present a plan the user can actually digest — not a wall of CLI commands. The plan is for informed consent, not a code review. One screenful, shaped like:

- **What gets created:** fleet + stack `<name>`, associated and started, with auto scaling (min/max) — in `<account>` / `<region>`. Add the screenshot bucket and its policy when the user chose a new bucket, or the policy change when they brought one.
- **Network:** the defaults chosen (VPC, subnets, security group, internet access on/off) with the one-line "say the word to change any of these."
- **The choices that matter:** fleet type, instance type, image, session cap — each with its one-line rationale (the environment summary already covered the rest; don't repeat it all).
- **Billing:** when charges start (fleet start) and what scale-to-zero means for idle cost, with a link to the [pricing page](https://aws.amazon.com/workspaces/applications/pricing/).

Don't print the CLI command sequence as part of the plan — most clients show each command for approval at execution time anyway, so the detail is available exactly when it's actionable. If the user asks to see the commands up front, show them.

Get explicit confirmation before executing. Nothing is provisioned or billed until approved. This is the concrete form of SKILL.md's default-to-read-only principle.

## Executing (you run the calls)

There is no bundled script — compose and run the AWS CLI/SDK calls yourself from the sequence below. Rules that make this reliable:

- **One step at a time, announced first.** Run the sequence as separate commands, never one chained invocation — a chain hides which step failed and gives the user no sense of progress. Before each step, say in one line what it does and the typical duration, then run it and report the result. Rough durations to set expectations: create fleet / create stack / associate — seconds each; start fleet to RUNNING — several minutes (the long pole); auto scaling registration — seconds.
- **Converge on re-runs.** Creates take no idempotency token: on `ResourceAlreadyExistsException`, describe the resource and continue rather than failing. Back off on `ConcurrentModificationException` / `ResourceInUseException`.
- **Don't block, narrate.** The fleet takes minutes to reach `RUNNING`. Issue the create/associate/start calls, then poll in short calls and report each state so the user sees steady progress instead of a silent wait:

  ```bash
  aws appstream describe-fleets --names <name> \
    --query "Fleets[0].{State:State,Available:ComputeCapacityStatus.Available}" --region <region>
  ```

  Poll ~15s apart ("fleet is STARTING... still STARTING... now RUNNING with 1 instance available") until `State: RUNNING` **and** `ComputeCapacityStatus.Available > 0`. RUNNING alone does not mean a session can be served.
- **Adapt to API errors.** If a call is rejected — an unknown field on an older CLI/SDK, a constraint violation, an instance type not offered in a subnet's AZ — read the error, apply the matching fix from [troubleshooting.md](references/troubleshooting.md), and continue the sequence from where it failed.

## Create

Before step 1, set up the screenshot bucket if the user chose one at Q10: create it with its policy, or add the policy statement to their existing bucket, as in [agent-access-config.md](references/agent-access-config.md). The stack names the bucket, and `CreateStack` checks that it exists in this account and Region and that the service can list it.

1. **Create the fleet** — `CreateFleet` with the resolved `FleetType` (`ALWAYS_ON`/`ON_DEMAND`), `InstanceType`, `ImageName` or `ImageArn` (do not pass `Platform`: it applies only to Elastic fleets, and Always-On and On-Demand fleets reject it and take the OS from the image), `VpcConfig`, `RootVolumeConfig` (its only field is `VolumeSizeInGb`), **`StreamView: DESKTOP`** for agents / the chosen view for humans (set explicitly — the API default is `APP`), the session timeouts (idle 900; disconnect 900 for agents and humans — the API minimum is 60, 0 is rejected; max duration defaulted per fleet-stack-recommendations.md, and it must be greater than the idle timeout — when the cap is ≤ 900s, set idle to 0), initial `ComputeCapacity.DesiredInstances` from expected concurrency, `DisableIMDSV1: true`, `IamRoleArn` if the workflow calls AWS APIs (see fleet-stack-recommendations.md), and `Tags` identifying the workflow (e.g. `workflow=invoice-reconciliation`) for cost attribution — apply the same tags to the stack and image. (Domain-joined fleets are outside this guided flow — route to the docs.)
2. **Create the stack** — `CreateStack`. For agent environments: include the resolved `AgentAccessConfig` (see fleet-stack-recommendations.md § Default policy set, and [agent-access-config.md](references/agent-access-config.md) for the fields and the screenshot bucket). For human environments: **no `AgentAccessConfig`**; application settings persistence off for the POC shape.
3. **Associate** — `AssociateFleet` (stack must exist before association).
4. **Start and poll to ready** — `StartFleet`, then poll `DescribeFleets` until `State: RUNNING` **and** `ComputeCapacityStatus.Available > 0`. RUNNING alone does not mean a session can be served.
5. **Grant access** — agents: nothing to create now. The UserIds come from the plan ([user-access.md](references/user-access.md)), and the agent gets its session when it connects, through the `amazon-workspaces-agent-access` skill. Humans: create user-pool users and associate them with the stack (welcome emails go out), in [user-access.md](references/user-access.md).
6. **Apply auto scaling** — separate from `CreateFleet`, via Application Auto Scaling:

   ```bash
   aws application-autoscaling register-scalable-target \
     --service-namespace appstream \
     --resource-id fleet/<fleet-name> \
     --scalable-dimension appstream:fleet:DesiredCapacity \
     --min-capacity <min> --max-capacity <max>
   # then put-scaling-policy (target-tracking or step) against the same resource-id/dimension
   ```

**Idempotency and ordering:** AppStream create operations take no idempotency token. Make creates safe to retry by keying on the unique resource `Name`: on `ResourceAlreadyExistsException`, describe the resource and converge instead of failing. Back off and retry on `ConcurrentModificationException` and `ResourceInUseException`. Poll long-running transitions (fleet → RUNNING); don't block.

**After create:** for agent environments, hand off to the `amazon-workspaces-agent-access` skill to connect an agent and drive the desktop. Give it the stack name, the fleet name, the Region and the planned UserIds. If the Agent Access server is in your own MCP config, it connected before the fleet was ready, so reconnect it, or ask the user to, before using it. For human environments, users sign in via the welcome-email portal link (user-access.md).

**Watch what you built:** fleets emit CloudWatch metrics in the `AWS/AppStream` namespace — capacity utilization and insufficient-capacity signals are the feedback loop for the scaling values this flow recommended. Suggest an alarm on insufficient-capacity errors and a periodic look at utilization to right-size min/max. Account-level usage reports (session details to S3) can be enabled with `create-usage-report-subscription` if the team wants per-session records. The reports go to the same service-managed S3 bucket as session-script logs, encrypted in transit and at rest; they hold user and session details, so limit read access to that bucket.

## Update

Most settings change in place — no rebuild:

- **Stack / agent access:** `aws appstream update-stack --name <stack> --agent-access-config '{...}'` — partial updates supported; remove agent access with `--attributes-to-delete AGENT_ACCESS_CONFIG`. Changes apply to **new** sessions; running sessions keep their launch settings. Image builders take the same configuration through `update-image-builder` while stopped ([agent-access-config.md](references/agent-access-config.md)).
- **Fleet:** `UpdateFleet` for instance type, timeouts, capacity, image. Some attribute changes require the fleet **STOPPED** first (stop → update → start) — surface the interruption to the user before doing it.
- **Scaling:** adjust the Application Auto Scaling min/max/policy on the registered target.
- **One-way doors to call out before applying:** the resource `Name` (immutable — only `DisplayName` changes) and GPU vs non-GPU instance family (image compatibility).

## Teardown

**Confirm before destroying.** A teardown request ("clean up", "delete the environment") starts a confirmation exchange, it doesn't authorize one. First describe the resources to verify what actually exists, then show the user the exact list — each resource by name, type, region, and account — state that deletion is permanent, and wait for an explicit yes to that list before running anything. Then proceed one announced step at a time, like create.

Reverse order, tolerant of already-deleted resources:

```
StopFleet → wait STOPPED → DisassociateFleet → DeleteFleet → DeleteStack
```

For human environments, disassociate user-pool users from the stack first (`batch-disassociate-user-stack`); delete users only if they're not associated with other stacks. Deregister the Application Auto Scaling target, and verify nothing billable is orphaned (running fleets, unattached stacks, image builders left running). Do not delete network resources the flow did not create. If the flow created an installer role for an image builder ([image-setup.md](references/image-setup.md), Installer sources) and the builder is gone, list the role for deletion too. The screenshot bucket stays unless the user asks to delete it ([agent-access-config.md](references/agent-access-config.md), At teardown).

## Boundaries

- **Installs and capture happen inside the builder** — [image-setup.md](references/image-setup.md) launches the builder, and an agent connected through agent access or the user in a browser session does the installs and capture.
- **Enterprise network and identity** (VPC/subnet/security-group creation, Active Directory) — admin-owned; this verb consumes `VpcConfig` if resolvable and otherwise stops at the pre-create check.
- **Connecting to and driving the desktop or an image builder, and how forwarded MCP tools appear to the agent** — the `amazon-workspaces-agent-access` skill.
