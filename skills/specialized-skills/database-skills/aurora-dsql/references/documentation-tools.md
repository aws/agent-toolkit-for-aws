# AWS Documentation Tools (via the AWS MCP Server)

Part of the [Aurora DSQL Skill](../SKILL.md). When the [AWS MCP Server](https://docs.aws.amazon.com/aws-mcp/latest/userguide/mcp-server.html)
is connected, these tools are available for AWS documentation lookups, including DSQL service docs.

The canonical tool list lives at
[Understanding the MCP Server tools](https://docs.aws.amazon.com/aws-mcp/latest/userguide/understanding-mcp-server-tools.html);
the entries below cover the ones load-bearing for DSQL workflows.

---

## AWS Knowledge Tools

### `aws___search_documentation`

**Use for:** finding relevant AWS documentation, looking up DSQL features, troubleshooting.

Search across all AWS documentation, including API references, best practices, service guides,
and skills. Use the topic filter to search skills exclusively, or see
skills alongside general knowledge search results. Find relevant information from multiple AWS
knowledge sources.

**Common DSQL queries:**

- `aurora dsql transaction limits`
- `aurora dsql index limits`
- `aurora dsql connection limits`
- `aurora dsql authentication token`

### `aws___read_documentation`

**Use for:** retrieving the full markdown of a specific AWS documentation page when a search
result snippet isn't enough. Pass the URL of the docs page you want to read.

### `aws___recommend`

**Use for:** getting content recommendations for a specific AWS documentation page based on
related topics and commonly viewed content.

### `aws___retrieve_skill`

**Use for:** retrieving the full content of a domain-specific AWS skill (workflows, context, best
practices, decision frameworks, step-by-step procedures). Discover available skills via
`aws___search_documentation` first, then call `aws___retrieve_skill` with the skill name.

### `aws___list_regions`

**Use for:** enumerating the AWS region identifiers and names. Pair with
`aws___get_regional_availability` when you need to confirm DSQL availability in a specific
region before recommending an architecture.

### `aws___get_regional_availability`

**Use for:** checking whether DSQL (or a feature you depend on) is available in the user's
target region before recommending an architecture. Supports per-service / per-feature
availability checks.

---

## AWS API Tools

### `aws___call_aws`

**Use for:** authenticated AWS API calls. Useful for `dsql:CreateCluster`, `dsql:GetCluster`,
`dsql:ListClusters`, `dsql:DeleteCluster`, etc., when the assistant should drive cluster
lifecycle directly. Long-running calls return a task ID — poll it with `aws___get_tasks`.

### `aws___run_script`

**Use for:** sandboxed Python with AWS API access. Useful for multi-step or parallel workflows
("list every cluster in the region, check whose tags include `Environment=eval`, then call
`GetCluster` on the matching ones"). Long-running scripts return a task ID — poll with
`aws___get_tasks`.

### `aws___get_tasks`

**Use for:** polling the status of long-running tasks started by `aws___call_aws` or
`aws___run_script`. **MUST** call when a previous tool invocation returned a task ID with a
working status — without this, the agent can't observe completion or final output.

### `aws___get_presigned_url`

**Use for:** generating pre-signed Amazon S3 URLs for uploading/downloading files. Relevant
when a DSQL workflow involves S3-hosted SQL scripts, exported data, or the bulk-loading guide.

---

For tool-call shape, parameter details, and per-assistant invocation, see the official
[AWS MCP Server tool reference](https://docs.aws.amazon.com/aws-mcp/latest/userguide/understanding-mcp-server-tools.html).
