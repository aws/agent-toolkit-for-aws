# Monitor a vLLM Model Server in CloudWatch Omni (Amazon ECS and Amazon EKS)

Set up a vLLM model server so that Omni's **AI Inference** page shows it, with its engine metrics,
GPU metrics, traces, and engine configuration. This is not ADOT SDK instrumentation. vLLM already
exposes Prometheus metrics and can send its own traces, so the work is a collector that scrapes vLLM
and the NVIDIA DCGM exporter, plus a few settings on the vLLM container. The setup steps and every
file are in [ai-inference-ecs.md](ai-inference-ecs.md) and [ai-inference-eks.md](ai-inference-eks.md);
this file holds what both share.

Tested with vLLM v0.27.0, CloudWatch agent 1.300073.2b1889, OpenTelemetry Collector Contrib 0.160.0, and
dcgm-exporter 4.6.0-4.8.3, on Tesla T4 GPUs (g4dn instances), EKS 1.34 with KServe 0.21 (Standard
and Knative modes), and the ECS-optimized AL2023 GPU AMI. The ECS CloudWatch agent path is also
tested with vLLM v0.19.1 on an A10G (g5.xlarge), in a bridge-mode task with a per-host trace agent.
Host-mode ECS tasks are tested with both collectors.

**Before you start:** confirm a Space exists in the target Region. `list-spaces` is account-global,
so filter to the Region: `aws cloudwatchomni list-spaces --region <region> --query "items[?region=='<region>']"`.
If that filtered list is empty, stop and run `../spaces-and-domains.md` first: telemetry sent before
a Space exists appears to succeed while reaching nothing the customer can see. If the CLI rejects
`cloudwatchomni` as an unknown service, its model is older than Omni; that is not evidence that no
Space exists. Ask the user to confirm the Space and its Region, and go on.

**Propose the changes; the user applies them.** You run the read-only commands (`describe`,
`list`, and `get` calls, and the Verify queries) and the local steps: writing the files, filling the
placeholders, and running `assemble.py` and `merge_taskdef.py`. Every command that creates or changes
something in AWS or in the cluster (IAM roles and policies, Pod Identity associations, add-ons,
`kubectl apply` and `kubectl patch`, task definitions, ECS services, log groups, security groups) is
the user's to run. Present those commands in order, with every value filled in, and say what each one
changes. The user approves the files by applying them, so show each file you wrote, or at least the
settings in it that they should review: what it collects and from where, its processors, the resource
attributes it sets, and every change to their instances and workload. Where the user must wait before the next command, give the command that shows it is done. If the workload is
managed by infrastructure as code (Terraform, CDK, Helm, or manifests in the repository), propose
the same change as edits to those files instead. After the user has applied a step, run its checks.

## When to use this file

- A user wants vLLM engine metrics, GPU metrics, traces, or the engine configuration in Omni.
- An inference service is missing from Omni's **AI Inference** page, or its GPU panels are empty.
- A user asks which collector to use for an inference workload on ECS or EKS.

Not covered: inference engines other than vLLM, Fargate (no GPUs), EC2 without ECS, Ray Serve, and
the CloudWatch agent on EKS (Step 2).

## What Omni needs

Omni builds the AI Inference views from these signals. Every path below produces all of them.

| Signal | Requirement | Used for |
|---|---|---|
| Engine metrics (`vllm:*`) | Resource attributes `service.name`, `aws.service.type=ai_inference`, `service.namespace` (the application) | Listing the service in the workloads table, all engine charts |
| GPU metrics (`DCGM_FI_*`) | The owner of each GPU: ECS `aws.ecs.task.family` (equals `service.name`); EKS `k8s.replicaset.name` + `k8s.namespace.name`, and `k8s.workload.name` | GPU panels, GPU type, GPU efficiency |
| DCGM fields | The device fields and the GPU profiling fields (`DCGM_FI_PROF_*`) | GPU Insights tab |
| Traces (`llm_request` spans) | The same `service.name` and `service.namespace` as the metrics, plus `aws.service.type=ai_inference` | Application map, trace views |
| vLLM startup line (`non-default args:`) | ECS: log group `/ecs/<task family>`, stream prefix `ecs`. EKS: log group `/aws/containerinsights/<clusterName>/application`, stream name containing `.containers.<pod>_<namespace>_`, JSON event with the line in its `log` field | Engine Configuration panel |
| Transaction Search | On in the region | Stores the OTLP traces |

The GPU series carry `service.name=dcgm` (the scrape job). On ECS they also carry `service.namespace`,
and with the CloudWatch agent `aws.service.type` too. That is expected: Omni lists services from the
engine metrics only, so no `dcgm` service appears.

## Rules

