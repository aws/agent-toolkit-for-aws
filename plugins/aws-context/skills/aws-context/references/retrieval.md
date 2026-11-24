# Retrieving from AWS Context

## Pick the path

Use **AgenticRetrieveStream** in the following cases:

- The question names no specific table, dashboard, document or other entity. For example "How do we calculate monthly active users?" or "What data do we have about customer churn?"
- The task's retrieval plan is ambiguous and needs data discovery, research and retrieval over both documents and tables.
- The question is about a policy, definition, procedure or other content inside documents, and the user does not name the document. For example "How long do customers have to request a refund?" Call AgenticRetrieveStream directly; do not search first to find the document.
- The answer needs facts combined across several entities. For example "Which dashboards depend on tables owned by the payments team?"
- The answer needs data values, not just metadata. For example "What was total refund volume last quarter?" Agentic retrieval can query table rows. Search and traverse return only what the graph knows about the data.

Pass the user's question and the relevant conversation turns, then answer from its final result.

When the data entities to retrieve from are known, use SearchAgentContext and
TraverseAgentContext for lower latency. For example "Find the orders table", "What
columns does fact_orders have?" or "What is connected to the revenue dashboard?"

## Search and traverse

1. Call SearchAgentContext with a query text of what you need. Start with the automatic search type.
2. Call TraverseAgentContext on the best match to see its neighborhood and the edges that connect it.
3. Answer, or decide what to search or traverse next.

If two turns of SearchAgentContext and TraverseAgentContext have not answered the
question, switch to AgenticRetrieveStream.

## When agentic retrieval needs consent

If AgenticRetrieveStream returns a URL asking the user to authorize a
connected source, show the URL, wait for the user to finish, then retry.

## When the graph has no answer

If nothing relevant comes back after one retry on AgenticRetrieveStream, tell the user the graph
has no answer. If the user says the graph is wrong or missing something, read
`curation.md`.
