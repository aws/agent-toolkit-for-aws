# Instrument a .NET Application on Amazon EKS with ADOT

Wire the ADOT .NET auto-instrumentation SDK into a Deployment on Amazon EKS. An init container copies the SDK into the pod at startup, so the application image is not rebuilt and the application source is not touched.

Read [instrumentation.md](instrumentation.md) first — it defines what is out of scope (OTLP endpoints, Application Signals). Deploying a collector is a separate, optional step — [collector-eks.md](collector-eks.md).

## Prerequisites

- An existing EKS cluster and a .NET workload deployed as a `Deployment`
- The Deployment manifest (or the CDK/Terraform that renders it) available to edit
- `kubectl` context pointing at the cluster, for verification

## Critical Requirements

**Do NOT:**

- Install the `amazon-cloudwatch-observability` add-on, or any OpenTelemetry operator — **unless you are also deploying a collector** ([collector-eks.md](collector-eks.md)). Deploying the CloudWatch Agent by Helm necessarily installs its operator, because the agent ships as a custom resource that only the operator reconciles; that is expected there, and is not the add-on
- Add the `instrumentation.opentelemetry.io/inject-dotnet` annotation (it requires an operator)
- Set `OTEL_EXPORTER_OTLP_*` — leave the SDK's default endpoint in place — **unless you are also deploying a collector** ([collector-eks.md](collector-eks.md)), which sets `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_PROTOCOL` deliberately
- Add `CloudWatchAgentServerPolicy` or `AWSXRayDaemonWriteAccess` to the workload, or add Application Signals / ServiceEvents / Dynamic Instrumentation configuration. The IAM half is lifted **when you are also deploying a collector** ([collector-eks.md](collector-eks.md)), which grants `CloudWatchAgentServerPolicy` to the collector's own service account — never to the workload. The Application Signals half always stands
- Run `kubectl apply`, `terraform apply`, `cdk deploy`, `helm install`/`helm upgrade`, `kubectl annotate`, or `kubectl delete` automatically — including the out-of-band IRSA commands in [collector-eks.md](collector-eks.md). Present every mutating command for the user to run; they act on a live cluster
- Modify the application's `.cs` files or its `.csproj`

**On IAM:** instrumentation on its own needs no permissions, so this change adds none. The workload may later need permission to reach wherever telemetry is sent — that belongs with the destination, not this guide. If you deploy a collector instead ([collector-eks.md](collector-eks.md)), the collector is what gets the IAM — the workload still gets none.

## Deployment manifest

.NET needs the most environment variables of any language, because the CoreCLR profiler is loaded by the runtime at process start and reads its configuration entirely from the environment.

**Four of them are what actually attach the profiler** — omit any one and the app starts normally with no instrumentation and no error: `CORECLR_ENABLE_PROFILING`, `CORECLR_PROFILER`, `CORECLR_PROFILER_PATH`, `DOTNET_STARTUP_HOOKS`. `OTEL_DOTNET_AUTO_HOME` and `OTEL_DOTNET_AUTO_PLUGINS` select the ADOT distro's behaviour.

`DOTNET_ADDITIONAL_DEPS` and `DOTNET_SHARED_STORE` are set for parity with the distro's own `instrument.sh`, but the `AdditionalDeps/` and `store/` directories **do not exist in the container image** (they ship only in the tarball). Instrumentation works with both paths dangling, so do not treat them as evidence of a broken install when auditing paths.

