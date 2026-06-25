# Trace Ingestion Setup for AOS/AOSS

## Architecture

```
ADOT Collector / X-Ray → OSI Pipeline → AOS/AOSS (otel-v1-apm-span-*)
```

## Option 1: ADOT Collector → OSI Pipeline → AOS

### Step 1: Create OSI Pipeline for Traces

```bash
aws osis create-pipeline --pipeline-name trace-pipeline \
  --min-units 1 --max-units 4 \
  --pipeline-configuration-body file://trace-pipeline.yaml
```

> **Tip — pipeline logging for debugging.** Trace data may carry sensitive application content (request parameters, user identifiers, span attributes), so create the log group **with KMS encryption first**, then attach it:
>
> ```bash
> # 1. Create the log group with a customer-managed KMS key
> aws logs create-log-group \
>   --log-group-name /aws/vendedlogs/OpenSearchIngestion/trace-pipeline \
>   --kms-key-id arn:aws:kms:<region>:<account>:key/<key-id>
> aws logs put-retention-policy \
>   --log-group-name /aws/vendedlogs/OpenSearchIngestion/trace-pipeline \
>   --retention-in-days 30
>
> # 2. Attach it to the pipeline
> aws osis update-pipeline --pipeline-name trace-pipeline \
>   --log-publishing-options 'CloudWatchLogDestination={LogGroup=/aws/vendedlogs/OpenSearchIngestion/trace-pipeline},IsLoggingEnabled=true'
> ```

### trace-pipeline.yaml

```yaml
version: "2"
otel-trace-pipeline:
  source:
    otel_trace_source:
      path: "/v1/traces"
  processor:
    - otel_traces:
        record_type: "event"
  sink:
    - opensearch:
        hosts: ["https://<aos-endpoint>"]
        index_type: trace-analytics-raw
        aws:
          sts_role_arn: "arn:aws:iam::<account>:role/OSIPipelineRole"
          region: "<region>"
    - opensearch:
        hosts: ["https://<aos-endpoint>"]
        index_type: trace-analytics-service-map
        aws:
          sts_role_arn: "arn:aws:iam::<account>:role/OSIPipelineRole"
          region: "<region>"
```

### Step 2: Configure ADOT Collector

Point the ADOT collector's OTLP exporter to the OSI pipeline endpoint:

```yaml
exporters:
  otlphttp:
    endpoint: "https://<pipeline-endpoint>/v1/traces"
    auth:
      authenticator: sigv4auth
extensions:
  sigv4auth:
    region: "<region>"
    service: "osis"
```

## Option 2: Application Signals → AOS

Application Signals automatically instruments applications and sends traces to X-Ray. To route these to AOS:

1. Enable Application Signals in your ECS/EKS service
2. Configure the ADOT collector (used by Application Signals) to also export traces to the OSI pipeline OTLP endpoint (`/v1/traces`)
3. Traces land in `otel-v1-apm-span-*` indices

## AOSS Pipeline Configuration

For AOSS, add `serverless: true` to the sink:

```yaml
sink:
  - opensearch:
      hosts: ["https://<collection-endpoint>"]
      index_type: trace-analytics-raw
      serverless: true
      aws:
        sts_role_arn: "arn:aws:iam::<account>:role/OSIPipelineRole"
        region: "<region>"
```

Ensure data access policy grants the pipeline role access to the collection.

## Verifying Trace Ingestion

```bash
# Check pipeline status
aws osis get-pipeline --pipeline-name trace-pipeline

# Verify data is flowing (use awscurl for data-plane access)
awscurl --service es --region $AWS_REGION \
  -X POST "$OPENSEARCH_ENDPOINT/otel-v1-apm-span-*/_search" \
  -H 'Content-Type: application/json' \
  -d '{"size": 1, "sort": [{"startTime": "desc"}]}'
```
