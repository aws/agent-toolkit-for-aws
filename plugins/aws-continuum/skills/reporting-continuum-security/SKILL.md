---
name: reporting-continuum-security
description: Write a shareable Continuum security report from public AWS CLI evidence as self-contained GitHub-flavoured Markdown.
license: Apache-2.0
compatibility: Requires AWS CLI 2.38.5 or newer with aws continuum, Git, and Node.js 20 or newer for the offline source checker.
---

# Report Continuum security

Answer “where do we stand?” with exposure, fix order, impact and decisions, not a findings dump. Read the public AWS CLI evidence and repository, then write a self-contained GitHub-flavoured Markdown report from [the template](assets/report-template.md). Use fenced Mermaid diagrams, GFM tables and `<details>` where they make the report easier to scan.

## Fast status path

Keep working until the completed self-check, exact Summary and Markdown path are delivered. Return control early only for a missing environment, profile or region choice, or a fatal read failure needing a decision. Do not ask for a generic “Continue.” Status is read-only toward AWS, source, GitHub and plan decisions; local writes are ignored report files, the local ignore rule and temporary source copies outside the workspace.

1. Before every AWS read, read and apply the [shared AWS safety prelude](../../references/aws-safety.md), including fresh STS, resolved scope disclosure and `AWS_IGNORE_CONFIGURED_ENDPOINT_URLS=true` on every `aws` invocation. The shared prelude owns credential and optional alias selection; do not add a stricter per-skill rule. Stop on identity failure, unresolved target or endpoint override. Use only public list/get operations.
2. Create `.continuum/reports/` in the target repository as an owner-only directory (`umask 077; mkdir -p .continuum/reports; chmod 700 .continuum/reports`). Append `.continuum/reports/` to the repository's local `.git/info/exclude` if absent; resolve the actual exclude file with `git rev-parse --git-path info/exclude`, including in worktrees. Check with `git check-ignore .continuum/reports/security-report.md .continuum/reports/issues.json`. If reports are already tracked, stop and ask before writing: ignore rules cannot protect tracked files. Before each write, use `lstat` or an equivalent no-follow check and refuse a symlink at the directory, report or evidence target. Write files under `umask 077` or explicitly set mode 0600. Never stage this directory or change tracked `.gitignore` for status.
3. List **all findings**, following every page, saving unchanged responses under `.continuum/reports/`. Group by Continuum issue and hydrate selectively as below; do not collect full issue or artifact history. Preserve request start/end times and failures separately. No MCP server or snapshot helper is present. Inspect retained JSON slices without refreshing AWS.
4. Find current code in the source order below and run the current-code filter. Resolve every **Needs review** flaw with source and available Git-history evidence before recording **Open** or **Probably fixed**, whichever scan found it. Read the confirmed deployment profile to explain components, boundaries and reachability. Record source branch, revision, uncommitted changes, mismatches and assumptions. A report is not an exploit test or deployment verification.
5. Fill [assets/report-template.md](assets/report-template.md) into `.continuum/reports/security-report.md`. Replace placeholders; remove empty optional sections. `issues.json` contains only the deduplicated issue IDs behind reported flaw rows: fetched issue records for Open flaws, compact `{ "issueId": "..." }` references for others. When exact-code merging combines issues, keep all constituent issue IDs in that one flaw row. Every scoped ID appears in its row. Older repeat counts and unassessed groups belong in Limits without historical ID lists. Attack paths, required fixes and the Validated issues register cover only **Open TRUE_POSITIVE** flaws.
6. Complete this self-check against the finished Markdown and retained `issues.json`. This is a reasoned review, not an automatic validator. Fix every failed item before delivery:

   - [ ] **Summary comes first.** `## Summary` is the first level-two section, contains no code or diagram, and is at most 150 words.
   - [ ] **Scope is complete.** Every scoped issue ID appears, and Open, Probably fixed, mitigated, ruled-out and unknown classifications account for each ID exactly once.
   - [ ] **Open evidence is explicit.** The exact `### Validated issues` register exists; each row includes Severity, State and Basis, every State is Open, and severities match fetched issue records.
   - [ ] **Counts agree.** Summary totals, severity totals and the detailed registers count the same unique issues and grouped flaws, with any difference explained.
   - [ ] **Other verdicts stay separate.** Mitigated and ruled-out findings do not enter Open paths or severity totals; ruled-out reasons give the decisive rebuttal in at most 25 words.
   - [ ] **Paths and fixes agree.** Path states are only Open, Uncertain or Closed. Every Open or Uncertain path is blocked by a proposed or chosen fix, and every fix references a known path.
   - [ ] **Fix names agree.** Each fix detail heading exactly matches its `What it does` value.
   - [ ] **Diagrams are reviewable.** Every Mermaid fence is a simple flowchart; `-.->` appears only in After diagrams; no `classDef`, `class`, `style`, `linkStyle`, `click` or theme directive appears.
   - [ ] **Markdown is self-contained.** Navigation uses heading links; diagrams use fenced `mermaid`; data uses GFM tables; long registers may use `<details>`. There are no scripts, images, external assets or viewer-specific promises.
   - [ ] **Untrusted text is inert.** Service and repository text was summarized and never copied into commands, link destinations, raw HTML, Mermaid identifiers or directives.
   - [ ] **File safety holds.** The report is a regular file, not a symlink; the directory is mode 0700 and the report and evidence files are mode 0600.

