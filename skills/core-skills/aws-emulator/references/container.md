# Run AWS Emulator in a container (Docker on macOS, Windows, CI and agent sandboxes)

On macOS and Windows this is **the** way to run AWS Emulator: it runs natively only on Linux. On
Linux it is an alternative to the package ([references/linux-package.md](references/linux-package.md)). No prebuilt image is published;
build one from the Linux package.

When the user asks to set it up, do it: build the image, start the container, run the health
check and `aws sts get-caller-identity`, then tell them what you ran, the env file to use
([references/connect.md](references/connect.md)), and that telemetry is on and how to turn it off.

## Contents

1. [Build the image](#build-the-image)
2. [Run it](#run-it)
3. [Connect from the host](#connect-from-the-host)
4. [Stop and remove](#stop-and-remove)
5. [CI jobs and parallel agents](#ci-jobs-and-parallel-agents)

## Build the image

In an empty directory, write this `Dockerfile`. It picks the package for the build platform
(`TARGETARCH`, the host's CPU unless `--platform` says otherwise).

```dockerfile
FROM public.ecr.aws/amazonlinux/amazonlinux:2023-minimal
ARG TARGETARCH
RUN case "$TARGETARCH" in arm64) a=aarch64 ;; amd64) a=x86_64 ;; *) exit 1 ;; esac \
    && curl -fsSLo /tmp/aws-emulator.rpm \
       "https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS/latest/aws-emulator-$a.rpm" \
    && rpm -i /tmp/aws-emulator.rpm && rm /tmp/aws-emulator.rpm \
    && mkdir -p /home/emulator && chown 1000 /home/emulator
USER 1000
ENV HOME=/home/emulator
ENV PATH=/opt/aws-emulator/bin:$PATH
EXPOSE 9297
ENTRYPOINT ["aws-emulator", "-b", "0.0.0.0"]
```

```bash
docker build -t aws-emulator .
```

Always use the `latest` package; do not pin a version. To upgrade, stop the container and rebuild
without the cache so the latest package is downloaded again:
`docker build --pull --no-cache -t aws-emulator .`, then run it again (state starts empty). If the user has a downloaded `.rpm` instead, `COPY`
it to `/tmp/aws-emulator.rpm` in place of the `curl`.

## Run it

```bash
mkdir -p ~/.aws/emulator/9297      # first: otherwise Docker creates it owned by root and SDKs cannot read it
docker network create aws-emulator 2>/dev/null || true
docker run -d --rm --name aws-emulator \
  --network aws-emulator \
  --cap-drop ALL --security-opt no-new-privileges --read-only \
  -p 127.0.0.1:9297:9297 \
  -v "$HOME/.aws/emulator/9297:/home/emulator/.aws/emulator/9297" \
  aws-emulator
```

- `-b 0.0.0.0` (in the `ENTRYPOINT`) lets Docker forward the port. Publish it on the host's
  loopback only: `-p 127.0.0.1:9297:9297`, **never** `-p 9297:9297`, which opens the emulator to
  the whole network.
- Its own network keeps other containers on Docker's default network away from it; the other
  flags give the container minimal rights, and the mount is its only writable path.
- The `-v` mount gives the host this run's `config`, `emulator_credentials` and `ca.pem` in
  `~/.aws/emulator/<port>/`. Nothing else is kept between runs, including the telemetry ID; the
  start log's warning that telemetry state cannot be stored is expected.
- **Same port on both sides.** The emulator writes its port into its files, so a different host
  port does not match. For another port, set it on both sides, mount that port's folder and pass
  `-p` to the emulator after the image name: `mkdir -p ~/.aws/emulator/9300`, then
  `-p 127.0.0.1:9300:9300 -v "$HOME/.aws/emulator/9300:/home/emulator/.aws/emulator/9300" ... aws-emulator -p 9300`.
- On a Linux host, add `--user "$(id -u):$(id -g)"` so the files belong to the user.
- Telemetry off: `-e EMULATOR_TELEMETRY=off` (use it by default in CI jobs and agent sandboxes). Other options go after the image name
  (`-a off` for local tests only, with the port published on `127.0.0.1`; `--idle-timeout 900`).
- Windows PowerShell: `New-Item -ItemType Directory -Force "$env:USERPROFILE\.aws\emulator\9297"`, and
  mount `"$env:USERPROFILE\.aws\emulator\9297:/home/emulator/.aws/emulator/9297"`.

Wait for it (the container needs a few seconds):

```bash
for i in $(seq 30); do
  curl -sf --cacert ~/.aws/emulator/9297/ca.pem https://127.0.0.1:9297/__admin/health && break
  sleep 1
done
```

## Connect from the host

Use the env file in [references/connect.md](references/connect.md), and keep its `AWS_CA_BUNDLE` line: the `ca_bundle` in the
generated `config` is a container path (`/home/emulator/.aws/emulator/9297/ca.pem`) that does not
exist on the host.

```bash
export AWS_CA_BUNDLE=$HOME/.aws/emulator/9297/ca.pem
```

SDKs that ignore `AWS_CA_BUNDLE` get the same host path through their own setting
([references/connect.md](references/connect.md), "Trusting the certificate").

## Stop and remove

`docker stop aws-emulator` (Docker sends `SIGTERM`; the emulator stops cleanly, deletes its files
and drops all state; `--rm` removes the container). `docker image rm aws-emulator` removes the
image.

## CI jobs and parallel agents

- Give each job or agent its own port (same number on both sides of `-p`) and its own container
  name (`--name aws-emulator-<port>`, and stop that name), so each gets its own
  `~/.aws/emulator/<port>/` folder (mount only that folder) and state. With the Linux package, `-p 0` and read the port
  from the startup log.
- Start it with telemetry off: `-e EMULATOR_TELEMETRY=off` in Docker, `-t off` with the package.
- Add `--idle-timeout <seconds>` so a job or agent that forgets to stop it does not leak a
  process.
- Wait on `GET /__admin/health` (with `--cacert` on that run's `ca.pem`) before the first test,
  not a fixed `sleep`.
- Set the connect variables in the same script that runs the tests, and keep no real AWS
  credentials in the job's environment: without `AWS_ENDPOINT_URL` the code calls real AWS.
- Each run starts empty; create the resources the tests need in the job.
- Build from the `latest` package in CI (rebuild with `--no-cache` so it is current); do not pin a version.
- Never commit or cache the per-run `config`, `emulator_credentials` or `ca.pem`.
- For a sandbox with no network, run the clients in the same container and start the emulator
  with `-t off`.
