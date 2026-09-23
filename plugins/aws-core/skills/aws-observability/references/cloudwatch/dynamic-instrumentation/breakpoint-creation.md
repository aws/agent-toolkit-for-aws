# Breakpoint Creation and Troubleshooting Reference

How to specify a breakpoint correctly, and what to do when it misfires.

## Two Instrumentation Levels

A breakpoint targets one of two levels, decided by whether you set `line_number`:

- **Method-level** (set `method_name`, omit `line_number`): captures at function entry and
  exit — `capture_arguments`, `capture_return` (return value + throwable), and execution
  duration. Use for "what went in / what came out / how long." `capture_locals` does not
  apply at this level.
- **Line-level** (set `line_number`, 1-based): captures the local variables in scope **at
  that line** via `capture_locals`. Use to inspect intermediate state mid-function (after an
  assignment, at a branch). No return value or duration is captured.

Rule of thumb: start method-level to bracket a function; drop to line-level when you need a
specific intermediate value — and for void/`None` methods that mutate a field (see
"Void / None-Return Mutated Fields" below).

## BREAKPOINT vs PROBE

**Default to `BREAKPOINT`** for every debugging / root-cause task — line-level or method-level,
one-off inspection of arguments, return values, locals, or timing, including on a live service.
When unsure, use `BREAKPOINT`.

Use `PROBE` **only when the user explicitly asks** to either (1) capture past the `max_hits` cap, or
(2) run long-term / ongoing observability. A mention of "production" or "live traffic" alone does
not qualify — a normal investigation on a live service is still a `BREAKPOINT`.

- **BREAKPOINT** (default) — capture-limited by `max_hits` (default `100`); transitions to DISABLED
  once reached. Expires automatically at `ttl_hours` (set `ttl_hours = 24`). Supports line-level
  (`line_number`) and method-level targets.
- **PROBE** (exception only) — **method/function-level only** (`line_number` must be omitted; the
  script rejects a PROBE create that sets it), **not supported for JavaScript**, **no `max_hits`**
  (fires on every hit). **Never expires on its own — `ttl_hours` is ignored — so you MUST delete it
  explicitly when done.**

## Scoping to specific instances — `attribute_filters`

To apply a breakpoint only to certain service instances (e.g. one version or deployment), pass
`attribute_filters`: a list of groups, each a dict of OpenTelemetry resource-attribute names to
**exact-match** values (no wildcards/patterns), e.g.
`[{"service.version": "1.2.0", "deployment.environment": "staging"}]`. Conditions are AND-ed within a
group and groups are OR-ed together; up to 10 groups, keys 1–50 chars and values 1–100 chars. Omit
to apply to all instances.

## Capture-limit fields

When snapshot values come back truncated, raise the matching limit (all optional):
`max_string_length` (string truncation), `max_collection_width` (collection width),
`max_collection_depth` (nested collection depth), `max_object_depth` (object traversal depth),
`max_fields_per_object` (object field count), `max_stack_frames` / `max_stack_trace_size` (stack
capture). `capture_stack_trace` toggles stack capture (on by default). For truncated Java
`Map`/`HashMap` contents, raise `max_object_depth` / `max_collection_width`.

## Location Fields

- `file_path`: source file path in the running application.
- `code_unit`: Python module or Java package.
- `class_name`: class name when targeting a class method.
- `method_name`: function/method name.
- `line_number`: required for line-level breakpoints; omit for function/method-level.

## Python Mapping

- `code_unit` = the target's **importable dotted module name** — the exact string you would put in
  an `import` statement for that module. The SDK resolves it with `importlib.import_module(code_unit)`
  and then looks up `method_name` on the result, so it must be the module *as the running app
  imports it*, not just the filename.
  - Derive it from the file path **relative to the import root** (the `sys.path` entry / working
    dir the app runs from): drop the `.py` and replace `/` with `.`, keeping every package segment.
  - Use `"__main__"` only for the script entrypoint (the file run as `python foo.py`).
  - If unsure of the import root, prefer the longest dotted path that `import_module` would accept
    and that exposes `method_name`.
