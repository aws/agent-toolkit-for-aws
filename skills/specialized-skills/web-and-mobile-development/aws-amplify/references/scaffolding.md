# Scaffolding

> **Prerequisites:** Node.js ^18.19.0 || ^20.6.0 || >=22, npm, and AWS credentials configured.

## Starter Templates

Use official starter templates — hand-crafted structures can break
Amplify Hosting deployment detection.

```bash
git clone <TEMPLATE_URL> my-app && cd my-app && rm -rf .git && git init && npm install
```

| Framework | Template URL |
|-----------|-------------|
| React (Vite) | `https://github.com/aws-samples/amplify-vite-react-template` |
| Next.js (App Router) | `https://github.com/aws-samples/amplify-next-template` |
| Next.js (Pages Router) | `https://github.com/aws-samples/amplify-next-pages-template` |
| Vue | `https://github.com/aws-samples/amplify-vue-template` |
| Angular | `https://github.com/aws-samples/amplify-angular-template` |

## Web — Brownfield

For existing web projects, add Amplify Gen2 without overwriting application
code. You **SHOULD** use the create command for automatic setup:

```bash
npm create amplify@latest -y
```

Use the `-y` flag for non-interactive execution — without it, the command
prompts interactively and hangs in agent/CI environments. This
scaffolds the `amplify/` directory and installs backend dependencies.

For monorepos or custom build pipelines where the create command conflicts,
install manually:

```bash
npm install --save-dev @aws-amplify/backend@latest @aws-amplify/backend-cli@latest typescript
```

> **Note:** `aws-cdk-lib` and `constructs` are peer dependencies — npm 7+ installs them automatically. If using `--legacy-peer-deps`, install them explicitly.

Then create `amplify/backend.ts`:

```typescript
import { defineBackend } from '@aws-amplify/backend';
defineBackend({});
```

Install the frontend library:

```bash
npm install aws-amplify
```

> **Next.js SSR:** `npm create amplify@latest` does NOT install `@aws-amplify/adapter-nextjs`. Add manually for server-side rendering:
>
> ```bash
> npm install @aws-amplify/adapter-nextjs
> ```

## Web — React Native

### Expo

```bash
npx --yes create-expo-app@latest my-app
cd my-app
npm create amplify@latest -y
npm install aws-amplify @aws-amplify/react-native @react-native-async-storage/async-storage react-native-get-random-values
```

### Bare CLI

```bash
npx --yes @react-native-community/cli init MyApp --pm npm
cd MyApp
npm create amplify@latest -y
npm install aws-amplify @aws-amplify/react-native @react-native-async-storage/async-storage react-native-get-random-values
npx --yes pod-install # iOS only
```

## Mobile — Flutter

```bash
flutter create --platforms ios,android my_app
cd my_app
npm create amplify@latest -y
```

Add dependencies to `pubspec.yaml`:

```yaml
dependencies:
  amplify_flutter: ^2.0.0
  amplify_auth_cognito: ^2.0.0
```

Then run `flutter pub get`.

## Mobile — Swift (Apple platforms)

Do not create the Xcode project from the CLI — assume an existing
Xcode project is open in Xcode.

1. In the project root (where `.xcodeproj` lives), run:
   `npm create amplify@latest -y`
2. Add the Swift package via Xcode: File → Add Package Dependencies →
   `https://github.com/aws-amplify/amplify-swift` (Up to Next Major Version).
3. Add `amplify_outputs.json` to the Xcode project (drag into navigator,
   check "Copy items if needed").

## Mobile — Android

Do not create the Android project from the CLI — assume an
existing Android Studio project.

1. In the project root, run: `npm create amplify@latest -y`
2. Add dependencies to `app/build.gradle.kts`:

   ```kotlin
   dependencies {
       implementation("com.amplifyframework:core:2.+")
       implementation("com.amplifyframework:aws-auth-cognito:2.+")
   }
   ```

3. Copy `amplify_outputs.json` into `app/src/main/res/raw/`.

## Generate amplify_outputs

> For mobile projects, this step must be completed before the app can build.
> Run the sandbox before opening the mobile project.

**WARNING:** After scaffolding, run `npx ampx sandbox --once`
(or `npx ampx sandbox` for local dev) **before** `npm run dev`. This
generates `amplify_outputs.json`, which the frontend imports at build time.
Without it, the app fails to compile because
`import outputs from '../amplify_outputs.json'` resolves to nothing.

### Development Workflow

```bash
# Terminal 1 — Start sandbox (watch mode, auto-deploys on changes)
npx ampx sandbox

# Terminal 2 — Start dev server (requires amplify_outputs.json from sandbox)
npm run dev
```

**Sandbox modes:**

- `npx ampx sandbox` — Watch mode, continuously deploys changes (recommended for development)
- `npx ampx sandbox --once` — Single deployment then exits (for CI/CD or initial setup)

> **First time:** Run `npx ampx sandbox` and wait for it to generate `amplify_outputs.json` before starting your dev server.

`amplify_outputs.json` is gitignored — see [deployment.md](deployment.md) for generation details.

### Sandbox Stack Naming

The sandbox stack name is derived from your project's root `package.json` name. If you clone a template, change the name to avoid collisions:

```json
{ "name": "my-unique-app-name" }
```

Running multiple projects with the same `name` simultaneously causes one sandbox to overwrite another.

## Pitfalls

- Using the wrong template for a web framework causes broken build configs.
  Always match template to framework exactly.
- Forgetting `npm create amplify@latest -y` after the framework scaffold
  is the most common mistake — without it, there is no `amplify/` directory.
- React Native requires `@react-native-async-storage/async-storage` — the
  Amplify SDK uses it for token persistence and will fail at runtime without it.

## Links

- [React Quickstart](https://docs.amplify.aws/react/start/quickstart/)
- [Next.js Quickstart](https://docs.amplify.aws/nextjs/start/quickstart/)
- [Vue Quickstart](https://docs.amplify.aws/vue/start/quickstart/)
- [Angular Quickstart](https://docs.amplify.aws/angular/start/quickstart/)
- [React Native Quickstart](https://docs.amplify.aws/react-native/start/quickstart/)
- [Flutter Quickstart](https://docs.amplify.aws/flutter/start/quickstart/)
- [Swift Quickstart](https://docs.amplify.aws/swift/start/quickstart/)
- [Android Quickstart](https://docs.amplify.aws/android/start/quickstart/)
- [Manual Installation](https://docs.amplify.aws/react/start/manual-installation/)
- [Account Setup](https://docs.amplify.aws/react/start/account-setup/)
- [Sandbox Environments](https://docs.amplify.aws/react/deploy-and-host/sandbox-environments/setup/)
- [CLI Commands](https://docs.amplify.aws/react/reference/cli-commands/)
