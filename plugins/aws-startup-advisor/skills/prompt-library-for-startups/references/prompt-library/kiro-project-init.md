---
source_url: https://aws.amazon.com/startups/prompt-library/kiro-project-init
title: "Kiro Project Init: Automated Spec-Driven Development Setup"
tags: ["Prototyping", "Deployment", "Kiro", "Lambda", "Beginner", "DynamoDB", "API Gateway"]
---

## Kiro Project Init: Automated Spec-Driven Development Setup

One-command project setup with AI-powered specs, automated testing, and AWS integrations. Generates structured requirements, design docs, and deployment-ready code—eliminating hours of manual setup.

## System Prompt

## Project Setup - modify this to describe what needs to be built

**App Name**:PROJECTNAME - e.g. MyLittle Project
**Description**: Use Case: A TODO list\
**Features**: Key features: add/remove tasks, assign to people, mark as done, view all tasks, view tasks for a person

---

You are setting up a specification-driven development environment with steering files, agent hooks, and the unified AWS MCP Server.

## PROJECT CONTEXT

Extract from Project Setup above. Use these defaults if not specified:

- **Project Type**: Full-stack web application
- **Tech Stack**: React frontend, Python backend, AWS services
- **AWS Services**: Lambda, DynamoDB, S3, API Gateway (simplest options)
- **Team Size**: Solo developer
- **Security**: Standard
- **Target Users**: Development teams

## TASK 1: CREATE STRUCTURE

```
[PROJECT_NAME]/
├── .kiro/
│   ├── steering/          # 6 files: product, tech, structure, api-standards, testing-standards, security-policies
│   ├── hooks/             # 4 files: test-sync, documentation-update, security-scan, cost-check
│   └── specs/.gitkeep
├── .vscode/mcp.json
├── .cursor/mcp.json
├── .gitignore
├── .env.example
└── README.md
```

## TASK 2: STEERING FILES

### .kiro/steering/product.md

```markdown
---
inclusion: always
---

# Product Overview: [PROJECT_NAME]

## Purpose

[2-3 paragraphs: what it does, why it exists]

## Target Users

[Who uses this]

## Key Features

[3-7 core features]

## Business Objectives

[Business goals]

## Success Metrics

[3-5 key metrics]
```

### .kiro/steering/tech.md

```markdown
---
inclusion: always
---

# Technology Stack: [PROJECT_NAME]

## Primary Technologies

- **Frontend**: [e.g., React 18, TypeScript, Vite]
- **Backend**: [e.g., Python 3.12, FastAPI]
- **Database**: [e.g., DynamoDB, Aurora PostgreSQL]
- **Infrastructure**: [e.g., AWS CDK, Lambda, API Gateway]
- **Testing**: [e.g., Jest, Pytest, Playwright]

## AWS Services

- **Compute**: [Lambda, ECS, EC2]
- **Storage**: [S3, DynamoDB, Aurora]
- **Networking**: [API Gateway, CloudFront, VPC]
- **AI/ML**: [Bedrock, SageMaker]
- **Monitoring**: [CloudWatch, X-Ray, CloudTrail]

## MCP Servers Configured

- **aws-mcp** (unified AWS MCP Server): AWS service management, AWS documentation search and reads, regional availability, and AWS skills — one server covering all AWS access for this project

## Development Tools

- **IDE**: [VS Code, Cursor]
- **Version Control**: [Git, GitHub]
- **CI/CD**: [GitHub Actions, CodePipeline]
- **Package Management**: [npm, pip, poetry]

## Technical Constraints

[Limitations, requirements]

## Architecture Decisions

[Key choices and rationale]
```

### .kiro/steering/structure.md

```markdown
---
inclusion: always
---

# Project Structure: [PROJECT_NAME]

## Directory Organization
```

src/
├── components/ # Reusable UI
├── pages/ # Page-level
├── services/ # Business logic
├── utils/ # Helpers
├── types/ # TypeScript types
├── hooks/ # Custom hooks
└── config/ # Configuration