- `method_name` = function name; `class_name` = class name if the method is in a class.
- Line numbers start at 1.

**What "import root" means.** Dotted module names are resolved *relative to the directory the app
is launched from* (the `sys.path` entry that holds your code), not from the filesystem root. The
same file gets a different `code_unit` depending on that root:

```text
/srv/checkout/          <- import root (on sys.path: the dir the app runs from)
|-- services/
|   |-- __init__.py
|   `-- billing.py      <- defines generate_invoice()
`-- main.py

# import root = /srv/checkout    -> `import services.billing` -> code_unit "services.billing"  (keep `services`)
# import root = /srv/checkout/services -> `import billing`     -> code_unit "billing"
```

The absolute path (`/srv/checkout/services/billing.py`) is irrelevant; only the path *from the
import root down to the file* becomes the dotted name. A truncated `code_unit` (e.g. just
`services`, the package) imports successfully but lacks the function, so the breakpoint never
installs.

```json
// create arguments (Python method-level)
// import root /srv/checkout, file services/billing.py, function generate_invoice(...)
//   -> code_unit "services.billing"
{
  "instrumentation_type": "BREAKPOINT", "language": "Python",
  "file_path": "services/billing.py",
  "code_unit": "services.billing",
  "method_name": "generate_invoice",
  "capture_arguments": ["invoice_id", "customer_id", "amount"],
  "ttl_hours": 24
}
```

### Direct import aliasing (important)

If a target function is imported by value (`from mod import func`), the SDK only wraps the
function inside the **defining** module and does not update imported aliases — so a breakpoint
on the defining module may never fire. Instead, target the **importing** module:

- `file_path` = the importing file (e.g. `__main__` → the app entrypoint).
- `method_name` = the alias as used at the call site. For `from mod import func`, use `func`.
  For `from mod import func as f`, use `f`.

## Java Mapping

**Use the simple class name, NOT the fully qualified name.**

- `code_unit` = package name (e.g., `com.amazon.sampleapp`).
- `class_name` = **simple class name only** (e.g., `OrderService`, not `com.example.OrderService`).
- `method_name` = method name. Note: Java may have **overloaded methods** (same name, different
  params) — an ambiguous target surfaces as `OVERLOADED_METHODS`; disambiguate by signature.

```json
// Given: package com.amazon.sampleapp; public class OrderContext { ... }
// create arguments (Java method-level)
{
  "instrumentation_type": "BREAKPOINT", "language": "Java",
  "file_path": "/path/to/OrderContext.java",
  "code_unit": "com.amazon.sampleapp",
  "class_name": "OrderContext",
  "method_name": "getCustomer",
  "capture_arguments": ["customerId"],
  "ttl_hours": 24
}
// code_unit = package name; class_name = simple name (NOT com.amazon.sampleapp.OrderContext)
// capture_arguments = the REAL parameter name from the signature ("customerId"), NOT "arg0".
// The snapshot may later render it as arg0 — that is a read-time concern, not a create input.
```

## JavaScript Mapping

**JavaScript binds by `file_path` + `line_number` only** — it is always line-level.

- `line_number` is **required** (>= 1); `code_unit`, `class_name`, and `method_name` are not
  used.
- Point `line_number` at the executable statement you want to observe.
- A breakpoint on a non-executable line **slides to the next parseable line** and fires there
  (unlike Python/Java, where it is ignored and never fires) — verify it lands where you intend.
- **PROBE is not supported for JavaScript** — use `instrumentation_type=BREAKPOINT`.

## Pre-flight Checklist

Before creating a breakpoint, read the relevant source files and verify:

