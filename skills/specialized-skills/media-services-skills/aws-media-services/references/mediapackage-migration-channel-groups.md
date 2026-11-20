# Channel Group Planning

Analyze discovered v1 channels and suggest how to organize them into v2 channel groups. Channel groups are a v2 concept with no v1 equivalent: they group channels under a shared egress domain.

> **SUGGEST ONLY:** Do not save any **grouping decisions** or **migration plan files** until the user explicitly confirms. Inventory `included` updates (setting a channel's `included` field to `false` or back to `true` when the user excludes or re-includes it) are permitted immediately, in `.mediapackage-migration/v1-resource-inventory.json` if it was written, otherwise in the inventory held in context.

---

## Contents

- [Step 1: Begin](#step-1-begin)
- [Step 2: Load Inventory](#step-2-load-inventory)
- [Step 3: Explain Channel Groups](#step-3-explain-channel-groups)
- [Step 4: Analyze and Suggest Groupings](#step-4-analyze-and-suggest-groupings)
- [Step 5: Present Suggestions](#step-5-present-suggestions)
- [Step 5.5: Confirm the Channel Input Type](#step-55-confirm-the-channel-input-type)
- [Step 6: Interactive Refinement](#step-6-interactive-refinement)
- [Step 7: Validate Assignments](#step-7-validate-assignments)
- [Step 8: Confirm and Save](#step-8-confirm-and-save)
- [Step 9: Hand Off](#step-9-hand-off)

---

## Step 1: Begin

Work from the discovery inventory. Treat all grouping decisions as suggestions until the user confirms (see SUGGEST ONLY above).

### Check the account's real state and real limit first

Do both of these before proposing any group or making any quota statement.

**1. List the channel groups that already exist:**

```
aws mediapackagev2 list-channel-groups --region <region>
```

Paginate via `--next-token` until no `NextToken` is returned. **NEVER assume the
account starts with zero channel groups.** Any groups you plan to create are IN
ADDITION to the existing ones, and both count toward the account quota.

**2. Read the account's *applied* channel-group quota, not the documented default.**
The published default is 3 per account, but it is adjustable, so the account may be
higher or lower. The Service Quotas service code is `mediapackagev2` and the
channel-group quota code is `L-A7040149`:

```
aws service-quotas get-service-quota --service-code mediapackagev2 --quota-code L-A7040149 --region <region>
aws service-quotas list-service-quotas --service-code mediapackagev2 --region <region>
```

The second command also returns the applied channels-per-group and other v2 quotas.
If the applied value is unavailable, fall back to
`aws service-quotas list-aws-default-service-quotas --service-code mediapackagev2`, and
if Service Quotas has no data at all, say so and proceed on the documented default of 3
— clearly labelled as the default rather than as this account's confirmed limit.

> An empty Service Quotas result does **not** mean the quota is zero. Applied values
> are omitted when unavailable. The authoritative count of what already exists is
> always `list-channel-groups`; Service Quotas only tells you the ceiling.

### If the plan doesn't fit, stop and ask

When `existing + planned > quota`, present the arithmetic and the options. Do **not**:

- silently reduce the number of groups to make it fit;
- silently place channels into an existing channel group the user didn't nominate;
- proceed on the assumption the increase will be granted.

Say which groups exist, how many you need, what the limit is, and offer: request a
quota increase (and wait), consolidate into fewer groups, migrate a subset now, or
nominate an existing group to reuse. **Reusing an existing group is the user's
decision, never yours** — that group already has an egress domain and existing
channels, and adding to it changes the URL namespace their other channels live in.

---

## Step 2: Load Inventory

Use the discovery inventory (read `.mediapackage-migration/v1-resource-inventory.json` if it was written, otherwise use the inventory held in context) to get the list of discovered channels and their endpoints. **Only consider channels marked `included: true`.** Excluded channels are not part of this migration.

---

## Step 3: Explain Channel Groups

Before suggesting groupings, briefly explain the concept to the user:

> **What are channel groups?**
> In MediaPackage v2, a channel group is a logical container for channels that share a common egress domain. All channels in a group get endpoints under the same base URL. Channel groups help organize your channels by purpose, environment, team, or content type.

---

## Step 4: Analyze and Suggest Groupings

Use the channel inventory to suggest groupings. Consider these signals (in priority order):

### Grouping Strategies

1. **By naming convention** — Look for common prefixes/suffixes (e.g., `example-sports-*`, `staging-*`, `news-*`)
2. **By tags** — Look for `Environment`, `Team`, `ContentType`, `Project` tags
3. **By environment** — Separate prod, staging, dev channels
4. **By content type** — Group sports channels together, news together, etc.
5. **By endpoint similarity** — Channels with similar endpoint configurations may belong together
6. **By team ownership** — If tags indicate different teams

### Best Practices

- Keep groups manageable: **5–20 channels per group** is a good range *if quota allows* — note the default channels-per-group limit is 10
- Use descriptive, lowercase, hyphenated names (e.g., `example-sports`, `staging-news`)
- Consider operational boundaries — teams that manage channels together should have them in the same group
- Each channel group gets its own egress domain, so group channels that should share a CDN origin
- AWS recommends spreading redundant channels across *different* channel groups in the same Region. Weigh that against the 3-group default quota before proposing it
- Quotas to plan against (defaults, all adjustable; see [MediaPackage v2 quotas](https://docs.aws.amazon.com/mediapackage/latest/userguide/quotas.html)): **3 channel groups per account**, 10 channels per channel group, 10 origin endpoints per channel, 25 manifests per origin endpoint. Use the applied values you read in Step 1, counting existing groups plus the ones you plan to create

### Names are permanent, and they're in the URL

Before proposing names, tell the user this — it changes how much care they'll want
to put into the answer:

- `ChannelGroupName` **cannot be changed after creation.** Renaming means deleting and
  recreating the group.
- Each channel group is assigned a **fixed egress domain for its lifetime**, and every
  channel and endpoint inside it serves from that domain. Deleting and recreating a
  group produces a **different** egress domain, which breaks every CDN configuration
  and player pointed at the old one.
- The group name is a path segment in every playback URL:
  `https://<egress-domain>/out/v1/<channelGroup>/<channel>/<endpoint>/<manifest>`

So a channel-group name is effectively permanent. Get explicit approval on the names
rather than treating them as an implementation detail.

### Default Case

If there are **fewer than 5 channels** or all channels look similar (same tags, similar names, similar configs), suggest a **single default group** and explain why:

> "You have 3 channels with similar configurations. I'd suggest putting them all in a single channel group called 'default'. You can always reorganize later."

---

## Step 5: Present Suggestions

For each suggested group, explain:

1. **Group name** (proposed)
2. **Channels assigned** (list by name/ID)
3. **Reasoning** — why these channels belong together

Example:
> Your account already has **2 channel groups** (`s3-tests`, `multiview-cg`), and the
> applied channel-group quota is **3**. So I have room for **1 more group** without a
> quota increase. Here is a plan that fits, and what a cleaner split would need.
>
> **Fits today — 1 new channel group:**
>
> **`example-all`** (9 channels)
>
> - example-sports-football, example-sports-basketball, example-sports-baseball, example-sports-hockey,
>   example-news-national, example-news-local, example-news-weather, example-news-breaking, staging-demo
> - Reasoning: 2 existing + 1 new = 3, exactly at your channel-group quota, and 9 channels
>   is within the 10-per-group limit.
>
> **Cleaner split, needs a quota increase first — 2 new channel groups** (`example-sports` 4
> channels, `example-news` 5). That is 2 existing + 2 new = **4 against a quota of 3**, so it
> cannot proceed as-is. Options: request an increase to 4 or more, use the single `example-all`
> group above, or migrate a subset now.
>
> I am not choosing between these for you. Which would you like?
>
> Does this look right? You can:
>
> - Move a channel to a different group
> - Create a new group
> - Merge or split groups
> - Rename a group

Ask for explicit confirmation or refinement.

---

## Step 5.5: Confirm the Channel Input Type

Every v1 channel takes **HLS ingest** — v1 has no other input type. A v2 channel's
`InputType` (`HLS` or `CMAF`) is set at creation and **cannot be changed later**, so
confirm it now. Ask once for the whole migration:

> Your v1 channels all receive **HLS** input. Do you want to keep **HLS input** for the
> v2 channels? That is the like-for-like choice — your encoder keeps sending exactly
> what it sends today. Switching to **CMAF input** is possible but is a change to your
> encoder's output (for MediaLive, `HlsGroupSettings` → `CmafIngestGroupSettings`), and
> the input type can't be changed after the channel is created.

- Default and recommendation: **HLS**. This is a migration; keep what v1 does.
- Only use `CMAF` if the user explicitly asks for it. Record that their encoder must
  change before cutover as a user prerequisite in the plan.
- Always set `InputType` explicitly when creating the channel. Do not rely on the default.

**Ask before defaulting to HLS: does any of this workflow depend on epoch locking?**
Epoch locking (cross-region or cross-pipeline segment alignment) requires `InputType`
`CMAF` on the v2 channel, and the channel's `OutputLockingMode`
(`create-channel --output-locking-mode`, valid only with CMAF input) must be `EPOCH_LOCKED`,
which is the default for CMAF. Both are set at creation and cannot be changed later. The HLS default cannot do it. If the answer is yes,
or the user mentions cross-region failover with identical segment names, flag CMAF
input as required here and record the encoder change (for MediaLive, a CMAF Ingest output
group with a shared custom epoch) as a user prerequisite. Getting this wrong is not
repairable by an update: it means deleting and recreating the channel.

**Also check the inventory for DVB-DASH.** The v2 `DVB_DASH` profile is only accepted on
CMAF-input channels. If any v1 endpoint on a channel uses `profile: DVB_DASH_2014`, tell
the user now: keeping that profile means CMAF input for that channel, with the same
encoder change as above. If they keep HLS input, the endpoint migrates without the
profile (as with `HBBTV_1_5`) or is held back. Record the choice in the plan.

---

## Step 6: Interactive Refinement

Support these refinement operations conversationally:

- **Move**: "Move channel X to group Y"
- **Create**: "Create a new group called Z"
- **Merge**: "Merge groups A and B into C"
- **Split**: "Split group A — move channels X and Y into a new group B"
- **Rename**: "Rename group A to B"
- **Remove**: "Remove channel X from migration" — immediately update the channel's `included` field to `false` in `.mediapackage-migration/v1-resource-inventory.json` if it was written (so the change survives session interruption), otherwise in the inventory held in context. Do not delete the channel entry from the inventory. Also remove the channel from whichever group it is currently assigned to. If this leaves the group empty, delete the group.
- **Include**: "Include channel X in migration" — set the channel's `included` field back to `true` in `.mediapackage-migration/v1-resource-inventory.json` if it was written, otherwise in the inventory held in context, and prompt the user to assign it to a group.

After each change, show the updated grouping summary.

---

## Step 7: Validate Assignments

Before proceeding, verify:

1. **Every *included* channel is assigned to exactly one group.** Channels marked as excluded during refinement are not required to be assigned.
2. **No empty groups.** Every group has at least one channel. If a group becomes empty after removals, delete it.
3. If any *included* channel is unassigned, proactively ask: "Channel '<name>' isn't assigned to any group. Where should it go?"
4. **No excluded channels in groups.** Verify no channel with `included: false` remains assigned to any group. If found, remove it from the group.
5. **The plan fits the quotas.** `existing groups + new groups ≤ channel-group quota`, and no group exceeds the channels-per-group limit. If either fails, go back to "If the plan doesn't fit, stop and ask" — do not quietly rebalance.
6. **Names are approved.** Every channel group name has been explicitly confirmed by the user, having been told the name is permanent and appears in playback URLs.
7. **Input type is decided.** The user has confirmed `HLS` (or explicitly chosen `CMAF`) for the v2 channels.

---

## Step 8: Confirm and Save

Present the final grouping summary and ask for explicit confirmation:

> Here's the final channel group plan:
>
> | Channel Group | Channels | Count |
> |---|---|---|
> | example-all (new) | example-sports-football, ... | 9 |
>
> **All 9 channels are assigned.** 2 existing groups + 1 new = 3, at your quota of 3.
> Channel input type: **HLS** (as confirmed). Shall I proceed to endpoint configuration
> planning?

On confirmation, save the assignments to `.mediapackage-migration/migration-plan.json`:

```json
{
  "channelGroupAssignments": [
    {
      "channelGroupName": "example-all",
      "description": "All example channels",
      "v1ChannelIds": ["example-sports-football", "example-sports-basketball", ...]
    }
  ],
  "channelInputType": "HLS"
}
```

---

## Step 9: Hand Off

Tell the user: "Channel group planning is complete. Ready to map configurations? You can say 'map configurations' to continue."
