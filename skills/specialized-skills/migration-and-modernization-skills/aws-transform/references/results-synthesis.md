# Results Synthesis

Generate a single summary file after bulk transformations complete.

## Output

Write one file: `~/.aws/atx/custom/atx-agent-session/transformation-summaries/transformation-summary-$SESSION_TS.md`

```bash
mkdir -p ~/.aws/atx/custom/atx-agent-session/transformation-summaries
```

**Important:** Do NOT use heredoc (`cat << EOF`) to write this file — heredoc
blocks can hang in shell environments. Use a command (ex. `printf '%s'`) to write the content.

## Template

```markdown
# ATX Transformation Summary
> Completed: <timestamp>
> Repositories: <total> | Succeeded: <count> | Failed: <count>

## Results
| Project | TD | Status | Notes |
|---------|-----|--------|-------|
| <name> | <td> | Succeeded/Failed | <brief note> |

## Failed Transformations
### <project-name>
- **TD**: <td-name>
- **Error**: <one-line error summary>
- **Suggested Fix**: <recommendation>

## Next Steps
1. Review changes in each transformed repo
2. Run tests and deploy
```

## Presentation

Tell the user:

```
Results: <succeeded>/<total> succeeded, <failed> failed
Summary: ~/.aws/atx/custom/atx-agent-session/transformation-summaries/transformation-summary-$SESSION_TS.md
```

For remote mode executions, also include the CloudWatch dashboard link:

```bash
REGION=${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region 2>/dev/null)}}
REGION=${REGION:-us-east-1}
echo "CloudWatch Dashboard: https://${REGION}.console.aws.amazon.com/cloudwatch/home#dashboards/dashboard/ATX-Transform-CLI-Dashboard"
```
