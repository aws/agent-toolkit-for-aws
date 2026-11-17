# MLflow Tracking Requirements

Shared requirements for logging a SageMaker Dataset Service job (synthetic data
generation **or** data quality evaluation) to SageMaker managed MLflow. Read this
only when the user has opted into MLflow tracking; the default (no MLflow) path
does not need it.

When MLflow is configured, the job logs its parameters and metrics into the
user's **MLflow app**. Collect the user's **MLflow app ARN**, then validate
against the following.

## Requirements

- **MLflow app ARN** — must be a SageMaker **MLflow app** ARN of the form
  `arn:aws:sagemaker:<region>:<account-id>:mlflow-app/<id>`. This is the
  serverless MLflow app, **not** an MLflow *tracking server*
  (`mlflow-tracking-server/...`). This reference has no validated workflow for
  tracking-server ARNs; the service will reject them if submitted.

  To get one:
  - **Console:** SageMaker AI → MLflow → create an MLflow app, then copy its ARN.
  - **CLI:** `aws sagemaker create-mlflow-app --name <name> --artifact-store-uri s3://<bucket>/<prefix> --role-arn <role-with-s3-access>` returns the app `Arn`. Use `aws sagemaker list-mlflow-apps` / `describe-mlflow-app --arn <arn>` to find or confirm an existing one.

- **Region** — the MLflow app must be in the **same region** as the job (the job
  reaches it at the regional endpoint `mlflow.sagemaker.<region>.app.aws`). An app
  in another region cannot be reached.

- **Role permissions** — the job's execution role needs permission to call the
  MLflow app data plane. These are **`sagemaker:`** actions scoped to the app ARN
  — *not* the granular `sagemaker-mlflow:*` actions (those apply to MLflow
  tracking servers, which have no validated workflow in this reference). Without them the MLflow setup
  step fails fast with a client error.
  Attach an inline policy granting the following.

  ```json
  {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Sid": "MlflowAppAccess",
        "Effect": "Allow",
        "Action": [
          "sagemaker:CallMlflowAppApi",
          "sagemaker:DescribeMlflowApp"
        ],
        "Resource": "arn:aws:sagemaker:<region>:<account-id>:mlflow-app/<id>"
      }
    ]
  }
  ```
