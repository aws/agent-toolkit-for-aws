# Storage — Mobile

> **Backend required:** Storage must be defined in `amplify/storage/resource.ts`
> using `defineStorage` — see [storage-backend.md](storage-backend.md).

## Flutter

Imports: `amplify_flutter` + `amplify_storage_s3`. All paths wrapped with `StoragePath.fromString()`.

| Operation | Call |
|---|---|
| Upload file | `Amplify.Storage.uploadFile(localFile: AWSFile.fromPath(path), path: const StoragePath.fromString('public/photo.jpg'))` |
| Download file | `Amplify.Storage.downloadFile(path: const StoragePath.fromString('public/photo.jpg'), localFile: localFile)` |
| List | `Amplify.Storage.list(path: const StoragePath.fromString('public/'))` → `.result.items` |
| Presigned URL | `Amplify.Storage.getUrl(path: const StoragePath.fromString('public/file.jpg'))` |
| Remove | `Amplify.Storage.remove(path: const StoragePath.fromString('public/file.jpg'))` |

Upload progress — use the `onProgress` callback parameter:

```dart
final op = Amplify.Storage.uploadFile(
  localFile: AWSFile.fromPath('/path/to/file'),
  path: const StoragePath.fromString('public/photos/photo.jpg'),
  onProgress: (p) => print('fraction: ${p.fractionCompleted}'),
);
final result = await op.result;
```

**MUST** use `const` with `StoragePath.fromString()` for compile-time constant paths.

## Swift (Apple platforms)

> Supported: iOS 13+, macOS 12+, tvOS 13+, watchOS 9+, visionOS 1+ (preview).

Uses `Amplify.Storage` with async/await. Import: `Amplify`.

| Operation | Call |
|---|---|
| Upload data | `Amplify.Storage.uploadData(path: .fromString("public/file.txt"), data: data)` → `try await task.value` |
| Upload file | `Amplify.Storage.uploadFile(path: .fromString("public/file.txt"), local: fileUrl)` → `try await task.value` |
| Download data | `Amplify.Storage.downloadData(path: .fromString("public/file.txt"))` → `.value` returns `Data` |
| Download file | `Amplify.Storage.downloadFile(path: .fromString("public/path"), local: fileUrl)` → `try await task.value` |
| List | `try await Amplify.Storage.list(path: .fromString("public/"))` → `.items` |
| Presigned URL | `try await Amplify.Storage.getURL(path: .fromString("public/file.jpg"))` |
| Remove | `try await Amplify.Storage.remove(path: .fromString("public/file.jpg"))` |

**Download with progress tracking:**

```swift
let downloadTask = Amplify.Storage.downloadData(
    path: .fromString("public/example.jpg")
)
Task {
    for await progress in await downloadTask.progress {
        print("Progress: \(progress.fractionCompleted)")
    }
}
let data = try await downloadTask.value
```

**Upload with progress tracking:**

```swift
let uploadTask = Amplify.Storage.uploadData(
    path: .fromString("public/photo.jpg"),
    data: imageData
)
Task {
    for await progress in await uploadTask.progress {
        print("Progress: \(progress)")
    }
}
let result = try await uploadTask.value
```

Use SwiftUI's `PhotosPicker` (from `import PhotosUI`) to obtain image data,
then pass to `uploadData`.

## Android (Kotlin)

Android supports both callback-based and coroutine-based APIs.
Import: `com.amplifyframework.core.Amplify`, `com.amplifyframework.storage.StoragePath`.

**Coroutine example (recommended):**

```kotlin
private suspend fun uploadFile() {
    val exampleFile = File(applicationContext.filesDir, "example")
    exampleFile.writeText("Example file contents")
    val upload = Amplify.Storage.uploadFile(
        StoragePath.fromString("public/example"), exampleFile
    )
    try {
        val result = upload.result()
        Log.i("MyAmplifyApp", "Successfully uploaded: ${result.path}")
    } catch (error: StorageException) {
        Log.e("MyAmplifyApp", "Upload failed", error)
    }
}
```

```kotlin
private suspend fun downloadFile() {
    val download = Amplify.Storage.downloadFile(
        StoragePath.fromString("public/example"), localFile
    )
    try {
        val result = download.result()
        Log.i("MyAmplifyApp", "Successfully downloaded: ${result.file.name}")
    } catch (error: StorageException) {
        Log.e("MyAmplifyApp", "Download failed", error)
    }
}
```

