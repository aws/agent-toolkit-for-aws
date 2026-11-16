# Appium sessions and iOS WebDriverAgent on Device Farm

## Contents

- [How Device Farm starts Appium](#how-device-farm-starts-appium)
- [Read the Appium server log in this order](#read-the-appium-server-log-in-this-order)
- [Capabilities the test code must not set](#capabilities-the-test-code-must-not-set)
- [Base path mismatches](#base-path-mismatches)
- [Sessions that expire and jobs that hang](#sessions-that-expire-and-jobs-that-hang)
- [iOS: WebDriverAgent and xcodebuild codes 65 and 70](#ios-webdriveragent-and-xcodebuild-codes-65-and-70)

## How Device Farm starts Appium

In a custom environment Device Farm's default test spec starts the Appium
server on the host, in the background, with `--default-capabilities` built from
Device Farm's variables: `appium:deviceName` from `$DEVICEFARM_DEVICE_NAME`, `platformName`,
`appium:app` from `$DEVICEFARM_APP_PATH`, `appium:udid` from
`$DEVICEFARM_DEVICE_UDID`, `appium:platformVersion` from
`$DEVICEFARM_DEVICE_OS_VERSION`, `appium:automationName`, and on iOS
`appium:derivedDataPath` (the prebuilt WebDriverAgent) with
`appium:usePrebuiltWDA` true. A customized spec may drop some of these, so read
the Appium server log for what the session actually got. The default spec logs
the server to `$DEVICEFARM_LOG_DIR/appium.log`, which is inside the job's
**Customer Artifacts** zip; the test spec output usually shows only the
client-side exception. A spec that starts Appium differently may log elsewhere
or not at all: check its startup command before concluding the log is missing.

The test code should connect to the local server (`http://127.0.0.1:4723` plus
the spec's base path) and send only test-specific capabilities. **Anything the
test code sends overrides the spec's defaults**, so a value hardcoded for a
local emulator, simulator, or lab phone replaces the right one for the device
Device Farm assigned.

## Read the Appium server log in this order

1. **Server start:** the version line (`Welcome to Appium v...`), the
   `Default capabilities` block the spec passed, and the listener line with the
   base path (`... listener started on http://0.0.0.0:4723/<base path>`).
2. **The session request:** the `Creating session with W3C capabilities` block
   is the merged result. Compare every value with the defaults; a value that
   differs came from the test code's session request (`POST .../session`).
3. **Warnings about the request**, for example `Capability 'usePrebuiltWDA'
   changed from string to boolean` (the client sends booleans as strings) or
   `Changing deviceName from 'iPhone Simulator'` (a simulator value).
4. **The first error** and the command line Appium ran (for iOS, the
   `xcodebuild` invocation with its flags).
5. **HTTP routes:** a `404` on `POST /wd/hub/session` means a base path mismatch.

Line up its timestamps with the Test spec timestamped output to see what the
server did while the client was silent.

## Capabilities the test code must not set

| Capability sent by the test code | What happens on Device Farm |
|---|---|
| `app` with a local file name or path | Appium looks for that file on the host: "The application at '...' does not exist or is not accessible". The upload and the install are fine |
| `deviceName`, `udid`, `platformVersion` with local values | Appium targets the wrong device or OS version; on iOS a hardcoded `platformVersion` newer than the device makes Appium launch WebDriverAgent for that version, which fails on the older device while the same suite passes on a device that happens to match |
| `xcodeOrgId`, `xcodeSigningId`, `updatedWDABundleId` | Appium asks `xcodebuild` to sign WebDriverAgent with the user's team (`DEVELOPMENT_TEAM=...`, `CODE_SIGN_IDENTITY=...`); Device Farm re-signs and provides its own prebuilt WebDriverAgent, so this fails |
| `usePrebuiltWDA` false | Appium tries to build WebDriverAgent on the host, which has no signing team and a read-only WebDriverAgent bundle, so the build fails |
| Booleans as strings (`"true"`) | Appium converts them with a warning; a sign of copied local settings |

Fix: on Device Farm, stop setting `app`, `deviceName`, `udid`,
`platformVersion`, and signing capabilities in test code, and let the spec's
default capabilities supply them; if the code needs the values, read
`DEVICEFARM_DEVICE_NAME`, `DEVICEFARM_DEVICE_OS_VERSION`, and the other
`DEVICEFARM_*` variables. Send booleans as booleans. Re-run on every device
that failed. Never recommend hardcoding a host path or a UDID, building or
signing WebDriverAgent yourself, or adding a development team.

Pre-starting WebDriverAgent in the spec is a legacy-host recipe. The developer
guide's page on speeding up Appium tests still shows it (`xcodebuild
test-without-building` on a `/usr/local/avm/...` WebDriverAgent project,
`iproxy 8100 8100`, and `webDriverAgentUrl: http://localhost:8100`). On
non-legacy hosts that project path does not exist and `iproxy`
(libimobiledevice) is not installed. Those commands run in the background, so
the visible failure is the recipe's own `WebDriverAgent server never started`
exit in `pre_test`; the real errors are in `webdriveragent_log.txt` and
`iproxy_log.txt` in Customer Artifacts. Fix on a non-legacy host: delete the
pre-start block, its wait loop, and `webDriverAgentUrl`, and use the default
spec's WebDriverAgent selection block with `appium:usePrebuiltWDA` true; Appium
starts WebDriverAgent itself when the capabilities are right. Do not fix it by
changing the wait loop.

## Base path mismatches

Appium 1.x served its routes under `/wd/hub`; Appium 2 and later serve at `/` by
default. Device Farm's current default specs export `APPIUM_BASE_PATH` (empty
by default) and start the server with `--base-path=$APPIUM_BASE_PATH`. A suite
whose driver URL still ends in `/wd/hub` gets `404` on `POST /wd/hub/session`
in the Appium server log and a `SessionNotCreatedException` in the framework
report.

Fix: make them agree, either `export APPIUM_BASE_PATH=/wd/hub` in the spec or
point the driver at `http://127.0.0.1:4723`. If the run still showed `PASSED`,
the test command's exit status is being masked (for example `|| true`); remove
the mask so a failing suite fails the run (see the artifacts and results
reference).

## Sessions that expire and jobs that hang

Appium ends a session when it receives no command for `newCommandTimeout`
seconds (60 by default): the Appium server log shows `New Command Timeout of 60 seconds
expired`, and every later command gets `A session is either terminated or not
started` (an invalid session id). A test whose wait or retry helper swallows
those errors keeps polling a dead session until the job timeout, and the job
ends `STOPPED` with a test spec output that just goes quiet. The device did
not hang. Before you blame the session, check the job's duration: a job that
ran close to the 150-minute limit with output still arriving needs longer, not
a session fix (see "Jobs that run to their timeout" in the uploads and
scheduling reference).

Fix: set `appium:newCommandTimeout` above the longest idle stretch (or keep the
session busy), make the wait helper rethrow session errors so the test fails
fast, and keep the framework's own timeouts below the job timeout. Raising only
the job timeout is not a fix.

## iOS: WebDriverAgent and xcodebuild codes 65 and 70

`Unable to launch WebDriverAgent. Original error: xcodebuild failed with code
65` (or `70`) is a generic `xcodebuild` exit status; the capabilities block and
the `xcodebuild` command line in the Appium server log decide the cause. Check,
in order:

1. `appium:derivedDataPath` in the session capabilities. Empty (`""`) means the
   spec passed a variable the host does not set; a path to an older
   WebDriverAgent build than the XCUITest driver expects fails the same way.
   Non-legacy iOS hosts expose the prebuilt WebDriverAgent builds as
   `DEVICEFARM_APPIUM_WDA_DERIVED_DATA_PATH_V<n>`; the old
   `DEVICEFARM_WDA_DERIVED_DATA_PATH...` names are deprecated (see the custom
   test spec reference, "Environment variables"). Quote the value from the
   Appium server log or the test spec output rather than asserting which names
   are set. Fix: replace the spec's WebDriverAgent lines with the current
   default spec's selection block and pass
   `$DEVICEFARM_APPIUM_WDA_DERIVED_DATA_PATH` as `appium:derivedDataPath` with
   `appium:usePrebuiltWDA` true.
2. `appium:usePrebuiltWDA` false, or signing capabilities (`xcodeOrgId`,
   `xcodeSigningId`) in the merged capabilities: remove them from the test code
   (table above).
3. `appium:platformVersion` that does not match the device's real version in
   the `Default capabilities`: remove it from the test code.

Each of these alone can fail the launch, so fix every one you find and say so.
The current default iOS spec also strips the hyphens from the UDID it passes to
Appium for iOS 16 and earlier; compare that step too when only older iOS
versions fail.
