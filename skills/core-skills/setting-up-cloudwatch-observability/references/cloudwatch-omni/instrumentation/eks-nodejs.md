# Instrument a Node.js Application on Amazon EKS with ADOT

Wire the ADOT Node.js auto-instrumentation SDK into a Deployment on Amazon EKS. The SDK is copied into the pod by an init container at startup, so the application image is not rebuilt and the application source is not touched.

Read [instrumentation.md](instrumentation.md) first — it defines what is out of scope (OTLP endpoints, Application Signals). Deploying a collector is a separate, optional step — [collector-eks.md](collector-eks.md).

## Prerequisites

- An existing EKS cluster and a Node.js workload deployed as a `Deployment`
- The Deployment manifest (or the CDK/Terraform that renders it) available to edit
- `kubectl` context pointing at the cluster, for verification

## Critical Requirements

**Do NOT:**

- Install the `amazon-cloudwatch-observability` add-on, or any OpenTelemetry operator — **unless you are also deploying a collector** ([collector-eks.md](collector-eks.md)). Deploying the CloudWatch Agent by Helm necessarily installs its operator, because the agent ships as a custom resource that only the operator reconciles; that is expected there, and is not the add-on
- Add the `instrumentation.opentelemetry.io/inject-nodejs` annotation (it requires an operator)
- Set `OTEL_EXPORTER_OTLP_*` — leave the SDK's default endpoint in place — **unless you are also deploying a collector** ([collector-eks.md](collector-eks.md)), which sets `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_PROTOCOL` deliberately
- Add `CloudWatchAgentServerPolicy` or `AWSXRayDaemonWriteAccess` to the workload, or add Application Signals / ServiceEvents / Dynamic Instrumentation configuration. The IAM half is lifted **when you are also deploying a collector** ([collector-eks.md](collector-eks.md)), which grants `CloudWatchAgentServerPolicy` to the collector's own service account — never to the workload. The Application Signals half always stands
- Run `kubectl apply`, `terraform apply`, `cdk deploy`, `helm install`/`helm upgrade`, `kubectl annotate`, or `kubectl delete` automatically — including the out-of-band IRSA commands in [collector-eks.md](collector-eks.md). Present every mutating command for the user to run; they act on a live cluster
- Modify `server.js` or any other application source file

**On IAM:** instrumentation on its own needs no permissions, so this change adds none. The workload may later need permission to reach wherever telemetry is sent — but that belongs with the destination, not this guide. If you deploy a collector instead ([collector-eks.md](collector-eks.md)), the collector is what gets the IAM — the workload still gets none. Don't add a policy speculatively here.

## Determine the module format first

The `NODE_OPTIONS` value differs between CommonJS and ESM. Check `package.json`:

- `"type": "module"` → **ESM**
- `"type": "commonjs"` or no `type` field → **CommonJS** (default)

If the project uses `import` syntax in its entrypoint without `"type": "module"`, ask the user rather than guessing.

## Deployment manifest

Add three things to the pod spec: a shared volume, an init container that copies the SDK into it, and the environment variables plus volume mount on the application container.

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
          image: public.ecr.aws/aws-observability/adot-autoinstrumentation-node:v0.12.0
          command: ['cp', '-a', '/autoinstrumentation/.', '/otel-auto-instrumentation-node']
          volumeMounts:
            - name: otel-auto-instrumentation
              mountPath: /otel-auto-instrumentation-node

      containers:
        - name: <my-app>
          # ... existing image, ports, probes unchanged ...
          env:
            # CommonJS. For ESM, see the note below.
            - name: NODE_OPTIONS
              value: '--require /otel-auto-instrumentation-node/autoinstrumentation.js'
            - name: OTEL_SERVICE_NAME
              value: <my-app>
          volumeMounts:
            - name: otel-auto-instrumentation
              mountPath: /otel-auto-instrumentation-node
