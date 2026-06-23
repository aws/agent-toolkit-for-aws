# Auth — Mobile

## Prerequisites

Initialize Amplify with the Auth plugin before using this feature:

**Flutter** — `lib/main.dart`:

```dart
await Amplify.addPlugins([AmplifyAuthCognito()]);
await Amplify.configure(amplifyConfig);
```

> Generate dart outputs: `npx ampx sandbox --outputs-format dart --outputs-out-dir lib`

**Swift (Apple platforms):**

```swift
try Amplify.add(plugin: AWSCognitoAuthPlugin())
try Amplify.configure(with: .amplifyOutputs)
```

> Drag `amplify_outputs.json` into the Xcode project navigator so it is included in the app bundle.

**Android:**

```kotlin
Amplify.addPlugin(AWSCognitoAuthPlugin())
Amplify.configure(AmplifyOutputs(R.raw.amplify_outputs), applicationContext)
```

> Place `amplify_outputs.json` in `app/src/main/res/raw/`. Enable core library desugaring for API level < 26.
>
> **Backend required:** Auth must be defined in `amplify/auth/resource.ts`
> using `defineAuth` — see [auth-backend.md](auth-backend.md).

## Authenticator Component (Recommended)

All three mobile platforms provide a drop-in **Authenticator** component that
handles sign-in, sign-up, MFA, social login, passwordless, password reset, and
all intermediate auth states automatically. **Use it unless you need a fully
custom UI.** Zero manual `signInStep` handling is required.

> **Passwordless:** The Authenticator component handles passwordless flows (email OTP, SMS OTP, and WebAuthn/passkey) automatically when configured in `defineAuth`. No custom UI code needed for passwordless authentication. Custom OTP/passkey flows require additional challenge handling.
>
> **Passwordless WebAuthn:**
>
> - Swift: `.userChoice(preferredAuthFactor: .webAuthn)`
> - Android: `AuthenticationFlow.UserChoice(preferredFirstFactor = AuthFactorType.WEB_AUTHN)`

### Flutter

**Dependencies** — add to `pubspec.yaml`:

```bash
flutter pub add amplify_flutter amplify_auth_cognito amplify_authenticator
```

**Usage** — wrap your `MaterialApp` and set its `builder`:

```dart
import 'package:amplify_authenticator/amplify_authenticator.dart';
import 'package:flutter/material.dart';

// After Amplify is configured (see Prerequisites above):
@override
Widget build(BuildContext context) {
  return Authenticator(
    child: MaterialApp(
      builder: Authenticator.builder(),
      home: const Scaffold(
        body: Center(child: Text('You are logged in!')),
      ),
    ),
  );
}
```

### Swift (Apple platforms)

**Dependencies** — add both SPM packages in Xcode (**File > Add Packages…**):

| Package                        | URL                                                             | Libraries                         |
| ------------------------------ | --------------------------------------------------------------- | --------------------------------- |
| Amplify Library for Swift      | `https://github.com/aws-amplify/amplify-swift`                  | `Amplify`, `AWSCognitoAuthPlugin` |
| Amplify UI Swift Authenticator | `https://github.com/aws-amplify/amplify-ui-swift-authenticator` | `Authenticator`                   |

> **SPM versioning:** For both packages, select **"Up to Next Major Version"** in Xcode's dependency rule. Do NOT pin to a specific branch (e.g., `main`) — use "Up to Next Major Version" to get compatible updates automatically.

**Usage** — SwiftUI entry point:

```swift
import Amplify
import Authenticator
import AWSCognitoAuthPlugin
import SwiftUI

@main
struct MyApp: App {
    // init() — configure Amplify (see Prerequisites above)

    var body: some Scene {
        WindowGroup {
            Authenticator { state in
                VStack {
                    Text("Hello, \(state.user.username)")
                    Button("Sign out") {
                        Task { await state.signOut() }
                    }
                }
            }
        }
    }
}
```

**Passwordless / user-choice flow:**

```swift
Authenticator(authenticationFlow: .userChoice(
    preferredAuthFactor: .webAuthn
)) { state in
    Text("Welcome \(state.user.username)!")
}
```

### Android (Kotlin)

**Dependencies** — add to your app's `build.gradle.kts`:

> Core library desugaring required — see Prerequisites above.

```kotlin
dependencies {
    implementation("com.amplifyframework.ui:authenticator:<version>")
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:<version>")
}
```

`INTERNET` permission is required in `AndroidManifest.xml`:

```xml
<uses-permission android:name="android.permission.INTERNET"/>
```

**Usage** — Jetpack Compose:

```kotlin
import com.amplifyframework.ui.authenticator.ui.Authenticator
import com.amplifyframework.ui.authenticator.SignedInState

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            Authenticator { state ->
                Column {
                    Text("Signed in as ${state.user.username}")
                    val scope = rememberCoroutineScope()
                    Button(onClick = { scope.launch { state.signOut() } }) {
                        Text("Sign Out")
                    }
                }
            }
        }
    }
}
```

