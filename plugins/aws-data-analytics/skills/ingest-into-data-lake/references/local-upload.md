# Local File Upload

Upload files from the local filesystem to S3, with optional ingestion into a table.

## Workflow

### 1. Determine Intent

**First, check the source path.** If the user provides an S3 URI (e.g., `s3://...`) as the source, stop and use [s3-files.md](s3-files.md) instead. This workflow is for local files only.

Parse the user's request to route:

- **Upload only?** ("put this in S3", "upload my file", "move to AWS") -> Path A
- **Upload + make queryable?** ("load this into a table", "ingest this CSV", "make it queryable") -> Path B

If ambiguous and the file is structured (CSV, JSON, Parquet, TSV, Avro, ORC), ask: "Do you want this queryable as a table, or just stored in S3?"

### 2. Discover Local Data

1. **Validate path**: Confirm the file or directory exists and is readable
2. **Detect format**: Infer from extension (.csv, .json, .parquet, .tsv, .avro, .orc) or ask
3. **Check size**: `ls -lh` for files, `du -sh` for directories
4. **For structured files, peek at content**:
   - CSV/TSV: `head -5` to check headers, delimiter, encoding
   - JSON: `head -20` to check structure (records vs. arrays)
   - Parquet/Avro/ORC: note format, skip content peek

**Encoding check** (CSV/TSV/JSON only):

```bash
file --mime-encoding <path>
```

If not UTF-8 or ASCII, warn the user before upload. Non-UTF-8 files can cause downstream parsing failures.

### 3. Choose S3 Destination

1. **Ask for target bucket** or list available buckets:

   ```bash
   aws s3 ls
   ```

2. **Suggest prefix structure**: `s3://<bucket>/<domain>/<dataset>/<filename>`
3. **Confirm with user** before uploading

Default: preserve original filename. Override: user specifies a different key.

### 4. Upload

**Single file -- check for existing objects** before uploading (`aws s3 cp` silently overwrites):

```bash
aws s3 ls s3://<bucket>/<prefix>/<filename>
```

If the object exists, warn the user and get explicit confirmation before proceeding.

**Directory -- check for existing objects** before syncing. Use a bounded existence check to avoid enumerating every object under the prefix (which can be very slow on large prefixes):

```bash
aws s3api list-objects-v2 --bucket <bucket> --prefix <prefix>/ --max-items 1
```

If the result contains any `Contents`, objects exist and the user should be warned before proceeding. `aws s3 sync` skips unchanged files but overwrites modified ones without prompting.

**Single file upload**:

```bash
aws s3 cp <local-path> s3://<bucket>/<prefix>/<filename>
```

**Directory upload**:

```bash
aws s3 sync <local-dir> s3://<bucket>/<prefix>/
```

For files over 8 MB, `aws s3 cp` uses multipart upload automatically. No special flags needed.

**Verify upload**:

```bash
aws s3 ls s3://<bucket>/<prefix>/<filename>
```

### 5. Route Based on Intent

#### Path A: Upload Only

Report results and stop:

- S3 URI of uploaded file(s)
- File size and format
- Example command to download: `aws s3 cp s3://... .`

#### Path B: Upload + Table Ingestion

After upload completes, continue with the [s3-files.md](s3-files.md) workflow using:

- S3 path where data was uploaded
- Detected file format
- Row/size estimate
- Encoding (if checked)

Do not reimplement schema inference or table creation -- follow the S3 files workflow for those steps.

## Gotchas

- `aws s3 cp` silently overwrites existing S3 objects. Always check first.
- `aws s3 sync` skips unchanged files but overwrites modified ones without prompting. Check destination before syncing directories.
- CSV files with mixed encodings (e.g., Latin-1 headers, UTF-8 body) upload fine but break downstream parsing. Always check encoding for text formats.
- Large uploads on slow connections can time out. For files over 5 GB, suggest running the upload in a `screen` or `tmux` session.
- Compressed files (.gz, .zip): upload as-is for Path A. For Path B, note the compression so the S3 files workflow can handle decompression.

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `upload failed: ... An error occurred (AccessDenied)` | No write permission to target bucket | Check IAM policy or bucket policy allows `s3:PutObject` |
| `The user-provided path ... does not exist` | Typo in local path | Verify path with `ls` |
| `fatal error: An error occurred (NoSuchBucket)` | Bucket does not exist | List buckets with `aws s3 ls` and pick an existing one |
| Upload hangs or is very slow | Large file on slow connection | Check file size, suggest `tmux`/`screen`, verify network |

## References

- [upload-options.md](upload-options.md) -- Compression, multipart thresholds, sync vs cp tradeoffs
