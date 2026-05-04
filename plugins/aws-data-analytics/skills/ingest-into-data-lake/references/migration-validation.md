# Migration Validation Checklist

Run all checks after migration. Do not skip any.

## 1. Row Count Match

```sql
SELECT 'source' AS tbl, COUNT(*) AS cnt
FROM "<source_catalog>"."<source_db>"."<source_table>"
UNION ALL
SELECT 'target' AS tbl, COUNT(*) AS cnt
FROM "s3tablescatalog/<bucket>"."<namespace>"."<target_table>"
```

Counts must match exactly unless a WHERE filter was applied during migration. If filtered, document the expected difference.

## 2. Schema Comparison

```sql
-- Source schema
DESCRIBE "<source_catalog>"."<source_db>"."<source_table>"

-- Target schema
DESCRIBE "s3tablescatalog/<bucket>"."<namespace>"."<target_table>"
```

Check:

- All expected columns are present
- Column order matches (or is acceptable if reordered)
- Types are compatible (minor promotions like int->bigint are OK)
- No unexpected columns added or dropped

## 3. Null Count Comparison

```sql
-- Run for each column, or generate dynamically
SELECT
    COUNT(*) - COUNT(col1) AS col1_nulls,
    COUNT(*) - COUNT(col2) AS col2_nulls
FROM "s3tablescatalog/<bucket>"."<namespace>"."<target_table>"
```

Compare against the same query on the source. Null counts should match.

## 4. Boundary Value Check

```sql
SELECT
    MIN(numeric_col) AS min_val,
    MAX(numeric_col) AS max_val,
    MIN(date_col) AS min_date,
    MAX(date_col) AS max_date
FROM "s3tablescatalog/<bucket>"."<namespace>"."<target_table>"
```

Compare against source. Min/max values should match (accounting for any WHERE filters).

## 5. Distinct Count Check

```sql
SELECT
    COUNT(DISTINCT key_col) AS distinct_keys
FROM "s3tablescatalog/<bucket>"."<namespace>"."<target_table>"
```

Compare against source. Mismatches indicate duplicates introduced or rows lost.

## 6. Partition Verification (if partitioned)

```sql
SELECT <partition_expression>, COUNT(*) AS row_count
FROM "s3tablescatalog/<bucket>"."<namespace>"."<target_table>"
GROUP BY 1
ORDER BY 1
```

Verify partition distribution is reasonable and no partitions are missing.

## 7. Sample Row Comparison

```sql
-- Pick a specific key value and compare full rows
SELECT * FROM "<source_catalog>"."<source_db>"."<source_table>"
WHERE key_col = '<known_value>'

SELECT * FROM "s3tablescatalog/<bucket>"."<namespace>"."<target_table>"
WHERE key_col = '<known_value>'
```

Spot-check 3-5 specific rows. All column values should match.

## Pass Criteria

| Check | Pass condition |
|-------|---------------|
| Row count | Exact match (or documented delta if filtered) |
| Schema | All columns present with compatible types |
| Null counts | Match within tolerance (0 difference expected) |
| Boundary values | Match exactly |
| Distinct counts | Match exactly |
| Partitions | All expected partitions present |
| Sample rows | All values match |
