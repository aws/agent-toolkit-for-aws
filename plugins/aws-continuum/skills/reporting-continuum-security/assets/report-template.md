<!-- markdownlint-disable MD032 MD033 -->
<!--
Report template. The reporting skill gives this to the coding agent.
The agent copies it, replaces every <placeholder>, deletes sections that have nothing
to say, and runs: node <skill-directory>/scripts/render-report.mjs report.md issues.json out.html
issues.json is { "items": [...] } for reported flaws only. Group by createdIssueId,
hydrate one newest finding per issue, and merge only identical normalized newest
vulnerableCode in the same file. Keep all constituent issue IDs in a merged flaw row. Open rows use fetched issue records; other rows
may use { "issueId": "..." } references. Every scoped ID appears in its flaw row.
Limits should use older duplicate counts rather than historical ID lists.

Write for a developer with no context. Plain words, short sentences, no jargon.
Name the symptom an attacker or user would see before explaining the cause.
The Summary has four bold leads: exposure, fix order, Impact of the proposed changes,
and decisions. All four answers should stay within 150 words.

Shareable writing: no account IDs, ARNs, bucket names, internal hostnames, credentials
or step-by-step exploits. Describe each attack in one plain sentence. Validation
verdicts are authoritative: only Open TRUE_POSITIVE flaws supply paths and fixes.

Split flowcharts by threat family, using corresponding before and after pairs.
Prefer top-to-bottom (TB) layouts and short labels. Keep native width below about
1,100 px. The parse-only Node check warns from a conservative width estimate, not
an actual layout measurement; the browser measures the real SVG and warns above
1,100 px. Fit whole figure is an overview; Readable size restores legible labels.
A cylinder [("…")] means a protected asset; a hexagon {{"…"}} means a proposed fix.
Use exactly three edge meanings, with optional short labels:
  --> is an attack attempt (red).
  -.-> is a refused attack attempt (green), only in an After diagram.
  ==> is a permitted or safe flow (neutral grey), even if it enters a fix.
Do not add classDef, class, style, linkStyle or theme directives; they are rejected.
The renderer owns the palette, visible legend and both light and dark themes.

The script checks these things:
  1. "## Summary" comes first and has no diagram. It should stay within 150 words (warning). It is printed in chat.
  2. Every issue ID in issues.json appears somewhere in the report.
  3. The "Path" table and the "Fix" table agree: every path that is open or uncertain today
     is blocked by at least one chosen fix, or the script warns that it stays open.
  4. Every Mermaid flowchart parses.
  5. The exact ### Validated issues register is required, even when its table has
     no rows (explicitly zero). Include State and Basis; only Open flaws belong here.
     Missing evidence is an error, never a zero count. The severity bar counts only
     its IDs and checks each row's severity against the fetched issue.
     Probably fixed rows have their own State and Basis table and do not enter the bar.
     Their Basis must give the agent's current-code evidence with file and lines.
     Needs review is not a final state. Scan absence cannot justify a fix; prose wording warns.
  6. Ruled-out tables have exactly Issue and Reason columns, with no Severity or
     legacy rationale column. Reason is the decisive rebuttal and should stay within 25 words (warning).
     Migrate legacy explanations into Reason; keep full rationales in raw evidence.
     Put scoped IDs in (`issue-id`) form.
Fixes are listed in priority order. Every ### <Letter>. <Name> detail heading uses
exactly the same name as its row's What it does field; include a detail for each fix.
Keep Proposed, Chosen, Patch preview, Tested, Merged and Deployed separate.
Raw HTML and images are shown as text. Links must be https://, #anchors, or repository-relative paths.
-->

# <Application>: security report

## Summary

**<N> open flaws, <M> probably fixed.** <One-sentence exposure detail. Keep the bold count headline alone, about 40 characters, no more than two lines at 412 CSS pixels.> Latest successful scan: <date>. <Latest attempt failed on date and stage, if applicable.>

**Proposed covering fixes for the modeled paths:** <fix letter and name>, and <fix letter and name>. <Their state: ready, in a PR, or waiting on a decision.>

**Impact of the proposed changes:** <who notices what, naming each affected group, for example customers, operators or developers; or "No visible change">.

**<"Nothing needs your decision." or the open question, asked plainly.>** Next step: <one concrete action>.

## Where you are today

<One sentence on what the diagram shows.>

```mermaid
flowchart TB
  %% Draw the real components. Use a subgraph for each trust boundary.
  %% Label each attack edge with what the attacker does, in words, plus its path IDs.
  %% Mark the protected asset, for example with a cylinder node [("...")].
```

