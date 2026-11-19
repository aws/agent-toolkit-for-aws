# Troubleshooting

## CLI Issues

| Error | Cause | Fix |
|-------|-------|-----|
| `invalid choice 'lambda-web'` | AWS CLI out of date | Update to the latest AWS CLI version (see deployment.md) |
| `Unknown parameter: "BuildConfig"` | PascalCase in JSON | Use camelCase: `buildConfig`, `codeConfig` |
| `authType failed constraint` | Invalid enum value | Use `ApplicationManaged` or `IamAuth` |
| `Missing required parameter` | Incomplete endpointConfig | Include `endpointName`, `endpointType`, `authType` |

## Deployment Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Stuck in "Pending" (>10 min) | Wrong trust policy | Must be `lambda.amazonaws.com` |
| Conflict error on `create-web-function` for a name you only used once | Function names are unique across **all Regions** in the account — the same name cannot exist in two Regions | Suffix the Region, or keep one function and add a `MultiRegion` endpoint (see domains-and-routing.md) |
| "S3 versioning enabled" error | Bucket lacks versioning | Enable versioning on the bucket |
| "does not have s3:GetObject" | Missing bucket policy | Add bucket policy granting `lambda.amazonaws.com` S3 read |
| 500 on create-revision (no msg) | Caller lacks S3 read | Add `s3:GetObject` + `s3:GetObjectVersion` to **caller's** policy |
| State: "Failed" | App doesn't start | Check entry point is `index.js` and that it binds the host and port from `AWS_LAMBDA_HTTP_ENDPOINT` |
| AccessDenied on get-endpoint | Resource ARN missing `/*` | Add `web-function/{name}/*` to policy Resource |

