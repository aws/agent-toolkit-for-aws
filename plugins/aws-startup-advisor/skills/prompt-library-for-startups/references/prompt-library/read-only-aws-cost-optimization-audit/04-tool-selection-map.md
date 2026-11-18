<!-- markdownlint-disable -->

## TOOL SELECTION MAP

Use the first available option per row.

| Data | MCP | AWS CLI |
| --- | --- | --- |
| Cost and usage | `cost_explorer` `getCostAndUsage` | `aws ce get-cost-and-usage` |
| Resource-level cost, 14 days | `cost_explorer` `getCostAndUsageWithResources` | `aws ce get-cost-and-usage-with-resources` |
| Forecast | `cost_explorer` `getCostForecast` | `aws ce get-cost-forecast` |
| Month-over-month drivers | `cost_comparison` | `aws ce get-cost-and-usage-comparisons` |
| Dimension values, tags | `cost_explorer` `getDimensionValues` | `aws ce get-dimension-values` |
| SP coverage and utilization | `sp_performance` | `aws ce get-savings-plans-coverage` / `-utilization` |
| RI coverage and utilization | `ri_performance` | `aws ce get-reservation-coverage` / `-utilization` |
| Consolidated recommendations | `cost_optimization` `list_recommendation_summaries` then `list_recommendations` | `aws cost-optimization-hub list-recommendations` |
| Anomalies detected | `cost_anomaly` | `aws ce get-anomalies` |
| List prices | `aws_pricing` | `aws pricing get-products` |
| Target-state cost | `aws-pricing-calculator` | manual from `aws_pricing` |
| Service behavior, limits | `aws-knowledge` `search_documentation` | none, do not guess |
| Compute Optimizer findings | not available | `aws compute-optimizer get-*-recommendations` |
| Resource inventory | not available | `aws <service> describe-*` / `list-*` |

MCP cost tools still call Cost Explorer and still incur the Rule 5 charge.

The Pricing API has endpoints in a few regions only (`us-east-1`, `eu-central-1`, `ap-southeast-1` in the classic partition). Pass `--region us-east-1` or another endpoint region to every `aws pricing` call: in any other region the failure surfaces as `AccessDeniedException` and reads like a permission problem when it is a routing one.

---

<!-- markdownlint-enable -->
