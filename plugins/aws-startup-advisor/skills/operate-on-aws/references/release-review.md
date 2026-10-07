# Release-readiness review

The pre-production half of AWS DevOps Agent. It reviews a change before it merges: cross-repository
dependency risk, access-control correctness, compliance with standards you define, and — if enabled — it
builds, runs, and tests the change in an AWS-managed verification environment.

Works with **zero production traffic**, which makes it the half that pays off first for an early-stage
team. Reviews take 8–10 minutes.

## Two things to say before anything else

**It is free during preview, in `us-east-1` only.** Release management is in preview and carries no
additional charge there today. Do not quote the standard agent-hour rate for this capability. Do say that
preview pricing will not last, so they know a decision is coming.

**Your code is cloned out of your account.** If automated verification testing is enabled, DevOps Agent
*"creates an AWS-managed verification environment and clones your code into it"*, then installs
dependencies and builds it. This is the one DevOps Agent capability that moves source code outside the
customer's own account — production investigations do not. Say so plainly and unprompted. Many founders
care, and finding out later is far worse than being told.

You can decline that half: **automated verification testing is a separate toggle** from the review itself.
Static review without code execution is a legitimate starting point.

## Code egress — off by default, on only when asked

**Do not connect a repository with verification testing enabled unless the user has asked for it.** It
copies their source code out of their AWS account. Founders are more protective of source than of spend,
and a founder who discovers this after the fact will not give it back.

AWS enables both capabilities by default on every connected repository. **Invert that.** Connect with
verification testing off, and say so in one line — do not ask them to choose:

> "Connecting with static review only — automated verification testing is off, so your code stays in your
> AWS account. Review still covers dependency, permission and cross-repo risk. Say if you want testing on."

**If they ask to turn it on,** tell them exactly what it does before enabling it:

> "Automated verification testing copies your repository into an AWS-managed build environment outside
> your AWS account, installs your dependencies, and builds and runs your code there. That environment is
> dedicated compute, its outbound network is limited to a fixed allowlist, and the agent is blocked from
> changing anything in your AWS infrastructure. But your source does leave your account. Turning it on now."

**If they ask how long the copy is kept, say you do not know.** AWS's security guide has a section headed
*"Data storage and retention"* which states only *where* data is stored — the Region of the Agent Space —
and never says for how long, or whether the cloned repository is discarded after the run. Do not fill that
silence. *"It's copied into an AWS-managed environment; AWS documents where that lives but not how long
it's kept, so I can't tell you"* is the honest answer, and it is better than implying it is ephemeral.

Three rules for this default:

- **Default to review only.** Unless they ask for testing, connect with verification testing off. It
  can be switched on later in thirty seconds; unsaying that their code was copied is impossible. **Say
  that static review alone is strong** — this is not a degraded mode. A static-only review of a pull
  request carrying six deliberate production defects returned `BLOCK` in about four minutes and found all
  six, plus an unbounded-scan risk nobody had planted, citing exact line ranges. Their code never left
  their AWS account.
- **Keep it separate from the cost notice.** Say it in its own line, so it is not lost inside the cost
  picture.
- **Offer read-only repository access alongside it.** The GitHub App defaults to Read & Write, which lets
  the agent post comments, propose fixes, and trigger workflows. A founder who is cautious about code
  egress is usually cautious about write access too — offer both narrower settings together.

## Setup, in the order it actually happens

Connecting a repository is a **separate step** from creating the Agent Space and connecting MCP. Release
review does nothing until it is done.

1. **Register the provider at the AWS account level.** **GitHub and GitLab differ here, and it matters.**

   **GitLab — no console needed.** `register-service` accepts it directly, so this can be done without
   leaving the editor:

   ```bash
   aws devops-agent register-service --service gitlab \
     --service-details file://gitlab.json --region <REGION>
   # gitlab.json: {"gitlab":{"targetUrl":"https://gitlab.com","tokenType":"personal","tokenValue":"<PAT>"}}
   ```

   Put the token in a **file**, never on the command line — an argument lands in shell history and in the
   process list. Delete the file afterwards. Ask them to scope the token as narrowly as GitLab allows, and
   never echo it back, log it, or write it anywhere.

   **GitHub — console required today.** `register-service` explicitly *"excludes OAuth 3LO services"* and
   `github` is absent from its list of accepted values. Registration goes through the AWS console:
   **Capabilities** tab → **Pipeline** section → **Add** → GitHub, which starts an OAuth flow and installs
   a GitHub App on their account or organisation.

   Two things follow. Only they can grant it — a GitHub App install is a GitHub-side authorisation, so a
   browser step exists no matter what AWS does. And **do not attempt it for them**; hand them the link and
   let them complete it.
