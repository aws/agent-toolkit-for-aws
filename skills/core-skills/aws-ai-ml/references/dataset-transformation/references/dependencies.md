# Python Dependencies

The local-execution scripts and templates use these third-party packages. Each
one is pinned to an exact version. Install only these pinned versions; never
suggest an unpinned `pip install <package>`, and never install a package on the
user's behalf (`spec_execution_flow.md` Step 4).

| Package | Version | Used by | When needed |
|---|---|---|---|
| `pandas` | `2.3.3` | `code_templates/ingest_fn.py`, `code_templates/filter_fn.py`, `scripts/build_training_set.py` (Parquet fallback) | Ingest, filter |
| `ftfy` | `6.3.1` | `code_templates/clean_fn.py` | Encoding fixes in clean |
| `pyarrow` | `25.0.1` | `code_templates/api_codegen_generate.py`, `scripts/build_training_set.py` (Parquet) | CodeGen Job 1 Parquet schema inspection and other Parquet inputs |
| `scikit-learn` | `1.7.2` | `scripts/cluster_split.py` | `--strategy cluster` only |
| `sentence-transformers` | `6.3.0` | `scripts/cluster_split.py` | `--strategy cluster` only |

`boto3` and the SageMaker SDK are installed by `../../sdk-getting-started/`; do not
install them from here.

Install commands (show only the ones the run needs):

```bash
pip install pandas==2.3.3 ftfy==6.3.1
pip install pyarrow==25.0.1
pip install scikit-learn==1.7.2 sentence-transformers==6.3.0
```

## Updating a pin

Versions change only through a reviewed code change to this file and the
install hints that point here. When a CVE is reported against a pinned
version, bump the pin to a fixed release in that change; do not float to the
latest release.
