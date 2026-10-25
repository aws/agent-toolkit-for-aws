# Measuring documentation coverage

**SageMaker Catalog.** On the Glue Data Catalog the same question is easy.
`Table.Description` and `StorageDescriptor.Columns[].Comment` are the two fields,
`glue get-tables` returns both, and there is nothing to explain. This chapter is
about the SageMaker Catalog's form model, where the same question is routinely
answered wrong in a specific way.

Scope note: reporting coverage **inside a project so it can be fixed** is this
skill. Counting gaps domain-wide by SQL over the exported metadata snapshot
belongs to `querying-aws-sagemaker-catalog`.

## The distinction that gets missed

A crawled asset can carry a description that no steward ever wrote. The data
source run **inherits** the source table's description into the *technical* form,
not into the asset's business metadata:

| Kind | Where it lives | Written by |
|---|---|---|
| authored business metadata | `asset.description`, `AssetCommonDetailsForm.summary` / `.readMe`, `ColumnBusinessMetadataForm`, `glossaryTerms` | a steward, or an accepted AI prediction |
| inherited technical description | `GlueTableForm.tableDescription`, `GlueTableForm.columns[].columnDescription` | the crawl, from the source table |

The three groups below are about **descriptions**: an asset is `AUTHORED` when it has
`asset.description`, `AssetCommonDetailsForm.summary` or `AssetCommonDetailsForm.readMe`.
Glossary terms and column business metadata are authored too, but they don't place an
asset in a group. The block prints the term count beside each asset (`terms=`), and
column business metadata is read separately.

An agent that reads only `asset.description` reports every asset as
undocumented. An agent that reads the forms and does not draw the distinction
reports the inherited ones as **documented**, which is the more damaging error:
the user closes the ticket and no steward ever writes the business meaning.

Both halves are the whole answer. You MUST report three groups, not two:

1. assets with **authored** business metadata,
2. assets with an **inherited technical** description and no authored metadata.
   These are the promotion candidates, and they are the cheapest work available,
3. assets with **nothing** anywhere.

And the answer MUST also carry two things beyond the three counts, because a
group total hides the work:

- **The column-level split, per asset in group 2.** An inherited table
  description with a description on every column is nearly finished; one with no
  column descriptions is not. Report it as `n of m columns`.
- **Where you read each value from**, by name: `asset.description`,
  `AssetCommonDetailsForm.summary` and `.readMe` for authored metadata,
  `GlueTableForm.tableDescription` and `GlueTableForm.columns[].columnDescription`
  for the inherited kind. Naming the field is what lets the user check you, and
  it is the distinction the whole answer turns on.

## How to read it

```bash
DOMAIN=<domain>; PROJECT=<project>

aws datazone search --domain-identifier "$DOMAIN" --owning-project-identifier "$PROJECT" \
  --search-scope ASSET --query 'items[].assetItem.{id:identifier,name:name}' --output text \
| while read -r id name; do
  aws datazone get-asset --domain-identifier "$DOMAIN" --identifier "$id" > /tmp/a.json
  jq -r --arg n "$name" '
    ( .description // "" ) as $d
    | ( [.formsOutput[]|select(.formName=="AssetCommonDetailsForm")
         |.content // "{}" |fromjson] | first // {} ) as $c
    | ( [.formsOutput[]|select(.formName=="GlueTableForm")
         |.content // "{}" |fromjson] | first // {} ) as $g
    | [ $n,
        ( if ($d|length)>0 or (($c.summary//"")|length)>0 or (($c.readMe//"")|length)>0
          then "AUTHORED" elif (($g.tableDescription//"")|length)>0
          then "INHERITED-only" else "NONE" end ),
        "cols_with_inherited=\([$g.columns//[]|.[]|select((.columnDescription//"")|length>0)]|length)/\(($g.columns//[])|length)",
        "terms=\((.glossaryTerms//[])|length)" ] | @tsv' /tmp/a.json
done
```

For a project of any size, generate this as one script and run it once rather
than issuing a call per asset conversationally.

## Ownership

There may be no owner field to report on. Before saying an asset is "missing an
owner", check whether any form in the project holds ownership at all. If none
does, the honest answer is that ownership is not recorded anywhere and capturing
it needs a custom metadata form or a glossary convention first; see
`references/metadata-forms.md`. Reporting fifteen assets as "missing an owner"
implies an empty field waiting to be filled, and there is none.

## What to recommend

Rank the fix by cost, not by count:

1. The **inherited-only** group is nearly free: the source already carries a
   description worth promoting. Promote it into the business metadata, reviewed
   rather than copied, because a technical description written for engineers is often
   not the business meaning.
2. The **nothing** group needs real authoring. If it is large, offer the
   generation path in `references/generating-metadata.md`, which is both cheaper
   and safer than hand-authoring at volume.
3. Terms and forms after descriptions. A classified asset with no description is
   less useful than a described one with no term.
