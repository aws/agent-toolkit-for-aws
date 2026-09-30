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
| Static files 404 | Wrong path or not in ZIP | Use `__dirname` relative paths; check `unzip -l` |
| Module not found | node_modules missing from ZIP | `npm ci --omit=dev` then include in zip |
| HTTP 507, or `EMFILE` / `too many open files` in logs | File-descriptor ceiling reached — often unclosed sockets, file handles or DB connections leaking across concurrent requests | Close handles per request and pool connections; a leak surfaces faster here because one execution environment serves many concurrent requests |
| Connection reset with no HTTP status and nothing in the logs | Request header block too large in bytes — rejected before the app, so no status code and no log line | Measure total header size; shrink cookies, tokens and proxy headers → [Request header limits](#request-header-limits) |
| HTTP 431 | Too many request header lines, including the ones the platform adds | Leave headroom below the documented ceiling → [Request header limits](#request-header-limits) |
| ESM errors | Missing type:module | Add `"type": "module"` to package.json |

## Request header limits

A request's headers are bounded two ways, by **how many** header lines it carries and by **how
many bytes** they total. Both are enforced before your app sees the request, and they fail very
differently. Check Service Quotas or the current documentation for the numbers; what follows is how
to recognise and fix each one.

| Exceeded | Result | What the caller sees |
|----------|--------|----------------------|
| Too many header lines | HTTP **431 Request Header Fields Too Large** | A normal HTTP error response |
| Header block too large in bytes | **Connection dropped. No HTTP response at all** | A transport error (`ECONNRESET`, `curl` exit 55, "connection reset by peer") |

The byte case is the harder of the two to diagnose. There is no status code to look up and nothing in
the application logs, so it reads as a network fault or a broken service rather than a client error
that will never succeed. Retrying does not help. If a caller reports intermittent connection resets
and the requests carry large cookies, a long `Authorization` bearer token, or a wide chain of
`x-forwarded-*` and tracing headers, measure the total header block first.

Two things make both ceilings bite sooner than a bare quota reading suggests:

- **The platform's own headers count against the same budget.** A request does not get the whole
  documented allowance to itself, so leave headroom rather than sizing right at the limit.
- **The count is of header lines, not distinct names.** Repeated headers each count, so a request
  accumulating `set-cookie` or `x-forwarded-for` through several proxies can reach the ceiling
  without any single header looking unusual.

If a client is anywhere near either bound, measure against the endpoint you are deploying to rather
than assuming the maximum is available.

**Neither limit can be raised from application code.** `server.maxHeadersCount` and
`--max-http-header-size` do not help, because the request is rejected before it reaches your
process: an over-limit request produces no application log line and no invocation. Confirm that
with the log check below rather than assuming a runtime flag took effect.

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

## Debug Steps

1. **Run locally**: `node index.js` then `curl localhost:3000/`
2. **Check ZIP**: `unzip -l function.zip` — `index.js` + node_modules present?
3. **Check role**: Trust policy has `lambda.amazonaws.com`?
4. **Check S3**: `aws s3 ls s3://{bucket}/{key}` — ZIP exists?
5. **Check endpoint**: `aws lambda-web get-web-function-endpoint --function-name {name} --endpoint-name default --region {r}`
6. **Check logs**: `aws logs tail /aws/lambda/web/{name} --region {home-region}`
7. **Check revision**: `aws lambda-web get-web-function-revision --function-name {name} --revision-id {rev} --region {r}`
