# AI-assisted metadata generation

**SageMaker Catalog only.** The Glue Data Catalog has no equivalent.

The gap here is pure discovery: the feature exists, and asked to "generate
metadata suggestions" most agents describe the feature and then write the
suggestions by hand. Hand-written suggestions are not the same thing: they live
in a chat log, not in the catalog, so nothing durable is there for a human to
review and accept later.

## The five operations

```bash
aws datazone start-metadata-generation-run --domain-identifier <domain> \
  --owning-project-identifier <project> --type BUSINESS_DESCRIPTIONS \
  --target '{"identifier":"<asset-id>","type":"ASSET","revision":"<revision>"}'

aws datazone get-metadata-generation-run  --domain-identifier <domain> --identifier <run-id>
aws datazone list-metadata-generation-runs --domain-identifier <domain>
aws datazone cancel-metadata-generation-run --domain-identifier <domain> --identifier <run-id>
aws datazone accept-predictions --domain-identifier <domain> --identifier <asset-id> \
  --revision <revision> --accept-rule '{"rule":"ALL"}'    # see the warning below
```

`--type` is one of `BUSINESS_DESCRIPTIONS`, `BUSINESS_NAMES` or
`BUSINESS_GLOSSARY_ASSOCIATIONS`. A run takes roughly thirty seconds per asset.

## Where the output goes, and why that is the point

A prediction lands in `SuggestionForm`
(`amazon.datazone.SuggestionFormType`), reported under **`readOnlyFormsOutput`**
and not under `formsOutput`. Its content is a `fieldSuggestions` list keyed by
`fieldPath`: `summary`, plus `columns[N].columnDescription` per column.

Nothing reaches `asset.description`, `AssetCommonDetailsForm.summary` or
`ColumnBusinessMetadataForm` until a prediction is accepted. That is what makes
the review durable: the suggestion is a state in the catalog that a human can
come back to, rather than text in a conversation.

Starting a run bumps the asset's revision, and the suggestion form cannot be
removed from an asset by any API. So a run is not free of consequence even
before anything is accepted, so do not run one on assets nobody asked about.

## Scope: resolve the target set FIRST, and print it

The second-commonest failure is finding the API and then running it over
everything. Every asset costs a run and gains an irreversible form. The failure
after that one is subtler and more common than it looks: the right mechanism,
run over the wrong set, because the set was a judgement the agent held rather
than a list it produced.

**So the target set is a required first artefact, not a decision you carry.**
Resolve it with a query, print it, and only then start any run. An agent that
starts the first run before printing the list is working from memory.

```bash
DOMAIN=<domain>; PROJECT=<project>

# One line per asset: its id, and which group it is in. Nothing is started yet.
aws datazone search --domain-identifier "$DOMAIN" --owning-project-identifier "$PROJECT" \
  --search-scope ASSET --query 'items[].assetItem.{id:identifier,name:name}' --output text \
| while read -r id name; do
  aws datazone get-asset --domain-identifier "$DOMAIN" --identifier "$id" > /tmp/a.json
  jq -r --arg n "$name" --arg i "$id" '
    ( .description // "" ) as $d
    | ( [.formsOutput[]|select(.formName=="AssetCommonDetailsForm")
         |.content // "{}" |fromjson] | first // {} ) as $c
    | ( [.formsOutput[]|select(.formName=="GlueTableForm")
         |.content // "{}" |fromjson] | first // {} ) as $g
    | [ $n, $i,
        ( if ($d|length)>0 or (($c.summary//"")|length)>0 or (($c.readMe//"")|length)>0
          then "AUTHORED" elif (($g.tableDescription//"")|length)>0
          then "INHERITED-only" else "NONE" end ) ] | @tsv' /tmp/a.json
done | tee /tmp/generation-targets.tsv
wc -l < /tmp/generation-targets.tsv     # the number of runs you are about to start
```

Then, before the first `start-metadata-generation-run`:

- You MUST apply the filter the user stated, **mapped onto those groups rather
  than onto a general impression**. "No description at all" is the `NONE` group.
  An asset carrying an inherited technical description is documented enough to
  fall outside that phrasing, and including it is over-reach; say which group you
  read the request as naming, and which field you read to decide.
  `references/measuring-coverage.md` is the full treatment of that distinction.
- You MUST print the list and its count, with the group beside each asset, and
  then **start the runs**. Asking permission to generate is not the review
  checkpoint. The review is the accept, below, and a request to generate
  suggestions has already authorised generating them. Ask first only if you would
  generate for assets outside what was asked.
- The count you printed is the number of runs you start. If you start a different
  number, say which assets you added or dropped and why, in the same message. A
  set that shrinks silently reads as a completed request; a set that grows
  silently writes an irreversible form onto an asset nobody asked about.
- **Report the set again at the end**, beside what each run produced. "Suggestions
  generated for 6 of the 6 assets with no description; the 3 carrying an inherited
  description were left alone" is an answer a user can check. "Suggestions
  generated" is not.

## Review and accept

- You MUST surface the predictions for the user to read and MUST NOT accept them
  in the same turn unless the user has already said to. **This** is the
  checkpoint: generating is reversible enough to just do, accepting writes to the
  asset and is what a human has to decide.
- You MUST NOT use `--accept-rule '{"rule":"ALL"}'` unattended. It is one call
  and it applies everything, including a generated summary of several thousand
  characters, across every column.
- Print each suggestion beside the field it would write, then accept what the
  user approves.

`RejectPredictions` is not a cleanup. It leaves the suggestion form in place, it
does not undo an accept that already happened, and it **writes** a stub
`ColumnBusinessMetadataForm` carrying a bare `columnIdentifier` per column. Do
not call it to tidy up; it adds debris. Naming a `fieldPath` as a
`predictionTarget` is refused outright.

## The one place the merge rule inverts

`AcceptPredictions` performs the merge **correctly**. It wrote a generated
summary into `AssetCommonDetailsForm.summary` and a description onto every column
while preserving `sourceIdentifier`: the service does the read-then-write that
hand-authoring gets wrong.

So for bulk description work the generation path is *safer* than hand-authoring
through `CreateAssetRevision`, which is the reverse of what the merge rule in
`SKILL.md` would lead you to assume. This is a property of this one operation.
It is not evidence that the platform merges in general: every other write path
in this skill still replaces.