```
## Naming Conventions
- **Components**: PascalCase (`UserProfile.tsx`)
- **Utilities**: camelCase (`formatDate.ts`)
- **Tests**: `.test.ts` suffix (`UserProfile.test.tsx`)
- **Types**: `.types.ts` suffix (`User.types.ts`)
## Import Patterns
- Absolute imports: `@/components/Button`
- Group: external, internal, types, styles
- Prefer named exports
## Infrastructure Location
[e.g., `infrastructure/`, `cdk/`]
```

### .kiro/steering/api-standards.md

````markdown
---
inclusion: fileMatch
fileMatchPattern: "**/{api,routes,endpoints,controllers}/**/*.{ts,js,py}"
---

# API Standards: [PROJECT_NAME]

## REST Conventions

- Plural nouns: `/users`, `/products`
- Methods: GET (read), POST (create), PUT (update), DELETE (delete)
- Status: 200 (success), 201 (created), 400 (client error), 500 (server error)

## Response Format

```typescript
// Success
{ "data": {}, "meta": { "timestamp": "ISO 8601", "requestId": "uuid" }}
// Error
{ "error": { "code": "ERROR_CODE", "message": "...", "details": {} }, "meta": {...}}
```
````

## Authentication

[JWT, API keys, OAuth, etc.]

## Validation

- Validate all inputs at API boundary
- Use schema validation (Zod, Joi, Pydantic)
- Return field-level errors

## Documentation

- OpenAPI 3.0 specs in `api-specs/`
- Use `aws___search_documentation` / `aws___read_documentation` for AWS patterns

````
### .kiro/steering/testing-standards.md
```markdown
---
inclusion: fileMatch
fileMatchPattern: "**/*.{test,spec}.{ts,js,tsx,jsx,py}"
---
# Testing Standards: [PROJECT_NAME]
## Organization
- Co-locate: `Component.tsx` → `Component.test.tsx`
- Or mirror in `__tests__/`
## Structure
```typescript
describe('[ComponentName]', () => {
  describe('[method]', () => {
    it('should [behavior] when [condition]', () => {
      // Arrange, Act, Assert
    });
  });
});
````

## Principles

- **Unit**: Isolated functions/components
- **Integration**: Module interactions
- **E2E**: Complete workflows
- **Coverage**: Minimum [80%]

## AWS Testing

- SDK mocks for unit tests
- LocalStack for integration
- Document which `aws-mcp` tools each test path relies on

