# Dataset Import (BYOD)

The hub registration of a bring-your-own-data (BYOD) dataset: one data file, local or in S3, becomes
a Dataset entity whose `HubContentArn` is the `DatasetArn` a quality evaluation takes. Read this page
on the BYOD entry point only; an SDG result or a known Dataset ARN needs no import
(`references/dataset-service-api.md`, "Verify the import").

The import runs in the generated notebook, after the user confirms the plan
(`references/quality-job-submit.md`, "Confirm the plan"): Cell 6 uploads a local file and Cell 7
registers the dataset. `references/quality-job.md` Step 8 only collects the location and verifies
access; nothing is uploaded or registered before the confirmation, and the plan states that the run
registers a Dataset entity in the account's SageMaker AI Registry, creating that hub when the account has
none. Both can be removed afterwards (`aws sagemaker delete-hub-content`, then `aws sagemaker delete-hub`;
the commands are below).

## The call

Cell 7 of `code_templates/notebook_cells.py` registers the dataset with the SDK: `DataSet.create(name=HUB_CONTENT_NAME,
source=DATASET_S3_URI, dataset_file_format=DATASET_FORMAT, role=REGISTRATION_ROLE_ARN,
validation_role_arn=VALIDATION_ROLE_ARN, wait=False, sagemaker_session=session)`,
then `dataset.wait()`, and `DATASET_ARN = dataset.arn`. The code is the cell's; copy nothing from here.

- `name` is the Hub content name collected at Step 8. `source` is the full S3 URI of the one data
  file. `dataset_file_format` is the detector's result from Step 9. `sagemaker_session` is Cell 3's
  session, so the import runs in the job's region. No `hub_name`, no version and no document are
  passed: the SDK writes the document and picks the version. A `.parquet` file is registered as
  `Custom`, the result the detector gives it.
- `role` and `validation_role_arn` are both the plan's role, Cell 3's `ROLE_ARN` (Step 11 item 3).
  For a `Custom` registration the cell's `VALIDATION_ROLE_ARN` is None, so no validation role is passed.
- The SDK also validates `role` itself, so the cell passes the plan's role there too; a refused
  role is a Common Errors row of `references/troubleshooting.md`. When `ROLE_ARN` is None (the session
  identity is itself a SageMaker execution role) the SDK's resolver, `TrainDefaults.get_role`, names
  that role.
- `wait=False` returns the entity as soon as the import call succeeds; the cell's `dataset.wait()`
  polls until the entry is Available.
- The returned object carries `name`, `version` and `arn`; `arn` is the `DatasetArn` Cell 8 sends.
- Before the import the SDK downloads the file to check it (`s3:HeadObject` and `s3:GetObject` on
  the key) and resolves an execution role (`iam:GetRole`). The notebook's credentials need those
  calls.

## What the SDK writes

- `DocumentSchemaVersion` 5.0.0, and a `HubContentDocument` of four fields: `DatasetType` `BYOD`,
  `DatasetFileFormat` (the format passed), `DatasetS3Bucket` (the bucket of the source URI) and
  `DatasetS3Prefix` (the full object key, filename included). The service adds a
  `ValidationManifest` and its own search keywords.
- A search keyword and a tag `method:generated` on the entry.
- The version. The SDK looks the name up in the account's SageMaker AI Registry. A name not found there
  gets version 1.0.0. A name already registered gets the next major version (1.0.0 is followed by
  2.0.0). A re-import under the same name is therefore a new version; nothing is overwritten, and
  the old version keeps its ARN.

- The format is recorded as passed; the SDK does not check it against the file. Step 9 runs the detector.

## Where it registers

The entry goes into the account's SageMaker AI Registry for the session's region, the hub the SDK and the
fine-tuning template use. Its name is a hash the SDK derives from the region and the account; its
display name is `AiRegistry-<region>-<account>`. The SDK creates the hub when the account has none.
There is no hub choice: the cell passes no `hub_name` (what passing one does is a Common Errors row of
`references/troubleshooting.md`).

## What the source must be

- One data file whose key ends in `.jsonl`, `.csv`, `.parquet` or `.json`. The SDK refuses any other
  source before it makes a call (`Unsupported file extension`); a folder has no extension and is
  refused the same way.
- The service evaluates one data file per dataset entry. A location holding several `.jsonl` or
  `.csv` files is rejected before compute with `contains N dataset files`, so a folder of several
  files is not a dataset the job can take. A `.json` file registers, but the job does not read that
  format; the formats the job reads are `.jsonl`, `.csv` and `.parquet`.
- A user's S3 folder: list it with `aws s3 ls s3://<bucket>/<folder>/`. One data file inside
  means its key is the source. Several means you say, in one sentence, that the service evaluates
  one data file per dataset and ask which file.
- A local file: Cell 6 uploads it to `s3://<input bucket>/byod/<hub content name>/<filename>`, and
  that URI is the source.

## Removing a registration

A registration the user does not want is removed with the hub name from the returned ARN
(`arn:aws:sagemaker:<region>:<account>:hub-content/<hub>/DataSet/<name>/<version>`):

```
aws sagemaker delete-hub-content --hub-name <hub> --hub-content-type DataSet --hub-content-name <name> --hub-content-version <version>
```

One command per version. A hub the run created (the account had none before) can be removed after
its contents with `aws sagemaker delete-hub --hub-name <hub>`; the SDK creates it again on the next
import.
