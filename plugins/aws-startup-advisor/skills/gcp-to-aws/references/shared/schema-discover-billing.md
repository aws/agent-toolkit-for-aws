# Billing Discovery Schema

Schema for `billing-profile.json`, produced by `discover-billing.md`.

**Convention**: Values shown as `X|Y` in examples indicate allowed alternatives — use exactly one value per field, not the literal pipe character.

---

## billing-profile.json (Phase 1 output)

Cost breakdown derived from GCP billing export CSV. Provides service-level spend and AI signal detection from billing data alone.

```json
{
  "metadata": {
    "report_date": "2026-02-24",
    "project_directory": "/path/to/project",
    "billing_source": "gcp-billing-export.csv",
    "billing_period": "2026-01"
  },
  "summary": {
    "total_monthly_spend": 2450.00,
    "service_count": 8,
    "currency": "USD"
  },
  "services": [
    {
      "gcp_service": "Cloud Run",
      "gcp_service_type": "google_cloud_run_service",
      "monthly_cost": 450.00,
      "percentage_of_total": 0.18,
      "top_skus": [
        {
          "sku_description": "Cloud Run - CPU Allocation Time",
          "monthly_cost": 300.00
        },
        {
          "sku_description": "Cloud Run - Memory Allocation Time",
          "monthly_cost": 150.00
        }
      ],
      "ai_signals": []
    },
    {
      "gcp_service": "Cloud SQL",
      "gcp_service_type": "google_sql_database_instance",
      "monthly_cost": 800.00,
      "percentage_of_total": 0.33,
      "top_skus": [
        {
          "sku_description": "Cloud SQL for PostgreSQL - DB custom CORE",
          "monthly_cost": 500.00
        },
        {
          "sku_description": "Cloud SQL for PostgreSQL - DB custom RAM",
          "monthly_cost": 300.00
        }
      ],
      "ai_signals": []
    },
    {
      "gcp_service": "Vertex AI",
      "gcp_service_type": "google_vertex_ai_endpoint",
      "monthly_cost": 600.00,
      "percentage_of_total": 0.24,
      "top_skus": [
        {
          "sku_description": "Vertex AI Prediction - Online Prediction",
          "monthly_cost": 400.00
        },
        {
          "sku_description": "Generative AI - Gemini Pro Input Tokens",
          "monthly_cost": 200.00
        }
      ],
      "ai_signals": ["vertex_ai", "generative_ai"]
    }
  ],
  "commitments": {
    "has_active_cuds": true,
    "total_monthly_commitment_fees": 150.00,
    "total_monthly_cud_credits": -120.00,
    "effective_discount_percent": 8.2,
    "details": [
      {
        "type": "resource_based",
        "term": "1_year",
        "covered_services": ["Compute Engine"],
        "region": "us-central1",
        "monthly_fee": 75.00,
        "sku_description": "Commitment v1: E2 Cpu in Americas for 1 Year"
      },
      {
        "type": "resource_based",
        "term": "1_year",
        "covered_services": ["Compute Engine"],
        "region": "us-central1",
        "monthly_fee": 75.00,
        "sku_description": "Commitment v1: E2 Ram in Americas for 1 Year"
      }
    ]
  },
  "cost_basis": {
    "uses_list_price": true,
    "total_at_list": 2450.00,
    "total_net_of_discounts": 2280.00,
    "discount_breakdown": {
      "committed_usage_discount": -120.00,
      "sustained_usage_discount": -50.00,
      "free_tier": 0.00
    }
  },
  "ai_signals": {
    "detected": true,
    "confidence": 0.85,
    "services": ["Vertex AI"]
  }
}
```

**Key Fields:**

- `summary.total_monthly_spend` — Total monthly GCP spend from the billing export (at list price when available)
- `summary.service_count` — Number of distinct GCP services with charges
- `services[].gcp_service_type` — Terraform resource type equivalent for the service (used by downstream phases)
- `services[].monthly_cost` — Monthly cost for this service (at list price; excludes commitment fee rows)
- `services[].top_skus` — Highest-cost line items within the service (excludes commitment fee SKUs)
- `services[].ai_signals` — AI-related keywords found in SKU descriptions for this service
- `commitments.has_active_cuds` — Whether any CUD commitment fees or credits were detected
- `commitments.total_monthly_commitment_fees` — Sum of commitment fee line items (positive values)
- `commitments.total_monthly_cud_credits` — Sum of CUD credits applied (negative values)
- `commitments.effective_discount_percent` — Overall discount rate from all commitments
- `commitments.details[]` — Individual commitment contracts with type, term, covered services, and monthly fee
- `commitments.details[].type` — `"resource_based"` (vCPU/RAM commitments) or `"dollar_based"` (spend-based)
- `commitments.details[].term` — `"1_year"` or `"3_year"`
- `cost_basis.uses_list_price` — Whether `costAtListUSD` was available and used as the baseline
- `cost_basis.total_at_list` — Total spend at list price (before discounts)
- `cost_basis.total_net_of_discounts` — Total spend after all discounts applied
- `cost_basis.discount_breakdown` — Per-discount-type credit totals (negative values = savings)
- `ai_signals.detected` — Whether any AI/ML services were found in the billing data
- `ai_signals.confidence` — Confidence that the project uses AI (derived from billing SKU analysis)
- `ai_signals.services` — List of AI-related GCP services found
