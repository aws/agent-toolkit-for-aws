# Data — Mobile

> **Backend required:** Data must be defined in `amplify/data/resource.ts`
> using `defineData` — see [data-backend.md](data-backend.md).

## Flutter

Import `package:amplify_flutter/amplify_flutter.dart`. All operations go through `Amplify.API`.

**Queries:** `Amplify.API.query(request: ModelQueries.list(Todo.classType))` — response in `.response.data?.items`.
Same pattern for `.get()`.

**Mutations:** `Amplify.API.mutate(request: ModelMutations.create(todo))` — same shape for `.update()`, `.delete()`.
Build updated models with `todo.copyWith(done: true)`.

**Subscriptions:** `Amplify.API.subscribe(ModelSubscriptions.onCreate(Todo.classType))` → returns a stream. Listen with `.listen()`, cancel with `sub.cancel()`.

## Swift (Apple platforms)

> Supported: iOS 13+, macOS 12+, tvOS 13+, watchOS 9+, visionOS 1+ (preview).

Uses `Amplify.API.query/mutate` with async/await.
Swift uses `ModelQueries`, `ModelMutations`, and `ModelSubscriptions` (plural, like Flutter).

**Queries:** `try await Amplify.API.query(request: .list(Todo.self))` — result is `.success(let todos)`.

**Mutations:** `try await Amplify.API.mutate(request: .create(newTodo))` — same for `.update()`, `.delete()`.
Modify models directly: `updated.done = true`.

**Subscriptions:** `Amplify.API.subscribe(request: .subscription(of: Todo.self, type: .onCreate))` → use `for try await event in subscription`. Cancel via `task.cancel()` when the view disappears.

## Android (Kotlin)

Android supports both callback-based and coroutine-based APIs.
Coroutine example (recommended):

**Queries:**

```kotlin
suspend fun getTodo(id: String) {
    try {
        val response = Amplify.API.query(ModelQuery.get(Todo::class.java, id))
        Log.i("MyAmplifyApp", response.data.name)
    } catch (error: ApiException) {
        Log.e("MyAmplifyApp", "Query failed", error)
    }
}
```

**Mutations:**

```kotlin
val todo = Todo.builder()
    .name("My todo")
    .build()
try {
    val response = Amplify.API.mutate(ModelMutation.create(todo))
    Log.i("MyAmplifyApp", "Todo with id: ${response.data.id}")
} catch (error: ApiException) {
    Log.e("MyAmplifyApp", "Create failed", error)
}
```

Same pattern for `.update()` and `.delete()`.
Build models via `Todo.builder().name("text").build()`; update via `todo.copyOfBuilder().done(true).build()`.

**Subscriptions (coroutine — uses Kotlin Flow):**

```kotlin
val job = scope.launch {
    try {
        Amplify.API.subscribe(ModelSubscription.onCreate(Todo::class.java))
            .catch { Log.e("MyAmplifyApp", "Error on subscription", it) }
            .collect { Log.i("MyAmplifyApp", "Todo created: ${it.data.name}") }
    } catch (error: ApiException) {
        Log.e("MyAmplifyApp", "Subscription not established", error)
    }
}
// When done:
job.cancel()
```

**Callback alternative:** all operations also accept `onSuccess`/`onError` lambdas — e.g.
`Amplify.API.query(ModelQuery.list(Todo::class.java), { response -> ... }, { error -> ... })`.

## Pitfalls

- **Missing codegen for native platforms:** Flutter, Swift, and Android
  **MUST** run `npx ampx generate graphql-client-code` to produce typed model
  classes. Without this step, model types do not exist. You **SHOULD** use
  typed model classes for compile-time safety.
- **GraphQL vs REST confusion:** All data operations use the GraphQL API
  (`Amplify.API.query`/`mutate`), not REST. Using REST methods for model
  CRUD returns errors.
- **Subscription cleanup:** Every platform **MUST** perform explicit
  subscription cleanup (`.cancel()` on Swift tasks, `job.cancel()` for
  Kotlin coroutines, `subscription.cancel()` for callbacks, or
  `sub.cancel()` for Flutter). Missing cleanup causes connection leaks and
  stale data.
- **Offline sync (Flutter/Swift/Android):** DataStore is a separate API
  from direct API operations. Do not mix `DataStore.query()` with
  `Amplify.API.query()` in the same model workflow.

## Links

- [Data Overview (Android)](https://docs.amplify.aws/android/build-a-backend/data/)
- [Set Up Data (Android)](https://docs.amplify.aws/android/build-a-backend/data/set-up-data/)
- [Connect to Existing Data Sources (Android)](https://docs.amplify.aws/android/build-a-backend/data/connect-to-existing-data-sources/)
- [Data Client (Android)](https://docs.amplify.aws/android/frontend/data/)
- [Data Overview (Swift)](https://docs.amplify.aws/swift/build-a-backend/data/)
- [Set Up Data (Swift)](https://docs.amplify.aws/swift/build-a-backend/data/set-up-data/)
- [Connect to Existing Data Sources (Swift)](https://docs.amplify.aws/swift/build-a-backend/data/connect-to-existing-data-sources/)
- [Data Client (Swift)](https://docs.amplify.aws/swift/frontend/data/)
- [Data Overview (Flutter)](https://docs.amplify.aws/flutter/build-a-backend/data/)
- [Set Up Data (Flutter)](https://docs.amplify.aws/flutter/build-a-backend/data/set-up-data/)
- [Connect to Existing Data Sources (Flutter)](https://docs.amplify.aws/flutter/build-a-backend/data/connect-to-existing-data-sources/)
- [Data Client (Flutter)](https://docs.amplify.aws/flutter/frontend/data/)
