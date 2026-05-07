# Auth — Web

> **Backend required:** Auth must be defined in `amplify/auth/resource.ts`
> using `defineAuth` — see [auth-backend.md](auth-backend.md).

## Authenticator Component

| Framework       | Package                   | Tag                                                      | CSS (MUST import)                   |
| --------------- | ------------------------- | -------------------------------------------------------- | ----------------------------------- |
| React / Next.js | `@aws-amplify/ui-react`   | `<Authenticator>`                                        | `@aws-amplify/ui-react/styles.css`  |
| Vue             | `@aws-amplify/ui-vue`     | `<Authenticator>`                                        | `@aws-amplify/ui-vue/styles.css`    |
| Angular         | `@aws-amplify/ui-angular` | `<amplify-authenticator>` + `AmplifyAuthenticatorModule` | `@aws-amplify/ui-angular/theme.css` |

Props: `loginMechanisms={['email']}`, `socialProviders={['google']}`.
Slot: `{({ signOut, user }) => ...}` — access `user?.signInDetails?.loginId`.
Next.js SSR: wrap layout in `<Authenticator.Provider>`, use `useAuthenticator` hook.

## Manual Auth Flows

Imports from `aws-amplify/auth`: `signIn`, `signUp`, `confirmSignUp`, `confirmSignIn`, `signOut`, `resetPassword`.

After `signIn()`, you **MUST** switch on `result.nextStep.signInStep`:

| signInStep value                               | Action                                                             |
| ---------------------------------------------- | ------------------------------------------------------------------ |
| `DONE`                                         | Authenticated                                                      |
| `CONFIRM_SIGN_UP`                              | Call `confirmSignUp()`                                             |
| `CONFIRM_SIGN_IN_WITH_TOTP_CODE`               | Prompt TOTP, call `confirmSignIn({ challengeResponse })`           |
| `CONFIRM_SIGN_IN_WITH_SMS_CODE`                | Prompt SMS code, same                                              |
| `CONFIRM_SIGN_IN_WITH_EMAIL_CODE`              | Prompt email code, same                                            |
| `CONTINUE_SIGN_IN_WITH_TOTP_SETUP`             | Show QR URI, call `confirmSignIn()`                                |
| `CONTINUE_SIGN_IN_WITH_MFA_SELECTION`          | `confirmSignIn({ challengeResponse: 'TOTP' \| 'SMS' \| 'EMAIL' })` |
| `RESET_PASSWORD`                               | Call `resetPassword()`                                             |
| `CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED`   | `confirmSignIn({ challengeResponse: newPassword })`                |
| `CONFIRM_SIGN_IN_WITH_CUSTOM_CHALLENGE`        | `confirmSignIn({ challengeResponse })`                             |
| `CONFIRM_SIGN_IN_WITH_PASSWORD`                | `confirmSignIn({ challengeResponse: password })`                   |
| `CONTINUE_SIGN_IN_WITH_MFA_SETUP_SELECTION`    | `confirmSignIn({ challengeResponse: 'TOTP' \| 'EMAIL' })`          |
| `CONTINUE_SIGN_IN_WITH_EMAIL_SETUP`            | Prompt email, call `confirmSignIn()`                               |
| `CONTINUE_SIGN_IN_WITH_FIRST_FACTOR_SELECTION` | `confirmSignIn({ challengeResponse: selectedFactor })`             |

OAuth/social: `signInWithRedirect({ provider: 'Google' })`.

## Session Management

| API (from `aws-amplify/auth`) | Returns                                                                                                |
| ----------------------------- | ------------------------------------------------------------------------------------------------------ |
| `getCurrentUser()`            | `{ userId, username, signInDetails? }`                                                                 |
| `fetchAuthSession()`          | `{ tokens?, credentials?, identityId?, userSub? }` — access `.tokens?.idToken`, `.tokens?.accessToken` |
| `fetchUserAttributes()`       | `{ email, phone_number, ... }`                                                                         |

Tokens refresh automatically.

## Next.js Server-Side Auth

For server components and route handlers, use cookie-based auth:

```typescript
import { generateServerClientUsingCookies } from '@aws-amplify/adapter-nextjs/data';
import { cookies } from 'next/headers';
import outputs from '@/amplify_outputs.json';

const client = generateServerClientUsingCookies({ config: outputs, cookies });
```

> **Critical:** `generateServerClientUsingCookies` from `@aws-amplify/adapter-nextjs/data` is the ONLY way to access authenticated data in Next.js server components. Do NOT use `generateClient()` on the server side — it has no access to the user's session cookies.

For server actions and middleware, use `createServerRunner` from `@aws-amplify/adapter-nextjs`:

```typescript
import { createServerRunner } from '@aws-amplify/adapter-nextjs';
import outputs from '@/amplify_outputs.json';

export const { runWithAmplifyServerContext } = createServerRunner({ config: outputs });
```

## React Native

React Native uses the same `aws-amplify` auth APIs as web. All manual auth
flows (`signIn`, `signUp`, `confirmSignIn`, etc.) and session management
APIs work identically.

### Setup

**Import order matters:** `react-native-get-random-values` **MUST** be
the FIRST import in the entry file, `@aws-amplify/react-native` **MUST**
come before `aws-amplify`. See [core-web.md](core-web.md) for the
full required import order.

```bash
npm install @aws-amplify/ui-react-native @react-native-async-storage/async-storage
```

Same `<Authenticator>` prop API as web React (from `@aws-amplify/ui-react-native`).
`@react-native-async-storage/async-storage` is **required** for token persistence.

### Social Login

`signInWithRedirect({ provider: 'Google' })` — same as web. Ensure
callback URLs in `defineAuth` include your Expo scheme.

## Pitfalls

- **Missing CSS import:** Without the `styles.css` import, the
  `<Authenticator>` renders as unstyled HTML.
- **Unhandled sign-in steps:** Not switching on ALL `signInStep` values
  causes the flow to silently stall on MFA or password-reset challenges.
  You **MUST** handle every possible value — missing any causes the auth
  flow to hang with no visible error.
- **MFA timing:** Calling `updateMFAPreference()` before authentication
  completes fails silently because the user is not yet authenticated.
  Wait until `signInStep` is `'DONE'`.
- **OAuth in multi-page apps:** You **MUST** call `Hub.listen('auth', ...)`
  to capture the OAuth redirect callback on page reload.
- **Vue component syntax:** Vue **MUST** use PascalCase `<Authenticator>`
  component syntax (not kebab-case `<authenticator>`).

## Links

- [Auth Overview (React)](https://docs.amplify.aws/react/build-a-backend/auth/)
- [Set Up Auth (React)](https://docs.amplify.aws/react/build-a-backend/auth/set-up-auth/)
- [Connect Auth Frontend (React)](https://docs.amplify.aws/react/frontend/auth/)
- [Auth Overview (Next.js)](https://docs.amplify.aws/nextjs/build-a-backend/auth/)
- [Set Up Auth (Next.js)](https://docs.amplify.aws/nextjs/build-a-backend/auth/set-up-auth/)
- [Connect Auth Frontend (Next.js)](https://docs.amplify.aws/nextjs/frontend/auth/)
- [Auth Overview (React Native)](https://docs.amplify.aws/react-native/build-a-backend/auth/)
- [Set Up Auth (React Native)](https://docs.amplify.aws/react-native/build-a-backend/auth/set-up-auth/)
- [Connect Auth Frontend (React Native)](https://docs.amplify.aws/react-native/frontend/auth/)