1. **Inspect before you propose anything.** Read the cluster, the task definitions or manifests,
   and the current collector first.
2. **The user applies every change.** Treat an unknown account or cluster as production. Propose
   only the permissions this file names: `CloudWatchAgentServerPolicy` is the tested set, broader
   than the OTLP endpoints need, so say so if the user asks for a minimal policy. Never propose
   deleting a resource that the user did not ask to remove.
3. **The setup must never stop, delay, or modify the engine.** Never wrap or replace the vLLM
   entrypoint. Every container that the setup adds to the vLLM task is non-essential, and vLLM waits
   on none of them. An init step that fails exits 0 and sends no data, rather than failing the task.
4. **One DCGM client on each host.** Only one client can hold the DCGM profiling module. A second
   exporter that requests `DCGM_FI_PROF_*` fields fails to start. Find existing exporters first.
5. **One identity on metrics and traces.** Use the same `service.name` and `service.namespace` on
   both. Do not use the old `workload_type` label. Never add a static `model_name` label: it renames
   vLLM's own label to `exported_model_name`.
6. **Prove each step.** After the user applies a step, run its checks, and run Verify at the end.
   Report what you saw, not what you expect.

## Step 1 — Detect the platform and the current state

Collect these facts. Ask the user for anything that you cannot read.

| Fact | ECS | EKS |
|---|---|---|
| Region, account | `aws sts get-caller-identity`, the cluster ARN | same |
| Cluster | `aws ecs list-clusters` | `kubectl config current-context`, `aws eks list-clusters` |
| GPU capacity | `aws ecs list-container-instances` + instance types (EC2, ECS GPU AMI) | `kubectl get nodes -o 'custom-columns=NODE:.metadata.name,GPU:.status.allocatable.nvidia\.com/gpu'` |
| vLLM workload | The task definition with the vLLM container | `kubectl get deploy,statefulset,inferenceservice -A`; a vLLM image or the KServe `kserve-container` |
| Network mode, port | The task's `networkMode` (none set on EC2 means `bridge`) and the vLLM `containerPort`. `awsvpc` and `host` share `localhost` with sidecars; `bridge` does not ([ai-inference-ecs.md](ai-inference-ecs.md) step 6). `host` binds the ports on the instance ([ai-inference-ecs.md](ai-inference-ecs.md) step 8) | — |
| Task size | A task-level `memory` and `cpu`. A task-level `memory` must grow by the sidecars' memory (`merge_taskdef.py` does it) | — |
| Service name | Is the task family stable? A hash or a per-version family is not: choose a stable name ([ai-inference-ecs.md](ai-inference-ecs.md) step 7) | — |
| Existing collector | A collector container in the vLLM task, or a cluster agent `DAEMON` service: `aws ecs list-services --cluster <ecsClusterName> --scheduling-strategy DAEMON` | `aws eks describe-addon --cluster-name <clusterName> --addon-name amazon-cloudwatch-observability`; `helm list -A`; an OpenTelemetry Collector Deployment |
| Credentials | The vLLM task definition's `taskRoleArn`, and whether other workloads share it (for example the account's `ecsTaskExecutionRole` used as the task role). No task role, or a shared one: create one for this task ([ai-inference-ecs.md](ai-inference-ecs.md) step 2) | `aws eks describe-addon --cluster-name <clusterName> --addon-name eks-pod-identity-agent` |
| IMDS from tasks | Instance metadata hop limit 2, and `ECS_AWSVPC_BLOCK_IMDS` not `true`: `config-init` reads the host IP from IMDS | — |
| Trace support in the image | The `vllm/vllm-openai` images include the OpenTelemetry SDK and OTLP exporters. For a custom image, check `opentelemetry-sdk` and `opentelemetry-exporter-otlp`: without them `--otlp-traces-endpoint` stops vLLM at start | same (`kubectl exec <pod> -- pip list`) |
| Existing DCGM exporter | An ECS `DAEMON` service | `kubectl get ds -A \| grep -i dcgm` |
| Transaction Search | `aws xray get-trace-segment-destination` (want `Destination=CloudWatchLogs`, `Status=ACTIVE`). Older AWS CLI builds lack this command: use a current CLI | same |

## Step 2 — Choose the path

| Path | What the setup adds | Choose it when | Watch for |
|---|---|---|---|
| ECS + CloudWatch agent | DCGM `DAEMON` service, `config-init` + CloudWatch agent sidecars in the vLLM task | The user wants the AWS agent | Agent configuration traps ([ai-inference-ecs.md](ai-inference-ecs.md) step 5) |
| ECS + OpenTelemetry Collector | DCGM `DAEMON` service, `config-init` + Collector Contrib sidecars | The user already runs the Collector | The `metric_start_time` processor |
| EKS + OpenTelemetry Collector | A Pod Identity role, a dcgm-exporter DaemonSet, one Collector Deployment | Every EKS cluster | No kube-state-metrics; logs need a log solution |