## Runtime Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| 500 + `Cannot find module '/var/task/index.js'` | Wrong filename | Must be `index.js` (not `.mjs`, not `server.js`), or deploy with `aws lambda-web deploy --entry-point {file}`, which adds the `index.js` for you |
| Crash on start + `ERR_MODULE_NOT_FOUND: Cannot find module '/var/task/app.ts'` | `.ts` file missing from ZIP | Include every `.ts` file your entry shim imports |
| 500 + `ECONNREFUSED 0.0.0.0:3000` | Bound the wrong address | Bind the host and port from `AWS_LAMBDA_HTTP_ENDPOINT`|
| 500 no logs at all | Missing CW Logs permissions | Attach `AWSLambdaBasicExecutionRole` to execution role |
| HTTP 502 | App crashes during request | Add error middleware, check logs |
| HTTP 417 on a large upload | Client sent `Expect: 100-continue`, which curl adds automatically for bodies over ~1 MB | Suppress it (`curl -H 'Expect:' ...`), or stop the client sending 100-continue |
| Large upload hangs until timeout, logs show 0 bytes received | Handler writes the response while the request body is still arriving; the request path is half-duplex | Read the request fully, then respond. Bodies under ~1 MB fit socket buffers and mask this |
| HTTP 403 | Auth type mismatch | Use `ApplicationManaged` for public |
| HTTP 429 `Platform.EndpointMaxEnvThrottle` on a new endpoint under a burst or load test, gone a few minutes later | Per-environment concurrency starts low on a new endpoint and learns; a low `maxEnvironments` caps scale-out meanwhile | Raise or remove `maxEnvironments`; repeat the test and use later runs → [scaling-and-concurrency.md](references/scaling-and-concurrency.md) |
| CloudFront `IllegalOriginAccessConfiguration`: "Lambda-Web origins require always-amz-auth signing behavior" | OAC signing behavior is `always`, `no-override` or `never` | Use an OAC with signing behavior `always-amz-auth` → [domains-and-routing.md](references/domains-and-routing.md) |
| HTTP 403 through CloudFront with OAC | Endpoint is not `IamAuth`, OAC is not origin type `lambda` with `always-amz-auth`, or the resource policy lacks a `cloudfront.amazonaws.com` statement matching the distribution's `aws:SourceArn` | Fix each → [domains-and-routing.md](references/domains-and-routing.md) |
| `Unsupported property [FunctionResourceArn]` on `AWS::Lambda::ResourcePolicy` | Wrong property name | Use `ResourceArn` with the web-function ARN → [infrastructure-as-code.md](references/infrastructure-as-code.md) |
| Static files 404 | Wrong path or not in ZIP | Use `__dirname` relative paths; check `unzip -l` |
| Module not found | node_modules missing from ZIP | `npm ci --omit=dev` then include in zip |
| Crash on start + `Cannot find package '@aws-sdk/...'`, every request 502 | The runtime does not include the AWS SDK; the client is not packaged, is marked external, or sits in `devDependencies` | Package the imported `@aws-sdk/*` clients like any other dependency → [deployment.md](references/deployment.md) |
| HTTP 507, or `EMFILE` / `too many open files` in logs | File-descriptor ceiling reached — often unclosed sockets, file handles or DB connections leaking across concurrent requests | Close handles per request and pool connections; a leak surfaces faster here because one execution environment serves many concurrent requests |
| HTTP 431 with `lambda-web-error-type: Platform.HeaderTooLarge`, no invocation and no application log entry | Request head over 128 KiB — rejected before the app | Measure total header size; shrink cookies, tokens and proxy headers → [Request header limits](#request-header-limits) |
| HTTP 431 with `lambda-web-request-id` and `lambda-web-logstream` but no `lambda-web-error-type` | More than 1,000 request header lines, including the ones the platform adds — the Node.js server rejects it while parsing | Raise `server.maxHeadersCount`, or send fewer header lines → [Request header limits](#request-header-limits) |
| ESM errors | Missing type:module | Add `"type": "module"` to package.json |

## Request header limits

A request's headers are bounded two ways, by **how many bytes** they total and by **how many**
header lines it carries. Both return HTTP **431 Request Header Fields Too Large**, so the status
code alone does not tell you which one you hit — the response headers do.

| Exceeded | Enforced by | How to tell them apart |
|----------|-------------|------------------------|
| Request head over **128 KiB** (131,072 bytes) | The platform, before your app runs | `lambda-web-error-type: Platform.HeaderTooLarge`. No invocation and no application log entry |
| More than **1,000 header lines** | The Node.js server in your function, while parsing | `lambda-web-request-id` and `lambda-web-logstream` are present, `lambda-web-error-type` is **not**. Your handler does not run |

The byte limit cannot be raised and is measured on the request head as the client sends it —
request line, every header line, and the line terminators. Headers the platform adds do not count
toward it.

The line count is the opposite: it *includes* the headers the platform adds, so a client sending
slightly under 1,000 lines can still trip it. It is also raisable from your own code, because it is
a Node.js default rather than a platform quota:

```javascript
const server = http.createServer(handler);
server.maxHeadersCount = 2000;  // or 0 to disable the count check entirely
server.listen(port, host);
```

- **The count is of header lines, not distinct names.** Repeated headers each count, so a request
  accumulating `set-cookie` or `x-forwarded-for` through several proxies can reach the ceiling
  without any single header looking unusual.

If a client is anywhere near either bound, measure against the endpoint you are deploying to rather
than assuming the maximum is available.

**The size limit cannot be raised from application code.** `--max-http-header-size` does not help,
because an over-128-KiB request is rejected before it reaches your process: no invocation and no
application log line. The managed runtimes already set the Node.js header *size* limit to match the
platform's, so there is nothing to tune there. Confirm with the log check below rather than assuming
a runtime flag took effect.

```bash
# Confirm an over-limit request never reaches the app.
# Send one normal request and one over-limit request, then count logged requests.
aws logs filter-log-events --log-group-name /aws/lambda/web/{name} \
  --region {home-region} --start-time {epoch-ms} --filter-pattern '"GET /"' \
  --query 'length(events)'
```

The fix is on the client side: shrink the request. Move bulk state out of headers and into the
request body, trim cookies, and collapse redundant proxy and tracing headers before the request
reaches the endpoint. If a CloudFront distribution sits in front, drop headers you do not need in
the origin request policy rather than forwarding everything.

## Network connector issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Revision is `Active` but private resources are unreachable | The serving revision has no `egressNetworkConnectorArn`; `aws lambda-web deploy` carries an existing one forward but has no option to set one | Read the field with `get-web-function-revision`; create a revision that carries it with `create-web-function-revision` |
| Public API calls time out after moving to a connector | No NAT route in the connector's subnets | Add a `0.0.0.0/0` route to a NAT gateway |
| HTTP 502 `Platform.InvalidNetworkConfiguration` | Serving revision references a deleted connector | Shift traffic to a working revision |
| `ValidationException` ... "A version qualifier is required" | Unqualified connector ARN | Use `LatestVersionArn` from `aws lambda-core get-network-connector` |

Full table, including connector creation errors: [networking.md](references/networking.md).

## Debug Steps

1. **Run locally**: `node index.js` then `curl localhost:3000/`
2. **Check ZIP**: `unzip -l function.zip` — `index.js` + node_modules present?
3. **Check role**: Trust policy has `lambda.amazonaws.com`?
4. **Check S3**: `aws s3 ls s3://{bucket}/{key}` — ZIP exists?
5. **Check endpoint**: `aws lambda-web get-web-function-endpoint --function-name {name} --endpoint-name default --region {r}`
6. **Check logs**: `aws logs tail /aws/lambda/web/{name} --region {home-region}`
7. **Check revision**: `aws lambda-web get-web-function-revision --function-name {name} --revision-id {rev} --region {r}`
