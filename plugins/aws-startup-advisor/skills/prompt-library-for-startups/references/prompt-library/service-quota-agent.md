---
source_url: "https://startups.aws.com/prompt-library/service-quota-agent"
title: "AWS Service Quota Agent"
kind: "agent"
install_source: "https://github.com/aws-samples/sample-genai-startups/tree/main/agentic-coding-library/agents/service-quota-agent"
tags: ["Architecture", "Automation", "Intermediate", "EC2", "Lambda"]
---

## AWS Service Quota Agent

This agent audits your AWS service quotes across EC2, Lambda, RDS, and more, and submits quota increase requests on your behalf with confirmation.

## About this agent

<!-- markdownlint-disable -->

Startups on AWS hit invisible service limits that cause production outages during scaling events, often with no warning until something breaks. This agent scans your account across 10+ services including EC2, VPC, Lambda, ELB, RDS, and ECS, compares your current usage against quota limits, and flags anything approaching a threshold. It can also project which quotas will break at a given scaling target so you can plan ahead instead of reacting to failures. When you're ready, it submits quota increase requests on your behalf through the Service Quotas API or AWS Support cases, always with your explicit confirmation before taking any action. The output is a shareable quota-report.md you can hand to your team or include in operational reviews.

<!-- markdownlint-enable -->

## How to use?

<!-- markdownlint-disable -->

**Prerequisites**

- Valid AWS credentials with permissions to read service quotas and current usage
- For submitting increase requests, credentials need write access to the Service Quotas API or AWS Support

**What it does**

- Scans quotas across 10+ AWS services and compares current usage against limits
- Flags quotas approaching their threshold before they cause outages
- Projects which quotas will break at a given scaling target
- Submits quota increase requests via the Service Quotas API or AWS Support cases with your confirmation before every action
- Produces a shareable quota-report.md as output

**When to use it**

- You're preparing for a launch, funding announcement, or traffic spike and need to make sure your account can handle the load
- You've experienced a scaling failure and want to audit your limits to prevent it from happening again

<!-- markdownlint-enable -->

## Install

Install source: <https://github.com/aws-samples/sample-genai-startups/tree/main/agentic-coding-library/agents/service-quota-agent>

This agent installs separately from this skill, into the user's AI coding agent.