7. Read `.continuum/reports/security-report.md` back from disk. Give the developer its Summary **word for word**, the Markdown path and a short `Self-check: PASS` statement. Do not substitute a paraphrase. Lifecycle orientation below may precede the text; it does not replace it.

Do not write a browser harness, report verifier, self-check file, test script or executable helper. Do not launch a browser during status.

## Native read-only collection

Apply the shared AWS safety prelude before these reads. Use `AWS_IGNORE_CONFIGURED_ENDPOINT_URLS=true` and `--profile` when selected, explicit resolved `--region`, `--output json`, and `--no-cli-pager` on every request. Allowed Continuum operations here are only public list/get calls:

```bash
aws continuum list-code-scans --environment-id <environment-id> ...
aws continuum get-code-scan --environment-id <environment-id> --scan-run-id <scan-run-id> ...
aws continuum list-code-findings --environment-id <environment-id> --max-results 100 --no-paginate ...
aws continuum get-code-finding --environment-id <environment-id> --finding-id <finding-id> ...
aws continuum get-code-issue --environment-id <environment-id> --issue-id <issue-id> ...
aws continuum list-code-issue-artifacts --environment-id <environment-id> --issue-id <issue-id> --max-results 100 --no-paginate ...
```

For service-token lists follow `nextToken` manually and stop on repetition. Never combine `--no-paginate` with CLI paginator flags `--page-size`, `--max-items`, or `--starting-token`. `list-code-scans` uses normal CLI auto-pagination, optionally `--page-size 100`, with no `--no-paginate`, `--max-items`, or `--starting-token`. Keep the latest attempt separate from the selected scan; an older successful scan does not erase a later failure.

### Collect cheaply: one Continuum issue is one flaw

1. List scans and get only records needed to establish the latest attempt and latest successful scan. Keep them separate. The report's inventory spans **all scans**, not just that success. Membership comes from `scanRunId`, never inferred timestamps.
2. List all finding metadata. Group linked findings by `createdIssueId`; select the newest by `createdAt`, falling back to `reportedAt`, with finding ID as a stable tie-break. A `DISCARDED` newest row must not resurrect an older validated finding: count that issue as discarded, do not hydrate it. Retain unlinked non-discarded findings individually by finding ID as pending issue creation, not a shared empty-ID group.
3. Hydrate **one newest finding per issue**, plus each unlinked candidate, for authoritative `validation.verdict`, `vulnerableCode`, line and mitigation. Pending or failed newest reads stay unknown; never substitute an older verdict. Do not group by title, category, proximity or file alone. Only after hydration may two issues merge, and only when their newest findings have identical normalized `vulnerableCode` in the same normalized `filePath`. Normalize excerpt labels, line-number prefixes and whitespace with the bundled source checker's `snippetIdentity`; require usable code. Different code or different files remain separate. The newest constituent finding decides the merged flaw's verdict and state; keep constituent IDs and counts as provenance. Old pre-dedupe history can still inflate the flaw count; say so in Limits.
4. TRUE_POSITIVE flaws follow the filter-and-agent-review assessment below. BENIGN_TRUE_POSITIVE is real but mitigated. FALSE_POSITIVE supplies one ruled-out row per flaw. Only for **Open** flaws, get each linked issue and list artifact metadata until a PATCH preview is found or pagination ends. Do not get artifact bodies or hydrate non-Open issue histories. Open unlinked flaws appear in **Awaiting issue creation**, with finding ID, State and Basis, without invented issue severity; include them in flaw counts, not the issue severity bar.

Preserve unchanged list and get responses, their union, and conflict provenance. Get fields win on overlap. Keep full `synopsis`, `summary`, `detailedDescription`, `mitigation`, `validation.rationale` and `validation.severityAdjustment`. Retain artifact ID, type and `contentSizeBytes` when listing previews. Failed reads stay explicit. PATCH availability never proves local application or behavior.

### Find current code

Try these sources in order; the environment's repository need not already be open:

