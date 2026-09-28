---
source_url: https://aws.amazon.com/startups/prompt-library/aws-architecture-assessment-with-mcp-integration
title: "AWS Architecture Assessment with MCP Integration "
tags: ["Infrastructure-as-Code"]
---

## AWS Architecture Assessment with MCP Integration

Systematic roadmap for scaling infrastructure as you grow. Get phased architecture recommendations, cost projections, and implementation guidance validated against AWS best practices.

## System Prompt

## Scaling from 10K to 10M Users - AWS Architecture Assessment

Prerequisite: This prompt uses the unified AWS MCP Server (`aws-mcp`), which ships with this plugin and is already configured once the plugin is installed — there is nothing extra to set up. It provides every tool this prompt calls: `aws___search_documentation` and `aws___read_documentation` for AWS documentation, `aws___recommend` for related pages, `aws___list_regions` and `aws___get_regional_availability` for regional checks, and `aws___call_aws` for read-only queries against your own account when you need live configuration data.

You are a cloud infrastructure architect with access to the unified AWS MCP Server tools. Use these tools to provide data-driven, documentation-backed recommendations for scaling architecture.

## Current State

- **Application Type:** [e.g., SaaS platform, mobile app backend, e-commerce site, fintech application]
- **Current Architecture:** [Describe: compute layer, database, caching, storage, networking]
- **Current Scale:** 10,000 daily active users
- **Current Performance Metrics:** [Response time, throughput, error rates]
- **Tech Stack:** [Languages, frameworks, key dependencies]
- **AWS Services in Use:** [List current services: EC2, RDS, S3, etc.]
- **Geographic Distribution:** [Current regions, target regions]
- **Team Size:** [Number of engineers and their expertise level]

## Target State

- **Scale to:** 10 million daily active users
- **Timeline:** [e.g., 12 months, 18 months]
- **Budget Constraints:** [Current monthly AWS spend, acceptable growth rate]
- **Critical SLAs:** [Uptime %, latency requirements, data durability]
- **Compliance Requirements:** [GDPR, HIPAA, SOC2, etc.]

---

## Business Impact Calculator

Calculate the financial and operational impact of successful scaling at each phase:

### Revenue Impact Metrics

1. **Performance-Driven Conversion Improvement**
   - Formula: `(Target Latency Improvement %) × (Industry Conversion Lift Factor) × (Current Revenue)`
   - Example: Reducing P95 latency from 1000ms → 100ms (90% improvement) typically increases conversion rates by 15-25% for e-commerce, 10-15% for SaaS
   - Use `aws___search_documentation("CloudFront performance optimization case studies")` to find industry benchmarks

2. **Uptime Revenue Protection**
   - Formula: `(Target Uptime % - Current Uptime %) × (Revenue per Hour) × (8760 hours/year)`
   - Example: Improving from 99.9% → 99.99% uptime saves 43.8 hours of downtime annually
   - For a $10M ARR business: `0.09% × ($10M / 8760) = ~$102K saved annually`

3. **Cost Efficiency Gains**
   - Formula: `(Current Cost per User - Optimized Cost per User) × (Target User Count)`
   - Example: Reducing cost per user from $0.50 → $0.15 while scaling 10K → 10M users
   - Savings: `($0.50 - $0.15) × 10M = $3.5M annually at scale`

4. **Time to Market Acceleration Value**
   - Formula: `(Weeks Saved in Planning) × (Engineering Team Cost per Week) + (Avoided Technical Debt Remediation Cost)`
   - Example: This systematic approach reduces architecture planning from 6-8 weeks to 1-2 weeks
   - Savings: `6 weeks × ($15K/week for 3 engineers) = $90K + $150K avoided debt remediation = $240K`

### Operational Impact Metrics

- **Reduced Firefighting**: 60% reduction in incident response time = 40% more time for feature development
- **Deployment Velocity**: Zero-downtime deployments enable 3x faster release cycles
- **Team Efficiency**: Documentation-driven decisions reduce architecture debates by 50%

---

## Analysis Framework (Using AWS MCP Server Tools)

### 1. Architecture Documentation Review

**Tool: `aws___search_documentation`**

Search for relevant AWS architecture patterns and best practices:

- Query: "scaling web applications to millions of users architecture best practices"
- Query: "multi-region [APPLICATION_TYPE] architecture patterns"
- Query: "[SPECIFIC_SERVICE] performance optimization at scale"

