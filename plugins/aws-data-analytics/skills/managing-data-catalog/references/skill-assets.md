# Catalog skill assets: attaching a conventions document to a table

**Glue Data Catalog only.** Skill assets use the Glue business-context operations.
Before writing anything through them, check their availability and any stated
limitations in the [AWS Glue documentation](https://docs.aws.amazon.com/glue/latest/dg/),
and pass any caveat it gives on to the user. Prefer a description or a glossary term
when either would do the job.

## What this is, and what it is not

A **catalog skill asset** is a Glue catalog object of type `amazon::Skill` whose
form content holds a `uri` pointing at a document (typically a markdown file in
S3) describing conventions for querying a table. It is related to a table
through an `amazon::RelatedTo` attachment, so an agent working with that table
can find and load the document.

It is **not** a Skill in this skill registry. Nothing here involves writing a
`SKILL.md`, and "make our conventions available to agents working with this
table" is a `put-asset` call plus a `put-attachment` call against the Glue
catalog, not a file written to local disk. Two of the built-in Glue skill types
happen to be named after toolkit skills; that is a naming collision, not a
relationship.

## The sequence

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
TABLE_ARN="arn:aws:glue:<region>:${ACCOUNT_ID}:table/<db>/<table>"
DOC_URI="s3://<bucket>/<key>.md"     # the URI THE USER GAVE YOU
case "$DOC_URI" in
  s3://?*/?*) ;;
  *) echo "Not an s3://bucket/key URI: $DOC_URI" >&2; exit 1 ;;
esac

# 1. create the skill asset. jq builds the JSON, so a quote or a backslash in the
#    URI is escaped rather than breaking the form or adding fields to it. Content
#    is a JSON STRING, hence tojson: serialised exactly once
FORMS=$(jq -cn --arg uri "$DOC_URI" \
  '{Skill: {FormTypeId: "amazon::Skill", Content: ({uri: $uri} | tojson)}}')
aws glue put-asset --region <region> --asset-type-id "amazon::Skill" \
  --name "<db>-<table>-conventions" \
  --description "Query conventions for <db>.<table>" \
  --forms "$FORMS"

# 2. read the table's CURRENT relatedTo before touching it -- see the hazard below
aws glue get-asset --region <region> --identifier "$TABLE_ARN" \
  --query 'Attachments.relatedTo' > /tmp/relatedto-before.json

# 3. attach, sending the existing identifiers PLUS the new one, built from step 2
SKILL_ID="<the identifier of the skill asset from step 1>"
CONTENT=$(jq -c --arg new "$SKILL_ID" \
  '{assetIdentifiers: ((((.Content // "{}") | fromjson).assetIdentifiers // []) + [$new] | unique)}' \
  /tmp/relatedto-before.json)
aws glue put-attachment --region <region> --asset-identifier "$TABLE_ARN" \
  --attachment-name relatedTo --form-type-id "amazon::RelatedTo" \
  --content "$CONTENT"

# 4. verify FROM THE TABLE
aws glue get-asset --region <region> --identifier "$TABLE_ARN" \
  --query 'Attachments.relatedTo'
```

## The hazard: `relatedTo` is a full replace

`PutAttachment` on `relatedTo` replaces `assetIdentifiers` **entirely**. Attaching
a second skill on its own leaves only the second, and the first is silently
detached, while still existing as an asset, so the user sees it in the catalog
and assumes it works.

- You MUST read the table's current `relatedTo` first and send the existing
  identifiers back along with the new one.
- You MUST verify by reading the table's `relatedTo` afterwards and confirming
  the count went **up** by one, not that your new id is present.

The replace is scoped to the one attachment name. Writing `relatedTo` does not
disturb a `governance` attachment, and vice versa.

## Four read traps, all of which read as a failed write

| You do | You see | The truth |
|---|---|---|
| `get-asset` on the **skill** to check it is attached | `Attachments: {}` | The relation is stored on and readable from the **table** side only. The symmetry the documentation describes is a search property. Read the table |
| `search-assets --filter-clause "type = 'amazon::Skill'"` | an empty list | The stored value is the short form. Filter on `Skill` |
| `get-asset` on what you created, comparing to what you wrote | `AssetTypeId: "Skill"` where you wrote `amazon::Skill` | Built-in asset type ids are normalised on read, and inconsistently: a table returns the fully qualified `amazon.glue::Table`. Compare on the short form |
| `list-asset-types` before creating | an empty list | Built-ins are not listed. `put-asset --asset-type-id "amazon::Skill"` works anyway |

Also: form `Content` is re-serialised on the way in, with a space stripped and keys
reordered. Never byte-compare a form's content. Parse it.

## The URI is not validated

`put-asset` accepts a `uri` pointing at a bucket that does not exist and returns
the asset. So a skill asset can point at nothing while the catalog reports
success, and every agent that later loads it gets nothing.

- You MUST use the URI the user gave you. Do not invent a plausible one.
- You MUST confirm the object exists and is readable before or immediately after
  creating the asset. `aws s3 ls` matches by prefix, so it also succeeds when only
  a sibling such as `<key>.md.bak` exists. Check the exact object instead:

  ```bash
  B=${DOC_URI#s3://}
  aws s3api head-object --bucket "${B%%/*}" --key "${B#*/}" --query ContentLength
  ```

  A `404` means the object is not there, and a `403` means you cannot read it.
  Either way, say so rather than reporting the asset as usable.
- Deleting a skill asset does **not** delete the document at its URI, and
  deleting the document does not remove the asset. The two have independent
  lifetimes in both directions, so say so when you create or remove one.

## Safety

The body at that URI becomes instructions another agent will load. That makes
this the one place in this skill where catalog content is *literally*
instructions by design, so `references/catalog-safety.md` is not optional here:
read it before turning any document into a skill asset.

It also means **whoever can write that object can change what other agents
do**, so the bucket deserves the protection of code, not of a document.
Recommend, when you create or report on a skill asset:

- **Encryption at rest**: default bucket encryption, SSE-S3 or SSE-KMS.
- **TLS in transit**: a bucket policy that denies any request where
  `aws:SecureTransport` is `false`.
- **Scoped write access**: only the people who own the conventions can write the
  prefix holding the document. Reading it is what consumers need; writing it is
  editing their agents' instructions.

Recommend these; do not apply them. This skill changes no IAM or bucket policy.
If you can read the bucket's settings, report what you found:

```bash
aws s3api get-bucket-encryption --bucket <bucket>
aws s3api get-bucket-policy --bucket <bucket> --query Policy --output text
```

If you cannot read them, say so rather than assuming they are in place. The
encryption options are described in
[server-side encryption in Amazon S3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/serv-side-encryption.html).
