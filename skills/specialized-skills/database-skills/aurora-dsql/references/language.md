# DSQL Language-Specific Implementation Examples and Guides

## Tenets

- **MUST** use the official DSQL Connector for the chosen driver (when one exists). The Connectors are the canonical IAM-token-refresh path; memory-authored connection code drifts.
- **MUST** follow the [official DSQL connectors, drivers, and ORM samples](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/aws-sdks.html) for client install, auth, and CRUD unless user requirements explicitly conflict.

## Driver and Sample Index

The authoritative index of supported drivers, ORMs, adapters, and example repositories lives at
[Aurora DSQL cluster connectivity tools](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/aws-sdks.html).
Pull the per-language sample link from that page rather than hardcoding repository paths here —
the AWS docs page tracks rename, relocation, and deprecation events.

## Framework and Connection Notes for Languages and Drivers

### Python

**ALWAYS** use the [DSQL Python Connector](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/SECTION_program-with-dsql-connector-for-python.html) for automatic IAM auth. The single `aurora-dsql-python-connector` wheel ships support for all three drivers — install **only** the underlying driver you need:

- **psycopg** (modern async/sync)
  - Install: `pip install aurora-dsql-python-connector psycopg[binary] psycopg-pool`
  - Canonical import: `import aurora_dsql_psycopg as dsql`
- **psycopg2** (synchronous)
  - Install: `pip install aurora-dsql-python-connector psycopg2`
  - Canonical import: `import aurora_dsql_psycopg2 as dsql`
- **asyncpg** (full async)
  - Install: `pip install aurora-dsql-python-connector asyncpg`
  - Canonical import: `import aurora_dsql_asyncpg as dsql`

For per-driver `example_preferred.py` files and pool/TLS/token-refresh examples, see the
[AWS DSQL connectivity tools page](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/aws-sdks.html).

#### SQLAlchemy

