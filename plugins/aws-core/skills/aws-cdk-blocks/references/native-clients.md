# Native clients: Swift, Kotlin, Dart

Contents: [Backend and API spec](#backend-and-api-spec), [Swift](#swift-ios-macos), [Kotlin](#kotlin-android-ios-jvm-desktop), [Dart and Flutter](#dart-and-flutter), [Sign-in](#sign-in).

A native client is generated from the backend's API spec. Web apps and APIs do not need this file.

## Backend and API spec

Scaffold the backend with `--template api-only`: no web frontend, an `Auth` Block exported as `authApi`, a sign-in-gated resource and a public health check. Then, from the app root, start the local server:

```bash
npm run dev > dev.log 2>&1 &
```

The server writes `.cdk-blocks-sandbox/config.json` while it starts, and the spec takes its server URL from that file. Once the file exists, write the spec:

```bash
npm run spec
```

- `npm run spec` writes `cdk-blocks/blocks.spec.json` and prints `OpenRPC spec written to` with the path. The file is git-ignored. Neither the local server nor a deploy writes it: run `npm run spec` again after a change to an exported API, then rebuild the client.
- The spec carries one server URL, which the generated `Blocks()` client uses: the local server by default. For a deployed backend, deploy first (ask the user: it changes their AWS account), then run `BLOCKS_SPEC_STAGE=sandbox npm run spec`, or `production`.
- A URL passed by hand is the full API URL ending in `/cdk-blocks/api`, not the origin. An Android emulator reaches the local server at `http://10.0.2.2:3001/cdk-blocks/api`.

Each snippet below leaves versions as placeholders: take the released version from the SDK's guide.

## Swift (iOS, macOS)

```swift
// Package.swift
.package(url: "https://github.com/aws/cdk-blocks-swift.git", .upToNextMinor(from: "<version>")),
// in the target
dependencies: [.product(name: "BlocksRuntime", package: "cdk-blocks-swift")],
plugins: [.plugin(name: "BlocksCodegenBuildPlugin", package: "cdk-blocks-swift")],
```

Copy the spec to `Sources/<Target>/blocks.spec.json`. Every build regenerates the client.

```swift
import BlocksRuntime
let blocks = Blocks() // one instance, held in app-scoped state
let state = try await blocks.authApi.getAuthState()
```

The SDK keeps the session in the Keychain; the app stores nothing. Guide: `native/swift/README.md`.

## Kotlin (Android, iOS, JVM desktop)

```kotlin
// build.gradle.kts
plugins {
    id("org.jetbrains.kotlin.plugin.serialization") version "<kotlin version>"
    id("com.aws.blocks.kotlin") version "<version>"
}
dependencies { implementation("com.aws.blocks.kotlin:runtime:<version>") }
cdkBlocks {
    apiSpec = rootProject.file("cdk-blocks/blocks.spec.json")
    packageName = "com.example.myapp.generated"
}
```

Building the module generates the client.

```kotlin
import com.example.myapp.generated.defaultServer
import com.example.myapp.generated.invoke // without it, Blocks() does not resolve to the generated client

val blocks = Blocks(BlocksConfig(server = Blocks.defaultServer, applicationId = "com.example.myapp"))
val state = blocks.authApi.getAuthState()
```

A JVM desktop app keeps the session across restarts only when `applicationId` is set. Guide: `native/kotlin/README.md`.

## Dart and Flutter

```yaml
# pubspec.yaml
dependencies:
  blocks_runtime: ^<version>
dev_dependencies:
  blocks_codegen: ^<version>
  build_runner: ^<version>
```

```yaml
# build.yaml
targets:
  $default:
    builders:
      blocks_codegen|blocks_codegen:
        options:
          spec: lib/blocks.spec.json
```

Copy the spec to `lib/blocks.spec.json` and run `dart run build_runner build`.

```dart
import 'package:blocks_runtime/blocks_runtime.dart';
import 'blocks.blocks.dart';

final blocks = Blocks(baseUrl: 'http://localhost:3001/cdk-blocks/api');
final state = await blocks.authApi.getAuthState();
```

The session stays in memory unless the app passes `sessionStore:`. In Flutter, add `blocks_runtime_flutter`, create a `PersistentSessionStore(store: FlutterSecureStore())`, `await` its `load()` before the first call, and pass it as `sessionStore:`. Guide: `native/dart/README.md`.

## Sign-in

`authApi.getAuthState()` returns the state and the actions it allows; submit one with `setAuthState`. Call `getAuthState()` at launch to restore a session. Never store passwords or tokens in app code: each SDK keeps the session as described above.

The guides are paths in <https://github.com/aws/cdk-blocks>.