1. `file_path` matches the deployed runtime source path.
2. `code_unit` matches the module/package exactly.
3. `class_name` is the simple name for Java (not FQCN).
4. `method_name` matches the executed symbol name.
5. `line_number` is executable code if line-level.
6. `capture_arguments` lists the **real parameter names from the source signature** (for Java too —
   never `arg0`/`arg1`; those only show up when reading the snapshot, never as a create input).

## Code Snippet Display (when proposing breakpoints)

When proposing breakpoints, **read the local source file** and display a code snippet so the
user can verify the location.

**Method-level:**

```
File: /app/product_service.py
Class: CacheKeyNormalizer  (omit if no class)
Method: def normalize_for_lookup(self, product_id)
Capture arguments: ["product_id"]
```

**Line-level (target line + 2 lines context):**

```
File: /app/product_service.py
   40|     key = product_id
   41|     if settings["strip_whitespace"]:
>> 42|         key = key.strip()
   43|     if settings["lowercase"]:
   44|         key = key.lower()
Capture locals: ["key"]
```

## Argument Names

The `create` operation requires explicit `capture_arguments` — argument names are not inferred,
and it rejects both `["*"]` and an empty list. (Line-level breakpoints use `capture_locals` the
same way, and a line-level create requires `capture_locals`.)

**Python:** read the source file directly, match the function/method signature, and list the
parameter names explicitly in `capture_arguments`.

**Java — create with the REAL names; snapshots may rename them positionally.** These are two
separate phases and the names differ between them. Do not confuse them:

1. **At `create` time:** pass the **real parameter names from the source signature** in
   `capture_arguments` (e.g. `["amount", "orderId"]`) — exactly as for Python. Read the source and
   use those exact names. **Never pass `arg0`/`arg1` to `create`** — positional placeholders are
   not valid breakpoint inputs and will not match the method's parameters.
2. **When reading the resulting snapshot:** Java bytecode does not always preserve parameter names,
   so the *captured values* may come back under **positional** keys (`arg0`, `arg1`, ...) no matter
   which real names you created with. Map those positional keys back to the signature by order:

```
# What you pass at CREATE (real source names):
#   capture_arguments = ["productId", "quantity", "couponCode", "state"]
#
# Method signature:
#   calculateTotal(String productId, int quantity, String couponCode, String state)
#
# How the captured values may appear when READING the snapshot (positional):
#   arg0 = productId
#   arg1 = quantity
#   arg2 = couponCode
#   arg3 = state
```

When building snapshot search filters (reading phase), use the positional names that actually
appear in the captured data:

```
@message like /"arg0"/ and @message like /"laptop"/     # filter by productId
@message like /"arg1"/ and @message like /"10"/          # filter by quantity
```

(Filters match what is *in the snapshot* — `arg0`/`arg1` — not the real names you created with.)

## max_hits and DISABLED

Breakpoints stop capturing after `max_hits` is reached, and their status transitions to
**DISABLED**. Use `max_hits=100` as the default. If a breakpoint is DISABLED due to max_hits
exhaustion and you need more snapshots, delete it and recreate it with the same parameters (or
a higher `max_hits`). When doing multi-phase debugging, check whether earlier breakpoints are
still ACTIVE before relying on them for new data. To recover ACTIVE timestamps from a
disabled breakpoint, run `di_instrumentation.py get-status` with an earlier time
range, then use those timestamps to fetch snapshots.

## Void / None-Return Mutated Fields

**HARD RULE: If the target method returns `void` (Java) or `None` (Python), you MUST place a
line-level breakpoint on the line immediately after the assignment. Do NOT use a method-level
breakpoint to observe a mutated field.**

**Do not rely on `capture_return` for void methods.** This is a common false assumption:
"Java passes objects by reference, so `capture_return=true` will show the mutated field at
method exit." **This is wrong.** For void/None methods the SDK omits the `return` key from the
snapshot entirely — there is no `body.captures.return`. The `capture_arguments` snapshot
reflects **entry state only**, so a field assigned inside the method still shows its pre-call
value (`0`, `null`, or default). Setting `capture_return=true` on a void method does not
re-capture argument fields at exit.

