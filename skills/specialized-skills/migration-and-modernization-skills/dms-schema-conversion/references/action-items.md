# Working with Action Items

After assessment or conversion, DMS Schema Conversion exports an conversion assessment report to S3 containing three CSV files. These files describe conversion issues that require manual review or fixes.

---

## Conversion Assessment Report CSV Files

The conversion assessment report is exported via `export-metadata-model-assessment` and produces a ZIP archive in S3 containing:

### 1. Summary CSV (`<target>_Summary.csv`)

High-level conversion statistics by object category.

| Column | Description |
|--------|-------------|
| Category | Object type (TABLE, CONSTRAINT, INDEX, SCHEMA, etc.) |
| Number of objects | Total objects in this category |
| Objects automatically converted | Objects converted without issues |
| Objects with simple actions | Objects with simple-complexity action items |
| Objects with medium-complexity actions | Objects with medium-complexity action items |
| Objects with complex actions | Objects with complex-complexity action items |
| Total lines of code | Lines of source code in this category |

Also includes metadata rows: `SQL_syntax_elements_number`, `Storage_objects_count`, `Code_objects_count`, and source database version information.

### 2. Detailed Action Items CSV (`<target>.csv`)

Every individual occurrence of a conversion issue, with exact location.

| Column | Description |
|--------|-------------|
| Category | Object type (table, constraint, procedure, etc.) |
| Occurrence | Full path to the affected object in the metadata tree |
| Action item | Numeric action item ID |
| Subject | Brief subject (may be empty) |
| Group | Issue group description |
| Description | Detailed explanation of the issue |
| Documentation references | Links to relevant documentation |
| Recommended action | What to do to fix the issue |
| Filtered | Whether this item was filtered |
| Estimated complexity | `Simple`, `Medium`, `Complex`, or `Info` |
| Line | Line number in source DDL |
| Position | Character position in source DDL |
| Source | Source server identifier |
| Target | Target server identifier |
| Server IP address and port | Source connection endpoint |
| Database name | Database containing the object |
| Schema name | Schema containing the object |

### 3. Action Items Summary CSV (`<target>_Action_Items_Summary.csv`)

Aggregated view — one row per unique action item type per schema.

| Column | Description |
|--------|-------------|
| Schema | Schema where the issues occur |
| Action item | Numeric action item ID |
| Number of occurrences | How many times this issue appears |
| Learning curve efforts | One-time effort to understand the issue (hours) |
| Efforts to convert an occurrence | Effort per occurrence (hours) |
| Action item description | What the issue is |
| Recommended action | How to resolve it |

---

## Reviewing Action Items

When the customer asks to review or work through action items:

1. **Start from the Summary CSV** to understand scope — how many objects need attention and at what complexity level.

2. **Use the Action Items Summary CSV** to prioritize — focus on items with highest occurrence count or highest complexity first.

3. **Use the Detailed CSV** to locate each specific object in the metadata tree by its `Occurrence` path.

---

## Fixing Action Items

When the customer asks to fix Action Items (e.g., "fix the action items", "help me resolve these"):

### Step 1 — Verify existing conversion

Before proposing any fixes, confirm the object has already been converted by checking for existing TARGET DDL. Use the object's `Occurrence` path from the Detailed CSV to build `explicit` selection rules targeting that specific object: [Selection rules in DMS Schema Conversion](https://docs.aws.amazon.com/dms/latest/userguide/sc-selection-rules.html)

If `TargetMetadataModels` is populated in the response, the object has been converted. Extract `TargetMetadataModels[0].SelectionRules` and verify target DDL:

```
aws dms describe-metadata-model \
  --migration-project-identifier <migration_project_identifier> \
  --origin TARGET \
  --selection-rules '<target_selection_rules_from_above>'
```

