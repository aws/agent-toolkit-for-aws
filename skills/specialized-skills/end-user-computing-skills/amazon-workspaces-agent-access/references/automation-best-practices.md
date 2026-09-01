# Desktop Automation Best Practices

These practices come from how computer-use models actually behave: they analyze screenshots pixel-by-pixel, and the screenshot round-trip is the dominant cost in tokens and latency. Following them produces dramatically more reliable, cheaper runs.

> Tool names used below (`key`, `type_text`, `screenshot`, ...) are the desktop tools defined in [tools-reference.md](tools-reference.md). Anything described as a client-side pause or loop runs in your agent's own code, not on the desktop.

## Minimize screenshots (the #1 rule)

Screenshots are large image payloads. A naive agent screenshots after every click and burns tokens for no benefit.

- Take **one** screenshot to establish state, perform **3–5 actions**, then screenshot only to verify a meaningful unit of work.
- **Trust predictable UI actions.** Tool/menu selections, color/dropdown settings, typing, and keyboard shortcuts reliably succeed — do **not** screenshot to confirm them. Proceed directly to the next action.
- Only screenshot after completing a batch, or when something unexpected happens and you need to diagnose.
- Treat a screenshot budget as a hard target: if you are screenshotting after single actions, you are doing it wrong.

## Batch actions

Group related actions into one sequence with no intermediate screenshots:

- **Setup then act:** select tool → set options → act — no screenshot between setup steps.
- **Repeat similar actions together:** e.g. fill five form fields or draw four shapes in sequence, then one screenshot at the end — not one per element.

## Plan coordinates up front

- From the establishing screenshot, note reference points (window corners, toolbar edges, canvas origin) and derive all target coordinates before acting.
- For drags, compute both start and end coordinates before beginning.
- Don't discover coordinates by trial and error — it wastes screenshots.

## Launch applications reliably

- Prefer the **Run dialog**: `key("super+r")` → `type_text("notepad")` → `key("Return")`. It is more reliable than Start-menu search.
- If the fleet exposes Application Catalog tools (`launch_application`), use those instead of navigating the shell.
- After launching, pause 3–5 seconds client-side before interacting so the app is ready (e.g. `time.sleep(3)` / `await asyncio.sleep(3)` in your agent loop — the desktop toolset has no `wait` tool, unlike some computer-use APIs).

## Prefer forwarded tools for file/web work

If the fleet has MCP tool forwarding enabled, use forwarded filesystem/fetch tools instead of driving an app by pixels — reading a file with a forwarded tool is far more reliable than opening it and reading the screen. See tool-forwarding.md.

## Handle unexpected dialogs

Apps show update prompts, recovery dialogs, setup wizards. When one appears:

- `key("Escape")` to dismiss, or `key("alt+F4")` to close a window.
- For save prompts choose "Don't Save"/"Discard" unless the task requires saving.
- `key("alt+Tab")` to bring the target window back to focus.

## Don't repeat failures

If an action fails twice, change approach — take a screenshot to re-orient, try a different launch path or coordinates, or use a forwarded tool. Repeating the same failing action wastes budget.

## Verify by outcome, not mechanics

To confirm a task succeeded, check the produced artifact (a saved file via a forwarded filesystem tool, an uploaded screenshot in S3, a changed window title) rather than screenshotting every intermediate step.
