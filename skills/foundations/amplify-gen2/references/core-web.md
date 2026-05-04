# Core — Web

## Critical Rules

These patterns apply to **every** task — not just new projects. You **MUST**
verify each one before implementing any feature.

### Gen2 Detection

Before modifying any code, check if the project is already Gen2:

1. `amplify/` directory exists with `backend.ts`
2. `@aws-amplify/backend` in `package.json` devDependencies

If both are true, the project is already Gen2 — skip to feature
implementation. If `amplify/.config/` exists instead, this is a Gen1
project — **MUST NOT** proceed (requires separate migration skill).

### Directory Structure

`amplify/` and `src/` **MUST** be siblings under the project root. Placing
them at different directory levels breaks sandbox detection.

```
project-root/
├── amplify/
│ ├── backend.ts
│ ├── auth/resource.ts
│ ├── data/resource.ts
│ └── storage/resource.ts
├── src/
├── amplify_outputs.json # Generated — DO NOT edit
└── package.json
```

### Frontend Configuration

Import the generated outputs and configure Amplify in the **correct entry
point** for your framework. Placing this in the wrong file causes silent
failures — Amplify API calls return undefined or empty responses with no error.

**WARNING:** `amplify_outputs.json` **MUST** exist before the app can
compile. If missing, the build fails with a module-not-found error.
Run `npx ampx sandbox` (or `npx ampx sandbox --once`) first to
generate it. See [scaffolding.md](scaffolding.md) for the correct sequence.
**React (Vite)** — `src/main.tsx`:

```typescript
import { Amplify } from 'aws-amplify';
import outputs from '../amplify_outputs.json';
Amplify.configure(outputs);
```

**Next.js (App Router)** — `app/layout.tsx`:

```typescript
import { Amplify } from 'aws-amplify';
import outputs from '@/amplify_outputs.json';
Amplify.configure(outputs, { ssr: true });
```

**`{ ssr: true }` applies only to Next.js App Router.** All other frameworks
(Vue, Angular, React SPA) omit this option.
**Vue** — `src/main.js`:

```javascript
import { Amplify } from 'aws-amplify';
import outputs from '../amplify_outputs.json';
Amplify.configure(outputs);
```

**Angular** — `src/main.ts`:

```typescript
import { Amplify } from 'aws-amplify';
import outputs from '../amplify_outputs.json';
Amplify.configure(outputs);
```

## Data Client Best Practices

See [data-web.md](data-web.md) for `generateClient` setup and module-scope rules.

For Next.js Server Components, use `generateServerClientUsingCookies` from
`@aws-amplify/adapter-nextjs/data` — NOT `generateClient`. Server
components have no browser session, so `generateClient` fails silently.
`<Authenticator.Provider>` is required in `layout.tsx` for auth context.

## React Native

React Native uses the same `aws-amplify` JS package as web frameworks (it is
part of amplify-js, not the native mobile SDKs). All web APIs apply to RN
with the additions below.

### Required Packages

```bash
npm install aws-amplify @aws-amplify/react-native \
  @react-native-async-storage/async-storage \
  react-native-get-random-values
```

`@react-native-async-storage/async-storage` is **required** — the Amplify
SDK uses it for token persistence and will fail at runtime without it.

### Configure Entry Points

No plugin registration needed — configure only.

**React Native (Expo)** — `App.tsx`:

```typescript
import 'react-native-get-random-values';  // MUST be first
import { Amplify } from 'aws-amplify';
import outputs from './amplify_outputs.json';
Amplify.configure(outputs);
```

**React Native (Bare CLI)** — `index.js` (before `AppRegistry.registerComponent`):

```typescript
import 'react-native-get-random-values';  // MUST be first
import { Amplify } from 'aws-amplify';
import outputs from './amplify_outputs.json';
Amplify.configure(outputs);
```

### Gen2 Detection (React Native)

Same as web — check for `amplify/` directory with `backend.ts` and
`@aws-amplify/backend` in `package.json` devDependencies.

### React Native Pitfalls

- **Import order:** `react-native-get-random-values` **MUST** be the FIRST
  import in the entry file, before `aws-amplify`. Reversing the order causes
  cryptographic failures at runtime.
- **Missing AsyncStorage:** Without
  `@react-native-async-storage/async-storage`, auth tokens are not persisted
  and users must re-authenticate on every app restart.

## Pitfalls

- Forgetting to import `amplify_outputs.json` in the entry point — the app
  will load but all Amplify API calls will fail silently.

## Links

- [React Quickstart](https://docs.amplify.aws/react/start/quickstart/)
- [Next.js Quickstart](https://docs.amplify.aws/nextjs/start/quickstart/)
- [Angular Quickstart](https://docs.amplify.aws/angular/start/quickstart/)
- [Vue Quickstart](https://docs.amplify.aws/vue/start/quickstart/)
- [React Native Quickstart](https://docs.amplify.aws/react-native/start/quickstart/)
