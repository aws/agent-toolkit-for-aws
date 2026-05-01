# Common Query Patterns (Presto/Athena SQL)

## Table Profiling

```sql
-- Schema discovery
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = '<database>' AND table_name = '<table>';

-- Quick row count and date range
SELECT COUNT(*) as total_rows,
       MIN(created_at) as earliest,
       MAX(created_at) as latest
FROM <table>;

-- Sample data (always do this before analytical queries)
SELECT * FROM <table> LIMIT 5;

-- Null analysis
SELECT
    '<column>' as field,
    COUNT(*) - COUNT(<column>) as null_count,
    ROUND((COUNT(*) - COUNT(<column>)) * 100.0 / COUNT(*), 2) as null_pct
FROM <table>;
```

## Cohort Retention

```sql
WITH cohorts AS (
    SELECT
        user_id,
        DATE_TRUNC('month', first_activity_date) as cohort_month
    FROM users
),
activity AS (
    SELECT
        user_id,
        DATE_TRUNC('month', activity_date) as activity_month
    FROM user_activity
)
SELECT
    c.cohort_month,
    COUNT(DISTINCT c.user_id) as cohort_size,
    COUNT(DISTINCT CASE
        WHEN a.activity_month = c.cohort_month THEN a.user_id
    END) as month_0,
    COUNT(DISTINCT CASE
        WHEN a.activity_month = DATE_ADD('month', 1, c.cohort_month) THEN a.user_id
    END) as month_1,
    COUNT(DISTINCT CASE
        WHEN a.activity_month = DATE_ADD('month', 3, c.cohort_month) THEN a.user_id
    END) as month_3,
    COUNT(DISTINCT CASE
        WHEN a.activity_month = DATE_ADD('month', 6, c.cohort_month) THEN a.user_id
    END) as month_6
FROM cohorts c
LEFT JOIN activity a ON c.user_id = a.user_id
GROUP BY c.cohort_month
ORDER BY c.cohort_month;
```

## Funnel Analysis

```sql
WITH funnel AS (
    SELECT
        user_id,
        MAX(CASE WHEN event = 'page_view' THEN 1 ELSE 0 END) as step_1_view,
        MAX(CASE WHEN event = 'signup_start' THEN 1 ELSE 0 END) as step_2_start,
        MAX(CASE WHEN event = 'signup_complete' THEN 1 ELSE 0 END) as step_3_complete,
        MAX(CASE WHEN event = 'first_purchase' THEN 1 ELSE 0 END) as step_4_purchase
    FROM events
    WHERE event_date >= DATE_ADD('day', -30, CURRENT_DATE)
    GROUP BY user_id
)
SELECT
    COUNT(*) as total_users,
    SUM(step_1_view) as viewed,
    SUM(step_2_start) as started_signup,
    SUM(step_3_complete) as completed_signup,
    SUM(step_4_purchase) as purchased,
    ROUND(100.0 * SUM(step_2_start) / NULLIF(SUM(step_1_view), 0), 1) as view_to_start_pct,
    ROUND(100.0 * SUM(step_3_complete) / NULLIF(SUM(step_2_start), 0), 1) as start_to_complete_pct,
    ROUND(100.0 * SUM(step_4_purchase) / NULLIF(SUM(step_3_complete), 0), 1) as complete_to_purchase_pct
FROM funnel;
```

## Deduplication

```sql
-- Keep the most recent record per key (Presto/Athena syntax)
WITH ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY entity_id
            ORDER BY updated_at DESC
        ) as rn
    FROM source_table
)
SELECT * FROM ranked WHERE rn = 1;
```

## Window Functions

```sql
-- Running total
SUM(revenue) OVER (ORDER BY event_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) as running_total

-- 7-day moving average
AVG(revenue) OVER (ORDER BY event_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) as moving_avg_7d

-- Period-over-period comparison
LAG(value, 1) OVER (PARTITION BY entity ORDER BY event_date) as prev_value

-- Percent of total
revenue / SUM(revenue) OVER () as pct_of_total
revenue / SUM(revenue) OVER (PARTITION BY category) as pct_of_category

-- Ranking
ROW_NUMBER() OVER (PARTITION BY category ORDER BY revenue DESC) as rank_in_category
```

## Period Comparison / Growth

When the user asks for "growth", "change", or "comparison" between periods, compute the delta — not raw totals.

```sql
WITH quarterly AS (
    SELECT
        category,
        QUARTER(order_date) as q,
        SUM(amount) as revenue
    FROM orders
    WHERE YEAR(order_date) = 2025
    GROUP BY category, QUARTER(order_date)
)
SELECT
    curr.category,
    prev.revenue as prev_period,
    curr.revenue as curr_period,
    ROUND((curr.revenue - prev.revenue) / prev.revenue * 100, 1) as growth_pct
FROM quarterly curr
JOIN quarterly prev ON curr.category = prev.category AND curr.q = prev.q + 1
ORDER BY growth_pct DESC;
```

## Performance-Aware Patterns

```sql
-- Always filter on partition keys to reduce scan cost
SELECT region, COUNT(*)
FROM sales
WHERE year = '2024' AND month = '02'
GROUP BY region;

-- Use LIMIT for exploratory queries
SELECT * FROM large_table LIMIT 100;

-- Use approximate functions for large-scale cardinality
SELECT APPROX_DISTINCT(user_id) as approx_unique_users
FROM events;
```

## Data Quality Checks

```sql
-- Distinct value counts per column
SELECT
    COUNT(DISTINCT col1) as col1_unique,
    COUNT(DISTINCT col2) as col2_unique
FROM <table>;

-- Detect unexpected values
SELECT column_name, COUNT(*) as cnt
FROM <table>
GROUP BY column_name
ORDER BY cnt DESC
LIMIT 20;

-- Check for join explosion
SELECT COUNT(*) as pre_join FROM table_a;
SELECT COUNT(*) as post_join FROM table_a a JOIN table_b b ON a.id = b.a_id;
```
