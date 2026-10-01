# S3 VPC Endpoint Troubleshooting (InfluxDB 3)

## Problem

Before diagnosing S3 connectivity, verify the [private-cluster S3
prerequisites](https://docs.aws.amazon.com/timestream/latest/developerguide/s3-vpc-endpoint-private-clusters.html).
For an existing resource, read `publiclyAccessible` from `GetDbCluster`; inspect
the Create and Update API models before asserting whether public access
is available or mutable.

When the documentation requires an S3 VPC endpoint, inspect the
endpoint's type, state, service name, VPC ownership, and `RouteTableIds`, plus
every selected subnet's effective route table. Do not infer compliance from an
internet-gateway route alone.

## Symptoms

- Instance fails to start or becomes unhealthy after provisioning
- "S3 endpoint does not exist" errors in logs
- Write failures with no clear error message

## Fix

When the prerequisites require a gateway endpoint, use the
documented VPC and account placement and service name. For example:

```bash
aws ec2 create-vpc-endpoint \
  --vpc-id <vpc-id> \
  --service-name com.amazonaws.<region>.s3 \
  --route-table-ids <route-table-id> \
  --vpc-endpoint-type Gateway
```

## Important Notes

- Verify the VPC and account ownership constraints before rejecting shared-subnet or cross-account designs
- When the prerequisites require route-table associations, inspect the effective route table for every selected subnet, including inheritance from the VPC's main route table
- Read `publiclyAccessible` from the resource and verify endpoint requirements instead of treating a `0.0.0.0/0` internet-gateway route as proof
- Verify the affected engine variants before applying this runbook
- Verify with: `aws ec2 describe-vpc-endpoints --filters Name=vpc-id,Values=<vpc-id>`
