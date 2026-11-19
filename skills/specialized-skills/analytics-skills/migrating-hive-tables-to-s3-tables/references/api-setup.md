# API setup

The migration commands are part of the `aws s3tables` CLI: `start-table-migration`,
`get-table-migration`, `update-table-migration`, `sync-table-migration`,
`complete-table-migration`, and `list-table-migrations`. There is no separate migration command.

## Verify the commands exist

```bash
aws s3tables help 2>/dev/null | col -b | grep -iE 'start-table-migration|sync-table-migration|complete-table-migration|get-table-migration|list-table-migrations|update-table-migration'
```

If nothing prints, the installed AWS CLI does not include the migration commands. Upgrade the AWS
CLI and check again.

## Regions

Pass `--region` on every call and do not set `--endpoint-url`. Migration is available in a subset
of S3 Tables Regions; confirm the current list in
[Migrating tables to S3 Tables](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-migrate.html)
and [S3 Tables Regions, endpoints, and service quotas](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-regions-quotas.html).
