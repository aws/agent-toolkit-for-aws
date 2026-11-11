# Run AWS Emulator embedded in Rust tests

Rust tests can run the emulator in-process, with no package, container, endpoint URL or
certificate: each emulator has its own state, so tests run in parallel. It needs a Rust toolchain
with Cargo, a C compiler and the AWS SDK for Rust. The crate comes from GitHub, not crates.io.
Pin it to the commit of the latest release, not to the tag (a tag can move). Get the latest
release tag with `gh release view -R aws/aws-emulator --json tagName -q .tagName` (without a
working `gh`: `git ls-remote --tags --refs --sort=-v:refname https://github.com/aws/aws-emulator | sed 's,.*refs/tags/,,' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -1` (release tags only, `vX.Y.Z` without a suffix; if it prints nothing, stop and ask the user for the tag)) and use
it exactly as printed (e.g. `v1.0.131`) as `<tag>`. Find its commit with
`git ls-remote https://github.com/aws/aws-emulator 'refs/tags/<tag>^{}'` (if that prints
nothing, use `refs/tags/<tag>`), and put that commit in `rev`. If neither prints a commit, stop
and tell the user the release tag is not in aws/aws-emulator.

```toml
[dependencies]
aws-config = "1"
aws-sdk-s3 = "1"   # the AWS SDK for Rust crates the code uses; add only the ones missing

[dev-dependencies]
# release <tag>
aws-emulator-embedded = { git = "https://github.com/aws/aws-emulator", rev = "<commit sha>" }
tokio = { version = "1", features = ["macros", "rt-multi-thread"] }
```

Before adding `aws-emulator-embedded`, tell the user that you are adding a git dependency whose build scripts (and its
dependencies' build scripts) run on their machine at build time.

Always use the latest release, as in SKILL.md: to upgrade, resolve the new latest release tag the
same way and replace `rev` (and the comment).

```rust
use aws_emulator_embedded::{AwsEmulatorEmbedded, EmbeddedOptions};
// for the options below: use aws_emulator_embedded::{Authentication, Telemetry};

#[tokio::test]
async fn put_then_get() {
    let emulator = AwsEmulatorEmbedded::new(EmbeddedOptions::default());
    let config = aws_config::defaults(aws_config::BehaviorVersion::latest())
        .http_client(emulator.http_client())
        .region(aws_config::Region::new("us-east-1"))
        .credentials_provider(emulator.aws_credentials_provider())
        .load()
        .await;
    let s3 = aws_sdk_s3::Client::new(&config);
    // ...
}
```

Set the Region and the credentials provider as shown; without them the SDK looks in the
environment and the test fails if it finds nothing. All clients built from one emulator share its
state. Authentication is off by default and no credentials file is written; to check signatures
use `EmbeddedOptions::default().authentication(Authentication::On)`. Telemetry is on by default
(`.telemetry(Telemetry::Off)` to turn it off).