````
### .kiro/steering/security-policies.md
```markdown
---
inclusion: always
---
# Security Policies: [PROJECT_NAME]
## Credential Management
- NEVER commit secrets
- Use environment variables
- Store in Secrets Manager/Parameter Store
- Document in `.env.example`
## Input Validation
- Validate ALL inputs
- Parameterized queries
- CSRF protection
- Length limits
## Authentication & Authorization
[Auth flows, authorization rules]
## Data Protection
[Encryption at rest/transit, PII handling]
## Compliance
[HIPAA, GDPR, SOC 2, PCI DSS]
## Security Scanning
- cdk-nag for CDK stacks
- Checkov for Terraform
- Well-Architected Framework review guidance via `aws___search_documentation` / `aws___read_documentation`
## Incident Response
[Procedures]
````

## TASK 3: AGENT HOOKS

### .kiro/hooks/test-sync.kiro.hook

```json
{
  "name": "Test File Synchronization",
  "description": "Auto-creates/updates test files on save",
  "version": "1",
  "when": {
    "type": "fileSaved",
    "patterns": ["src/**/*.{ts,tsx,js,jsx}"]
  },
  "then": {
    "type": "askAgent",
    "prompt": "Source file saved:\n1. Check for test file (.test.ts/.test.tsx)\n2. If missing: Create with tests for all exports per testing-standards.md\n3. If exists: Add tests for untested functionality\n4. Follow structure.md conventions\n5. Don't modify source\n\nRef: #[[file:.kiro/steering/testing-standards.md]] #[[file:.kiro/steering/structure.md]]"
  }
}
```

### .kiro/hooks/documentation-update.kiro.hook

```json
{
  "name": "API Documentation Updater",
  "description": "Updates API docs on API file changes",
  "version": "1",
  "when": {
    "type": "fileSaved",
    "patterns": ["src/{api,routes,endpoints,controllers}/**/*.{ts,py}"]
  },
  "then": {
    "type": "askAgent",
    "prompt": "API file modified:\n1. Analyze endpoint/parameter/response changes\n2. Update OpenAPI spec in api-specs/\n3. Use aws___search_documentation / aws___read_documentation for AWS patterns\n4. Update README API section\n5. Update JSDoc/docstrings\n6. Verify api-standards.md compliance\n\nRef: #[[file:.kiro/steering/api-standards.md]]"
  }
}
```

### .kiro/hooks/security-scan.kiro.hook

```json
{
  "name": "Security Validation Scanner",
  "description": "Pre-commit security scan",
  "version": "1",
  "when": { "type": "manual" },
  "then": {
    "type": "askAgent",
    "prompt": "Security scan:\n1. Scan for: credentials, API keys, console.log with sensitive data, SQL injection, unsafe eval()\n2. Infrastructure: run cdk-nag against CDK stacks and Checkov against Terraform\n3. Verify security-policies.md: input validation, auth checks, encryption\n4. Report: issues by severity (CRITICAL/HIGH/MEDIUM/LOW), locations, fixes, pass/fail\n\nRef: #[[file:.kiro/steering/security-policies.md]]"
  }
}
```

### .kiro/hooks/cost-check.kiro.hook

```json
{
  "name": "Infrastructure Cost Estimator",
  "description": "Estimates cost impact",
  "version": "1",
  "when": {
    "type": "fileSaved",
    "patterns": ["{infrastructure,cdk,terraform}/**/*", "**/*.template.{json,yaml,yml}"]
  },
  "then": {
    "type": "askAgent",
    "prompt": "Infrastructure modified:\n1. Identify added/modified/removed resources\n2. Price each resource with the AWS Price List Query API (`aws pricing get-products`, via aws___call_aws) or the AWS Pricing Calculator: costs per resource, region pricing, data transfer, compare previous\n3. Report: monthly estimate, delta, optimizations, unexpected costs\n4. Append to infrastructure/cost-estimates.md\n5. Flag if increase > $[THRESHOLD, e.g., 500]\n\nNote: cost figures are estimates — state assumptions explicitly"
  }
}
```

## TASK 4: MCP CONFIGURATION

### Both .vscode/mcp.json and .cursor/mcp.json (identical)

Declare exactly one MCP server — the unified AWS MCP Server. It covers AWS API calls, AWS
documentation, and regional availability, so no per-service AWS MCP servers are needed.

```json
{
  "mcpServers": {
    "aws-mcp": {
      "command": "uvx",
      "args": [
        "mcp-proxy-for-aws-cli@latest",
        "https://aws-mcp.us-east-1.api.aws/mcp",
        "--skip-auth"
      ],
      "env": {
        "AWS_REGION": "[us-east-1]",
        "AWS_PROFILE": "[profile-name]"
      }
    }
  }
}
```

## TASK 5: SUPPORTING FILES

### .gitignore

```
mcp.json.local
.env
*.log
mcp-*.log
.mcp-cache/
.aws/
.vscode/
.cursor/
.idea/
node_modules/
__pycache__/
.venv/
venv/
dist/
build/
*.js.map
.DS_Store
Thumbs.db
```

### .env.example

```bash
AWS_REGION=us-east-1
AWS_PROFILE=your-profile
DATABASE_CLUSTER_ARN=arn:aws:rds:...
DATABASE_SECRET_ARN=arn:aws:secretsmanager:...
# API_KEY=your-key
COST_ALERT_THRESHOLD=500
```

### README.md

````markdown
# [PROJECT_NAME]

[Brief description]

## Structure

- `.kiro/steering/` - AI context, standards
- `.kiro/hooks/` - Automated workflows
- `.kiro/specs/` - Feature specs (requirements, design, tasks)
- `.vscode/mcp.json`, `.cursor/mcp.json` - MCP configs

## Prerequisites

1. **uv**: install per the official guide (https://docs.astral.sh/uv/getting-started/installation/), e.g. `brew install uv` or `pipx install uv`
2. **Python 3.10+**: `uv python install 3.10`
3. **AWS CLI**: Configured
4. **Node.js**: [version]

### AWS Setup

```bash
aws configure --profile [PROFILE]
export AWS_PROFILE=[PROFILE]
export AWS_REGION=[REGION]
```
````

## Getting Started

```bash
## Install
[npm install / pip install]
## Configure
cp .env.example .env
## Edit .env
## Verify MCP
timeout 15s uvx mcp-proxy-for-aws-cli@latest https://aws-mcp.us-east-1.api.aws/mcp --skip-auth 2>&1 || echo "OK"
```

## Workflow

### Spec-Driven Development

1. Create spec in AI assistant
2. Requirements → Design → Tasks
3. Execute tasks
4. Iterate

### Agent Hooks

- **Test Sync**: Auto-creates tests on save
- **Doc Update**: Updates API docs
- **Security Scan**: Manual pre-commit scan
- **Cost Check**: Estimates infrastructure costs

### MCP Usage

```
"Use aws-mcp to read CloudWatch error logs from the last hour"
"Use aws-mcp to query the AWS Price List API and estimate costs for 3 Lambda functions"
```

## MCP Servers

One server: **aws-mcp**, the unified AWS MCP Server. Tools it exposes:

- `aws___call_aws`, `aws___run_script` - AWS API calls and scripted AWS CLI workflows
- `aws___search_documentation`, `aws___read_documentation`, `aws___recommend` - AWS documentation
- `aws___list_regions`, `aws___get_regional_availability` - region and service availability data
- `aws___retrieve_skill`, `aws___get_tasks`, `aws___get_presigned_url` - AWS skills and task helpers

## Troubleshooting

### MCP Issues

```bash
## Logs
tail -f ~/Library/Logs/Claude/mcp*.log  # Mac
tail -f %APPDATA%/Claude/mcp*.log       # Windows
## Clear cache
uv cache clean mcp-proxy-for-aws-cli
## Test
timeout 15s uvx mcp-proxy-for-aws-cli@latest https://aws-mcp.us-east-1.api.aws/mcp --skip-auth 2>&1
```

### Auth Errors

```bash
aws sts get-caller-identity --profile [PROFILE]
```

## Resources

- [MCP Docs](https://modelcontextprotocol.io)
- [Kiro](https://kiro.dev)

````
## TASK 6: INITIAL FEATURE SPEC
Create `.kiro/specs/[app-name]-core/` with three files:
### requirements.md
```markdown
# Requirements: [FEATURE_NAME]
## Overview
[2-3 paragraphs from PROJECT CONTEXT]
## User Personas
[From PROJECT CONTEXT]
## User Story 1: [From Core Features]
As a [persona]
I want to [action]
So that [benefit]
### Acceptance Criteria
WHEN [action/event]
THE SYSTEM SHALL [behavior]
AND THE SYSTEM SHALL [behavior]
WHEN [error condition]
THE SYSTEM SHALL [error handling]
[Repeat for each core feature]
## Non-Functional Requirements
### Performance
- Response time: [define]
- Throughput: [define]
- Scalability: [define]
### Security
- Authentication: [from PROJECT CONTEXT]
- Authorization: [define]
- Data protection: [encryption, PII]
### Reliability
- Availability: [define]
- Error handling: [define]
- Monitoring: [define]
## External Dependencies
[List with integration requirements]
## Data Requirements
[Schema, access patterns, retention]
## Out of Scope
[What's NOT included]
````

### design.md

````markdown
# Design: [FEATURE_NAME]

## Architecture

[High-level using tech stack from PROJECT CONTEXT]

```text
[ASCII component diagram]
```
````

## Components

### Component 1: [Name]

**Purpose**: [What it does]
**Technology**: [From tech stack]
**Responsibilities**:

- [Responsibility 1]
- [Responsibility 2]
  **Interfaces**:
- Input: [What it receives]
- Output: [What it produces]
- Dependencies: [What it calls]
  [Repeat for each component]

## Data Model

### Entity 1: [Name]

**Storage**: [DynamoDB/Aurora/S3]
**Schema**:

```typescript
{
  id: string;
  [field]: type;
  createdAt: timestamp;
  updatedAt: timestamp;
}
```

**Access Patterns**:

- Query by [field]: [use case]
- List by [criteria]: [use case]
  **Indexes**: [GSIs/LSIs]
  [Repeat for each entity]

## API Design

### [METHOD] /[path]

**Purpose**: [What it does]
**Auth**: [Required level]
**Request**:

```typescript
{ [param]: type; }
```

**Response** (200):

```typescript
{ data: {...}, meta: {...} }
```

**Errors**: 400, 401, 500
[Repeat for each endpoint]

## AWS Services

### [Service 1]

**Purpose**: [How used]
**Config**: Runtime, Memory, Timeout, Env vars
**Triggers**: [What invokes]
**Permissions**: [IAM]
[Repeat for each service]

## Security

### Auth Flow

[Describe + ASCII diagram]

### Authorization

[RBAC, ABAC, etc.]

### Data Protection

- At rest: [approach]
- In transit: [TLS]
- PII: [handling]
- Secrets: [Secrets Manager]

## Error Handling

- Client (4xx): [approach]
- Server (5xx): [approach]
- External: [retry, circuit breakers]
- Validation: [approach]

### Logging

- App: CloudWatch structured JSON
- Access: API Gateway/ALB
- Audit: CloudTrail
- Metrics: CloudWatch custom

## Testing

- **Unit**: Isolated, mocked, [coverage%]
- **Integration**: Component interactions, LocalStack
- **E2E**: Full workflows, deployed env

## Deployment

### IaC

**Tool**: AWS CDK
**Structure**:

```
infrastructure/
├── lib/[feature]-stack.ts
└── bin/app.ts
```

### Environments

- Dev, Staging, Production: [configs]

### CI/CD

1. Commit → 2. Tests → 3. Security scan → 4. Deploy staging → 5. E2E → 6. Approval → 7. Production

## Monitoring

### Metrics

- [Metric 1]: [how to measure]

### Alarms

- [Alarm 1]: Threshold, action

### Dashboards

- [Dashboard 1]: [what it shows]

## Performance

- Optimization: [strategies]
- Caching: [what, where]
- Scalability: [how components scale]

## Cost

-
- **Total**: $[total]/month
- Optimizations: [opportunities]

## Migration & Rollback

- Deployment: [blue/green, canary, rolling]
- Rollback: [how to rollback]

## Open Questions

[Design decisions needing clarification]

## References

- #[[file:.kiro/steering/tech.md]]
- #[[file:.kiro/steering/api-standards.md]]
- #[[file:.kiro/steering/security-policies.md]]

````
### tasks.md
```markdown
# Tasks: [FEATURE_NAME]
## Task 1: Setup Infrastructure
**Status**: pending | **Depends**: none | **Effort**: 2-4h
### Description
Create base infrastructure: VPC, security groups, foundational resources
### Acceptance Criteria
- [ ] CDK initialized
- [ ] VPC with subnets
- [ ] Security groups
- [ ] IAM roles (least-privilege)
- [ ] CDK Nag passes
- [ ] Deploys to dev
### Files
- `infrastructure/lib/foundation-stack.ts`
- `infrastructure/bin/app.ts`
### Testing
- Deploy to dev
- Verify in Console
- Run CDK Nag
---
## Task 2: Data Layer
**Status**: pending | **Depends**: Task 1 | **Effort**: 3-5h
### Description
Database tables/resources, data access layer
### Acceptance Criteria
- [ ] Database with schema
- [ ] Indexes for access patterns
- [ ] CRUD operations
- [ ] Connection pooling
- [ ] Error handling
- [ ] Unit tests (>80%)
### Files
- `infrastructure/lib/database-stack.ts`
- `src/data/[entity]-repository.ts`
- `src/data/[entity]-repository.test.ts`
### Testing
- Unit tests
- Integration with LocalStack
- Verify in AWS
---
## Task 3: [Component] Service
**Status**: pending | **Depends**: Task 2 | **Effort**: 4-6h
### Description
Business logic per design.md
### Acceptance Criteria
- [ ] All methods from design
- [ ] Input validation
- [ ] Error handling
- [ ] Structured logging
- [ ] Unit tests (>80%)
- [ ] Integration tests
### Files
- `src/services/[component]-service.ts`
- `src/services/[component]-service.test.ts`
### Testing
- Unit tests
- Error scenarios
- Edge cases
---
## Task 4: API Endpoints
**Status**: pending | **Depends**: Task 3 | **Effort**: 4-6h
### Description
API endpoints per design.md, api-standards.md
### Acceptance Criteria
- [ ] All endpoints
- [ ] Standard request/response format
- [ ] Auth middleware
- [ ] Authorization checks
- [ ] Input validation
- [ ] Error responses
- [ ] OpenAPI spec
- [ ] Unit tests (>80%)
### Files
- `src/api/[resource]-controller.ts`
- `src/middleware/auth.ts`
- `api-specs/[feature].openapi.yaml`
### Testing
- Endpoint tests
- Auth/authz
- Validation errors
---
## Task 5: Deploy Lambda
**Status**: pending | **Depends**: Task 4 | **Effort**: 2-3h
### Description
Package and deploy Lambda functions
### Acceptance Criteria
- [ ] Lambda in CDK
- [ ] Env vars
- [ ] IAM permissions
- [ ] CloudWatch Logs
- [ ] Layers (if needed)
- [ ] Deploys successfully
- [ ] Cold start <3s
### Files
- `infrastructure/lib/lambda-stack.ts`
- `src/lambda/[function]-handler.ts`
### Testing
- Local invocation
- Deploy to dev
- Test via API Gateway
- Check logs
---
## Task 6: Authentication
**Status**: pending | **Depends**: Task 4 | **Effort**: 3-5h
### Description
Auth flow per design.md security
### Acceptance Criteria
- [ ] Auth mechanism
- [ ] Token generation/validation
- [ ] Session management
- [ ] Secure storage
- [ ] Middleware protects endpoints
- [ ] Unit tests (>80%)
- [ ] Integration tests
### Files
- `src/auth/auth-service.ts`
- `src/middleware/auth.ts`
### Testing
- Successful auth
- Invalid credentials
- Token expiration
- Unauthorized access
---
## Task 7: Monitoring & Logging
**Status**: pending | **Depends**: Task 5 | **Effort**: 2-3h
### Description
Monitoring, logging, alarms per design.md
### Acceptance Criteria
- [ ] Structured logging
- [ ] CloudWatch Logs with retention
- [ ] Custom metrics
- [ ] Alarms
- [ ] Dashboard
- [ ] X-Ray (if applicable)
### Files
- `infrastructure/lib/monitoring-stack.ts`
- `src/utils/logger.ts`
### Testing
- Generate logs, verify
- Trigger alarms
- View dashboard
---
## Task 8: Security Hardening
**Status**: pending | **Depends**: Task 6 | **Effort**: 2-4h
### Description
Security controls per security-policies.md
### Acceptance Criteria
- [ ] CDK Nag passes
- [ ] Secrets in Secrets Manager
- [ ] Encryption at rest
- [ ] TLS/HTTPS enforced
- [ ] CORS configured
- [ ] Rate limiting
- [ ] Input sanitization
- [ ] Security headers
### Files
- `infrastructure/lib/security-stack.ts`
- `src/middleware/security.ts`
### Testing
- CDK Nag scan
- Rate limiting
- Encryption
- CORS
- Penetration testing
---
## Task 9: Integration Testing
**Status**: pending | **Depends**: Task 7, 8 | **Effort**: 3-5h
### Description
Integration tests for all user stories
### Acceptance Criteria
- [ ] Tests for each user story
- [ ] Happy paths
- [ ] Error scenarios
- [ ] Edge cases
- [ ] All acceptance criteria verified
- [ ] CI/CD integration
- [ ] Automated cleanup
### Files
- `tests/integration/[feature].test.ts`
### Testing
- Full suite
- Verify user stories
- Coverage report
---
## Task 10: Documentation
**Status**: pending | **Depends**: Task 9 | **Effort**: 2-3h
### Description
Comprehensive documentation
### Acceptance Criteria
- [ ] API docs (OpenAPI)
- [ ] README updated
- [ ] Architecture diagrams
- [ ] Deployment guide
- [ ] Troubleshooting guide
- [ ] Code comments
- [ ] Operations runbook
### Files
- `docs/[feature]/README.md`
- `docs/[feature]/architecture.md`
### Testing
- Review completeness
- Follow deployment guide
- Verify links
---
## Task 11: Performance Testing
**Status**: pending | **Depends**: Task 9 | **Effort**: 2-4h
### Description
Performance testing for non-functional requirements
### Acceptance Criteria
- [ ] Load tests
- [ ] Meets performance requirements
- [ ] Scalability verified
- [ ] Bottlenecks documented
- [ ] Cost under budget
- [ ] Results documented
### Files
- `tests/performance/[feature]-load.test.ts`
### Testing
- Load tests (expected traffic)
- Stress tests (2x traffic)
- Monitor costs
- Verify auto-scaling
---
## Task 12: Production Deployment
**Status**: pending | **Depends**: Task 10, 11 | **Effort**: 2-3h
### Description
Deploy to production with safeguards
### Acceptance Criteria
- [ ] Staging deployment
- [ ] E2E tests pass (staging)
- [ ] Security scan passed
- [ ] Cost reviewed
- [ ] Rollback plan documented
- [ ] Production deployment
- [ ] Smoke tests pass
- [ ] Monitoring healthy
### Files
- `.github/workflows/deploy-production.yml`
- `docs/[feature]/rollback-plan.md`
### Testing
- Deploy staging
- Full test suite
- Deploy production
- Smoke tests
- Monitor 24h
---
## Summary
**Total**: 12 tasks  
**Effort**: [sum estimates]  
**Critical Path**: 1→2→3→4→5→6→7→8→9→10→11→12
## Notes
- Parallelize where possible
- Review before marking complete
- Update as requirements change
````

## COMPLETION CHECKLIST

- [ ] Directory structure (.kiro/, .vscode/, .cursor/)
- [ ] 6 steering files
- [ ] 4 hooks
- [ ] 2 MCP configs (identical, single `aws-mcp` server)
- [ ] .gitignore, .env.example, README.md
- [ ] Replace all [PLACEHOLDER] values
- [ ] Initial spec: requirements.md, design.md, tasks.md

## POST-SETUP

1. Set region and profile for the `aws-mcp` server in mcp.json
2. Add custom steering files
3. Customize hook prompts
4. Review/refine generated spec
5. Create additional specs
6. Keep docs current

## SECURITY

- Never commit credentials
- Gitignore .env
- Use Secrets Manager
- Review MCP permissions
- Run security scan before commits