```yaml
# k8s-deployment.yaml
spec:
  template:
    spec:
      volumes:
        - name: otel-auto-instrumentation
          emptyDir: {}

      initContainers:
        - name: otel-auto-instrumentation
          # Look up the latest tag — see instrumentation.md
          image: public.ecr.aws/aws-observability/adot-autoinstrumentation-dotnet:v1.15.0
          command: ['cp', '-a', '/autoinstrumentation/.', '/otel-auto-instrumentation-dotnet']
          volumeMounts:
            - name: otel-auto-instrumentation
              mountPath: /otel-auto-instrumentation-dotnet

      containers:
        - name: <my-app>
          # ... existing image, ports, probes unchanged ...
          env:
            # CoreCLR profiler — all four are required for the profiler to attach
            - name: CORECLR_ENABLE_PROFILING
              value: '1'
            - name: CORECLR_PROFILER
              value: '{918728DD-259F-4A6A-AC2B-B85E1B658318}'
            - name: CORECLR_PROFILER_PATH
              value: /otel-auto-instrumentation-dotnet/linux-x64/OpenTelemetry.AutoInstrumentation.Native.so
            - name: DOTNET_STARTUP_HOOKS
              value: /otel-auto-instrumentation-dotnet/net/OpenTelemetry.AutoInstrumentation.StartupHook.dll
            # SDK locations
            - name: DOTNET_ADDITIONAL_DEPS
              value: /otel-auto-instrumentation-dotnet/AdditionalDeps
            - name: DOTNET_SHARED_STORE
              value: /otel-auto-instrumentation-dotnet/store
            - name: OTEL_DOTNET_AUTO_HOME
              value: /otel-auto-instrumentation-dotnet
            - name: OTEL_DOTNET_AUTO_PLUGINS
              value: 'AWS.Distro.OpenTelemetry.AutoInstrumentation.Plugin, AWS.Distro.OpenTelemetry.AutoInstrumentation'
            - name: OTEL_SERVICE_NAME
              value: <my-app>
          volumeMounts:
            - name: otel-auto-instrumentation
              mountPath: /otel-auto-instrumentation-dotnet
```

`CORECLR_PROFILER_PATH` depends on **two** things, and the guide's own checks cannot catch getting it wrong — a bad path means the profiler silently does not attach:

- **Architecture**, from the node: `linux-x64` on x86-64, `linux-arm64` on ARM64/Graviton.
- **libc, from the application's base image** — not the node. `linux-<arch>` for glibc bases

  (`mcr.microsoft.com/dotnet/aspnet:*`, Debian, Ubuntu); **`linux-musl-<arch>` for Alpine bases.**

Do not infer it. List what the image actually shipped and read the app's libc:

```bash
kubectl exec <pod> -c <my-app> -- ls /otel-auto-instrumentation-dotnet/
kubectl exec <pod> -c <my-app> -- sh -c 'head -2 /etc/os-release'
```

The amd64 image contains `linux-x64` **and** `linux-musl-x64`, and no `linux-arm64` — so on amd64 the choice is entirely about libc. ARM64 nodes pull a different image from the manifest list.

Set `OTEL_SERVICE_NAME` from the existing Deployment name or application name. Optionally add `OTEL_RESOURCE_ATTRIBUTES` for attributes such as `deployment.environment=production`.

Preserve the container's existing `env`, `volumeMounts`, probes, and resources — append to them rather than replacing.

## If the manifest is rendered by CDK

When the Deployment is applied through `eks.KubernetesManifest` / `cluster.addManifest`, add the same three pieces to the manifest object:

```typescript
// eks-stack.ts
volumes: [{ name: 'otel-auto-instrumentation', emptyDir: {} }],
initContainers: [{
  name: 'otel-auto-instrumentation',
  image: 'public.ecr.aws/aws-observability/adot-autoinstrumentation-dotnet:v1.15.0',
  command: ['cp', '-a', '/autoinstrumentation/.', '/otel-auto-instrumentation-dotnet'],
  volumeMounts: [{ name: 'otel-auto-instrumentation', mountPath: '/otel-auto-instrumentation-dotnet' }],
}],
containers: [{
  name: 'my-app',
  image: imageUri,
  env: [
    { name: 'CORECLR_ENABLE_PROFILING', value: '1' },
    { name: 'CORECLR_PROFILER', value: '{918728DD-259F-4A6A-AC2B-B85E1B658318}' },
    { name: 'CORECLR_PROFILER_PATH', value: '/otel-auto-instrumentation-dotnet/linux-x64/OpenTelemetry.AutoInstrumentation.Native.so' },
    { name: 'DOTNET_STARTUP_HOOKS', value: '/otel-auto-instrumentation-dotnet/net/OpenTelemetry.AutoInstrumentation.StartupHook.dll' },
    { name: 'DOTNET_ADDITIONAL_DEPS', value: '/otel-auto-instrumentation-dotnet/AdditionalDeps' },
    { name: 'DOTNET_SHARED_STORE', value: '/otel-auto-instrumentation-dotnet/store' },
    { name: 'OTEL_DOTNET_AUTO_HOME', value: '/otel-auto-instrumentation-dotnet' },
    { name: 'OTEL_DOTNET_AUTO_PLUGINS', value: 'AWS.Distro.OpenTelemetry.AutoInstrumentation.Plugin, AWS.Distro.OpenTelemetry.AutoInstrumentation' },
    { name: 'OTEL_SERVICE_NAME', value: 'my-app' },
  ],
  volumeMounts: [{ name: 'otel-auto-instrumentation', mountPath: '/otel-auto-instrumentation-dotnet' }],
}],
```

