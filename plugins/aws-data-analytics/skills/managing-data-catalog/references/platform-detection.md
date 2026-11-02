# Platform detection: what exists here, and how to establish it

This is a **capability inventory**, not a preamble. The dominant failure in this
domain is not performing an operation badly. It is not believing the
capability exists.

Detection has **two steps and you are not finished after the first**:

1. **Which platform**, from the two probes below.
2. **Which scope you will work in, and what is actually in it**: the project on
   the SageMaker Catalog, the database or catalog on Glue. Resolve it and count
   what is there.

Step 2 is the one that gets skipped, and skipping it produces a technically
correct answer made of API names. "What can I do here" is answered by what is
actually in front of the user, not by the capability table: *one project, fifteen
assets, nine of them Glue tables and six Redshift, none carrying an authored
description* is orientation. A list of operations is a brochure.

## Step 1: the two probes, and what each answer means

```bash
aws datazone list-domains --region <region>
aws glue list-form-types --region <region> --max-results 5
```

| `list-domains` | `list-form-types` | Conclusion |
|---|---|---|
| returns one or more domains | either | **SageMaker Catalog.** Work at the asset layer inside a project |
| `AccessDeniedException` | succeeds, returns built-in form types | **Glue Data Catalog, metadata tier.** Glossaries, terms, custom form types, catalog assets and attachments are available |
| `AccessDeniedException` | `AccessDeniedException` or the operation is absent | **Glue Data Catalog, baseline tier.** Only table `Description`, column `Comment` and `Parameters` |
| returns an empty list | succeeds | Glue. But you have permission to look and there is genuinely no domain; say which of the two you observed |

**A denial is only evidence if the call named a region.** Every row above assumes
`--region` was supplied. A role may carry a region restriction, which an
`aws:RequestedRegion` condition makes common in an AWS Organization, and a call
that omits the region goes to whatever default the caller resolves rather than to
the region holding the catalog. A denial on an unqualified call therefore says
nothing about the platform: it can mean only "not in that region". So if you are
denied and you did not name a region, **add the region and probe again before
concluding anything**, and do not fall back to an unqualified retry. Only a
denial on a region-qualified call belongs in the table above.

If you do not know which region to use, ask, or take it from the resource the
user named. Guessing a region and reporting the denial as a platform answer is
the failure this rule exists to prevent.

**A denial is not an absence.** `AccessDenied` on `datazone:ListDomains` is
exactly what a Glue-only caller sees. It means *this principal cannot see a
domain*; it does not mean a domain exists and is merely blocked, and it does
not mean the account has no catalog. You MUST establish what **is** available
with a positive probe before advising, and you MUST NOT report a permissions
problem as the answer when the second probe succeeded.

Both probes are cheap and neither writes. Run both, every time, and state in
your answer which one you ran and what it returned. Note that both succeeding is
normal on a domain-backed account (the SageMaker Catalog sits over Glue), and
the first row of the table is the conclusion, not a reason to stop probing.

## Step 2: resolve the scope, and inventory it

Do this before recommending anything, and report it. It is two or three calls.

| Platform | Resolve | Then inventory |
|---|---|---|
| SageMaker Catalog | the caller's project, per "Resolving my project" below | `datazone search --search-scope ASSET --owning-project-identifier <project>`: how many assets, of which types, and how many carry an authored description |
| Glue, either tier | the database or catalog the user means, or list the databases and say which you chose | `glue get-tables --database-name <db>`: how many tables, and how many carry a `Description` and column `Comment`s |

Then answer with both halves: **what exists here**, in numbers, and **what you
can therefore do**, as the operations that apply to what you found. If the user's
request implies a next action, name the specific assets it would touch.

## Capability inventory

