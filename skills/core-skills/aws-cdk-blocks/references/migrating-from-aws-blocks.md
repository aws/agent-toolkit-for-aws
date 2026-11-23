# Move an app from the AWS Blocks names to the CDK Blocks names

Contents: [Never change](#never-change), [Steps](#steps), [Errors](#errors).

For an app that has an `aws-blocks/` folder or depends on `@aws-blocks/*`. The move renames packages, folders and settings in the repository, and renames no deployed resource. Work on a branch, make one commit per step, and run each check before the next step.

Installing the renamed packages also installs every release since the app's last install. Before step 8, read `docs/guides/upgrading-older-apps.md` in <https://github.com/aws/cdk-blocks> for the changes between those releases.

## Never change

- `stackId` in the hidden config file, and the id and scope of every Block in the backend. They name the deployed stack and its resources: a changed value makes the next deploy create a second stack, or replace a resource and lose its data.
- URLs under `/aws-blocks/` in deployed clients and mobile apps. They keep working.
- The `aws-blocks` entry in `keywords` and the `aws-blocks` key in the `package.json` of a Block package.
- The local folders `.bb-data/` and `.blocks-sandbox/`. Leave them in place: the next task copies what it needs.

## Steps

1. Record the stack names. Run `npm run whoami` and keep its sandbox and production stack names. If the app has no `whoami` script, or the task stops for AWS credentials, read `stackId` in `.blocks/config.json`: production is `<stackId>-prod`.

2. Rename the hidden folder, and commit:

   ```bash
   git mv .blocks .cdk-blocks
   ```

   In every `tsconfig*.json`, change `.blocks/**/*.d.ts` to `.cdk-blocks/**/*.d.ts`. Check that `.cdk-blocks/config.json` holds the `stackId` from step 1. Never create that file by hand.

3. Rename the dependencies, in `package.json` files only:

   - `@aws-blocks/blocks` becomes `aws-cdk-blocks`.
   - Every other `@aws-blocks/<name>` becomes `@aws-cdk-blocks/<name>`, except `@aws-blocks/bb-auth-basic`, `@aws-blocks/bb-auth-cognito` and `@aws-blocks/bb-auth-oidc`, which step 5 replaces.
   - Set each renamed dependency to a version that exists under its name: `npm view aws-cdk-blocks version` prints it.

   Run `npm install` and check that it exits with status 0. Commit the manifests and the lockfile together.

4. Only when `package.json` scripts run `aws-blocks/scripts/*.ts` files or a `cdk-blocks` command: move them to package tasks. Do it now, while those files are unchanged, because the command recognizes them by their exact text. It needs a clean git tree:

   ```bash
   node --input-type=module -e "import 'aws-cdk-blocks/run'" -- migrate --dry-run
   node --input-type=module -e "import 'aws-cdk-blocks/run'" -- migrate
   ```

   It rewrites the scripts the scaffolder generated, adds the missing tasks and deletes the generated files. It renames no folder, package or import. Exit status 1 lists the customized scripts it kept: replace each by hand with the matching `npm run` task. Commit.

5. Replace the sign-in classes, when the app uses `AuthBasic`, `AuthCognito` or `AuthOIDC`. One class, `Auth`, replaces them. Ask the user first when the app uses `AuthBasic`: its users have to sign up again.

   ```bash
   npx --yes @aws-cdk-blocks/bb-auth migrate --dry-run
   npx --yes @aws-cdk-blocks/bb-auth migrate
   ```

   The command keeps the id and scope of every sign-in Block. Then replace the old sign-in packages in `package.json` with `@aws-cdk-blocks/bb-auth`, run `npm install`, resolve every `TODO(aws-blocks-auth-migrate)` comment, and read `node_modules/@aws-cdk-blocks/bb-auth/MIGRATION.md` before a deploy.

6. Rename the import specifiers in every source file, in the `scripts` values of `package.json`, and in docs such as the app's `AGENTS.md`: `@aws-blocks/blocks` becomes `aws-cdk-blocks`, with the same subpaths (`aws-cdk-blocks/cdk`, `aws-cdk-blocks/client`, `aws-cdk-blocks/run`), and every other `@aws-blocks/<name>` becomes `@aws-cdk-blocks/<name>`. Check that this lists nothing, then commit:

   ```bash
   git grep -n "@aws-blocks/" -- . ':!package-lock.json'
   ```

7. Rename the backend folder. These edits go in one commit:

   ```bash
   git mv aws-blocks cdk-blocks
   ```

   - In `cdk-blocks/package.json`, set `"name": "cdk-blocks"`.
   - In the root `package.json`, change the `"workspaces"` entry `"aws-blocks"` to `"cdk-blocks"`.
   - Change every `from 'aws-blocks'` and `import('aws-blocks')` to `'cdk-blocks'`.
   - Change every remaining `aws-blocks/` path: `cdk.json`, `.gitignore`, `tsconfig*.json`, CI files, the app's `AGENTS.md`, and a `Database` Block's `migrationsPath`. Find them with `git grep -n "aws-blocks" -- . ':!package-lock.json'`, and leave what "Never change" lists.
   - Add `.cdk-blocks-sandbox` to `.gitignore` and keep the `.blocks-sandbox` entry, since the old folder stays on disk. Change `.blocks-sandbox` to `.cdk-blocks-sandbox` in `cdk.json` and CI steps. In a Next.js app, also run `git mv src/app/.blocks-sandbox src/app/.cdk-blocks-sandbox` and change the folder name inside its `route.ts`.

   Run `npm install`, then check that `npm run typecheck` and `npm run test:e2e` pass.

8. Update the names the app owns outside the source tree, and commit.

   - **CI and scripts.** `AWS_BLOCKS_DISABLE_TEMPLATE_METADATA` becomes `CDK_BLOCKS_DISABLE_TEMPLATE_METADATA`. The earlier name is ignored.
   - **Telemetry.** `AWS_BLOCKS_DISABLE_TELEMETRY` no longer opts out. Ask the user whether they had opted out. If so, set `CDK_DISABLE_CLI_TELEMETRY=1` in their shell and CI.
   - **Sign-in with external identity providers.** If `Auth` has `providers` and no `redirects.callbackPath`, add `redirects: { callbackPath: '/aws-blocks/auth/callback' }`, so the redirect URI registered at the provider stays valid. Tell the user they can register `<origin>/cdk-blocks/auth/callback` at the provider instead and drop the option.
   - **Swift clients.** The dependency URL is `https://github.com/aws/cdk-blocks-swift.git` and the package name `cdk-blocks-swift` in every `.product(...)` and `.plugin(...)`. Change both together.
   - **Kotlin clients.** `awsBlocks { }` becomes `cdkBlocks { }`, and the `awsBlocksCodegen` tasks become `cdkBlocksCodegen`. Keep the plugin id `com.aws.blocks.kotlin`.

9. Deploy the sandbox. Ask the user first: it changes their AWS account.

   ```bash
   npm run -s sandbox:deploy -- --output json > sandbox.json
   ```

   Check that `stack` in `sandbox.json` is the sandbox stack from step 1 and that no other stack was created. If another stack name appears, stop, destroy nothing, and compare `stackId` with step 1.

10. Production. Ask the user before each action. Deploy with `npm run deploy`, then move every CloudWatch alarm and dashboard that reads the `AWSBlocks` metric namespace to `CDKBlocks`.

## Errors

| Message contains | Do |
|---|---|
| `Cannot find module 'aws-blocks'` | Finish step 7 |
| `no package.json with a cdk-blocks/ directory` | Finish step 7, and run tasks from the app root |
| `config.json not found or missing stackId` | Finish step 2. Never invent a `stackId` |
| `the git working tree has uncommitted changes` | Commit, then repeat step 4 |
| `custom-named resource requires replacing` | Stop and follow the upgrade guide named at the top. Never rename or delete the table: the data is in it |
