# MWAA Serverless Code Packaging (Python/Bash)

How to ship custom code for `PythonOperator`/`BashOperator` tasks. The
authoritative reference for pre-installed packages, Python version, and worker
constraints is fetched in B3 step 0 of the skill. This file covers the
operational packaging and deployment mechanics.

## Delivering code

Pass code via `--code '{"S3Location": {"Bucket": "...", "ObjectKey": "...",
"VersionId": "..."}}'` on `create-workflow`/`update-workflow` (alongside
`--definition-s3-location` for the YAML; `VersionId` optional). Accepted: a
single `.py`, a single `.sh`, or a `.zip` with all modules and dependencies at
the archive root. Code extracts to `/usr/local/airflow/dags`, so root-level
modules import directly; `python_callable` uses `module_name.function_name`.

## Packaging with dependencies

Stage sources and deps in one directory, install Linux wheels for the runtime
Python version (from the [operators-python-bash-detail doc](https://docs.aws.amazon.com/mwaa/latest/mwaa-serverless-userguide/operators-python-bash-detail.html); verify the platform tag and version there if the runtime architecture changes), then zip from inside that directory:

    mkdir package && cp my_module.py package/
    pip install -r requirements.txt --target package \
        --platform manylinux2014_x86_64 --python-version <PY_VERSION> --only-binary=:all:
    cd package && zip -r ../my_code.zip . -x "*__pycache__*" "*.pyc"

Replace `<PY_VERSION>` with the version from the AWS doc (e.g., `3.12`). The
`--platform`/`--python-version`/`--only-binary` flags are REQUIRED — without
them pip installs wheels for the local machine and imports fail at run time.

`--target package` installs the full dependency tree, so pip may also pull in
packages that are already pre-installed (as transitive deps). That is harmless
at run time — the pre-installed copy takes precedence — but the bundled copies
still count against the 250 MB code-bundle limit. Keep `requirements.txt` to
packages that are not pre-installed, and if you are near the size limit, delete
the pre-installed packages (per the AWS doc's list) from `package/` before
zipping. Do NOT add `--no-deps` to suppress this — it would also drop
genuinely-missing transitive dependencies and break imports at run time.

## Rules and limits

- Only bundle packages that are NOT already pre-installed; design your code
  against the pre-installed versions. Pre-installed packages take precedence
  over a bundled copy — if you bundle a different version of a pre-installed
  package, your version is not used and the pre-installed version is imported
  instead. The AWS doc (fetched in B3 step 0) lists the full pre-installed set.
- All deps must be `manylinux2014_x86_64` wheels for the runtime Python
  version — verify the platform tag and version against the [operators-python-bash-detail doc](https://docs.aws.amazon.com/mwaa/latest/mwaa-serverless-userguide/operators-python-bash-detail.html); files at the zip root; no `__pycache__`.
- Code file <= 250 MB; zip uncompressed <= 250 MB; 75 GB total per account —
  verify current values against [Quotas for Amazon MWAA Serverless](https://docs.aws.amazon.com/mwaa/latest/mwaa-serverless-userguide/mwaa-serverless-quotas.html)
  at runtime, as these quotas can change.
- No internet by default (add a `NetworkConfiguration` VPC for external calls).
  Execution-role creds resolve automatically via the default provider chain.
- For reproducible prod deploys, enable S3 versioning and pin `VersionId`.
- The service snapshots code at `create-workflow`/`update-workflow` time.
  Updating the S3 object alone does NOT update the running code — call
  `update-workflow` with `--code` again to re-snapshot.

Extraction failures and runtime `ModuleNotFoundError`/`ImportError` are almost
always a packaging problem (wrong-platform wheel, missing dep, bad layout);
repackage per the steps above.
