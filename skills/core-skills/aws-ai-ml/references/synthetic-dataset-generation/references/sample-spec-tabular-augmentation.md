# Sample Spec: Tabular Data Generation

Example specs for tabular synthetic dataset generation. Tabular generation can be either **contextual** (CDG — seed data provided as input) or **non-contextual** (NCDG — schema defined entirely in the spec).

## When to Use This Template

- Customer wants to generate structured row/column data
- Output should be CSV, Parquet, or SQLite
- Use case: database augmentation, test data, anonymized datasets, schema-preserving synthetic records
- Single-table or multi-table relational schemas

## Supported Output and Seed Data Formats

See [supported-output-formats.md](supported-output-formats.md) → *Tabular / Custom Format* for the canonical list:

- Delivery formats (CSV / Parquet / SQLite): how to request each and the output files produced
- Seed data formats accepted via `InputDataS3Uri` (.csv / .parquet / .sqlite / .db / .json / .jsonl)

---

## Example: Contextual (CDG) — Augment from CSV Seed

The customer provides a `.csv` file as `InputDataS3Uri`. The spec references its schema.

```markdown
# Tabular Data Generation

## Overall Goal
Generate synthetic CSV rows matching the schema of the provided seed_data.csv.

## Input Format
input_data contains seed_data.csv with columns: customer_id,name,age,city,purchase_amount,signup_date

## prepare_batch
Parse seed_data.csv and store the column names and a few example rows for context.

## generator
Output one CSV row with 6 comma-separated values matching the column order from seed_data.csv.
Values should be plausible (e.g. age 18-80, positive purchase_amount, date as YYYY-MM-DD).

## verify_sample
Confirm the output has exactly 6 comma-separated fields (empty fields allowed for nulls).
```

**Job config:**

```python
config = DatasetJobConfig(
    dataset_name="my-tabular-dataset",
    generation_config={
        "DatasetSpecification": {"SpecS3Uri": "s3://bucket/specs/tabular_spec.txt"},
        "InputDataS3Uri": "s3://bucket/input/seed_data.csv",
        "NumSamples": 100,
    },
)
```

## Example: CDG with SQLite Seed

The customer provides a `.sqlite` database. The platform extracts each table as CSV and provides them as seed context.

```markdown
# Tabular Data Generation

## Overall Goal
Generate synthetic records matching the schema of the provided database. Output as sqlite.

## Input Format
input_data contains sales.sqlite with tables: products (id, name, category, price) and transactions (id, product_id, quantity, date)

## prepare_batch
Load the seed database and store the schema, sample rows, and distribution characteristics.
Tables: products (id, name, category, price), transactions (id, product_id, quantity, date).
Foreign key: transactions.product_id → products.id.

## generator
Output a JSON object representing one transaction row:
{"id": <int>, "product_id": <int>, "quantity": <int>, "date": "<YYYY-MM-DD>"}
- id: sequential integer starting from 1001
- product_id: must reference an existing product ID from the seed data
- quantity: random integer 1-20
- date: random date in 2024, format YYYY-MM-DD

## verify_sample
- Confirm all required fields are present and non-null
- Confirm id is a positive integer
- Confirm quantity is between 1 and 20
- Confirm date matches YYYY-MM-DD pattern using re.match()

## Tabular Output Constraints
- Output format: SQLite
- One record per sample.
- Foreign keys: product_id must reference a valid product from seed data.
- Dates: YYYY-MM-DD.
```

## Example: Non-Contextual (NCDG) — Parquet Output

No input file. The spec fully defines the schema. Output as Parquet.

```markdown
# Tabular Data Generation

## Overall Goal
Generate 500 synthetic e-commerce transaction records. Output as parquet.

## prepare_batch
Store the target schema in auxiliary_datastore:
- Columns: transaction_id, customer_email, product_sku, quantity, unit_price, timestamp
- transaction_id: sequential integer starting from 1000
- quantity: 1-10
- unit_price: 5.00-500.00
- timestamp: ISO 8601 within the last 90 days

## generator
Output a JSON object with exactly 6 fields:
{"transaction_id": <int>, "customer_email": "<str>", "product_sku": "<str>", "quantity": <int>, "unit_price": <float>, "timestamp": "<str>"}
Generate realistic values within the specified constraints.

## verify_sample
- Confirm the record has exactly 6 fields
- Confirm quantity is an integer between 1 and 10
- Confirm unit_price is a positive decimal between 5.00 and 500.00
- Confirm timestamp matches YYYY-MM-DDTHH:MM:SS pattern using re.match()

## Tabular Output Constraints
- Output format: Parquet (converted from streaming CSV at job completion)
- One record per sample.
- Column order is fixed: transaction_id, customer_email, product_sku, quantity, unit_price, timestamp
- Numeric fields must be actual numbers in the JSON object, not strings.
- Decimals: round to 2 places.
- IDs: sequential IDs start from 1000.
```

