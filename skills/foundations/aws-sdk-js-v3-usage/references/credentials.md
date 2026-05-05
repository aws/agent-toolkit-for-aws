# Credentials Reference

All providers from `@aws-sdk/credential-providers`.

## Provider Quick Reference

| Provider | Use case |
|---|---|
| `fromNodeProviderChain()` | Default Node.js chain (env → ini → IMDS/ECS) |
| `fromEnv()` | `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` env vars |
| `fromIni()` | `~/.aws/credentials` / `~/.aws/config` profiles |
| `fromTemporaryCredentials()` | STS AssumeRole |
| `fromWebToken()` | STS AssumeRoleWithWebIdentity (OIDC) |
| `fromTokenFile()` | OIDC token file (EKS IRSA) — reads `AWS_WEB_IDENTITY_TOKEN_FILE` + `AWS_ROLE_ARN` |
| `fromSSO()` | AWS IAM Identity Center (SSO) |
| `fromCognitoIdentityPool()` | Browser/mobile — Cognito Identity Pool |
| `fromInstanceMetadata()` | EC2 instance profile (IMDSv1/v2) |
| `fromContainerMetadata()` | ECS task role |
| `fromHttp()` | Custom HTTP credential endpoint |
| `createCredentialChain()` | Custom fallback chain |

## Assume Role (STS)

```js
import { fromTemporaryCredentials } from "@aws-sdk/credential-providers";

const client = new S3Client({
  credentials: fromTemporaryCredentials({
    params: {
      RoleArn: "arn:aws:iam::123456789012:role/MyRole",
      RoleSessionName: "my-session", // optional, auto-generated if omitted
      DurationSeconds: 3600,         // optional
    },
    // clientConfig: { region: "us-east-1" } // override STS region if needed
  }),
});
```

Chained role assumption:

```js
credentials: fromTemporaryCredentials({
  masterCredentials: fromTemporaryCredentials({
    params: { RoleArn: "arn:aws:iam::123456789012:role/RoleA" },
  }),
  params: { RoleArn: "arn:aws:iam::123456789012:role/RoleB" },
})
```

## Named Profile

```js
// Simplest — sets profile for both client config and credentials
const client = new S3Client({ profile: "my-profile" });

// Explicit — credentials only
import { fromIni } from "@aws-sdk/credential-providers";
const client = new S3Client({ credentials: fromIni({ profile: "my-profile" }) });
```

## Web Identity / OIDC (fromWebToken)

```js
import { fromWebToken } from "@aws-sdk/credential-providers";

const client = new S3Client({
  credentials: fromWebToken({
    roleArn: "arn:aws:iam::123456789012:role/MyRole",
    webIdentityToken: await getTokenFromIdP(),
    roleSessionName: "session",  // optional
  }),
});
```

## Cognito Identity Pool (browser/mobile)

```js
import { fromCognitoIdentityPool } from "@aws-sdk/credential-providers";

const client = new S3Client({
  region: "us-east-1",
  credentials: fromCognitoIdentityPool({
    identityPoolId: "us-east-1:1699ebc0-7900-4099-b910-2df94f52a030",
    logins: { "accounts.google.com": googleIdToken }, // optional, for authenticated identities
  }),
});
```

## Custom Chain

```js
import { createCredentialChain, fromEnv, fromIni } from "@aws-sdk/credential-providers";

const client = new S3Client({
  credentials: createCredentialChain(fromEnv(), fromIni({ profile: "fallback" })),
});
```

## STS Region Priority

When a credential provider uses STS internally, region is resolved in this order:

1. `clientConfig.region` passed to the provider
2. Profile region — if resolving from config file, this beats `AWS_REGION`
3. Outer client's region
4. `AWS_REGION` env var
5. Profile region — if *not* resolving from config file, this is lower than `AWS_REGION`
6. `us-east-1` fallback

To pin the STS region explicitly:

```js
fromTemporaryCredentials({
  params: { RoleArn: "..." },
  clientConfig: { region: "us-east-1" },
})
```
