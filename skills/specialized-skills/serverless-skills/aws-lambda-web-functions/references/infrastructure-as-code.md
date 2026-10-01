# Infrastructure as Code (CloudFormation and CDK)

The AWS CLI (`aws lambda-web`) is the quickest path — see [deployment.md](deployment.md) and the CLI section of `SKILL.md`. Use CloudFormation when you want infrastructure-as-code (IaC): repeatable deployments, rollback support, and resources managed as a stack.

Load this file only when the user asks about CloudFormation or infrastructure-as-code for Lambda Web Functions.

**Check the current documentation before creating any CDK or SAM code:** the [AWS SAM resource reference](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-specification-resources-and-properties.html) and the [AWS CDK API reference](https://docs.aws.amazon.com/cdk/api/v2/). The CloudFormation resources below are what both compile down to.

## CloudFormation

Three resources: the function, an immutable revision (code + config), and an HTTPS endpoint weighted to that revision.

```yaml
Resources:
  WebFunction:                       # just the name
    Type: AWS::Lambda::WebFunction
    Properties:
      FunctionName: {name}

  WebFunctionRevision:               # immutable code + config
    Type: AWS::Lambda::WebFunctionRevision
    DependsOn: WebFunction
    Properties:
      FunctionName: {name}
      BuildConfig:
        CodeConfig:
          S3Object:
            Bucket: {bucket}
            Key: "{name}/function.zip"
            # VersionId: {version}   # optional; use it to pick up a new upload under the same key
        RuntimeConfig:
          Runtime: {runtime}
      ServiceConfig:
        ExecutionRoleArn: !GetAtt WebFunctionRole.Arn
        TimeoutSeconds: 30

  WebFunctionEndpoint:               # HTTPS endpoint, weighted to a revision
    Type: AWS::Lambda::WebFunctionEndpoint
    DependsOn: [WebFunction, WebFunctionRevision]
    Properties:
      FunctionName: {name}
      EndpointName: default
      EndpointType: HomeRegion
      AuthType: IamAuth              # SigV4 callers only; ApplicationManaged = PUBLIC, app owns auth
      RevisionWeights:
        - RevisionId: !GetAtt WebFunctionRevision.RevisionId
          Weight: 100

Outputs:
  EndpointDomainName:
    Value: !GetAtt WebFunctionEndpoint.DomainName
```

`{runtime}` is the Node.js runtime named in `SKILL.md`. For an existing function, read the current
value from `buildConfig.runtimeConfig.runtime` with `aws lambda-web get-web-function-revision`.

You must create the execution role yourself (trust `lambda.amazonaws.com`, attach `AWSLambdaBasicExecutionRole` for CloudWatch Logs) — see [iam-and-security.md](iam-and-security.md).

## CDK

There is no L2 construct for Web Functions. If your `aws-cdk-lib` has no generated L1
(`CfnWebFunction`), declare the three resources with the escape hatch, `CfnResource`, which takes the
same property names as the YAML above:

```ts
const fn = new cdk.CfnResource(this, 'WebFunction', {
  type: 'AWS::Lambda::WebFunction',
  properties: { FunctionName: name },
});

const rev = new cdk.CfnResource(this, 'WebFunctionRevision', {
  type: 'AWS::Lambda::WebFunctionRevision',
  properties: {
    FunctionName: name,                        // the bare name, never getAtt('FunctionArn')
    BuildConfig: {
      CodeConfig: { S3Object: { Bucket: bucket, Key: key } },
      RuntimeConfig: { Runtime: runtime },
    },
    ServiceConfig: {
      ExecutionRoleArn: role.roleArn,
    },
  },
});
rev.addDependency(fn);
```

Two CDK-specific points:

- **A bare name creates no reference, so ordering is yours to declare.** In YAML that is `DependsOn`;
  in CDK it is `addDependency`. Without it the revision is created in parallel with the function and
  fails with `ResourceNotFoundException`, `The function ... does not exist`.
- **`cdk synth` and `cdk deploy` can print warnings that do not mean the template is wrong.**
  `Unknown resource type 'AWS::Lambda::WebFunction' (CloudFormation Validate)` appears when the
  installed `aws-cdk-lib` does not know the type; the deploy still succeeds. Check the schema with
  `aws cloudformation describe-type` rather than trusting the validator.

## S3 Code Bucket

Upload the zip, including `node_modules`, before deploying — nothing packages the code for you.

```bash
zip -r function.zip index.js package.json node_modules/
aws s3 cp function.zip s3://{bucket}/{name}/function.zip --region {region}
```

- Versioning must be enabled (required by `AWS::Lambda::WebFunctionRevision`).
- The code artifact is encrypted at rest by default (SSE-S3); for a customer-managed key, see
  [getting-started.md](getting-started.md). The function's log group is not encrypted with
  your own KMS key by default; to associate one, see [observability.md](observability.md).
- Bucket policy must grant Lambda read access:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": ["s3:GetObject", "s3:GetObjectVersion"],
    "Resource": "arn:aws:s3:::{bucket}/*",
    "Condition": {
      "StringEquals": {"aws:SourceAccount": "{account-id}"},
      "ArnLike": {"aws:SourceArn": "arn:aws:lambda:{region}:{account-id}:web-function/*"}
    }
  }, {
    "Effect": "Deny",
    "Principal": "*",
    "Action": "s3:*",
    "Resource": ["arn:aws:s3:::{bucket}", "arn:aws:s3:::{bucket}/*"],
    "Condition": {"Bool": {"aws:SecureTransport": "false"}}
  }]
}
```

`aws:SourceArn` must end in `/*`: the source ARN is under the revision, not the function itself, so the
bare function ARN matches nothing and the read is refused.

## Gotchas

- **Use `DependsOn`**. Without it Cfn could try to create revision or endpoint before the function exists.
- **A code change needs a new S3 key or version.** Re-uploading over the same key reports "No changes to deploy". Use a new key (`function-v2.zip`) or set `S3Object.VersionId`.
- **`RevisionWeights` is always required** on the endpoint, even for a single revision.
- **`FunctionName` must be the bare function name on every resource — never the function ARN.**
  An ARN is accepted at create time and the resources come up, then the endpoint's `DomainName`
  attribute cannot be read: `Property '/FunctionName' has value '{arn}' in the resource model but
  '{name}' in the ARN`. That fails the stack, and the rollback fails the same way on the revision,
  leaving `ROLLBACK_FAILED`. Recovery takes two calls, because retention is rejected until a delete
  has already failed: `delete-stack` to reach `DELETE_FAILED`, then
  `delete-stack --retain-resources WebFunctionRevision`. `!GetAtt WebFunctionRevision.RevisionId` on
  the endpoint is fine — the restriction is on `FunctionName`.

## Verify a Stack Deploy

```bash
# Get the endpoint domain from stack outputs, then curl it
ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name {stack-name} --region {region} \
  --query "Stacks[0].Outputs[?OutputKey=='EndpointDomainName'].OutputValue" --output text)

curl https://$ENDPOINT/
```

### Cleanup

```bash
aws cloudformation delete-stack --stack-name {stack-name} --region {region}
```
