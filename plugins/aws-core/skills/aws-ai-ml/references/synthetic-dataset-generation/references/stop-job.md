When the user asks to cancel or stop a running synthetic dataset generation job (e.g., "stop the job", "cancel", "abort", "kill it", "the spec is wrong, stop it", "this is taking too long — stop"), follow this logic:

1. **Identify the job to stop.**
   - If the notebook Job handle from a `wait=False` submission is in scope, use it directly.
   - Otherwise, use the job ARN printed at submission time.
   - If neither is available, ask the user to paste the ARN.

2. **Confirm briefly.** Say something like:
   > "This stops the job. A stopped job cannot be resumed. The cell will block for 1–5 min while the container shuts down gracefully. Continue?"

   Skip this confirmation if the user was already explicit ("stop it now").

3. **Fire the stop.**
   - **Notebook mode:** Insert `synthetic_generation_adhoc.py` Cell 2 as a new cell in the user's notebook, replacing `[JOB_HANDLE_OR_ARN]` with the live `Job` handle (if the user submitted with `wait=False` and still has the handle in scope) or the ARN string of the running job.
   - **Script mode:** The agent executes the same code (`synthetic_generation_adhoc.py` Cell 2) directly in its own session — no notebook cell to insert. Substitute `[JOB_HANDLE_OR_ARN]` with the ARN string of the running job.
   - Default (`wait=True`) blocks until the job transitions to `Stopped` (1–5 min), so the cell / call confirms the terminal state on its own.
   - Pass `wait=False` if the user wants fire-and-forget (returns in ~1 s as soon as the service accepts the request) — e.g., they explicitly ask to skip waiting, or they need the cell/session freed up immediately.

4. **Handle the two benign outcomes:**
   - **Already terminal** (`Completed` / `Failed` / `Stopped`): `DataPreparer.stop()` is a safe no-op — the SDK logs `nothing to stop.` Report: "The job was already in a terminal state (<status>); nothing to stop."
   - **`ResourceNotFound`** (SDK raises "Job '<name>' not found"): the ARN doesn't correspond to any job in this account and region. Report: "No job with that ARN was found — please double-check the ARN." Ask the user to re-supply it from their original submission output.

5. **To confirm the transition landed later**, follow `progress-check.md` — poll via `DataPreparer.attach(job_arn, wait=False)`, read `job.job_status`. Terminal `Stopped` means the stop landed.

<!-- markdownlint-disable-file MD033 -->
