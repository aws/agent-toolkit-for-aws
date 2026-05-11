# Deterministic Calculations

**You MUST NEVER perform arithmetic by reasoning in your response.** This includes sums, averages, percentages, percent changes, counts, min/max, or any math on data from API calls. LLM arithmetic is unreliable and produces wrong cost figures.

**You MUST ALWAYS write a script** to perform calculations and print the result.

## Pattern: Python script for Cost Explorer data

After calling `aws ce get-cost-and-usage`, extract the numbers and calculate with a script:

```python
# Example: Calculate total cost and percent change from CE response data
import json

# Data extracted from API responses (replace with actual values)
current_month = [("EC2", 1500.42), ("S3", 823.17), ("RDS", 612.90)]
previous_month = [("EC2", 1200.00), ("S3", 750.00), ("RDS", 580.00)]

current_total = sum(cost for _, cost in current_month)
previous_total = sum(cost for _, cost in previous_month)
pct_change = ((current_total - previous_total) / previous_total) * 100

print(f"Current total: ${current_total:,.2f}")
print(f"Previous total: ${previous_total:,.2f}")
print(f"Change: {pct_change:+.1f}%")

for service, cost in current_month:
    pct_of_total = (cost / current_total) * 100
    print(f"  {service}: ${cost:,.2f} ({pct_of_total:.1f}%)")
```

## Pattern: Count and aggregate

```python
# Example: Count exceeded budgets from Budgets API response
budgets = [("Monthly-Total", "EXCEEDED"), ("Dev-Budget", "OK"), ("Prod-Budget", "EXCEEDED")]
exceeded = [name for name, status in budgets if status == "EXCEEDED"]
print(f"Exceeded budgets: {len(exceeded)} — {', '.join(exceeded)}")
```

## Pattern: Savings calculation

```python
# Example: Calculate savings from right-sizing recommendations
recs = [
    {"instance": "i-abc123", "current_cost": 121.03, "recommended_cost": 16.64},
    {"instance": "i-def456", "current_cost": 350.00, "recommended_cost": 175.00},
]
total_current = sum(r["current_cost"] for r in recs)
total_recommended = sum(r["recommended_cost"] for r in recs)
total_savings = total_current - total_recommended
pct_savings = (total_savings / total_current) * 100
print(f"Total monthly savings: ${total_savings:,.2f} ({pct_savings:.1f}%)")
print(f"Annual savings: ${total_savings * 12:,.2f}")
```

## Why this matters

- LLMs frequently make arithmetic errors on multi-digit numbers, especially with percentages and aggregations
- Cost data involves currency — wrong numbers erode customer trust immediately
- Scripts produce verifiable, reproducible results
- The AWS MCP server's `run_script` tool runs Python in a sandbox — use it when available
