# AWS Pricing Lookup

Price List API service codes differ from Cost Explorer service names. Use these exact codes.

## Common Service Codes

| Service | Price List Code | Cost Explorer Name |
|---------|----------------|-------------------|
| EC2 | `AmazonEC2` | `Amazon Elastic Compute Cloud - Compute` |
| Lambda | `AWSLambda` | `AWS Lambda` |
| S3 | `AmazonS3` | `Amazon Simple Storage Service` |
| RDS | `AmazonRDS` | `Amazon Relational Database Service` |
| DynamoDB | `AmazonDynamoDB` | `Amazon DynamoDB` |
| ElastiCache | `AmazonElastiCache` | `Amazon ElastiCache` |
| Redshift | `AmazonRedshift` | `Amazon Redshift` |
| ECS | `AmazonECS` | `Amazon Elastic Container Service` |
| CloudFront | `AmazonCloudFront` | `Amazon CloudFront` |
| Bedrock | `AmazonBedrock` | `Amazon Bedrock` |

## EC2 Pricing Attributes

- Filter instances: `productFamily: "Compute Instance"`
- Reserved Instances: `termType: "Reserved"`, check `LeaseContractLength`, `OfferingClass`, `PurchaseOption`
- Spot and Capacity Block pricing are NOT in the Price List API

## S3 Pricing Attributes

Filter storage: `productFamily: "Storage"`. Use `volumeType` (NOT `storageClass`):

| Storage Class | volumeType Value |
|--------------|-----------------|
| Standard | `"Standard"` |
| Infrequent Access | `"Standard - Infrequent Access"` |
| One Zone IA | `"One Zone - Infrequent Access"` |
| Glacier Instant Retrieval | `"Glacier Instant Retrieval"` |
| Glacier Flexible | `"Amazon Glacier"` |
| Glacier Deep Archive | `"Glacier Deep Archive"` |
| Intelligent-Tiering | `"Intelligent-Tiering"` |

**Intelligent-Tiering has 5 sub-tiers** with distinct volumeType values: `"Intelligent-Tiering Frequent Access"`, `"Intelligent-Tiering Infrequent Access"`, `"Intelligent-Tiering Archive Instant Access"`, `"IntelligentTieringArchiveAccess"`, `"IntelligentTieringDeepArchiveAccess"`. For complete IT cost analysis, also query monitoring fee (`feeCode: "S3-Monitoring and Automation-ObjectCount"`) and transition costs (`operation: "S3-INTTransition"`).

API requests: `productFamily: "API Request"`, check `group` for request type (PUT, GET).

## RDS Pricing Attributes

- `databaseEngine`: `"MySQL"`, `"PostgreSQL"`, `"MariaDB"`, `"Aurora MySQL"`, `"Aurora PostgreSQL"`, `"SQL Server"`, `"Oracle"`, `"Db2"`
- `deploymentOption`: `"Single-AZ"`, `"Multi-AZ"`, `"Multi-AZ (readable standbys)"`
- `databaseEdition`: for Oracle/SQL Server — `"Standard"`, `"Enterprise"`, `"Express"`, `"Web"`
- `licenseModel`: important for Oracle and SQL Server
- Instances: `productFamily: "Database Instance"`. Storage: `"Database Storage"`. Aurora Serverless: `"Serverless"` or `"ServerlessV2"`

## General Rules

- **Price List API is only available in `us-east-1` and `ap-south-1`** — always specify `--region us-east-1`
- AWS uses binary system: 1 KB = 1,024 bytes
- Monthly calculations: use 730 hours/month
- Volume-based pricing: check `beginRange` and `endRange` in `priceDimensions`
- Pricing is public on-demand only — does not reflect customer-specific discounts
- Always refer customers to the AWS Pricing Calculator for detailed estimates

```bash
# List available service codes
aws pricing describe-services --region us-east-1

# Get attribute values for a service
aws pricing get-attribute-values \
  --service-code AmazonEC2 --attribute-name instanceType --region us-east-1

# Get pricing for specific product
aws pricing get-products \
  --service-code AmazonEC2 --region us-east-1 \
  --filters Type=TERM_MATCH,Field=instanceType,Value=m5.xlarge \
            Type=TERM_MATCH,Field=location,Value="US East (N. Virginia)" \
            Type=TERM_MATCH,Field=operatingSystem,Value=Linux \
            Type=TERM_MATCH,Field=tenancy,Value=Shared \
            Type=TERM_MATCH,Field=preInstalledSw,Value=NA \
            Type=TERM_MATCH,Field=capacitystatus,Value=Used
```
