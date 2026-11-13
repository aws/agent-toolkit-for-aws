# Artifacts, results, and what a verdict means

## Contents

- [Retrieve artifacts](#retrieve-artifacts)
- [Which artifact answers which question](#which-artifact-answers-which-question)
- [Artifacts that are missing or cut short](#artifacts-that-are-missing-or-cut-short)
- [How Device Farm decides PASSED or FAILED](#how-device-farm-decides-passed-or-failed)
- [Runs that pass but should have failed](#runs-that-pass-but-should-have-failed)
- [Runs that fail although "the tests pass"](#runs-that-fail-although-the-tests-pass)
- [Test insights](#test-insights)
- [Standard environment: one test at a time](#standard-environment-one-test-at-a-time)
- [Comparing runs and builds](#comparing-runs-and-builds)

## Retrieve artifacts

Artifacts belong to jobs (and to suites and tests). `aws devicefarm
list-artifacts --arn <job> --type FILE`, then `--type LOG` and `--type
SCREENSHOT`. Each entry has a `name`, a `type`, an `extension`, and a presigned
`url`; download the ones you need as step 3 of the triage workflow describes.
Unzip the Customer Artifacts zip and list it (`unzip -l`) before reading.

## Which artifact answers which question

| Question | Artifact |
|---|---|
| What did each spec command do, and which one failed first? | Test spec output |
| When did each spec command run? | Test spec timestamped output (the plain Test spec output has no timestamps) |
| What spec actually ran, and how was each command parsed? | Test spec file (also the run's `testSpecArn` upload); Test spec shell script |
| What did the Appium server receive and answer? | The Appium server log (`appium.log` inside Customer Artifacts) |
| What did the framework count, and with what stack traces? | The framework report inside Customer Artifacts (for TestNG, `test-output/testng-results.xml`); the framework's console summary in the test spec output; the insights report when test insights are on |
| What happened on the device (crash, kill, network, TLS, entitlement errors)? | Logcat (Android) or Syslog (iOS): listed under `--type LOG` (or `FILE`) with `type` `DEVICE_LOG` |
| What was on screen? | Video and screenshots (the framework's own screenshots are in Customer Artifacts or Screenshots) |
| What did one test do in the standard environment? | That test's Automation Output and its own logs |

`list-suites --arn <job>` and `list-tests --arn <suite>` give the structure. In a
custom environment a job has a **Setup Suite**, a **Tests Suite**, and a
**Teardown Suite**; these are spec phases, not the framework's test classes.

## Artifacts that are missing or cut short

Confirm the absence first: list all three `--type` values for the job (and, in
the standard environment, for each test) before calling an artifact missing.
Then check, in order:

1. **What was collected.** The Customer Artifacts Log, when listed, says which
   paths in the spec's `artifacts:` block were attached, missing, or skipped.
   Only listed paths are collected, each a literal directory or file; wildcards
   are not supported. Tests that write outside `$DEVICEFARM_LOG_DIR` and outside
   the listed paths leave nothing behind.
2. **Size limits**
   ([file limits](https://docs.aws.amazon.com/devicefarm/latest/developerguide/limits.html#file-limits)):
   Customer Artifacts over 1 GB in total are not available at all; the device
   log and the video are each cut off after 1 GB; when everything a run
   produces exceeds 4 GB, some artifacts (video, device logs, User
   Artifacts) may be dropped. A spec that collects all of
   `$DEVICEFARM_DERIVED_DATA_PATH` or a full `.xcresult` is the common cause.
   Evidence: the spec's `artifacts:` paths and what the tests write; have the
   user add `du -sh $DEVICEFARM_LOG_DIR/*` to `post_test` so the size shows in
   the test spec output. Fix: copy only the files needed into
   `$DEVICEFARM_LOG_DIR` in `post_test`.
3. **Retention.** Device Farm keeps run results, logs, and screenshots for 400
   days and uploaded apps and test packages for 30 days, so an old run can list
   while its app upload is gone
   ([retention](https://docs.aws.amazon.com/devicefarm/latest/developerguide/test-runs.html#test-runs-retention)).

None of these is a service fault; rule them out before escalating.

## How Device Farm decides PASSED or FAILED

In a custom environment Device Farm does not parse the framework's results to
decide the verdict. The Tests Suite result is the exit status of the test-phase
commands as the shell sees it: non-zero is `FAILED`, zero is `PASSED`. Setup and
Teardown are separate phases, so their passing says nothing about the tests.
Commands that fail in `install`, `pre_test`, or `post_test` don't change the
verdict either (unless one runs an explicit `exit`, which ends the spec): only
the test phase's exit status does.
The job's test counters (`counters`, "total 3, passed 2, failed 1") count the
Setup Test and Teardown Test along with the Tests suite, so they aren't the
framework's results: a job whose framework never started still shows 3 tests.
The framework's own counts are in the test spec output (for example TestNG's
`Total tests run: N, Passes: N, Failures: N, Skips: N`) and its report.

## Runs that pass but should have failed

A `PASSED` job with failures in the framework output is a false green. One with
no framework totals is a likely one, since some frameworks print no summary or
write their report outside the collected paths: confirm from the test command in
the test spec output and the framework's report that tests failed or never ran
before calling it. Then find where the exit status was lost:

- **Nothing ran:** the test spec output shows each phase entered with no
  command under it. Open the Test spec file and look at its top-level keys:
  `install`, `pre_test`, `test`, and `post_test` sitting at the top level
  without a `phases:` parent is the cause (see the custom test spec reference);
  the fix is to nest them under `phases:`. Or the framework never started
  because the session failed and the failure was masked.
- **Swallowed status:** a test command ending in `|| true`, `; exit 0`, or
  `set +e` with a final command that succeeds.
- **Pipelines:** `cmd | tee log` returns `tee`'s status (0), masking `cmd`'s.
  Fix with `set -o pipefail` before the pipeline or `exit ${PIPESTATUS[0]}`.
- **Wrapper scripts:** when the test phase only runs a script (for example
  `bash <wrapper>.sh`), open it before you explain anything: download the test package
  (`get-run` → find the package with `list-uploads`, or the CI log; then
  `get-upload` → `url`), unzip it, and read the script. Do not guess what it
  does.

Fix: make the framework's exit status the test phase's exit status, and add a
check that fails the phase when zero tests ran.

## Runs that fail although "the tests pass"

When the Tests Suite is `FAILED` with "Tests failed" and the user says the
tests pass, find the command in the test phase that exited non-zero, then read
the framework's totals and the failing tests' names and stack traces in the test
spec output or the report. When that command is the test framework and its
totals show failures or errors, or skips whose stack trace carries a setup or
configuration error (see Test insights below), the tests did fail; point the
user at the failing tests and their shared error. Only when every test that
ran passed and no skip traces back to a failed setup is the failure not in the
tests: something else set the exit status. It can be the framework's own
exit-code rules (TestNG exits 8 when no test ran, and some TestNG versions exit
2 for intentionally skipped tests; pytest exits 5 when it collected no tests),
a later command in the phase (such as a report copy), or a step inside the same
command that runs after the tests (a reporter or listener error, or a coverage
threshold checked in the same Gradle or Maven invocation). Find the line that
reports it and fix that. Never recommend forcing the test command
to exit 0. When failures share a cause such as a missing fixture file or a
missing setting, see the custom test spec reference ("Files and settings the
tests need at run time").

## Test insights

Test insights are enabled per run with `ScheduleRun`
`configuration.insightsTypes` `["TEST_REPORT"]` (the run shows `insightsTypes`).
The results are on each job: `get-job` → `job.insights.status`
(`PENDING`, `RUNNING`, `COMPLETED`, `SKIPPED`, `ERRORED`) and
`job.insights.testReport`: `message` (for example `Results: 7 Executed | 4 passed
| 3 failed`), `metrics` (`testsTotal`, `testsPassed`, `testsFailed`,
`testsSkipped`, `testsErrored`, durations), and `testDetailsUrl`, a URL to the
per-test report: download it and read each test's status, class, method, and
stack trace. The run also has `run.insights.jobReport`. When the user asks
about the insights report, answer from it, not only from the raw framework XML.

- When insights are missing or empty, find which of these it is:
  - Not requested: the run has no `insightsTypes`.
  - Not supported: insights exist only for custom-environment runs of
    Instrumentation, Appium Java TestNG, Appium Node.js, and XCTest UI.
  - Not finished, or not produced: `job.insights.status` is `PENDING` or
    `RUNNING`, or `SKIPPED` or `ERRORED`; then `testReport.message` names the
    reason (for example the job did not complete, the results file was not
    found where the framework writes it, or it exceeded the size limit). Fix
    that first.
  - Dropped by the client: the run requested insights but `get-job` has no
    `insights` field at all, so the CLI or SDK is too old to know it. Tell the
    user it may need a newer CLI or SDK, and ask before updating or installing
    anything.
- Insights count test methods, not configuration methods. When a TestNG
  configuration method (`@BeforeClass`, `@BeforeMethod`) throws, TestNG skips
  the dependent tests, so the report shows only skips with no failures; the
  skipped tests' stack trace carries the setup error. Other frameworks report
  setup failures differently (JUnit marks the affected tests failed or
  aborted), so read the report's failures, errors, and skips as the framework
  defines them. Those skips are a real failure, and the framework exits non-zero, so
  `FAILED` is correct.

## Standard environment: one test at a time

In the standard environment (no custom test spec) Device Farm runs each test
method as its own invocation: for XCUITest, a separate `xcodebuild
test-without-building -only-testing:<Target>/<Class>/<test>` with its own
derived data path, each reporting `Executed 1 test`; the app is reinstalled and
relaunched for each test, and suites appear per test class with each method
listed separately. State from one test (a sign-in, a session) cannot carry to
the next, and test ordering and suite-level setup do not behave as in Xcode or
a local runner. This is how standard mode works, not a crash. Evidence: the run
has no `testSpecArn`; the per-test structure in `list-suites`/`list-tests`; and,
because standard-mode artifacts belong to each test, `list-artifacts --arn
<test ARN> --type FILE` for a test, then download its Automation Output and
quote its opening command line (the per-test `-only-testing:` filter and its
own `-derivedDataPath`) and its executed-test count. Quote at least one test's
Automation Output before explaining the mechanism. Fix: run in a custom environment
(a test spec based on Device Farm's current default for the framework) that
runs the whole suite in one invocation; the trade-off is that per-test results
then come from the framework's output and report. No standard-mode setting
stops the per-test reinstall. Appium tests always need a custom environment.

## Comparing runs and builds

When something changed "overnight", compare the two runs field by field:

- `appUpload` on each run → `get-upload` → `metadata` (package or bundle id,
  `version_name`/`version_code` or bundle version) shows whether the app build
  changed.
- The test spec (`testSpecArn`) and test package used.
- Each job's `device` (model, OS version, form factor, resolution) and result.

A symptom that follows the new app build on the same device model is the app's
change, not the device or the service.
