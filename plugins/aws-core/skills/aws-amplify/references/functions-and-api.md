# Functions & API

## Lambda Functions

Define a function in `amplify/functions/<name>/resource.ts`:

```typescript
import { defineFunction } from '@aws-amplify/backend';

export const myFunc = defineFunction({
  name: 'my-func',
  entry: './handler.ts',
  timeoutSeconds: 30, // default 3, max 900
  memoryMB: 512, // default 512
  runtime: 22, // Node.js version (18, 20, 22, 24); default 22
  environment: {
    TABLE_NAME: 'my-table',
    REGION: 'us-east-1',
  },
});
```

Create the handler at `amplify/functions/<name>/handler.ts`:

```typescript
import type { Handler } from 'aws-lambda';
import { env } from '$amplify/env/my-func';

export const handler: Handler = async (event) => {
  const table = env.TABLE_NAME; // typed, from defineFunction environment
  return { statusCode: 200, body: JSON.stringify({ table }) };
};
```

Import into `amplify/backend.ts`:

```typescript
import { defineBackend } from '@aws-amplify/backend';
import { auth } from './auth/resource';
import { myFunc } from './functions/my-func/resource';
defineBackend({ auth, myFunc });
```

## Environment Variables & Secrets

You **SHOULD** import environment variables from `$amplify/env/<function-name>`
— this provides **type-safe** access to values defined in `defineFunction`.
Values are also available at runtime via `process.env.VAR_NAME`, but the
`$amplify/env` import is preferred because it gives you compile-time type
checking and autocompletion.

For sensitive values, use `secret()`:

```typescript
import { defineFunction, secret } from '@aws-amplify/backend';

export const myFunc = defineFunction({
  name: 'my-func',
  entry: './handler.ts',
  environment: {
    API_KEY: secret('MY_API_KEY'),
  },
});
```

Set secrets via CLI: `echo "<value>" | npx ampx sandbox secret set MY_API_KEY`.

> **IMPORTANT:** The `ampx sandbox secret set` command is for **local/sandbox development only**. For apps deployed to **Amplify Hosting**, secrets **MUST** be created via the Hosting console or CLI — sandbox secrets are NOT available in hosted environments. See: https://docs.amplify.aws/react/deploy-and-host/fullstack-branching/secrets-and-vars/#set-secrets

## Scheduled Functions

Use `schedule` to invoke a function on a cron or natural-language schedule:

```typescript
import { defineFunction } from '@aws-amplify/backend';

export const cronJob = defineFunction({
  name: 'cron-job',
  entry: './handler.ts',
  schedule: 'every 1h', // natural-language shorthand
  // Valid shorthands: 'every 5m', 'every 1h', 'every 6h', 'every 1d'
  // OR: schedule: '0 */1 * * ? *', // cron expression — same property
});
```

The handler **MUST** use `EventBridgeHandler` type:

```typescript
import type { EventBridgeHandler } from 'aws-lambda';
export const handler: EventBridgeHandler<'Scheduled Event', void, void> = async () => {
  // scheduled logic
};
```

## Resource Access

Grant a function access to other Amplify resources:

```typescript
const backend = defineBackend({ auth, data, storage, myFunc });

// Grant function access to auth, data, and storage
backend.myFunc.resources.lambda.addEnvironment(
  'USER_POOL_ID', backend.auth.resources.userPool.userPoolId
);
backend.data.resources.tables['Todo'].grantReadData(backend.myFunc.resources.lambda);
backend.storage.resources.bucket.grantReadWrite(backend.myFunc.resources.lambda);
```

For data schema access, use `allow.resource()` in authorization rules:

```typescript
const schema = a.schema({
  Todo: a.model({
    content: a.string(),
  }).authorization(allow => [allow.resource(myFunc)]),
});
```

## Custom Queries and Mutations

Use `a.query()` and `a.mutation()` with `.handler()` to add custom server-side logic through AppSync (no API Gateway needed):

```typescript
// amplify/data/resource.ts
const schema = a.schema({
  // Custom query with Lambda handler
  summarize: a.query()
    .arguments({ text: a.string().required() })
    .returns(a.string())
    .handler(a.handler.function(summarizeHandler))
    .authorization(allow => [allow.authenticated()]),

  // Custom mutation with Lambda handler
  processOrder: a.mutation()
    .arguments({ orderId: a.string().required() })
    .returns(a.json())
    .handler(a.handler.function(processOrderHandler))
    .authorization(allow => [allow.authenticated()]),
});
```

