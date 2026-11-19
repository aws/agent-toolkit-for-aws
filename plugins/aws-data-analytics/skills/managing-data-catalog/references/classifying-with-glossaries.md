# Classifying with business glossaries and terms

The calls are simple. Both platforms fail here for reasons that are not about
the calls: on Glue, not believing the capability exists; on both, creating a
second term instead of finding the one that is already there.

## Glue Data Catalog: the capability exists

> **Check availability first.** Before using the Glue business-context operations
> in this section (glossaries, terms, custom form types, catalog assets and
> attachments), check their availability and any stated limitations in the
> [AWS Glue documentation](https://docs.aws.amazon.com/glue/latest/dg/), and pass
> any caveat it gives on to the user. The table-layer operations (`Description`,
> column `Comment` and `Parameters` via `update-table`) are not part of that surface.

**The AWS Glue Data Catalog has native business glossaries and glossary terms.**
`glue create-glossary`, `glue create-glossary-term` and
`glue associate-glossary-terms` are Glue operations.

They are not Amazon DataZone's glossaries, they are not Lake Formation LF-Tags,
and they do not need a SageMaker Catalog domain. You MUST NOT tell a user that
"there is no Glue API to create a glossary". The statement is false, and it was
the single most common wrong answer measured on this task.

`CreateGlossary` takes **no catalog scoping**. There is no `--catalog-id` to
find, so an agent looking for the scoped create will not find one and should not
conclude the operation is absent.

```bash
aws glue create-glossary --region <region> --name "<Glossary Name>" \
  --description "<what this glossary covers>"
# -> {"Id": "<opaque generated id>"}

aws glue create-glossary-term --region <region> \
  --glossary-identifier <glossary-id> --name "<Term Name>" \
  --short-description "<one sentence: what it means and how it is scoped>"
```

## Resolve an existing term by NAME before creating one

Glossaries and terms get **opaque generated ids** (`bjaif1ziwej5bb`), so a name
is never usable as an identifier and a name-to-id lookup is mandatory. This is
where the task fails most often: asked to apply *the* term a user named, agents
create a new glossary with a new term of that name in it and associate that,
leaving two terms of the same name and the intended one still attached to
nothing. The end state looks correct in the answer and is wrong in the catalog.

- You MUST search for the named term first, and use its id.
- You MUST create a term only when the search found none, and say that you did.

```bash
# Glue: find the term the user named, across every glossary.
# The name is matched in jq, never pasted into a --query: a quote in it ("Customer's
# ID") would end the JMESPath string early and the search would error or match the
# wrong term. Not called TERM, which is the shell's terminal type.
TERM_NAME='<the term name the user used>'
for g in $(aws glue list-glossaries --region <region> --query 'Items[].Id' --output text); do
  aws glue list-glossary-terms --region <region> --glossary-identifier "$g" --output json \
    | jq -r --arg name "$TERM_NAME" --arg g "$g" \
        '.Items[] | select(.Name == $name) | [$g, .Id, .Name] | @tsv'
done
```

It prints one `glossary<TAB>term-id<TAB>name` line per match. Nothing printed means no
glossary has the term.

**If `list-glossaries` is denied, do not fall back to creating one.** A policy
allowing `glue:*Glossary*` does **not** cover `glue:ListGlossaries`, because the plural
has no `Glossary` substring, so enumerating can be refused on a caller that can
happily create, list terms and associate. In that case:

1. Try `aws glue list-glossary-terms --glossary-identifier <name-or-id>` if the
   user named the glossary; the identifier accepts what you were given.
2. Otherwise ask the user for the glossary name or id, and say that
   `glue:ListGlossaries` is what you were denied.

Creating a second term to work around a read denial is the worst available
outcome: the association succeeds, the answer looks right, and the term the user
meant is still attached to nothing.

On the SageMaker Catalog the same rule applies through search:

```bash
aws datazone search --domain-identifier <domain> --search-scope GLOSSARY_TERM \
  --search-text "<term name>" --query 'items[].glossaryTermItem.{Id:id,Name:name}'
```

## Associating terms

### Glue: additive, and there is no merge hazard here

`AssociateGlossaryTerms` is **additive**: associating a second term leaves the
first in place. This is the opposite of the SageMaker Catalog, and it is worth
knowing precisely so you neither warn about a hazard that does not exist nor
assume merging is safe elsewhere in this skill. `DisassociateGlossaryTerms`
removes one, with the same two flags.

```bash
aws glue associate-glossary-terms --region <region> \
  --asset-identifier "arn:aws:glue:<region>:<ACCOUNT_ID>:table/<db>/<table>" \
  --glossary-term-identifiers <term-id>
```

Resolve `<ACCOUNT_ID>` at runtime with `aws sts get-caller-identity --query
Account --output text`. Never hardcode it.

### SageMaker Catalog: the terms ride on a full asset revision

Term associations live in the top-level `glossaryTerms` list on the asset, which
`CreateAssetRevision` **replaces**. So associating one term the naive way clears
every other term the asset had. Use the canonical read-modify-write in
`references/describing-assets.md`, which reads the existing list and sends it
back with the addition. Note that the same revision drops any form you
omit, so tagging an asset can silently unbind it from its table.

To remove the asset's only term, **omit** the `glossaryTerms` parameter. Passing
an empty list is refused client-side: the parameter has a minimum length of one.

## Choosing which assets a term applies to

When the request describes the assets by meaning ("every table that reports
revenue") rather than by name, read the schema and the column comments. Do not
match on table names. Both directions matter: a table whose **name** says nothing
about the concept can still carry a measure column that does, and a table whose
name suggests the concept can turn out to measure a neighbouring one: spend,
cost, margin and billings are not revenue. Judge on the measure columns and their
comments, not the table name.

- You MUST list the candidates with the evidence for each, and name the ones you
  excluded and why.
- Then **associate the clear ones**. Association is additive and reversible, so
  it does not warrant blocking on a confirmation. Report the borderline cases
  with your reasoning and offer to add or remove them.
- Do the associations as one generated script over the list, not one
  conversational call per table.

## Designing a taxonomy

When asked to create a glossary for a domain rather than a named list of terms:
one glossary per business domain, terms named as the business says them, and a
one-sentence definition on every term that says how the metric is computed or
scoped. A term with no definition is a tag, not a glossary term.
