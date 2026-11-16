# Uploads, scheduling, device selection, and limits

## Contents

- [Uploads that fail processing](#uploads-that-fail-processing)
- [Test package layout](#test-package-layout)
- [ScheduleRun rejects an upload that exists](#schedulerun-rejects-an-upload-that-exists)
- [Starting a run the user asked for](#starting-a-run-the-user-asked-for)
- [Skipped runs and device pools](#skipped-runs-and-device-pools)
- [Queued jobs, device slots, and acquisition timeouts](#queued-jobs-device-slots-and-acquisition-timeouts)
- [Jobs that run to their timeout](#jobs-that-run-to-their-timeout)
- [Performance samples](#performance-samples)

## Uploads that fail processing

An upload goes through `CreateUpload` (returns a presigned PUT `url`), an HTTP PUT
of the file, and then asynchronous processing: `INITIALIZED` → `PROCESSING` →
`SUCCEEDED` or `FAILED`. A 200 on the PUT only means the bytes reached storage.

1. Find the upload. With a project ARN, `aws devicefarm list-uploads --arn
   <project> --type <ANDROID_APP|IOS_APP|..._TEST_PACKAGE|..._TEST_SPEC>` (the
   [CreateUpload reference](https://docs.aws.amazon.com/devicefarm/latest/APIReference/API_CreateUpload.html)
   lists every type) and sort by `created`; the last one is the newest. Ignore
   uploads with `category` `CURATED` (Device Farm's own default specs).
2. `aws devicefarm get-upload --arn <upload>`: cite `status`, `message`, and
   `metadata`. `metadata` is a JSON string; on failure it carries an
   `errorCode` (for example `ANDROID_APP_UNZIP_FAILED`, `IOS_APP_UNZIP_FAILED`)
   and, for apps that parsed, fields such as the package name and version.
3. Look at what was actually stored. The upload record has no size field, so
   download its `url` (to `stored.bin`, for example), then
   `ls -l stored.bin; file stored.bin; head -c 300 stored.bin`, and for zip-based
   formats (APK, IPA, test packages) `unzip -l stored.bin` and `unzip -t
   stored.bin`.
4. Compare with earlier `SUCCEEDED` uploads of the same name and type: download
   one and compare sizes and entry lists.

| What the stored file is | Meaning | User-side fix |
|---|---|---|
| A few hundred bytes of HTML or JSON (a sign-in, error, or redirect page) | The CI step that fetched the build downloaded an error page instead of the binary; Device Farm processed exactly what it was given | Fix the CI artifact download (credentials, token, URL, redirects); fail the pipeline when the file is not the expected type and size before `CreateUpload` (for example `file` and `unzip -t`) |
| A zip that is shorter than the good uploads and fails `unzip -t` ("End-of-central-directory signature not found") | A truncated upload: an interrupted download or an incomplete PUT | Verify the artifact in CI before `CreateUpload` (size and SHA-256 against the build output, `unzip -t`), send the whole file in the PUT (correct `Content-Length`, check the PUT's HTTP status), then re-upload |
| A complete, valid file of the wrong kind (an AAB for an APK slot, a debug archive, a zip of a folder) | Wrong artifact or wrong upload type | Upload the right file with the right `--type` |
| A complete, valid file larger than the documented upload limit | The file exceeds the [upload size limit](https://docs.aws.amazon.com/devicefarm/latest/developerguide/limits.html#file-limits) | Shrink the package (drop unused dependencies, debug symbols, or bundled data) |

Do not agree that Device Farm's processing is broken when earlier uploads of the
same app succeeded, and do not tell the user to re-upload the same CI artifact
without first verifying it.

## Test package layout

Appium Java (TestNG or JUnit) test packages are a zip whose **root** holds the
`*-tests.jar` and a `dependency-jars/` folder. The validator does not look into
subfolders, so a zip made from the folder rather than its contents
(`zip-dir/app-tests.jar`, `zip-dir/dependency-jars/...`) fails validation with a
message that no `*-tests.jar` file was found in the test package, even though the
jar is in the zip.

- Evidence: `get-upload` on the failed package (`status` `FAILED`, the
  `message`), then download its `url` and `unzip -l` to show the entry paths.
- Fix: zip the folder's contents (`cd target/zip-dir && zip -r ../tests.zip .`),
  or set `<includeBaseDirectory>false</includeBaseDirectory>` in the Maven
  assembly descriptor; check `unzip -l` shows `*-tests.jar` at the root, then
  re-upload and confirm the upload `SUCCEEDED`.

Files the tests read at run time must be inside the test package (see the
custom test spec reference, "Files and settings the tests need at run time").

## ScheduleRun rejects an upload that exists

`ScheduleRun` only accepts uploads whose status is `SUCCEEDED`. Called while an
upload is still `INITIALIZED` or `PROCESSING`, it fails with a
`NotFoundException` or `ArgumentException` that calls the ARN invalid or not
found, which misleads users into thinking the ARN is wrong. It is intermittent
because processing time varies.

Evidence:

- The upload exists in the project and is `SUCCEEDED` now (`get-upload`).
- Its `created` time is seconds before the failed call. For the failed call
  itself, look it up in CloudTrail: `aws cloudtrail lookup-events --region
  us-west-2 --lookup-attributes AttributeKey=EventName,AttributeValue=ScheduleRun`
  shows `eventTime`, `errorCode`, `errorMessage`, and the uploads it referenced
  in `requestParameters` (`appArn`, and under `test`, `testPackageArn` and
  `testSpecArn`). A `Run` has no test package field, so CloudTrail or the CI log
  is the way to tie a run request to its test package.
- If `get-upload` on the referenced ARN itself returns `NotFoundException`, the
  upload is gone, not pending: it was deleted, belongs to another account, or
  was removed after Device Farm's 30-day retention for uploads. Upload again;
  retrying cannot help.

Fix: after each PUT, poll `get-upload` until `status` is `SUCCEEDED` (stop and
report on `FAILED`, with a timeout) for every upload the run references (app,
test package, test spec, extra data), and only then call `ScheduleRun`. There is
no Device Farm waiter in the AWS CLI or SDKs, so write the poll loop. Blind
retries or fixed sleeps are not a fix.

Read the error code before you choose a mechanism:

- `NotFoundException` or `ArgumentException` naming an upload that is not yet
  `SUCCEEDED`: the race above.
- `LimitExceededException` ("Max open jobs rate exceeded"): the account has
  reached its limit of in-flight jobs (running plus queued); let queued runs
  drain or request an increase
  ([service limits](https://docs.aws.amazon.com/devicefarm/latest/developerguide/limits.html#service-limits)).
- `ThrottlingException` ("Rate exceeded"): API pacing, not an outage; it does
  not affect running jobs. Back off and space the calls, especially a CI job
  that schedules many runs at once or polls `get-run` or `list-uploads` in a
  tight loop ([API limits](https://docs.aws.amazon.com/devicefarm/latest/developerguide/limits.html#api-limits)).
- `ArgumentException` saying the test type "is only compatible with custom
  environment mode": every Appium test type needs a custom environment (a test
  spec). Only Instrumentation, XCTest, XCTest UI, and built-in fuzz runs accept
  the standard environment. Upload a `<TYPE>_TEST_SPEC` (start from the
  project's default spec in `list-uploads`) and pass `testSpecArn`.

## Starting a run the user asked for

Only when the user asked for the run (see the guardrails in `SKILL.md`). Every
upload it references MUST be `SUCCEEDED`:

```
aws devicefarm schedule-run --region us-west-2 --project-arn <project> \
  --app-arn <app upload> \
  --test type=<TEST_TYPE>,testPackageArn=<test package upload>,testSpecArn=<test spec upload> \
  --device-pool-arn <pool>
```

For an ad hoc choice such as "one Android device", replace `--device-pool-arn`
with `--device-selection-configuration
'{"filters":[{"attribute":"PLATFORM","operator":"EQUALS","values":["ANDROID"]}],"maxDevices":1}'`
instead of creating a pool. Report the run ARN, and follow it with `get-run`.

## Skipped runs and device pools

Read `get-run`'s `resultCode` first; it is set only on `SKIPPED` runs, and only
on the run, never on a job:

- `PARSING_FAILED`: the standard environment could not enumerate the tests in
  the test package (job messages often read "Signing error with app or tests").
  Download the file at `parsingResultUrl` and quote the reason. Standard-mode
  runs are also limited to 250 test cases and may be skipped above it. The fix
  is a custom test environment, which does not parse the package.
- `VPC_ENDPOINT_SETUP_FAILED`: check the run's VPC configuration (subnets and
  security groups); if it is correct, escalate under the guardrails. It is not
  a device pool problem.

A run that is `SKIPPED` with `totalJobs` 0 and no `resultCode` never created a
job, so it has no artifacts or logs by design: the evidence is the API fields
and the device pool. Do not chase the missing logs.

1. `get-run`: `result`, `message`, `totalJobs`, `devicePoolArn` (or
   `deviceSelectionResult` with `matchedDevicesCount` and `maxDevices` for
   dynamic selection).
2. `get-device-pool --arn <pool>`: read `maxDevices` and every rule
   (`attribute`, `operator`, `value`; values are JSON-encoded strings).
3. Check the rules against what exists, and state the result as checked:
   - `INSTANCE_ARN` and `INSTANCE_LABELS` match only private device instances.
     `aws devicefarm list-device-instances` lists the account's private
     instances and their labels; with none, such a rule matches nothing.
   - `aws devicefarm get-device-pool-compatibility --device-pool-arn <pool>
     --app-arn <app> --test-type <type>` lists compatible and incompatible
     devices with reasons.
   - `list-devices --filters ...` shows what a selection matches; pool rules
     and device filters use different shapes (`value` as a JSON string versus
     `values`, and some operators differ), so translate each rule, and use
     `get-device-pool-compatibility` for rules without an equivalent filter.
4. Compare with the previous run: if it passed on a device that the pool's
   current rules can never select (a static attribute such as platform, model,
   label, or instance, not a device that is merely busy), the rules changed
   between the runs. `get-run` shows the pool ARN, not the rules at that time;
   CloudTrail `UpdateDevicePool` events show when they changed.

`AVAILABILITY` rules: pool rules are evaluated once, when the run is scheduled.
With `AVAILABILITY` `EQUALS` `AVAILABLE`, a device that is busy at that moment
is dropped from the run without a message:
the run goes ahead on the devices that passed, and when none pass it is
`SKIPPED` with `totalJobs` 0 instead of waiting. A device that passed can still
be busy by the time its job starts, and that job then waits. Without the rule,
every matching device gets a job, and jobs for busy devices wait in the queue.
Waiting cannot help when no device can ever match. A run with fewer jobs than
the pool's matching devices points first at the pool's `maxDevices` (or
`deviceSelectionResult.maxDevices`), then at this rule.

Fix: correct the rules (remove the rule that can't match, or label the intended
private instances), confirm the pool matches at least one device with
`get-device-pool-compatibility` or `list-devices`, then re-run. Give the
`update-device-pool` command and ask before running it, as the guardrails say.

## Queued jobs, device slots, and acquisition timeouts

Concurrency is bounded by the account's device slots. `aws devicefarm
get-account-settings` shows `unmeteredDevices` (the slots the account has
purchased, per platform) and `maxSlots` (the most it can purchase); metered
(pay-as-you-go) runs have their own default concurrency limit, and a run only
uses purchased slots when it is scheduled with `billingMethod` `UNMETERED`.
`list-offerings` and `get-offering-status` show purchases for accounts enabled
for the offerings API (others get `NotEligibleException`, which is not an IAM
denial). Jobs beyond the free slots wait in `PENDING_CONCURRENCY`; jobs waiting
for a busy or offline device wait in `PENDING_DEVICE`. A queued job keeps
waiting until a slot and the requested device are free; a job still waiting
at the queue limit (up to 24 hours,
[service limits](https://docs.aws.amazon.com/devicefarm/latest/developerguide/limits.html#service-limits))
is skipped with "Timeout in device acquisition". A device Device Farm can't
serve at all doesn't queue: its job errors right away ("Unable to acquire
device"). Jobs on private devices don't count against the account's
concurrency, so they never show `PENDING_CONCURRENCY`. A run's result is its
worst job's result (in the order `ERRORED`, `SKIPPED`, `STOPPED`, `FAILED`,
`PASSED`), so one skipped job shows the whole run as `SKIPPED`: judge results
per job.

Evidence: the skipped jobs' `message`; the gap between the run's `created` and
each job's `started`; the number of jobs scheduled at once against the slots
the account has (ask for it when you cannot read the account), and the run's
`billingMethod`.
Fix: queue fewer or shorter jobs at a time (spread scheduling, fewer devices per
run, split suites), or buy more slots and schedule with the unmetered billing
method. This is not an API rate limit or an outage, and retrying immediately
adds to the queue.

## Jobs that run to their timeout

A job's timeout is `jobTimeoutMinutes` on the run; the account's default and
maximum are in `get-account-settings` (`defaultJobTimeoutMinutes`,
`maxJobTimeoutMinutes`). The hard limit is 150 minutes per job
([service limits](https://docs.aws.amazon.com/devicefarm/latest/developerguide/limits.html#service-limits));
it cannot be raised, so do not suggest a quota request. A job that reaches its
timeout is forcibly stopped and ends `STOPPED` with partial results. Look up
`StopRun` and `StopJob` in CloudTrail to rule out a person or pipeline stopping
it.

Then decide which case it is from the test spec output's timeline (`get-job`
`started` and `stopped` give the duration):

- **Still progressing when it stopped:** test output keeps arriving until the
  end. If the run's `jobTimeoutMinutes` is below the account's
  `maxJobTimeoutMinutes`, the fix is a longer timeout on the next run
  (`executionConfiguration` `jobTimeoutMinutes` in `schedule-run`). If it is
  already at the maximum, or the suite needs more than 150 minutes, it needs
  longer than one job allows: split it across runs or jobs that each finish
  under the limit; Device Farm does not shard one suite across devices.
- **Silent long before the end:** something never exited. The test spec output
  only shows the silence; read what happened during it in the Appium server log
  for Appium suites (an expired session the test keeps polling is the common
  case; see the Appium reference) or the device log for instrumentation and
  XCTest, and check for a background process the spec started and never ended.
  Raising the timeout is not a fix.

Slow progress is not a hang: before you call it one, check that the output
really stopped rather than slowed down.

## Performance samples

Device Farm does not collect performance samples (CPU, memory, threads, FPS)
for jobs. [`ListSamples`](https://docs.aws.amazon.com/cli/latest/reference/devicefarm/list-samples.html)
remains in the API but returns an empty list for every job, and no project, pool,
host, or run setting brings the samples back. Confirm the empty list once for the
user's job (`aws devicefarm list-samples --arn <job>`), then tell them nothing in
their project is misconfigured.