On ECS, offer the CloudWatch agent and the OpenTelemetry Collector as equal choices, and let the user
pick. If the task already runs a collector, prefer it.

**ECS tasks in `bridge` mode** (on EC2 also tasks with no `networkMode`) need one more part for traces:
a collector on each host at the bridge gateway, owned by whoever runs the cluster ([ai-inference-ecs.md](ai-inference-ecs.md) step 6).

On EKS, the OpenTelemetry Collector is the only path here. Do not use the
`amazon-cloudwatch-observability` add-on or its Helm chart for vLLM: it is outside the Omni
instrumentation path ([instrumentation.md](instrumentation.md), "Do NOT add"), and it does not
discover vLLM or give its metrics `aws.service.type`. If the cluster already runs the add-on with its
DCGM exporter, a second exporter cannot start (Rule 4). Tell the user, and let them choose between
turning off the add-on's DCGM exporter, which removes its Container Insights GPU metrics, and
stopping here.

## Step 3 — Set up the path

Follow [ai-inference-ecs.md](ai-inference-ecs.md) or [ai-inference-eks.md](ai-inference-eks.md). On
EKS with KServe or Knative, also read the next section before you propose the trace change.

Placeholders, used the same way in the files, the commands, and the queries:

| Placeholder | Value |
|---|---|
| `<region>`, `<accountId>` | The AWS Region and account |
| `<ecsClusterName>` / `<clusterName>` | The ECS or EKS cluster name |
| `<taskRoleName>` | ECS: the role in the vLLM task definition's `taskRoleArn`, or the new role for this task ([ai-inference-ecs.md](ai-inference-ecs.md) step 2) |
| `<collectorRoleName>` | EKS with the OpenTelemetry Collector: a new role name for the collector |
| `<CUSTOMER_SERVICE_NAME>` | The service name. ECS: the task definition family. EKS: the KServe InferenceService name, else the owning workload's name |
| `<CUSTOMER_APPLICATION_NAME>` | ECS: the application name |
| `<vllmHost>`, `<vllmPort>` | ECS: where the collector reaches vLLM. `localhost` in `awsvpc` and `host` mode, `vllm` (the container link) in `bridge` mode; the vLLM `containerPort`, often `8000` |
| `<vllmNamespace>` | EKS: the namespace of each vLLM workload, which is also its application. Several namespaces are several applications: use each workload's own namespace in its trace settings |
| `<gpuInstanceTypes>` | EKS: every GPU instance type that the GPU nodes can have, comma-separated ([ai-inference-eks.md](ai-inference-eks.md) step 3) |
| `<instance security group>`, `<task security group>` | ECS: the container instances' group (`aws ec2 describe-instances`) and, for an `awsvpc` task, the vLLM service's group (`aws ecs describe-services`, `networkConfiguration.awsvpcConfiguration.securityGroups`) |
| `<vLLM container name>`, `<ECS service name>` | ECS: the container in the task definition, and the service that runs it (`aws ecs list-services`) |
| `<new revision>` | ECS: the number that `register-task-definition` returns. Have the user check it before the deploy |

Fill them in the readable files before you assemble the templates. Name the files: a wildcard that
matches nothing stops the whole command in zsh. On EKS:

```bash
sed -i -e 's/<region>/us-east-1/g' -e 's/<accountId>/123456789012/g' -e 's/<clusterName>/my-cluster/g' \
  -e 's/<gpuInstanceTypes>/g5.xlarge, g6.xlarge/g' dcgm-exporter.yaml config.yaml
```

On ECS, with the CloudWatch agent in `awsvpc` mode (with the OpenTelemetry Collector, name `otel.yaml`
instead of `cwagent-config.json prometheus.yml`; in `bridge` mode, `vllm` instead of `localhost`; when
you reuse an existing DCGM exporter, leave out `dcgm-exporter-taskdef.json`):

```bash
sed -i -e 's/<region>/us-east-1/g' -e 's/<ecsClusterName>/my-cluster/g' \
  -e 's/<CUSTOMER_SERVICE_NAME>/my-service/g' -e 's/<CUSTOMER_APPLICATION_NAME>/my-app/g' \
  -e 's/<vllmHost>/localhost/g' -e 's/<vllmPort>/8000/g' \
  dcgm-exporter-taskdef.json collector-containers.json cwagent-config.json prometheus.yml
```