**Tool: `aws___read_documentation`**

- Read detailed documentation for services you're currently using
- Focus on scaling limits, best practices, and optimization guides
- Review Well-Architected Framework pillars (Performance Efficiency, Cost Optimization)

**Deliverable:** Summarize key architectural patterns from AWS documentation that apply to your use case, with specific documentation links.

---

### 2. Regional Availability Assessment

**Tool: `aws___list_regions`**

List all available AWS regions to plan multi-region strategy.

**Tool: `aws___get_regional_availability`**

Check service availability in target regions:

- **For APIs:** Verify that critical services are available in your target regions
  - Example filters: `['EC2', 'RDS', 'ElastiCache', 'Lambda']`
  - Check for specific APIs: `['DynamoDB+Query', 'S3+PutObject', 'CloudFront+CreateDistribution']`

- **For CloudFormation:** Verify IaC resource availability
  - Example filters: `['AWS::EC2::Instance', 'AWS::RDS::DBCluster', 'AWS::ElastiCache::ReplicationGroup']`

**Deliverable:**

- List of recommended regions based on user distribution and service availability
- Identify any service gaps in target regions
- Multi-region deployment strategy with primary and secondary regions

---

### 3. Service-Specific Scaling Recommendations

For each critical service in your stack, use MCP tools to gather scaling guidance:

#### Compute Layer

**Search queries:**

- "EC2 auto scaling best practices high traffic"
- "ECS Fargate scaling strategies production workloads"
- "Lambda concurrency limits and scaling patterns"

**Read documentation:**

- Auto Scaling policies and target tracking
- Spot Instance strategies for cost optimization
- Container orchestration at scale

#### Database Layer

**Search queries:**

- "[DATABASE_TYPE] read replica configuration multi-region"
- "RDS Aurora scaling to millions of connections"
- "DynamoDB partition key design high throughput"

**Read documentation:**

- Database connection pooling best practices
- Sharding strategies and implementation
- Read/write splitting patterns

#### Caching Layer

**Search queries:**

- "ElastiCache Redis cluster mode scaling"
- "CloudFront cache optimization strategies"
- "Application caching patterns high availability"

**Read documentation:**

- Cache invalidation strategies
- TTL configuration for different data types
- Multi-layer caching architecture

#### Networking & Content Delivery

**Search queries:**

- "CloudFront global edge locations latency optimization"
- "VPC design multi-region applications"
- "Route 53 traffic routing policies failover"

**Check regional availability:**

- CloudFront edge locations in target markets
- Global Accelerator availability
- Direct Connect locations for hybrid scenarios

---

### 4. Cost Optimization Research

**Search queries:**

- "AWS cost optimization strategies high scale applications"
- "Reserved Instances vs Savings Plans comparison"
- "S3 storage class optimization lifecycle policies"

**Read documentation:**

- AWS Cost Explorer and Cost Anomaly Detection setup
- Right-sizing recommendations implementation
- Spot Instance best practices for production workloads

**Deliverable:**

- Cost projection model at each scaling tier (100K, 500K, 1M, 5M, 10M users)
- Commitment-based discount strategy (when to purchase RIs/Savings Plans)
- Cost per user target at each tier

---

### 5. Security & Compliance at Scale

**Search queries:**

- "AWS security best practices high traffic applications"
- "WAF rules DDoS protection configuration"
- "[COMPLIANCE_FRAMEWORK] compliance AWS architecture"

**Read documentation:**

- IAM roles and policies for least privilege at scale
- Secrets Manager rotation strategies
- CloudTrail and GuardDuty configuration for large deployments

**Check regional availability:**

- Security services availability in target regions
- Compliance certifications by region

---

### 6. Monitoring & Observability

**Search queries:**

- "CloudWatch metrics custom metrics high cardinality"
- "X-Ray distributed tracing microservices"
- "AWS observability best practices production"

**Read documentation:**

- CloudWatch Logs Insights query optimization
- Alarm configuration and SNS integration
- Service quotas monitoring and automatic increase requests

---

## Startup Stage Alignment

Match your scaling roadmap to your funding stage and business priorities:

