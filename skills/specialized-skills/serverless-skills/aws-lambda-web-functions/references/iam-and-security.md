# IAM and Security

## Execution Role

Trust policy principal: `lambda.amazonaws.com`

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
```

Attach policies for the services your app accesses (DynamoDB, S3, etc). Grant **least privilege** — scope to the specific actions and resource ARNs the app needs.

## Deployer IAM Policy

Actions use the `lambda:` prefix. Resource ARN: `arn:aws:lambda:{region}:{account}:web-function/{name}`

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "lambda:CreateWebFunction",
        "lambda:GetWebFunction",
        "lambda:DeleteWebFunction",
        "lambda:CreateWebFunctionRevision",
        "lambda:GetWebFunctionRevision",
        "lambda:ListWebFunctionRevisions",
        "lambda:DeleteWebFunctionRevision",
        "lambda:CreateWebFunctionEndpoint",
        "lambda:GetWebFunctionEndpoint",
        "lambda:ListWebFunctionEndpoints",
        "lambda:UpdateWebFunctionEndpoint",
        "lambda:DeleteWebFunctionEndpoint"
      ],
      "Resource": [
        "arn:aws:lambda:{region}:{account}:web-function/{name}",
        "arn:aws:lambda:{region}:{account}:web-function/{name}/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion"],
      "Resource": "arn:aws:s3:::{bucket}/*"
    },
    {
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::{account}:role/{name}-web-role",
      "Condition": {
        "StringEquals": {"iam:PassedToService": "lambda.amazonaws.com"}
      }
    }
  ]
}
```

Keep the `/{name}/*` entry alongside the base ARN: endpoint and revision operations target
sub-resource ARNs, not the top-level web-function ARN.

## Auth Types

`authType` decides who can reach the endpoint at the network layer. **Choose it deliberately — ask the user before deploying.**

| Type | Exposure | What it means |
|------|----------|---------------|
| `ApplicationManaged` | **Public — anyone on the internet with the URL.** No AWS-layer auth. | Your **app** is solely responsible for authentication/authorization (JWT, cookies, sessions, API keys). The `Authorization` header is passed through to your code. |
| `IamAuth` | Private — only callers with valid IAM credentials. | Callers must sign requests with SigV4. The `Authorization` header is stripped after validation.|

There is no `NONE` / unauthenticated-but-not-app-managed option, and there is no built-in WAF. `ApplicationManaged` does **not** mean "no security needed" — it means the security is entirely yours to implement.

## Security Considerations

Web Functions endpoints are **public by default** (`ApplicationManaged`). Treat every public endpoint as internet-exposed and design accordingly.

- **The URL is not a secret.** Anyone who learns it can send requests. Do not rely on an unguessable domain as an access control.
- **App-owned auth.** For `ApplicationManaged`, implement authentication and authorization in the app (validate a JWT / session / API key on every protected route).
- **Input validation.** Validate and sanitize all request input (path, query, headers, body) — you're taking raw internet traffic. Guard against injection, oversized payloads, and malformed input.
- **Rate limiting / abuse protection.** Set `throttleConfig.rateLimit` on the endpoint to cap requests per second, and cap `scalingConfig.maxEnvironments` to bound blast radius. That throttle is endpoint-wide, not per-client, so per-client quotas still belong in the app.
- **L7 protection (DDoS / bots / WAF).** No built-in WAF. For public-facing apps that need L7 DDoS/bot protection, place your own CloudFront distribution (with AWS WAF) in front of the endpoint.
- **Security headers.** For browser-facing responses, set standard headers — `Content-Security-Policy`, `Strict-Transport-Security` (HSTS), `X-Frame-Options`, `X-Content-Type-Options`. Use a middleware like `helmet` for Express/Fastify rather than setting them by hand.
- **Enforce TLS on the code bucket.** For production, add a `Deny` statement on `s3:*` for both the bucket and its objects conditioned on `aws:SecureTransport` being `false`, so artifacts cannot be fetched over plain HTTP.

Further reading: [Lambda security best practices](https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html)
and the [Well-Architected Security Pillar](https://docs.aws.amazon.com/wellarchitected/latest/security-pillar/).
