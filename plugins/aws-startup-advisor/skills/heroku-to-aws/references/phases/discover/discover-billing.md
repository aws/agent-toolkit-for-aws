---
_fragment: billing
_of_phase: discover
_contributes:
  - heroku-resource-inventory.json (billing_profile section)
---

# Discover Phase: Billing Discovery

> Self-contained billing discovery sub-file. Scans for Heroku Dashboard invoice files and Enterprise CSV billing exports, parses billing data, builds a billing profile with per-app cost breakdowns, and contributes the `billing_profile` section to `heroku-resource-inventory.json`.
> If no billing files are found, exits cleanly with no output. The parent `discover.md` handles graceful degradation.

**Execute ALL steps in order. Do not skip or optimize.**

---

## Step 0: Self-Scan for Billing Files

This fragment runs only when its `_trigger` glob matches a billing/invoice file
(see frontmatter). Confirm at least one such file is present and readable.

**Exit gate:** If no usable billing file is found (none present, or the matched
file(s) turn out not to be parseable billing data), contribute
`billing_profile: { available: false }` and **exit cleanly** — return no other
output. Discovery continues; other sub-discoveries still produce their artifacts.

Log: "No billing files found — skipping billing discovery. Cost comparison will be limited to projected AWS costs only."

---

## Step 1: Detect File Format

For each discovered billing file, determine format by inspection:

### 1a. CSV Format Detection

Read the first line (header row). Match against known schemas:

| Header Pattern                                                 | Format Type      | Source                           |
| -------------------------------------------------------------- | ---------------- | -------------------------------- |
| Contains `app`, `dyno_units`, `addon_total`, `platform_total`  | `enterprise_csv` | Heroku Enterprise billing export |
| Contains `description`, `amount`, `period_start`, `period_end` | `invoice_csv`    | Heroku Dashboard invoice CSV     |
| Contains `resource_name`, `category`, `cost`                   | `line_item_csv`  | Heroku itemized billing CSV      |

**If header does not match any known pattern:**

- Log warning: "Unrecognized CSV billing format in `{filename}`. Expected Heroku Enterprise or Dashboard invoice headers. Skipping file."
- Skip this file and continue to next billing file (if any).

### 1b. JSON Format Detection

Parse JSON and check top-level structure:

| Structure Pattern                                              | Format Type        | Source                                |
| -------------------------------------------------------------- | ------------------ | ------------------------------------- |
| Has `total`, `period_start`, `period_end`, and `charges` array | `invoice_json`     | Heroku Dashboard invoice JSON         |
| Has `invoice_id`, `total_amount`, `line_items` array           | `api_invoice_json` | Heroku Platform API invoice response  |
| Has `apps` array with nested cost objects                      | `enterprise_json`  | Heroku Enterprise billing JSON export |

**If JSON structure does not match any known pattern:**

- Log warning: "Unrecognized JSON billing format in `{filename}`. Expected Heroku invoice or Enterprise export structure. Skipping file."
- Skip this file and continue to next billing file (if any).

**If JSON is malformed (parse error):**

- Log warning: "Failed to parse JSON in `{filename}`: {error_message}. Skipping file."
- Skip this file and continue to next billing file (if any).

---

## Step 2: Parse Billing Data

Apply format-specific parsing logic. Extract normalized line items from each recognized file.

### 2a. Enterprise CSV Parsing

Extract from each row:

| CSV Column                          | Maps To                               | Notes                                       |
| ----------------------------------- | ------------------------------------- | ------------------------------------------- |
| `app`                               | `resource_name`                       | Heroku app name                             |
| `dyno_units` or `dyno_cost`         | line item with `category: "dyno"`     | Compute costs                               |
| `addon_total` or `addon_cost`       | line item with `category: "addon"`    | Add-on costs                                |
| `platform_total` or `platform_cost` | line item with `category: "platform"` | Platform charges (SSL, etc.)                |
| `period` or `billing_period`        | `billing_period`                      | Format: YYYY-MM                             |
| `total` or `line_total`             | Per-row total for validation          | Should equal sum of dyno + addon + platform |