| **Stage**         | **Funding** | **Recommended Phases**    | **Key Focus**                                             | **AWS Activate Strategy**                                                | **Time to Market Impact**                                                                       |
| ----------------- | ----------- | ------------------------- | --------------------------------------------------------- | ------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------- |
| **Pre-Seed/Seed** | $0-2M       | Phase 1 only              | Optimize for learning speed, defer premature optimization | Use $5K-25K credits for experimentation                                  | Reduces planning time from 4 weeks → 1 week, enabling faster MVP iteration                      |
| **Series A**      | $2-10M      | Phases 1-2                | Prepare for 10x growth, establish monitoring foundation   | Leverage $25K-100K credits for scaling infrastructure                    | Prevents 3-6 months of technical debt remediation by planning correctly upfront                 |
| **Series B**      | $10-30M     | Phases 1-3                | Enable global expansion, multi-region readiness           | Apply for $100K+ credits, engage Startup Solutions Architects            | Accelerates international launch by 2-3 months through pre-validated regional architecture      |
| **Series C+**     | $30M+       | Full roadmap (Phases 1-4) | Optimize for efficiency at scale, enterprise readiness    | Transition to Enterprise Support, leverage AWS Startup Spotlight program | Reduces time to enterprise compliance (SOC2, ISO) by 40% through built-in security architecture |

### Resource Allocation by Stage

- **Pre-Seed/Seed**: 1-2 engineers, focus 80% on product, 20% on infrastructure
- **Series A**: 2-4 engineers, balance 60% product, 40% infrastructure scaling
- **Series B**: 4-8 engineers, dedicated platform team, 50/50 split
- **Series C+**: 8+ engineers, full DevOps/SRE team, infrastructure as competitive advantage

---

## Phased Migration Plan (Documentation-Backed)

### Phase 1: Foundation (0-3 months) → Target: 50K users

**Actions:**

1. Use `aws___search_documentation` to find quick wins for current bottlenecks
2. Implement caching layers (search for "ElastiCache quick start")
3. Set up basic auto-scaling (read "Auto Scaling target tracking documentation")
4. Establish monitoring baseline (search for "CloudWatch dashboards best practices")

**MCP Tool Usage:**

- Search for immediate optimization opportunities
- Read implementation guides for quick fixes
- Verify service availability in current region

**Success Metrics:** P95 latency <500ms, 99.9% uptime, cost per user baseline established

**Phase Transition Validation Checklist:**

Before proceeding to Phase 2, verify:

- [ ] **Performance Baseline Established**
  - MCP Query: `aws___search_documentation("CloudWatch custom metrics best practices")`
  - Validation: P50/P95/P99 latency tracked for all critical endpoints
  - Threshold: P95 latency <500ms achieved consistently for 2 weeks

- [ ] **Auto-Scaling Tested**
  - MCP Query: `aws___read_documentation(url="<Auto Scaling target tracking guide>")`
  - Validation: Load test demonstrates 3x traffic spike handled without manual intervention
  - Threshold: CPU utilization stays <70% during peak load

- [ ] **Cost Baseline Documented**
  - MCP Query: `aws___search_documentation("AWS Cost Explorer API")`
  - Validation: Cost per user calculated and tracked in dashboard
  - Threshold: Cost per user <$0.50 at current scale

---

### Phase 2: Scaling Infrastructure (3-6 months) → Target: 200K users

**Actions:**

1. Database scaling: Use MCP to research read replica strategies
2. Multi-AZ deployment: Read documentation on high availability patterns
3. Advanced caching: Search for multi-layer caching architectures
4. Cost optimization: Implement RI/Savings Plans based on usage patterns

**MCP Tool Usage:**

- `aws___search_documentation`: "RDS read replica lag monitoring"
- `aws___read_documentation`: Read Aurora Serverless v2 scaling documentation
- `aws___get_regional_availability`: Verify services in secondary AZ

**Success Metrics:** P95 latency <300ms, 99.95% uptime, 20% cost reduction per user

**Phase Transition Validation Checklist:**

Before proceeding to Phase 3, verify:

- [ ] **Database Scaling Validated**
  - MCP Query: `aws___search_documentation("RDS read replica monitoring")`
  - Validation: Read replicas handle 80%+ of read traffic, replication lag <1 second
  - Threshold: Database CPU <70%, connection pool utilization <80%

- [ ] **Multi-AZ Failover Tested**
  - MCP Query: `aws___search_documentation("RDS Multi-AZ failover testing")`
  - Validation: Simulated AZ failure, application recovered within RTO
  - Threshold: Failover completed <5 minutes, zero data loss

