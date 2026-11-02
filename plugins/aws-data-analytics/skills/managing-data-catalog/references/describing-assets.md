# Describing assets: descriptions, README, ownership, columns

The operations here are well known and you probably know them already. What
goes wrong is the **merge**, the **surface**, and the **content**. This chapter
is about those three.

## What a good description says

A description that lists the columns has documented nothing: the column names
were already in the catalog. State what the data means and what it shows,
including where it is incomplete or surprising.

- You MUST look at the data or its quality results before writing, not only at
  the schema. A table's meaning is often not guessable from its name.
- You MUST state the finding, not the framing. Naming what the table holds
  describes it; saying what the data turned out to show is the documentation the
  user asked for. The contrast pair below is the same table written both ways.
- If a data quality score, a row count or a coverage gap changes how the table
  should be read, say so. A table that covers only part of the population, or
  starts partway through the history, or whose key column is nullable in
  practice, is a table a consumer will misuse unless the description says so.
- Keep it to what a consumer needs to decide whether to use the table. No
  credentials, no PII values, no cross-account ARNs.

### The failure has a shape, so here it is twice

The wrong version is not lazy or short. It is usually fluent, accurate about the
structure, and written without looking at a single value, which is why it passes
a self-review. Both of these describe the same imaginary table.

**Not this.** *"Monthly active users by region. Each row is one region and one
month, and reports the count of active users along with the month-over-month
change."*

That is a schema restated in sentences. Every fact in it was already in the
catalog: a consumer learns nothing they could not have read off the column list,
and nothing in it could have come out differently whatever the data said.

**This.** *"Monthly active users by region. Usage is concentrated in two
regions that together account for about four fifths of activity, so a
region-level average is misleading. The EMEA series begins partway through the
history because collection started then, and those earlier months are absent
rather than zero, so the month-over-month change is not meaningful for its first
month."*

Two tests that separate them, and both are cheap to apply to your own draft:

- **Could you have written it without reading the data?** If yes, you have
  documented the schema. Every clause in the second version is a claim that could
  have turned out false.
- **Could a consumer decide NOT to use the table from what you wrote?** A
  description that can only encourage use is a sales page. The limits are the
  most valuable part of it, and they are the part a schema cannot supply.

If the table exists to answer a question, the description states the answer,
**including when the answer is that the effect the table was built to measure is
not present in the data, or that the data cannot settle it.** A null result is a
finding, and it is the one most often left unwritten, because it feels like
having found nothing. It is not: a consumer who does not know it will read the
table as evidence for the thing it disproves.

## SageMaker Catalog

### The merge is the whole hazard

`CreateAssetRevision` **replaces the entire record**. Anything you do not send
is dropped, the call still succeeds, and the console still shows the field you
asked for. `AssetCommonDetailsForm` is the sharp edge, because it carries
`summary`, `readMe` and `sourceIdentifier` in one form, so writing a README by
sending only that field unbinds the asset from the table it describes.

The API protects the technical form (`GlueTableForm`) and refuses a revision
that omits it. It does **not** protect `AssetCommonDetailsForm`, which is the
reverse of what you would expect. An omitted `glossaryTerms` clears every
association.

Where each field lives:

| Field | Home |
|---|---|
| short description | the asset's own `description` |
| README | `AssetCommonDetailsForm.readMe` |
| summary | `AssetCommonDetailsForm.summary` |
| binding to the source table | `AssetCommonDetailsForm.sourceIdentifier`; never write this yourself |
| column names, descriptions, terms | `ColumnBusinessMetadataForm` |
| glossary term associations | the top-level `glossaryTerms` list |

### The canonical read-modify-write

Run this as given, substituting the four variables. It preserves every form,
patches one field, and prints a before/after comparison. Do not compose your
own from memory.

It **patches a form that is already on the asset**. It cannot add one: if `$FORM`
is not in `formsOutput`, as with `ColumnBusinessMetadataForm` on a freshly
crawled asset, the rebuild changes nothing and the write still succeeds with the
field never written. The guard after the snapshot turns that into a stop. To add
a form, follow "Applying it" in `references/metadata-forms.md`, which sources
the form's type revision rather than guessing it.

