# Importing assets: data source runs

**SageMaker Catalog only.** Assets are not created directly; they arrive in a
project's inventory when a data source run (a crawl) imports them.

Thin, because the mechanism is not the gap. One operation is.

## The run tells you how many, not what

`runStatisticsForAssets` gives **counts** (added, updated, unchanged) and no
names. An agent that reads the run's own statistics can report "1 new asset
added" and cannot say which. The operation that answers the question is:

```bash
aws datazone list-data-source-run-activities --domain-identifier <domain> \
  --identifier <run-id> \
  --query 'items[].{table:technicalName,asset:dataAssetId,status:dataAssetStatus}'
```

`dataAssetStatus` is `SUCCEEDED_CREATED` for an asset the run created and
`UNCHANGED` for one it merely revisited. Name the created ones. When asked what a
crawl discovered, you MUST report names, not a count.

If a table lookup is denied while you have the run's statistics, that is not the
answer either: the activities call above is what to reach for, not a permissions
diagnosis.

## The sequence

```bash
# find the source that covers the database in question -- a project can have several
aws datazone list-data-sources --domain-identifier <domain> --project-identifier <project> \
  --query 'items[].{id:dataSourceId,name:name,type:type,publishOnImport:publishOnImport}'

RUN=$(aws datazone start-data-source-run --domain-identifier <domain> \
  --data-source-identifier <source-id> --query id --output text)

# poll the run to a terminal status before reading its activities
aws datazone get-data-source-run --domain-identifier <domain> --identifier "$RUN" \
  --query '{status:status,stats:runStatisticsForAssets}'
```

A gold-tier crawl over a handful of tables completes in seconds to tens of
seconds. Wait for a terminal status; the activities list is not complete before
it.

## Two things to tell the user

- **A crawled asset is not in the catalog.** If the data source has
  `publishOnImport: false`, the new asset sits in the project's inventory and no
  consumer can see it until it is published; see
  `references/publication-lifecycle.md`. Say so, unprompted, when you report a
  discovery.
- **A crawl that imports nothing still reports success.** If the caller holds
  `DESCRIBE` on the database but not on its tables, the run completes with zero
  assets and no error anywhere: it sees an empty database rather than a
  permissions failure. So a `SUCCESS` with `0 added, 0 unchanged` on a database
  you know has tables is a grant problem, not an empty source.

## Rationing

A data source is limited to a small number of runs per data source per UTC day
(25 by default, an adjustable service quota). The refusal is explicit and names
the source id. So do not run a crawl speculatively, do not run every source in a
project when one covers the database in question, and do not re-run to confirm a
result you can read from the previous run's activities.