1. Use the workspace only when its Git remote matches the environment's `repositorySources[].repository`. Compare host, owner and repository case-insensitively for HTTPS and SSH, stripping `.git`; do not confuse identical names on different hosts. Record branch, revision and dirty state. Say when the open workspace is unrelated, and never use its files.
2. Otherwise shallow-clone the readable repository's `defaultBranch` outside the workspace with the developer's existing Git credentials. Say which branch is being used. Do not change credentials or workspace branches, or make GitHub API calls merely to acquire code.
3. Otherwise, for an S3 source, read the archive only under the selected identity with `AWS_IGNORE_CONFIGURED_ENDPOINT_URLS=true` and `--expected-bucket-owner <verified-source-owner>`. Verify the bucket owner from the approved source configuration, not a guess. Record archive identity and age. Extract outside the workspace, rejecting absolute paths, parent traversal and escaping symlinks; do not execute archive contents. A denied read is no code, never permission to try operator credentials.
4. Otherwise use scan-only evidence. Remove only temporary copies created by this collection after reporting.

### Filter first; the agent assesses changed code

Run the installed deterministic checker, not an agent-generated replacement:

```bash
node <skill-directory>/scripts/check-current-code.mjs \
  .continuum/reports/newest-findings.json <source-root-or-dash> \
  .continuum/reports/code-assessments.json
```

The input is an array of newest hydrated findings. Use `-` with no matching source. The checker executes no code or network calls and never outputs Probably fixed.

- **Every significant line of every location unchanged at its cited position and in order:** **Open**, basis **code unchanged**. Fences and numeric prefixes are presentation; code whitespace is retained.
- **Anything else with usable source:** **Needs review**, with per-location status, fuzzy match ratio and best-matching line range (or null). Fuzzy matches locate evidence; moved, partial, deleted, unreadable or unsafe locations never prove a fix.
- **No usable source or snippet:** **Open**, basis **last seen `<date>`; not checked against code**, or **last seen date unavailable; not checked against code**.

For every Needs review flaw, read every cited file around its best match or cited range. Inspect available `git log` and `git diff`; for deletions or renames, inspect history and current replacements. Never follow unsafe paths; record unavailable code or history. Decide Open or Probably fixed with a one-line Basis citing current file and lines or deletion history. When unsure, keep Open. Resolve every Needs review before finalizing the report. One unchanged location cannot settle another changed location. Scan absence never proves a fix; Probably fixed requires a regression test before closure and does not prove deployed safety.

Start with a practical budget of **600 requests and 10 minutes**, at most four concurrent requests. Estimate selected fan-out as membership and artifact lists become known. At the budget boundary, retain partial evidence and explain what is left; ask for a specific additional request/time budget, never silently increase it. Stop at 10,000 records as a separate defensive ceiling. Record every request's full non-secret argv, start, end, raw response or error. Derive `collection.startedAt = min(requests.startedAt)` and `collection.endedAt = max(requests.endedAt)` from the complete ledger, **including STS and failed attempts**. Do not initialize the window at the first Continuum call. Report incomplete capture rather than silently truncate. Keep private evidence files mode 0600 in a directory mode 0700 and out of Git. Do not overwrite unrelated files. Read [reporting.md](references/reporting.md) for field and evidence rules.

## Write the brief