Fill the rest (`<collectorRoleName>`, the security groups, the revision) in the commands. Then check
the files you built: `grep -n '<[A-Za-z][A-Za-z_ ]*>' *.ready.*` (and `new-revision.json` on ECS)
should print nothing, except on EKS three comment lines from `config.yaml` with `<vllmNamespace>` and
`<label>`, which do not matter. The templates themselves keep their `<contents of FILE>` slots.

### KServe and Knative (EKS)

The collector finds a KServe predictor by its `kserve-container` and scrapes it on 8080, and Knative's
`queue-proxy` sidecar is not scraped as vLLM. The service name is the InferenceService name, not the
predictor Deployment. Three behaviours of KServe and Knative change how the service looks in Omni:

1. **Scale to zero.** KServe keeps one replica by default. With `minReplicas: 0`, an idle Knative
   predictor scales to zero: the engine sends nothing, its series stop, and the service drops out of
   Omni until traffic wakes it, after a cold start that reloads the model. For a monitored service,
   keep `minReplicas: 1`, or tell the user to expect the gaps.
2. **A change rolls the predictor, and the rollout needs a spare GPU.** Knative starts the new
   revision beside the old one and switches when it is Ready. KServe Standard mode rolls its
   Deployment with a surge. With every GPU in use, the new pod stays `Pending` with
   `Insufficient nvidia.com/gpu`, and the old one keeps serving the old settings. Ask the user to add
   a GPU node for the rollout. In Standard mode you can instead set the strategy below; the service is then down
   while the model reloads. Knative has no such option.

   ```yaml
   spec:
     predictor:
       deploymentStrategy: { type: Recreate }
   ```

   With several workloads and one spare GPU, change them one at a time, and wait for each to finish:
   the old pod's GPU is then free for the next one. Change the InferenceServices before any
   Deployment with a `Recreate` strategy: that restart frees a GPU that a pending predictor would
   take. Give the user a wait command after each change:

   ```bash
   # KServe Standard: done when the old predictor pod is gone.
   kubectl -n <vllmNamespace> wait --for=delete pod/<old predictor pod> --timeout=45m
   # Knative: wait for the new revision, then for the old pod. <revision> is the current revision's
   # number plus 1, as 5 digits: after ...-predictor-00001 comes 00002.
   # --for=create needs kubectl 1.31 or later.
   kubectl -n <vllmNamespace> wait --for=create --for=condition=Ready revision/<InferenceService>-predictor-<revision> --timeout=45m
   kubectl -n <vllmNamespace> wait --for=delete pod/<old predictor pod> --timeout=45m
   # Deployment with Recreate: the old pod goes first, so wait for it, then for the new one.
   kubectl -n <vllmNamespace> wait --for=delete pod/<old vLLM pod> --timeout=10m
   kubectl -n <vllmNamespace> wait --for=condition=Available deploy/<name> --timeout=45m
   ```

   Do not rely on `kubectl rollout status`: the Deployments have a 600-second progress deadline, so
   it reports a failure while a slow image pull is still going. A Knative revision that is not Ready within
   `serving.knative.dev/progress-deadline` (default 600 s) fails. Image pull plus model load can
   take longer on a node that has not pulled the vLLM image yet, so add the annotation, for example
   `1800s`, to the InferenceService's `metadata.annotations` in the same change.
3. **The Knative workload name changes with each revision.** The predictor Deployment is
   `<InferenceService>-predictor-<revision>-deployment`, so `k8s.workload.name` changes when a
   change creates a new revision. Select by `service.name` in queries and alarms; it stays the
   InferenceService name. Pod names are capped at 63 characters, and the revision suffix uses 44 of
   them: an InferenceService name of 19 characters or fewer keeps the pod name whole.

## Step 4 — Optional: send vLLM traces

Traces give the service its application in Omni (without them it shows application "None") and
add the request spans; the service is listed from its engine metrics alone (Step 5). Recommend
them. First check that Transaction Search is on in the Region:
`aws xray get-trace-segment-destination` shows `CloudWatchLogs` and `ACTIVE` when it is. If it is
off, the user turns it on as [collector.md](collector.md) Step 1 describes.
Check the image's trace support (Step 1).

Append the flag to the vLLM container's `args` (EKS) or `command` (ECS; `merge_taskdef.py --traces`
does it). On a KServe InferenceService, put the container lines on `kserve-container`. The change
restarts vLLM. With one GPU for each replica and a `Recreate` strategy, the service is down until the
model reloads, a few minutes, and longer on a node that has not pulled the vLLM image yet: agree a
time with the user. On a KServe InferenceService the change rolls the predictor, which needs a spare
GPU (KServe and Knative, item 2).

