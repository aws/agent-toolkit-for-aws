---
description: Run automated UAT tests (UI or API) using a test profile on the AWS DevOps Agent
argument-hint: [test profile ID]
---

Read and follow the `running-release-tests` skill for full execution details.

## Step 0 — Choose your execution path (DO THIS FIRST)

Check your available tools. Do you have ALL of these tools?

- `aws_devops_agent__create_release_testing_job`
- `aws_devops_agent__get_task`
- `aws_devops_agent__list_journal_records`
- `aws_devops_agent__get_release_ui_testing_report`
- `aws_devops_agent__get_release_api_testing_report`

These tools are NOT deferred/lazy-loaded — if they do not appear in your tool list, they are unavailable. Do NOT search for them via ToolSearch.

- **YES (all present)** → Use the "Remote Server" path (steps 4-8 below)
- **NO** → Tell the user: "Remote server not configured." Then prompt the user with instructions from the `setup-devops-agent` skill if they intend to set up the connection. If not, mention that you are "proceeding with the AWS CLI fallback." Then use the Fallback (CLI) path below.

---

## Steps 1-3 — Common to both paths (see skill: "Gathering test parameters")

1. If `$ARGUMENTS` contains a test profile ID (e.g., `ki-12345`), use it directly.
2. If `$ARGUMENTS` is empty, ask the user which test profile to use.
3. Ask if the user has a specific test requirement or focus area.

## Steps 4-8 — Remote Server path (see skill: "Core workflow")

1. Call `aws_devops_agent__create_release_testing_job(test_profile_id="...", webhook_event_message="...")`.
2. Tell the user tests take 10+ minutes and you'll keep them posted.
3. Poll `aws_devops_agent__get_task(task_id=TASK_ID)` every 30s.
4. Stream progress via `aws_devops_agent__list_journal_records(execution_id=EXEC_ID, order="ASC")`.
5. On `COMPLETED`: call `aws_devops_agent__get_release_ui_testing_report(execution_id=EXEC_ID)` (UI) or `aws_devops_agent__get_release_api_testing_report(execution_id=EXEC_ID)` (API), and save to file.

## Steps 9-12 — Fallback (CLI) path

Use this path when the remote server tools are unavailable.

1. List agent spaces with `aws devops-agent list-agent-spaces --region us-east-1` and ask the user which one to use.
2. Start the job:

    ```
    aws devops-agent create-backlog-task \
      --agent-space-id SPACE_ID \
      --task-type RELEASE_TESTING \
      --title 'Release Testing' \
      --priority MEDIUM \
      --description '{"testProfileId": "<PROFILE_ID>", "webhookEventMessage": "<REQUIREMENT>"}' \
      --region us-east-1
    ```

3. Poll for status every 30s:

    ```
    aws devops-agent get-backlog-task \
      --agent-space-id SPACE_ID \
      --task-id TASK_ID \
      --region us-east-1
    ```

4. On completion, retrieve the report. For UI testing, use --record-type qa_ui_testing_report, and for API testing, use --record-type qa_api_testing_report:

    ```
    aws devops-agent list-journal-records \
      --agent-space-id SPACE_ID \
      --execution-id EXEC_ID \
      --record-type qa_ui_testing_report \
      --order ASC \
      --region us-east-1
    ```

    Save to file.

---

If `$ARGUMENTS` is empty and no test profile ID is provided, prompt the user.
