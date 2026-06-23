# aws-data-analytics

## Overview

This plugin brings AWS data engineering expertise directly into your coding assistant, covering the full data lifecycle across [AWS Analytics](https://aws.amazon.com/big-data/datalakes-and-analytics/) services; currently, skills are provided to assist with the following capability areas:

- **Data Lake Operations** — Build and operate a data lake on AWS: create managed Iceberg tables on Amazon S3 Tables, ingest data from diverse sources (S3, JDBC databases, Snowflake, BigQuery, DynamoDB, AWS Glue catalog tables), and query across default and federated catalogs with Amazon Athena.
- **Data Discovery** — Inventory and audit your AWS Glue Data Catalog across S3 Tables, Amazon Redshift-federated, and remote Iceberg catalogs. Resolve data asset references by name, keyword, column, or reverse-lookup from S3 location metadata in the catalog.
- **Vector Storage** — Store and query vector embeddings using Amazon S3 Vectors for cost-effective semantic search and RAG workloads.
- **External Connectivity** — Create and troubleshoot AWS Glue connections to JDBC databases (Oracle, SQL Server, PostgreSQL, MySQL, RDS, Aurora), Amazon Redshift, Snowflake, and BigQuery.
- **Search & Observability (OpenSearch)** — Migrate from Solr/Elasticsearch/self-managed OpenSearch into Amazon OpenSearch Service or Serverless, provision domains and collections, and build vector/semantic/hybrid search, log analytics, and trace analytics.

## Agent Skills

| # | Skill | Description | Documentation |
| -- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------- |
| 1 | `creating-data-lake-table` | Create managed Iceberg tables using Amazon S3 Tables with automatic compaction, AWS Glue catalog registration, and partitioning | [SKILL.md](skills/creating-data-lake-table/SKILL.md) |
| 2 | `ingesting-into-data-lake` | Import data from S3 files, JDBC databases, Snowflake, BigQuery, DynamoDB, or existing AWS Glue catalog tables into S3 Tables or standard Iceberg | [SKILL.md](skills/ingesting-into-data-lake/SKILL.md) |
| 3 | `querying-data-lake` | Execute and manage Athena SQL queries across default and federated catalogs (AWS Glue, S3 Tables, Amazon Redshift) | [SKILL.md](skills/querying-data-lake/SKILL.md) |
| 4 | `finding-data-lake-assets` | Resolve data lake asset references across AWS Glue Data Catalog, S3, S3 Tables, and Amazon Redshift by name, keyword, column, or S3 path | [SKILL.md](skills/finding-data-lake-assets/SKILL.md) |
| 5 | `exploring-data-catalog` | Full inventory and audit of AWS Glue Data Catalog assets across S3 Tables, Amazon Redshift-federated, and remote Iceberg catalogs | [SKILL.md](skills/exploring-data-catalog/SKILL.md) |
| 6 | `storing-and-querying-vectors` | Store and query vector embeddings using Amazon S3 Vectors for semantic search and RAG workloads | [SKILL.md](skills/storing-and-querying-vectors/SKILL.md) |
| 7 | `connecting-to-data-source` | Create and troubleshoot AWS Glue connections to JDBC databases, Amazon Redshift, Snowflake, and BigQuery | [SKILL.md](skills/connecting-to-data-source/SKILL.md) |
| 8 | `amazon-opensearch-service` | Migration, provisioning, vector/semantic/hybrid search, log analytics, and trace analytics for Amazon OpenSearch Service and Serverless | [SKILL.md](skills/amazon-opensearch-service/SKILL.md) |

## MCP Servers

| # | Server | Description |
| - | --------- | ----------------------------------------------------------- |
| 1 | `aws-mcp` | AWS API access, documentation search, and SOP retrieval via [AWS MCP Server](https://docs.aws.amazon.com/aws-mcp/latest/userguide/what-is-mcp-server.html) |

## Installation

See [Quick Start](../../README.md#quick-start).

## Data Lake Operations

The data lake skills cover the jobs-to-be-done for building and operating a data lake on AWS. They follow AWS best practices as agent-readable instruction packages, guiding you from table creation through ingestion and querying.

### How It Works

- **Create tables** — The `creating-data-lake-table` skill sets up managed Iceberg tables on Amazon S3 Tables with automatic compaction, snapshot management, AWS Glue catalog registration, partitioning, and IAM access control.
- **Ingest data** — The `ingesting-into-data-lake` skill moves data from local files, S3, JDBC databases (Oracle, SQL Server, PostgreSQL, MySQL, RDS, Aurora, Amazon Redshift), Snowflake, BigQuery, DynamoDB, or existing AWS Glue catalog tables into your data lake. Supports one-time loads, recurring pipelines, and migrations.
- **Query data** — The `querying-data-lake` skill executes Athena SQL queries across default and federated catalogs, with workgroup selection, statement classification, cost tracking, and error recovery.

### Examples

- "Create an Iceberg table for our order events with daily partitioning"
- "Import our PostgreSQL sales data into the data lake"
- "Query the top 10 customers by revenue from our analytics table"
- "Migrate our existing Hive tables to Iceberg on S3 Tables"

## Data Discovery

The discovery skills help you understand what data exists in your AWS account and find specific assets quickly.

- **`exploring-data-catalog`** — Full inventory and audit across AWS Glue Data Catalog, S3 Tables, Amazon Redshift-federated, and remote Iceberg catalogs. Maps your data landscape, flags stale tables, and suggests improvements.
- **`finding-data-lake-assets`** — Resolves fuzzy data references ("our orders table", "the sales dataset") to concrete catalog entries using layered search across AWS Glue, S3, S3 Tables, and Amazon Redshift.

### Examples

- "What data do we have in our account?"
- "Inventory all catalogs and databases"
- "Find the table that has customer_id"
- "Where is our quarterly revenue data?"

## Vector Storage

The `storing-and-querying-vectors` skill provides cost-effective vector embedding storage and retrieval using Amazon S3 Vectors, optimized for long-term storage with subsecond query latency.

### Examples

- "Create a vector index for our product embeddings"
- "Store these document embeddings for RAG"
- "Find the most similar items to this query vector"

## External Connectivity

The `connecting-to-data-source` skill creates and troubleshoots AWS Glue connections to external databases. It discovers existing connections and candidate sources in your account, registers credentials securely via Secrets Manager or IAM DB auth, configures VPC networking, and tests end-to-end connectivity.

### Examples

- "Connect to our Oracle production database"
- "Set up an AWS Glue connection to Snowflake"
- "Test my existing BigQuery connection"
- "Troubleshoot the connection timeout on my RDS connection"

## Supported Environments

### Using the plugin in your local compute

In your local environment, configure AWS credentials and set your target region to get started.

#### Prerequisites

- An AWS account with access to AWS Analytics services (AWS Glue, Athena, S3 Tables, S3 Vectors)
- Local AWS credentials and config
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (for MCP server)

#### Authentication and Authorization

Configure AWS credentials using one of the following methods:

- **AWS CLI** — Run [`aws configure`](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-quickstart.html) (IAM credentials) or [`aws sso login`](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html) (IAM Identity Center)
- **Environment variables** — Set `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_SESSION_TOKEN`. See [Configuring environment variables](https://docs.aws.amazon.com/cli/v1/userguide/cli-configure-envvars.html) for details.

Your IAM role needs permissions for the AWS services used by the skills you install. The relevant IAM action namespaces are:

- `athena` - Query execution and workgroup management
- `glue` - Data Catalog operations and ETL jobs
- `s3` - Object storage operations
- `s3tables` - Managed Iceberg table operations (separate from `s3`)
- `s3vectors` - Vector storage operations (separate from `s3`)

Scope permissions to the resources your workload uses.

#### Configuration

- Set `AWS_DEFAULT_REGION` to your preferred AWS region (e.g., `us-east-1`). See [Configuring environment variables](https://docs.aws.amazon.com/cli/v1/userguide/cli-configure-envvars.html) for details.

## Customizing Skills for Your Organization

The skills in this plugin follow AWS best practices, but they are fully customizable. You can fork the repository and modify any `SKILL.md` to reflect your organization's standards, naming conventions, approved data formats, or internal tooling. Workspace-level skills take precedence over global skills, so teams can maintain their own versions without affecting other users.

## Related Resources

- [AWS Analytics Services](https://aws.amazon.com/big-data/datalakes-and-analytics/)
- [Amazon S3 Tables](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables.html)
- [Amazon S3 Vectors](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors.html)
- [Amazon Athena User Guide](https://docs.aws.amazon.com/athena/latest/ug/what-is.html)
- [AWS Glue Developer Guide](https://docs.aws.amazon.com/glue/latest/dg/what-is-glue.html)
- [Agent Skills open standard — Anthropic](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [AWS Agent Toolkit for AWS](https://github.com/aws/agent-toolkit-for-aws)

## License

This project is licensed under the Apache 2.0 License.