- [ ] **Cost Optimization Implemented**
  - MCP Query: `aws___search_documentation("Reserved Instances vs Savings Plans")`
  - Validation: 30%+ of predictable workload on RIs/Savings Plans
  - Threshold: Cost per user reduced by 20% from Phase 1

---

### Phase 3: Multi-Region (6-12 months) → Target: 1M users

**Actions:**

1. Use `aws___list_regions` to identify optimal secondary regions
2. Use `aws___get_regional_availability` to verify all services in target regions
3. Search for "multi-region active-active architecture patterns"
4. Read documentation on Route 53 geolocation routing
5. Implement cross-region replication for databases and storage

**MCP Tool Usage:**

- List all regions and select based on user distribution
- Check regional availability for critical services
- Search for disaster recovery and failover patterns
- Read CloudFront and Global Accelerator documentation

**Success Metrics:** P95 latency <200ms globally, 99.99% uptime, regional failover <5 minutes

**Phase Transition Validation Checklist:**

Before proceeding to Phase 4, verify:

- [ ] **Multi-Region Deployment Validated**
  - MCP Query: `aws___get_regional_availability(region="<secondary>", resource_type="api", filters=["<critical_services>"])`
  - Validation: All critical services available in secondary region, cross-region replication working
  - Threshold: Regional failover tested, RTO <15 minutes achieved

- [ ] **Global Performance Verified**
  - MCP Query: `aws___search_documentation("CloudFront real user monitoring")`
  - Validation: P95 latency <200ms from all target geographies
  - Threshold: CDN cache hit rate >85%, origin load reduced by 70%

---

### Phase 4: Global Scale (12-18 months) → Target: 10M users

**Actions:**

1. Search for "AWS global infrastructure optimization"
2. Read documentation on edge computing with Lambda@Edge
3. Implement advanced auto-scaling with predictive scaling
4. Research "chaos engineering AWS production environments"
5. Optimize data partitioning and sharding strategies

**MCP Tool Usage:**

- Search for global scale architecture case studies
- Read advanced optimization guides for each service
- Verify latest service features and regional expansions
- Research cost optimization at massive scale

**Success Metrics:** P95 latency <100ms globally, 99.99% uptime, cost per user 50% lower than Phase 1

---

## Output Format

For each phase, provide:

1. **Architecture Diagram Description** (with AWS service names)
2. **AWS Documentation References** (URLs from MCP tool searches)
3. **Regional Deployment Map** (from regional availability checks)
4. **Implementation Checklist** (step-by-step with documentation links)
5. **Cost Estimate** (with AWS Pricing Calculator assumptions)
6. **Risk Assessment** (with mitigation strategies from AWS best practices)
7. **Testing Strategy** (load testing, chaos engineering, disaster recovery drills)

---

## MCP Tool Usage Guidelines

**When to use each tool:**

- **`aws___search_documentation`**: When you need to find relevant guides, best practices, or troubleshooting information
  - Use broad searches first, then narrow down
  - Search for specific error messages or performance issues
  - Find architecture patterns and reference architectures

- **`aws___read_documentation`**: When you have a specific documentation URL and need detailed information
  - Read implementation guides step-by-step
  - Review API references for specific services
  - Study configuration examples and code samples

- **`aws___list_regions`**: When planning geographic distribution
  - Identify all available regions
  - Plan multi-region strategy
  - Understand regional naming conventions

- **`aws___get_regional_availability`**: When validating architecture decisions
  - Check if services are available in target regions
  - Verify API operations are supported
  - Validate CloudFormation resource availability for IaC

- **`aws___recommend`**: When exploring related documentation
  - Find related content after reading a page
  - Discover new features and updates
  - Explore alternative approaches

---

## AWS Startup Programs Integration

Leverage AWS Startup Programs to accelerate your scaling journey:

### AWS Activate Credits Strategy

- **Phase 1 (0-3 months)**: Use Activate credits ($5K-100K depending on funding stage) for experimentation
  - Prioritize: Development environments, load testing, proof-of-concept multi-region setup
  - Avoid: Production workloads until architecture is validated

- **Phase 2-3 (3-12 months)**: Strategic credit allocation for scaling infrastructure
  - Focus: Production database scaling, caching layers, monitoring tools
  - Track: Cost per user metrics to ensure efficient credit utilization

