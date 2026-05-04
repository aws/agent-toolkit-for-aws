# limits

Understand AgentCore Runtime quotas, diagnose which one you're hitting, and request an increase when you need one.

## When to use

- Your agent is being throttled or returning quota-related errors
- You're getting `ServiceQuotaExceededException: maxVms limit exceeded`
- You searched for a quota in the Service Quotas console and couldn't find it
- You're planning a launch and want to make sure quotas won't block you
- You're about to request a quota increase and want to get it right the first time

## Step 0: Verify CLI version

Run `agentcore --version`. This skill requires v0.9.0 or later. If older, run `agentcore update`.

---

## Which limit am I hitting?

Use the error you're seeing to find the right quota.

### Invocation rate

**Error shape:**

```
ThrottlingException: Rate exceeded
HTTP 429 Too Many Requests
```

On `InvokeAgentRuntime` or `InvokeAgentRuntimeWithWebSocketStream`.

**What it means:** Too many invocations per second for a single agent endpoint in your account. Default 25 TPS per agent, per account, per region. Adjustable.

**Before requesting an increase:**

- Add client-side retry with exponential backoff and jitter — throttling spikes are usually transient
- Check whether traffic is concentrated in bursts vs. spread — a burst of 100 requests at the same millisecond hits the TPS limit even if your average rate is well under it
- If the rate is a real long-term need, go request an increase (steps below)

---

### Concurrent VM / active session limit

**Error shape:**

```
ServiceQuotaExceededException: maxVms limit exceeded
```

**What it means:** Your account has too many concurrent microVMs active for AgentCore Runtime. In the AgentCore docs this quota is called **"Active session workloads per account."** Default 1,000 in us-east-1 and us-west-2, 500 in other regions. Adjustable.

**Critical — read before requesting an increase:**

CloudWatch's "concurrent active sessions" metric is not the same as live VM count. The `maxVms` quota counts all live microVMs in your account, including sessions that have completed their invocation but haven't yet been reclaimed. Your CloudWatch concurrency metric can show 50 while your actual live VM count is 500.

Real root cause for most customers hitting this is session lifecycle, not true concurrency. Check these first:

1. **Are you calling `StopRuntimeSession` after each invocation completes?** If not, the VM sticks around until `idleRuntimeSessionTimeout` expires (default 900 seconds / 15 minutes) before being reclaimed. At even modest request rates, VMs pile up.

2. **Are you reusing session IDs across related requests?** A unique session ID per request means a new environment per request. Reusing a session ID routes subsequent requests to the same environment, keeping total VM count low.

3. **Is your `idleRuntimeSessionTimeout` appropriate for your workload?** Short-lived requests with the default 900s timeout mean each VM ties up a slot for 15 minutes after its last request. Lower it by editing the runtime's `lifecycleConfiguration` in `agentcore/agentcore.json` and running `agentcore deploy`.

If you're hitting the limit after checking all three, request an increase.

See `agents-harden` SKILL.md (Session lifecycle management) for patterns and code snippets.

---

### New sessions created rate

**Error shape:**

```
HTTP 429 Too Many Requests
```

**What it means:** Rate of new session creation (per endpoint, per account). Default 100 TPM for container deployments; 25 TPS for direct code deployments. Adjustable.

**Before requesting an increase:**

- Reuse session IDs where possible — fewer new sessions = less pressure on this quota
- Spread traffic if you can — bursts of new-session requests hit the rate limit harder than steady-state traffic

---

### Memory operation rates

**Error shape:**

```
ThrottlingException
```

On `CreateEvent`, `RetrieveMemoryRecords`, `ListEvents`, and similar Memory APIs.

**What it means:** AgentCore Memory has per-operation rate limits. `CreateEvent` (default 10 TPS) is most commonly hit because agent code typically writes more than it reads. Most Memory API limits are adjustable.

**Before requesting an increase:**

- Add client-side retry with exponential backoff
- Confirm you're not accidentally writing the same content repeatedly (e.g., on every turn instead of once per fact)
- For long-term memory extraction, watch the `TokenCount` CloudWatch metric in the `Bedrock-AgentCore` namespace — the default is 150,000 tokens per minute per account (adjustable)

