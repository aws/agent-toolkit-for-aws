---
source_url: https://aws.amazon.com/startups/prompt-library/aws-security-baseline-terraform-deployment-kit
title: "AWS Security Baseline: Terraform Deployment Kit"
tags: ["Deployment", "Security & Compliance", "Intermediate", "Terraform", "GuardDuty", "Security Hub"]
---

## AWS Security Baseline: Terraform Deployment Kit

Deploy comprehensive AWS security baseline using Terraform with automated monitoring, threat detection, and compliance controls so startups meet enterprise security requirements faster.

## System Prompt

Create a comprehensive AWS security baseline using Terraform that includes:

1. Multi-region CloudTrail with encryption, log file validation, and CloudWatch integration
2. GuardDuty with S3 protection and malware scanning enabled
3. Security Hub with AWS Foundational Best Practices standard
4. AWS WAF with OWASP Top 10 rules and rate limiting (2000 req/5min)
5. AWS Inspector for EC2, ECR, and Lambda vulnerability scanning
6. CloudWatch Dashboard with 8 widgets showing security metrics
7. 4 CloudWatch Alarms: root account usage, unauthorized API calls (5+ in 5min), IAM policy changes, S3 bucket policy changes
8. 3 IAM roles with least-privilege access:
   - BreakGlassAdmin (requires ExternalId for emergency access)
   - SecurityAuditor (read-only security monitoring)
   - DeveloperTemplate (least-privilege development access)
9. KMS encryption with auto-rotation for CloudTrail and SNS
10. S3 state management with versioning and DynamoDB locking
11. SNS topic for security alerts with email subscription

Requirements:

- Use modular Terraform structure (root + security_baseline module)
- Include comprehensive documentation: README, QUICKSTART, SECURITY-BASELINE with SOC 2 mapping
- Provide migration script for S3 backend
- Include .gitignore for sensitive files
- Add terraform.tfvars.example template
- Create demo scripts for 5-minute and 10-minute presentations
- Ensure all resources are tagged with Project, Environment, ManagedBy
- Configure proper IAM policies and trust relationships
- Enable versioning and encryption on all S3 buckets
- Set up metric filters for security event detection

Output should serve as a starting point for a production security baseline — well-documented and deployable in under 10 minutes. Review all generated resources against your organization's security requirements and conduct an application security review before deploying to production.

## How to use?

### Prerequisites

**Required Access:**

1. Unified AWS MCP Server (`aws-mcp`) available for documentation lookups — it ships with this plugin, so no separate install is needed
2. AWS account access (read-only sufficient for assessment)
3. Basic understanding of AWS services (EC2, RDS, S3, IAM)

**Recommended Background:**

- Familiarity with cloud security concepts
- Understanding of startup funding stages
- Basic knowledge of compliance frameworks (SOC2, GDPR)

**Tools Required:**

1. AI assistant with MCP support
2. Access to MCP tools: aws_search_documentation, aws_read_documentation, aws_get_regional_availability, aws_list_regionsSETUP

### Instructions

#### Step 1: Prepare Assessment Context

Gather the following information:

- Startup Profile: Company name, funding stage, industry, current scale
- AWS Environment: Services in use, account structure, team size
- Security Goals: Primary objectives, timeline, budget, compliance requirements

#### Step 2: Configure the Prompt

- Copy the complete prompt composition
- Replace all bracketed placeholders [LIKE_THIS] with your specific information
- Ensure all sections are completed, especially Current Environment Context

#### Step 3: Execute Assessment

- Submit configured prompt to AI assistant with MCP support
- Assistant will systematically assess each control using MCP tools
- Review output for completeness (Executive Summary, Control Reports, Remediation Roadmap)
