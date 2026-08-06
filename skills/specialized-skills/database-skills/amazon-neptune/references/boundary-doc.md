# Neptune Skill — Ownership Boundary Document

What this skill owns directly, what it delegates, and what it defers to AWS documentation.

## What the Skill Owns Directly

* **Intent routing.** Classifying user requests across sub-skills and selecting the correct pipeline.
* **Architecture guidance.** Recommending Neptune Database vs Analytics, property graph vs RDF, Gremlin vs openCypher, and when NOT to use Neptune.
* **Data modeling patterns.** Graph schema design for fraud detection, customer 360, service dependencies, access control, supply chain, knowledge graphs, semantic layers.
* **Query generation.** Producing Gremlin, openCypher, and SPARQL queries with correct pagination, parameterization, and optimization patterns.
* **Connection recipes.** Generating SDK connection code (Python, Java, Node.js) with correct VPC, TLS, IAM auth, and public endpoint configuration for both Neptune Database and Analytics.
* **GraphRAG pipeline design.** Designing document ingestion, entity extraction, graph construction, embedding storage, and two-phase retrieval with Neptune Analytics.
* **Agentic memory architecture.** Designing long-term (Neptune) + short-term (DynamoDB) memory systems with graph traversal and vector search.
* **Migration planning.** Producing Neo4j → Neptune migration runbooks, compatibility matrices, query porting guides, and APOC alternatives.
* **Troubleshooting.** Diagnosing connectivity failures, query timeouts, supernodes, cold starts, and bulk loader errors.
* **Performance optimization.** Instance sizing, serverless vs provisioned, read replicas, query profiling, and CloudWatch monitoring.
* **Input validation.** Running `scripts/input_validator.py` before write-path operations.

## What the Skill Delegates

* **Infrastructure provisioning** — The skill generates AWS CLI commands, CDK stacks, or boto3 code. The user or their CI/CD pipeline executes them.
* **Data-plane operations** — The skill generates Gremlin/openCypher queries. The user runs them against their Neptune endpoint.
* **LLM calls** — For GraphRAG entity extraction and agentic memory, the skill generates prompts and code structure. The user provides their LLM client (Bedrock, OpenAI, etc.).

## What the Skill Defers to AWS Documentation

* **Parameter group tuning** — Full parameter reference and advanced optimization.
* **Service limits and quotas** — Current limits for instances, connections, storage.
* **Engine release notes** — Patch contents, deprecation timelines, version-specific changes.
* **Compliance certifications** — HIPAA, PCI, FedRAMP coverage details.
* **Pricing** — The skill links to official pricing pages. It does not invent price points.
* **API reference** — Full request/response schemas, error codes, throttling behavior.

## AI-Generated Output Disclaimer

All code, configurations, CLI commands, and recommendations produced by this skill are AI-generated. Review all outputs before deploying to production environments.
