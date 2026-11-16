---
source_url: "https://startups.aws.com/prompt-library/read-only-aws-cost-optimization-audit"
title: "AWS Cost Optimization Audit: Eight-Phase Read-Only Spend Review"
kind: "prompt"
tags: ["Cost Optimization", "EC2", "RDS", "S3"]
---

## AWS Cost Optimization Audit: Eight-Phase Read-Only Spend Review

Audits your AWS account for waste, rightsizing, and savings opportunities, then hands you a prioritized fix list. Fully read-only, so nothing in your account changes.

## System Prompt

This prompt is long, so it is split into one file per section below. Read the parts in
order to reproduce the full System Prompt. To run or adapt one phase, load every shared
part (`00-overview.md`, `01-system-prompt.md`, `02-operating-rules.md`, `03-prerequisites.md`, `04-tool-selection-map.md`, `05-conventions-for-the-cli-blocks.md`, `16-key-principles.md`), then only that phase's file.
For the report phase, also load the appendices (`14-appendix-a-proposed-remediation-human.md`, `15-appendix-b-audit-trail.md`).

| Part | Section |
| ---- | ------- |
| [00-overview.md](read-only-aws-cost-optimization-audit/00-overview.md) | AWS Cost Optimization Audit: Eight-Phase Read-Only Spend Review |
| [01-system-prompt.md](read-only-aws-cost-optimization-audit/01-system-prompt.md) | System Prompt |
| [02-operating-rules.md](read-only-aws-cost-optimization-audit/02-operating-rules.md) | OPERATING RULES |
| [03-prerequisites.md](read-only-aws-cost-optimization-audit/03-prerequisites.md) | PREREQUISITES |
| [04-tool-selection-map.md](read-only-aws-cost-optimization-audit/04-tool-selection-map.md) | TOOL SELECTION MAP |
| [05-conventions-for-the-cli-blocks.md](read-only-aws-cost-optimization-audit/05-conventions-for-the-cli-blocks.md) | CONVENTIONS FOR THE CLI BLOCKS |
| [06-phase-1-scope-discovery-confirmation.md](read-only-aws-cost-optimization-audit/06-phase-1-scope-discovery-confirmation.md) | PHASE 1: SCOPE DISCOVERY & CONFIRMATION |
| [07-phase-2-preflight-checks.md](read-only-aws-cost-optimization-audit/07-phase-2-preflight-checks.md) | PHASE 2: PREFLIGHT CHECKS |
| [08-phase-3-cost-baseline.md](read-only-aws-cost-optimization-audit/08-phase-3-cost-baseline.md) | PHASE 3: COST BASELINE |
| [09-phase-4-waste-idle-resource-detection.md](read-only-aws-cost-optimization-audit/09-phase-4-waste-idle-resource-detection.md) | PHASE 4: WASTE & IDLE RESOURCE DETECTION |
| [10-phase-5-rightsizing-modernization.md](read-only-aws-cost-optimization-audit/10-phase-5-rightsizing-modernization.md) | PHASE 5: RIGHTSIZING & MODERNIZATION |
| [11-phase-6-commitment-analysis.md](read-only-aws-cost-optimization-audit/11-phase-6-commitment-analysis.md) | PHASE 6: COMMITMENT ANALYSIS |
| [12-phase-7-governance-gaps.md](read-only-aws-cost-optimization-audit/12-phase-7-governance-gaps.md) | PHASE 7: GOVERNANCE GAPS |
| [13-phase-8-report-generation.md](read-only-aws-cost-optimization-audit/13-phase-8-report-generation.md) | PHASE 8: REPORT GENERATION |
| [14-appendix-a-proposed-remediation-human.md](read-only-aws-cost-optimization-audit/14-appendix-a-proposed-remediation-human.md) | APPENDIX A: PROPOSED REMEDIATION (HUMAN EXECUTION REQUIRED) |
| [15-appendix-b-audit-trail.md](read-only-aws-cost-optimization-audit/15-appendix-b-audit-trail.md) | APPENDIX B: AUDIT TRAIL |
| [16-key-principles.md](read-only-aws-cost-optimization-audit/16-key-principles.md) | KEY PRINCIPLES |

## How to use?

<!-- markdownlint-disable -->

**1. Install the tools**

Install the [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) and an AI agent that can run shell commands, such as Kiro CLI.

**2. Enable cost data sources**

[Enable Cost Explorer](https://docs.aws.amazon.com/cost-management/latest/userguide/ce-enable.html) in the account you want to analyse: the audit cannot run without it, and the first data takes about 24 hours to appear. For a member account of an organization, the management account must enable it and [grant member accounts access](https://docs.aws.amazon.com/cost-management/latest/userguide/ce-access.html). Optionally, but recommended, opt in to [AWS Compute Optimizer](https://docs.aws.amazon.com/compute-optimizer/latest/ug/getting-started.html) and [Cost Optimization Hub](https://docs.aws.amazon.com/cost-management/latest/userguide/coh-getting-started.html) at the same time, so rightsizing findings are complete.

**3. Copy and run the prompt**

Click "Copy Prompt" to copy the prompt into your clipboard. Paste the prompt into your AI tool (e.g., Kiro CLI) and run it. Follow the instructions to generate the results.

**4. Choose the audit mode**

In `attended` mode (the default), the agent stops at each checkpoint, such as choosing the account, creating the audit role, and confirming scope, and waits for your answer. In `unattended` mode, it never waits: it applies safe defaults, skips the audit role and treats your current credentials as write-capable, and lists every assumption in the report. Use `attended` mode for your first run, so you create the read-only role and answer the scoping questions yourself.

**5. Audit role**

The prompt lists the AWS accounts you can access and asks you to choose one. It then gives you the steps to create a read-only IAM role that follows the principle of least privilege, as described in [Create a role to give permissions to an IAM user](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-user.html). The role definition is in the **PREREQUISITES** section of the prompt.

**6. Review and apply the results**

Read the report and analyse its findings critically before you act on them. Then apply the changes you agree with, starting with the low-risk ones in Appendix A.

<!-- markdownlint-enable -->