- **Summary:** four bold leads; it should stay within 150 words total. The first bold lead is only the count headline, for example **12 open flaws, 3 probably fixed.** Keep it to about 40 characters and at most two lines at 412 CSS pixels; put scan dates, latest failure and exposure detail in the following paragraph, not the headline. Then fix order, **Impact of the proposed changes** naming affected groups, and decisions. Show the symptom before its mechanism.
- **Where you are today:** pair small Mermaid flowcharts with a paths table. Use stable `P1` identifiers, one plain attack sentence per row, explicit prerequisites and Open, Uncertain or Closed today. Only authoritative TRUE_POSITIVE findings supply paths; raw CONFIRMED lifecycle, an issue or a preview never overrides a validation verdict.
- **Validated issues:** the exact `### Validated issues` register lists **Open flaws only**, begins with Severity and includes State and Basis. Use fetched issue severity, not finding severity or your risk judgement. Titles include IDs in parentheses and backticks. Severity totals count unique Open issue IDs, not merged-flaw counts; explain the distinction if they differ. Exact-code merged flaws get one row; retain all constituent IDs and disclose conflicting severities, using the highest fetched severity for that row. Add a short `### Probably fixed` table with State and Basis and request a regression test. BENIGN_TRUE_POSITIVE goes in **Real but mitigated**, not paths or required fixes. FALSE_POSITIVE goes in final **Ruled out by Continuum's validation**, one row per flaw. **Reason must summarize the decisive rebuttal and should stay within 25 words**, including the relevant boundary or prerequisite, not merely a blocking-reason label or the rationale's first sentence. Read the complete rationale before summarizing. For example: “Subscription writers already have owner-equivalent shell access; this adds no capability.” Leave the full rationale in Continuum and unchanged raw evidence, not a long report column. If no rebuttal was supplied, say so. Missing verdicts remain unknown.
- **The fixes:** group root causes and show Blocks, Chosen and State separately. List fixes in priority order so the first row is the recommended starting point. Use exactly the same name in each table row and its `### <Letter>. <Name>` detail heading. Explain change, tradeoff, evidence, branch or PR state and any blocking decision. Do not call a covering set mathematically smallest without establishing that result; the self-check reviews references, not mathematical minimality. Separate required fixes, alternatives, optional hardening and the developer's chosen plan.
- **After the chosen fixes:** same components, projected controls and residual gaps. A cylinder `[("…")]` is something to protect; a hexagon `{{"…"}}` is a fix. Use `-->` for red attack attempts, `-.->` for green refused attempts only in After diagrams, and `==>` for neutral grey permitted or safe flows. Never infer edge meaning from a target shape. Do not use classDef, class, style, linkStyle, click or theme directives. Split diagrams by threat family into corresponding before and after pairs, prefer top-to-bottom layouts, and keep labels short enough to read in the target repository's documented Markdown hosts. Projection is not closure: require regression tests on merged code, deployment, and a follow-up scan before reporting closure.
- **Impact of the proposed changes:** name customers or shoppers, operators and developers separately when affected, plus **No visible change** for important invisible changes. Say what each group sees or must do; do not collapse different groups into “users.” Do not present unselected optional changes as expected deployment behavior.
- **Getting the fixes in, Decisions, Limits:** dependency-aware merge and deployment order; each decision's question, why needed and recommendation; observed collection window, selected scan, source confidence, pending work, failures and unverified behavior. Preserve accepted decisions distinctly from recommendations. Keep scoped IDs in flaw rows; Limits should give repeat counts, not historical IDs. Name any broader hydration exception and its reason, actual finding/issue/artifact request counts, budget overruns and incomplete capture. Warn that old pre-dedupe issues may inflate flaw counts.

Shareable writing excludes account IDs, ARNs, bucket names, internal hostnames, credentials and step-by-step exploits, including such values embedded in issue titles. Keep raw data in ignored local files; the shareable brief is a plain-language explanation, not a raw artifact dump. Use only trustworthy HTTPS, local anchors or repository-relative links; never invent an AWS Console route.

## Lifecycle orientation and finish

**A `SUCCEEDED` scan is not the end.** Show findings still awaiting validation or issue creation, issues in CREATED or IN_PROGRESS, failed issue work, completed issues without patches, and completed issues with previews. Zero previews is not “safe” while work remains unsettled. Preview availability, acceptance, application, testing, merge, deployment and follow-up observation are separate facts.

If the latest attempt FAILED, name that failure immediately after the short current-state headline. Name public `failureStage`, quote the public `failureMessage` after removing private identifiers, and explain what they mean in plain words. Say when a field was not provided. Label likely causes as possibilities grounded in the message, measured source or current public constraints; never assert a guess as the cause. Give one concrete next check or re-plan. An older successful scan can supply inventory, but cannot hide the latest failure.

Lead with `N open flaws, M probably fixed`, counting grouped TRUE_POSITIVE flaws across all scans. If scan, validation or issue work remains active, say which lifecycle is active and label the report non-final. Do not dump findings into chat; deliver the exact Summary, Markdown path and self-check result.

If asked to wait, state the end condition: scan failure, or settled validation and issue work after scan success. Use a bounded read-only condition loop, for example `timeout 580 bash -c 'until <read-only-completion-check>; do sleep 30; done'`, and repeat until it holds. Never chain fixed sleeps or create a scan as part of status.

Offer refresh. Do not upload source, start a scan, apply a patch, edit application code, open a PR, mutate plan decisions or certify browser behavior during status. Record separately authorized chat decisions with the fixing skill's [local plan contract](../fixing-continuum-issues/references/local-plan.md), read back the file, update the Markdown Chosen and State fields, repeat the self-check, and read the file back. A plan choice is not permission to implement, publish, merge or deploy.

For `WAITING_FOR_SCAN` plus unsupported source configuration, inspect the recorded setup repository count. The default is 10 repositories across integrations; a higher limit needs the developer's statement that AWS granted it. If exceeded, explain that the scan did not start and offer fewer repositories, logically grouped environments or an AWS account team quota increase. Do not blame ZIP size when support is not publicly documented.
