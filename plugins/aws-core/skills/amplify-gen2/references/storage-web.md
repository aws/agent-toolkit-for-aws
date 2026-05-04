# Storage — Web

> **Backend required:** Storage must be defined in `amplify/storage/resource.ts`
> using `defineStorage` — see [storage-backend.md](storage-backend.md).

## API Reference

All imports from `'aws-amplify/storage'`.

| Operation | Call |
|---|---|
| Upload | `uploadData({ path: 'public/file.txt', data })` |
| Download blob | `(await downloadData({ path }).result).body.blob()` |
| Presigned URL | `await getUrl({ path })` (default 15 min expiry) |
| List | `await list({ path: 'public/' })` → `{ items }` |
| Remove | `await remove({ path })` |
| Copy | `await copy({ source: { path }, destination: { path } })` |

`uploadData` returns a control object: `.pause()`, `.resume()`, `.cancel()`, `.result` (Promise). Progress: `options.onProgress: ({ transferredBytes, totalBytes }) => …`.

Custom bucket: `options: { bucket: 'nameFromDefineStorage' }` or `{ bucket: { bucketName, region } }`. Raw ARN does **NOT** work.

## React UI Components

`npm add @aws-amplify/ui-react-storage` — you **MUST** import **BOTH** CSS files or components render unstyled:

```typescript
import '@aws-amplify/ui-react/styles.css';
import '@aws-amplify/ui-react-storage/styles.css';
```

**WARNING:** Missing either CSS import causes unstyled components.
Training data often omits the second import.

| Component | Import from | Key props / setup |
|---|---|---|
| `<StorageBrowser />` | `@aws-amplify/ui-react-storage/browser` | `createStorageBrowser({ config: createAmplifyAuthAdapter() })` — bucket specified by name string, NOT ARN |
| `<StorageImage />` | `@aws-amplify/ui-react-storage` | `alt`, `path` |
| `<FileUploader />` | `@aws-amplify/ui-react-storage` | `path`, `maxFileCount`, `acceptedFileTypes` |

## React Native

Same JS API as web — all imports from `'aws-amplify/storage'`:

`uploadData`, `downloadData`, `getUrl`, `list`, `remove` — identical signatures. Use `react-native-image-picker` or `expo-document-picker` for file selection.

## Pitfalls

- **`{entity_id}` paths:** `protected/{entity_id}/` and `private/{entity_id}/` resolve to the user's Cognito identity ID at runtime.
- **Upload cancellation:** `uploadData` returns a task with `.cancel()` — call `task.cancel()`, not `result.cancel()`. Await `task.result` for the final outcome and catch `CanceledError`.
- **Bucket option:** Accepts string name (matching `defineStorage` `name`) or `{ bucketName, region }` — raw ARN does **NOT** work.

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
