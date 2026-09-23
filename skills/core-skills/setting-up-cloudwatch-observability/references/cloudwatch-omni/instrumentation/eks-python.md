# Instrument a Python Application on Amazon EKS with ADOT

Wire the ADOT Python auto-instrumentation SDK into a Deployment on Amazon EKS. An init container copies the SDK into the pod at startup, so the application image is not rebuilt and the application source is not touched.

Read [instrumentation.md](instrumentation.md) first — it defines what is out of scope (OTLP endpoints, Application Signals). Deploying a collector is a separate, optional step — [collector-eks.md](collector-eks.md).

## Prerequisites

- An existing EKS cluster and a Python workload deployed as a `Deployment`
- The Deployment manifest (or the CDK/Terraform that renders it) available to edit
- `kubectl` context pointing at the cluster, for verification

## Critical Requirements

**Do NOT:**

- Install the `amazon-cloudwatch-observability` add-on, or any OpenTelemetry operator — **unless you are also deploying a collector** ([collector-eks.md](collector-eks.md)). Deploying the CloudWatch Agent by Helm necessarily installs its operator, because the agent ships as a custom resource that only the operator reconciles; that is expected there, and is not the add-on
- Add the `instrumentation.opentelemetry.io/inject-python` annotation (it requires an operator)
- Set `OTEL_EXPORTER_OTLP_*` — leave the SDK's default endpoint in place — **unless you are also deploying a collector** ([collector-eks.md](collector-eks.md)), which sets `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_PROTOCOL` deliberately
- Add `CloudWatchAgentServerPolicy` or `AWSXRayDaemonWriteAccess` to the workload, or add Application Signals / ServiceEvents / Dynamic Instrumentation configuration. The IAM half is lifted **when you are also deploying a collector** ([collector-eks.md](collector-eks.md)), which grants `CloudWatchAgentServerPolicy` to the collector's own service account — never to the workload. The Application Signals half always stands
- Run `kubectl apply`, `terraform apply`, `cdk deploy`, `helm install`/`helm upgrade`, `kubectl annotate`, or `kubectl delete` automatically — including the out-of-band IRSA commands in [collector-eks.md](collector-eks.md). Present every mutating command for the user to run; they act on a live cluster
- Modify the application's `.py` files

**On IAM:** instrumentation on its own needs no permissions, so this change adds none. The workload may later need permission to reach wherever telemetry is sent — that belongs with the destination, not this guide. If you deploy a collector instead ([collector-eks.md](collector-eks.md)), the collector is what gets the IAM — the workload still gets none.

## Deployment manifest

Add a shared volume, an init container that copies the SDK into it, and the environment variables plus volume mount on the application container.

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
          image: public.ecr.aws/aws-observability/adot-autoinstrumentation-python:v0.19.0
          command: ['cp', '-a', '/autoinstrumentation/.', '/otel-auto-instrumentation-python']
          volumeMounts:
            - name: otel-auto-instrumentation
              mountPath: /otel-auto-instrumentation-python

      containers:
        - name: <my-app>
          # ... existing image, ports, probes unchanged ...
          env:
            - name: PYTHONPATH
              value: '/otel-auto-instrumentation-python/opentelemetry/instrumentation/auto_instrumentation:/otel-auto-instrumentation-python'
            - name: OTEL_SERVICE_NAME
              value: <my-app>
          volumeMounts:
            - name: otel-auto-instrumentation
              mountPath: /otel-auto-instrumentation-python