| Path | `--otlp-traces-endpoint` | Environment | Also |
|---|---|---|---|
| ECS, both collectors | `http://localhost:4318/v1/traces` (`awsvpc`, `host`); `http://172.17.0.1:4318/v1/traces`, the per-host collector (`bridge`, [ai-inference-ecs.md](ai-inference-ecs.md) step 6) | `OTEL_SERVICE_NAME=<CUSTOMER_SERVICE_NAME>`, `OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf`, `OTEL_RESOURCE_ATTRIBUTES=service.name=<CUSTOMER_SERVICE_NAME>,aws.service.type=ai_inference,service.namespace=<CUSTOMER_APPLICATION_NAME>` | vLLM sends gRPC by default, even to an `http://…:4318` endpoint |
| EKS + OpenTelemetry Collector | `http://otelcol.otel-collector:4318/v1/traces` | `OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf`, `OTEL_RESOURCE_ATTRIBUTES=aws.service.type=ai_inference,service.namespace=<vllmNamespace>` | Do not set `OTEL_SERVICE_NAME`: the collector names the traces like the metrics |

On EKS, a JSON patch appends the lines; the `test` stops it if the container at that index is not
the vLLM container. For a KServe InferenceService, the container is `kserve-container`, and the last
line is the Knative deadline (KServe and Knative, item 2); drop it in Standard mode. An `add` to
`env/-` or to an annotation needs the `env` list and the `annotations` map to exist: add an empty one
first if not.

```bash
kubectl patch inferenceservice <CUSTOMER_SERVICE_NAME> -n <vllmNamespace> --type json -p '[
  {"op":"test","path":"/spec/predictor/containers/0/name","value":"kserve-container"},
  {"op":"add","path":"/spec/predictor/containers/0/args/-","value":"--otlp-traces-endpoint=http://otelcol.otel-collector:4318/v1/traces"},
  {"op":"add","path":"/spec/predictor/containers/0/env/-","value":{"name":"OTEL_EXPORTER_OTLP_TRACES_PROTOCOL","value":"http/protobuf"}},
  {"op":"add","path":"/spec/predictor/containers/0/env/-","value":{"name":"OTEL_RESOURCE_ATTRIBUTES","value":"aws.service.type=ai_inference,service.namespace=<vllmNamespace>"}},
  {"op":"add","path":"/metadata/annotations/serving.knative.dev~1progress-deadline","value":"1800s"}]'
```

For a Deployment, use the pod template's path and the container's name and index:

```bash
kubectl patch deployment <name> -n <vllmNamespace> --type json -p '[
  {"op":"test","path":"/spec/template/spec/containers/0/name","value":"<vLLM container name>"},
  {"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--otlp-traces-endpoint=http://otelcol.otel-collector:4318/v1/traces"},
  {"op":"add","path":"/spec/template/spec/containers/0/env/-","value":{"name":"OTEL_EXPORTER_OTLP_TRACES_PROTOCOL","value":"http/protobuf"}},
  {"op":"add","path":"/spec/template/spec/containers/0/env/-","value":{"name":"OTEL_RESOURCE_ATTRIBUTES","value":"aws.service.type=ai_inference,service.namespace=<vllmNamespace>"}}]'
```

On EKS the service name is the KServe InferenceService name, else the name of the owning workload,
such as the Deployment. Only if you name services with the pod-label rule in `config.yaml`, set
`OTEL_SERVICE_NAME` to the same value; otherwise leave it unset. On Knative, write `service.namespace` as text: Knative rejects
`env[].valueFrom.fieldRef` unless `kubernetes.podspec-fieldref` is enabled. vLLM sends one span for
each request with no sampling; on a busy endpoint, set `OTEL_TRACES_SAMPLER` to limit the cost.

## Step 5 — Verify

Run these PromQL checks in the CloudWatch console (Query Studio, PromQL), or with the query API:
`GET https://monitoring.<region>.amazonaws.com/api/v1/query?query=...`, signed with SigV4 for the
service `monitoring`. Encode spaces as `%20`, not `+`, or the signature does not match (HTTP 403).
Save the script below as `promql.py` and run `python3 promql.py <region> '<query>'`. It needs `boto3`
and `requests`. Without them, use curl (7.75 or later), which signs the same request:

```bash
eval "$(aws configure export-credentials --format env)"
curl -sG "https://monitoring.<region>.amazonaws.com/api/v1/query" --aws-sigv4 "aws:amz:<region>:monitoring" \
  --user "$AWS_ACCESS_KEY_ID:$AWS_SECRET_ACCESS_KEY" -H "x-amz-security-token: $AWS_SESSION_TOKEN" \
  --data-urlencode 'query=<query>'
```