```bash
DOMAIN=<domain-id>; ASSET=<asset-id>
FORM=AssetCommonDetailsForm            # the form to patch
FIELD=readMe                           # the field inside it
VALUE='<the new value>'                # a string; for an object or array, see below

# 1. SNAPSHOT
aws datazone get-asset --domain-identifier "$DOMAIN" --identifier "$ASSET" \
  > /tmp/asset-before.json
jq -e --arg form "$FORM" 'any(.formsOutput[]; .formName == $form)' /tmp/asset-before.json >/dev/null \
  || { echo "Form $FORM is not on this asset -- add it (metadata-forms.md), do not write"; exit 1; }

# 2. Rebuild every form, patching only the target field. jq keeps the rest byte
#    for byte, and `readOnlyFormsOutput` is deliberately not read -- no form
#    input can write one. Omit --glossary-terms entirely when there are none:
#    the parameter has a minimum length of one and [] is refused client-side.
#    --arg inserts VALUE as a STRING. For an object or array, use --argjson.
jq --arg form "$FORM" --arg field "$FIELD" --arg value "$VALUE" '
  [ .formsOutput[]
    | . as $f
    | {formName, typeIdentifier: .typeName, typeRevision}
      + ( if $f.content then {content: $f.content} else {} end )
    | if .formName == $form
      then .content = ((.content // "{}") | fromjson | . + {($field): $value} | tojson)
      else . end ]
' /tmp/asset-before.json > /tmp/forms-input.json

TERMS=$(jq -r '[.glossaryTerms // [] | .[]] | join(" ")' /tmp/asset-before.json)

# 3. WRITE
if [ -n "$TERMS" ]; then
  aws datazone create-asset-revision --domain-identifier "$DOMAIN" \
    --identifier "$ASSET" --name "$(jq -r .name /tmp/asset-before.json)" \
    --forms-input file:///tmp/forms-input.json --glossary-terms $TERMS
else
  aws datazone create-asset-revision --domain-identifier "$DOMAIN" \
    --identifier "$ASSET" --name "$(jq -r .name /tmp/asset-before.json)" \
    --forms-input file:///tmp/forms-input.json
fi

# 4. VERIFY -- these three MUST all be non-empty and unchanged
aws datazone get-asset --domain-identifier "$DOMAIN" --identifier "$ASSET" \
  > /tmp/asset-after.json
echo "forms before/after:"; jq -r '[.formsOutput[].formName]|sort|join(",")' \
  /tmp/asset-before.json /tmp/asset-after.json
echo "sourceIdentifier:"; jq -r '.formsOutput[]|select(.formName=="AssetCommonDetailsForm")
  |(.content // "{}")|fromjson|.sourceIdentifier' /tmp/asset-after.json
echo "glossaryTerms:"; jq -c '.glossaryTerms' /tmp/asset-before.json /tmp/asset-after.json
```

If the form list shrank, or `sourceIdentifier` is now null, or the term list is
shorter, restore from `/tmp/asset-before.json` by running the same
`create-asset-revision` with the untouched forms, and tell the user what was
lost. A dropped term is recoverable. A dropped `AssetCommonDetailsForm` is not
recoverable from anything but your snapshot or a fresh data source run.

### Column-level business metadata

Two lookup traps, both of which read as a missing capability:

- The form **type** is `amazon.datazone.ColumnBusinessMetadataFormType`; the
  form **name** on an asset is `ColumnBusinessMetadataForm`. Querying the type
  by the form name answers `ResourceNotFoundException`.
- `ListIterableForms` and `BatchGetIterableForms` are **Glue** operations. They
  do not exist on the `datazone` client, and their absence there is not
  evidence that column metadata is unavailable.

Written through the same merge above, with `FORM=ColumnBusinessMetadataForm`,
`FIELD=columnsBusinessMetadata` and `VALUE` set to the array below. Bind it with
`--argjson value "$VALUE"` in place of `--arg value "$VALUE"`. `--arg` always inserts a
string, so the array would be stored as a quoted JSON string that no consumer can
parse. Read back the form after the write and check that `columnsBusinessMetadata` is
an array: `jq '.formsOutput[]|select(.formName=="ColumnBusinessMetadataForm")
|(.content // "{}")|fromjson|.columnsBusinessMetadata|type' /tmp/asset-after.json`
prints `"array"`.

Content shape:

```json
{"columnsBusinessMetadata": [
  {"columnIdentifier": "<column name>", "name": "<business name>",
   "description": "<what the column means>"}]}
```

Ignore entries that carry a bare `columnIdentifier` with no name or
description: a rejected AI prediction leaves stubs of exactly that shape, and
counting them reads as a documented column.

## Glue Data Catalog

