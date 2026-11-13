# Custom test environment: test spec and test host

## Contents

- [How a custom environment job runs](#how-a-custom-environment-job-runs)
- [Get the spec that ran and the current default](#get-the-spec-that-ran-and-the-current-default)
- [Spec structure errors](#spec-structure-errors)
- [Test hosts and host migration drift](#test-hosts-and-host-migration-drift)
- [Environment variables](#environment-variables)
- [Files and settings the tests need at run time](#files-and-settings-the-tests-need-at-run-time)

## How a custom environment job runs

The test spec is a YAML file whose `phases` (`install`, `pre_test`, `test`,
`post_test`) run as shell commands on a test host connected to the device. The
**Test spec output** artifact has every command and its output in order; the
**Test spec file** artifact is the YAML that ran, and the **Test spec shell
script** artifact is the script Device Farm generated from it.

- In the `test` phase, the first command that exits non-zero ends the phase, so
  later commands, often the test runner itself, never run: a `cp`, `cd`,
  `export`-dependent path, or tool invocation that fails before the framework
  starts means no tests ran and there are no framework results.
- In `install`, `pre_test`, and `post_test`, a failing command stops nothing:
  the phase goes on to its next command, the job goes on to the next phase, and
  the verdict doesn't change. A failure there shows up later, usually as a
  test-phase error (a tool or server the tests needed isn't there), or not at
  all (a report upload in `post_test` that failed).
- An explicit `exit` ends the whole spec: an old Appium wait loop's `exit 1` in
  `pre_test` means the test phase never runs, and the Tests Suite is `FAILED`.

Read the test spec output from the top and quote the first failing command and
its error, in whichever phase it is.

Typical first errors and what they mean:

| Error in the test spec output | Meaning |
|---|---|
| `<path>: No such file or directory` for a JDK, Node, Appium, SDK, or `/usr/local/...` path | The spec hardcodes a path from another (usually legacy) host image |
| `<tool>: command not found` (for example `avm`) | The tool exists only on a legacy host |
| `Unknown software version '<tool> <version>'. The versions available are:` after `devicefarm-cli use` | The host doesn't have that version, so the pin was ignored and the job went on with the host's default version (the list printed after it shows what the host has). Pin a version from that list |
| `cp: cannot stat '<path>'` for data the tests need | The spec expects a file on the host that Device Farm never puts there (see [Files and settings](#files-and-settings-the-tests-need-at-run-time)) |
| The spec's own "server never started ... Exiting" after a log-grep wait loop | Appium didn't start, or the loop greps for a log line from an older Appium. The Appium server log the spec writes (in Customer Artifacts) has the reason; poll `http://127.0.0.1:4723<base path>/status` instead of grepping |

## Get the spec that ran and the current default

The first move on any custom-spec failure is to diff the user's spec against
Device Farm's current default spec for the same framework and platform.

- The spec that ran: the job's Test spec file artifact, or `get-run` →
  `testSpecArn` → `get-upload --arn <spec>` → download its `url`.
- The current default: `aws devicefarm list-uploads --arn <project> --type
  <FRAMEWORK>_TEST_SPEC` (for example `APPIUM_JAVA_TESTNG_TEST_SPEC`), keep
  `category` `CURATED`, pick the newest "Default Android ..." or "Default iOS ..."
  entry by its `(updated YYYY-MM-DD)` name, and download its `url`.

When the user's spec is an old default carried forward with workarounds
(version-manager calls, symlinks, hardcoded or versioned paths, hand-built
`_V<n>` variable ladders, log-grep wait loops), the fix is to rebase it on the
current default template and re-add only the user's real changes. Present the
rebase as the fix, not as an aside after a patch, and do not also offer a patch
to the old lines as a "minimal" alternative: patching one more line (a new grep
string, another ladder branch, reinstalling an old tool or version) keeps the
spec tied to a legacy host.

Rebase checklist (say which of these apply to the user's spec):

- Set `android_test_host` (required on Android) or `ios_test_host` to a
  non-legacy host, or to `default`, which lets Device Farm pick the host from
  each device's OS version (see
  [Test hosts](https://docs.aws.amazon.com/devicefarm/latest/developerguide/custom-test-environments-hosts.html)).
- Select tools with `devicefarm-cli use <tool> <version>` instead of version
  managers (`avm`, `nvm`) and symlinks into tool directories.
- Replace hardcoded host paths (`JAVA_HOME`, `/usr/local/...`) with tools run
  by name and `DEVICEFARM_*` variables.
- Start Appium the way the default spec does, and wait for it by polling
  `http://127.0.0.1:4723<base path>/status` instead of grepping its log.
- On iOS, use the default spec's WebDriverAgent selection block instead of a
  hand-built `_V<n>` ladder, and keep `appium:usePrebuiltWDA` true with that
  `appium:derivedDataPath`: Device Farm's hosts cannot build or sign
  WebDriverAgent, so never remove the prebuilt one.
- Check the base path the new Appium serves at against the test code's driver
  URL.
- Re-run on every device that failed and on one that passed.

## Spec structure errors

- `phases:` is required. If `install`, `pre_test`, `test`, and `post_test` sit
  at the top level without the `phases:` parent, Device Farm runs none of their
  commands; the test spec output shows each phase entered with no command run,
  the Test spec shell script's phase functions are empty, the job has only its
  Setup, Tests, and Teardown entries, and with no failing command the job is
  `PASSED`: a false green. The upload validator accepts such a spec, so a
  `SUCCEEDED` spec upload proves nothing. Fix: nest the phases under `phases:`,
  each with a `commands:` list.
- YAML quoting: multi-line shell blocks belong in `- |-` block scalars; an
  unquoted `:` or `#` inside a command changes its meaning. The Test spec shell
  script shows each command as the shell received it.

## Test hosts and host migration drift

The spec chooses the host image with `android_test_host` (Amazon Linux hosts) or
`ios_test_host` (macOS hosts); the current default spec and the
[test host pages](https://docs.aws.amazon.com/devicefarm/latest/developerguide/custom-test-environments-hosts.html)
name the values, and `default` lets Device Farm choose by the device's OS
version. `android_test_host` is required. An iOS spec without `ios_test_host`
falls back to a legacy iOS host, which supports only older iOS versions; newer
versions need an explicit host (the test host pages list which versions each
host supports), so one unchanged spec can pass on older devices and fail on
newer ones.

Tool versions on non-legacy hosts are chosen with `devicefarm-cli use <tool>
<version>`: a major version for `java`, `node`, and `appium`, and `major.minor`
for `python` (for example `devicefarm-cli use python 3.12`); the
[host software page](https://docs.aws.amazon.com/devicefarm/latest/developerguide/custom-test-environments-hosts-software.html)
lists what each host has. A newer host can drop older versions, and a pin the
host doesn't have only prints `Unknown software version` and leaves the host's
default in place, so a spec moved to a new host can run on different tool
versions without failing at the pin. Tools such as `avm` and legacy paths such
as `/usr/lib/jvm/java-11-openjdk-amd64` or `/usr/local/avm/...` exist only on
legacy hosts.

Moving a spec to a new host, or a device moving to one, is a migration, not a
one-line change. Symptoms: hardcoded paths missing, a tool not found, the
Appium version changing (and with it the base path and log format), and iOS
WebDriverAgent variables renamed (see [Environment variables](#environment-variables)).
The migration guides list the differences:
[iOS](https://docs.aws.amazon.com/devicefarm/latest/developerguide/ios-host-migration.html)
and [Android](https://docs.aws.amazon.com/devicefarm/latest/developerguide/android-host-upgrade.html).
Fix: rebase on the current default spec for that host, select tools with
`devicefarm-cli`, run tools by name (`java`, not `$JAVA_HOME/bin/java` from a
hardcoded `JAVA_HOME`), and replace hardcoded paths with the `DEVICEFARM_*`
variables. A spec still pinned to a legacy host is a stopgap, not a fix.

A job skipped with "The selected test host does not support one or more of the
features for this job" right after the user added an execution role or custom
environment variables means the spec still lands on the legacy iOS host, which
supports neither; set `ios_test_host` to a non-legacy host or `default`.

## Environment variables

The
[custom environment variables page](https://docs.aws.amazon.com/devicefarm/latest/developerguide/custom-test-environment-variables.html)
lists what Device Farm sets on the test host. The ones diagnoses turn on:

| Variable | Value |
|---|---|
| `DEVICEFARM_LOG_DIR` | directory collected into Customer Artifacts |
| `DEVICEFARM_TEST_PACKAGE_PATH` | where a `.zip` test package is extracted; for an APK, IPA, or JAR package, the file itself. Every default spec uses it; it is documented on the "Adding extra files to your test package" page, not the variables page |
| `DEVICEFARM_APP_PATH` | the app under test on the host |
| `DEVICEFARM_DEVICE_UDID` (with `_NAME`, `_OS_VERSION`, `_PLATFORM_NAME`) | the device under test |
| `DEVICEFARM_APPIUM_WDA_DERIVED_DATA_PATH_V<n>` (non-legacy iOS hosts) | prebuilt WebDriverAgent builds, one per XCUITest driver major version; the default spec selects the match into `DEVICEFARM_APPIUM_WDA_DERIVED_DATA_PATH` |
| `DEVICEFARM_WDA_DERIVED_DATA_PATH...` (no `APPIUM`) | the deprecated legacy-host family: non-legacy hosts set none of them except, on some hosts, `_V9` as a compatibility alias that can point at an older WebDriverAgent build than its name suggests. Treat any use as a migration item, and confirm the actual value from the test spec output or an `env` line before saying it is empty |

Do not invent other variables; in particular there is no variable for the extra
data package. Custom environment variables the user sets on the run or project
(`configuration.environmentVariables`; run values override the project's) are
not supported on the legacy iOS host.

## Files and settings the tests need at run time

On the host, only the test package is present: Device Farm puts it at
`$DEVICEFARM_TEST_PACKAGE_PATH` (for a Java `.zip`, the tests jar plus
`dependency-jars/`; for a non-zip package, unzip it yourself, for example
`unzip $DEVICEFARM_TEST_PACKAGE_PATH -d /tmp/package`), and the job's working
directory is not the user's source checkout.

- **Source-tree paths fail.** Tests that open `src/test/resources/...` or another
  path relative to a developer checkout find nothing on the host (a
  `FileNotFoundException` or a fixture-loading error in every test that uses the
  file). Fix: ship the file with the tests: as a classpath resource inside the
  tests jar loaded with `getResourceAsStream`, or as a file in the test package
  zip read from `$DEVICEFARM_TEST_PACKAGE_PATH`.
- **Extra data goes to the device, not the host.** The run's extra data package
  (`extraDataPackageArn`) is extracted onto the device: on Android into external
  storage under `/sdcard`, keeping the zip's folder names; on iOS into the app
  under test's sandbox. Nothing is extracted to a host path such as
  `/test-data`, and no environment variable points at it. The run object does
  not show the extra data package; `list-uploads --type EXTERNAL_DATA` lists the
  project's extra data uploads. Any copy of the zip that happens to sit on the
  host is undocumented and not guaranteed, so do not build on it. For files the
  host-side tests need, ship them in the test package
  ([Adding extra files to your test package](https://docs.aws.amazon.com/devicefarm/latest/developerguide/custom-test-environments-extending-files.html));
  for values, pass them with `ScheduleRun`'s
  `configuration.environmentVariables`; reading from the device during the run
  (`adb pull /sdcard/<folder>/<file>`) is a fallback.
- **System properties and settings.** A suite that gets settings from a build
  profile or CI (`-Dkey=value`, environment variables) gets none of them on
  Device Farm unless the spec passes them: add them to the spec's test command
  (`java -Dkey=value org.testng.TestNG ...`) or pass them with
  `environmentVariables`.
- **AWS credentials.** The test host has no AWS credentials of its own, so tests
  that call AWS (for example to read a secret) fail with an SDK credential
  error such as `Unable to load credentials from any of the providers` while
  passing locally or in CI. Fix: give the run an IAM execution role
  (`configuration.executionRoleArn`, or the project's), trusted by
  `devicefarm.amazonaws.com` in the same account, with a maximum session
  duration at least the job timeout, and passed by a caller with `iam:PassRole`
  ([IAM roles](https://docs.aws.amazon.com/devicefarm/latest/developerguide/custom-test-environments-iam-roles.html)).
  Never put access keys in the spec or in environment variables. Not supported
  on the legacy iOS host.
