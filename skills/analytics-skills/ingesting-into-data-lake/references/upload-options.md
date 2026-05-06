# Upload Options Reference

## cp vs sync

| Command | Use when |
|---------|----------|
| `aws s3 cp` | Single file, or directory with `--recursive` |
| `aws s3 sync` | Directory upload, skips unchanged files on re-run |

`sync` is idempotent — safe to re-run after interruption. Prefer `sync` for directories.

## Multipart Upload

`aws s3 cp` automatically uses multipart for files over 8 MB (default threshold). No flags needed. To tune:

```bash
aws configure set default.s3.multipart_threshold 64MB
aws configure set default.s3.multipart_chunksize 64MB
```

## Compression Before Upload

Compressing locally saves transfer time and storage cost. Downstream tools (Athena, Glue) read gzip natively.

```bash
gzip file.csv
aws s3 cp file.csv.gz s3://<bucket>/<prefix>/
```

Do NOT compress Parquet, Avro, or ORC — they have built-in compression.

## Overwrite Protection

Check if target exists before uploading:

```bash
aws s3 ls s3://<bucket>/<prefix>/<filename>
```

If it exists, warn the user. `aws s3 cp` overwrites without confirmation.
