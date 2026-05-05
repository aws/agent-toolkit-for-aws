# Metadata Filtering

For full docs: search AWS docs for `"S3 Vectors metadata filtering"`

## Filterable vs Non-filterable

- **Filterable** (default): All metadata is filterable unless explicitly declared otherwise.
  Can be used in query `--filter` expressions. Limited to 2 KB per vector.
- **Non-filterable**: Declared at index creation via `--metadata-configuration`. Search AWS docs for `"S3 Vectors non-filterable metadata"` for JSON syntax.
  Cannot be used in filters but can store larger data. Total metadata per vector
  (filterable + non-filterable combined) is limited to 40 KB. Ideal for text
  chunks, descriptions, raw content. Immutable — cannot change after index
  creation. Max 10 non-filterable keys per index.

## Filter Operators

| Operator | Input types | Description |
|----------|------------|-------------|
| `$eq` | string, number, boolean | Exact match (default when no operator specified) |
| `$ne` | string, number, boolean | Not equal |
| `$gt` | number | Greater than |
| `$gte` | number | Greater than or equal |
| `$lt` | number | Less than |
| `$lte` | number | Less than or equal |
| `$in` | array of primitives | Match any value in array |
| `$nin` | array of primitives | Match none of the values |
| `$exists` | boolean | Check if field exists |
| `$and` | array of filters | Logical AND |
| `$or` | array of filters | Logical OR |

## Filter Examples

Simple equality (implicit `$eq`):

```json
{"genre": "documentary"}
```

Numeric range:

```json
{"year": {"$gte": 2020, "$lte": 2024}}
```

Array match:

```json
{"category": {"$in": ["science", "technology"]}}
```

Compound filter:

```json
{"$and": [{"genre": {"$eq": "drama"}}, {"year": {"$gte": 2020}}]}
```

Existence check:

```json
{"genre": {"$exists": true}}
```

## Key Rules

- `$eq` is implicit — `{"genre": "drama"}` equals `{"genre": {"$eq": "drama"}}`
- `$eq` on array metadata matches if input matches ANY element in the array
- Filtering is applied during search (not post-filter). All returned results satisfy the filter, but fewer than top-K may be returned when few vectors match
- Query with filter requires both `s3vectors:QueryVectors` AND `s3vectors:GetVectors`