---

### Gateway target count or request rate

**Error shape:**

```
ValidationException: Too many targets for gateway
ThrottlingException
```

**What it means:** A single gateway has limits on number of targets (default 100 per gateway, adjustable), tools per target (default 1,000, adjustable), and invocation rate.

**Before requesting an increase:**

- Consolidate tools where possible — one Lambda with multiple tool definitions is more efficient than one Lambda per tool
- Split into multiple gateways if you have logically separate tool groups

---

### Code Interpreter / Browser session limits

**Error shape:**

```
ServiceQuotaExceededException
```

With an item name referencing Code Interpreter or Browser sessions.

**What it means:** Concurrent session limits for built-in tools.

**Before requesting an increase:**

- Ensure sessions are explicitly terminated when work completes
- Check for orphaned sessions from previous runs that might still be counted

---

## Where to find current quota values

1. **Canonical reference:** The AgentCore limits documentation page — https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html — lists every quota with its default value and whether it's adjustable. The **Adjustable** column is the source of truth. If the `awsknowledge` MCP server is available, use the `aws___search_documentation` tool to look up current quota values — it can fetch the latest docs directly instead of relying on potentially stale links.

2. **Service Quotas console:** https://console.aws.amazon.com/servicequotas/home → **AWS services** → search for "Amazon Bedrock AgentCore". Shows your current applied quota values and lets you request increases directly. Virtually every adjustable AgentCore quota is available here today — this should be your default path.

3. **`aws service-quotas list-services`** / **`list-service-quotas`:** Programmatic view — run `aws service-quotas list-services` and grep for "agentcore" or "bedrock" to find the current service code, then list quotas with `list-service-quotas --service-code <code>`.

---

## How to request a quota increase

Use the Service Quotas console. Virtually every adjustable AgentCore quota is available there; a direct AWS Support case is only needed in rare cases where a specific quota isn't surfaced in the console for your region.

### Path 1 — Service Quotas console (use this)

1. Open https://console.aws.amazon.com/servicequotas/home in the region where you need the increase. Quotas are region-specific — select the correct region in the top-right before proceeding.
2. Navigation pane → **AWS services** → search for **Amazon Bedrock AgentCore** and select it.
3. Find the quota in the list. The **Adjustable** column tells you if an increase can be requested.
4. Select the quota → **Request increase at account-level** (or **resource-level** if available for that quota).
5. Enter the new value (must be greater than the current applied value) → **Request**.
6. Track status in the **Request history** tab or the **Dashboard** in the navigation pane. When the status moves from **Pending** to **Quota requested**, a Support case number is assigned — you can open that case from the console to see progress.

**What happens next:**

- Smaller increases are often auto-approved within minutes to a few hours.
- Larger increases escalate to AWS Support and take longer (hours to days, depending on the magnitude and the quota).
- Support can approve, partially approve, or deny the request. If denied, the console message explains why; you can submit a new request with more justification.

**CLI equivalent** — for scripted workflows:

```bash
# Discover the Service Quotas service code for AgentCore (it follows the
# service's API prefix — run this once to confirm the exact code)
aws service-quotas list-services \
  --region <REGION> \
  --query "Services[?contains(ServiceName, 'AgentCore') || contains(ServiceCode, 'agentcore')]"

# List quotas for that service code
aws service-quotas list-service-quotas \
  --service-code <SERVICE_CODE> \
  --region <REGION>

# Submit the increase request
aws service-quotas request-service-quota-increase \
  --service-code <SERVICE_CODE> \
  --quota-code <QUOTA_CODE> \
  --desired-value <NEW_VALUE> \
  --region <REGION>

# Check status
aws service-quotas list-requested-service-quota-change-history-by-quota \
  --service-code <SERVICE_CODE> \
  --quota-code <QUOTA_CODE> \
  --region <REGION>
```

