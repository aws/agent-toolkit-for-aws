# Fleet & Stack Recommendation Logic

The fixed mapping from onboarding answers (onboarding-flow.md) to concrete configuration. Every field and value below is from the [CreateFleet](https://docs.aws.amazon.com/appstream2/latest/APIReference/API_CreateFleet.html) / [CreateStack](https://docs.aws.amazon.com/appstream2/latest/APIReference/API_CreateStack.html) API references — do not invent others.

> Recommendations are heuristic, derived from what the user *describes* — present them as a reasonable starting point to refine from real usage, never as validated sizing. No dollar figures: qualitative tradeoffs and documented licensing facts only, with the [pricing page](https://aws.amazon.com/workspaces/applications/pricing/) linked for rates.
>
> **Guided-flow fleet shape (both personas):** `ALWAYS_ON` or `ON_DEMAND`, single-session. Elastic and multi-session fleets are out of the guided flow (and unsupported for agent access entirely). For agent environments the platform must be **Windows Server**; **1 instance = 1 concurrent session**.

## Fleet type & scaling (default, don't ask)

**Default `ALWAYS_ON` — don't ask.** Instant sessions, no cold-start surprises, and the simplest first experience; it's also the cheapest choice to *understand*. List it under "defaults chosen for you" with the honest tradeoff: it bills all running instances even when nothing is streaming, and the user can switch to On-Demand later (`UpdateFleet`, fleet stopped) once the usage pattern is known.

Recommend `ON_DEMAND` instead only when the workflow description clearly implies it, or the user raises cost: scheduled/batch/event-driven runs with long idle gaps, where a one-to-two-minute session start is obviously tolerable. Present that as a swap of the default ("your workflow runs twice a night — On-Demand would avoid paying for idle hours; want that instead?"), not as an open question.

| Pattern (from the description) | `FleetType` | Warm capacity (min) | Scaling strategy |
|---|---|---|---|
| Default — interactive, unknown, or mixed usage | `ALWAYS_ON` | ≥ expected concurrency during working hours | Scheduled scaling to working hours if the description gives hours |
| Clearly scheduled / batch / event-driven with idle gaps (offer as swap) | `ON_DEMAND` | Can be 0 (scale from zero) | Match the pattern: queue/backlog → scale on pending work; batch/burst → scale up for the window, then to zero |

Qualitative tradeoff to state (documented on the pricing page): `ALWAYS_ON` bills all running instances even when no one is streaming, for instant access; `ON_DEMAND` bills instance streaming while connected plus a small hourly fee for provisioned instances that aren't streaming, and connecting takes one to two minutes.

**Capacity:** max = expected peak concurrency (the concurrency question), since one single-session instance serves one agent session. Undersizing produces insufficient-capacity errors at peak.

**Quota:** each instance type has a quota of streaming instances for fleets in each Region, shared by every fleet of that type in the account. Read it before the plan, a read-only call:

```bash
aws service-quotas list-service-quotas --service-code appstream2 --region <region> \
  --query "Quotas[?ends_with(QuotaName, 'streaming instances for fleets')].[QuotaName,Value]" --output text
```

That returns applied values only. If the instance type's quota isn't in it, run the same query with `list-aws-default-service-quotas` to read the default.

The `stream.standard` quotas are named by size, for example "Standard small streaming instances for fleets". Subtract what the account's other fleets of that type can scale to: find them with `describe-fleets` (`InstanceType`), then read each one's `MaxCapacity` with `aws application-autoscaling describe-scalable-targets --service-namespace appstream`, or its `ComputeCapacityStatus.Desired` if it has no scaling target. If the concurrency is above what's left, set max capacity to what's left, say so in the plan, and say that an increase is requested through Service Quotas and isn't instant. Don't request it for the user. If the quota for the type is 0, which is the default for graphics types in new accounts, don't plan that type at all.

**Mechanics note:** `CreateFleet` sets `FleetType` and initial `ComputeCapacity.DesiredInstances`. Min/max and scaling policies are **Application Auto Scaling**, applied separately after creation — see create-workspace.md step 6. **Scale-from-zero is achieved there, not at create:** create the fleet with `DesiredInstances: 1`, then register the scaling target with `MinCapacity: 0` — and say so in the plan, so the summary ("scales to zero when idle") and the `CreateFleet` call (desired 1) don't look contradictory.

## OS & licensing

**For agent desktops the platform is Windows Server** — the only platform agent access supports, in any of its versions. Default to the newest base image among the public images (`aws appstream describe-images --type PUBLIC`): the highest Windows Server version, then the latest date at the end of the name (`MM-DD-YYYY`), skipping `Graphics` images unless the workflow needs a GPU. Don't sort by `CreatedTime`: it doesn't follow release order, and sorting by it can put an older version first. If the described workflow appears Linux-only or needs a client OS, flag the conflict with agent-access support explicitly rather than recommending an unsupported platform. When you tell the user which Windows Server versions exist, name the ones `describe-images` returned, not versions from memory. Windows 11 needs the customer's own Microsoft licenses on dedicated hardware ([bring your own license](https://docs.aws.amazon.com/appstream2/latest/developerguide/byol-windows-images.html)), which this guided setup doesn't cover: say so, and offer the newest Windows Server base image or a different workflow.

**For human setups** Windows Server is the same sensible default; if every needed application runs on Linux (`AMAZON_LINUX2`, `RHEL8`, `ROCKY_LINUX8`), a Linux fleet avoids the per-user RDS SAL fee entirely — a documented cost fact worth surfacing.

Licensing facts to surface (documented, not computed):

- **Windows Server fleets incur a per-user RDS SAL fee** (a Microsoft Remote Desktop Services Subscriber Access License, billed by AWS monthly per unique user). The [pricing page](https://aws.amazon.com/workspaces/applications/pricing/) documents current rates, including the rate that applies to AI agent use cases. Bring-your-own RDS CALs via Microsoft License Mobility can waive it.
- **Microsoft 365 applications require a customer-procured license eligible for unattended use** — desktop Office bought through AWS cannot be provisioned for agent (unattended) use. Surface this whenever M365 apps are in the application list, regardless of other choices.
- **For people, Office, Visio and Project can be licensed through AWS** (image-setup.md, License-included applications). Every user streaming from a fleet built from that image is billed for them monthly, whether or not they open them; entitlements don't limit who is billed. Say this whenever one is in the plan.

## Instance & storage

Recommend `InstanceType` from the workflow profile — memory from working-set/file sizes, compute for CPU-bound work, GPU only if the workflow genuinely needs it — as a starting point, not validated sizing.

Families: `stream.standard`, `stream.compute`, `stream.memory` and `stream.graphics`. Take exact instance types from the `InstanceType` values in the [CreateFleet API reference](https://docs.aws.amazon.com/appstream2/latest/APIReference/API_CreateFleet.html) instead of guessing sizes; regional availability varies — confirm when it matters.

- **Default:** `stream.standard.large` for typical multi-app desktop automation; step up for large files or heavy applications.
- **Graphics:** graphics-instance service quotas default to 0 in new accounts — a quota increase must be requested and is not instant. Flag this before recommending a GPU family, and note GPU vs non-GPU is effectively a one-way door (image compatibility).
- **Storage:** `RootVolumeConfig.VolumeSizeInGb` default 200 (the documented range is 200–500). Storage above the base allocation bills regardless of running state.

## Session timeouts (persona-conditional)

| `CreateFleet` field | Agent default | Human default | Accepted values |
|---|---|---|---|
| `IdleDisconnectTimeoutInSeconds` | 900 (15 min) — an agent that stops sending input is done or stuck. **Must be less than `MaxUserDurationInSeconds`**: when the run cap is ≤ 900s, set idle to 0 (the cap is the guardrail; an idle timeout at or above the cap is rejected/redundant) | 900, rounded to whole minutes (users are warned before idle disconnect) | 0 (never) or 60–36000 |
| `DisconnectTimeoutInSeconds` | 900 (15 min) — an agent's connection can drop, for example when its runtime times out, and within this window it reconnects to the same session with its work intact. The API minimum of 60 ends the session a minute after any drop | 900 (15 min) — humans close laptops and come back; within this window they reconnect to their same session | 60–36000 (0 is rejected) |
| `MaxUserDurationInSeconds` | **Default 14400 (4 h) — don't ask.** Generous on purpose: at the cap the instance is terminated mid-run, and idle disconnect is the stuck-agent catch. Scale up ~4× if the description implies longer runs; right-size with `UpdateFleet` once real run times are known | Match the workday (e.g. 36000 / 10 h) unless there's a reason to cap | 600–432000 |

State plainly: idle and disconnected sessions bill until they end.

## Default policy set (applied silently, all changeable later)

- **`AgentAccessConfig.Settings`:** `COMPUTER_VISION` ENABLED, `COMPUTER_INPUT` ENABLED (input requires vision). `FORWARD_MCP_TOOLS` ENABLED only if the user said yes to Q9, with the servers and manifest added to the image (image-setup.md); otherwise DISABLED (can be enabled later via `UpdateStack`, partial updates supported).
- **`UserControlMode`: `VIEW_STOP`** — a human can watch the live session and stop the agent (`VIEW_ONLY` = observe only, `DISABLED` = no observer access). Set it by default. Caveat: an older installed CLI/SDK whose bundled AppStream model predates this field rejects it client-side before the call is sent — upgrade the CLI/SDK, or set it via the console (see troubleshooting.md).
- **Screen:** `ScreenResolution: W_1280xH_720` (the only value the API accepts), `ScreenImageFormat: PNG`.
- **`StreamView: DESKTOP`** on the fleet — must be set explicitly; the API default is `APP`, and agent workflows need the full desktop.
- **Persistence off:** leave `ApplicationSettings.Enabled: false` — agent sessions are task-scoped; no profile state should carry between sessions.
- **Screenshot storage is asked, not applied silently:** question 10 of onboarding-flow.md offers a new bucket (the default), an existing one, or none. The bucket rules, its policy and the permissions the agent's IAM identity needs are in [agent-access-config.md](references/agent-access-config.md).

## Persona differences (stack and view)

- **`StreamView`:** agents get `DESKTOP` (set explicitly — the API default is `APP`). For humans, ask: `APP` shows only application windows (simpler, kiosk-like); `DESKTOP` gives the full OS desktop.
- **`AgentAccessConfig` is agent-only.** Never put it on a stack meant for human users — a stack with `AgentAccessConfig` is configured for agent sessions, not human streaming.
- **UserId / user access:** planning agent UserIds and creating human user-pool users is [user-access.md](references/user-access.md).
- **GPU is out of the guided flow for human setups** — graphics capacity must be reserved/secured first (quotas default to 0, increases are not instant); route to the [instance families documentation](https://docs.aws.amazon.com/appstream2/latest/developerguide/instance-types.html). For agents, read the quota for the graphics type first (Fleet type & scaling, Quota). If it's 0, don't plan a GPU fleet: say the quota must be raised first and isn't instant, and offer a plan on a non-GPU type or to come back once the increase is approved.

## Fleet IAM role (when the workflow calls AWS APIs)

If the agent's desktop workflow itself needs AWS access (upload results to S3, read a queue), set `IamRoleArn` on the fleet: instances assume the role and expose an `appstream_machine_role` credential profile — no credentials on the image, ever. Scope the role to the specific actions the workflow performs. Skip entirely if the workflow doesn't touch AWS APIs.

## Instance metadata (IMDSv2)

Set `DisableIMDSV1: true` (CLI flag `--disable-imdsv1`) on new fleets and image builders unless something on the image demonstrably needs IMDSv1. (The API's default for this parameter depends on the image, so set it explicitly rather than relying on the default.)

## Streaming protocol

Leave `StreamingExperienceSettings.PreferredProtocol` at the TCP default. UDP applies to the Windows native client — not the agent path.

The full `AgentAccessConfig` reference, including how to change or remove it later and how it works on image builders, is [agent-access-config.md](references/agent-access-config.md).