> **Check availability first.** Before using the Glue business-context operations
> in this section (glossaries, terms, custom form types, catalog assets and
> attachments), check their availability and any stated limitations in the
> [AWS Glue documentation](https://docs.aws.amazon.com/glue/latest/dg/), and pass
> any caveat it gives on to the user. The table-layer operations (`Description`,
> column `Comment` and `Parameters` via `update-table`) are not part of that surface.

### There are two descriptions and they diverge permanently

| Surface | Written by | Read by |
|---|---|---|
| `Table.Description` | `glue update-table` | Athena, Spark, the Glue console, query engines |
| the catalog asset's `Description` | `glue update-asset` | `glue get-asset`, `glue search-assets`, agents |

Initially the asset layer mirrors the table. After the first `update-asset`,
that mirroring stops for good: a later `update-table` no longer propagates, and
no API can clear the asset-layer value: `update-asset` refuses an empty
description. So the two disagree permanently.

The trade to state to the user rather than decide silently: `update-asset` takes
only an identifier, a name and a description, so it **cannot** drop anything,
but query engines never see it. `update-table` is what a consumer sees, and it
is the destructive path. When the request says "the table", prefer
`update-table` with the recipe below and mention the other surface. When it says
"the catalog asset", use `update-asset`.

### The allow-list read-modify-write

`glue get-table` output cannot be fed back into `update-table`: six read-only
fields are rejected client-side, and stripping them reveals a seventh. Build the
input from an **allow-list** of the fourteen keys `TableInput` accepts, not a
deny-list you discover one error at a time.

The API rewards the wrong choice: the minimal write succeeds silently, the
correct one fails loudly. `update-table` with only a name and a description
returns exit 0 and leaves the table with no columns, no `Parameters`, no
`Location` and no `TableType`, which on an Iceberg table means no schema
**and** no pointer to its metadata. Athena then reports `Table
StorageDescriptor is null`.

```bash
DB=<database>; TBL=<table>; REGION=<region>
DESC='<the new table description>'

aws glue get-table --region "$REGION" --database-name "$DB" --name "$TBL" \
  > /tmp/table-before.json

jq --arg desc "$DESC" '
  .Table
  | {Name, Description, Owner, LastAccessTime, LastAnalyzedTime, Retention,
     StorageDescriptor, PartitionKeys, ViewOriginalText, ViewExpandedText,
     TableType, Parameters, TargetTable, ViewDefinition}
  | with_entries(select(.value != null))
  | .Description = $desc
' /tmp/table-before.json > /tmp/table-input.json

aws glue update-table --region "$REGION" --database-name "$DB" \
  --table-input file:///tmp/table-input.json

# VERIFY on get-table, NOT on the asset surface -- see below
aws glue get-table --region "$REGION" --database-name "$DB" --name "$TBL" \
  > /tmp/table-after.json
jq -r '.Table | "cols=\(.StorageDescriptor.Columns|length) params=\(.Parameters|keys|join(","))
  loc=\(.StorageDescriptor.Location) type=\(.TableType)"' \
  /tmp/table-before.json /tmp/table-after.json
```

To add column comments, patch `StorageDescriptor.Columns[].Comment` inside the
same `jq` filter: there is no per-column write on the table layer, so they
travel in the same full `TableInput`.

**Verify on `get-table` and nowhere else.** The column metadata layer is a
separate store: with a table's `StorageDescriptor` destroyed and `get-table`
returning null, `glue list-iterable-forms` still returns every column with its
comment intact, ninety seconds later. That is the surface an agent naturally
reaches for, and it cannot see the damage.

**Recovery.** If a definition is already destroyed, Glue's version history is
the repair path: `glue get-table-versions --database-name <db> --table-name <table>`,
pick the last good `VersionId`, and send its `TableInput` back through the
allow-list above. This restores columns, `Parameters`, `Location` and
`TableType`, and an Iceberg table becomes readable again. It depends on the
version still being in history, so it is a repair, not a substitute for the
snapshot.

### Iceberg: the two write paths conflict, and order matters

Measured on a live Iceberg table. This is the trap that no amount of general
reasoning gets right, because both halves look safe on their own.

| Statement | Result |
|---|---|
| `ALTER TABLE db.t CHANGE COLUMN c c <type> COMMENT '...'` (Athena) | **works.** Preserves all `Parameters` including a custom key, advances `metadata_location` correctly, keeps `TableType`, `Location` and every column |
| the same statement's side effect | **wipes `Table.Description` to null**, and **wipes every column comment not already in the Iceberg schema** |
| `ALTER TABLE ... ALTER COLUMN c COMMENT '...'` | rejected by the parser |
| `COMMENT ON TABLE` / `COMMENT ON COLUMN` | rejected by the parser |
| `ALTER TABLE ... SET TBLPROPERTIES ('comment'='...')` | fails: `Unsupported table property key: comment`. It is not a route to the table description |
| column comments written by `update-table` | land in the Glue mirror, and Athena `DESCRIBE` does **not** show them |

The mechanism: `update-table` writes only the Glue catalog's mirror of the
schema, while an Iceberg DDL commit re-derives that mirror from Iceberg's own
schema. So the two do not compose, and a comment written one way is erased by
the next write of the other kind.

So for an **Iceberg** table where the column comments must be visible to Athena
and Spark:

1. Set **every** column comment through Athena DDL, one `CHANGE COLUMN`
   statement per column, in one batch. Repeat the column's exact current name
   and type and change only the `COMMENT`, because the statement redefines the column.
   A comment you do not restate is lost.
2. **Then** write `Table.Description` with the allow-list `update-table` above.
   Doing it in the other order loses the description to step 1.
3. Verify with both `aws glue get-table` and an Athena `DESCRIBE`, because they
   read different stores.

If the column comments only need to be visible in the Glue catalog and console,
the allow-list `update-table` alone is enough and no DDL is needed. Say which
audience you optimised for.

### Columns on the Glue asset layer

`amazon::BasicAttribute` is reserved and `put-attachment` with it is refused.
The asset layer's column `Description` mirrors the Glue column `Comment`
read-only. So there is no safe asset-layer route to a column description: the
paths above are the only ones. Custom forms **can** attach to a column, which is
`references/metadata-forms.md`.