The account submitting the CLI request needs `ServiceQuotasFullAccess` (or equivalent) and `iam:CreateServiceLinkedRole` so Service Quotas can create the Support case on your behalf.

### Path 2 — AWS Support Center case (edge case)

Only needed when a specific quota you need isn't listed in the Service Quotas console for your region, or the console returns "This quota can't be increased from this console." This is uncommon — check the console first.

1. Open https://console.aws.amazon.com/support. You can also reach it from the **?** help icon in the AWS console → **Support Center**.
2. **Create case**.
3. **Case type** → **Service quotas**.
4. **Service** → **Service Limit increase**.
5. **Category** → select the AgentCore service (e.g., "Amazon Bedrock AgentCore Runtime"). If the specific AgentCore category isn't listed, use the closest match and put the exact quota name in the description.
6. **Region** → select the AWS Region you need the increase in. You can choose **Add another limit** to request the same increase in multiple regions in one case.
7. **Description** — include everything the reviewer needs (see fields below).
8. Pick a **Contact method** (Web, Chat, Phone) → **Submit**.

### Required information, regardless of path

Whether you're using the Service Quotas console justification field or the Support case description, give the reviewer enough to say yes:

- **AWS Account ID** (the account that needs the increase)
- **Region(s)** — limits are per-region; list every region you need if this is a Support case covering multiple
- **Quota name** — match the exact name from the AgentCore limits documentation (e.g., "Active session workloads per account," "InvokeAgentRuntime API rate, per agent, per account")
- **Current value → requested value** — be specific (e.g., "25 → 100")
- **Agent Runtime ID(s)** or ARN(s) — what this request is for
- **Use case** — 1–3 sentences on what the agent does and the traffic pattern (sustained vs. bursty matters for some quotas)
- **Expected peak** — a real number (peak TPS, concurrent sessions, etc.), not a range
- **Business impact** — what's blocked at the current limit (e.g., "blocks our GA launch on X date")
- **Timeline / need-by date**

### Copy-paste justification template

Drop this into the Service Quotas justification field or the Support case description:

```
Account ID: <12-digit account>
Region(s): <comma-separated>
Quota name: <exact name from AgentCore limits docs>
Current value: <N>
Requested value: <N>
Agent Runtime ID(s): <comma-separated agentRuntimeId or ARN values>

Use case:
  <1–3 sentences describing what the agent does and the traffic pattern>

Expected peak:
  <specific number — peak TPS, concurrent sessions, etc.>

Business impact if not raised:
  <what happens to your workload at the current limit>

Need-by date: <date>
```

### What speeds up approval

- Specific numbers, not "as high as possible"
- Traffic pattern explained — sustained vs. bursty
- Pre-launch load-testing numbers if you have them
- Production launch date called out explicitly

### What slows approval down

- Requesting an increase before trying the mitigations above (`StopRuntimeSession`, session reuse, batching, retries)
- Requesting every quota to some large round number "just in case"
- Missing the exact quota name — reviewers need to know which quota in which service
- Requesting increases in every region when only one or two are needed

---

## Before you request: quick triage

Work through this list first. Most "I'm hitting a limit" issues get resolved at one of these steps without needing an actual increase.

- [ ] Is the error really a quota error? (Check the exception class and code — not every `Exception` is throttling)
- [ ] Client-side retry with exponential backoff — present for transient throttling?
- [ ] For `maxVms`: is `StopRuntimeSession` being called after each invocation?
- [ ] For `maxVms`: are session IDs reused across related requests?
- [ ] For `maxVms`: is `idleRuntimeSessionTimeout` set appropriately for your workload?
- [ ] For memory writes: are you batching where possible, and not writing duplicates?
- [ ] Is traffic bursty? Can you smooth it out at the caller?
- [ ] Is the current quota actually the problem, or is a downstream dependency the real bottleneck?

If you've checked all of the above and still need the increase, submit it through the Service Quotas console.

## Output

- Identification of the specific quota being hit based on the error
- Mitigations to try before requesting an increase
- Path to submit: Service Quotas console (or, rarely, a Support case) — with a filled-in justification ready to paste
