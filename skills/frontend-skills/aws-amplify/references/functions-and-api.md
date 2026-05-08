# Functions & API

> **Prerequisites:** Backend defined in `amplify/backend.ts` with `defineBackend({ auth, data })`.

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

### Sharing Code Between Functions

Each Lambda function is bundled independently from its own directory. Importing from a shared directory (`amplify/shared/utils.ts`) fails at build time.

**Options:**

1. **Duplicate** the shared code in each function directory
2. **Symlink:** `ln -s ../../shared/utils.ts amplify/functions/my-fn/utils.ts`
3. **Package:** Create a local npm package and install it in each function's `package.json`

## Handler Return Types

| Handler Type | Import | Returns |
|-------------|--------|---------|
| `S3Handler` | `@types/aws-lambda` | `void` — async event, no response expected |
| `APIGatewayProxyHandler` | `@types/aws-lambda` | `{ statusCode, headers?, body }` |
| `APIGatewayProxyHandlerV2` | `@types/aws-lambda` | `{ statusCode, headers?, body }` |

> **Common mistake:** Writing an S3 handler like an API handler. S3Handler returns `void`, not a response object.

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

Set secrets via CLI: `echo -n "<value>" | npx ampx sandbox secret set MY_API_KEY`.

> **Important:** Use `echo -n` (no trailing newline) when piping values to `secret set`.
>
> **Important:** The `ampx sandbox secret set` command is for **local/sandbox development only**. For apps deployed to **Amplify Hosting**, secrets must be created via the Amplify console (NOT `ampx sandbox secret` — that's local only) — sandbox secrets are NOT available in hosted environments. See: https://docs.amplify.aws/react/deploy-and-host/fullstack-branching/secrets-and-vars/#set-secrets

### Environment Variables in Lambda

**Recommended (type-safe):**

```typescript
import { env } from '$amplify/env/my-function';
const tableName = env.TABLE_NAME;
```

**Fallback (if `$amplify/env` causes esbuild bundling errors):**

```typescript
const tableName = process.env.TABLE_NAME!;
```

## Scheduled Functions

Use `schedule` to invoke a function on a cron or natural-language schedule:

```typescript
import { defineFunction } from '@aws-amplify/backend';

export const cronJob = defineFunction({
  name: 'cron-job',
  entry: './handler.ts',
  schedule: 'every 1h', // natural-language shorthand
  // Valid shorthands: 'every 5m', 'every 1h', 'every day', 'every week', 'every month', 'every year'
  // OR: schedule: '0 */1 * * ? *', // cron expression — same property
});
```

The handler must use `EventBridgeHandler` type:

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

### Lambda + API Gateway + Data Access

When a Lambda both accesses data tables AND is exposed via API Gateway, use `resourceGroupName` to avoid circular dependencies:

```typescript
export const myFunction = defineFunction({
  name: 'my-function',
  resourceGroupName: 'data', // Places in data stack to avoid circular dep
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

> **How `.handler()` works:** `.handler()` grants AppSync the permission to **invoke** the Lambda (AppSync→Lambda). The Lambda IS the resolver — it receives the GraphQL event directly. If the Lambda also needs to call the Data API or access DynamoDB tables for side effects, add `allow.resource(fn)` to the model with `resourceGroupName: 'data'` on the function to avoid circular dependencies.
>
> ```typescript
> // ❌ CIRCULAR DEPENDENCY — manual table grant in backend.ts
> backend.data.resources.tables["Model"].grantReadData(backend.myFn.resources.lambda);
>
> // ✅ Use resourceGroupName to co-locate the function in the data stack
> const myFn = defineFunction({ name: 'my-fn', resourceGroupName: 'data' });
> // Then in the schema: allow.resource(myFn) on the model
> ```
>
> **Gap:** The Lambda resolver receives the GraphQL event but does NOT automatically get `TABLE_NAME` as an environment variable. Your Lambda must either:
>
> 1. Use the Amplify data client (`generateClient()`) which discovers tables automatically
> 2. Explicitly set env vars: `myFunction.addEnvironment('TABLE_NAME', backend.data.resources.tables['Todo'].tableName)`
>
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

The handler must use `APIGatewayProxyHandler` type for REST API (v1):

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

The handler must use `APIGatewayProxyHandlerV2` type for HTTP API (v2).

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
- **Secrets in plain `environment`:** Sensitive values must use
  `secret()`, not string literals.
- **`createStack` name collision:** Stack names passed to
  `backend.createStack()` must be unique across the backend.
  Duplicate names cause deployment failures.
- **Missing `@types/node`:** Lambda functions require `@types/node` in devDependencies. Without it, `process.env` and Node.js globals cause TypeScript errors. Install: `npm install --save-dev @types/node`
- **`@types/aws-lambda`:** Lambda handlers (`S3Handler`, `PreSignUpTriggerHandler`, etc.) need this package for TypeScript types. Install at project root or in the function's directory if it has its own `package.json`.
- **AppSync identity typing:** `event.identity` in custom handlers has varying types depending on auth mode. Use type assertion:

  ```typescript
  const identity = event.identity as { username?: string; sub?: string };
  const userId = identity?.username || identity?.sub || 'unknown';
  ```

- **`dataSource: 'NONE'`:** Using `a.handler.custom({ dataSource: 'NONE' })` causes "Data source not found" during deployment. Use a Lambda handler instead, or create the NONE data source explicitly via CDK.

- **Lambda error types lost:** Custom error classes thrown in Lambda arrive at the frontend as generic `Error` with only the `message` preserved. Error name, stack, and custom properties are stripped by AppSync. Return structured error data in the response instead.

## Links

- [Functions Overview](https://docs.amplify.aws/react/build-a-backend/functions/)
- [Set Up Function](https://docs.amplify.aws/react/build-a-backend/functions/set-up-function/)
- [Environment Variables and Secrets](https://docs.amplify.aws/react/build-a-backend/functions/environment-variables-and-secrets/)
- [Grant Access to Other Resources](https://docs.amplify.aws/react/build-a-backend/functions/grant-access-to-other-resources/)
- [Add custom queries and mutations](https://docs.amplify.aws/react/build-a-backend/data/custom-business-logic/)
- [Connect to Existing Data Sources](https://docs.amplify.aws/react/build-a-backend/data/connect-to-existing-data-sources/)