What a method-level breakpoint on a void method actually gives you:

- No `body.captures.return` key at all
- The mutated field stuck at its pre-call value in `body.captures.entry.arguments`

The ONLY way to observe the post-mutation value is a **line-level breakpoint on the line
immediately after the assignment**, capturing the mutated object as a local:

```java
// Java example
void applyCouponDiscount(PricingContext ctx) {
    ctx.couponSavings = round(ctx.subtotal * couponRate);  // line 57
    ctx.orderAmount = ctx.orderAmount - ctx.couponSavings; // line 58  ← breakpoint here
}
// At line 58, ctx.couponSavings is already set — it appears in body.captures.lines.58.locals.ctx
```

**Proof (real snapshot from a method-level breakpoint on a `void` Java method with
`capture_return=true`).** Note: there is NO `return` key, and `couponSavings` is `0.0` even
though the method sets it — because the snapshot is entry-state only:

```json
{
  "body": {
    "captures": {
      "entry": {
        "arguments": {
          "ctx": {
            "type": "com.amazon.sampleapp.PricingService$PricingContext",
            "fields": {
              "subtotal": { "type": "java.lang.Double", "value": "299.99" },
              "orderAmount": { "type": "java.lang.Double", "value": "299.99" },
              "couponSavings": { "type": "java.lang.Double", "value": "0.0" }
            }
          }
        }
      }
    }
  }
}
```

There is no `body.captures.return`. `capture_return=true` was set and still produced nothing
at exit. This is why you must use a line-level breakpoint.

**When to apply this pattern:**

- Method signature is `void` / returns `None` (this alone is enough — apply the rule)
- The value you need is assigned inside the method, not passed in as an argument
- Method-level breakpoint snapshot shows the field as `0`, `null`, or its default value, and
  has no `body.captures.return` key

## Troubleshooting Playbooks

### Breakpoint in ERROR state

Check the `ErrorCause` field and act on it:

- `FILE_NOT_FOUND` — the file path may not match the running application.
- `METHOD_NOT_FOUND` — the function name may be incorrect or not loaded.
- `LINE_NOT_EXECUTABLE` — the line may be a comment, blank, or declaration.
- `OVERLOADED_METHODS` — ambiguous Java method; disambiguate by signature.
- `LANGUAGE_MISMATCH` — the wrong `language` was specified.
- `RUNTIME_ERROR` — other runtime failure.

Record the error and notify the user with the specific cause.

### Breakpoint stays in READY (no traffic)

The breakpoint installed but received no traffic. Tell the user, and ask whether this code
path is actually being executed and whether to wait longer or try a different location. If
traffic is known to hit the function but it stays READY, re-check Python direct-import aliasing
(instrument the importing module — see "Direct import aliasing" above).

### Breakpoint in DISABLED state

`max_hits` was exceeded. See "max_hits and DISABLED" above — recover ACTIVE timestamps via
`di_instrumentation.py get-status` with an earlier time range, then delete and recreate
with a higher `max_hits` if more data is needed.

### No snapshot data found

1. Check your timestamp — try the 2nd or 3rd most recent ACTIVE event, not just the latest
   (older events have had more time to ingest).
2. CloudWatch Logs has ingestion delay (typically 1–3 minutes); wait and retry.
3. If still no data after waiting, notify the user.

## Parallel Breakpoints

Usually a single, well-chosen breakpoint is enough. Set **multiple breakpoints at once** only
when you genuinely don't know which of several functions is implicated — e.g. a latency chain
with several branches (compare durations), or an intermittent value/cache bug where you need
data from the **same request** across functions before the next problematic request arrives. If
you already have a strong hypothesis about one function, start there and expand only if needed.
