# Author a custom Block

Write a custom Block when no existing Block covers an AWS service the app needs, or when a team wants a Block of its own with its defaults built in. Check `npm run -s docs -- --output text` first: an existing Block, or `fromExisting` on one, is less to maintain.

## Scaffold

Run from the app's root with a PascalCase class name and no `BB` prefix:

```bash
npx --yes @aws-cdk-blocks/create-block SearchIndex --dry-run
npx --yes @aws-cdk-blocks/create-block SearchIndex --yes
```

- `--dry-run` prints `Block`, `Package`, `Mode`, `Target` and the planned files, and writes nothing. `--yes` skips the confirmation.
- `npm create @aws-cdk-blocks/block@latest <ClassName>` runs the same scaffolder, but `npm create` passes flags such as `--dry-run` to it only after `--`.
- `Mode: customer` applies when the root `package.json` has `workspaces`, as a CDK Blocks app does. The command creates `packages/bb-search-index`, adds it to the root `workspaces`, installs dependencies, then builds and tests the package.
- `Mode: external` applies anywhere else. The command creates a standalone `./bb-search-index` package to publish, and does not build or test it. Pass `--scope <npm-scope>`, then build and test it with `cd bb-search-index && npm run build && npm test`. An app uses it as a dependency, like any other package.
- The package name is on the `Package:` line. `--scope <npm-scope>` overrides its scope.
- The exit status is 0 even when a step fails. On `! npm install failed` or `! Verification failed` in customer mode, fix the cause and run `npm run build -w <package> && npm test -w <package>`.

## Fill in the skeleton

The generated Block has one placeholder method, `echo`, and `TODO` markers.

| File | Loaded | Write here |
|---|---|---|
| `src/types.ts`, `src/errors.ts` | everywhere | Option types and the error-name constants |
| `src/index.cdk.ts` | synth and deploy | CDK resources, IAM grants, configuration, a stub per runtime method |
| `src/index.aws.ts` | deployed runtime | The AWS SDK calls |
| `src/index.mock.ts` | `npm run dev` and tests | The same API on memory or disk, never AWS |
| `src/index.browser.ts` | browser bundles | Leave as generated |

- Give `index.mock.ts` and `index.aws.ts` the same class, methods, signatures, results and error names. Put input validation in one module and call it from both.
- Grant IAM only in `index.cdk.ts`, on the shared role, with the narrowest grant: `queue.grantSendMessages(this.executionRole)`. Add no `*` actions or resources.
- Name resources from `this.fullId`. Pass any other deploy-time value with `registerConfig(this, 'KEY', value)` in `index.cdk.ts` and read `process.env.KEY` in `index.aws.ts`. Never pass a secret this way.
- Return JSON-serializable values, and `null` for not-found. Throw `blocksError(<Class>Errors.<Name>, '<message>')`, with `blocksError` from `@aws-cdk-blocks/core`: only an error thrown this way keeps its name on the way to the caller, who matches it with `isBlocksError(e, <Class>Errors.<Name>)`.
- List the AWS SDK clients the Block uses in its own `dependencies`.

Fill in the remaining `TODO` markers and replace the placeholder tests. The app imports the Block's built output, so rebuild after every change:

```bash
npm run build -w <package> && npm test -w <package>
```

## Use it in the app

In `cdk-blocks/index.ts`, construct the Block and expose the methods clients may call:

```ts
import { ApiNamespace, Scope } from 'aws-cdk-blocks';
import { SearchIndex } from '<package>';

const scope = new Scope('my-app');
const search = new SearchIndex(scope, 'search');
export const api = new ApiNamespace(scope, 'api', () => ({
  // Public as written. Require a session before deploying: see security.md.
  echo: (input: string) => search.echo(input),
}));
```

Call Block methods only inside API methods. Check with `npm run dev`, which uses the mock. Ask the user before deploying: a deploy creates the Block's resources and IAM grants in their AWS account.

More detail is in `npx --yes @aws-cdk-blocks/create-block --help` and in the generated package's `README.md` and `DESIGN.md`.