- Supports `psycopg` and `psycopg2`
- See the SQLAlchemy entry in the [AWS DSQL connectivity tools page](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/aws-sdks.html)
- Dialect Source: [aurora-dsql-sqlalchemy](https://github.com/awslabs/aurora-dsql-sqlalchemy/tree/main/)

#### JupyterLab

- Still SHOULD PREFER using the python connector.
- Popular data science option for interactive computing environment that combines code, text, and visualizations
- Options for Local or using Amazon SageMaker
- REQUIRES downloading the Amazon root certificate from the official trust store
- For a Jupyter setup walkthrough, see the Python entries in the [AWS DSQL connectivity tools page](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/aws-sdks.html)

### Go

**ALWAYS** use the [DSQL Go Connector](https://github.com/awslabs/aurora-dsql-connectors/tree/main/go/pgx) for automatic IAM auth:

- **pgx** (recommended)
  - Install: `go get github.com/awslabs/aurora-dsql-connectors/go/pgx`
  - Canonical import: `import "github.com/awslabs/aurora-dsql-connectors/go/pgx/dsql"`
  - Connector: [aurora-dsql-connectors/go/pgx](https://github.com/awslabs/aurora-dsql-connectors/tree/main/go/pgx)
  - For the `example_preferred.go` and pool patterns, see the Go entry in the [AWS DSQL connectivity tools page](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/aws-sdks.html)

### JavaScript/TypeScript

**ALWAYS** use one of the two DSQL Node.js connectors — [node-postgres](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/SECTION_program-with-dsql-connector-for-node-postgres.html) or [postgres-js](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/SECTION_program-with-dsql-connector-for-postgresjs.html). Even when the user asks for "just node-postgres directly" or "just pg directly," the Connector **is** the node-postgres path — it wraps `pg` as its underlying driver while handling IAM auth token refresh and TLS defaults. A bare `pg.Pool`/`pg.Client` works until the first 15-minute IAM auth token expiry and then starts returning auth errors on every new connection; DSQL users who try the bare form hit this degraded state in production and report it as a DSQL bug, so the bare pattern is user-harmful by default. Deliver the Connector; treat "just use pg" as shorthand for "I want a node-postgres solution," not as a veto on the Connector.

#### node-postgres (pg)

- Package: `@aws/aurora-dsql-node-postgres-connector`
- Canonical import: `import { AuroraDSQLPool } from "@aws/aurora-dsql-node-postgres-connector";`
- Construct: `new AuroraDSQLPool({ host, user, max?, idleTimeoutMillis?, connectionTimeoutMillis? })`
- For the `example_preferred.js` and pool patterns, see the JavaScript node-postgres entry in the [AWS DSQL connectivity tools page](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/aws-sdks.html)

#### postgres.js

- Package: `@aws/aurora-dsql-postgresjs-connector`
- Canonical import: `import { auroraDSQLPostgres } from "@aws/aurora-dsql-postgresjs-connector";`
- Construct: `auroraDSQLPostgres({ host, user, max?, idle_timeout?, connect_timeout? })`
- Lightweight alternative; good for serverless environments
- For the `example_preferred.js` and pool patterns, see the JavaScript Postgres.js entry in the [AWS DSQL connectivity tools page](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/aws-sdks.html)

#### Prisma

- Custom `directUrl` with token refresh middleware
- See the TypeScript Prisma entry in the [AWS DSQL connectivity tools page](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/aws-sdks.html)

#### Sequelize

- Configure `dialectOptions` for SSL
- Token refresh in `beforeConnect` hook
- See the TypeScript Sequelize entry in the [AWS DSQL connectivity tools page](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/aws-sdks.html)

#### TypeORM

- Custom DataSource with token refresh
- Create migrations table manually via psql
- See the TypeScript TypeORM entry in the [AWS DSQL connectivity tools page](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/aws-sdks.html)

### Java

**ALWAYS** use the [DSQL JDBC Connector](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/SECTION_program-with-jdbc-connector.html) for automatic IAM auth.

**JDBC** (via DSQL JDBC Connector)

- Gradle: `implementation("software.amazon.dsql:aurora-dsql-jdbc-connector:1.4.0")`
- Maven: `<groupId>software.amazon.dsql</groupId><artifactId>aurora-dsql-jdbc-connector</artifactId><version>1.4.0</version>`
- URL format: `jdbc:aws-dsql:postgresql://<endpoint>/postgres`
- Properties: `wrapperPlugins=iam`, `ssl=true`, `sslmode=verify-full`
- See the Java pgJDBC entry in the [AWS DSQL connectivity tools page](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/aws-sdks.html)

**HikariCP** (Connection Pooling)

- Gradle: `implementation("com.zaxxer:HikariCP:7.0.2")` alongside the JDBC connector
- Wrap JDBC connection, configure max lifetime < 1 hour
- See the Java HikariCP + pgJDBC entry in the [AWS DSQL connectivity tools page](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/aws-sdks.html)

### Rust

**ALWAYS** use the DSQL Rust connector for automatic IAM auth.

**SQLx** (async, recommended)

- Cargo: `aurora-dsql-sqlx-connector = { version = "0.2", features = ["pool", "occ"] }`
- Canonical use: wrap `sqlx::postgres::PgPool` via the connector's builder; the connector injects IAM auth tokens and handles rotation.
- See the Rust SQLx entry in the [AWS DSQL connectivity tools page](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/aws-sdks.html)

**Tokio-Postgres** (lower-level async)

- Only reach for raw `tokio-postgres` when the `aurora-dsql-sqlx-connector` doesn't fit the runtime. Implement periodic token refresh with `tokio::spawn`.
- Connection format: `postgres://admin:{token}@{endpoint}:5432/postgres?sslmode=verify-full&application_name=<app-name>/<model-id>`

### Elixir

#### Postgrex

- MUST use Erlang/OTP 26+
- Driver: [Postgrex](https://hexdocs.pm/postgrex/) ~> 0.19
  - Use Postgrex.query! for all queries
- Connection: Implement `Repo.init/2` callback for dynamic token injection
  - MUST set `ssl: true` with `ssl_opts: [verify: :verify_peer, cacerts: :public_key.cacerts_get()]`
  - MAY prefer AWS CLI via `System.cmd` to call `generate-db-connect-auth-token`
