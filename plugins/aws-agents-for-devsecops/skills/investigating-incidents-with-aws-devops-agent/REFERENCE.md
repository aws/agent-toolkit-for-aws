# Investigation reference

## Journal record types

| Type | Emoji | Meaning |
|------|-------|---------|
| `PLANNING` | 📋 | Agent is planning its approach |
| `SEARCHING` | 🔍 | Agent is querying CloudWatch, X-Ray, logs, IAM, etc. |
| `ANALYSIS` | 🔬 | Agent is analyzing collected data |
| `FINDING` | 🎯 | Key discovery — surface this prominently |
| `ACTION` | 🔧 | Agent is performing a read-only action |
| `SUMMARY` | 📊 | Investigation summary with root cause |
| `SUGGESTION` | 💡 | Recommended fix |

## Polling cadence

| Status | Action |
|--------|--------|
| `CREATED` | Poll every 30s. Wait up to 60s — if still CREATED, keep waiting. |
| `IN_PROGRESS` | Poll every 30–45s. Fetch journal records with pagination. |
| `COMPLETED` | Stop polling. Fetch full journal `--order DESC --max-items 10`. If the user approves, trigger mitigation (2-5 min) via `update-backlog-task --task-status PENDING_START`. |
| `FAILED` | Stop polling. Fetch journal — partial findings often exist. |

Never poll faster than 30s — you'll hit throttling.

## Pagination

`aws devops-agent list-journal-records` returns `nextToken` when there are more records. Save it and pass `--next-token TOKEN` on the next poll so you only fetch *new* records each cycle. Re-fetching the full journal on every poll is wasteful and slow.

## Error recovery

| Error | Cause | Action |
|-------|-------|--------|
| `ResourceNotFoundException` | Wrong agent_space_id | `aws devops-agent list-agent-spaces --region us-east-1` to verify |
| `ThrottlingException` | Polling too fast | Back off — 60s, then 90s, then 120s |
| `ValidationException` | Missing required field on `create-backlog-task` | `--title`, `--task-type`, and `--priority` are required |
| `AccessDeniedException` | Missing IAM permissions | User needs `AIDevOpsAgentFullAccess` |
| `ExpiredTokenException` | AWS credentials expired | `aws sso login` or refresh access keys |

## Priority guide

| Priority | Use for |
|----------|---------|
| `CRITICAL` | Active sev1, customer-facing outage |
| `HIGH` | Active production incident, error rate elevated |
| `MEDIUM` | Recurring issue, performance degradation |
| `LOW` | Postmortem, follow-up mitigation generation |
| `MINIMAL` | Exploratory analysis, no time pressure |

## Common patterns

### Parallel triage + investigation

When the user reports an incident, fire **both** in sequence so they get instant guidance while the deep investigation runs:

```
# Instant triage (2-10s)
aws devops-agent create-chat --agent-space-id SPACE_ID --user-id USER_ID --user-type IAM --region us-east-1 → executionId
aws devops-agent send-message --agent-space-id SPACE_ID --execution-id EXEC_ID --user-id USER_ID --content '<incident> + <local context>' --region us-east-1

# Deep investigation (5-8 min)
aws devops-agent create-backlog-task --agent-space-id SPACE_ID --task-type INVESTIGATION --title '<incident>' --priority HIGH --description '<local context>' --region us-east-1 → taskId
aws devops-agent get-backlog-task ... → poll for executionId
aws devops-agent list-journal-records ... → stream findings
```

Show the chat response immediately. Update the user with investigation progress as journal records come in.

### Trigger mitigation on a completed investigation

If a previous investigation completed without recommendations, trigger mitigation (2-5 min):

```
aws devops-agent update-backlog-task \
  --agent-space-id SPACE_ID \
  --task-id TASK_ID \
  --task-status PENDING_START \
  --region us-east-1
```

Poll `get-backlog-task` until `COMPLETED`, then retrieve the mitigation plan:

```
aws devops-agent list-executions \
  --agent-space-id SPACE_ID \
  --task-id TASK_ID \
  --region us-east-1
```

Find the newest execution_id, then:

```
aws devops-agent list-journal-records \
  --agent-space-id SPACE_ID \
  --execution-id EXEC_ID \
  --record-type mitigation_summary_md \
  --region us-east-1
```