Terraform users applying a raw manifest file (`kubectl apply -f`, `envsubst`, or `kubernetes_manifest`) edit the YAML directly — no Terraform resource changes are needed for instrumentation.

## Verify

After the user applies the change and pods restart:

```bash
# The init container should be listed on the pod
kubectl get pod -l app=<my-app> -o jsonpath='{.items[0].spec.initContainers[*].name}'

# The init container copied the SDK in
kubectl get pod <pod> -o jsonpath='{.status.initContainerStatuses[*].state.terminated.exitCode}'   # want 0

# The loader variables reached the RUNNING process (not just the pod spec)
kubectl exec <pod> -c <my-app> -- printenv | grep -E '^(CORECLR|DOTNET_|OTEL_)' | sort

# Each path they name actually exists. Quote and wrap in `sh -c` so the variable expands INSIDE the
# pod -- an unwrapped `-- test -f "$CORECLR_PROFILER_PATH"` expands in your local shell, where it is
# unset, so `test -f ""` always exits 1 and reports failure on a healthy pod.
kubectl exec <pod> -c <my-app> -- sh -c \
  'test -f "$CORECLR_PROFILER_PATH" && echo "profiler .so present" || echo "MISSING: $CORECLR_PROFILER_PATH"'

# The SDK's own log -- present at the DEFAULT log level, no OTEL_LOG_LEVEL needed. This is the most
# direct answer to "did the profiler attach and is it exporting", per signal:
kubectl exec <pod> -c <my-app> -- sh -c 'tail -20 /tmp/otel-dotnet-auto-*-Managed-*.log'
#   [Information] The profiler has been initialized with NN direct definitions
#   [Information] Export succeeded for http://<collector>:4318/v1/traces.  Export completed successfully.
# Benign lines to ignore there: AWSEKSDetector DirectoryNotFoundException / "Certificate file does
# not exist" warnings.
```

`DOTNET_ADDITIONAL_DEPS` and `DOTNET_SHARED_STORE` are the exception to the existence check: those
directories are **not shipped in the container image** (only in the tarball), so both paths dangle on
a working deployment. Do not treat them as the fault.

**Do not use the application's own log as the success signal.** ADOT .NET writes nothing to it at the
default level — a working pod logs nothing matching `opentelemetry|otlp|exporter`, and the init
container's log stream is empty because `cp -a` is silent.

The `printenv` check matters more for .NET than for other languages: if any CoreCLR variable is missing or its path is wrong, the profiler does not attach and the application starts normally with no instrumentation and no error. Until a receiver exists at the default OTLP endpoint, exporter connection errors are expected.

## Completion

**Tell the user:**

"I've wired ADOT .NET auto-instrumentation into your EKS Deployment.

**Changes:**

- Added an `emptyDir` volume and an `otel-auto-instrumentation` init container that copies the ADOT .NET SDK into the pod
- Added the CoreCLR profiler variables, the SDK location variables, and `OTEL_SERVICE_NAME` to the application container, plus the shared volume mount

**Not changed:** your application image, your application source and `.csproj`, and cluster-level components — no add-on or operator was installed, and no IAM changes were needed.

**Next steps:**

1. Review the manifest diff — confirm `CORECLR_PROFILER_PATH` matches your node architecture **and the application image's libc**: `linux-x64` or `linux-arm64` for glibc bases, `linux-musl-<arch>` for Alpine. A wrong path means the profiler silently never attaches.
2. Apply it and let the pods roll.
3. **Telemetry has nowhere to go yet.** No OTLP endpoint was configured, so the SDK is using its default (`localhost:4318`). Two ways to fix that: deploy an OTel Collector alongside it and export to that ([collector-eks.md](collector-eks.md)), or point `OTEL_EXPORTER_OTLP_ENDPOINT` at an OTLP endpoint you already have.

Let me know if you'd like adjustments before you apply."