> **When to use which:**
>
> - `a.query()` / `a.mutation()` with `.handler()` — AppSync-native, type-safe, uses the data schema. **Preferred for most custom logic.**
> - API Gateway + Lambda — Use when you need REST endpoints, webhooks, or third-party integrations that require a specific URL.

## REST API (API Gateway)

Create a REST API using CDK in `amplify/backend.ts`:

```typescript
import { defineBackend } from '@aws-amplify/backend';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import { myFunc } from './functions/my-func/resource';

const backend = defineBackend({ auth, myFunc });
const apiStack = backend.createStack('RestApiStack');

const api = new apigateway.RestApi(apiStack, 'MyRestApi', {
  restApiName: 'my-rest-api',
  deployOptions: { stageName: 'prod' },
});
api.root.addResource('items').addMethod(
  'GET', new apigateway.LambdaIntegration(backend.myFunc.resources.lambda)
);

backend.addOutput({ custom: { restApiUrl: api.url } });
```

The handler **MUST** use `APIGatewayProxyHandler` type for REST API (v1):

```typescript
import type { APIGatewayProxyHandler } from 'aws-lambda';
```

## HTTP API (API Gateway v2)

For a lightweight HTTP API:

```typescript
import type { APIGatewayProxyHandlerV2 } from 'aws-lambda';
import * as apigwv2 from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';

const httpApi = new apigwv2.HttpApi(apiStack, 'MyHttpApi', {
  corsPreflight: { allowOrigins: ['*'], allowMethods: [apigwv2.CorsHttpMethod.GET] },
});
httpApi.addRoutes({
  path: '/items',
  methods: [apigwv2.HttpMethod.GET],
  integration: new HttpLambdaIntegration('GetItems', backend.myFunc.resources.lambda),
});

backend.addOutput({ custom: { httpApiUrl: httpApi.url! } });
```

The handler **MUST** use `APIGatewayProxyHandlerV2` type for HTTP API (v2).

## Backend Outputs

Use `backend.addOutput()` to expose custom values to the frontend via
`amplify_outputs.json`:

```typescript
backend.addOutput({ custom: { apiUrl: api.url, region: 'us-east-1' } });
```

Frontend reads custom outputs from the configured Amplify outputs.

## Calling from Client

For custom queries and mutations defined via `a.query()` or `a.mutation()`, call them from the client:

```typescript
const { data } = await client.queries.summarize({ text: '...' });
```

For REST/HTTP API outputs added via `backend.addOutput()`, read the endpoint URL from `amplify_outputs.json` and use standard HTTP clients.

## Pitfalls

- **`runtime` must be an integer:** Use `runtime: 22`, NOT
  `runtime: "nodejs22.x"`. String format causes build errors.
- **Wrong handler type:** REST API (v1) requires `APIGatewayProxyHandler`
  with `event.httpMethod`; HTTP API (v2) requires `APIGatewayProxyHandlerV2`
  with `event.requestContext.http.method`. Mixing them causes malformed
  responses. Both return `{ statusCode, body }`.
- **Missing resource access:** A function without explicit grants cannot
  access auth, data, or storage resources — add grants in `backend.ts`.
- **Secrets in plain `environment`:** Sensitive values **MUST** use
  `secret()`, not string literals.
- **`createStack` name collision:** Stack names passed to
  `backend.createStack()` **MUST** be unique across the backend.
  Duplicate names cause deployment failures.

## Links

- [Functions Overview](https://docs.amplify.aws/react/build-a-backend/functions/)
- [Set Up Function](https://docs.amplify.aws/react/build-a-backend/functions/set-up-function/)
- [Environment Variables and Secrets](https://docs.amplify.aws/react/build-a-backend/functions/environment-variables-and-secrets/)
- [Grant Access to Other Resources](https://docs.amplify.aws/react/build-a-backend/functions/grant-access-to-other-resources/)
- [Add custom queries and mutations](https://docs.amplify.aws/react/build-a-backend/data/custom-business-logic/)
- [Connect to Existing Data Sources](https://docs.amplify.aws/react/build-a-backend/data/connect-to-existing-data-sources/)
