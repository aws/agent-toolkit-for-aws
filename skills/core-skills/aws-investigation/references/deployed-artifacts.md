# Read the deployed artifact, don't infer it

A question about what a system *currently does* is answered only by the artifact that governs
runtime. Anything else (the newest stored version, a draft, a tag, a description field, a parameter
spec, or your own paraphrase of the code's query) is a **proxy**. Proxies are allowed as leads,
never as evidence.

## Core procedure

1. **Name the governing artifact before fetching anything.** Ask what the runtime actually
   consults. Typical answers:
   - the version a *deployment record* says is live, not the latest stored version;
   - the configuration *served to clients*, not the hosted store;
   - the code that *executes* for the question (the implementing function or executor), not the
     card, schema, wiring or docstring that references it;
   - the packaged code attached to the live version or alias, not the repository HEAD.
2. **Retrieve that artifact and record where it came from.** Keep a provenance note per claim:
   `claim <- artifact (identifier, version, timestamp)`.
3. **Check the gap between proxy and artifact explicitly.** If you also saw a newer version, a
   description or a spec, state whether it is live, pending or only descriptive.
4. **Reproduce queries verbatim, not from intuition.** When code filters, sorts or limits data and
   you want to check live data, copy the exact predicate set, ordering and limit from the code.
   Reconcile any difference before concluding.
5. **When a route is blocked, try the alternatives before concluding.** Only after every route fails
   may you report the claim, and then as *unverified*.
6. **Answer with staged and live separated.** Never let an undeployed version, a draft or a
   descriptive field appear as live behaviour.

## Proxy traps and the artifact that replaces them

| Proxy you reached first | Why it is not evidence | Artifact to read instead |
|---|---|---|
| Latest hosted or stored configuration version | Creating a version does not deploy it; deployment is a separate step per environment | The environment's deployment history: the `ConfigurationVersion` of the most recent `COMPLETE` deployment, or the configuration actually served to clients |
| Repository HEAD, `$LATEST` or branch code | Clients may invoke a published version or alias that points elsewhere | The package attached to the version or alias actually invoked |
| Source template in a repository | The running stack may differ | The template the stack is running (`GetTemplate` on the stack) |
| Description, tag, label, schema field, card or wiring definition | Descriptive unless something enforces it | The implementing code that reads and acts on the value |
| Your own rewritten query ("status = X") | Narrower or wider than the code's predicate; a different order and limit change the "first result" and the counts | The code's exact filter set, sort direction and limit |
| One failed data route plus an empty log search | Absence of evidence from one route is not evidence of absence | Other routes (below), or label the claim as unverified |

## Reproducing a code path's query

- Extract from the code every status or state value in the `IN` set, every additional predicate
  (tenant, date range, soft-delete flags), the `ORDER BY` column and direction, and the `LIMIT` or
  page size.
- Run exactly that. Do not substitute the "obvious" status, drop the limit or change ascending to
  descending.
- If your count or first row differs from what the code would observe, explain the difference
  before building a root cause on it. A customer-specific root cause built on the wrong first row is
  a wrong root cause.
- Say "N rows matched the code's query" only after running the code's query; otherwise say "my
  approximation returned N".

## When the first route is blocked

Try these, roughly in order, and record what each returned:

1. Deployment or release records (which version is live, since when, in what state).
2. Configuration as served to clients (the data-plane read path, not the control-plane store).
3. The running stack's template or the packaged artifact of the live version.
4. Alternative data sources (replicas, exports, metrics, cached responses).
5. Broader log windows, other log groups, and structured fields instead of free text.

If all fail, mark each dependent conclusion **UNVERIFIED** with the routes tried. Do not turn "I
could not see it" into "it is silently failing".

## Answer template

```text
Live behaviour (read from <artifact + identifier>): ...
Staged / pending / undeployed (read from <artifact>): ...   <- NOT live
Parameter semantics (read from implementing code at <path/function>): ...
Query reproduced verbatim from <file:line>: <predicates, order, limit> -> N rows; first row = ...
Unverified: <claim> - routes tried: <list>
```

## AWS routes to the governing artifact

### AWS AppConfig: what is actually being served

Creating a hosted configuration version only uploads it; a separate deployment to an environment
makes it live. The newest version number in a profile says nothing about what clients receive.

Control plane, the deployment history of the environment:

- `ListDeployments(ApplicationId, EnvironmentId)` returns deployments in descending
  `DeploymentNumber` order, each with `ConfigurationProfileId`, `ConfigurationVersion`, `State`,
  `PercentageComplete`, `StartedAt` and `CompletedAt`.
- `GetDeployment(ApplicationId, EnvironmentId, DeploymentNumber)` adds `EventLog` and
  `VersionLabel`.
- `State` is one of `BAKING`, `VALIDATING`, `DEPLOYING`, `COMPLETE`, `ROLLING_BACK`,
  `ROLLED_BACK`, `REVERTED`.

Interpretation:

- The live version of a profile in an environment is the `ConfigurationVersion` of the most recent
  deployment of that profile whose `State` is `COMPLETE`.
- `DEPLOYING`, `BAKING` or `VALIDATING` means a partial rollout: report the prior complete version
  and the in-flight one, with `PercentageComplete`.
- `ROLLED_BACK` or `REVERTED` means the targeted version is not live; fall back to the previous
  `COMPLETE` deployment.
- A profile with hosted versions but no `COMPLETE` deployment in the environment has nothing live
  there; say so instead of reporting the newest version's content.
- Repeat per environment; one environment's history says nothing about another.

Data plane, the configuration as clients receive it: `StartConfigurationSession` then
`GetLatestConfiguration` returns the deployed configuration for the application, environment and
profile. It can return empty data when the caller already holds the latest version, so use a fresh
session.

### AWS Lambda: which code actually runs

- Clients usually invoke an **alias** that points to a published **version**, optionally weighted
  across two versions through `RoutingConfig`. `$LATEST` and the repository HEAD may differ from
  what the alias serves.
- `GetFunction(FunctionName, Qualifier=<version or alias>)` returns that version's configuration
  and `Code.Location`, a presigned URL (valid 10 minutes) for the deployment package, or
  `Code.ImageUri` and `ResolvedImageUri` for container images. Read the package behind the invoked
  qualifier, not the unqualified function.
- `Configuration.CodeSha256` tells you whether two versions, or a version and a build, are the same
  code.

### AWS CloudFormation: what the stack is really running

`GetTemplate(StackName, TemplateStage=Original|Processed)` returns the template the running stack
was created or updated with; `Processed`, the default, is the post-transform form. It works for
running stacks and, by stack ID, for deleted stacks up to 90 days. Use it instead of a repository
template when you need the deployed definition (inline function code, parameter wiring, resource
properties).

### Descriptive fields that are not enforced

`Description`, `VersionLabel`, tags and similar fields on AppConfig deployments and hosted versions,
Lambda versions and aliases, and CloudFormation resources are user-authored metadata. They show
intent, not behaviour. Cite them only as "labelled as ...", and read the implementing code or the
deployment record for the actual meaning.
