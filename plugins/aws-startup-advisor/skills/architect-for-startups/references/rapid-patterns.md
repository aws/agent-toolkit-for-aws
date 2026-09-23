# Rapid Patterns

Opinionated architecture choices for startups. These differ from standard AWS guidance.

---

## Key Opinionated Choices

- **API Gateway HTTP API over REST API**: $1/M requests vs $3.50/M, lower latency. REST API only if you need request validation, caching, or usage plans.
- **Skip OpenSearch Serverless for RAG**: ~$700/month minimum. Use Bedrock Knowledge Base with managed vector store instead.
- **Aurora Serverless v2 minimum is $43/month** (0.5 ACU floor) — not truly zero-scale. DynamoDB is $0 at rest.
- **Fargate over Lambda for multi-tenant SaaS**: containers give more flexibility for tenant routing, connection pooling, long-running requests.
- **Presigned S3 URLs for uploads**: Skip Lambda entirely for large file uploads from mobile/web clients.

---

## Pattern Graduation Triggers

These are the specific signals to move from the rapid/cheap pattern to something more robust:

| Signal                                   | Action                                              |
| ---------------------------------------- | --------------------------------------------------- |
| Lambda hitting 15-min timeout            | Move that workload to Fargate                       |
| >1000 concurrent Lambda executions       | Consider Fargate for steady-state traffic           |
| DynamoDB costs > $100/month              | Evaluate access patterns, consider provisioned mode |
| Need complex SQL queries                 | Add Aurora Serverless v2 alongside DynamoDB         |
| Multiple teams deploying to same service | Split into separate services with clear APIs        |
| Customers asking about SLAs              | Add multi-AZ, health checks, monitoring             |
| >100GB of analytics data                 | Graduate from Athena+S3 to a data warehouse         |
| >10 tenants with isolation requirements  | Graduate from Lambda+DynamoDB to Fargate+Aurora     |

---

## AI-Powered App: Cost Traps

- **Bedrock Knowledge Base with OpenSearch Serverless** = ~$700/month minimum. Use Bedrock's managed vector store instead.
- Start with **Nova Micro** for classification/routing, **Nova Lite** for generation — cheapest Bedrock models.
- Store conversation history in DynamoDB, not in-memory (Lambda is stateless) and not S3 (too slow for chat).
- Don't build an agent unless you need tool use — `InvokeModel` directly is simpler and cheaper.
