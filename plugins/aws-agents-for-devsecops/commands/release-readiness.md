---
description: Trigger a pre-merge release readiness review on a GitHub PR, GitLab MR, or local branch
argument-hint: [PR/MR URL or repo name]
---

Read and follow the `analyzing-release-readiness` skill for full execution details.

**IMPORTANT: NEVER use `gh` CLI, `glab` CLI, `curl`, or any external tool to fetch PR/MR details. All required fields (repository, prNumber/mergeRequestIid, hostname) MUST be parsed directly from the URL string. The DevOps Agent fetches the content itself.**

## Step 0 — Choose your execution path (DO THIS FIRST)

Check your available tools. Do you have ALL of these tools?

- `aws_devops_agent__create_release_readiness_review`
- `aws_devops_agent__get_task`
- `aws_devops_agent__list_journal_records`
- `aws_devops_agent__get_release_readiness_report`

These tools are NOT deferred/lazy-loaded — if they do not appear in your tool list, they are unavailable. Do NOT search for them via ToolSearch.

- **YES (all present)** → Use the "Remote Server" path below
- **NO** → Tell the user: "Remote server not configured." Then prompt the user with instructions from the `setup-devops-agent` skill if they intend to set up the connection. If not, mention that you are "proceeding with the AWS CLI fallback." Then use the Fallback (CLI) path below.

---

## Common to both paths (see skill: "Gathering execution parameters")

1. If `$ARGUMENTS` contains a URL (github.com or gitlab.com), parse the PR/MR details directly from the URL string — do NOT fetch or inspect the PR via any tool.
2. If `$ARGUMENTS` is a repo name or path, use the "Local GitHub/GitLab repo" flow below.
3. If `$ARGUMENTS` is empty, check the current git repository and use the local flow.
4. Build the `content` object following the skill's "Gathering execution parameters" section.
5. Ask the user about automated testing (static-only vs full analysis). Do NOT proceed until the user answers.

## Remote Server path (see skill: "Core workflow")

1. Call `aws_devops_agent__create_release_readiness_review(content={...}, skip_automated_testing=...)`.
2. Poll `aws_devops_agent__get_task(task_id=TASK_ID)` every 30s.
3. Stream progress via `aws_devops_agent__list_journal_records(execution_id=EXEC_ID, order="ASC")`.
4. On `COMPLETED`: call `aws_devops_agent__get_release_readiness_report(execution_id=EXEC_ID)`, save to file, and run the auto-fix flow from the skill.

## Fallback (CLI) path

Use this path when the remote server tools are unavailable.

1. List agent spaces with `aws devops-agent list-agent-spaces --region us-east-1` and ask the user which one to use. **Do NOT proceed until the user has selected one.**
2. Build the `content` object using the guidance from the `analyzing-release-readiness` skill's "Gathering execution parameters" section. Key rules: `githubPrContent`/`gitlabMrContent` MUST be an array, `prNumber`/`mergeRequestIid` MUST be strings.
3. Start the job (**CRITICAL:** `content` must be a single object, NOT wrapped in a list. Correct: `{"githubPrContent": [...]}`. Wrong: `[{"githubPrContent": [...]}]`):

    ```
    aws devops-agent create-backlog-task \
      --agent-space-id SPACE_ID \
      --task-type RELEASE_READINESS_REVIEW \
      --title 'Release Readiness Review' \
      --priority MEDIUM \
      --description '{"agentInput": {"content": <CONTENT_JSON>, "metadata": {"skipAutomatedTesting": true/false}}}' \
      --region us-east-1
    ```

4. Poll for status every 30s:

    ```
    aws devops-agent get-backlog-task \
      --agent-space-id SPACE_ID \
      --task-id TASK_ID \
      --region us-east-1
    ```

