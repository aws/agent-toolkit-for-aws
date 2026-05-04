# S3 Tables Access Control

You MUST use least-privilege permissions when configuring access to S3 Tables.

## Bucket Policy (s3tables actions)

Actions: `s3tables:GetTableBucket`, `s3tables:GetNamespace`, `s3tables:GetTable`, `s3tables:GetTableMetadataLocation`, `s3tables:GetTableData`

Resources:

- `arn:aws:s3tables:{region}:{account_id}:bucket/{bucket_name}`
- `arn:aws:s3tables:{region}:{account_id}:bucket/{bucket_name}/table/*`

Set with `aws s3tables put-table-bucket-policy --table-bucket-arn <ARN> --resource-policy '<POLICY_JSON>'`.

## IAM Policy (glue actions)

Actions: `glue:GetCatalog`, `glue:GetDatabase`, `glue:GetTable`

Resources (all three actions on each):

- `arn:aws:glue:{region}:{account_id}:catalog` (root -- required for federated catalog resolution)
- `arn:aws:glue:{region}:{account_id}:catalog/s3tablescatalog`
- `arn:aws:glue:{region}:{account_id}:catalog/s3tablescatalog/*`
- `arn:aws:glue:{region}:{account_id}:database/s3tablescatalog/*/*`
- `arn:aws:glue:{region}:{account_id}:table/s3tablescatalog/*/*/*`

## SSE-KMS

If the table bucket uses SSE-KMS, the querying principal also needs `kms:Decrypt` and `kms:GenerateDataKey` on the KMS key.

## Glue ETL Service Role

See `table-creation-glue-etl.md` for the Glue job service role permissions.

## Additional Resources

For latest IAM guidance, search AWS docs for `"S3 Tables identity-based policies IAM"`, `"S3 Tables access management"`, and `"S3 Tables Glue catalog prerequisites"`.
