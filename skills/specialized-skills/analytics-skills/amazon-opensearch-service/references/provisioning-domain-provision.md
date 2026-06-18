# Amazon OpenSearch Service Domain — Provision

## Prerequisites

1. Confirm AWS credentials: `aws sts get-caller-identity`
2. Verify `call_aws` or AWS CLI is available

## Step 1: Get Latest OpenSearch Version

```bash
aws opensearch list-versions
```

Pick the latest `OpenSearch_X.Y` version. Ignore `Elasticsearch_*` versions.

> For agentic search, confirm version is 3.3 or higher.

## Step 2: Create Domain

The example below provisions a single-node `t3.medium.search` for development/test only.

```bash
aws opensearch create-domain \
  --domain-name <domain-name> \
  --engine-version <latest-version> \
  --cluster-config InstanceType=t3.medium.search,InstanceCount=1 \
  --ebs-options EBSEnabled=true,VolumeType=gp3,VolumeSize=100 \
  --node-to-node-encryption-options Enabled=true \
  --encryption-at-rest-options Enabled=true \
  --domain-endpoint-options EnforceHTTPS=true
```

**For production:** use a current-generation Graviton instance — `r7g.large.search` (or larger per `references/sizing.md`) — with 3+ data nodes and 3 dedicated cluster managers (the AWS API still uses "DedicatedMaster" in CLI/SDK; prose: "cluster managers"). `r6g` is previous-generation and only used with explicit compatibility justification.

## Step 3: Enable Fine-Grained Access Control

**Recommended (production):** IAM-based authentication with MasterUserARN:

```bash
aws opensearch update-domain-config \
  --domain-name <domain-name> \
  --advanced-security-options "Enabled=true,InternalUserDatabaseEnabled=false,MasterUserOptions={MasterUserARN=arn:aws:iam::<account>:role/AdminRole}"
```

### Development Only: Internal User Database

> WARNING: NEVER use internal users in production. Production deployments MUST use IAM-based authentication (shown above). Internal user database is for local development/testing only.

```bash
PASSWORD=$(aws secretsmanager get-secret-value --secret-id opensearch-admin-password --query SecretString --output text)

aws opensearch update-domain-config \
  --domain-name <domain-name> \
  --advanced-security-options "Enabled=true,InternalUserDatabaseEnabled=true,MasterUserOptions={MasterUserName=admin,MasterUserPassword=$PASSWORD}"
```

> **Security note:** If using internal users, store the password in AWS Secrets Manager with automatic rotation enabled.

## Step 4: Configure Network Access

- **Development**: Public access with IP-based policies + fine-grained access control

> **Warning:** Never use 0.0.0.0/0. Always restrict to specific source CIDR ranges.
>
> **AWS WAF for any public domain** (defense-in-depth, beyond throwaway dev): associate an AWS WAF web ACL with the domain to block common web exploits, rate-limit by IP, and apply AWS-managed rule groups (`AWSManagedRulesCommonRuleSet`, `AWSManagedRulesKnownBadInputsRuleSet`, `AWSManagedRulesAmazonIpReputationList`). Without WAF, public domains are exposed to the open internet with no L7 protection beyond the IP allowlist.
>
> ```bash
> aws wafv2 associate-web-acl \
>   --web-acl-arn arn:aws:wafv2:<region>:<account>:regional/webacl/<name>/<id> \
>   --resource-arn arn:aws:es:<region>:<account>:domain/<domain-name>
> ```

- **Production**: Deploy within VPC, configure security groups

## Step 5: Wait for Domain Active

```bash
aws opensearch describe-domain --domain-name <domain-name>
```

Wait for `Processing: false` and `DomainStatus.Endpoint` available (10-15 min).

## Next Step

Proceed to [provisioning-domain-deploy-search.md](provisioning-domain-deploy-search.md).
