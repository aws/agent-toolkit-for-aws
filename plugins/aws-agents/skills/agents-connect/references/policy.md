# policy

Control what your AgentCore agent can do — restrict tool calls, enforce business rules, and protect sensitive operations.

## When to use

- You want to restrict which tools your agent can call
- You want to enforce business rules (e.g., refunds only under $500)
- You want role-based access control on agent actions
- You want an emergency kill switch for specific tools
- A policy is denying requests you expect to allow (or allowing what you expect to deny)

## Input

`$ARGUMENTS` is optional:

```
/policy                     # interactive — asks what you want to restrict
/policy generate            # generate Cedar from natural language
/policy debug               # diagnose why a policy is allowing/denying
/policy emergency           # generate an emergency shutdown policy
```

## How AgentCore policy works

AgentCore Policy enforces Cedar-based authorization rules at the **gateway boundary** — before any tool call reaches its target. Every tool call is evaluated against your policies in real time.

**Default behavior:** Without a policy engine attached to your gateway, all tool calls are allowed. Once you attach a policy engine, the default is **deny** — you must write explicit `permit` policies for everything you want to allow.

**Key concepts:**

- **Policy engine** — the container for your policies, attached to a gateway
- **Policy** — a Cedar rule that permits or forbids specific actions
- **`forbid` overrides `permit`** — if any forbid policy matches, the action is denied regardless of permit policies

---

## Process

### Step 1: Read the project

Read `agentcore/agentcore.json` to understand:

- What gateways exist (in the `agentCoreGateways` array)
- Whether a policy engine is already configured (in the `policyEngines` array)

### Step 2: Understand the goal

Ask (or infer from `$ARGUMENTS`):

> "What do you want to control?
>
> 1. Restrict a tool based on input values (e.g., amount < $500)
> 2. Role-based access (only certain users can call certain tools)
> 3. Block a specific tool entirely
> 4. Emergency shutdown — disable all tools immediately
> 5. Debug why a policy is allowing or denying unexpectedly"

---

## Path A: Set up a policy engine

### Step A1: Create the policy engine

```bash
# Create and attach to an existing gateway
agentcore add policy-engine \
  --name MyPolicyEngine \
  --attach-to-gateways MyGateway \
  --attach-mode LOG_ONLY
```

**Start with `LOG_ONLY` mode** — policies are evaluated and logged but not enforced. This lets you verify your policies work correctly before enabling enforcement.

Switch to `ENFORCE` when ready:

```bash
# Update an existing gateway
agentcore add gateway \
  --name MyGateway \
  --policy-engine MyPolicyEngine \
  --policy-engine-mode ENFORCE
```

(The same `--policy-engine` and `--policy-engine-mode` flags work at gateway creation time too.)

### Step A2: Deploy to activate

```bash
agentcore deploy -y
```

---

## Path B: Write Cedar policies

> [!WARNING]
> Cedar policies that reference a specific gateway ARN in the `resource` field require
> the gateway to be deployed first. You cannot add a policy with a gateway ARN before
> the gateway exists in AWS.
>
> Two-phase deployment:
>
> 1. Deploy the gateway first: `agentcore deploy -y`
> 2. Get the gateway ARN: `agentcore status --type gateway --json`
> 3. Add the policy with the real ARN, then deploy again
>
> The `-g` / `--generate` flag also requires a deployed gateway — it calls an AWS API
> that needs the gateway ARN to convert natural language into Cedar. If you run
> `-g` before deploying the gateway, it will fail.

### Option 1: Natural language generation (easiest)

**Requires the gateway to be deployed first** — the CLI calls an API that needs the gateway ARN.

```bash
# Deploy the gateway first
agentcore deploy -y

# Then generate the policy (--gateway tells the CLI which deployed gateway to use)
agentcore add policy \
  --name refund_policy \
  --engine MyPolicyEngine \
  -g "Allow users with the refund-agent role to process refunds when the amount is less than 500" \
  --gateway MyGateway
```

The CLI generates Cedar from your description, resolves the gateway ARN automatically, and validates the result. Review the generated policy before deploying.

**Policy name rules:** letters, numbers, underscores only — **no hyphens**. `refund-policy` fails; `refund_policy` works.

### Option 2: Write Cedar directly

Save to a `.cedar` file and register. If the policy references a gateway ARN in the `resource` field, you need the ARN from a prior deploy:

```bash
# Get the gateway ARN after deploying
agentcore status --type gateway --json | jq -r '.gateways[0].arn'

# Update your .cedar file with the real ARN, then add the policy
agentcore add policy \
  --name refund_policy \
  --engine MyPolicyEngine \
  --source policy.cedar
```

### Cedar syntax reference

**Action name format:** `AgentCore::Action::"TargetName___tool_name"` — three underscores between target name and tool name. This is the most common Cedar mistake.

