# Discover Phase: Billing Discovery

> Self-contained billing discovery sub-file. Scans for billing CSV/JSON files, parses billing data, builds service usage profiles, flags AI signals, and generates `billing-profile.json`.
> If no billing files are found, exits cleanly with no output.

**Execute ALL steps in order. Do not skip or optimize.**

---

## Step 0: Self-Scan for Billing Files

Scan the target directory for billing data:

- `**/*billing*.csv` — GCP billing export CSV
- `**/*billing*.json` — BigQuery billing export JSON
- `**/*cost*.csv`, `**/*cost*.json` — Cost report exports
- `**/*usage*.csv`, `**/*usage*.json` — Usage report exports

**Exclude `.migration/**`** — migration run artifacts (e.g. `openai-usage-profile.json`, `openai-capture/`) are never billing input.

**Exit gate:** If NO billing files are found, **exit cleanly**. Return no output artifacts. Other sub-discovery files may still produce artifacts.

---

## Step 1: Parse Billing Data

Supported formats:

- GCP billing export CSV
- BigQuery billing export JSON

### Step 1.0: Schema check — fail open, never hard-stop

The Step 0 glob matches on **filename** (`*billing*`, `*cost*`, `*usage*`), so a
matched file is not guaranteed to be a GCP/BigQuery export — it may be an
OpenAI/Anthropic invoice, an **OpenRouter usage export**, a Stripe payout, or a
hand-rolled spreadsheet. Billing is an **optional, secondary** signal; the
authoritative discovery inputs are IaC/live resources (infra migrations) and the
**application code scan** (AI/LLM migrations). A billing file this sub-file
cannot read must degrade gracefully — it must **never** halt the run or get
parsed against GCP column names into empty/garbage service rows.

Before parsing, confirm the file is a GCP/BigQuery export by checking for the
expected columns/keys (any of `service_description` / `sku_description` /
`service.description` / `sku.description`, plus a cost field such as `cost` /
`costAtListUSD`). Then:

- **Recognized (GCP/BigQuery):** parse it per the fields below.
- **Not recognized:** **skip that file** and append an entry to the
  `billing-profile.json` `warnings[]` array (an optional field in
  `schema-discover-billing.md`): `{ "file": "<name>", "code":
  "unrecognized_billing_export", "detail": "not a GCP/BigQuery export (looks
  like <provider, if identifiable>); skipped — model/service discovery relies on
  IaC and the code scan. To include spend, export GCP billing to CSV or supply a
  BigQuery billing export." }`. Do **not** parse it, and do **not** stop.
- **If EVERY matched file is unrecognized:** still write `billing-profile.json`
  in Step 4, with empty `services` (`total_monthly_spend: 0`,
  `ai_signals.detected: false`) and the `warnings[]` entries above — do **not**
  exit with no artifact. The empty-but-present profile validates against the
  schema and leaves a durable record that billing files were seen and skipped,
  rather than silently vanishing. (Contrast the Step 0 exit gate, which fires
  only when NO billing file matched the glob at all.)
  - **This is a SKIP RECORD, not parsed billing.** A profile with empty
    `services[]` **and** non-empty `warnings[]` records that billing input was
    seen and skipped — it must **not** be treated as usable spend data
    downstream. It does **not** on its own satisfy the Discover completion gate
    (`discover.md` Completion Handoff check 1), and it does **not** select the
    billing-only Design route (`design.md` requires non-empty `services[]`).
    Discover reports it as "Skipped N billing files," never "Parsed billing
    data." A run whose only artifact is a skip-record profile has effectively no
    billing signal — it must still anchor on IaC, code scan, or AI discovery.
- **OpenRouter specifically:** OpenRouter is a multi-provider **transport**, not
  a billing source this flow ingests. It is detected from the application code
  (`discover-app-code.md`, `gateway_type: llm_router`); an OpenRouter billing
  export is not needed and is skipped here per the rule above.

Extract from each recognized line item:

- `service_description` — GCP service name
- `sku_description` — Specific SKU/resource
- `cost` — Cost amount
- `usage_amount` — Usage quantity
- `usage_unit` — Usage unit (e.g., hours, bytes, requests)

Group by service and calculate monthly totals.

---

## Step 1.5: Identify Commitments and Discounts

Scan billing line items for GCP Committed Use Discount (CUD) artifacts and other billing-level discounts. These are **not workload costs** — they are financial instruments that must be separated from actual resource usage.

### Detection patterns