```

### PYTHONPATH must be prepended, not replaced

If the container **already sets** `PYTHONPATH`, keep its existing value in the middle so the instrumentation paths are prepended rather than overwriting it:

```
/otel-auto-instrumentation-python/opentelemetry/instrumentation/auto_instrumentation:<EXISTING_PYTHONPATH>:/otel-auto-instrumentation-python
```

If the container does not set `PYTHONPATH` today, use the two-segment form shown in the manifest above. Check the existing container `env` before writing this value — silently dropping an existing `PYTHONPATH` will break the application's imports.

Set `OTEL_SERVICE_NAME` from the existing Deployment name or application name. Optionally add `OTEL_RESOURCE_ATTRIBUTES` for attributes such as `deployment.environment=production`.

Preserve the container's existing `env`, `volumeMounts`, probes, and resources — append to them rather than replacing.

## If the manifest is rendered by CDK

When the Deployment is applied through `eks.KubernetesManifest` / `cluster.addManifest`, add the same three pieces to the manifest object:

```typescript
// eks-stack.ts
volumes: [{ name: 'otel-auto-instrumentation', emptyDir: {} }],
initContainers: [{
  name: 'otel-auto-instrumentation',
  image: 'public.ecr.aws/aws-observability/adot-autoinstrumentation-python:v0.19.0',
  command: ['cp', '-a', '/autoinstrumentation/.', '/otel-auto-instrumentation-python'],
  volumeMounts: [{ name: 'otel-auto-instrumentation', mountPath: '/otel-auto-instrumentation-python' }],
}],
containers: [{
  name: 'my-app',
  image: imageUri,
  env: [
    { name: 'PYTHONPATH', value: '/otel-auto-instrumentation-python/opentelemetry/instrumentation/auto_instrumentation:/otel-auto-instrumentation-python' },
    { name: 'OTEL_SERVICE_NAME', value: 'my-app' },
  ],
  volumeMounts: [{ name: 'otel-auto-instrumentation', mountPath: '/otel-auto-instrumentation-python' }],
}],
```

Terraform users applying a raw manifest file (`kubectl apply -f`, `envsubst`, or `kubernetes_manifest`) edit the YAML directly — no Terraform resource changes are needed for instrumentation.

## Note on pre-fork servers

Gunicorn with its default sync workers and no `--preload` needs no special handling — instrumentation loads and produces both server spans and nested client spans normally.

The configurations that more often need attention are `--preload` and async worker classes (gevent, eventlet). If the workload uses one of those and no telemetry appears, the usual remedy is a Gunicorn `post_fork` hook that re-initializes the SDK — flag that to the user rather than changing the server configuration silently.

## Verify

After the user applies the change and pods restart:

```bash
# The init container should be listed on the pod
kubectl get pod -l app=<my-app> -o jsonpath='{.items[0].spec.initContainers[*].name}'

# Init container completed, and the SDK's own startup line.
# NOTE: ADOT Python does NOT print the word "opentelemetry" -- grepping for it returns nothing on a
# working pod. The real line is "configurator already loaded".
kubectl get pod <pod> -o jsonpath='{.status.initContainerStatuses[*].state.terminated.exitCode}'   # want 0
kubectl logs <pod> -c <my-app> --since=5m | grep -iE 'aws_configurator|configurator already loaded'
```

Until a receiver exists at the default OTLP endpoint, exporter connection errors are expected — that is the next step, not a failure of instrumentation.

## Completion

**Tell the user:**

"I've wired ADOT Python auto-instrumentation into your EKS Deployment.

**Changes:**

- Added an `emptyDir` volume and an `otel-auto-instrumentation` init container that copies the ADOT Python SDK into the pod
- Added `PYTHONPATH` (prepended to any existing value) and `OTEL_SERVICE_NAME` to the application container, plus the shared volume mount

**Not changed:** your application image, your application source, and cluster-level components — no add-on or operator was installed, and no IAM changes were needed.

**Next steps:**

1. Review the manifest diff — confirm the `PYTHONPATH` value preserves any path the container already relied on.
2. Apply it and let the pods roll.
3. **Telemetry has nowhere to go yet.** No OTLP endpoint was configured, so the SDK is using its default (`localhost:4318`). Two ways to fix that: deploy an OTel Collector alongside it and export to that ([collector-eks.md](collector-eks.md)), or point `OTEL_EXPORTER_OTLP_ENDPOINT` at an OTLP endpoint you already have.

Let me know if you'd like adjustments before you apply."
