---
description: Ask the AWS DevOps Agent for cost optimization opportunities, scoped to your local IaC
argument-hint: [optional focus area, e.g. "ECS only" or "across all spaces"]
---

Cost optimization is a chat-first workflow.

1. Read whatever local IaC files are present — CDK stacks, CloudFormation templates, Terraform modules. Pick files referenced from `cdk.json`, `template.yaml`, `*.tf`, `serverless.yml`, etc.
2. If `$ARGUMENTS` mentions "all spaces" / "across accounts" and the user has SigV4 auth with multiple spaces, follow the `coordinating-multi-space-devops-agent` skill's parallel-query pattern.
3. Call `aws_devops_agent__chat(message="[Local IaC Context]\n<IaC snippets>\n\nAnalyze cost optimization opportunities. $ARGUMENTS")`.
4. Show the response. Ask if the user wants to drill into any specific recommendation, or escalate to a deep investigation for one of them.
