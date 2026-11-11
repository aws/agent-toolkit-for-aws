# Works locally, fails on Device Farm: device and network differences

## Contents

- [Start by grouping the failures](#start-by-grouping-the-failures)
- [iOS public devices re-sign the app](#ios-public-devices-re-sign-the-app)
- [Android re-signing and private-device state](#android-re-signing-and-private-device-state)
- [Proxies left on a device](#proxies-left-on-a-device)
- [TLS trust errors that depend on the device](#tls-trust-errors-that-depend-on-the-device)
- [Black screenshots or video](#black-screenshots-or-video)
- [Element found on one device but not another](#element-found-on-one-device-but-not-another)

## Start by grouping the failures

List every job with its device (`list-jobs`: `device.model`, `device.os`,
`device.formFactor`, `device.resolution`) and result, or read the user's
per-device results, and find the one attribute that separates failing from
passing devices: OS version, form factor, model, public versus private, or the
app build. Then read the failing job's device log (Logcat or Syslog, artifact
`type` `DEVICE_LOG` in `list-artifacts`) around the failure time for the app's
own error lines. When the user hands you saved logs or result files
instead of an ARN, read those files and quote them the same way; do not claim
checks you could not run, and give the user the command for each one you
could not.

## iOS public devices re-sign the app

Device Farm re-signs every app it installs on a public iOS device with its own
provisioning profile and team. Entitlements tied to the user's team do not
survive, such as `keychain-access-groups` with the user's team prefix, App
Groups, and associated domains. The app runs, but calls that need the missing
entitlement fail. Typical Syslog lines: `securityd` with `-34018`
(`errSecMissingEntitlement`), `Client explicitly specifies access group
<TEAMID>.<group> but is only entitled for (<other TEAMID>.<bundle id> ...)`, and
the app's own keychain error at the same moment; the UI shows only a generic
error, and no network error goes with it. Only the app's
lines count; other processes log `-34018` too.

Fix: run the flows that need those entitlements on private devices with
`ScheduleRun` `executionConfiguration.skipAppResign` true, which keeps the app's
own signature and entitlements (Device Farm always re-signs on public iOS
devices, and the skip option is not available for the XCTest unit-test type),
or keep those flows out of public-device runs (for example a test
build that does not depend on the shared group). Re-signing with the user's
own certificate or editing the provisioning profile does not make public
devices work.

## Android re-signing and private-device state

- **Android re-signing depends on the host.** On `amazon_linux_2`, apps on
  public devices are always re-signed (and on private devices by default); on
  `amazon_linux_2023` they are installed as uploaded unless re-signing is
  turned on ([app re-signing](https://docs.aws.amazon.com/devicefarm/latest/developerguide/apps.html#test-runs-app-resigning)).
  A re-signed app breaks anything keyed to its signing certificate: a Google
  Maps Android API key restricted to the app's certificate, the app's own
  signature check, or anti-tamper tools such as DexGuard. Evidence: the Test
  spec file's `android_test_host`, the run's `skipAppResign`, and the device
  log's authorization or integrity error. Fix: run on `amazon_linux_2023`
  without re-signing, or on private devices with `skipAppResign` true.
- **Private devices keep state between runs** unless their instance profile
  cleans up: `packageCleanup` is off by default
  ([private device settings](https://docs.aws.amazon.com/devicefarm/latest/developerguide/set-up-private-devices-account-settings.html);
  `list-device-instances` shows each instance's `instanceProfile`). A build an
  earlier run left installed, or a changed device setting such as a proxy
  (below), carries into later runs. Package cleanup removes app packages, not
  settings, and a reboot does not clear settings either.

## Proxies left on a device

`adb shell settings delete global http_proxy` (and deleting
`global_http_proxy_host` and `global_http_proxy_port`) changes the stored
settings but does not notify Android, so the proxy Android already applied stays
in effect for every app, including apps started later, while `settings get
global http_proxy` returns `null`. On a private device it carries into later
runs. Android ignores `https_proxy`. Evidence: the app's connection errors name
the proxy's host and port (for example `failed to connect to /<proxy host> (port
<port>)`), and logcat's `ProxyTracker` shows the broadcast when the proxy was
set and none after the cleanup.

Fix: clear it with a write Android acts on, `adb shell settings put global
http_proxy :0`, in the test's cleanup, and also in the spec's `pre_test` so a
device an earlier run left dirty is reset; deleting the keys afterwards is fine.
For a proxy the whole run needs, Device Farm recommends `ScheduleRun`
`configuration.deviceProxy` (host and port) over shell commands.

## TLS trust errors that depend on the device

`SSLHandshakeException: ... Trust anchor for certification path not found` is a
certificate trust failure, not reachability: the TCP connection worked.
Group the results by OS version. When failures follow the Android version, the
server's chain ends at a root that newer Android trust stores include and older
ones do not; a chain that ends at a newer root without the cross-signed
intermediate to an older root fails on older versions. For example, a chain
ending at GlobalSign Root R46 without the R3 cross-sign fails on Android 11
through 13 and passes on 14 and later. Which devices fail is just which OS
versions the pool picked; the user's own phones run a newer version.
An app log line such as "No Network Security Config specified, using platform
default" confirms the app relies on the system trust store alone.

Check: have the user inspect the served chain,
`openssl s_client -connect <host>:443 -servername <host> -showcerts`, unless
you can reach the endpoint yourself.
Fix: serve the complete chain including the cross-sign to a root older Android
trusts, or bundle the needed root in the app's `network_security_config`
alongside the system store. Restricting the pool to newer Android is only a
stopgap. Never disable certificate verification or trust all certificates.
For private endpoints reached over a VPC connection, reachability and trust are
separate problems: the app must trust a private CA however the traffic gets there.

## Black screenshots or video

Black captures have three causes that look alike, so find which one fits before
naming a fix. Compare the black run with the last good one (same device model,
and the app upload each used) and with the other devices in the same run, and
note what is black. If you cannot view the images, use what you can read (file
sizes, which are much smaller for black frames, the UI hierarchy the test
saved, and the Appium server log) and ask the user what the black frames show.

- **The app's window is black from the moment it opens, on every device that
  runs this build, while the tests still pass and find their elements:** the
  app marks its window secure (`FLAG_SECURE`). Android blanks secure windows in
  screenshots and screen recordings by design; the status bar or the home
  screen is still captured, and older UiAutomator2 versions fail the screenshot
  with "Does the current view have 'secure' flag set?". A new `appUpload` with a
  different version in its metadata, on the same device model that recorded
  fine before, points at the app's change; only the app's code confirms the
  flag. Fix: find where the build added `FLAG_SECURE`
  (`getWindow().setFlags(...)` or `addFlags(WindowManager.LayoutParams.FLAG_SECURE)`)
  and leave it out of test builds (for example behind a build flag), or accept
  black captures on those screens. Recording and the device are fine.
- **Only a video playback area is black:** when the content is DRM-protected
  (the device log shows `MediaDrm` or Widevine sessions for it, or the
  user confirms it), it plays on a secure surface, which also captures as
  black by design; recording is fine, so check playback through the player's
  own state or logs instead. Without that evidence, treat it as a playback
  failure and look for decoder or player errors in the device log.
- **Everything is black on one device, including the home screen or other
  apps, while the same app build recorded fine on other devices:** a capture
  problem on that device. Send AWS Support the device, the job ARN, and the
  times.

Name `FLAG_SECURE` only when the black capture follows the app build, not the
device.

## Element found on one device but not another

When the same locator works on one device and throws `NoSuchElementException` on
another with the same OS version, establish what was on the failing device's
screen before touching locators. The UI hierarchy is the most direct evidence:
if the tests save the page source (`driver.getPageSource()`) to
`$DEVICEFARM_LOG_DIR` on failure, compare the two devices' XML hierarchies: the
element missing, its `bounds` outside the screen, or `displayed` or `visible`
false on the failing device. Otherwise look at the failing job's failure
screenshot or video, with a tool that can display images. Then compare the two
devices' screens (`list-jobs` → `device.resolution`, or `deviceScreenSize` and
`deviceScreenDensity` in the session capabilities in the Appium server log;
convert to dp) with that screen's layout in the app's source (or, without the
source, in the app upload): if the layout puts the target control beyond the
phone's screen width and nothing scrolls it into view, that is the cause; if it
does not, clipping is only a hypothesis. UiAutomator2 only finds views that are
on screen, so a layout built for a wider screen that pushes the form past the
edge without scrolling hides it on the narrower device. XCUITest can find
off-screen elements in its snapshot but cannot tap them, so on iOS check whether
the element exists and whether it is hittable before concluding it is clipped.
If the tests don't save the page source, recommend adding it to the failure
hook; it is the fastest way to compare form factors such as a phone and a
tablet. If you could view neither the hierarchy nor the screenshot, say which
evidence your conclusion rests on. Fix the layout so the elements are reachable
on every form factor (an adaptive or scrollable layout), keep the
accessibility-id locators, and scroll an element into view when it can be off
screen. Switching to XPath or coordinates, longer waits, or dropping the device
from the pool are not fixes.
