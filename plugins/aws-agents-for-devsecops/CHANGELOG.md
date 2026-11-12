# Changelog

Changes to the `aws-agents-for-devsecops` plugin that can change how it behaves for a user. Read this when a skill or command stops working as it used to.

## 1.2.0

### Release readiness review is now code change risk analysis

The `analyzing-release-readiness` skill and the `/aws-agents-for-devsecops:release-readiness` command call the code change risk analysis tools on the AWS DevOps Agent MCP server.

| Old tool | New tool |
|---|---|
| `create_release_readiness_review` | `create_code_change_risk_analysis` |
| none | `list_code_change_risk_analyses` |
| `cancel_release_readiness_review` | `cancel_code_change_risk_analysis` |
| `get_release_readiness_report` | `get_code_change_risk_analysis_report` |

- The old tools still exist on the server and do the same thing, so older copies of the plugin keep working.
- The server picks the task type (`CODE_CHANGE_RISK_ANALYSIS` or `RELEASE_READINESS_REVIEW`). `list_code_change_risk_analyses` returns reviews of both types.
- The aws-mcp fallback creates `CODE_CHANGE_RISK_ANALYSIS` tasks.
- Report files are saved as `code-change-risk-analysis-<timestamp>.md`, and the local flow pushes `feat/code-change-risk-analysis` and `feat/code-change-risk-analysis-fix` branches.
- The skill and command names did not change.

**If the skill falls back to aws-mcp, or prompts for every call:** a tool allowlist (for example `permissions.allow` in Claude Code settings) or an MCP client that connected before the server update may only know the old tool names. Allow the new tool names and restart the session.

### Review depth

The skill and command send `review_depth` instead of `skip_automated_testing` when starting an analysis.

| `review_depth` | Meaning | Older equivalent |
|---|---|---|
| `static-analysis` | Static analysis only | `skip_automated_testing=true` |
| `verification-testing` | Static analysis plus automated testing | `skip_automated_testing=false` |

- The skill still asks the user whether they want a quick or a full analysis. Only the parameter changed.
- Automated testing runs only on repositories where it is enabled in the agent space. `verification-testing` can't turn it on elsewhere.
- The aws-mcp fallback writes `metadata.reviewDepth` together with the matching `metadata.skipAutomatedTesting`.
- The server still accepts `skip_automated_testing`.

**If `create_code_change_risk_analysis` rejects `review_depth`:** the server doesn't support it yet. Retry with `skip_automated_testing` (`true` for static analysis only).