5. Stream progress — once `IN_PROGRESS`, poll journal records and present updates to the user:

    ```
    aws devops-agent list-journal-records \
      --agent-space-id SPACE_ID \
      --execution-id EXEC_ID \
      --order ASC \
      --region us-east-1
    ```

    Use `next_token` from the response to fetch only new records on subsequent polls. **Wait 15 seconds** between each poll iteration. Keep polling until the task reaches a terminal status (`COMPLETED`, `FAILED`, `CANCELED`, `TIMED_OUT`).

6. On `COMPLETED`, retrieve the report:

    ```
    aws devops-agent list-journal-records \
      --agent-space-id SPACE_ID \
      --execution-id EXEC_ID \
      --record-type release_analysis_report \
      --order ASC \
      --region us-east-1
    ```

    Save the report to `release-readiness-review-<YYYY-MM-DD-HHmmss>.md` and run the auto-fix flow from the skill.

    On `FAILED` or `TIMED_OUT`: present the error and suggest next steps. On `CANCELED`: inform the user no report is available.

7. After analysis completes, clean up the review branch (if local flow was used — see below).
8. To cancel a running job:

    ```
    aws devops-agent update-backlog-task \
      --agent-space-id SPACE_ID \
      --task-id TASK_ID \
      --task-status CANCELED \
      --region us-east-1
    ```

---

## Local GitHub/GitLab repo flow (no PR/MR URL provided)

When `$ARGUMENTS` is a repo name/path or empty (steps 2-3 above), execute this flow to prepare the content object. The review agent needs a pushed branch to read from — do NOT shortcut.

1. **Navigate to the repository directory**: `cd` to the repo root. Ask the user if needed.
2. **Determine the base branch**: Use `main` unless the user specifies otherwise. Verify:

   ```bash
   BASE_BRANCH="main"
   if ! git show-ref --verify --quiet refs/remotes/origin/$BASE_BRANCH; then
       git fetch origin $BASE_BRANCH
   fi
   ```

   If fetch fails, ask the user to specify the base branch and stop.
3. **Check for local changes**: Run `git status --short` and `git rev-list --count origin/$BASE_BRANCH..HEAD`:
   - **Clean AND not ahead**: Nothing to analyze — stop.
   - **Has uncommitted changes**: Tell the user what will be committed and pushed. **Do NOT proceed until the user approves.**
   - **Clean but ahead of remote**: Tell the user commits will be pushed. **Do NOT proceed until the user approves.**
4. **Stash uncommitted changes** (skip if clean):

   ```bash
   git stash push --include-untracked -m "release-analysis: preserve working changes"
   ```

5. **Create review branch**:

   ```bash
   ORIGINAL_BRANCH=$(git rev-parse --abbrev-ref HEAD)
   BRANCH_NAME="feat/release-readiness-review"
   git checkout -b $BRANCH_NAME 2>/dev/null || { BRANCH_NAME="feat/release-readiness-review-$(date +%Y%m%d-%H%M%S)"; git checkout -b $BRANCH_NAME; }
   ```

6. **Apply stash and commit** (skip if clean):

   ```bash
   git stash apply
   git add -A
   git commit -m "chore: snapshot for release readiness review"
   ```

   Check for sensitive files before staging — warn user if found.
7. **Push**:

   ```bash
   git push -u origin HEAD
   ```

8. **Build the content**: Extract `owner/repo` and hostname from `git remote get-url origin | sed 's|://[^@]*@|://|'`. MANDATORY: Always use the sed command, we cannot expose PAT tokens in the context window!
9. Set `headBranch` to `$BRANCH_NAME`. Use `githubPrContent` (GitHub) or `gitlabMrContent` (GitLab) as an array.
10. **After analysis completes** — clean up:

   ```bash
   git checkout $ORIGINAL_BRANCH
   git push origin --delete $BRANCH_NAME 2>/dev/null || true
   git branch -D $BRANCH_NAME 2>/dev/null || true
   ```

   If stash was used: `git stash pop`.

**Important**: Do NOT create a PR/MR — only push the branch.

---

If `$ARGUMENTS` is empty and no git repo is detected, prompt the user for a PR/MR URL or repo name.