| Pattern                  | How to identify                                                                                 | Type             |
| ------------------------ | ----------------------------------------------------------------------------------------------- | ---------------- |
| Resource-based CUD fee   | SKU contains "Commitment v1:" (e.g., "Commitment v1: E2 Cpu in Americas for 1 Year")            | `resource_based` |
| Dollar-based CUD fee     | SKU contains "Commitment - dollar based" (e.g., "Commitment - dollar based v1: GCE for 1 year") | `dollar_based`   |
| CUD credit (offset)      | Column `committedUsageDiscount` or `committedUsageDiscountDollarBase` has non-zero value        | credit           |
| Sustained usage discount | Column `sustainedUsageDiscount` has non-zero value                                              | credit           |
| Subscription benefit     | Column `subscriptionBenefit` has non-zero value                                                 | credit           |
| Free tier credit         | Column `freeTier` has non-zero value                                                            | credit           |

Additional signals:

- `resourceGlobalName` contains `project_commitments` → commitment fee row
- `resourceName` starts with `commitment-` → commitment fee row

### Extraction

For each detected commitment fee row, extract:

- **Term**: Parse from SKU (e.g., "1 Year" or "3 Year")
- **Covered service**: Parse from SKU (e.g., "E2 Cpu", "E2 Ram", "GCE", "Cloud SQL")
- **Region**: From the `region` field
- **Monthly fee**: Sum `costAtListUSD` for all rows in that commitment

For discount credits, sum per type across all services:

- Total `committedUsageDiscount` (negative values = credits applied)
- Total `sustainedUsageDiscount`
- Total `freeTier`

### Cost basis determination

If any CUD-related columns or rows are detected:

- Use `costAtListUSD` (list price) as the baseline for all service costs in Step 2
- Record `total_at_list` (sum of all `costAtListUSD`)
- Record `total_net_of_discounts` (list price + all discount credits)
- Calculate `effective_discount_percent`: `(total_at_list - total_net_of_discounts) / total_at_list × 100`

If no CUD columns are present in the export (older export format), use the available cost column as-is and set `cost_basis.uses_list_price` to `false`.

---

## Step 2: Build Service Usage Profile

From the parsed billing data:

1. List all GCP services with non-zero spend
2. Calculate monthly cost per service **using list price (`costAtListUSD`) when available** — exclude commitment fee rows from service totals
3. Identify top services by spend (sorted descending)
4. Note usage patterns (consistent vs bursty spend)

---

## Step 3: Flag AI Signals

Scan billing line items for AI-relevant patterns. For each match, record the pattern, line item details, and confidence score.

| Pattern                     | What to look for                                                                                        | Confidence |
| --------------------------- | ------------------------------------------------------------------------------------------------------- | ---------- |
| 3.1 Vertex AI billing       | Description contains "Vertex AI", "AI Platform"; monthly cost > $10                                     | 98%        |
| 3.2 BigQuery ML billing     | "BigQuery ML" line items + high BigQuery analysis costs (>$500/month)                                   | 80%        |
| 3.3 Generative AI API       | "Generative AI API", "Gemini API", foundation model token charges                                       | 95%        |
| 3.4 Specialized AI services | "Document AI", "Vision AI", "Speech-to-Text", "Natural Language API", "Cloud Translation", "Dialogflow" | 85%        |

---

## Step 4: Generate billing-profile.json

Write `$MIGRATION_DIR/billing-profile.json` with the following structure:

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
    }
  ],
  "commitments": {
    "has_active_cuds": false,
    "total_monthly_commitment_fees": 0.00,
    "total_monthly_cud_credits": 0.00,
    "effective_discount_percent": 0.0,
    "details": []
  },
  "cost_basis": {
    "uses_list_price": true,
    "total_at_list": 2450.00,
    "total_net_of_discounts": 2450.00,
    "discount_breakdown": {
      "committed_usage_discount": 0.00,
      "sustained_usage_discount": 0.00,
      "free_tier": 0.00
    }
  },
  "ai_signals": {
    "detected": false,
    "confidence": 0,
    "services": []
  }
}
```

Load `references/shared/schema-discover-billing.md` and validate the output against the `billing-profile.json` schema.

After generating the output file, the parent `discover.md` handles the phase status update — do not update `.phase-status.json` here.

---

## Scope Boundary

**This phase covers Discover & Analysis ONLY.**

FORBIDDEN — Do NOT include ANY of:

- AWS service names, recommendations, or equivalents
- Migration strategies, phases, or timelines
- Terraform generation for AWS
- Cost estimates or comparisons
- Effort estimates

**Your ONLY job: Inventory what exists in GCP. Nothing else.**
