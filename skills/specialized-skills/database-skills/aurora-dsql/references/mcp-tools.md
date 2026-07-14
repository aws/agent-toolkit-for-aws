# MCP Tools for the Aurora DSQL Skill

This file describes how the Aurora DSQL skill interacts with MCP servers. The skill PREFERS
direct `psql` (via [`scripts/psql-connect.sh`](../scripts/psql-connect.sh)) and PostgreSQL drivers
over MCP-mediated DSQL execution. MCP is consulted primarily for **AWS knowledge** (docs lookup,
service limits, AWS API calls) via the official AWS MCP Server.

## AWS MCP Server (recommended)

When connected, the AWS MCP Server provides:

**Knowledge tools** (no extra setup beyond the server itself):

- `aws___search_documentation` — search across all AWS documentation, including DSQL service
  docs and skills. PREFER for verifying DSQL limits or finding the canonical doc page.
- `aws___read_documentation` — fetch a specific AWS docs page in markdown form.
- `aws___recommend` — content recommendations related to a specific docs page.
- `aws___retrieve_skill` — fetch the full content of a domain-specific AWS skill discovered via
  `aws___search_documentation`.
- `aws___list_regions` / `aws___get_regional_availability` — confirm DSQL or a dependent feature
  is available in the target region before recommending an architecture.

**AWS API tools** (require IAM credentials):

- `aws___call_aws` — execute an authenticated AWS API call. Useful for `dsql:CreateCluster`,
  `dsql:GetCluster`, `dsql:ListClusters`, etc., when the user wants the assistant to drive cluster
  lifecycle operations directly. For asynchronous DSQL operations (`CreateCluster`,
  `DeleteCluster`) poll readiness by re-invoking `aws___call_aws` with `dsql:GetCluster` — DSQL
  returns the cluster status directly, not an MCP task ID.
- `aws___run_script` — sandboxed Python with AWS API access. Useful for multi-step or parallel
  workflows like "list every cluster in the region, check whose tags include `Environment=eval`,
  then describe the matching ones." May return an MCP task ID for very long scripts.
- `aws___get_presigned_url` — generate pre-signed Amazon S3 URLs for uploading/downloading files
  (e.g., DSQL bulk-loading source data).

**MCP session tools** (no IAM):

- `aws___get_tasks` — poll MCP-side task IDs returned by `aws___call_aws` or `aws___run_script`
  when the MCP wrapper queues a long-running invocation. **NOT** for polling AWS-API-side async
  operations like `dsql:CreateCluster` — those return their status field directly.

See [documentation-tools.md](documentation-tools.md) for per-tool detail and example calls.

Setup, auth, and per-assistant invocation differ by client — see the official
[AWS MCP Server docs](https://docs.aws.amazon.com/aws-mcp/latest/userguide/mcp-server.html).

## Database Operations

Database operations against a DSQL cluster run through `psql` by default. The wrapper script
[`scripts/psql-connect.sh`](../scripts/psql-connect.sh) handles IAM auth token generation, TLS
defaults, application_name tagging, and single-statement guards.

See [database-tools.md](database-tools.md) for the full read / write / schema-discovery patterns.

## Detailed References

- **[input-validation.md](input-validation.md)** — **MUST** load before building any query.
  Build SQL with `safe_query.build()`, which rejects raw strings by construction.
- **[safe_query.py](../scripts/safe_query.py)** — the validated-query helper module.
- **[database-tools.md](database-tools.md)** — `psql`-based read / write / schema patterns.
- **[workflow-patterns.md](workflow-patterns.md)** — common multi-step workflow patterns.

## Additional Resources

- [Aurora DSQL Documentation](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/)
- [Aurora DSQL Connectivity Tools](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/aws-sdks.html)
- [AWS MCP Server](https://docs.aws.amazon.com/aws-mcp/latest/userguide/mcp-server.html)
