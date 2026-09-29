# Knowledge Bases (retrieval, agentic retrieval and RAG) — Decision Guide & Routing

Choose the knowledge base type first, then route to the correct setup and retrieval reference. Creation and the query API differ by type.

## Decision: Managed KB vs Customer-managed KB

**Default to the Managed Knowledge Base (MKB)** for agentic retrieval and RAG on Bedrock — AWS recommends it and it fully manages storage, chunking, parsing, and retrieval, with no infrastructure to provision. Use it for essentially all new RAG work.

Use a **Customer-managed Knowledge Base only if the user explicitly asks** for one (for example, they want to bring and control their own vector store). Do not screen the request against a capability list or try to predict whether MKB can satisfy it — default to MKB and proceed; if a specific configuration is not supported, let the create call surface the error. Connector, feature, quota, and region specifics change frequently and differ by type — consult the [Bedrock Knowledge Base docs](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html); this skill deliberately does not maintain a capability matrix.

## Create / manage a knowledge base

- **Managed KB (default):** you MUST read [managed KB setup](managed-knowledge-bases-setup.md) and execute it step by step (create → connect a data source via the managed connector → ingest/sync → verify with `Retrieve`). Do NOT summarize — execute each step, respecting all MUST constraints before proceeding.
- **Customer-managed KB (only if explicitly asked):** you MUST read [customer-managed KB setup](knowledge-bases-setup.md) and execute its 7-step procedure (choose chunking → choose/provision vector store → IAM role → create KB → data source → ingest → verify).

## Query a knowledge base

- **Managed KB:** you MUST read [managed KB retrieval](managed-knowledge-bases-retrieval.md). Use `Retrieve` (single-shot chunks) or `AgenticRetrieveStream` (agentic: plan → retrieve → evaluate → iterate across multiple KBs — check the service quota). `AgenticRetrieveStream` is streaming ⇒ **SDK-only** (not the AWS CLI). `RetrieveAndGenerate` (synthesized answer with citations) is the Customer-managed path; if you specifically need it on MKB, verify support against the docs.
- **Customer-managed KB:** you MUST read [customer-managed KB retrieval](knowledge-bases-retrieval.md). Present the retrieve-and-generate / retrieve / manual modes so the user selects the right one.

## Security

Before creating or querying, review the Security Considerations in [managed KB setup](managed-knowledge-bases-setup.md) and [managed KB retrieval](managed-knowledge-bases-retrieval.md): least-privilege connector IAM roles, customer-managed KMS encryption, and CloudTrail data-event logging for KB access apply to both the create and query paths.
