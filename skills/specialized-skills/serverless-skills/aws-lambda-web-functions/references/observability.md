# Observability

## Logs

**Every log line is already structured JSON, with no configuration and no logging library.** A
plain `console.log('GET /')` inside a request handler arrives in CloudWatch as:

```json
{"timestamp":"2026-09-16T23:48:17.188Z","level":"INFO","message":"GET /",
 "requestId":"NF5U6CMIUAWPER24GXDNDEZSVU","endpointName":"default","region":"us-east-1"}
```

`requestId` and `endpointName` are injected for you, so requests are correlatable without passing
a context object down your call stack. `applicationLogLevel` filtering works against the `level`
field, so raising the level actually suppresses lines rather than just tagging them. If you are
porting code that wraps every log call in a logging library purely to get JSON and a request id,
you can drop that wrapper.

Lines emitted outside a request, during module load, carry `timestamp`, `level`, `message` and
`region` but no `requestId`, because there is no request to attribute them to.

The platform also emits its own records under a `type` field — `platform.initStart`,
`platform.initReport`, `platform.invokeStart`, `platform.invokeSummary` — with the detail in a
nested `record` object. `platform.initReport` is the one worth alerting on: it carries
`status: success` or `status: failure` with an `errorType`, and it is the only reliable signal that
a revision actually started. See the deployment warning on `LatestRevision` in
[deployment.md](deployment.md).

Cold start cost is reported in `platform.initReport.record.metrics`, so measure your own app rather
than assuming a figure — the dominant term for most apps is module resolution, and importing the
AWS SDK is usually the largest single contributor. Keep the deployment package small and import
SDK clients lazily inside the handler that needs them rather than at module top level. The metric
field names have changed between runtime versions, so read whatever the record contains rather than
hardcoding a key.

- Everything written to `console.log()` is shipped to CloudWatch Logs
- Works if the execution role has CloudWatch Logs permissions

## Distributed tracing

There is **no X-Ray instrumentation wired into the execution environment**. Neither `_X_AMZN_TRACE_ID` nor
`AWS_XRAY_DAEMON_ADDRESS` is set, so the X-Ray SDK has no trace header to continue and no daemon
to emit segments to, and auto-instrumentation that depends on those variables will no-op silently
rather than error. Confirm against the current documentation before ruling tracing out.

Until it is, correlate with what the platform does give you: the `requestId` on every log line,
and the `lambda-web-request-id` response header, which lets a caller tie a client-side failure to
a specific server-side request.

### Logging Configuration

Logging is configurable via `serviceConfig.telemetryConfig.loggingConfig`. All three fields are optional:

| Field | Values | Default |
|-------|--------|---------|
| `logGroup` | Any CloudWatch log group name | `/aws/lambda/web/{function-name}` if unset |
| `applicationLogLevel` | `TRACE`, `DEBUG`, `INFO`, `WARN`, `ERROR`, `FATAL` | `INFO` |
| `systemLogLevel` | `DEBUG`, `INFO`, `WARN` | `INFO` |

For anything serving real traffic, encrypt this log group with your own KMS key — see
Logging Security below.

```json
"serviceConfig": {
  "executionRoleArn": "...",
  "telemetryConfig": {
    "loggingConfig": {
      "logGroup": "/my-app/prod",
      "applicationLogLevel": "DEBUG",
      "systemLogLevel": "WARN"
    }
  }
}
```

`applicationLogLevel` filters your app's `console.*` output; `systemLogLevel` filters runtime/platform logs. Send the JSON above with `create-web-function` or `create-web-function-revision`.

## Viewing Logs

```bash
# Use the log group you configured (or the default if unset)
aws logs tail {logGroup} --follow --region {home-region}
```

Tail `{logGroup}` — it holds every region's logs centralized to the home region; the `{logGroup}.local` group you will also see holds only what the region that served the request wrote, so it is expected rather than a stray group.

## Structured Logging

```javascript
console.log(JSON.stringify({
  level: 'info',
  message: 'Request handled',
  path: req.path,
  method: req.method,
  statusCode: res.statusCode,
  durationMs: Date.now() - start
}));
```

## Health Checks

```javascript
app.get('/api/health', (req, res) => {
  res.json({
    status: 'ok',
    uptime: process.uptime(),
    memory: process.memoryUsage().rss
  });
});
```

## Error Tracking

```javascript
app.use((err, req, res, next) => {
  console.error(JSON.stringify({
    level: 'error',
    message: err.message,
    stack: err.stack,
    path: req.path
  }));
  res.status(500).json({ error: 'Internal server error' });
});
```

## Multi-Region Observability

Multi-region endpoints are **latency-routed per request**, so invokes spread across all configured regions.

**Which region served a request?** Read `AWS_REGION` in your app; it's the region that actually executed the invoke. Log it next to a request id:

```javascript
console.log(JSON.stringify({ requestId, region: process.env.AWS_REGION, path: req.path }));
```

For AZ and stage as well, call the runtime execution-environment metadata endpoint from inside the function (`AWS_LAMBDA_METADATA_API`, authenticated with `AWS_LAMBDA_METADATA_TOKEN`).

### Logs and metrics

- Each region keeps the logs it served, **and** they replicate to the home region automatically. Expect a cross-region replication delay.
- In the home region, each source region's events land in a stream named `{stream}-{accountId}-{region}`, so the stream name tells you the origin.
- Metrics (invocations, latency, 2xx/3xx/4xx/5xx) aggregate into the home region too.

```bash
# Home region, filtered to one source region
aws logs tail {logGroup} --region {home-region} \
  --log-stream-name-prefix {stream}-{accountId}-us-east-1
```

## Logging Security

- **Don't log sensitive data.** Never write credentials, tokens, session cookies, `Authorization` headers, or PII to logs. Redact them before logging — request/response bodies and headers often carry secrets. Prefer allow-listing the fields you log (as in Structured Logging above) over dumping whole request objects.
- **Encrypt logs with your own KMS key.** CloudWatch Logs are encrypted at rest by default with an AWS-managed key, which means decryption is not gated on any policy you control. Associate the log group with a customer-managed KMS key so access is governed by your key policy and auditable in CloudTrail:

  ```bash
  aws logs associate-kms-key --log-group-name {logGroup} --kms-key-id {arn}
  ```

  Do this for any endpoint serving real traffic — request paths, headers and error payloads routinely capture more than intended.

## Auditing & Alarms

- **CloudTrail.** Control-plane calls (`CreateWebFunction`, `CreateWebFunctionRevision`, `UpdateWebFunctionEndpoint`, `DeleteWebFunction`, etc.) are recorded in CloudTrail. Ensure a trail is enabled in the account to audit who created/changed/deleted functions and endpoints.
- **CloudWatch alarms.** Add alarms on error rate, p99 latency, and throttling/concurrency so you're alerted on regressions — especially before shifting traffic to a new revision.

## Checking Active Revision

Use `aws lambda-web get-web-function-endpoint` to see which revision is serving traffic:

```bash
aws lambda-web get-web-function-endpoint \
  --function-name {name} --endpoint-name default --region {region}
# Shows: state, revisionWeights, domainName, updateStatus
```
