---
source_url: "https://startups.aws.com/prompt-library/multi-account-transition-advisor"
title: "AWS Multi-Account Transition Advisor"
kind: "agent"
install_source: "https://github.com/aws-samples/sample-genai-startups/tree/main/agentic-coding-library/agents/multi-account-architect"
tags: ["Architecture", "Security & Compliance", "Intermediate", "IAM", "CloudFormation"]
---

## AWS Multi-Account Transition Advisor

This agent guides startups through transitioning from a single AWS account to a multi-account setup.

## About this agent

<!-- markdownlint-disable -->

Most startups begin with a single AWS account and eventually hit the point where environments, permissions, and billing are tangled together. This agent walks you through the transition to a multi-account architecture using AWS Organizations. It starts by scanning your existing resources with the Resource Groups Tagging API, classifies them by environment based on tags and naming conventions, and proposes how to split them across organizational units like Production, Development, and Security. It also audits your IAM roles and policies for hardcoded account IDs and ARNs that would silently break after migration, and generates a remediation report for each one. When you're ready to build, it produces Terraform or CloudFormation templates to bootstrap your new Organization structure — Management, Log Archive, Security, Tooling, and Workload accounts — sized to what it actually found in your account. Progress is tracked in a persistent state file so you can pick up where you left off across sessions.

<!-- markdownlint-enable -->

## How to use?

<!-- markdownlint-disable -->

**Prerequisites**

- Valid AWS credentials with read-only access — the agent is designed to scan and assess, not modify your resources
- Works with existing resource tags and naming conventions — the more consistent your naming, the better the recommendations

**What it does**

- Audits your account and classifies resources by environment (prod, dev, staging, etc.)
- Scans IAM roles and policies for hardcoded account IDs and ARNs that will break during migration
- Generates Terraform or CloudFormation to bootstrap your new AWS Organization
- Tracks migration progress across sessions with a persistent checklist
- Maintains a MIGRATION.md with task list and Mermaid architecture diagrams

**When to use it**

- You're running everything in one account and need to separate environments before your next SOC 2 audit or funding round
- You want a concrete, trackable migration plan instead of reading through AWS docs

<!-- markdownlint-enable -->

## Install

Install source: <https://github.com/aws-samples/sample-genai-startups/tree/main/agentic-coding-library/agents/multi-account-architect>

This agent installs separately from this skill, into the user's AI coding agent.
