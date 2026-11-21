# Web handoff: plan.json and AWS credits

The main window runs this handoff at two points: when the user chooses Done-for-now at the Estimate decision, and after Generate emits `HANDOFF_OK`. It is an optional enhancement and never a gate. On any skip or error the migration result is still complete; continue without it and do not surface the writer output to the user.

## Write plan.json (fail-open)

Run, with absolute paths so the working directory is not load-bearing:

```bash
uv run --project "$SKILL_BASE/scripts" --frozen python \
  "$SKILL_BASE/scripts/emit-plan-json.py" --migration-dir "$MIGRATION_DIR" --plugin-json "$PLUGIN_ROOT/.claude-plugin/plugin.json"
```

The writer reads `.phase-status.json` and `estimation-infra.json`, writes `$MIGRATION_DIR/plan.json`, and prints `PLAN_OK | …` or `PLAN_SKIP | reason=…`. It copies validated values only. Render's baseline is copied only when `current_costs.currency` is `USD`, and the AWS total is the known-cost figure of the capacity-preserving scenario. When that figure is a floor, unpriced lines never appear as service items.

If it printed `PLAN_SKIP`, omit everything below: there is no file to upload and no credits link.

## When the writer printed PLAN_OK

Do these in order.

1. Name `plan.json` once in the closing message as plain text with no link: `plan.json — upload it at AWS Startup Advisor (https://startups.aws.com/migrate/plans/import?source=plugin) to see if you qualify for AWS credits`, with the import page's address written out. The clickable link is the What's next block below.
2. Show the user their `plan.json`. The `.migration` folder is hidden by default on macOS and Linux, so open the file's location instead of leaving the user to find it. Run the command for the user's OS once, as an ordinary command, without asking separately first:
   - macOS: `open -R "$MIGRATION_DIR/plan.json"` opens Finder with the file selected.
   - Windows: `MSYS_NO_PATHCONV=1 explorer.exe /select,"<absolute Windows path to plan.json>"`. In Git Bash get the path with `cygpath -w "$MIGRATION_DIR/plan.json"`. `explorer.exe` exits non-zero even when it succeeds, so treat it as opened unless it prints an error.
   - Linux: `xdg-open "$MIGRATION_DIR"` opens the folder; it cannot select the file.
3. Show exactly one of the messages below as plain text, not in a code block. Do not reword them; this copy is owned by the web experience. If the folder opened:

   > **The folder is open with your plan.json selected.**

   On Linux show **The folder with your plan.json is open.** instead. If the command failed, was unavailable, or the user declined it, show this as its own message, separate from the phase summary, with `<absolute path to plan.json>` replaced by the real path:

   > The folder did not open. The open command is blocked in your permissions.
   >
   > Your plan.json is saved at:
   > `<absolute path to plan.json>`
   >
   > The .migration folder is hidden by default on macOS. In Finder, press Command + Shift + Period (.) to show it.

   On Linux use "The .migration folder is hidden by default on Linux. In your file manager, press Ctrl + H to show it." as the last line. On Windows omit the last line. If the migration report also failed to open, start with "The report and the folder did not open." Keep "The open command is blocked in your permissions." only when a permission rule blocked it.
4. Append the What's next block verbatim, replacing `<run_id>` in the link with the run's `run_id` from `.phase-status.json`, lowercased when it is a UUID so the `run=` value matches the plan's `runId`. It must begin with the "💬 What's next" heading, and the call to action must be a Markdown link with no bare URL. Never name AWS Startup Advisor's import page without its address: if you shorten or restate any of this, keep the address. (The plain-text mention uses `?source=plugin` without `run=` on purpose, to stay short; the two links in this block carry the run.) Do not reword it; this copy is owned by the web experience:

   > **💬 What's next**
   >
   > - **Refine your plan**
   >   Tell me what to change. For example: "use Fargate instead," "make it multi-region," or "reduce the cost."
   > - **See your AWS credits**
   >   Sign in with your AWS Builder ID (or create one) on [AWS Startup Advisor](https://startups.aws.com/migrate/plans/import?source=plugin&run=<run_id>), the AWS Startups site where you import your migration plan, then upload plan.json to see the AWS migration credits you qualify for.
   >
   > [Go to AWS Startup Advisor →](https://startups.aws.com/migrate/plans/import?source=plugin&run=<run_id>)
   >
   > After you upload, you also get:
   >
   > - Interactive plan dashboard
   > - Monthly cost estimate
   > - Migration paths: AI agent, AWS expert, or AWS Partner

Ship note: the writer is gated off in code (`RENDER_TO_AWS` is absent from `SKILL_TO_PLATFORM`), so it prints `PLAN_SKIP` and writes no file. Re-enable it by restoring that one entry only after the import page and the ImportPlan API both accept the `RENDER` source platform in production. This handoff is separate from any base64url plan-share link.
