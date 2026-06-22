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

1. **Export target as SQL script:**

   ```
   aws dms start-metadata-model-export-as-script \
     --migration-project-identifier <migration_project_identifier> \
     --origin TARGET \
     --selection-rules '<json>'
   ```

   Wait via `aws dms wait metadata-model-exported-as-script --migration-project-identifier <migration_project_identifier>`. Download the exported SQL file from S3 and restrict permissions:

   ```
   aws s3 cp s3://<bucket>/<S3ObjectKey> ./exported_target.sql
   chmod 600 ./exported_target.sql
   ```

2. **Make a working copy:** Copy the exported SQL file locally. All fixes are applied to this copy — the original remains untouched as a reference.

3. **Load the Detailed CSV** to get the list of affected objects grouped by occurrence path.

4. **For each affected object:**
   a. Locate the object's DDL in the SQL file — find the line where the object's `CREATE` statement begins (match by object name from the `Occurrence` column).
   b. Analyze the action item description and the current DDL at that location.
   c. Propose the corrected SQL to the customer — explain the issue in plain language and show the before/after.
   d. On customer confirmation, replace the relevant portion of the DDL in the working copy.
   e. Move to the next object.

5. **After all fixes:** The customer has a corrected SQL script they can apply to the target database manually or review further.

**Constraints:**

- You MUST process objects one at a time and get customer confirmation before modifying each.
- You MUST show the original and proposed DDL so the customer has full context.
- You MUST explain the action item in plain language — do not just repeat the CSV description verbatim.
- You MUST only modify the specific lines for the affected object — do not alter other objects in the file.
- For `Info`-level items, inform the customer these are informational and may not require changes — ask if they want to review or skip them.

---

## Security Considerations

Conversion assessment reports and exported SQL scripts contain sensitive infrastructure metadata including server endpoints, database names, schema structures, and DDL definitions. When working with these files:

- You MUST recommend that the customer deletes local working copies of SQL files and CSV reports after the fixing workflow completes.
- These operations are logged via CloudTrail for audit and compliance purposes.
