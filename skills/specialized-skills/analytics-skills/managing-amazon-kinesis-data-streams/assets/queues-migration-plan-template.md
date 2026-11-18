# Migration Plan Template

This is a template. Copy it to the user's chosen location and fill it in. Every Status starts as `pending`; set it to `done` or `n/a` as the migration progresses. On later sessions, read the user's plan document to recover state and resume at the current step.

---

```markdown
# Migration Plan: Queues in Kinesis Data Streams - <service / consumer name>

## Status Summary

| Step | Status | Last Updated |
|------|--------|--------------|
| 1. Identify the current consumption method | pending | - |
| 2. Assess fit | pending | - |
| 3. Analyze existing consumer | pending | - |
| 4. Confirm strategy and tracking | pending | - |
| 5. Code Generation | pending | - |
| 6. Validate | pending | - |

## 1. Identify the current consumption method

- Consumption method: <KCL / custom GetRecords / Lambda ESM / other>
- (No existing consumer → greenfield setup, not a migration.)

## 2. Assess fit

- Strict ordering required: <yes/no>
- Partition key grouping required: <yes/no>
- Duplicate processing causes a problem: <yes/no; if yes, made idempotent first: yes/no>
- Result: <go / no-go / hybrid>
- Hybrid partition (if applicable): <which paths migrate, which stay>

### Pre-migration checklist
| Item | Status | Notes |
|------|--------|-------|
| Stream → On-demand | pending | |
| Stream encrypted at rest (KMS) | pending | |
| IAM policy updates | pending | |
| Client-side filtering | pending | |
| Room under stream registered consumer limit (enhanced fan-out + queues) | pending | |
| Producer not using KPL aggregation (queues don't de-aggregate records) | pending | |
| Dead-letter configuration chosen (`MaxReceiveCount` or off) | pending | |
| Owner for dead-letter records (who inspects, restores, or acknowledges them) | pending | |

## 3. Analyze existing consumer

### Technology Stack
- Language/SDK: <e.g., Python boto3 / Java KCL 2.x / Lambda handler>
- IaC tool: <CloudFormation / Terraform / CDK / none>

### Existing Consumer
| Component | File Path | Notes |
|-----------|-----------|-------|
| Entry point | <e.g., consumer.py, handler.js> | |
| Record processing logic | <file + method> | |
| State management | <checkpoint / lease table / Lambda batch window / none> | |
| Associated resources | <DynamoDB table, event source mapping, etc.> | |

### Infrastructure
- Stream: <name>   Mode: <On-demand / Provisioned>
- Region: <region>
- IAM policy location: <file path or "ambient credentials">

## 4. Confirm strategy and tracking

- Test environment: <account, Region, and stream / none>
- Selected: <parallel run / all-at-once (only if cutover downtime is accepted)>
- Rationale: <why this strategy fits the workload>
- Risk level: <low / medium / high>
- Downtime: <zero / brief cutover>

## 5. Code Generation

- Queues (test / production): <name / ARN for each>, starting position <LATEST / TRIM_HORIZON / AT_TIMESTAMP>, visibility timeout <seconds>, MaxReceiveCount <n>
- Consumer file(s): <paths - new files alongside existing consumer>
- IAM policy: <path to JSON policy document>
- IaC changes: <paths or N/A>

## 6. Validate

### Cutover steps
1. <test environment: create the queue with the setup/operator policy and wait for ACTIVE, apply the consumer IAM policy scoped to the queue ARN, start the queue consumer, validate>
2. <production: create the queue with the setup/operator policy and wait for ACTIVE>
3. <production: apply the consumer IAM policy, scoped to the new queue ARN>
4. <production: start queue consumer alongside the existing consumer (parallel run), or stop the existing consumer first (all-at-once)>
5. <production: verify records flowing and acknowledged>
6. <after validation and user approval: stop the existing consumer>

### Validation results
- Validated in test environment: <yes/no>
- Records received and acknowledged: <yes/no>
- Acknowledge failures: <none / details>
- Records accumulating in the dead-letter state: <no / count and cause>
- Consumer instances keep up (`VisibleQueueRecords` not growing): <yes / no, and the instance count>
- Existing consumer state store idle: <yes/no/N/A>
- User confirmation to proceed: <yes/no>

### Rollback (if validation fails)
- Stop queue consumer
- Re-enable existing consumer (state store intact if applicable)
- Revert IAM changes
- Stream stays on-demand: a stream with queues cannot switch back to provisioned, so delete its queues first if it needs to
- No data loss: records remain in the stream for its retention period

### Decommission (only after validation passes and explicit user approval)
- Existing consumer stopped: <yes/no>
- Associated resources cleaned up: <yes/no>
- Outcome: <completed / blocked>

## Log
- <YYYY-MM-DD> <event>
```
