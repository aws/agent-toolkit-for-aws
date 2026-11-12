# Connect the AWS CLI and SDKs

Examples use port 9297; replace it in every value (and in the file name) with the emulator's
port. Do not change the user's interactive shell. When the user asks to connect, write the
variables below to `~/.aws/emulator/9297.env` and run each command in a subshell that reads it,
so nothing carries over into later commands:

```bash
( . ~/.aws/emulator/9297.env && aws sts get-caller-identity )
```

Verify with `aws sts get-caller-identity` this way before reporting back. In a test script, read
the file at the top of the script. If the user wants their own shell set up, give them
`source ~/.aws/emulator/9297.env`; to get back, they open a new shell (or unset the emulator
variables, and their profile restores their own credentials).

## Environment variables

Contents of `~/.aws/emulator/9297.env`:

```bash
export AWS_ENDPOINT_URL=https://127.0.0.1:9297
export AWS_SHARED_CREDENTIALS_FILE=$HOME/.aws/emulator/9297/emulator_credentials
export AWS_CONFIG_FILE=$HOME/.aws/emulator/9297/config
export AWS_EC2_METADATA_DISABLED=true   # never fall back to EC2 instance credentials
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1

# Environment credentials win over the credentials file: real keys would be sent and rejected.
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_PROFILE AWS_DEFAULT_PROFILE \
  AWS_WEB_IDENTITY_TOKEN_FILE AWS_ROLE_ARN AWS_ROLE_SESSION_NAME AWS_CONTAINER_CREDENTIALS_RELATIVE_URI \
  AWS_CONTAINER_CREDENTIALS_FULL_URI AWS_CONTAINER_AUTHORIZATION_TOKEN

# Emulator in Docker (always on macOS and Windows): config's ca_bundle is a container path.
export AWS_CA_BUNDLE=$HOME/.aws/emulator/9297/ca.pem

export AWS_PAGER=""                      # optional: CLI output inline instead of through a pager
```

Give the `AWS_CA_BUNDLE` line every time, as "needed when it runs in Docker", unless you have
seen how the running emulator was started (its host process or its container); an installed
package does not show that the running emulator is the package. Setting it for a native emulator
is harmless.

Windows PowerShell, in a child `powershell -Command` or the script that runs the tests (not the
user's session): `$env:AWS_ENDPOINT_URL = "https://127.0.0.1:9297"` and so on, with paths under
`$env:USERPROFILE\.aws\emulator\9297\`; remove the credential variables with
`Remove-Item Env:AWS_ACCESS_KEY_ID, Env:AWS_SECRET_ACCESS_KEY, Env:AWS_SESSION_TOKEN, Env:AWS_PROFILE, Env:AWS_DEFAULT_PROFILE, Env:AWS_WEB_IDENTITY_TOKEN_FILE, Env:AWS_ROLE_ARN, Env:AWS_ROLE_SESSION_NAME, Env:AWS_CONTAINER_CREDENTIALS_RELATIVE_URI, Env:AWS_CONTAINER_CREDENTIALS_FULL_URI, Env:AWS_CONTAINER_AUTHORIZATION_TOKEN -ErrorAction SilentlyContinue`.

Then the code run this way needs no endpoint or credentials, e.g. `boto3.client("s3").list_buckets()`.

- **Regions.** The emulator accepts any Region but does not keep resources separate by Region,
  so requests in different Regions see each other's resources. Use one Region (`us-east-1`) per
  emulator; to test several Regions, run one emulator per Region on its own port.
- Setting `AWS_CONFIG_FILE` replaces the user's own config for those commands (retry, S3 settings).
  Do not edit the emulator's `config`; it is rewritten every start. Copy it, add settings to the
  copy and point `AWS_CONFIG_FILE` at the copy (again after a port change).
- With `-a off` (local tests only, reachable only on `127.0.0.1`; in Docker: port published on
  `127.0.0.1`) there is no `emulator_credentials`: in the env file, replace the
  `AWS_SHARED_CREDENTIALS_FILE` line with `export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test`
  (any key pair works) and keep the rest; the config still supplies endpoint and CA.

## Check you reach the emulator

```bash
( . ~/.aws/emulator/9297.env && aws sts get-caller-identity )
```

Expected: `Account` `000000000000`, `Arn` `arn:aws:iam::000000000000:user/emulator`. Any other
account means the requests go to real AWS: stop, make no further calls, and re-check the
variables above. Readiness alone:
`curl --cacert ~/.aws/emulator/9297/ca.pem https://127.0.0.1:9297/__admin/health` returns `ok`.

## Trusting the certificate

The emulator serves HTTPS with a certificate that is new every start; settings that point at the
path of `ca.pem` keep working, copies or imports must be redone after each start. Never disable
TLS verification (`verify=False`, `--no-verify-ssl`, `NODE_TLS_REJECT_UNAUTHORIZED=0`).

| Client | Extra setting |
|---|---|
| AWS CLI v2, Python (boto3), Go v2 | none: read `ca_bundle` from `config` (Docker: `AWS_CA_BUNDLE`) |
| JavaScript v3 (Node.js) | `NODE_EXTRA_CA_CERTS=$HOME/.aws/emulator/9297/ca.pem` |
| Rust, .NET | `SSL_CERT_FILE=$HOME/.aws/emulator/9297/ca.pem` |
| Java 2.x | a trust store containing `ca.pem` (below) |

Java:

```bash
rm -f ~/emulator-truststore.p12
keytool -importcert -noprompt -alias aws-emulator -file ~/.aws/emulator/9297/ca.pem \
  -keystore ~/emulator-truststore.p12 -storetype PKCS12 -storepass changeit
( . ~/.aws/emulator/9297.env && JAVA_TOOL_OPTIONS="-Djavax.net.ssl.trustStore=$HOME/emulator-truststore.p12 -Djavax.net.ssl.trustStorePassword=changeit -Djavax.net.ssl.trustStoreType=PKCS12" <test command> )
```

Set `JAVA_TOOL_OPTIONS` only on the command that runs the tests; never export it. It replaces the
JVM's default trust store, so use it only for emulator test runs, and rebuild the trust store
after every start. With Maven or Gradle, `JAVA_TOOL_OPTIONS` also reaches the build tool, whose
dependency downloads then fail TLS: pass the three `-D` options to the test JVM only instead
(`mvn test -DargLine="<the three -D options>"` for Surefire, Gradle `test { jvmArgs(...) }`). On Windows some SDKs need `ca.pem` imported into the Windows certificate store.

## Credentials

By default every request must be SigV4-signed with this run's keys (or keys created in the
emulator through IAM `CreateAccessKey` or STS). Keys stop working when the emulator stops and do
not work on another port. Rejections are HTTP 403: `AccessDenied` ("Sign the request with the
emulator credentials": unsigned or foreign keys) or `SignatureDoesNotMatch` (right key ID, wrong
secret or body). See [references/troubleshooting.md](references/troubleshooting.md).

## DynamoDB tables right after CreateTable

If a call right after `CreateTable` fails because the table is still `CREATING`, poll
`DescribeTable` until `TableStatus` is `ACTIVE`, as on AWS.
