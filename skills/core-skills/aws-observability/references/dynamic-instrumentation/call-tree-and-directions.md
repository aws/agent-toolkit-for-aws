# Call Tree and Investigation Directions

Visual call tree patterns and correlation-guided direction choices.

## Visual Call Tree for Debugging

Use a visual tree structure to represent the debugging process. This helps:

1. **Visualize the call graph** - see how functions relate to each other
2. **Track investigation progress** - annotate nodes with status
3. **Communicate findings** - show the user what's been checked and what hasn't
4. **Document the path to root cause** - trace the issue through the tree

### Node Annotations

Use these annotations to mark the status of each node:

| Annotation | Meaning                                           |
| ---------- | ------------------------------------------------- |
| `OK`       | **Cleared** - No issue found in this code path    |
| `X`        | **Issue Found** - Bug or problem identified here  |
| `?`        | **Investigating** - Currently analyzing this node |
| `...`      | **Pending** - Need to investigate but haven't yet |

### Building the Call Tree

Start from the entry point and expand as you investigate. Example for a user registration service:

```
register_user() [entry point - auto-instrumented, skip]
├── validate_email(email) ...
├── check_username_available(username) ? [investigating - slow calls observed]
│   └── query_user_database(username) ...
├── hash_password(password) ...
├── create_user_record(user_data) ...
│   └── insert_into_database(record) ...
└── send_welcome_email(email) ...
```

### Detailed Node Expansion

When investigating a specific function, expand it to show internal logic:

```
check_username_available("john_doe") X [BUG FOUND - case sensitivity issue]
├── normalized = normalize_username("john_doe")
│   └── result: "john_doe" (no change)
├── query = build_query(normalized)
│   └── SQL: SELECT * FROM users WHERE username = 'john_doe'
├── result = execute_query(query)
│   └── Found: "John_Doe" exists X [case-insensitive match missed!]
├── return: True (available) X WRONG - should be False
└── Root cause: Query uses case-sensitive comparison but
    usernames should be case-insensitive
```

### Annotating with Evidence

Include snapshot data evidence directly in the tree:

```
process_checkout("order-5678", cart=[...])
├── Duration: 2,847ms X [SLOW - SLA is 500ms]
├── Input: cart = [
│   {"sku": "LAPTOP-001", "qty": 1},
│   {"sku": "MOUSE-002", "qty": 2}
│   ]
├── check_inventory("LAPTOP-001") OK
│   ├── Duration: 45ms [normal]
│   └── Evidence: Snapshot @ 14:22:03.112
├── check_inventory("MOUSE-002") OK
│   ├── Duration: 38ms [normal]
│   └── Evidence: Snapshot @ 14:22:03.157
├── calculate_shipping(address) X
│   ├── Duration: 2,651ms [SLOW!]
│   ├── Evidence: Snapshot @ 14:22:03.201
│   └── ? Need to investigate downstream calls
└── Return: {order_id: "ORD-9999", total: 1249.99}
```

### Comparing Good vs Bad Cases

Use side-by-side trees for comparison:

```
FAST REQUEST (domestic):               SLOW REQUEST (international):

calculate_shipping(addr)               calculate_shipping(addr)
├── country: "US"                      ├── country: "JP"
├── get_rates() → cache HIT OK          ├── get_rates() → cache MISS
├── duration: 12ms                     │   └── fetch_from_api()
└── return: $9.99                      │       └── duration: 2,340ms X
                                       ├── duration: 2,651ms
                                       └── return: $89.99
```

### Progressive Investigation Tree

Update the tree as you investigate deeper:

#### Step 1: Initial investigation

```
submit_payment()
├── validate_card() ? [some calls failing - investigating]
├── check_fraud() ?
├── charge_card() ?
└── send_receipt() ?
```

#### Step 2: After analyzing validate_card

```
submit_payment()
├── validate_card() ? [fails for certain card types]
│   ├── check_luhn() OK [algorithm correct]
│   ├── check_expiry() OK [date parsing correct]
│   └── check_card_type() X [fails for Amex cards]
├── check_fraud() OK [not reached when validation fails]
├── charge_card() OK [not reached when validation fails]
└── send_receipt() OK [not reached when validation fails]
```

#### Step 3: Drilling into check_card_type

```
submit_payment()
├── validate_card()
│   └── check_card_type("378282246310005") X
│       ├── Input: card_number starting with "37"
│       ├── Expected: "amex" (Amex starts with 34 or 37)
│       ├── Actual: "unknown" X
│       └── Bug: Regex pattern missing Amex prefix "37"
...
```

### Including in Reports

Include a "Call Tree" in your inline closure summary:

```markdown
## Call Tree

\`\`\`
submit_payment() [entry - auto-instrumented]
+-- validate_card(card_number) X ROOT CAUSE
| +-- check_luhn() OK
| +-- check_expiry() OK
| +-- check_card_type() X Missing Amex pattern "37"
+-- check_fraud() [not reached]
+-- charge_card() [not reached]
+-- send_receipt() [not reached]
\`\`\`

**Legend**: OK Cleared | X Issue | ? Investigating | ... Pending
```

---

## Connecting the Tree to Direction Choices

Use the call tree to choose the next move, not just to display progress. The node where the
tree first turns suspicious (`X` or `?`) determines the next direction — look it up in the
**Correlate → Decide** table in `dynamic-instrumentation.md` (Step 4). In short: an `X` on inputs sends you upstream, an
`X` on the return sends you downstream, a `?` on an intermediate value sends you line-level,
and mixed `OK`/`X` across runs sends you to multi-snapshot comparison.
