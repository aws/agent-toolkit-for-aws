# Data-plane requests (OpenSearch REST API)

Every OpenSearch REST call in this skill (`_search`, `_bulk`, `_cat`, `_plugins/_ppl`, `_plugins/_ml`, mappings, ISM, saved objects) is a SigV4-signed HTTPS request to a domain, collection, or OpenSearch Application. References write these calls as `awscurl` commands. How you send them depends on the environment:

- **AWS MCP server available:** send the request with the `aws_opensearch` capability inside `run_script`. It resolves the endpoint from the resource name or ARN, so you skip the endpoint lookup and never build a URL.
- **No AWS MCP server, or `import aws_opensearch` fails in `run_script`:** run the `awscurl` command as written.

## `aws_opensearch` functions

Pick the function by target. The capability signs requests itself; there is no `--service` choice.

- **Managed domain** (`awscurl --service es`): `aws_opensearch.domain_request(domain=<name or ARN>, ...)`
- **Serverless collection** (`awscurl --service aoss`): `aws_opensearch.collection_request(collection=<ARN, id, or name>, ...)`. Prefer the ARN.
- **OpenSearch Application** (`awscurl --service opensearch`): `aws_opensearch.application_request(application=<application ARN>, ...)`. It always sends `osd-xsrf: true`, so drop the `-H "osd-xsrf: ..."` from `awscurl` examples; there is no header parameter. The chat proxy returns its event stream without an `Accept: text/event-stream` header.

All three take the same keyword arguments, and every call is awaited:

- `method`: `GET`, `POST`, `PUT`, `DELETE`, or `HEAD`, from `awscurl -X` (`GET` when `-X` is absent)
- `path`: the URL after the endpoint, query string included, e.g. `/_cat/indices?format=json`
- `body`: optional JSON string, from `awscurl -d`. `Content-Type: application/json` is sent when a body is present.
- `region_name`: optional; it must match the region in an ARN

The result is a dict with `status_code`, `headers`, and `body` (a string; parse it with `json.loads`). An HTTP 4xx/5xx raises an exception that carries the status and response body.

## Example

`awscurl --service aoss --region <region> -X POST "<collection-endpoint>/_plugins/_ppl" -d '{"query": "source = * | stats count() by index"}'` becomes:

```python
import json
import aws_opensearch

resp = await aws_opensearch.collection_request(
    collection="arn:aws:aoss:<region>:<account>:collection/<collection-id>",
    method="POST",
    path="/_plugins/_ppl",
    body=json.dumps({"query": "source = * | stats count() by index"}),
)
result = json.loads(resp["body"])
result
```

Run a whole multi-step workflow (discover indices, read mappings, sample, query) in one `run_script` call. Each call starts with no state.

## When to use `awscurl` even with the AWS MCP server

- **VPC-only domains:** `domain_request` rejects them. Run `awscurl` from a host inside the VPC.
- **Resources in another account or partition:** an ARN must belong to the caller's account.
- **Requests signed as another role** (for example, testing an OSI pipeline's sink role): `aws_opensearch` signs with the caller's credentials. Assume the role and use `awscurl`.

## Guarded routes

`aws_opensearch` rejects or limits high-risk routes: alerting destinations and the console proxy are denied; notification channels must be in-account SNS; cluster settings writes are limited to an allowlisted set of keys; snapshot repositories must use an in-account `role_arn`; security API writes are limited to `PUT` on `roles` and `rolesmapping`; ML connector, model, and agent bodies may only point at `https://*.amazonaws.com` endpoints. If a request is rejected, report the rejection to the user. Do not resend it with `awscurl` unless the user confirms, because these guards block data exfiltration and privilege escalation.

## Security considerations

- Both paths sign with the caller's IAM credentials. Use an IAM role or SSO session (temporary credentials), not long-lived access keys.
- Both paths use HTTPS. For `awscurl`, check that the endpoint starts with `https://`; `aws_opensearch` builds the HTTPS URL itself.
- Grant least privilege: `es:ESHttp*` on the domain ARN, or `aoss:APIAccessAll` on the collection plus a data access policy scoped to the needed indices. Endpoint resolution also needs `es:DescribeDomain`, `aoss:BatchGetCollection`, or `es:GetApplication`.
- Responses may contain PII or sensitive business data. Return only the fields the task needs.
- Enable CloudTrail for control-plane calls and OpenSearch audit logs for data-plane access.
