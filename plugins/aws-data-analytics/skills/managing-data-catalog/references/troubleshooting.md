# Troubleshooting

Errors whose message names the wrong fix, and results that look like an absent
capability. Every row is one that cost real time.

## The error names the wrong thing

| Symptom | Actual cause | Fix |
|---|---|---|
| `ParamValidation: Unknown parameter --form-type-id` on `glue get-form-type` | Three names for one concept across four calls: `list-form-types` returns `Id`, `get-form-type` takes `--identifier`, `put-attachment` takes `--form-type-id`, `put-asset` takes `--asset-type-id` plus a `Forms` map keyed by form name whose value carries `FormTypeId` | Use the name that call takes. The message suggests the operation is wrong; it is the flag |
| A wall of validation errors from `glue update-table` naming `DatabaseName`, `CreateTime`, `CreatedBy`, `CatalogId`... | You fed `get-table` output back in. Stripping the named fields reveals `IsMaterializedView` one error later | Build `TableInput` from the fourteen-key **allow-list** in `references/describing-assets.md`, not a deny-list |
| `Namespace X does not match request glue_Y` on `glue put-form-type` | The Smithy namespace must be exactly `glue_<ACCOUNT_ID>` | Resolve the account id at runtime and interpolate it |
| `put-form-type` refuses your type name | `Name` must match `^[A-Z]\w*$`: no hyphen, must start with a capital | `DataClassification`, not `data-classification` |
| `target shape <domain_id>#<name> not found`, then `inner shape <domain_id>.<name>#<other> is of illegal type structure`, on `datazone create-form-type` | The `structure` in the model has a different name from `--name`. The message names a shape you never wrote, so it reads as a malformed model | Make the two names the same string |
| `Namespace X does not match request <domain_id_with_underscores>` on `datazone create-form-type` | A `namespace` line in the model. The service's own is the domain id with hyphens as underscores | Write the model as a bare `structure` with no `$version` and no `namespace` |
| `ParamValidation: Expected: ',', received: '"'` from `--model smithy=...` | The CLI's shorthand parser stops at the first double quote, which any `@documentation` trait contains | Pass the model as JSON: `--model file:///tmp/form-model.json` holding `{"smithy": "..."}` |
| `Invalid length for parameter glossaryTerms, value: 0, valid min length: 1` | You passed `[]` to clear an asset's terms | **Omit** the parameter |
| `AccessDeniedException: Failed to validate IAM role` on `datazone get-user-profile` | A role cannot resolve its own profile that way | `datazone search-user-profiles --user-type DATAZONE_IAM_USER --search-text <role name>` |
| `ResourceNotFoundException` on a form type you can see on an asset | The form **type** is `...FormType`; the form **name** on the asset is `...Form` | Query the type by its type id |
| `ConflictException: deletion prevented by containedSubscriptionGrant ...` on `delete-listing` | A grant has not finished being torn down | Wait, per `references/publication-lifecycle.md`. The message names every blocker; clear those, do not retry |
| `EntityNotFoundException` from `glue update-asset` seconds after `create-table` | The catalog's asset projection lags table creation by a few seconds | Retry. It does not mean the table has no asset |
| `Unsupported table property key: comment` from Athena | `SET TBLPROPERTIES ('comment'=...)` is not a route to a table description | Use `glue update-table` with the allow-list |
| `mismatched input 'ALTER'` / `mismatched input 'COMMENT'` from Athena | `ALTER COLUMN ... COMMENT`, `COMMENT ON TABLE` and `COMMENT ON COLUMN` are not in this dialect | `ALTER TABLE t CHANGE COLUMN c c <type> COMMENT '...'` |

## An empty result that is not an absence

| You called | It returned | The truth |
|---|---|---|
| `glue list-asset-types` | `[]` | Built-in asset types are not listed. Only custom ones appear |
| `glue search-assets` filtered on `amazon::Skill` | `[]` | The stored value is `Skill` |
| `datazone list-projects --user-identifier <role ARN>` | `[]` | Pass the **profile id**, not the ARN |
| `glue list-iterable-forms` after attaching a form to a column | the columns, with no attachments | It never shows attachments. Use `batch-get-iterable-forms` |
| `glue get-asset` on a skill you just attached | `Attachments: {}` | The relation is readable from the **table** side only |
| a data source run | `SUCCESS, 0 added, 0 unchanged` on a database with tables | Table-level grants are missing. The run saw an empty database, not a permissions error |
| `glue list-iterable-forms` on a table whose write you suspect broke it | every column, with comments | A separate store. Verify with `glue get-table` |

## Content that wrote successfully and is unreadable

- **Double-encoded form content.** A form's `Content` is a JSON **string**. If
  you serialise an already-serialised string, the write succeeds and the value is
  a quoted blob no consumer can parse. Serialise once; parse on read.
- **A description written to the wrong surface.** On the SageMaker Catalog, a
  description written to the Glue table documents the table, and the asset does not
  carry it until the next crawl. On Glue, `update-asset` writes a description no
  query engine sees. Both are silent. State which surface you wrote to.

## Before diagnosing a permission

Confident, wrong permission diagnoses were a recurring failure: an invented
`BatchPutAttributesMetadata` for a field that is written by an operation the
agent had already used, an invented Lake Formation denial for a name it could
have read from the run activities. Before blaming a permission:

1. Name the exact call that was denied and quote the error.
2. Check that call is the one the task needs. Often it is not.
3. **Check which identity made it, on the surface that failed.** See below; this
   is the step that gets skipped, and skipping it is how a denial gets reported as
   an IAM gap that does not exist.
4. If the second probe in `references/platform-detection.md` succeeded, the
   answer is a platform difference, not a permission.

### Your tool surfaces may not be the same principal

You may have more than one way to reach AWS: an MCP server tool, and a shell in
which you run the `aws` CLI. **They authenticate separately, and nothing tells you
when they resolve different credentials.** A shell usually resolves the ambient
credential chain, which can be a different role, or a different account, from the
one an MCP tool is signed with. Measured: `GetAsset` and `CreateFormType` refused
with `UnauthorizedException` through a shell while both succeeded through an MCP
tool in the same session, seconds apart, with identical arguments.

So when a call is refused:

- Run `aws sts get-caller-identity` **on the same surface as the failing call**, not
  on whichever one is convenient, and compare the account and the role with the
  target. One command, and it distinguishes "I am not allowed" from "I am somewhere
  else".
- If another surface has been working, retry the failing call there before
  concluding anything. A capability that works through either surface is not a
  permission problem.
- Report the surface and the identity beside the error. "`CreateFormType` was
  refused for `<role>` in `<account>`, and the same call succeeds through the MCP
  tool as `<other role>`" is a fact the user can act on; "the role lacks
  `datazone:CreateFormType`" may be false and sends them to change a policy that is
  already correct.

The failure mode this prevents is worse than a wrong diagnosis. `UnauthorizedException`
on a **DataZone** call is what a caller outside the domain gets, so an identity in
the wrong account produces exactly the error an under-privileged one does. And a
read whose failure you discard (`2>/dev/null || echo 0`) comes back as an empty
result from the wrong account and reads as "nothing there".
