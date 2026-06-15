# Storage — Web

> **Prerequisites:** Project initialized, `amplify_outputs.json` exists (from `npx ampx sandbox`), and `Amplify.configure(outputs)` called in app entry point.
>
> **Backend required:** Storage must be defined in `amplify/storage/resource.ts`
> using `defineStorage` — see [storage-backend.md](storage-backend.md).

## API Reference

All imports from `'aws-amplify/storage'`.

| Operation | Call |
|---|---|
| Upload | `uploadData({ path: 'public/file.txt', data })` |
| Download blob | `await (await downloadData({ path }).result).body.blob()` |
| Presigned URL | `await getUrl({ path })` (default 15 min expiry) |
| List | `await list({ path: 'public/' })` → `{ items }` |
| Remove | `await remove({ path })` |
| Copy | `await copy({ source: { path }, destination: { path } })` |

> **Security:** Amplify Gen2 enables S3 server-side encryption (SSE-S3) by default. For sensitive data, consider configuring SSE-KMS with a customer-managed key via CDK overrides. Amplify also enforces HTTPS-only access to S3 buckets by default; if using custom bucket configurations, add a bucket policy with `"aws:SecureTransport": "false"` → Deny to ensure encryption in transit.

`uploadData` returns a control object: `.pause()`, `.resume()`, `.cancel()`, `.result` (Promise). Progress: `options.onProgress: ({ transferredBytes, totalBytes }) => …`.

Custom bucket: `options: { bucket: 'nameFromDefineStorage' }` or `{ bucket: { bucketName, region } }`. Raw ARN does **NOT** work.

## React UI Components

`npm add @aws-amplify/ui-react-storage` — import **both** CSS files or components render unstyled:

```typescript
import '@aws-amplify/ui-react/styles.css';
import '@aws-amplify/ui-react-storage/styles.css';
```

**WARNING:** Missing either CSS import causes unstyled components.

| Component            | Import from                             | Key props / setup                                                                                         |
| -------------------- | --------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `<StorageBrowser />` | `@aws-amplify/ui-react-storage/browser` | `createStorageBrowser({ config: createAmplifyAuthAdapter() })` — bucket specified by name string, NOT ARN |
| `<StorageImage />`   | `@aws-amplify/ui-react-storage`         | `alt`, `path`                                                                                             |
| `<FileUploader />`   | `@aws-amplify/ui-react-storage`         | `path`, `maxFileCount`, `acceptedFileTypes`                                                               |

### StorageBrowser Requirements

- Must be inside an `<Authenticator>` component (needs auth context)
- Must have an explicit height on the container (component doesn't set its own height)
- Client-side only — use dynamic import with `ssr: false` in Next.js
- Both CSS files required: `@aws-amplify/ui-react/styles.css` and `@aws-amplify/ui-react-storage/styles.css`

## React Native

Same JS API as web — all imports from `'aws-amplify/storage'`:

`uploadData`, `downloadData`, `getUrl`, `list`, `remove` — identical signatures. Use `react-native-image-picker` or `expo-document-picker` for file selection.

## Pitfalls

- **`{entity_id}` paths:** `protected/{entity_id}/` and `private/{entity_id}/` resolve to the user's Cognito identity ID at runtime.
- **Upload cancellation:** `result.cancel()` rejects the promise — catch `CanceledError` to handle it gracefully.

## Common Patterns

### Displaying Uploaded Images

Use `getUrl()` to generate presigned URLs for display:

```typescript
import { getUrl } from "aws-amplify/storage";

const result = await getUrl({
  path: "photos/my-photo.jpg",
  options: { expiresIn: 3600 }, // URL valid for 1 hour
});

// Use in img tag
<img src={result.url.toString()} alt="Photo" />
```

> **Note:** Presigned URLs expire (default 15 minutes). Use `expiresIn` to set a custom duration.

## Links

- [Storage Overview (React)](https://docs.amplify.aws/react/build-a-backend/storage/)
- [Set Up Storage (React)](https://docs.amplify.aws/react/build-a-backend/storage/set-up-storage/)
- [Upload Files (React)](https://docs.amplify.aws/react/frontend/storage/upload-files/)
- [Download Files (React)](https://docs.amplify.aws/react/frontend/storage/download-files/)
- [List Files (React)](https://docs.amplify.aws/react/frontend/storage/list-files/)
- [Remove Files (React)](https://docs.amplify.aws/react/frontend/storage/remove-files/)
- [Copy Files (React)](https://docs.amplify.aws/react/frontend/storage/copy-files/)
- [Storage Overview (Next.js)](https://docs.amplify.aws/nextjs/build-a-backend/storage/)
- [Storage Overview (React Native)](https://docs.amplify.aws/react-native/build-a-backend/storage/)
- [Upload Files (React Native)](https://docs.amplify.aws/react-native/frontend/storage/upload-files/)
- [Download Files (React Native)](https://docs.amplify.aws/react-native/frontend/storage/download-files/)
