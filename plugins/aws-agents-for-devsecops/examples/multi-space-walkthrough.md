# Multi-Space Walkthrough: Production Incident with Staging Comparison

This example shows how to use multiple AgentSpaces during a real incident — investigating production, comparing staging, and pulling runbooks from a knowledge space.

## Scenario

Your checkout-service is throwing 503 errors in production. You have three AgentSpaces:

- **prod** (as-prod-001) — production account
- **stage** (as-stage-002) — staging account
- **kb** (as-kb-003) — knowledge base with runbooks

## Steps

### Step 1 — Discover and pick the right spaces

```
aws devops-agent list-agent-spaces --region us-east-1
```

This returns all spaces. Pick the one matching the incident scope (production).

### Step 2 — Open the prod investigation in parallel with the staging check

Don't serialize — the investigation takes 5–8 minutes; the staging chat takes seconds. Fire both, then keep both progressing.

**Prod (deep investigation):**

```
aws devops-agent create-backlog-task --agent-space-id as-prod-001 --task-type INVESTIGATION --title 'ECS 503 errors on checkout-service (prod)' --priority HIGH --description '<local context>' --region us-east-1
```

Save `taskId`. Poll with `get-backlog-task` every 30-45s.

**Staging (fast chat):**

```
aws devops-agent create-chat --agent-space-id as-stage-002 --user-id USER_ID --user-type IAM --region us-east-1
→ executionId

aws devops-agent send-message --agent-space-id "as-stage-002" --execution-id exec_stage --user-id USER_ID --content 'Is the checkout-service healthy in staging? Any 503s or error spikes in the last hour?' --region us-east-1
```

### Step 3 — Pull runbooks from the knowledge space

While the investigation runs, check the knowledge base for existing runbooks:

```
aws devops-agent create-chat --agent-space-id as-kb-003 --user-id USER_ID --user-type IAM --region us-east-1
→ exec_kb

aws devops-agent send-message --agent-space-id "as-kb-003" --execution-id exec_kb --user-id USER_ID --content "What's our standard runbook for ECS 503 errors?" --region us-east-1
```

### Step 4 — Stream investigation progress

```
aws devops-agent get-backlog-task --agent-space-id as-prod-001 --task-id TASK_ID --region us-east-1
→ When status=IN_PROGRESS and executionId available:

aws devops-agent list-journal-records --agent-space-id as-prod-001 --execution-id EXEC_ID --region us-east-1
```

Update the user after each poll:
> 🔍 **2 min in:** Agent querying CloudWatch for error rate across AZs...
> 🎯 **5 min in:** Root cause — memory limit reduced from 512MB to 256MB in last deploy.

### Step 5 — Synthesize and present

Once the investigation completes:

```
aws devops-agent update-backlog-task --agent-space-id as-prod-001 --task-id TASK_ID --task-status PENDING_START --region us-east-1
```

Poll until `COMPLETED`, then retrieve the mitigation plan:

```
aws devops-agent list-executions --agent-space-id as-prod-001 --task-id TASK_ID --region us-east-1
aws devops-agent list-journal-records --agent-space-id as-prod-001 --execution-id EXEC_ID --record-type mitigation_summary_md --region us-east-1
```

Combine findings:

- **Prod investigation**: Root cause + mitigation plan
- **Staging comparison**: "Staging is healthy — confirms this is a prod-only deploy issue"
- **KB runbook**: Standard ECS 503 runbook for reference

Present a unified summary with the remediation plan. **Never auto-execute** — show the diff and let the user approve.
