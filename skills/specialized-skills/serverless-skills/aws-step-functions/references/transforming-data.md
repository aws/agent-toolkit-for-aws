# Data Transformation Patterns

## JSONata Expression Syntax

JSONata expressions are written inside `{% %}` delimiters in string values:

```json
"Output": "{% $states.input.customer.name %}"
"TimeoutSeconds": "{% $timeout %}"
"Condition": "{% $states.input.age >= 18 %}"
```

Rules:

- The string must start with `{%` (no leading spaces) and end with `%}` (no trailing spaces).
- Not all fields accept JSONata — `Type` and `Resource` must be constant strings.
- JSONata expressions can appear in string values within objects and arrays at any nesting depth.
- A string without `{% %}` is treated as a literal value.
- All string literals inside JSONata expressions must use single quotes (`'text'`), not double quotes. The expression is already inside a JSON double-quoted string, so double quotes would break the JSON.
- Complex logic is wrapped in `( expr1; expr2; ...; finalExpr )` where semicolons separate sequential expressions and the last expression is the return value.
- You cannot use `$` or `$$` at the top level.
- You cannot use unqualified field names at top level.
- Use `$parse()` instead `$eval` for deserializing JSON strings.
- Expressions must produce a defined value because JSON cannot represent undefined.

### String Quoting

```json
"Output": "{% 'Hello ' & $states.input.name %}"
"Condition": "{% $states.input.status = 'active' %}"
```

Never use double quotes inside the expression:

```
❌  "Output": "{% "Hello" %}"
✓  "Output": "{% 'Hello' %}"
```

### Local Variable Binding with `:=`

Use `:=` inside `( ... )` blocks to bind intermediate values within a single JSONata expression. Semicolons separate each binding, and the last expression is the return value:

```json
"Output": "{% ( $subtotal := $sum($states.input.items.price); $tax := $subtotal * 0.1; $discount := $exists($couponValue) ? $couponValue : 0; {'subtotal': $subtotal, 'tax': $tax, 'discount': $discount, 'total': $subtotal + $tax - $discount} ) %}"
```

You can also define local helper functions:

```json
"Assign": {
  "summary": "{% ( $formatPrice := function($amt) { '$' & $formatNumber($amt, '#,##0.00') }; $subtotal := $sum($states.input.items.price); {'itemCount': $count($states.input.items), 'subtotal': $formatPrice($subtotal), 'total': $formatPrice($subtotal * 1.1)} ) %}"
}
```

Local variables bound with `:=` exist only within the `( ... )` block. They do not affect state machine variables. To persist values across states, use the `Assign` field.

### Filtering Arrays

```json
"Output": {
  "expensiveItems": "{% $states.input.items[price > 100] %}"
}
```

### Aggregation

```json
"Output": {
  "total": "{% $sum($states.input.items.price) %}",
  "average": "{% $average($states.input.items.price) %}",
  "count": "{% $count($states.input.items) %}"
}
```

### String Operations

```json
"Output": {
  "fullName": "{% $states.input.firstName & ' ' & $states.input.lastName %}",
  "upper": "{% $uppercase($states.input.name) %}",
  "trimmed": "{% $trim($states.input.rawInput) %}"
}
```

### Object Merging

```json
"Output": "{% $merge([$states.input, {'processedAt': $now(), 'status': 'complete'}]) %}"
```

### Building Lookup Maps with `$reduce`

Use `$reduce` to transform an array into a key-value object:

```json
"Assign": {
  "priceByProduct": "{% $reduce($states.input.items, function($acc, $item) { $merge([$acc, {$item.productId: $item.price}]) }, {}) %}"
}
```

Given `[{"productId": "A1", "price": 10}, {"productId": "B2", "price": 25}]`, this produces `{"A1": 10, "B2": 25}`.

### Dynamic Key Access with `$lookup`

Use `$lookup` to access an object property by a variable key:

```json
"Output": {
  "price": "{% $lookup($priceByProduct, $states.input.productId) %}"
}
```

This is essential when you've built a mapping object with `$reduce` and need to retrieve values dynamically. Standard dot notation (`$priceByProduct.someKey`) only works with literal key names.

### Conditional Values

```json
"Output": {
  "tier": "{% $states.input.total > 1000 ? 'gold' : 'standard' %}",
  "discount": "{% $exists($states.input.coupon) ? 0.1 : 0 %}"
}
```

### Array Membership with `in` and Concatenation with `$append`

Test if a value exists in an array with `in`:

```json
"Condition": "{% $states.input.status in ['pending', 'processing', 'shipped'] %}"
```

Concatenate arrays with `$append`:

```json
"Assign": {
  "allIds": "{% $append($states.input.orderIds, $states.input.returnIds) %}"
}
```

### Array Mapping

```json
"Output": {
  "names": "{% $states.input.users.(firstName & ' ' & lastName) %}"
}
```

### Generating UUIDs and Random Values

```json
"Assign": {
  "requestId": "{% $uuid() %}",
  "randomValue": "{% $random() %}"
}
```

### Partitioning Arrays

```json
"Assign": {
  "batches": "{% $partition($states.input.items, 10) %}"
}
```

### Parsing JSON Strings

```json
"Assign": {
  "parsed": "{% $parse($states.input.jsonString) %}"
}
```

### Hashing

```json
"Assign": {
  "hash": "{% $hash($states.input.content, 'SHA-256') %}"
}
```

### Timestamp Comparison with `$toMillis`

JSONata timestamps are strings, so you can't compare them directly with `<` or `>`. Use `$toMillis` to convert to numeric milliseconds:

```json
"Condition": "{% $toMillis($states.input.orderDate) > $toMillis($states.input.cutoffDate) %}"
```

Useful for sorting timestamps, calculating durations, or finding the most recent entry:

```json
"Assign": {
  "ageMinutes": "{% $round(($toMillis($now()) - $toMillis($states.input.createdAt)) / 60000, 2) %}",
  "mostRecent": "{% $sort($states.input.timestamps, function($a, $b) { $toMillis($a) < $toMillis($b) })[0] %}"
}
```

## Step Functions Built-in functions

| Function | Purpose |
|----------|---------|
| `$partition(array, size)` | Partition array into chunks |
| `$range(start, end, step)` | Generate array of values |
| `$hash(data, algorithm)` | Calculate hash (MD5, SHA-1, SHA-256, SHA-384, SHA-512) |
| `$random([seed])` | Random number 0 ≤ n < 1, optional seed |
| `$uuid()` | Generate v4 UUID |
| `$parse(jsonString)` | Deserialize JSON string |
