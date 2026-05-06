# Network Setup

VPC, subnet, and security group configuration for Glue connections to private data sources. Skip this reference if the source is reachable over the public internet (Snowflake default, BigQuery, public RDS).

## Contents

- [When Networking Is Required](#when-networking-is-required)
- [VPC and Subnet](#vpc-and-subnet)
- [Security Group Rules](#security-group-rules)
- [S3 VPC Endpoint](#s3-vpc-endpoint)
- [NAT Gateway](#nat-gateway)
- [Cross-VPC and On-Prem](#cross-vpc-and-on-prem)

## When Networking Is Required

Required:

- RDS/Aurora in private subnets
- Redshift in private subnets
- Self-managed databases in a VPC
- Snowflake with PrivateLink
- BigQuery if the Glue job also needs private AWS resources (then the Glue subnet needs NAT egress for Google APIs)

Not required:

- Public Snowflake endpoints
- Public BigQuery (default)
- Public RDS instances (not recommended for production)

## VPC and Subnet

The Glue connection's `SubnetId` determines where Glue provisions ENIs at job runtime. Constraints:

- MUST be in the same VPC as the source (or a peered/VPN-connected VPC)
- SHOULD be a private subnet with NAT gateway egress (Glue needs internet access to pull dependencies and write to CloudWatch)
- MUST have route to source's VPC
- `AvailabilityZone` in `PhysicalConnectionRequirements` MUST match the subnet's AZ

Match AZ to source for lower latency:

```bash
aws rds describe-db-instances --db-instance-identifier <ID> \
  --query 'DBInstances[0].AvailabilityZone'
```

## Security Group Rules

Two security groups are involved: Glue's and the source's.

**Glue security group (outbound):**

- Allow TCP to source port (1521 Oracle, 1433 SQL Server, 5432 Postgres, 3306 MySQL, 5439 Redshift)
- Destination: source's security group ID
- Self-referencing rule on all ports: Glue ENIs must talk to each other during a job. Required even for single-worker jobs.

**Source security group (inbound):**

- Allow TCP on source port from Glue's security group ID (not CIDR -- ENIs change)

Verify:

```bash
aws ec2 describe-security-groups --group-ids <glue-sg> \
  --query 'SecurityGroups[0].IpPermissionsEgress'
aws ec2 describe-security-groups --group-ids <source-sg> \
  --query 'SecurityGroups[0].IpPermissions'
```

## S3 VPC Endpoint

Glue jobs read their scripts from S3 and write results to S3. The Glue subnet MUST have either a NAT gateway or an S3 VPC gateway endpoint; endpoint is preferred (no NAT costs, stays on AWS backbone).

Check:

```bash
aws ec2 describe-vpc-endpoints \
  --filters Name=vpc-id,Values=<VPC_ID> Name=service-name,Values=com.amazonaws.<region>.s3
```

Create if missing:

```bash
aws ec2 create-vpc-endpoint \
  --vpc-id <VPC_ID> \
  --service-name com.amazonaws.<region>.s3 \
  --route-table-ids <RTB_ID>
```

Without this, Glue jobs fail at startup with `UnableToFindVpcEndpoint`.

## NAT Gateway

Required if:

- Glue needs to reach the internet (BigQuery, public Snowflake, external APIs)
- The subnet has no S3 VPC endpoint

Not required if:

- Source is in the same VPC AND S3 VPC endpoint exists AND no other internet access needed

NAT gateway costs per-hour plus per-GB processed. For pure private-VPC ETL with S3 endpoint, omit it.

## Cross-VPC and On-Prem

**Peered VPCs:** Glue subnet's route table MUST have a route to the source VPC's CIDR via the peering connection. Both VPCs must be in the same region.

**Transit Gateway:** Route tables in both VPCs attached to the TGW MUST have routes to each other's CIDR.

**On-premises via VPN/Direct Connect:** Route table for Glue subnet MUST have a route to on-prem CIDR via virtual private gateway (VPN) or transit gateway (DX). Source firewall must allow inbound from Glue's ENI IPs (which change per-job -- use subnet CIDR).

Test reachability from an EC2 instance in the same subnet before creating the Glue connection:

```bash
# From EC2 in Glue's intended subnet
telnet <source-host> <source-port>
```

If EC2 can't reach the source, neither will Glue. Fix routing first.