Leave out the `x-amz-security-token` header when `AWS_SESSION_TOKEN` is empty (long-term keys).

```python
import sys, urllib.parse, boto3, requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
region, query = sys.argv[1], sys.argv[2]
url = f"https://monitoring.{region}.amazonaws.com/api/v1/query?" + urllib.parse.urlencode({"query": query}, quote_via=urllib.parse.quote)
req = AWSRequest(method="GET", url=url)
SigV4Auth(boto3.Session().get_credentials().get_frozen_credentials(), "monitoring", region).add_auth(req)
r = requests.get(url, headers=dict(req.headers), timeout=60)
r.raise_for_status()
for s in r.json()["data"]["result"]:
    print(s["metric"], s["value"][1])
```

Select resource attributes with the quoted form, as below. A regex on `__name__` returns HTTP 400.
Wait 5 minutes after a vLLM restart: until then the old pod, revision, or task is still in the
lookback window, so a check shows an extra series, an extra workload, or a GPU with two owners.
To evaluate a query at a past time, add `@ <unix seconds>` after its range or selector, for example
`sum(last_over_time({"vllm:request_success_total","@resource.service.name"="<CUSTOMER_SERVICE_NAME>"}[1m] @ 1700000000))`.

**ECS:**

```promql
count by ("@resource.service.name", "@resource.service.namespace") ({"vllm:num_requests_running","@resource.aws.service.type"="ai_inference","@resource.service.name"="<CUSTOMER_SERVICE_NAME>"})
count by (UUID) ({"DCGM_FI_DEV_GPU_UTIL","@resource.aws.ecs.task.family"="<CUSTOMER_SERVICE_NAME>"})
max by ("@resource.aws.ecs.task.family") ({"DCGM_FI_DEV_FB_USED","@resource.aws.ecs.task.family"="<CUSTOMER_SERVICE_NAME>"})
  and on ("@resource.aws.ecs.task.family")
max by ("@resource.aws.ecs.task.family") ({"vllm:num_requests_running","@resource.service.name"="<CUSTOMER_SERVICE_NAME>"})
count by (UUID) ({"DCGM_FI_PROF_SM_OCCUPANCY","@resource.aws.ecs.task.family"="<CUSTOMER_SERVICE_NAME>"})
count by (UUID) ({"DCGM_FI_PROF_GR_ENGINE_ACTIVE","@resource.aws.ecs.task.family"="<CUSTOMER_SERVICE_NAME>"})
```

Expect: one engine series with your application; exactly the task's own GPUs; one joined series
(its value is the GPU memory in use, in MiB); the two profiling fields for each of those GPUs.

**EKS:**

```promql
count by ("@resource.service.name", "@resource.k8s.workload.name") ({"vllm:num_requests_running","@resource.aws.service.type"="ai_inference","@resource.k8s.cluster.name"="<clusterName>"})
max by ("@resource.k8s.workload.name") ({"DCGM_FI_DEV_FB_USED","@resource.k8s.workload.name"!="","@resource.k8s.cluster.name"="<clusterName>"})
  and on ("@resource.k8s.workload.name")
max by ("@resource.k8s.workload.name") ({"vllm:num_requests_running","@resource.aws.service.type"="ai_inference","@resource.k8s.cluster.name"="<clusterName>"})
count by (UUID) ({"DCGM_FI_PROF_SM_OCCUPANCY","@resource.k8s.cluster.name"="<clusterName>"})
count by (UUID) ({"DCGM_FI_PROF_GR_ENGINE_ACTIVE","@resource.k8s.cluster.name"="<clusterName>"})
```

Expect: one engine series for each service and workload; one joined series for each workload (its
value is the GPU memory in use, in MiB); the two profiling fields for each GPU.

Send the test traffic after the collector runs. Requests that finish before its first scrape
raise the counters' totals but show no `increase()`, and a rate window that starts before the first
scrape reads low.

**Counters and histograms arrive:**
`sum(rate({"vllm:generation_tokens_total","@resource.service.name"="<CUSTOMER_SERVICE_NAME>"}[5m]))`.
Do not apply `rate()` or `increase()` to a native histogram directly: CloudWatch inflates the result
many times over. Take `histogram_count` for each replica first, then `rate`, then `sum`; a sum over
all replicas drops when a replica goes away, and `rate` counts that as a reset. On EKS:
`sum(rate(histogram_count(sum by ("@resource.k8s.pod.name") ({"vllm:e2e_request_latency_seconds","@resource.service.name"="<CUSTOMER_SERVICE_NAME>"}))[5m:30s]))`.
On ECS:
`sum(rate(histogram_count(sum by ("@resource.aws.ecs.task.arn") ({"vllm:e2e_request_latency_seconds","@resource.service.name"="<CUSTOMER_SERVICE_NAME>"}))[5m:30s]))`.
It equals the request rate of `vllm:request_success_total`.