Sum all row totals to derive `total_monthly_cost`.

### 2b. Invoice CSV Parsing

Extract from each row:

| CSV Column                    | Maps To                      | Notes                                                       |
| ----------------------------- | ---------------------------- | ----------------------------------------------------------- |
| `description`                 | `resource_name` + `category` | Parse app name and charge type from description text        |
| `amount`                      | `cost`                       | Line item cost (USD assumed unless currency column present) |
| `period_start` / `period_end` | `billing_period`             | Derive YYYY-MM from period_start                            |
| `currency` (if present)       | `currency`                   | Default to "USD" if absent                                  |

**Description parsing rules:**

- "Dyno usage for {app_name}" → `resource_name: app_name`, `category: "dyno"`
- "Add-on: {addon_name} for {app_name}" or "{addon_name} ({app_name})" → `resource_name: app_name`, `category: "addon"`
- "Platform" or "SSL" or "Support" → `resource_name: "platform"`, `category: "platform"`
- Unrecognized description → `resource_name: "unknown"`, `category: "other"`

### 2c. Invoice JSON Parsing

Extract from the JSON structure:

```
total → total_monthly_cost
period_start → billing_period (extract YYYY-MM)
charges[] → line_items:
  charges[].description → resource_name + category (same parsing rules as 2b)
  charges[].amount → cost
```

### 2d. API Invoice JSON Parsing

Extract from the JSON structure:

```
total_amount → total_monthly_cost
line_items[] → line_items:
  line_items[].description → resource_name + category (same parsing rules as 2b)
  line_items[].amount → cost
  line_items[].app_name → resource_name (if field present, overrides description parsing)
```

### 2e. Enterprise JSON Parsing

Extract from the JSON structure:

```
apps[] → iterate:
  apps[].name → resource_name
  apps[].dyno_cost → line item with category: "dyno"
  apps[].addon_cost → line item with category: "addon"
  apps[].platform_cost → line item with category: "platform"

Sum all app costs → total_monthly_cost
Extract billing_period from top-level metadata or filename pattern (YYYY-MM)
```

---

## Step 3: Build Billing Profile

From the parsed and normalized line items, assemble the billing profile object:

### 3a. Compute Totals

1. Sum all line item costs → `total_monthly_cost`
2. Extract `billing_period` (YYYY-MM format) from the parsed data
3. Set `currency` from parsed data (default: `"USD"`)
4. Set `available` to `true`

### 3b. Build Per-App Cost Breakdown

Group line items by `resource_name` (app name). For each app:

1. Sum items where `category == "dyno"` → app dyno cost
2. Sum items where `category == "addon"` → app add-on cost
3. Sum items where `category == "platform"` → app platform cost

Produce one line item per app per category (dyno, addon, platform). Omit categories with $0.00 cost.

### 3c. Validate Totals

Cross-check: sum of all line items should equal `total_monthly_cost` (within $0.01 tolerance for floating-point).

- If mismatch > $0.01: Log warning: "Billing total mismatch: line items sum to ${sum} but reported total is ${total}. Using line item sum."
- Use the line item sum as the authoritative `total_monthly_cost`.

### 3d. Handle Multiple Billing Files

If multiple billing files are found:

1. Use the file with the most recent `billing_period`.
2. If multiple files cover the same period, prefer Enterprise format over Dashboard invoice (Enterprise has richer per-app breakdown).
3. Log: "Multiple billing files found. Using `{selected_filename}` (period: {billing_period})."

---

## Step 4: Produce Billing Profile Output

Produce the `billing_profile` section for inclusion in `heroku-resource-inventory.json`. The parent `discover.md` Step 3 merges this into the final inventory.

### Output Schema