- **If TARGET DDL exists** (i.e., `Definition` is non-empty) → the object was already converted by the DMS Schema Conversion engine. Proceed to Step 2 to apply targeted fixes to the action-item-affected code only. Do NOT trigger a full reconversion.
- **If TARGET DDL does not exist** (i.e., `TargetMetadataModels` is empty or `Definition` is empty) → inform the customer that this object has not been converted yet and ask whether they want to convert it first (via [Convert Database](../SKILL.md#convert-database)) before fixing action items.

### Step 2 — Export and prepare

1. **Export target as SQL script:** Use `--origin TARGET` with selection rules containing the **target** server name (from `TargetMetadataModels[0].SelectionRules` in Step 1):

   ```
   aws dms start-metadata-model-export-as-script \
     --migration-project-identifier <migration_project_identifier> \
     --origin TARGET \
     --selection-rules '<json>'
   ```

   > **Important:** The `server-name` must be the target data provider server name (e.g., `"virtual"` for virtual targets), NOT the source server name. The schema name also uses the target naming convention (e.g., `bobsusedbookstore_dbo` instead of `dbo`).

   Wait via `aws dms wait metadata-model-exported-as-script --migration-project-identifier <migration_project_identifier>`. Download the exported SQL file from S3 and restrict permissions:

   ```
   aws s3 cp s3://<bucket>/<S3ObjectKey> ./exported_target.sql
   chmod 600 ./exported_target.sql
   ```

2. **Make a working copy:** Copy the exported SQL file locally. All fixes are applied to this copy — the original remains untouched as a reference.

3. **Load the Detailed CSV** to get the list of affected objects grouped by occurrence path.

### Step 3 — Targeted fixes (preserve rule-based conversion)

For each affected object:

1. **Locate the action-item scope:** Use the `Line` and `Position` columns from the Detailed CSV to identify the exact lines/section of code covered by the action item.

2. **Fix only the action-item-affected code.** Rewrite ONLY the specific lines or code block identified by the action item. The surrounding DDL produced by the DMS Schema Conversion rule-based engine MUST remain untouched.

3. **Mark generated code:** Wrap any agent-generated SQL with a comment indicating it requires verification:

   ```sql
   -- [GenAI-generated] Begin. Requires verification.
   <generated SQL>
   -- [GenAI-generated] End.
   ```

4. **Present the fix:** Show the customer:
   - The original action-item-affected code (before)
   - The proposed replacement (after)
   - A plain-language explanation of what was changed and why

5. **On customer confirmation**, apply the replacement to the working copy.

6. **Move to the next action item.**

### Step 4 — Completion

After all fixes, the customer has a corrected SQL script they can apply to the target database manually or review further.

**Constraints:**

- You MUST verify that TARGET DDL exists (Step 1) before proposing fixes — do NOT assume conversion has run.
- You MUST fix only the code covered by the action item — do NOT reconvert or rewrite the entire object. Full-object reconversion MUST only happen if the customer explicitly requests it (e.g., "reconvert the whole object", "redo the entire procedure").
- You MUST mark all agent-generated SQL with `-- [GenAI-generated]` comments so the customer can identify what needs verification.
- You MUST process objects one at a time and get customer confirmation before modifying each.
- You MUST show the original and proposed DDL so the customer has full context.
- You MUST explain the action item in plain language — do not just repeat the CSV description verbatim.
- You MUST only modify the specific lines for the affected object — do not alter other objects in the file.
- For `Info`-level items, inform the customer these are informational and may not require changes — ask if they want to review or skip them.
- If the customer explicitly asks to reconvert an entire object, use `start-metadata-model-conversion` with selection rules scoped to that object and inform them that the full rule-based conversion output will be replaced.

---

## Security Considerations

Conversion assessment reports and exported SQL scripts contain sensitive infrastructure metadata including server endpoints, database names, schema structures, and DDL definitions. When working with these files:

- You MUST recommend that the customer deletes local working copies of SQL files and CSV reports after the fixing workflow completes.
- These operations are logged via CloudTrail for audit and compliance purposes.