**Traces,** with CloudWatch Logs Insights on the log group `aws/spans`, over the last 15 minutes
(in the console, or `aws logs start-query` with `--start-time` and `--end-time`, then
`aws logs get-query-results`):

```
filter name = "llm_request" and `resource.attributes.service.name` = "<CUSTOMER_SERVICE_NAME>"
| stats count(*) by `resource.attributes.aws.service.type`, `resource.attributes.service.namespace`,
  `resource.attributes.cloud.platform`
```

Expect `ai_inference`, the application, and `cloud.platform=aws_eks` or `aws_ecs`. The deployment
environment is `deployment.environment=eks:<clusterName>/<vllmNamespace>` on EKS, and
`deployment.environment.name=aws_ecs:<ecsClusterName>` on ECS with the CloudWatch agent. On ECS with the
OpenTelemetry Collector the spans carry none, and X-Ray reports `aws.local.environment=ecs:default`. Spans arrive
about 2 to 3 minutes after the request. vLLM also sends startup spans (`Load model`, `Compile graph`, and
others), so count `llm_request` spans only. Over a closed window of several minutes, their count matches,
within a request or so, the change of
`vllm:request_success_total`: subtract its `last_over_time` values at the window's start and end
(`increase()` extrapolates, so it differs by a fraction). Start the window after the trace rollout has
finished, because an old pod that is still serving sends no spans. End it at least 3 minutes ago.

**In Omni,** on the AI Inference page:

- The service is in the workloads table about 5 minutes after its engine metrics arrive, with or
  without traffic or traces.
- The service page shows the GPU type and the GPU charts.
- Engine Configuration shows the vLLM arguments, 2 to 15 minutes after the startup line arrives.

