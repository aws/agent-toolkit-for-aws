# Aurora Express Configuration — Constraints and Limitations

Constraints below are documented in the AWS Aurora User Guide; verify current constraints before acting. Each bullet cites its source; those subject to change are marked.

## Engine constraints

- **Aurora PostgreSQL only** — Aurora MySQL is not supported. The express path in console and CLI is PostgreSQL-only. Source: [Create with express configuration](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html) (primary reference).
- **Engine version is the AWS default for this flow** — The express flow does not expose the full engine-version picker; verify the current default in the [Aurora PostgreSQL User Guide](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Aurora.AuroraPostgreSQL.html). Versions can be upgraded later via modify. Subject to change.
- **Extensions and engine features follow the selected version** — Any extension or feature unavailable in the version AWS picks is unavailable in the cluster. Source: [extensions](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Appendix.PostgreSQL.Extensions.html). Subject to change.

## Networking constraints

- **No customer VPC** — Express clusters are not placed in a customer VPC, subnet group, or security group. Connectivity comes from an AWS-managed layer. Source: [Create with express configuration](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html).
- **AWS-managed connectivity only** — The routing layer terminating PostgreSQL connections is AWS-managed and not customer-configurable; customers cannot attach, peer, or modify it. Source: same page above.
- **No VPC endpoints or PrivateLink routing** — VPC-dependent and unavailable here. Source: [Aurora and VPC endpoints](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/USER_VPC.html). Subject to change.
- **No customer security groups** — A VPC-only construct; the express flow surfaces no security-group attachment step. Source: [Aurora security groups](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Overview.RDSSecurityGroups.html).
- **No customer subnet selection** — AZ placement is AWS-managed; the user does not pick subnets or AZs. Source: [Aurora DB subnet groups](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/USER_VPC.WorkingWithRDSInstanceinaVPC.html).
- **No customer route tables, NACLs, or Transit Gateway attachments** — All customer-side network policy controls are VPC-dependent and do not apply. Source: [Create with express configuration](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html). Subject to change.

## Capacity constraints

- **Aurora serverless only during create** — Express clusters are created with a serverless instance only; change it later via modify instance. Provisioned instance classes (for example, `r7g.xlarge`) are not selectable during create. Source: [Aurora serverless User Guide](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2.html).
- **Default min/max ACU range** — The express flow applies the AWS default serverless capacity range (verify current values); you can modify min/max during create.
- **Scale-to-zero / auto-pause** — Follows standard Aurora serverless pause/resume behavior; verify in the [Aurora serverless auto-pause documentation](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2.html). Subject to change.

## Storage and backup constraints

- **Aurora Standard storage at create; switchable after** — At create time express clusters can only use Aurora Standard storage; Aurora I/O-Optimized is not selectable during express create. Change the storage type after creation. Source: [Create with express configuration](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html) (Limitations and Express configuration settings table — "Cluster storage configuration: Aurora standard by default. Can be changed after the create operation completes.").
- **Backup retention defaults** — The retention window applied at creation is the Aurora default for this flow; verify in the [Aurora backups User Guide](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/USER_WorkingWithAutomatedBackups.html). Subject to change.

## Security and identity constraints

- **AWS owned key for encryption at rest** — Express clusters are encrypted at rest with an AWS owned key (SSE-RDS), an AWS-controlled key customers cannot view or manage; this is distinct from the AWS managed key (`aws/rds`). Customer-managed KMS keys (CMKs) belong to the Full Configuration flow, where the user selects a KMS key at creation. Source: [Encrypting Amazon Aurora resources](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Overview.Encryption.html). Subject to change.
- **IAM database authentication (REQUIRED for express)** — Express clusters only support IAM authentication through the internet access gateway. The master user (`postgres`) is automatically configured for IAM authentication during create, and subsequent database users must be too. There is no password-based auth on the master user. See [IAM database authentication for Aurora](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/UsingWithRDS.IAMDBAuth.html).
- **No Secrets Manager / managed master user password** — Express clusters do NOT support Secrets-Manager-backed master passwords. The internet access gateway only supports IAM authentication, so no password is created or stored for the master user. Do NOT use `--manage-master-user-password` or set a password manually on an express cluster — see [Password management with AWS Secrets Manager](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/rds-secrets-manager.html) for the full-configuration alternative.

## Feature incompatibilities

- **Features depending on VPC-only connectivity are unavailable** — VPC endpoints, customer VPC peering, PrivateLink-only routing, and any integration requiring the cluster to be reachable from inside a customer VPC. Source: [express configuration](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html).
- **Custom parameter groups** — The default cluster parameter group applies at creation; apply a custom parameter group after the cluster is created. See [Aurora PostgreSQL parameters](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Appendix.PostgreSQL.CommonDBATasks.Parameters.html).
- **Customer security groups** — Not applicable in the express flow (see Networking constraints).
- **Aurora Global Database — NOT supported.** AWS lists it among unsupported features (express clusters are not associated with a VPC). Source: [Limitations](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html#CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.Limitations).
- **Aurora Zero-ETL integrations — NOT supported.** A documented hard limitation (no VPC association). Source: [Limitations](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html#CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.Limitations).
- **Blue/Green deployments — NOT supported.** The AWS Limitations list explicitly names Blue/Green Deployments (along with Aurora Limitless, Aurora Global Database, RDS Proxy, Aurora Zero-ETL, RDS Query Editor, Database Activity Streams, Zero Downtime Patching, and Babelfish) as unsupported, since express clusters are not associated with a VPC. Source: [Limitations](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html#CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.Limitations).
- **RDS Data API** — Can be enabled after creation using `ModifyDBCluster`. However, Data API on an express cluster does NOT support master username/password authentication — you must create new user credentials in the database for Data API access. See [RDS Data API User Guide](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/data-api.html).

## Parity note

Express Configuration does not offer full feature parity with Full Configuration. Where the AWS documentation identifies a gap, assume the capability is unavailable in the express flow until AWS documents otherwise. Source: [Create with express configuration](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html).

## Subject-to-change

The following may evolve; re-verify against the AWS User Guide before any production decision:

- Engine support (PostgreSQL only — Aurora MySQL is not supported in express)
- Engine-version default
- Default min/max ACU values
- Backup retention default
- Customer-managed KMS key availability
- Regional availability

Always verify current behavior in the AWS User Guide before relying on a specific limit.

## Source documentation

All source pages are linked inline above. Additional feature pages: [Aurora Global Database](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-global-database.html), [Aurora Blue/Green deployments](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/blue-green-deployments.html).
