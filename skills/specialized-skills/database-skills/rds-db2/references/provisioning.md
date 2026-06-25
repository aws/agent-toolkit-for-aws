# Provisioning a New RDS for Db2 Instance

## Engine Edition + Version Matrix

| Engine | Major Versions | Parameter Group Family | Notes |
|--------|---------------|----------------------|-------|
| `custom-db2-ce` | 12.1 | `db2-ce-12.1` | Community Edition (introduced in 12.1) |
| `custom-db2-se` | 11.5, 12.1 | `db2-se-11.5`, `db2-se-12.1` | Standard Edition |
| `custom-db2-ae` | 11.5, 12.1 | `db2-ae-11.5`, `db2-ae-12.1` | Advanced Edition |

To find the latest minor version:

```bash
aws rds describe-db-engine-versions \
  --engine custom-db2-se \
  --query 'DBEngineVersions[].EngineVersion' \
  --region us-east-1
```

GovCloud version strings include a service-builder suffix (e.g. `11.5.9.0.sb00075854.r1`). Use `describe-db-engine-versions` rather than hardcoding.

## Step 1: Create Parameter Group with IBM IDs

Every RDS Db2 instance requires a custom parameter group with your IBM customer and site IDs. These are BYOL licensing identifiers.

```bash
aws rds create-db-parameter-group \
  --db-parameter-group-name rds-db2-params \
  --db-parameter-group-family db2-se-11.5 \
  --description "RDS Db2 SE 11.5 with IBM licensing IDs"

aws rds modify-db-parameter-group \
  --db-parameter-group-name rds-db2-params \
  --parameters \
    "ParameterName=rds.ibm_customer_id,ParameterValue=<YOUR_IBM_CUSTOMER_ID>,ApplyMethod=pending-reboot" \
    "ParameterName=rds.ibm_site_id,ParameterValue=<YOUR_IBM_SITE_ID>,ApplyMethod=pending-reboot"
```

**Constraints:**

- You MUST ask the user for their IBM customer ID and site ID. These are not optional.
- The parameter group family MUST match the engine edition + major version (e.g. `db2-se-11.5` for Standard Edition 11.5).

## Step 2: Create the Instance

```bash
aws rds create-db-instance \
  --db-instance-identifier <name> \
  --engine custom-db2-se \
  --engine-version <version-from-step-above> \
  --db-instance-class db.r7i.xlarge \
  --db-parameter-group-name rds-db2-params \
  --allocated-storage 100 \
  --storage-type gp3 \
  --storage-encrypted \
  --kms-key-id <optional-kms-key-arn> \
  --multi-az \
  --manage-master-user-password \
  --master-username db2inst1 \
  --db-subnet-group-name <subnet-group> \
  --vpc-security-group-ids <sg-id> \
  --backup-retention-period 7 \
  --port 50000 \
  --license-model bring-your-own-license \
  --region <region>
```

**Key flags:**

- `--manage-master-user-password`: **MANDATORY for production.** RDS creates the master password and automatically rotates it in Secrets Manager. Do NOT use `--master-user-password` with a plaintext value under any circumstances for a production instance.
- `--license-model bring-your-own-license`: Required for all Db2 editions.
- `--port 50000`: Default Db2 port. Can be changed but 50000 is standard.
- `--master-username db2inst1`: Standard Db2 admin user.
- `--storage-encrypted --kms-key-id`: Enables encryption at rest. For customer-managed KMS keys, imported key material, and re-encrypting an existing instance, see `byok-kms.md`.

> For the least-privilege IAM policy and trust policy that the provisioning and License Manager calls require, see `minimum-iam.md`.

## Storage: gp3 Quirk

| Storage type | Min size | IOPS | Throughput |
|---|---|---|---|
| `gp3` | 20 GiB | Below 400 GiB: 3000 IOPS included by default (not configurable). ≥400 GiB: 3000-16000 | Below 400 GiB: 125 MB/s included by default (not configurable). ≥400 GiB: 125-1000 MB/s |
| `io1` | 100 GiB | Required: 1000-64000 | N/A |
| `io2` | 100 GiB | Required: 1000-256000 | N/A |