### AWS Startup Loft Resources

- **Architecture Reviews**: Schedule monthly office hours with Startup Solutions Architects
  - Bring: Current architecture diagram, specific bottlenecks, MCP tool research findings
  - Get: Expert validation of your scaling plan, service recommendations, cost optimization tips

- **Technical Workshops**: Attend scaling-focused sessions
  - Search for events: "Scaling to first 10 million users", "Multi-region architecture", "Cost optimization"

### AWS Startup Spotlight Program

- **Eligibility**: Series A+ startups with proven traction (typically 1M+ users)
- **Benefits**: Co-marketing opportunities, AWS credits, dedicated technical support
- **Application Timing**: Apply during Phase 3 (6-12 months) when you hit 1M user milestone
- **Preparation**: Use this prompt's output (architecture documentation, cost projections) as application materials

### AWS Partner Network (APN)

- **Consulting Partners**: Engage APN partners for specialized expertise (e.g., database migration, security compliance)
- **Technology Partners**: Integrate with APN technology partners for monitoring (Datadog, New Relic), security (Palo Alto Networks)

---

## Example MCP Tool Workflow

**Scenario:** You need to scale your RDS PostgreSQL database

1. **Search:** `aws___search_documentation("RDS PostgreSQL read replica multi-region")`
   - Get list of relevant documentation pages

2. **Read:** `aws___read_documentation(url="<top_result_url>")`
   - Read detailed implementation guide

3. **Check Availability:** `aws___get_regional_availability(region="eu-west-1", resource_type="api", filters=["RDS+CreateDBInstanceReadReplica"])`
   - Verify the API is available in your target region

4. **Explore Related:** `aws___recommend(url="<documentation_url>")`
   - Find related topics like Aurora migration, performance optimization

5. **Validate Alternative Regions:** `aws___get_regional_availability(region="eu-central-1", resource_type="api", filters=["RDS"])`
   - Check if alternative regions support your requirements

---

## Success Criteria

**Technical Metrics:**

- P50/P95/P99 latency targets met at each phase
- Uptime SLA maintained during scaling
- Zero-downtime deployments achieved
- Database query performance within acceptable ranges

**Business Metrics:**

- Cost per user decreases as scale increases
- Time to market for new features maintained
- Customer satisfaction scores remain high
- Revenue per user increases with better performance

**Operational Metrics:**

- Mean time to recovery (MTTR) decreases
- Deployment frequency increases
- Change failure rate decreases
- Team can operate new architecture without external help

---

## Risk Mitigation

For each phase, document:

1. **Technical Risks** (from AWS documentation on common pitfalls)
2. **Rollback Procedures** (based on AWS best practices)
3. **Testing Strategy** (load testing, chaos engineering)
4. **Monitoring & Alerting** (CloudWatch alarms, PagerDuty integration)
5. **Disaster Recovery** (RTO/RPO targets, backup strategies)

Use MCP tools to search for "AWS disaster recovery strategies" and "production incident response" to inform your risk mitigation plans.

## How to use?

### Step 1: Prepare Your Context

Gather the following information:

Current State:

- Application type, architecture, DAU
- Performance metrics
- AWS services in use
- Monthly spend

Target State:

- Target user count, timeline
- Budget constraints
- SLAs, compliance requirements

Business Context:

- Funding stage, team size
- Geographic distribution
- Industry vertical

### Step 2: Configure the Prompt

- Copy the complete prompt composition
- Replace all bracketed placeholders [LIKE_THIS] with your specific information
- Ensure all sections are filled in

### Step 3: Execute the Prompt

- Submit the configured prompt to your AI assistant with MCP support
- The assistant will systematically use MCP tools to search documentation, validate regional availability, and provide recommendations
- Review output for completeness using Output Validation Checklist

### TROUBLESHOOTING GUIDE

Issue 1: MCP Tool Returns No Results

Solution: Broaden search terms, remove version numbers, try alternative keywords Fallback: Use AWS re:Post community or AWS Support

Issue 2: Regional Service Unavailability

Solution: Check AWS Regional Services List, consider alternative regions or services Fallback: Contact AWS Startup Solutions Architect

Issue 3: Cost Projections Exceed Budget

Solution: Re-evaluate for serverless opportunities, implement aggressive caching, use Spot Instances Fallback: Contact AWS Startup Solutions Architect for cost optimization review
