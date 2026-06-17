---
description: Start a deep root-cause investigation on the AWS DevOps Agent and stream progress
argument-hint: [incident description]
---

Use the `investigating-incidents-with-aws-devops-agent` skill workflow.

1. Gather local context — `git log --oneline -10`, dependency manifest, relevant IaC, the error/log the user is looking at.
2. Call `aws_devops_agent__investigate(title="$ARGUMENTS — <local context summary>")`.
3. Tell the user investigations take 5–8 minutes and that you'll keep them posted.
4. Poll `aws_devops_agent__get_task(task_id="TASK_ID")` every 30–45s.
5. When `IN_PROGRESS`, fetch findings: `aws_devops_agent__list_journal_records(execution_id="EXEC_ID", order="ASC")`. Summarize each new record using emoji prefixes from the `investigating-incidents-with-aws-devops-agent` skill.
6. On `COMPLETED`: pull final findings, then call `aws_devops_agent__list_recommendations(task_id="TASK_ID")` for mitigations. Show the user the proposed fix — **do not** auto-apply.

If `$ARGUMENTS` is empty, ask the user for a one-line incident description first.