**Do NOT pass `--iops` or `--storage-throughput` when `--allocated-storage` is below 400 GiB with gp3.** The API rejects them. Only specify these for ≥400 GiB gp3 or io1/io2.

## Instance Class Sizing

| Instance class | vCPUs | Memory | Use case |
|---|---|---|---|
| `db.r7i.xlarge` | 4 | 32 GiB | Dev/test, small workloads |
| `db.r7i.2xlarge` | 8 | 64 GiB | Medium production |
| `db.r7i.4xlarge` | 16 | 128 GiB | Large production |
| `db.r7i.8xlarge` | 32 | 256 GiB | High-performance |
| `db.m6i.2xlarge` | 8 | 32 GiB | Balanced (less memory) |

The vCPU count matters for License Manager (see below).

## Step 3: License Manager Setup

License Manager tracks BYOL compliance. This is a one-time setup per account/region.

### Bootstrap the service-linked role (first time only)

```bash
aws iam create-service-linked-role \
  --aws-service-name license-manager.amazonaws.com

aws license-manager get-service-settings
```

If `get-service-settings` returns `AccessDenied`, your IAM role needs `license-manager:GetServiceSettings` and `license-manager:CreateLicenseConfiguration` (plus `iam:CreateServiceLinkedRole` for the one-time service-linked-role bootstrap) — scope to these specific actions rather than `license-manager:*`.

### Create a license configuration

```bash
aws license-manager create-license-configuration \
  --name "RDS-Db2-SE-License" \
  --license-counting-type vCPU \
  --license-count <vCPU-count-matching-instance-class> \
  --license-count-hard-limit \
  --product-information-list '[{
    "ResourceType": "RDS",
    "ProductInformationFilterList": [{
      "ProductInformationFilterName": "Engine Edition",
      "ProductInformationFilterValue": ["db2-se"],
      "ProductInformationFilterComparator": "EQUALS"
    }]
  }]'
```

**Note:** `aws_licensemanager_association` does NOT work with RDS ARNs directly. License Manager auto-discovers matching RDS instances via the `Engine Edition` product filter within 24 hours.

## GovCloud Differences

- ARNs use `arn:aws-us-gov:` instead of `arn:aws:`
- Engine version strings include a service-builder suffix (use `describe-db-engine-versions`)
- Directory service trust policies must use partition-neutral principals (`directoryservice.rds.amazonaws.com`), not regional ones
- Multi-region KMS keys (`mrk-*` prefix) are supported
- STS credentials from the console expire in 1-12 hours
- License Manager SLR often does not exist by default (run bootstrap above)

## Verify Instance

```bash
aws rds describe-db-instances \
  --db-instance-identifier <id> \
  --query 'DBInstances[0].{Status:DBInstanceStatus,Endpoint:Endpoint.Address,Port:Endpoint.Port,Engine:Engine,Version:EngineVersion}'
```

## Retrieve Managed Password

```bash
aws rds describe-db-instances \
  --db-instance-identifier <id> \
  --query 'DBInstances[0].MasterUserSecret.SecretArn' --output text

aws secretsmanager get-secret-value \
  --secret-id <secret-arn> \
  --query SecretString --output text
```

Returns JSON with `username` and `password`.

## Common Errors

| Error | Cause | Fix |
|---|---|---|
| `InvalidParameterValue: Invalid DB parameter group` | Parameter group family doesn't match engine edition + version | Use `db2-se-11.5` for `custom-db2-se` engine version 11.5.x |
| `InvalidSubnetGroup: DBSubnetGroup ... not found` | Subnet group name is case-sensitive | Use exact case from `describe-db-subnet-groups` |
| `AccessDenied` on License Manager | SLR not created | Run `create-service-linked-role` for license-manager.amazonaws.com |
| `InvalidParameterCombination` with gp3 IOPS | Storage < 400 GiB | Remove `--iops` and `--storage-throughput` flags |
| `InsufficientDBInstanceCapacity` | Instance class not available in AZ | Try a different AZ or instance class |