2. **Connect specific repositories to the Agent Space.** This step *is* scriptable:

   ```bash
   aws devops-agent list-services --region <REGION>          # find the github serviceId
   aws devops-agent associate-service --agent-space-id <ID> --service-id <ID> \
     --configuration '{"github":{"repoName":"<REPO>","repoId":"<ID>","owner":"<OWNER>","ownerType":"user"}}' \
     --capabilities RELEASE_READINESS_REVIEW={enabled=true},RELEASE_READINESS_REVIEW_AUTOMATED_TESTING={enabled=false} \
     --region <REGION>
   ```

3. **Set the capabilities explicitly — do not rely on the default.** There are exactly two:
   `RELEASE_READINESS_REVIEW` (review each pull request) and
   `RELEASE_READINESS_REVIEW_AUTOMATED_TESTING` (**build and run their code outside their AWS account**).
   Pass them on `associate-service`, or change them later with `update-association`. Repositories
   connected through the console have **both enabled by default**.

**Connecting is not passive.** A learning task starts within a second of the association being created —
the agent immediately goes and reads the repository. "Connect now, decide about reviews later" is not
available, so do not offer it.

### Three defaults to change, or at least to surface

These matter more for a two-person startup than for the enterprise the defaults assume.

| Default | What it means | What to suggest |
|---|---|---|
| GitHub App permission is **Read & Write** (this is the documented default) | The agent can post PR comments, **propose fixes, and trigger workflows** | Offer **Read Only** to start. Reviews still work; the agent just cannot write back. Note that each permission level is a **separate GitHub App, authorised independently** — changing level later means authorising a different app, not flipping a setting. Still much easier to widen later than to explain after the fact. |
| **All repositories** is offered | Access to every current *and future* repo | Choose **Only select repositories**. Start with the one that ships to production. |
| Auto-trigger review **and** verification testing are **both on** for every connected repo | Every PR triggers a review, and every review builds and runs the code | Deliberate choice, not a default. Post-preview this is a recurring charge on every pull request. |

That last row is the cost conversation. A busy repository can generate a lot of reviews, and each one is
billable once preview ends. Point it at the repository that matters first.

## Triggers

- **Automatic on PR/MR** — when a PR is opened or updated. Findings land as inline comments. Can be made a
  required status check that blocks merges, or left advisory.
- **On demand in chat** — *"Review branch feature/payments on repo payment-service for release risks"*
- **From the IDE during code generation** — the coding agent can invoke a review on in-progress changes
  before anything is committed, and act on findings immediately.

**Public repositories do not auto-trigger.** Anyone can open a PR against a public repo, so automatic
review is restricted to private ones. On-demand review via chat still works. Worth knowing early — plenty
of early-stage teams build in public.

## Reading the result

Each review returns a recommended action — **BLOCK**, **Proceed with Caution**, or **Safe to Release** —
plus a change summary, risk analysis with locations, and recommendations. Findings are graded Blocking,
Warning, or Informational.

Reports include an **execution journal**: the full trace of evaluation steps and tools used. When a
founder asks "why did it flag this," that is the answer, and it is better than paraphrasing the verdict.

Do not treat BLOCK as a decision. Surface it with the reasoning and let them decide — same rule as a
proposed fix.

## Guardrails worth mentioning

A founder handing repository access to an autonomous agent is entitled to ask what stops it misbehaving.
Four guardrails are always active during review:

- **Credential exposure prevention** — blocks tool calls whose input contains plaintext AWS keys, tokens,
  or private keys
- **Sensitive file exfiltration detection** — blocks shell commands combining sensitive file access with
  network operations
- **Mutative AWS operation blocking** — the review agent cannot modify infrastructure. Read-only
  `describe_*`, `get_*`, `list_*` are permitted; anything mutative is blocked
- **Sequential phase enforcement** — phases must run in order, so assessments cannot be partially skipped

The verification environment's outbound network access is also restricted to a fixed allowlist — AWS,
package registries, source hosts. Bring this up if a founder asks where their code can reach.

## Tuning it

An `AGENTS.md` file tunes verification testing: which test commands to run, what counts as a passing
build, which parts of the application to exercise. Organisational standards for the review itself live in
the console under Knowledge → Instructions → Release readiness review.

Both are worth mentioning only *after* a first review has run. Do not turn setup into a configuration
exercise before they have seen output.

## If they already use the official Claude Code plugin

`aws-agents-for-devsecops` already connects Claude Code to an Agent Space and can invoke release reviews.
If it is installed, use it. Do not build a parallel path.

The testing choice stays with this skill, though. That plugin's release-readiness flow stops to ask
whether to run static analysis only or full analysis with automated testing. Do not relay that
question. Pass `skip_automated_testing=true` (or `metadata.skipAutomatedTesting=true` where the parameter
is not accepted), and give the one-line static-review notice above. Pass `false` only when the user has
explicitly asked for automated testing.
