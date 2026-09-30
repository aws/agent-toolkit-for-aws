# Getting Started

## 1. Prerequisites

```bash
aws lambda-web help               # not recognised? update the AWS CLI (see deployment.md)
node --version              # match the runtime; confirm supported runtimes with `aws lambda-web help` or the AWS docs
```

Create S3 bucket with versioning and Lambda access:

```bash
aws s3 mb s3://{bucket} --region {region}
aws s3api put-bucket-versioning --bucket {bucket} \
  --versioning-configuration Status=Enabled --region {region}
aws s3api put-bucket-policy --bucket {bucket} --policy '{
  "Version": "2012-10-17",
  "Statement": [{"Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": ["s3:GetObject", "s3:GetObjectVersion"],
    "Resource": "arn:aws:s3:::{bucket}/*",
    "Condition": {
      "StringEquals": {"aws:SourceAccount": "{account-id}"},
      "ArnLike": {"aws:SourceArn": "arn:aws:lambda:{region}:{account-id}:web-function/*"}}},
   {"Effect": "Deny", "Principal": "*", "Action": "s3:*",
    "Resource": ["arn:aws:s3:::{bucket}", "arn:aws:s3:::{bucket}/*"],
    "Condition": {"Bool": {"aws:SecureTransport": "false"}}}]
}'
```

S3 encrypts every new object at rest with SSE-S3 by default, so the code artifact is encrypted without an extra step. To encrypt the code artifact and environment variables with a customer-managed key instead, set `revisionConfig.kmsKeyArn` — see [deployment.md](deployment.md).

Create execution role:

```bash
aws iam create-role --role-name {name}-web-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"}]
  }'
# Logs only — this is all a basic web function needs at runtime:
aws iam attach-role-policy --role-name {name}-web-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

# Add LEAST-PRIVILEGE inline policies ONLY for the AWS services your app calls at runtime,
# scoped to specific resource ARNs. Example — read/write one DynamoDB table:
# aws iam put-role-policy --role-name {name}-web-role --policy-name app-access \
#   --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
#     "Action":["dynamodb:GetItem","dynamodb:PutItem"],
#     "Resource":"arn:aws:dynamodb:{region}:{account}:table/{name}-items"}]}'
```

## 2. Create Project

```bash
mkdir my-app && cd my-app
npm init -y && npm pkg set type=module
npm install express
```

## 3. Write App (index.js)

```javascript
import express from 'express';
const app = express();
app.get('/', (req, res) => res.send('Hello from Web Functions'));
const [HOST, PORT] = (process.env.AWS_LAMBDA_HTTP_ENDPOINT || '0.0.0.0:3000').split(':');
app.listen(PORT, HOST);
```

This starter deploys with `authType: ApplicationManaged` — public to anyone with the URL.
It has no auth, which is fine for a hello-world. Before exposing anything non-public,
implement auth in the app (see [iam-and-security.md](iam-and-security.md)) or use
`IamAuth`.

## 4. Test Locally

```bash
node index.js
curl http://localhost:3000/
```

## 5. Package and Deploy

```bash
npm ci --omit=dev
zip -r function.zip index.js package.json node_modules/
aws s3 cp function.zip s3://{bucket}/my-app/function.zip

aws lambda-web create-web-function \
  --function-name my-app \
  --revision-config '{"buildConfig":{"codeConfig":{"s3Object":{"bucket":"{bucket}","key":"my-app/function.zip"}},"runtimeConfig":{"runtime":"nodejs24.x"}},"serviceConfig":{"executionRoleArn":"arn:aws:iam::{account}:role/my-app-web-role"}}' \
  --endpoint-config '{"endpointName":"default","endpointType":"HomeRegion","authType":"ApplicationManaged","autoDeploymentMode":"LatestRevision"}' \
  --region {region}
```

## 6. Verify

```bash
# Get endpoint URL (wait for state: Active, ~5 min first time)
aws lambda-web get-web-function-endpoint --function-name my-app --endpoint-name default --region {region}
# curl the domainName from the response
```

## 7. Before Real Traffic

The steps above get a function serving. Before it takes real traffic, set up
observability: confirm a CloudTrail trail is enabled in the account so control-plane
calls (`CreateWebFunction`, `CreateWebFunctionRevision`, `UpdateWebFunctionEndpoint`,
`DeleteWebFunction`) are audited, and add a CloudWatch alarm on endpoint error rate so
regressions surface before a traffic shift. See
[observability.md](observability.md) for log configuration, alarms and multi-region
log centralization.

## One-command alternative: `aws lambda-web deploy`

`deploy` sets up the bucket, role and endpoint above for you. **Choose endpoint auth first.** `deploy` creates a public (`ApplicationManaged`) endpoint unless
you pass `--auth-type IamAuth`, and anyone with a public URL can call it. Ask the user which they
want before running either command below; see [iam-and-security.md](iam-and-security.md) for what a
public endpoint needs.

```bash
aws lambda-web help                                   # not recognised? update the AWS CLI (see deployment.md)
aws lambda-web deploy --name my-app --hello-world --auth-type IamAuth --region {region}    # internal (SigV4 callers only)
aws lambda-web deploy --name my-app --hello-world --region {region}                        # public, only if the user chose it
```

`--hello-world` writes a zero-dependency TypeScript HTTP server into `./my-app` (Node runs it
directly, with no build step), creates the function, a code bucket, an execution role and an
endpoint named `dev`, and prints the URL. Edit the code, then ship each change with:

```bash
cd my-app && aws lambda-web deploy --name my-app --code . --region {region}
```

For an app you already have, install its dependencies and deploy the directory; see
[deployment.md](deployment.md) for every flag:

```bash
npm ci --omit=dev
aws lambda-web deploy --name my-app --code . --create --auth-type {auth-type} --region {region}   # IamAuth or ApplicationManaged, as the user chose
```

## Common First-Deploy Issues

| Symptom | Fix |
|---------|-----|
| `aws lambda-web` not found | Update to the latest AWS CLI version (see deployment.md) |
| Stuck in Pending | Trust policy must be `lambda.amazonaws.com` |
| ParamValidation | Use camelCase: `buildConfig`, `codeConfig` |
| AuthType error | Use `ApplicationManaged` (not `NONE`) |
| 500 no logs | Entry point must be `index.js` (not `.mjs`) |
| 500 with ECONNREFUSED 3000 | Bind the host and port from `AWS_LAMBDA_HTTP_ENDPOINT` |
| 500 on create-revision | Caller needs `s3:GetObject` on code bucket |
