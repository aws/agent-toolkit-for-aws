# DSQL Connectivity & Data Loading Tools

Part of [DSQL Development Guide](../development-guide.md).

---

## Database Connectivity Tools

DSQL is compatible with many third-party database drivers and ORM libraries. The authoritative,
up-to-date list — covering connectors, adapters/dialects, driver samples, and ORM/framework
samples across all supported languages — lives at the official AWS docs page:

**→ [Aurora DSQL cluster connectivity tools](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/aws-sdks.html)**

PREFER using the DSQL Connectors when one exists for the chosen driver — they handle IAM auth token
generation and refresh automatically. For ORMs, prefer the DSQL adapters/dialects over hand-rolled
token-refresh middleware.

When picking a stack, consult the AWS docs page directly rather than caching driver lists or
sample paths in this skill — the docs page tracks rename, relocation, and deprecation events that
hardcoded links here cannot.

---

## Data Loading

For bulk data loading from CSV, TSV, Parquet, or S3 sources, follow the official AWS guide:

**→ [Loading data into Aurora DSQL](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/loading-data.html)**

The page covers supported file formats, schema inference, resume semantics, and the recommended
tooling (with platform-specific install instructions). Defer to it rather than wrapping the
loader in this skill.