```cedar
// TargetName is the gateway target name (from agentcore add gateway-target --name)
// tool_name is the tool name within that target
AgentCore::Action::"RefundTarget___process_refund"
//                              ^^^
//                         three underscores
```

**Principal types:**

- `AgentCore::OAuthUser` — authenticated user via OAuth/JWT
- `AgentCore::IamEntity` — IAM-authenticated caller (when gateway uses AWS_IAM auth). The `id` attribute contains the full IAM ARN.

**Resource format:**

```cedar
AgentCore::Gateway::"arn:aws:bedrock-agentcore:<REGION>:<YOUR_ACCOUNT_ID>:gateway/<GATEWAY_ID>"
```

Get your gateway ARN: `agentcore status --type gateway --json | jq -r '.gateways[0].arn'`

### Common policy patterns

**Amount-based restriction:**

```cedar
permit(
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"RefundTarget___process_refund",
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/my-gateway-id"
)
when {
  principal.hasTag("role") &&
  principal.getTag("role") == "refund-agent" &&
  context.input.amount < 500
};
```

**Role-based access (OAuth user):**

```cedar
permit(
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"AdminTarget___delete_record",
  resource == AgentCore::Gateway::"arn:..."
)
when {
  principal.hasTag("role") &&
  ["admin", "superuser"].contains(principal.getTag("role"))
};
```

**Account-based access (IAM entity):**

```cedar
permit(
  principal is AgentCore::IamEntity,
  action == AgentCore::Action::"AdminTarget___delete_record",
  resource == AgentCore::Gateway::"arn:..."
)
when {
  principal.id like "arn:aws:iam::123456789012:*"
};
```

**Block a specific tool entirely:**

```cedar
forbid(
  principal,
  action == AgentCore::Action::"PaymentTarget___transfer_funds",
  resource == AgentCore::Gateway::"arn:..."
);
```

**Emergency shutdown — disable all tools:**

```cedar
forbid(principal, action, resource);
```

**Required field validation:**

```cedar
forbid(
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"InsuranceTarget___file_claim",
  resource == AgentCore::Gateway::"arn:..."
)
unless {
  context.input has description &&
  context.input has priority
};
```

### Critical Cedar rules

**Always use `hasTag()` before `getTag()`:**

```cedar
// ❌ Wrong — throws error if tag doesn't exist
when { principal.getTag("role") == "admin" }

// ✅ Correct — check existence first
when {
  principal.hasTag("role") &&
  principal.getTag("role") == "admin"
}
```

**Default deny:** Once a policy engine is attached in ENFORCE mode, everything is denied unless a `permit` policy matches. Write explicit permits for every action you want to allow.

**`forbid` always wins:** A `forbid` policy overrides any `permit` policy. Use this for emergency shutdowns and hard blocks.

---

## Path C: Test policies before enforcing

### LOG_ONLY mode

In LOG_ONLY mode, all requests are allowed but policy decisions are logged to CloudWatch. Use this to verify your policies before switching to ENFORCE.

```bash
# Check policy decision logs
agentcore logs --runtime MyAgent --since 1h --query "policy"
```

Look for log entries showing `ALLOW` or `DENY` decisions for each tool call.

### Validate policy syntax

```bash
agentcore add policy \
  --name test_policy \
  --engine MyPolicyEngine \
  --source policy.cedar \
  --validation-mode FAIL_ON_ANY_FINDINGS
```

If the Cedar syntax is invalid, the CLI returns a validation error before creating the policy.

### Switch to ENFORCE

Once LOG_ONLY results look correct:

```bash
# Update gateway to enforce mode
agentcore add gateway \
  --name MyGateway \
  --policy-engine MyPolicyEngine \
  --policy-engine-mode ENFORCE
agentcore deploy -y
```

---

## Path D: Debug policy failures

**"Access denied" on a tool call you expect to allow:**

1. Check that a `permit` policy exists for this action — remember, default is deny
2. Verify the action name format: `TargetName___tool_name` (three underscores)
3. Verify the resource ARN matches your gateway's actual ARN
4. Check that `hasTag()` is used before `getTag()` in conditions
5. Check LOG_ONLY logs to see what the policy engine is evaluating

```bash
# Check recent policy decisions
agentcore logs --runtime MyAgent --since 1h --query "policy"
agentcore status --type policy-engine
```

**"Everything is being denied" after attaching a policy engine:**
You attached a policy engine but haven't written any `permit` policies yet. The default is deny. Write at least one `permit` policy for the actions you want to allow.

**Policy name validation error:**
Policy names must match `^[A-Za-z][A-Za-z0-9_]*$` — letters, numbers, underscores only, starts with a letter. No hyphens.

---

## Output

- CLI commands to create the policy engine and policies
- Cedar policy file for the requested use case
- LOG_ONLY testing workflow before enforcement
- Debugging guidance for policy failures