**Job config:**

```python
config = DatasetJobConfig(
    dataset_name="ecommerce-parquet",
    generation_config={
        "DatasetSpecification": {"SpecS3Uri": "s3://bucket/specs/ecommerce_parquet.txt"},
        "NumSamples": 500,
    },
)
```

## Example: Multi-Relational (Multiple Tables with FK Integrity)

Generates data for multiple related tables in a single job. The platform maintains foreign-key integrity across tables.

```markdown
# Multi-Table Data Generation

## Overall Goal
Generate a customer-orders dataset with 10 customers and 2-4 orders each.

## prepare_batch
Define the schema for both tables:
- Customers: id (int, PK, sequential from 1), name (string), email (string, unique), age (int 18-65)
- Orders: id (int, PK, sequential from 1), customer_id (int, FK→customers.id), amount (decimal 10-500), status (one of: completed, pending, cancelled)

Track the next available ID for each table.

## generator
Output a list of [table_name, row_dict] tuples representing one customer group:
[
  ["customers", {"id": <int>, "name": "<str>", "email": "<str>", "age": <int>}],
  ["orders", {"id": <int>, "customer_id": <int>, "amount": <float>, "status": "<str>"}],
  ["orders", {"id": <int>, "customer_id": <int>, "amount": <float>, "status": "<str>"}]
]

Rules:
- Generate exactly 1 customer row + 2-4 order rows per sample
- All orders.customer_id must equal the customer's id (FK integrity)
- IDs must be sequential and unique across all samples

## verify_sample
- Confirm output is a list of [table_name, row] pairs
- Customers: id present and integer, name non-empty, valid email pattern, age 18-65
- Orders: id present and integer, customer_id matches the customer in this group, amount 10.00-500.00, status in allowed set
- All orders reference the customer generated in this same sample

## Tabular Output Constraints
- Multi-relational: output is a list of [table_name, row_object] tuples.
- Generate parent rows before child rows in each sample.
- Every FK must reference a PK generated in this sample or a previous sample.
- The platform writes separate CSV files per table (customers.csv, orders.csv).
```

**Job config:**

```python
config = DatasetJobConfig(
    dataset_name="customer-orders",
    generation_config={
        "DatasetSpecification": {"SpecS3Uri": "s3://bucket/specs/multi_table.txt"},
        "NumSamples": 10,  # 10 customer groups, each with 2-4 orders
    },
)
```

---

## Key Patterns

1. **`generator` outputs one record (or group) per call** — not a full table. The platform calls the generator once per sample.
2. **`verify_sample` checks structure** — field count, basic type validation. Use `re.match()` for dates, NOT `datetime.strptime()`.
3. **Keep verification minimal** — fewer checks = fewer retries = faster jobs.
4. **CDG vs NCDG** — CDG references input file columns; NCDG defines the schema inline in the spec.
5. **Multi-relational: group parent + children** — for FK integrity, specify that each sample produces one parent + its associated children together.
6. **NULLs as empty fields** — use consecutive commas in CSV, not the string "NULL".
7. **Fixed column order** — declare it once, every sample must match.
8. **Dates as YYYY-MM-DD** — timestamps as YYYY-MM-DDTHH:MM:SS. No ambiguity.
9. **Arithmetic self-validation** — for specs with computed fields (total = subtotal + tax), state the formula explicitly so the generator can self-check.
10. **Format in Overall Goal** — state "Output as parquet" or "Output as sqlite" to get non-CSV formats.

For the canonical `## Tabular Output Constraints` blocks (CSV / Parquet / SQLite) that get inserted verbatim into the user's spec, see `tabular-authoring.md`. The three worked examples above show the pattern in context.

## Output

- **CSV**: `.csv` file delivered to S3
- **Parquet**: `.parquet` file delivered to S3 (+ `.csv` also retained)
- **SQLite**: `.sqlite` file with typed columns and FK constraints delivered to S3 (+ `.csv` also retained)
- All formats include `dataset_schema.json` manifest describing the table/column structure
- Hub format is `Custom` for all tabular outputs