| Path | What an attacker can do | Route | Issue | Today |
|---|---|---|---|---|
| P1 | <plain sentence> | <A → B → C> | <severity: issue title> (`<issue-id>`) | <Open, Uncertain or Closed> |

### Validated issues

| Severity | Issue | State | Basis | Continuum status | Patch |
|---|---|---|---|---|---|
| <Critical> | <title> (`<issue-id>`) | Open | <code unchanged, agent evidence, or last seen date; not checked against code> | <Validated, in progress, …> | <Patch preview ready, none, or unknown read> |

### Awaiting issue creation

<Optional: delete if empty. Open validated flaws without createdIssueId count in the
Summary, not the issue severity bar. Do not invent issue severity.>

| Flaw | Finding | State | Basis |
|---|---|---|---|
| <title> | `<finding-id>` | Open | <code unchanged, agent evidence, or last seen date; not checked against code> |

### Probably fixed

<Optional: delete if empty. Confirm with a regression test; only checked code
change justifies Probably fixed. Absence from a later scan is not proof. No paths or fixes above
are supplied by these rows.>

| Issue | State | Basis |
|---|---|---|
| <title> (`<issue-id>`) | Probably fixed | <current file and lines or deletion history; why the flaw no longer applies> |

### Real but mitigated

<Optional: delete this subsection if empty. BENIGN_TRUE_POSITIVE findings are real
patterns with effective mitigations, not open attack paths or required fixes.>

| Issue | Why the risk is mitigated |
|---|---|
| <title> (`<issue-id>`) | <plain explanation from latest validation; one row per grouped flaw> |

## The fixes

<One or two sentences: proposed covering fixes for the modeled Open paths, with alternatives and optional hardening kept separate. Use smallest only with stated proof and scope.>

| Fix | What it does | Blocks | Chosen | State |
|---|---|---|---|---|
| A | <Fix name> | <P1, P2> | <Proposed, Yes, or No and why> | <Patch preview, PR link, or Needs a decision> |

### <Letter>. <Fix name>

<What changes in the code, one or two sentences.> **Tradeoff:** <what it costs>. <Recorded decision, if any.> <Branch, PR or local draft link.>

## After the chosen fixes

<Say that this is a projection: a path counts as closed only after the regression tests pass on the merged code, the fix is deployed, and a follow-up scan agrees.>

```mermaid
flowchart TB
  %% Same components as today. Put each chosen fix where it blocks the attack,
  %% for example as a {{"B: origin check"}} node on the edge it cuts.
```

## Impact of the proposed changes

<One sentence: who is affected and how much, in plain words. Name each group separately; do not write "users" when customers and operators are affected differently. Drop a group that has nothing to say.>

**<Group, for example Customers>:**
- **<Change>.** <What they see or must do, and when.>

**<Another group, for example Operators>:**
- **<Change>.** <What they see or must do.>

**No visible change:**
- **<Change>.** <Why it still matters.>

## Getting the fixes in

1. <Prerequisite or migration.>
2. <Review and merge, in order, and why that order.>
3. <Deploy.>
4. <Validate: regression tests, the journeys that must keep working, a follow-up scan.>

## Decisions

<Open questions first, each with why it matters and a recommendation. Then decisions already recorded, with the answer. Say "None open" if so.>

## Limits

- <Source used, branch and revision or archive age; workspace mismatch or inaccessible code.>
- <Latest successful scan date, latest failed attempt, collection window and failed reads.>
- <N> probably fixed flaws need regression tests; <M> older duplicate issues omitted (counts only, no IDs).
- <Pending or unknown newest verdicts; what this report could not see or prove.>
- <Old pre-dedupe issues may inflate flaw counts; exact-code merges, issue units and hydration calls.>
- <Any broader hydration exception, why it was necessary, budget overruns and missing capture.>

## Ruled out by Continuum's validation

<Optional final section: delete if empty. One row per FALSE_POSITIVE flaw. Reason
keeps the decisive rebuttal and relevant boundary or prerequisite and should stay
within 25 words, not the allegation, a generic blocking-reason label or the rationale's first
sentence. Read the complete rationale; leave the full text in Continuum and raw
local evidence. Use exactly the Issue and Reason columns below; no extra rationale
or Severity column. Migrate legacy tables by writing the decisive rebuttal directly
in Reason, not by truncating the rationale. Example: Subscription writers already have owner-equivalent shell
access; this adds no capability. If the service omitted the rebuttal, say so.>

| Issue | Reason |
|---|---|
| <title> (`<issue-id>`) | <decisive rebuttal, at most 25 words> |
