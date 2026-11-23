# Add CDK Blocks to an existing project

For a project that has a `package.json` and no `cdk-blocks/` folder. Run every command from the project root. The scaffolder detects the kind of project: if `amplify/backend.ts` exists, go to [Amplify Gen 2](#amplify-gen-2).

## A web project or an API

1. Choose the backend to copy.

   | The project | `--template` | The local server serves |
   |---|---|---|
   | Next.js | `nextjs` | the API and the Next.js app at `http://localhost:3000` |
   | Another frontend: Vite, SvelteKit, Astro, Nuxt | `bare` | the API and the project's frontend at `http://localhost:3000` |
   | No frontend: an Express API, a worker | `backend` | the API alone at `http://localhost:3001` |

   Without `--template` the command copies a sample backend with sign-in, a todo model and realtime that the project then has to remove.

2. Tell the user what the command changes, then run it:

   ```bash
   npx --yes @aws-cdk-blocks/create-blocks-app . --template <template> --yes
   ```

   - The trailing `--yes` is required. Without it the command stops at `Proceed? (y/N)`, and with no terminal attached it exits with status 0 having written nothing.
   - It creates `cdk-blocks/` and `cdk.json`, adds a workspace, dependencies and scripts to `package.json`, appends to `.gitignore`, and installs dependencies. It keeps existing scripts and commits nothing.
   - Wait for exit status 0. It ends with `✓ AWS CDK Blocks backend added to your project!` and next steps.
   - If it stops with `is a workspace of the npm workspace root`, add the `"workspaces"` line it prints to that root's `package.json` and run the command again.
   - If it stops with `cdk-blocks/ already exists`, CDK Blocks is already there: do not scaffold again.

3. Find the task names. A task whose script name was taken is added as `blocks:<name>`, and the command lists those under `CDK Blocks tasks renamed to preserve your existing scripts:`. To find a task later, look in `scripts` for the command that ends with it, such as `-- dev` or `-- docs`.

   | Task | Command |
   |---|---|
   | Start the local server in the background: the API, plus the project's frontend when it has one | `npm run dev:server > dev.log 2>&1 &` |
   | Stop it | `npm run dev:stop` |
   | The guide for the installed version | `npm run -s docs guide -- --output text` |
   | Block docs, signatures, search | `npm run -s docs KVStore -- --output text`, `npm run -s docs:api KVStore -- --output text`, `npm run -s docs:search "<term>" -- --output text` |
   | Every task | `npm run help` |

   The local server needs no AWS account. Stop it with its task, never with `pkill` or `killall`, which can match your own process.

4. If the project typechecks with `tsc` and is not Next.js, apply the `TypeScript:` note the command prints: a `references` entry for `./cdk-blocks` in the tsconfig that compiles the code importing `cdk-blocks`, and `tsc -b --force` in place of `tsc`.

5. The command adds no `AGENTS.md`, test, build or typecheck script. Keep the project's own, and read the guide from step 3 before writing backend code.

## Write the backend

- **API.** `cdk-blocks/index.ts` exports namespaces. Clients call `<export name>.<method>()`, so a request for `orders.create()` needs `export const orders`:

  ```ts
  import { ApiNamespace, ApiError, Scope } from 'aws-cdk-blocks';
  const scope = new Scope('my-app');
  export const orders = new ApiNamespace(scope, 'orders', (context) => ({
    // Public as written. Require a session before deploying: see Sign-in below.
    async create(item: string) {
      if (!item) throw new ApiError('Item is required', 400, { name: 'ItemRequired' });
      return { item };
    },
  }));
  ```

- **Clients.** Frontend code and tests import the same export names with their types: `import { orders } from 'cdk-blocks'`, then `await orders.create('x')`. Never build requests by hand, and never import `cdk-blocks/index.ts` by path: that is the server module.
- **Errors.** An `ApiError` reaches the client with its status, message and `name`, and an error thrown by a Block reaches it with its name. Any other error arrives as an unnamed 500 `Internal error`. Client code imports `ApiError` and `isBlocksError` from `aws-cdk-blocks/client` and matches the name: `isBlocksError(e, 'ItemRequired')`.
- **Sign-in.** A method is public until it requires a session. Read `npm run -s docs Auth -- --output text` before adding sign-in.
- **Data.** Store data with Blocks such as `KVStore`, never in local files or memory.

Ask the user before deploying, then follow [deploying.md](deploying.md).

## Amplify Gen 2

1. Tell the user what the command changes, then run it. It takes no `--template`:

   ```bash
   npx --yes @aws-cdk-blocks/create-blocks-app . --yes
   ```

   It creates `cdk-blocks/` and `amplify/blocks.ts`, adds the CDK Blocks import to `amplify/backend.ts`, edits or creates `amplify.yml`, and updates `package.json` and `.gitignore`. Amplify auth and data stay as they are, and the CDK Blocks API accepts the Amplify user pool's tokens. It ends with `✓ Blocks integrated with your Amplify Gen 2 app!`. If it prints `Could not auto-patch amplify/backend.ts`, apply `amplify/blocks-manual-patch.txt` by hand. If it created `amplify.yml`, check that file's `frontend` section against the project's build before committing it.

2. Use these tasks:

   | Task | Command |
   |---|---|
   | Start the local CDK Blocks API at `http://localhost:3001` | `npm run blocks:dev > dev.log 2>&1 &` |
   | Stop it | `npm run blocks:stop` |
   | Regenerate the typed client after changing the API | `npm run generate-client` |
   | Block docs and the task list | `npm run -s docs -- --output text`, `npm run help` |

3. Deploy through Amplify, never with a CDK Blocks deploy task. `npm run sandbox -- --once` deploys Amplify and CDK Blocks together to the user's Amplify sandbox and exits; without `--once` the task keeps watching and does not exit. Branch deploys run from `amplify.yml`. Ask the user before `npm run sandbox` or `npm run sandbox:delete`.