These checks need the console. Without a browser, say so, give the user the times to look, and check
what you can: the startup line in its log group, and the service in the Verify queries.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Service not in AI Inference | No engine metrics with `aws.service.type=ai_inference` | Run the engine-metrics Verify query. Check that the collector scrapes vLLM and sets `aws.service.type` |
| Application is "None" | No traces, or `service.namespace` differs | Send traces. Use the same `service.namespace` on metrics and traces |
| No spans with an HTTP endpoint | vLLM sent gRPC, or the `/v1/traces` path is missing | Set `OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf` and the full path |
| Gauges arrive, counters and histograms do not | No start time on the cumulative points | Add the `metric_start_time` processor (deprecated former name `metricstarttime`) |
| The ECS task does not start: log group does not exist | The new `/ecs/<CUSTOMER_SERVICE_NAME>` group was not created | Create it ([ai-inference-ecs.md](ai-inference-ecs.md) step 4) |
| The new ECS revision never starts: no instance meets the requirements | No free GPU next to the old task | Deploy with `minimumHealthyPercent=0` ([ai-inference-ecs.md](ai-inference-ecs.md) step 5) |
| The EKS DCGM DaemonSet has 0 pods, or fewer than the GPU nodes | `<gpuInstanceTypes>` misses the nodes' instance types | List every GPU instance type ([ai-inference-eks.md](ai-inference-eks.md) step 3) |
| A KServe change never finishes; the new predictor pod is `Pending` with `Insufficient nvidia.com/gpu` | The rollout needs a second GPU beside the running one | If another rollout holds the spare GPU, wait for it. Else add a GPU node, or use `deploymentStrategy: Recreate` in Standard mode (KServe and Knative) |
| A new Knative revision fails before vLLM is Ready | Image pull plus model load took longer than `progress-deadline` | Set `serving.knative.dev/progress-deadline` (KServe and Knative) |
| A Knative service drops out of Omni when it is idle | `minReplicas: 0`: the predictor scaled to zero | Keep `minReplicas: 1` (KServe and Knative) |
| Queries by `k8s.workload.name` stop matching after a change (Knative) | A new revision has a new workload name | Select by `service.name` (KServe and Knative) |
| The ECS agent sidecar never starts: `CannotStartContainerError ... dependency will never start` | `config-init` did not start, for example `HostConfigError: Unable to get execution role credentials for task` after the instance rebooted while the task started (a patch association on a new instance) | Stop the task; the service starts a new one. vLLM is not affected |
| No spans; the ECS task uses `bridge` networking | vLLM sends to `localhost`, which is its own container | Send to the per-host collector at the bridge gateway ([ai-inference-ecs.md](ai-inference-ecs.md) step 6) |
| ECS does not place a `host` task: `RESOURCE:PORTS`, `Port 8000 in use.` | Another task on the instance holds the port | One such task per instance, or give each task its own ports ([ai-inference-ecs.md](ai-inference-ecs.md) step 8) |
| ECS does not place a `host` task: the service event says an instance is missing an attribute required by the task | The instance lacks `com.amazonaws.ecs.capability.task-iam-role-network-host`: the ECS agent sets it only with `ECS_ENABLE_TASK_IAM_ROLE_NETWORK_HOST=true` | Add the setting to `/etc/ecs/ecs.config` ([ai-inference-ecs.md](ai-inference-ecs.md) step 8); the ECS-optimized AMIs set it |
| CloudFormation lint `E1029` on the `config-init` command | Dollar-brace variable forms in the script | Use the `config-init.sh` in [ai-inference-ecs.md](ai-inference-ecs.md), which has none |
| ECS rejects the new revision, or cannot place it, for memory | A task-level `memory` that does not include the sidecars | Raise it by the sidecars' memory (`merge_taskdef.py` does it) |
| Counter totals are right but `increase()` is 0 | All requests finished before the collector's first scrape | Send traffic again after the collector runs |
| Collector pod has no AWS credentials (EKS) | The `eks-pod-identity-agent` add-on is missing | Install it ([ai-inference-eks.md](ai-inference-eks.md) step 2), then restart the collector |
| GPU panels empty (ECS) | The `config-init` log shows `no GPU IDs from DescribeTasks` (missing permission, or no GPU requested) or `no host IP from IMDS` | Fix the task role or the IMDS access. Check `aws.ecs.task.family` on the GPU series |
| GPU panels empty (EKS) | The DCGM series have no `pod` label, or the wrong owner | Run the exporter in Kubernetes mode with the pod-resources mount. Keep the order `groupbyattrs/dcgm` → `transform/dcgm_promote` → `k8sattributes/pod` |
| DCGM exporter exits: `Failed to watch DCGM fields` | Another DCGM client holds the profiling module | Run one exporter on each host |
| CloudWatch agent exits: `environment variable "1" has invalid name` (ECS) | A relabel rule without a `replacement`, or with an empty one (agent 1.300074.0 and later) | Set `replacement: unused` |
| Collector gets no credentials (EKS) | No Pod Identity association, or the node role with hop limit 1 | Associate the role with the collector's service account |
| Service shows as Kubernetes, not EKS | No `cloud.platform=aws_eks` | Keep `resource/cluster` in all three pipelines |
| Knative rejects the InferenceService | `nodeSelector` or `fieldRef` not allowed | Enable `kubernetes.podspec-nodeselector` (and `-fieldref`) in the `config-features` ConfigMap of `knative-serving` |
| Engine Configuration empty | The log group, stream, or event layout is not the one Omni reads; or the pod started before the log solution, or more than 30 days ago | Match the layout in "What Omni needs". The panel fills at the next vLLM restart |
| Duplicate series; sample counts a multiple of the scrape rate | Each pod is scraped by several collectors | One scrape per source: one Collector replica, or a node-local filter on DaemonSet agents |

## Limitations

- **EKS:** no GPUs allocated and idle values, and no pod restarts chart. These need
  kube-state-metrics, which this setup does not run. `host.id` is not set: a cluster-wide
  collector cannot derive it.
- **ECS:** no GPU requested or allocatable values, and no node or reliability panels. These come from
  Kubernetes. A GPU that no task uses sends no metrics, because each task keeps only its own GPUs.
- **Service names:** two clusters with a service of the same name show as one row in Omni.
- **ECS bridge mode:** traces need a per-host collector ([ai-inference-ecs.md](ai-inference-ecs.md) step 6). Not tested with the
  OpenTelemetry Collector sidecar, and Omni's console views were not checked for a family that is not
  the service name (step 7); the Verify queries pass.
- **ECS host mode:** tested with both collectors and one task per instance, on the ECS GPU AMI.
  Per-task ports on a multi-GPU instance are not tested ([ai-inference-ecs.md](ai-inference-ecs.md) step 8).
- **Tested owners:** a Deployment, directly or through KServe (Standard and Knative modes), and ECS
  tasks. A StatefulSet, a LeaderWorkerSet, or a Ray cluster is not tested.

## Report back

Tell the user:

- The path, the files, and the commands that you proposed, in order, and which of them the user
  ran. Name every change to their workload: on ECS the vLLM log configuration, any new task role and
  task memory and, with traces, the vLLM trace argument and environment variables, and the per-host
  collector in `bridge` mode; on EKS the trace argument, the environment
  variables, and the annotations. Say when vLLM restarted and for how long it was down.
- The Verify results, with the query output.
- What is still missing and why: a step the user has not run, a limitation, or a wait time.