| Capability | SageMaker Catalog | Glue, metadata tier | Glue, baseline tier |
|---|---|---|---|
| Table / asset description | `CreateAssetRevision` | `UpdateAsset` (asset layer) or `UpdateTable` (table layer), two different stores | `UpdateTable` |
| README / summary | `AssetCommonDetailsForm` | none | none |
| Column documentation | `ColumnBusinessMetadataForm` | column `Comment` via `UpdateTable`; custom forms per column | column `Comment` |
| Business glossary and terms | `CreateGlossary`, `CreateGlossaryTerm`, `CreateAssetRevision` (`glossaryTerms` list) | `CreateGlossary`, `CreateGlossaryTerm`, `AssociateGlossaryTerms` | **none** |
| Custom metadata forms | `CreateFormType` (Smithy model) | `PutFormType` (`Schema` string), `PutAssetType` | **none** |
| Catalog skill assets (`amazon::Skill`) | **none** | `PutAsset`, `PutAttachment` | **none** |
| AI metadata generation | `StartMetadataGenerationRun` + accept / reject | **none** | **none** |
| Listings, publish / unpublish | `CreateListingChangeSet`, `GetListing`, `DeleteListing` | **none** | **none** |
| Data products | `CreateDataProduct` | **none** | **none** |
| Subscription workflow | request → approve → grant → revoke | **none** | **none** |
| Governance container | domains, projects, domain units | catalogs, databases | databases |

The asymmetry runs both ways. Glue lacks publishing, data products,
subscriptions and metadata generation. The SageMaker Catalog has no equivalent
of a Glue **skill asset** at all.

## Gate, do not improvise

When the request names a capability the detected platform does not have, the
answer has four parts, in this order. Keep the order: name the limitation (part 2)
before the alternative (part 3). A user who hears the alternative first assumes you
did what they asked.

1. **What you probed and what it answered.** Not "this is a Glue account":
   which call, and what it returned.
2. **What does not exist here**, named as a platform limitation rather than as a
   permissions problem or a failure on your part.
3. **The closest supported outcome**, concretely, with the operations that
   achieve it, and offer to do it.
4. **What that alternative still does not cover**, so the gap is explicit rather
   than papered over.

You MUST NOT substitute an adjacent mechanism and describe it in the requester's
words. A Lake Formation or IAM grant is **not** publishing: it changes who can
read the data, not whether anyone can discover it or ask for it. Where the missing
capability is discovery-related, part 3 is usually documentation (a description,
column comments and glossary terms so the table surfaces in `glue search-assets`),
and part 4 is that access remains a separately granted decision.

## Three lookups that answer "nothing" rather than "not for you"

Each of these returns an empty result on a working surface, which reads as an
absent capability. All three are measured, on Glue:

| You call | It answers | The truth |
|---|---|---|
| `glue list-asset-types` | an **empty list** | Built-in asset types are not listed. `put-asset --asset-type-id "amazon::Skill"` works anyway; only custom types appear here |
| `glue search-assets --filter-clause 'type = amazon::Skill'` | an **empty list** | The stored value is the short form, `Skill`. Filter on that |
| `datazone get-user-profile --user-identifier <role ARN>` | denied, or a not-found | Use `datazone search-user-profiles --user-type DATAZONE_IAM_USER --search-text <role name>` |

## Resolving "my project" on the SageMaker Catalog

Do not stop and ask the user which project. It is discoverable in three calls,
and the obvious shortcut fails silently:

```bash
aws sts get-caller-identity                                    # the role ARN
aws datazone search-user-profiles --domain-identifier <domain> \
  --user-type DATAZONE_IAM_USER --search-text <role name>      # -> profile id
aws datazone list-projects --domain-identifier <domain> \
  --user-identifier <profile id>                               # -> the caller's projects
```

Passing the **role ARN** straight to `list-projects` returns an empty list
rather than an error, which reads as "no projects". Pass the profile id.

If the caller belongs to exactly one project, use it and say which. If more
than one, and the task creates an object inside a project, ask, but only then,
and name the candidates you found.