**Passwordless / user-choice flow:**

```kotlin
val authenticatorState = rememberAuthenticatorState(
    authenticationFlow = AuthenticationFlow.UserChoice(
        preferredFirstFactor = AuthFactorType.WEB_AUTHN
    )
)
Authenticator(state = authenticatorState) { state ->
    Text("Welcome ${state.user.username}!")
}
```

## Custom UI

Use the low-level Auth APIs when you need full control over the UI. Each
platform returns a `nextStep` from `signIn` / `signUp` — switch on it and
call `confirmSignIn` as needed. The Authenticator handles all these steps
automatically; the list below is for reference when building custom flows.

### Flutter

```dart
import 'package:amplify_flutter/amplify_flutter.dart';
```

**Sign in:**

```dart
final result = await Amplify.Auth.signIn(
  username: username,
  password: password,
);
if (result.isSignedIn) {
  safePrint('Sign in complete');
} else {
  // Handle result.nextStep.signInStep — e.g.:
  //   confirmSignInWithSmsMfaCode → prompt for SMS code, call confirmSignIn
  //   confirmSignInWithTotpMfaCode → prompt for TOTP code, call confirmSignIn
  //   confirmSignInWithNewPassword → prompt new password, call confirmSignIn
  //   done → authenticated
}
```

**Confirm sign-in** (for MFA / challenge steps):

```dart
final result = await Amplify.Auth.confirmSignIn(
  confirmationValue: codeFromUser,
);
```

**Sign up:**

```dart
final result = await Amplify.Auth.signUp(
  username: username,
  password: password,
  options: SignUpOptions(
    userAttributes: {AuthUserAttributeKey.email: email},
  ),
);
if (result.nextStep.signUpStep == AuthSignUpStep.confirmSignUp) {
  // Prompt for confirmation code
}
```

**Confirm sign-up:**

```dart
await Amplify.Auth.confirmSignUp(
  username: username,
  confirmationCode: code,
);
```

### Swift (Apple platforms)

Uses async/await.

```swift
import Amplify
```

**Sign in:**

```swift
do {
    let result = try await Amplify.Auth.signIn(
        username: username,
        password: password
    )
    switch result.nextStep {
    case .done:
        print("Sign in succeeded")
    case .confirmSignInWithSMSMFACode(let details, _):
        print("SMS code sent to \(details.destination)")
        // Prompt user, then call confirmSignIn
    case .confirmSignInWithTOTPCode:
        // Prompt for TOTP code, then call confirmSignIn
    default:
        print("Next step: \(result.nextStep)")
    }
} catch let error as AuthError {
    print("Sign in failed: \(error)")
}
```

**Confirm sign-in:**

```swift
let result = try await Amplify.Auth.confirmSignIn(
    challengeResponse: codeFromUser
)
```

**Sign up:**

```swift
let options = AuthSignUpRequest.Options(
    userAttributes: [AuthUserAttribute(.email, value: email)]
)
let result = try await Amplify.Auth.signUp(
    username: username,
    password: password,
    options: options
)
if case .confirmUser(let details, _, _) = result.nextStep {
    print("Confirmation sent to \(String(describing: details))")
}
```

**Confirm sign-up:**

```swift
try await Amplify.Auth.confirmSignUp(
    for: username,
    confirmationCode: code
)
```

### Android (Kotlin)

Android supports **both** Kotlin coroutines and callbacks. Coroutines are
recommended.

```kotlin
import com.amplifyframework.kotlin.core.Amplify
import com.amplifyframework.auth.AuthUserAttributeKey
import com.amplifyframework.auth.options.AuthSignUpOptions
```

**Sign in (coroutines — recommended):**

```kotlin
try {
    val result = Amplify.Auth.signIn("username", "password")
    if (result.isSignedIn) {
        Log.i("Auth", "Sign in succeeded")
    } else {
        // Handle result.nextStep.signInStep — e.g.:
        //   CONFIRM_SIGN_IN_WITH_SMS_MFA_CODE → prompt SMS code
        //   CONFIRM_SIGN_IN_WITH_TOTP_CODE → prompt TOTP code
        //   DONE → authenticated
        Log.i("Auth", "Next step: ${result.nextStep.signInStep}")
    }
} catch (error: AuthException) {
    Log.e("Auth", "Sign in failed", error)
}
```

**Sign in (callbacks — alternative):**

```kotlin
import com.amplifyframework.core.Amplify  // Java facade for callback style

Amplify.Auth.signIn("username", "password",
    { result -> Log.i("Auth", "Signed in: ${result.isSignedIn}") },
    { error -> Log.e("Auth", "Sign in failed", error) }
)
```

**Confirm sign-in (coroutines):**

```kotlin
try {
    val result = Amplify.Auth.confirmSignIn("code from user")
    Log.i("Auth", "Confirmed: $result")
} catch (error: AuthException) {
    Log.e("Auth", "Confirm failed", error)
}
```

