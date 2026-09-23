# Instrument a Java Application on Amazon EKS with ADOT

Wire the ADOT Java auto-instrumentation agent into a Deployment on Amazon EKS. An init container copies the agent jar into the pod at startup, so the application image is not rebuilt and the application source is not touched.

Read [instrumentation.md](instrumentation.md) first — it defines what is out of scope (OTLP endpoints, Application Signals). Deploying a collector is a separate, optional step — [collector-eks.md](collector-eks.md).

## Prerequisites

- An existing EKS cluster and a Java workload deployed as a `Deployment`
- The Deployment manifest (or the CDK/Terraform that renders it) available to edit
- `kubectl` context pointing at the cluster, for verification

## Critical Requirements

**Do NOT:**

- Install the `amazon-cloudwatch-observability` add-on, or any OpenTelemetry operator — **unless you are also deploying a collector** ([collector-eks.md](collector-eks.md)). Deploying the CloudWatch Agent by Helm necessarily installs its operator, because the agent ships as a custom resource that only the operator reconciles; that is expected there, and is not the add-on
- Add the `instrumentation.opentelemetry.io/inject-java` annotation (it requires an operator)
- Set `OTEL_EXPORTER_OTLP_*` — leave the SDK's default endpoint in place — **unless you are also deploying a collector** ([collector-eks.md](collector-eks.md)), which sets `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_PROTOCOL` deliberately
- Add `CloudWatchAgentServerPolicy` or `AWSXRayDaemonWriteAccess` to the workload, or add Application Signals / ServiceEvents / Dynamic Instrumentation configuration. The IAM half is lifted **when you are also deploying a collector** ([collector-eks.md](collector-eks.md)), which grants `CloudWatchAgentServerPolicy` to the collector's own service account — never to the workload. The Application Signals half always stands
- Run `kubectl apply`, `terraform apply`, `cdk deploy`, `helm install`/`helm upgrade`, `kubectl annotate`, or `kubectl delete` automatically — including the out-of-band IRSA commands in [collector-eks.md](collector-eks.md). Present every mutating command for the user to run; they act on a live cluster
- Modify the application's `.java` files or its build configuration

**On IAM:** instrumentation on its own needs no permissions, so this change adds none. The workload may later need permission to reach wherever telemetry is sent — that belongs with the destination, not this guide. If you deploy a collector instead ([collector-eks.md](collector-eks.md)), the collector is what gets the IAM — the workload still gets none.

## Deployment manifest

Add a shared volume, an init container that copies the agent jar into it, and the environment variables plus volume mount on the application container.

Note that the Java init container copies a **single jar**, not a directory tree — the copy command differs from the other languages.

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
          image: public.ecr.aws/aws-observability/adot-autoinstrumentation-java:v2.30.0
          command: ['cp', '-a', '/javaagent.jar', '/otel-auto-instrumentation-java/javaagent.jar']
          volumeMounts:
            - name: otel-auto-instrumentation
              mountPath: /otel-auto-instrumentation-java

      containers:
        - name: <my-app>
          # ... existing image, ports, probes unchanged ...
          env:
            # Note the leading space — JAVA_TOOL_OPTIONS is appended to, not replaced
            - name: JAVA_TOOL_OPTIONS
              value: ' -javaagent:/otel-auto-instrumentation-java/javaagent.jar'
            - name: OTEL_SERVICE_NAME
              value: <my-app>
          volumeMounts:
            - name: otel-auto-instrumentation
              mountPath: /otel-auto-instrumentation-java
```

### If JAVA_TOOL_OPTIONS is already set

If the container already sets `JAVA_TOOL_OPTIONS`, append the `-javaagent` flag to the existing value rather than overwriting it — losing existing JVM flags (heap settings, GC options, other agents) will change how the application runs:

```
<EXISTING_JAVA_TOOL_OPTIONS> -javaagent:/otel-auto-instrumentation-java/javaagent.jar
```

Check the existing container `env` before writing this value.

Set `OTEL_SERVICE_NAME` from the existing Deployment name or application name. Optionally add `OTEL_RESOURCE_ATTRIBUTES` for attributes such as `deployment.environment=production`.

Preserve the container's existing `env`, `volumeMounts`, probes, and resources — append to them rather than replacing.

## If the manifest is rendered by CDK

When the Deployment is applied through `eks.KubernetesManifest` / `cluster.addManifest`, add the same three pieces to the manifest object:

```typescript
// eks-stack.ts
volumes: [{ name: 'otel-auto-instrumentation', emptyDir: {} }],
initContainers: [{
  name: 'otel-auto-instrumentation',
  image: 'public.ecr.aws/aws-observability/adot-autoinstrumentation-java:v2.30.0',
  command: ['cp', '-a', '/javaagent.jar', '/otel-auto-instrumentation-java/javaagent.jar'],
  volumeMounts: [{ name: 'otel-auto-instrumentation', mountPath: '/otel-auto-instrumentation-java' }],
}],
containers: [{
  name: 'my-app',
  image: imageUri,
  env: [
    { name: 'JAVA_TOOL_OPTIONS', value: ' -javaagent:/otel-auto-instrumentation-java/javaagent.jar' },
    { name: 'OTEL_SERVICE_NAME', value: 'my-app' },
  ],
  volumeMounts: [{ name: 'otel-auto-instrumentation', mountPath: '/otel-auto-instrumentation-java' }],
}],
```

Terraform users applying a raw manifest file (`kubectl apply -f`, `envsubst`, or `kubernetes_manifest`) edit the YAML directly — no Terraform resource changes are needed for instrumentation.

## Verify

After the user applies the change and pods restart:

```bash
# The init container should be listed on the pod
kubectl get pod -l app=<my-app> -o jsonpath='{.items[0].spec.initContainers[*].name}'

# The JVM logs the agent being picked up via JAVA_TOOL_OPTIONS on startup
kubectl logs -l app=<my-app> -c <my-app> | grep -iE "javaagent|opentelemetry"
```

The JVM prints a `Picked up JAVA_TOOL_OPTIONS:` line on startup listing the `-javaagent` flag — that confirms the agent attached. Until a receiver exists at the default OTLP endpoint, exporter connection errors are expected.

## Completion

**Tell the user:**

"I've wired the ADOT Java auto-instrumentation agent into your EKS Deployment.

**Changes:**

- Added an `emptyDir` volume and an `otel-auto-instrumentation` init container that copies `javaagent.jar` into the pod
- Added `JAVA_TOOL_OPTIONS` (appended to any existing value) and `OTEL_SERVICE_NAME` to the application container, plus the shared volume mount

**Not changed:** your application image, your application source and build config, and cluster-level components — no add-on or operator was installed, and no IAM changes were needed.

**Next steps:**

1. Review the manifest diff — confirm `JAVA_TOOL_OPTIONS` preserves any JVM flags the container already set.
2. Apply it and let the pods roll. Look for the `Picked up JAVA_TOOL_OPTIONS:` line in the logs.
3. **Telemetry has nowhere to go yet.** No OTLP endpoint was configured, so the agent is using its default (`localhost:4317`, gRPC — the Java agent's default, not 4318). Two ways to fix that: deploy an OTel Collector alongside it and export to that ([collector-eks.md](collector-eks.md)), or point `OTEL_EXPORTER_OTLP_ENDPOINT` at an OTLP endpoint you already have.

Let me know if you'd like adjustments before you apply."
