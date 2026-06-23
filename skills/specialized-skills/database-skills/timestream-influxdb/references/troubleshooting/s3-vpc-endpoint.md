# S3 VPC Endpoint Requirement (InfluxDB 3)

## Problem

InfluxDB 3 uses Amazon S3 for WAL and data storage (Parquet files). If your V3 instance or cluster is in a **private subnet** without internet access, it requires an S3 VPC Gateway Endpoint to function.

## Symptoms

- Instance fails to start or becomes unhealthy after provisioning
- "S3 endpoint does not exist" errors in logs
- Write failures with no clear error message

## Fix

Create an S3 VPC Gateway Endpoint in the **same VPC and account** as the InfluxDB 3 instance:

```bash
aws ec2 create-vpc-endpoint \
  --vpc-id <vpc-id> \
  --service-name com.amazonaws.<region>.s3 \
  --route-table-ids <route-table-id> \
  --vpc-endpoint-type Gateway
```

## Important Notes

- The S3 endpoint **must be in the same account VPC** — shared subnets from another account will NOT work
- This applies to V3 only (V2 does not use S3 for storage)
- Verify with: `aws ec2 describe-vpc-endpoints --filters Name=vpc-id,Values=<vpc-id>`
- Use `scripts/check_vpc_endpoints.sh` to automate this check