```json
{
  "billing_profile": {
    "available": true,
    "total_monthly_cost": 450.00,
    "currency": "USD",
    "billing_period": "2026-02",
    "source_file": "billing-export-2026-02.csv",
    "source_format": "enterprise_csv",
    "line_items": [
      {
        "resource_name": "my-web-app",
        "category": "dyno",
        "cost": 100.00
      },
      {
        "resource_name": "my-web-app",
        "category": "addon",
        "cost": 200.00
      },
      {
        "resource_name": "my-web-app",
        "category": "platform",
        "cost": 50.00
      },
      {
        "resource_name": "my-api-app",
        "category": "dyno",
        "cost": 75.00
      },
      {
        "resource_name": "my-api-app",
        "category": "addon",
        "cost": 25.00
      }
    ],
    "parse_warnings": []
  }
}
```

### Field Definitions

| Field                        | Type    | Required | Description                                                                                                     |
| ---------------------------- | ------- | -------- | --------------------------------------------------------------------------------------------------------------- |
| `available`                  | boolean | Yes      | `true` if billing data was successfully parsed                                                                  |
| `total_monthly_cost`         | number  | Yes      | Total monthly Heroku spend (sum of all line items)                                                              |
| `currency`                   | string  | Yes      | Currency code (default: `"USD"`)                                                                                |
| `billing_period`             | string  | Yes      | Billing period in YYYY-MM format                                                                                |
| `source_file`                | string  | Yes      | Filename of the billing file used                                                                               |
| `source_format`              | string  | Yes      | One of: `enterprise_csv`, `invoice_csv`, `line_item_csv`, `invoice_json`, `api_invoice_json`, `enterprise_json` |
| `line_items`                 | array   | Yes      | Per-app, per-category cost breakdown                                                                            |
| `line_items[].resource_name` | string  | Yes      | Heroku app name or `"platform"` or `"unknown"`                                                                  |
| `line_items[].category`      | string  | Yes      | One of: `"dyno"`, `"addon"`, `"platform"`, `"other"`                                                            |
| `line_items[].cost`          | number  | Yes      | Cost amount for this line item                                                                                  |
| `parse_warnings`             | array   | Yes      | Any warnings generated during parsing (empty array if none)                                                     |

---

## Error Handling

| Error Category                  | Behavior                                       | Effect on Discovery                                         |
| ------------------------------- | ---------------------------------------------- | ----------------------------------------------------------- |
| Unrecognized CSV header format  | Log warning with filename, skip file           | Try next billing file; if none remain, exit cleanly         |
| Unrecognized JSON structure     | Log warning with filename, skip file           | Try next billing file; if none remain, exit cleanly         |
| Malformed JSON (parse error)    | Log warning with filename and error, skip file | Try next billing file; if none remain, exit cleanly         |
| CSV row missing required fields | Log warning, skip row, continue                | Partial data included; warning recorded in `parse_warnings` |
| Billing total mismatch          | Log warning, use line item sum                 | Proceed with corrected total                                |
| All billing files fail to parse | Log warning, exit cleanly                      | Discovery continues without billing profile                 |
| Currency not recognized         | Default to "USD", log warning                  | Proceed with USD assumption                                 |
| Billing period not parseable    | Use filename date pattern or "unknown"         | Proceed with best-effort period                             |

**Key principle:** Billing discovery is **always optional**. Any parse failure results in a warning and graceful skip — it NEVER blocks or fails the overall Discover phase.

---

## Scope Boundary

**This sub-file covers billing data parsing ONLY.**

FORBIDDEN — Do NOT include ANY of:

- AWS service names, recommendations, or equivalents
- Migration strategies, phases, or timelines
- Cost estimates or projections for AWS
- Cost comparisons between Heroku and AWS
- Pricing recommendations

**Your ONLY job: Parse Heroku billing data into a structured profile. Nothing else.**

After generating the billing profile output, the parent `discover.md` handles merging it into the inventory and updating phase status — do NOT update `.phase-status.json` here.