```

**For ESM applications**, replace the `NODE_OPTIONS` value with:

```
--import /otel-auto-instrumentation-node/autoinstrumentation.js --experimental-loader=/otel-auto-instrumentation-node/node_modules/@opentelemetry/instrumentation/hook.mjs
```

Set `OTEL_SERVICE_NAME` from the existing Deployment name or application name in the manifest. Optionally add `OTEL_RESOURCE_ATTRIBUTES` for attributes such as `deployment.environment=production`.

Preserve the container's existing `env`, `volumeMounts`, probes, and resources — append to them rather than replacing.

## If the manifest is rendered by CDK

When the Deployment is applied through `eks.KubernetesManifest` / `cluster.addManifest`, add the same three pieces to the manifest object:

```typescript
// eks-stack.ts
cluster.addManifest('AppDeployment', {
  apiVersion: 'apps/v1',
  kind: 'Deployment',
  metadata: { name: 'my-app' },
  spec: {
    template: {
      spec: {
        volumes: [{ name: 'otel-auto-instrumentation', emptyDir: {} }],
        initContainers: [{
          name: 'otel-auto-instrumentation',
          image: 'public.ecr.aws/aws-observability/adot-autoinstrumentation-node:v0.12.0',
          command: ['cp', '-a', '/autoinstrumentation/.', '/otel-auto-instrumentation-node'],
          volumeMounts: [{ name: 'otel-auto-instrumentation', mountPath: '/otel-auto-instrumentation-node' }],
        }],
        containers: [{
          name: 'my-app',
          image: imageUri,
          env: [
            { name: 'NODE_OPTIONS', value: '--require /otel-auto-instrumentation-node/autoinstrumentation.js' },
            { name: 'OTEL_SERVICE_NAME', value: 'my-app' },
          ],
          volumeMounts: [{ name: 'otel-auto-instrumentation', mountPath: '/otel-auto-instrumentation-node' }],
        }],
      },
    },
  },
});
```

Terraform users applying a raw manifest file (`kubectl apply -f`, `envsubst`, or the `kubernetes_manifest` resource) edit the YAML directly as shown above — no Terraform resource changes are needed for instrumentation.

## Verify

After the user applies the change and pods restart, confirm the init container ran and the SDK loaded:

```bash
# The init container should be listed on the pod
kubectl get pod -l app=my-app -o jsonpath='{.items[0].spec.initContainers[*].name}'

# Init container completed, and the SDK's own startup line.
# Quote the real string: a bare grep for "opentelemetry" also matches benign warnings that contain
# the word "Failed", and -l across replicas can pull in a terminating pod's stale errors.
kubectl get pod <pod> -o jsonpath='{.status.initContainerStatuses[*].state.terminated.exitCode}'   # want 0
kubectl logs <pod> -c <my-app> --since=5m | grep -F 'automatic instrumentation started successfully'
```

A successfully instrumented Node.js process logs that the ADOT/OpenTelemetry instrumentation started. Until a receiver exists at the default OTLP endpoint, exporter connection errors in the logs are expected — that is the next step, not a failure of instrumentation.

## Completion

**Tell the user:**

"I've wired ADOT Node.js auto-instrumentation into your EKS Deployment.

**Changes:**

- Added an `emptyDir` volume and an `otel-auto-instrumentation` init container that copies the ADOT Node.js SDK into the pod
- Added `NODE_OPTIONS` (module format: CommonJS/ESM) and `OTEL_SERVICE_NAME` to the application container, plus the shared volume mount

**Not changed:** your application image, your application source, and cluster-level components — no add-on or operator was installed, and no IAM changes were needed.

**Next steps:**

1. Review the manifest diff.
2. Apply it and let the pods roll.
3. **Telemetry has nowhere to go yet.** No OTLP endpoint was configured, so the SDK is using its default (`localhost:4318`). Two ways to fix that: deploy an OTel Collector alongside it and export to that ([collector-eks.md](collector-eks.md)), or point `OTEL_EXPORTER_OTLP_ENDPOINT` at an OTLP endpoint you already have.

Let me know if you'd like adjustments before you apply."
