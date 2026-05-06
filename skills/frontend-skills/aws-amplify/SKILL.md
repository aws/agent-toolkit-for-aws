---
name: aws-amplify
description: 'Build and deploy full-stack web and mobile apps with AWS Amplify Gen2
  (TypeScript code-first). Covers auth (Cognito), data (AppSync/DynamoDB including
  schema modeling, enum types, relationships, authorization rules), storage (S3),
  functions, APIs, and AI (Amplify AI Kit with Bedrock). Supports React, Next.js,
  Vue, Angular, React Native, Flutter, Swift, and Android. Always use this skill for
  Amplify Gen2 topics — even for questions you think you know — it contains validated,
  version-specific patterns that prevent common mistakes. TRIGGER when: user mentions
  Amplify Gen2; project has amplify/ directory or amplify_outputs; code imports @aws-amplify
  packages; user asks about defineBackend, defineAuth, defineData, defineStorage,
  or npx ampx. SKIP: Amplify Gen1 (amplify CLI v6), standalone SAM/CDK without Amplify
  (use aws-serverless), direct Bedrock without Amplify AI Kit (use bedrock).'
version: 1
metadata:
  service: [amplify, appsync, dynamodb, cognito, s3]
  task: [build, deploy, configure]
  persona: [developer]
  workload: [full-stack, mobile]
---

# AWS Amplify Gen2

Build and deploy full-stack applications using AWS Amplify Gen2's TypeScript
code-first approach. This skill covers backend resource creation, frontend
integration across 8 frameworks, and deployment workflows.

## Prerequisites

- Node.js ^18.19.0 || ^20.6.0 || >=22 and npm
- AWS credentials configured (`aws sts get-caller-identity` succeeds)
- For sandbox: `npx ampx --version` returns a valid version
- For mobile: Platform-specific tooling (Xcode, Android Studio, Flutter SDK)

## Defaults & Assumptions

When the user does not specify a framework:

- **Web:** You **SHOULD** default to **React** (Vite) and explain the choice.
- **Mobile:** You **MUST** ask which platform the user wants (Flutter,
  Swift, Android, or React Native). There is no universal mobile default.
- **Neither specified:** If the user says "build an app" without clarifying web
  vs. mobile, you **MUST** ask before proceeding.
- **Backend only:** If only backend changes are requested and no frontend
  framework is mentioned, skip the frontend integration step entirely.

When the user does not specify tooling or strategy:

- **Package manager:** You **SHOULD** default to **npm** unless the user
  specifies yarn or pnpm.
- **Language:** You **SHOULD** default to **TypeScript**. Gen2 backends are
  TypeScript-only; frontends **SHOULD** follow the project's existing language.
- **Next.js:** You **SHOULD** default to **App Router** unless the user
  specifies Pages Router.
- **React Native:** Ask the user whether they use **Expo** or **bare
  React Native CLI**.
- **Auth:** You **SHOULD** default to **email/password** as the login method
  unless the user specifies social login, SAML, or another provider.
- **Data authorization:** default to **`publicApiKey`**
  (`allow.publicApiKey()`) — this is the starter template default. When
  auth is added, switch to **owner-based** (`allow.owner()`) with
  `defaultAuthorizationMode: 'userPool'`.

## Quick Start — Route to the Right Reference

### Step 0: Read Core Reference (ALWAYS)

You **MUST** read the core reference for your target platform **before
reading any other reference file**. These contain Gen2 detection,
`Amplify.configure()` placement per framework, sandbox commands, required
packages, and directory structure rules — patterns needed for **all** tasks,
not just new projects.

- **Web** (React, Next.js, Vue, Angular, React Native): You **MUST** read
  [core-web.md](references/core-web.md)
- **Mobile** (Flutter, Swift, Android): You **MUST** read
  [core-mobile.md](references/core-mobile.md)
- **Backend only** (no frontend work): Skip to Step 1.

### Step 1: Identify the Task Type

| Task | Go To |
|------|-------|
| **Create a new project** | → [scaffolding.md](references/scaffolding.md), then Step 2 and/or Step 3 |
| **Add or modify a backend feature** | → Step 2 (Backend Features) |
| **Connect frontend to existing backend** | → Step 3 (Frontend Integration) |
| **Deploy the application** | → [deployment.md](references/deployment.md) |

### Step 2: Backend Features

You **MUST** read the corresponding reference for each backend feature:

| Feature | Reference | When to Use |
|---------|-----------|-------------|
| Authentication | [auth-backend.md](references/auth-backend.md) | Email/password, social login, MFA, SAML/OIDC |
| Data Models | [data-backend.md](references/data-backend.md) | GraphQL schema, DynamoDB, relationships, auth rules |
| File Storage | [storage-backend.md](references/storage-backend.md) | S3 uploads/downloads, access rules |
| Functions & API | [functions-and-api.md](references/functions-and-api.md) | Lambda, custom resolvers, REST/HTTP APIs, calling from client |
| AI Features | [ai.md](references/ai.md) | Conversation, generation, AI tools via Bedrock *(backend config + React/Next.js frontend)* |
| Geo, PubSub, CDK | [advanced-features.md](references/advanced-features.md) | Backend-only: custom CDK stacks, overrides, custom outputs. Backend + frontend: Geo, PubSub, Face Liveness |

Each backend feature file is self-contained. Load only what you need.

