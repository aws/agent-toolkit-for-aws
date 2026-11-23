# Deploy a CDK Blocks app

For an app the scaffolder created or extended. An app with CDK Blocks inside the team's own CDK stack deploys with that team's command ([existing-cdk-app.md](existing-cdk-app.md)), and an Amplify Gen 2 project deploys through Amplify ([existing-project.md](existing-project.md)).

Run every task from the app root. Flags go after `--`.

## Before the first deploy

1. Check the target without changing anything:

   ```bash
   npm run -s whoami -- --output json
   ```

   It prints `account`, `region`, `credentials` and the stack names under `stacks`. Nothing is deployed.

2. Tell the user the account, the Region and the stack, and ask before you deploy. A deploy creates billable resources in their account.

3. Settle `users.signInWith` and `users.caseSensitive` on `Auth` first. They cannot change once the user pool exists.

## Deploy a sandbox

A sandbox is a personal, disposable copy of the backend on AWS. Deploy it once and exit:

```bash
npm run -s sandbox:deploy -- --output json > sandbox.json
```

- Success is exit status 0. `sandbox.json` then holds `apiUrl`, `url`, `stack`, `account` and `region`.
- A first deploy takes minutes. Run it as a background job and wait for it to exit. Do not poll it with sleeps.
- For a readable log instead, run `npm run sandbox:deploy -- --output text > deploy.log 2>&1`. Its last line is `BLOCKS_DEPLOYED api=<api url>`.
- `npm run sandbox:preview` deploys the same stack plus a hosted copy of the frontend and adds `url=<preview url>` to that line.
- `npm run sandbox` deploys, then keeps watching and serves the frontend locally. It does not exit: use it only when the user wants a live loop.

Confirm the stack from AWS:

```bash
aws cloudformation describe-stacks \
  --stack-name "$(npm run -s whoami -- --query stacks.sandbox)" \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text
```

The stack carries the tag `blocks:deployment-type` with the value `sandbox`.

## When a deploy stops

| Message starts with | Do |
|---|---|
| `AWS credentials could not be verified` | The message names the profile, the Region and the command that fixes it, such as `aws login --profile <name>` or `aws sso login --profile <name>`. Sign-in opens a browser: ask the user, then run the task again. If the message lists `aws configure set region` first, that command edits the user's AWS configuration: include it in the same question. |
| `CDK is not bootstrapped in Region` | The message prints the `npx cdk bootstrap` command to run. Bootstrapping creates IAM roles and a bucket in the account, once per account and Region: ask the user, run it from the app root, then run the task again. |
| `Deployment failed` | Read the lines above it. If a later sandbox deploy reports that the stack cannot be updated, remove the sandbox and deploy again. |

Before it deploys, the task prints `Deployment target:` with the credentials and the Region, and does not pause. If that is not the account the user named, stop the task and ask. Never change a spend limit; pass a billing link in the output on to the user.

Exit status: `0` success, `1` the operation failed, `2` a usage error or a confirmation the run could not give, `130` interrupted.

## Deploy to production

Ask the user first, and finish [security.md](security.md). Then:

```bash
npm run -s deploy -- --output json > deploy.json
```

The result adds `live`. The production stack is named `<stackId>-prod` and tagged `blocks:deployment-type` = `production`. Add `--wait-live` to hold the result until the frontend build is being served.

## Remove what was deployed

- **Sandbox:** `npm run sandbox:destroy -- --yes` deletes this machine's sandbox stack and prints `Sandbox destroyed!`. Ask the user unless they asked for the teardown. A sandbox deployed from another clone is not found: delete that stack by name.
- **Production:** `npm run destroy -- --yes` deletes `<stackId>-prod`. Always ask the user first. Production data stores are retained and stay in the account.
- These tasks never remove the CDK bootstrap stack.
