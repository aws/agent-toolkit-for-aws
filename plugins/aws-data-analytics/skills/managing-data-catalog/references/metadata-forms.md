# Custom metadata forms

Thin by design: defining a form is mostly straightforward on both platforms.
Two things go wrong: a form type created and applied to nothing, and two Glue
naming rules that are not guessable.

## Finish the job

A form **type** is a schema. Creating one changes no asset. The task is not done
until the form is applied to the target with values in it, and read back.

- You MUST apply the form after creating the type, in the same task.
- You MUST read the applied form back and print the values it holds.
- If the request named no field names or type name, choose sensible ones and say
  what you chose rather than asking.

## Glue Data Catalog: two rules that will refuse your first two attempts

> **Check availability first.** Before using the Glue business-context operations
> in this section (glossaries, terms, custom form types, catalog assets and
> attachments), check their availability and any stated limitations in the
> [AWS Glue documentation](https://docs.aws.amazon.com/glue/latest/dg/), and pass
> any caveat it gives on to the user. The table-layer operations (`Description`,
> column `Comment` and `Parameters` via `update-table`) are not part of that surface.

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```

1. **`Name` must match `^[A-Z]\w*$`.** It must start with a capital and may
   contain only word characters. `data-classification` and
   `data_classification` are both refused, the first for the hyphen, the second
   for the lower-case start. Use `DataClassification`. This is a trap because
   kebab-case is the convention for every other identifier on this surface.
2. **The Smithy `namespace` inside the schema must be exactly
   `glue_<ACCOUNT_ID>`.** Any other value is refused with `Namespace X does not
   match request glue_Y`. Resolve the account id at runtime as above and
   interpolate it. Never write a literal account id into a schema, a script or
   an example.

```bash
cat > /tmp/form-type.smithy <<EOF
namespace glue_${ACCOUNT_ID}

structure DataClassification {
    @documentation("One of: public, internal, confidential, restricted")
    classification: String

    @documentation("Retention period, e.g. 7 years")
    retentionPeriod: String
}
EOF

aws glue put-form-type --region <region> --name DataClassification \
  --schema "$(cat /tmp/form-type.smithy)"
```

Apply it to a table, and to a column:

```bash
TABLE_ARN="arn:aws:glue:<region>:${ACCOUNT_ID}:table/<db>/<table>"

# on the table
aws glue put-attachment --region <region> --asset-identifier "$TABLE_ARN" \
  --attachment-name governance --form-type-id DataClassification \
  --content '{"classification":"restricted","retentionPeriod":"7 years"}'

# on one column
aws glue put-attachment --region <region> --asset-identifier "$TABLE_ARN" \
  --iterable-form-name columns --item-identifier "${TABLE_ARN}#<column>" \
  --attachment-name governance --form-type-id DataClassification \
  --content '{"classification":"restricted","retentionPeriod":"7 years"}'
```

### Read it back on the right surface

Three read surfaces, and two of them cannot see an attachment:

| To see | Call |
|---|---|
| a **table's** attachments | `glue get-asset --identifier <table-arn>` |
| a **column's** attachments | `glue batch-get-iterable-forms --asset-identifier <table-arn> --iterable-form-name columns --item-identifiers <col-id>` |
| nothing useful for this purpose | `glue list-iterable-forms`, which returns the columns **without** their attachments |

So verifying column-level work with `list-iterable-forms` shows nothing and
reads as a failed write. Use `batch-get-iterable-forms`.

### Attachments replace within a name, and are isolated across names

`PutAttachment` replaces the whole content of the attachment name you address.
It does **not** touch other attachment names: writing a `governance` attachment
leaves `relatedTo` alone, and vice versa. That boundary is exact and worth
keeping exact: the destructive case is `relatedTo`, in
`references/skill-assets.md`.

`amazon::BasicAttribute` is reserved; `put-attachment` with it is refused
outright.

Parameter naming is inconsistent across these four calls. See
`references/troubleshooting.md` before assuming a `ParamValidation` means the
operation is wrong.

## SageMaker Catalog: three rules that will refuse your first attempts

Same shape of trap as Glue's, different rules, and the error messages name things
you did not write. All three are measured.

1. **The `structure` in the model MUST have the same name as `--name`.** A
   mismatch is refused with an error that names a shape you never wrote:
   `target shape <domain_id>#<--name> not found` followed by
   `inner shape <domain_id>.<--name>#<structure name> is of illegal type structure`.
   Nothing in that message says "your two names differ", so it reads as the model
   being malformed.
2. **Do not write a `namespace` line.** The service supplies one, and it must be
   the domain id with hyphens as underscores. Any other value is refused with
   `Namespace <yours> does not match request <domain_id_with_underscores>`. A model
   that is a bare `structure` with no `$version` and no `namespace` is accepted, so
   omitting both is the reliable choice, and do not resolve the domain id into a
   namespace to work around a rule you can avoid.
3. **`--name` may not contain a hyphen**, and may not start with a digit or an
   underscore: the constraint is `(amazon.datazone.)?(?![0-9_])\w+$|^_\w*[a-zA-Z0-9]\w*`.
   `data-classification` is refused. Use `DataClassification`, matching the
   structure per rule 1.

```bash
DOMAIN=<domain-id>; PROJECT=<project-id>; NAME=DataClassification

# --model is a STRUCTURE inside a JSON wrapper, so build it as JSON rather than
# with the CLI's `smithy=...` shorthand: any @documentation trait contains double
# quotes, and the shorthand parser fails on the first one with
# `ParamValidation: Expected: ',', received: '"'`.
cat > /tmp/form-model.json <<EOF
{"smithy": "structure ${NAME} {\n    @documentation(\"One of: public, internal, confidential, restricted\")\n    classification: String\n\n    @documentation(\"Retention period, e.g. 7 years\")\n    retentionPeriod: String\n}\n"}
EOF

aws datazone create-form-type --domain-identifier "$DOMAIN" --name "$NAME" \
  --owning-project-identifier "$PROJECT" --model file:///tmp/form-model.json \
  --status ENABLED
# -> {"domainId": "...", "name": "DataClassification", "revision": "1"}
```

Keep the `revision` it returns: applying the form needs it. `@amazon.datazone#searchable`
and `@required` are both accepted on a field, and declaring a field searchable is
how you make it findable, not writing the value into a description as well.

There is **no `UpdateFormType`**. The only three operations are `CreateFormType`,
`GetFormType` and `DeleteFormType`, so changing a type means calling `CreateFormType`
again with the same name and the whole model, which returns a new revision. Read the
current model back first rather than retyping it, for the same reason every other
write in this skill snapshots.

### Applying it, which is where the full-record replace bites

The form is applied by including it in the asset's `formsInput`, so it goes through
`CreateAssetRevision` and therefore through the replace. Use the canonical
read-modify-write in `references/describing-assets.md` and **add** an entry rather
than sending one: applying a governance form the naive way is one of the operations
measured dropping `sourceIdentifier` and unbinding the asset from its table.

A new form's entry needs three fields the existing forms already carry, which is the
only part the canonical block does not do for you:

```json
{"formName": "DataClassification",
 "typeIdentifier": "DataClassification",
 "typeRevision": "1",
 "content": "{\"classification\":\"restricted\",\"retentionPeriod\":\"7 years\"}"}
```

`formName` and `typeIdentifier` are both the form type's name, and `typeRevision` is
the revision `CreateFormType` returned. Every other form in `formsOutput` goes back
unchanged beside it, `content` included.

Content is a JSON **string** inside the form. Serialise it once. Passing an
already-serialised string through a second `json.dumps` produces a form whose
content is a quoted blob that no consumer can read, and the call succeeds.

Then read the asset back and print the applied form's values: a type created and
applied to nothing is the failure this chapter opens with.