**Sign up (coroutines):**

```kotlin
val options = AuthSignUpOptions.builder()
    .userAttributes(listOf(
        AuthUserAttribute(AuthUserAttributeKey.email(), email)
    ))
    .build()
try {
    val result = Amplify.Auth.signUp("username", "password", options)
    Log.i("Auth", "Sign up step: ${result.nextStep.signUpStep}")
} catch (error: AuthException) {
    Log.e("Auth", "Sign up failed", error)
}
```

**Confirm sign-up (coroutines):**

```kotlin
try {
    Amplify.Auth.confirmSignUp("username", "123456")
} catch (error: AuthException) {
    Log.e("Auth", "Confirm sign-up failed", error)
}
```

## Social Login on Mobile

Social sign-in uses an OAuth web UI redirect. **Callback URLs must match** the
`callbackUrls` configured in your `defineAuth` backend resource.

**Flutter:**

```dart
final result = await Amplify.Auth.signInWithWebUI(
  provider: AuthProvider.google,
);
```

Platform setup for Flutter OAuth:

- **Android:** Add `<intent-filter>` with your callback scheme to `MainActivity` in `AndroidManifest.xml`.
- **iOS:** No additional platform configuration required.
- **macOS:** Enable App Sandbox → "Incoming Connections (Server)" in Xcode.

**Swift:**

```swift
let result = try await Amplify.Auth.signInWithWebUI(
    for: .google,
    presentationAnchor: window
)
```

Platform setup: Add callback URL scheme to `Info.plist` under `CFBundleURLSchemes`.

**Android (coroutines):**

```kotlin
try {
    val result = Amplify.Auth.signInWithSocialWebUI(
        AuthProvider.google(), activity
    )
    Log.i("Auth", "Social sign-in OK: $result")
} catch (error: AuthException) {
    Log.e("Auth", "Social sign-in failed", error)
}
```

Platform setup: Add `HostedUIRedirectActivity` with your callback scheme to `AndroidManifest.xml`:

```xml
<activity
    android:name="com.amplifyframework.auth.cognito.activities.HostedUIRedirectActivity"
    android:exported="true">
    <intent-filter>
        <action android:name="android.intent.action.VIEW" />
        <category android:name="android.intent.category.DEFAULT" />
        <category android:name="android.intent.category.BROWSABLE" />
        <data android:scheme="myapp" />
    </intent-filter>
</activity>
```

## Pitfalls

- **Missing INTERNET permission (Android):** Without
  `<uses-permission android:name="android.permission.INTERNET"/>` in
  `AndroidManifest.xml`, all auth calls fail with a network error.
- **Callback URL mismatch (social login):** OAuth redirect URLs configured
  in the native app (Info.plist / AndroidManifest.xml / Flutter scheme)
  must match the `callbackUrls` in your `defineAuth` backend resource.
  A mismatch causes a silent redirect failure.
- **Unhandled auth steps (Custom UI only):** When building custom sign-in
  flows, the `nextStep` returned from `signIn` must be handled. Ignoring
  steps like MFA confirmation causes the auth flow to stall silently. The
  Authenticator component handles all steps automatically.

## Links

- [Authenticator (Android)](https://ui.docs.amplify.aws/android/connected-components/authenticator)
- [Authenticator (Swift)](https://ui.docs.amplify.aws/swift/connected-components/authenticator)
- [Authenticator (Flutter)](https://ui.docs.amplify.aws/flutter/connected-components/authenticator)
- [Auth Overview (Android)](https://docs.amplify.aws/android/build-a-backend/auth/)
- [Sign In (Android)](https://docs.amplify.aws/android/frontend/auth/sign-in/)
- [External Identity Providers (Android)](https://docs.amplify.aws/android/build-a-backend/auth/concepts/external-identity-providers/)
- [Multi-Factor Authentication (Android)](https://docs.amplify.aws/android/build-a-backend/auth/concepts/multi-factor-authentication/)
- [Auth Overview (Swift)](https://docs.amplify.aws/swift/build-a-backend/auth/)
- [Sign In (Swift)](https://docs.amplify.aws/swift/frontend/auth/sign-in/)
- [External Identity Providers (Swift)](https://docs.amplify.aws/swift/build-a-backend/auth/concepts/external-identity-providers/)
- [Multi-Factor Authentication (Swift)](https://docs.amplify.aws/swift/build-a-backend/auth/concepts/multi-factor-authentication/)
- [Auth Overview (Flutter)](https://docs.amplify.aws/flutter/build-a-backend/auth/)
- [Sign In (Flutter)](https://docs.amplify.aws/flutter/frontend/auth/sign-in/)
- [External Identity Providers (Flutter)](https://docs.amplify.aws/flutter/build-a-backend/auth/concepts/external-identity-providers/)
- [Multi-Factor Authentication (Flutter)](https://docs.amplify.aws/flutter/build-a-backend/auth/concepts/multi-factor-authentication/)