| Operation (coroutine) | Call |
|---|---|
| Upload file | `Amplify.Storage.uploadFile(StoragePath.fromString("public/photo.jpg"), file)` → `.result()` |
| Upload stream | `Amplify.Storage.uploadInputStream(StoragePath.fromString("public/example"), stream)` → `.result()` |
| Download file | `Amplify.Storage.downloadFile(StoragePath.fromString("public/photo.jpg"), localFile)` → `.result()` |
| List | `Amplify.Storage.list(StoragePath.fromString("public/"))` → `.items` |
| Presigned URL | `Amplify.Storage.getUrl(StoragePath.fromString("public/file.jpg"))` → `.url` |
| Remove | `Amplify.Storage.remove(StoragePath.fromString("public/file.jpg"))` |

**Callback alternative:** all operations also accept `onSuccess`/`onError` lambdas — e.g.
`Amplify.Storage.uploadFile(StoragePath.fromString("public/photo.jpg"), file, { result -> ... }, { error -> ... })`.

## Permissions

For authenticated user paths, use `protected/{entity_id}/` or `private/{entity_id}/` — the `{entity_id}` resolves to the user's Cognito identity ID at runtime.

- **Android:** Verify `INTERNET` permission is declared in `AndroidManifest.xml` (usually present by default). If the app accesses the camera, add `CAMERA`; for gallery access, add `READ_MEDIA_IMAGES` (API 33+) or `READ_EXTERNAL_STORAGE` (older).
- **Apple (iOS/macOS):** No special permissions for S3 storage operations. If the app accesses the camera, add `NSCameraUsageDescription` in `Info.plist`. If the app accesses the photo library, add `NSPhotoLibraryUsageDescription`.
- **Flutter:** Follows Android/iOS rules above — add permissions in `AndroidManifest.xml` and `Info.plist` respectively.

## Pitfalls

- **Swift SDK uses `getURL` (capital URL), not `getUrl`:** Using the
  wrong casing (lowercase `l`) causes compile errors. JS/web uses
  `getUrl` (lowercase), but Swift uses `getURL`.
- **Wrong file wrapper per platform:** Flutter requires
  `AWSFile.fromPath()`, Swift uses `Data` (for `uploadData`) or a file
  URL (for `uploadFile`), Android uses `File`. Using the wrong type
  causes compile errors — check the platform's expected input.
- **Missing `StoragePath.fromString()`:** Flutter and Android require
  `StoragePath.fromString('path')` to wrap path strings. Passing a raw
  string literal does not compile.
- **Large file uploads on mobile:** For files over 5 MB, the SDK
  automatically uses multipart upload. You **SHOULD** implement
  progress tracking (`onProgress` in Flutter, `for await progress in ...`
  in Swift, `transferObserver` or progress callback in Android) to show
  upload progress to the user.

## Links

- [Storage Overview (Android)](https://docs.amplify.aws/android/build-a-backend/storage/)
- [Set Up Storage (Android)](https://docs.amplify.aws/android/build-a-backend/storage/set-up-storage/)
- [Upload Files (Android)](https://docs.amplify.aws/android/frontend/storage/upload-files/)
- [Download Files (Android)](https://docs.amplify.aws/android/frontend/storage/download-files/)
- [Storage Overview (Swift)](https://docs.amplify.aws/swift/build-a-backend/storage/)
- [Set Up Storage (Swift)](https://docs.amplify.aws/swift/build-a-backend/storage/set-up-storage/)
- [Upload Files (Swift)](https://docs.amplify.aws/swift/frontend/storage/upload-files/)
- [Download Files (Swift)](https://docs.amplify.aws/swift/frontend/storage/download-files/)
- [Storage Overview (Flutter)](https://docs.amplify.aws/flutter/build-a-backend/storage/)
- [Set Up Storage (Flutter)](https://docs.amplify.aws/flutter/build-a-backend/storage/set-up-storage/)
- [Upload Files (Flutter)](https://docs.amplify.aws/flutter/frontend/storage/upload-files/)
- [Download Files (Flutter)](https://docs.amplify.aws/flutter/frontend/storage/download-files/)
