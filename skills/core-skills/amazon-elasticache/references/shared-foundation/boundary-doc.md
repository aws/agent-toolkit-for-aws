# ElastiCache Skill -- Ownership Boundary Document

This document defines what the ElastiCache skill owns directly and what it defers to AWS documentation.

## What the Skill Owns Directly

The skill is the authoritative source for the following capabilities. It produces these outputs inline, without requiring external tool calls.

* **Intent routing.** Classifying user requests across the six sub-skills (requirements, setup, data-modeling, genai, monitoring, migration) and selecting the correct pipeline.
* **Architecture guidance.** Recommending engine (Valkey, Redis OSS, Memcached), deployment model (serverless vs node-based), and topology (standalone, cluster mode, Global Datastore) based on workload requirements.
* **Hard routing enforcement.** Ensuring vector search always routes to node-based Valkey 8.2 or later (serverless caches do not support vector search; data-tiering node types are also excluded from vector search), Global Datastore always routes to node-based (requires M5, M6g, M7g, R5, R6g, R6gd, R7g, or C7gn instance families, size large and above), serverless auth never includes AUTH tokens, and online migration targets do not have encryption in-transit enabled, sources do not have AUTH enabled, and targets have Multi-AZ enabled. Online migration has additional prerequisites; see `references/migration/topology-validation.md` for the full preflight checklist.
* **IaC generation.** Producing CloudFormation, CDK, and Terraform templates for cache creation, security groups, IAM policies, and RBAC user setup.
* **Connection recipes.** Generating SDK connection snippets (Python, Java, Node.js, Go, CLI) with correct TLS, auth, and VPC configuration for both serverless and node-based deployments.
* **Observability bootstrap.** Generating CloudWatch dashboard and alarm definitions via `scripts/generate_dashboards.py`, and providing metric-driven troubleshooting guidance.
* **Cost estimation.** Running `scripts/price_calculator.py` to compare serverless vs node-based pricing for a given workload profile.
* **Security audit.** Running `scripts/security_audit.py` to validate post-creation security posture.
* **Migration planning.** Producing migration runbooks, preflight checks (via `scripts/migration_preflight.py`), validation steps, and rollback procedures.
* **Data modeling patterns.** Recommending data structures, key schemas, TTL strategies, and invalidation approaches for common use cases (cache-aside, session store, rate limiting, leaderboards, etc.).
* **GenAI pattern design.** Designing semantic cache, conversational memory, RAG, recommendation, and vector search implementations using Valkey.

## Execution Paths

The skill generates instructions, code, or parameters for each operation. The primary execution paths are AWS CLI, SDK, and valkey-py code.

* **Control-plane operations** (creating, modifying, and deleting serverless caches and replication groups; creating and managing RBAC users and user groups; describing cache clusters, endpoints, and configuration; creating and managing snapshots and backups; setting up Global Datastore; creating jump hosts and generating SSH tunnel commands): the skill generates AWS CLI commands, boto3 SDK calls, or CloudFormation/CDK templates.
* **Data-plane operations** (Valkey or Memcached commands, vector search, JSON operations against a live endpoint): the skill generates valkey-py (Python) code that runs commands via `execute_command()`.

## What the Skill Defers to AWS Documentation

The skill does not attempt to be exhaustive on edge cases, tuning parameters, or service limits. It links to official AWS docs for the following.

* **Parameter group tuning.** The skill recommends starting defaults but defers to the ElastiCache User Guide for the full parameter reference and advanced optimization.
* **Service limits and quotas.** Current limits for nodes per cluster, connections, memory, ECPUs, and other quotas change over time and live in the AWS Service Quotas console and documentation.
* **Version-specific release notes.** Detailed engine release notes, patch contents, and deprecation timelines are maintained in the ElastiCache User Guide.
* **Edge-case configurations.** Unusual topologies (e.g., multi-AZ with read replicas in specific failure modes), niche parameter interactions, and rarely used features are covered in the User Guide.
* **Compliance and certification details.** Specific compliance programs (HIPAA, PCI, FedRAMP) and their ElastiCache coverage are documented in AWS compliance resources.
* **Pricing changes.** The skill uses `scripts/price_calculator.py` for estimation but defers to the official AWS ElastiCache Pricing page for authoritative, current pricing.
* **API Reference details.** Full API request/response schemas, error codes, and throttling behavior are in the ElastiCache API Reference.

## AI-Generated Output Disclaimer

All code, configurations, CLI commands, and recommendations produced by this skill are AI-generated. Review all outputs before deploying to production environments.
