"""Lambda handler with Powertools Logger, Tracer, Metrics, and Idempotency wired."""

import json

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.idempotency import (
    DynamoDBPersistenceLayer,
    IdempotencyConfig,
    idempotent,
)
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger()
tracer = Tracer()
metrics = Metrics()
persistence = DynamoDBPersistenceLayer(table_name="IdempotencyTable")

# Idempotency key: "body" deduplicates identical payloads.
config = IdempotencyConfig(event_key_jmespath="body")


# Set log_event=True only in non-production environments;
# events may contain auth tokens, cookies, or PII.
@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
@idempotent(config=config, persistence_store=persistence)
def handler(event: dict, context: LambdaContext) -> dict:
    logger.info("Processing request")

    result = process(event)

    metrics.add_metric(name="RequestsProcessed", unit=MetricUnit.Count, value=1)

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "https://your-domain.example",  # Replace with your domain
        },
        "body": json.dumps(result),
    }


@tracer.capture_method
def process(event: dict) -> dict:
    """Replace with your business logic."""
    return {"message": "success"}
