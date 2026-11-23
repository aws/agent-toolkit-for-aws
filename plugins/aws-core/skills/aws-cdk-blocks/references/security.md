# Before a production deploy

Print the security checklist of the installed version:

```bash
npm run -s docs guide -- --section security --output text
```

Then check each point in the app.

- **Sign-in on every method.** A method of `new ApiNamespace(...)` is public until it starts with `await auth.requireAuth(context)` or `await auth.requireRole(context, '<group>')`. A guard without `await` protects nothing. Prefer `auth.protect(scope, '<name>', { public, methods })`, where only the `public` methods skip the session check. The local server does not flag a method left public.
- **Secrets.** Keep API keys and credentials in the `Secret` Block (`npm run -s docs Secret -- --output text`), which stores them in AWS Secrets Manager. Never put them in source, committed `.env` files or plain environment variables.
- **Validated input.** Give every `KVStore` and `AppSetting` that takes user input a `schema`, and validate the arguments of every public method.
- **Origins.** With `Hosting` and `api: blocksStack` the frontend is same-origin and needs no entry. A frontend hosted elsewhere needs its exact origins in `defaults.allowedOrigins` on `BlocksStack.create(...)`. Never allow every origin.
- **Files.** `FileBucket` buckets block public access. Share files with signed URLs from the Block, and list the frontend origins in the bucket's `corsRules`.
- **Rate limits and WAF.** API throttling is on through `defaults.throttling`. AWS WAF is off: for a public app set `apiWaf: { enabled: true }` on the stack, and `frontDoor: { features: { waf: { enabled: true } } }` on `Hosting` for browser traffic.
- **Encryption and transport.** The data Blocks encrypt what they store, and the default front door serves the API and the frontend over HTTPS. Keep both. A front door on a custom domain needs a certificate from AWS Certificate Manager.
- **Logs.** `Logger` does not redact. Never log credentials, tokens, secrets or whole request objects, and remove personal data before sharing a log.
- **Alarms and access logs.** Give `Hosting` alarm subscriptions under `frontDoor: { features: { monitoring: { enabled: true, subscriptions: [...] } } }` so an alarm reaches a person who is allowed to see it. Alarm on the `RpcErrors` metric with `StatusClass` = `5xx`: a failed API call does not count as a Lambda error. API access logs are off: turn them on with `defaults: { ...BlocksPresets.production, accessLogging: true }`, on one stack per Region.
- **Browser headers.** Set a Content Security Policy for the frontend with `frontDoor.features.contentSecurityPolicy` on `Hosting`.
- **IAM.** Add no `*` policies: each Block grants access to its own resources only. Review `cdk.out/<stack>.blocks-iam.json` after a synth, and set `defaults.permissionsBoundary` when the account requires one.
- **Deploy credentials.** Deploy with a role scoped to this app and short-lived credentials, not an administrator user or long-lived access keys.
- **Data protection.** Keep `BlocksPresets.production` on the production stack: it retains data stores and turns on deletion protection and point-in-time recovery.
- **Destructive actions.** Ask the user before `npm run destroy`, before deleting a data store, and before changing a Block's id or scope, which replaces its resource and data.

AWS guidance for the services behind the Blocks: <https://docs.aws.amazon.com/wellarchitected/latest/framework/security.html>.
