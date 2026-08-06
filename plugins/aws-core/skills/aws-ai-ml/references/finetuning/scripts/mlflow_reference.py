# scripts/mlflow_reference.py
# Reference for querying MLflow metrics from a training job.
# The agent reads this to understand the pattern, then writes
# its own code adapted to what the user needs.

import os

os.environ["AWS_DEFAULT_REGION"] = "[REGION]"

import mlflow
from mlflow.tracking import MlflowClient
from sagemaker.core.resources import TrainingJob

# Connect to MLflow via the training job
tj = TrainingJob.get(training_job_name="[TRAINING_JOB_NAME]")
mlflow.set_tracking_uri(tj.mlflow_config.mlflow_resource_arn)
client = MlflowClient()
run_id = tj.mlflow_details.mlflow_run_id

# List available metrics
run = client.get_run(run_id)
print(run.data.metrics.keys())

# Get full history for a metric
history = client.get_metric_history(run_id, "[METRIC_NAME]")
for h in history:
    print(f"step={h.step}, value={h.value:.4f}")