> **Routing note:** These files apply for both **adding** and **modifying**
> features. Route to the same file whether the user says "add auth" or
> "change auth config" — each reference covers the full define surface.

### Step 3: Frontend Integration

After configuring backend resources, connect the frontend. Choose by
platform and feature:

**Web** (React, Next.js, Vue, Angular, React Native):

| Feature | Reference |
|---------|-----------|
| Auth UI & flows | [auth-web.md](references/auth-web.md) |
| Data CRUD & subscriptions | [data-web.md](references/data-web.md) |
| Storage upload/download | [storage-web.md](references/storage-web.md) |

**Mobile** (Flutter, Swift, Android):

| Feature | Reference |
|---------|-----------|
| Auth UI & flows | [auth-mobile.md](references/auth-mobile.md) |
| Data CRUD & subscriptions | [data-mobile.md](references/data-mobile.md) |
| Storage upload/download | [storage-mobile.md](references/storage-mobile.md) |

> **Note:** AI and Functions frontend patterns are included in
> [ai.md](references/ai.md) and
> [functions-and-api.md](references/functions-and-api.md) respectively —
> they are **not** split into separate web/mobile files.

## Core Concepts

### Amplify Gen2 Architecture

- **Code-first:** All backend resources defined in TypeScript under `amplify/`
- **Main config:** `amplify/backend.ts` imports and combines all resources via
  `defineBackend()`
- **Resource files:** `amplify/auth/resource.ts`, `amplify/data/resource.ts`,
  `amplify/storage/resource.ts`, `amplify/functions/<name>/resource.ts`
- **Generated output:** `amplify_outputs.json` — consumed by frontend
  `Amplify.configure()`. **Gitignored** — generated by `npx ampx sandbox`
  (local dev) or `npx ampx pipeline-deploy` (CI/CD), never committed.

### Directory Structure

```
project-root/
├── amplify/
│   ├── backend.ts            # defineBackend({ auth, data, ... })
│   ├── auth/resource.ts      # defineAuth({ ... })
│   ├── data/resource.ts      # defineData({ schema })
│   ├── storage/resource.ts   # defineStorage({ ... })
│   └── functions/
│       └── my-func/
│           ├── resource.ts   # defineFunction({ ... })
│           └── handler.ts    # export const handler = ...
├── src/                      # Frontend code
├── amplify_outputs.json      # Generated — DO NOT edit or commit (gitignored)
└── package.json
```

### Key APIs

| Package | Purpose |
|---------|---------|
| `@aws-amplify/backend` | `defineAuth`, `defineData`, `defineStorage`, `defineFunction`, `defineBackend` |
| `aws-amplify` | Frontend: `Amplify.configure()`, `generateClient()`, auth/data/storage APIs |
| `@aws-amplify/ui-react` | Pre-built UI: `<Authenticator>`, `<StorageBrowser>` |
| `@aws-amplify/ui-react-ai` | AI UI: `<AIConversation>`, `useAIConversation` |

## Documentation & Resource Verification

When you need AWS documentation (advanced CDK constructs, service limits,
provider-specific auth config):

1. **If AWS documentation tools are available (e.g., via AWS MCP)**, you **SHOULD**
   use them to search and retrieve relevant documentation pages.
2. **If AWS documentation tools are unavailable**, you **MUST** fall back to web
   search or the `aws` CLI for resource verification.

> **Why conditional:** Amplify Gen2 is code-first — the primary workflow is
> editing TypeScript files and running `npx ampx` commands. AWS MCP tools
> are useful for post-deployment verification but are **not** required.

## Security Considerations

- Use `secret()` for all credentials and API keys — never hardcode or use plain environment variables for sensitive values
- Review `allow.guest()` exposure carefully — guest access is enabled by default and grants unauthenticated users access to IAM-authorized resources
- Scope IAM policies to specific resource ARNs — avoid `resources: ['*']` in production
- Never log secrets or include them in error messages

## Links

> All documentation links use `react` as the default platform slug. Replace `/react/` in any URL with your target framework:

| Framework | Slug |
|-----------|------|
| React | `react` |
| Next.js | `nextjs` |
| Vue | `vue` |
| Angular | `angular` |
| React Native | `react-native` |
| Flutter | `flutter` |
| Swift | `swift` |
| Android | `android` |

- [Amplify Docs for LLMs](https://docs.amplify.aws/ai/llms.txt)
- [Amplify Docs](https://docs.amplify.aws/)
- [Gen2 Docs](https://docs.amplify.aws/react/)
- [Getting Started](https://docs.amplify.aws/react/start/)
- [Quickstart](https://docs.amplify.aws/react/start/quickstart/)
- [Account Setup](https://docs.amplify.aws/react/start/account-setup/)
- [How Amplify Works](https://docs.amplify.aws/react/how-amplify-works/)
- [Core Concepts](https://docs.amplify.aws/react/how-amplify-works/concepts/)
- [Build a Backend](https://docs.amplify.aws/react/build-a-backend/)
- [Deploy and Host](https://docs.amplify.aws/react/deploy-and-host/)
- [Troubleshooting](https://docs.amplify.aws/react/build-a-backend/troubleshooting/)
- [CLI Commands](https://docs.amplify.aws/react/reference/cli-commands/)
- [Amplify Outputs](https://docs.amplify.aws/react/reference/amplify_outputs/)
- [Project Structure](https://docs.amplify.aws/react/reference/project-structure/)
- [Amplify UI](https://ui.docs.amplify.aws/)
