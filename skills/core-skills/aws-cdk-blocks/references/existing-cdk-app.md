# Add CDK Blocks to an existing AWS CDK app

Contents: [Steps](#steps), [Reach the team's AWS resources from the backend](#reach-the-teams-aws-resources-from-the-backend), [Errors](#errors).

For a repository that already has `cdk.json` and stacks deployed with `cdk deploy`. Embed a CDK Blocks backend in one of those stacks with `BlocksBackend`: it adds the backend's Lambda function, an API Gateway REST API, an IAM role and their supporting resources (a configuration bucket and its helpers) to that stack, and the team keeps its own deploy command. `BlocksStack` takes the same props and is a stack of its own; use it only when the user asks for a separate stack.

Do not run the app scaffolder in the CDK app's root. It keeps the existing `cdk.json`, adds a separate `BlocksStack` app beside it, and adds a `deploy` task that runs `cdk deploy --all` on the team's app.

Check first, and ask the user before changing either:

- The CDK app is an ES module (`"type": "module"`) started with `tsx`. The steps need top-level `await`.
- The stack name does not start with `aws`. Synth fails on such a name.

## Steps

1. Install the packages:

   ```bash
   npm install aws-cdk-blocks zod
   npm install -D tsx esbuild
   ```

2. In `cdk.json`, start the app with the `cdk` condition and keep the team's entry path: `"app": "npx tsx -C cdk bin/app.ts"`. Without it synth stops with `Missing --conditions=cdk`.

3. Create `cdk-blocks/` beside the root `package.json` with the backend and its handler:

   ```ts
   // cdk-blocks/index.ts
   import { ApiNamespace, Scope } from 'aws-cdk-blocks';
   const scope = new Scope('my-app');
   export const api = new ApiNamespace(scope, 'api', () => ({
     // Public as written. Require a session on every method that is not meant to be public: see security.md.
     async health() { return { ok: true }; },
   }));
   ```

   ```ts
   // cdk-blocks/index.handler.ts
   import { createLambdaHandler } from 'aws-cdk-blocks/lambda-handler';
   export const handler = createLambdaHandler(() => import('./index.js'));
   ```

4. `BlocksBackend.create()` is async, because it imports `cdk-blocks/index.ts` during synth, so it cannot run in a constructor. Add an async factory to the team's stack class:

   ```ts
   import { dirname, join } from 'node:path';
   import { fileURLToPath } from 'node:url';
   import { BlocksBackend, BlocksPresets } from 'aws-cdk-blocks/cdk';

   const __dirname = dirname(fileURLToPath(import.meta.url)); // an ES module has none

   static async build(scope: cdk.App, id: string, props?: cdk.StackProps) {
     const stack = new MyExistingStack(scope, id, props);
     const blocks = await BlocksBackend.create(stack, 'BlocksApi', {
       backendHandlerPath: join(__dirname, '../cdk-blocks/index.handler.ts'),
       backendCDKPath: join(__dirname, '../cdk-blocks/index.ts'),
       defaults: BlocksPresets.production,
     });
     new cdk.CfnOutput(stack, 'ApiUrl', { value: blocks.publicApiUrl });
     return stack;
   }
   ```

   In the app entry, replace `new MyExistingStack(app, 'Name')` with `await MyExistingStack.build(app, 'Name')`. Every prop shown is required. `BlocksPresets.production` retains data and turns on deletion protection; `BlocksPresets.sandbox` deletes data with the stack. Confirm the choice with the user.

5. Add the local tasks to the root `package.json`, under another script name if one is taken:

   ```json
   "blocks": { "dev": { "frontend": false } },
   "scripts": {
     "dev": "node --input-type=module -e \"import 'aws-cdk-blocks/run'\" -- dev",
     "dev:stop": "node --input-type=module -e \"import 'aws-cdk-blocks/run'\" -- dev stop",
     "docs": "node --input-type=module -e \"import 'aws-cdk-blocks/run'\" -- docs",
     "vendorize": "node --input-type=module -e \"import 'aws-cdk-blocks/run'\" -- vendorize"
   }
   ```

   `npm run dev` serves the backend at `http://localhost:3000/cdk-blocks/api` with the local implementation of every Block. It needs no AWS credentials and does not synthesize the stack.

6. Verify with `npx cdk synth --quiet`, then `npx cdk diff <StackName>`.

7. Deploy with the team's own command. Ask the user first: show the diff, name the account and Region, and wait for approval. Never run `cdk bootstrap` unasked. Do not use the CDK Blocks `deploy` or `sandbox` tasks in this setup.

## Reach the team's AWS resources from the backend

Take the first row that fits.

| Situation | Do this |
|---|---|
| A Block has `fromExisting` for the resource: check `npm run -s docs <Block> -- --output text` | Wrap the resource. The Block gives a typed API, local data under `npm run dev`, and its own IAM grant. |
| No Block, one call site | Grant access and pass configuration from the stack, then call the AWS SDK in the backend. |
| No Block, several call sites, or local behavior is needed | Write a custom Block: [custom-block.md](custom-block.md). |
| A Block exists but its infrastructure must change | Last resort: `npm run vendorize -- <Block>` copies the Block's source into the app, which then owns it. Never modify a Block's resources from outside it. |

Wrap an existing DynamoDB table, in `cdk-blocks/index.ts`:

```ts
import { KVStore } from 'aws-cdk-blocks';
import { z } from 'zod';

const orders = new KVStore(scope, 'orders', {
  schema: z.object({ customerId: z.string(), orderId: z.string(), total: z.number() }),
  key: { partitionKey: 'customerId', sortKey: 'orderId' }, // must match the table's key schema
  table: KVStore.fromExisting(process.env.ORDERS_TABLE!),
});
```

In the stack, set `process.env.ORDERS_TABLE` to the table name before `BlocksBackend.create()`, and call `registerConfig(blocks, 'ORDERS_TABLE', '<table name>')` after it (`registerConfig` comes from `aws-cdk-blocks/cdk`). The name is a plain string, not a CDK token, and the table is in the same account. The Block never changes the table, its indexes or its TTL setting.

Use a resource that has no Block:

```ts
// In the stack, after create()
queue.grantSendMessages(blocks.executionRole);
registerConfig(blocks, 'WORK_QUEUE_URL', queue.queueUrl); // names and URLs only, never secrets

// In cdk-blocks/index.ts: read process.env.WORK_QUEUE_URL and call the AWS SDK
const IS_DEPLOYED = !!process.env.AWS_LAMBDA_FUNCTION_NAME; // false under `npm run dev`
```

`npm run dev` does not replace these SDK calls. Guard them with `IS_DEPLOYED`, or they reach AWS from the developer's machine.

## Errors

| Message contains | Cause |
|---|---|
| `Missing --conditions=cdk` | Step 2 is missing |
| ``requires a `defaults` field`` | `defaults` is missing in step 4 |
| `access .gateway/.apiUrl after BlocksBackend.create() resolves` | Code in `cdk-blocks/index.ts` read the backend's API URL while it was being imported. Read it in the stack, after `await BlocksBackend.create()` |
| `starts with 'aws'` | Rename the stack; ask the user first, because a renamed stack is a different stack |
