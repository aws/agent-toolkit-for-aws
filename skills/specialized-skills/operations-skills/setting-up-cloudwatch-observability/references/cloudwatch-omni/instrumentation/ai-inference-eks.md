# vLLM AI inference on Amazon EKS (OpenTelemetry Collector)

The EKS steps and files of [ai-inference.md](ai-inference.md). Read that file first: it holds the
rules, the placeholders, KServe and Knative, the trace settings, and Verify. Write the files under
[Files](#files) into one working directory with the names shown, fill the placeholders, and build
the templates with `assemble.py`. In the blocks below, the lines marked `# you` are local or
read-only, and you run them. Present the rest to the user, in order, with every value filled in:
each one creates or changes something in AWS or in the cluster.

The collector is upstream OpenTelemetry Collector Contrib, one Deployment for the cluster. Do not
use the `amazon-cloudwatch-observability` add-on or its chart for this: see
[ai-inference.md](ai-inference.md) Step 2.

## Setup

1. **GPU nodes.** The EKS-optimized NVIDIA AMI. The NVIDIA device plugin reports `nvidia.com/gpu` on
   each GPU node.
2. **Permissions.** A role for EKS Pod Identity with `CloudWatchAgentServerPolicy`:

   ```bash
   aws iam create-role --role-name <collectorRoleName> \
     --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
       "Principal":{"Service":"pods.eks.amazonaws.com"},"Action":["sts:AssumeRole","sts:TagSession"]}]}'
   aws iam attach-role-policy --role-name <collectorRoleName> \
     --policy-arn arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy
   aws eks create-pod-identity-association --cluster-name <clusterName> \
     --namespace otel-collector --service-account otelcol \
     --role-arn arn:aws:iam::<accountId>:role/<collectorRoleName>
   ```

   The cluster needs the `eks-pod-identity-agent` add-on. If the cluster does not have it, install it
   before the collector starts:

   ```bash
   aws eks create-addon --cluster-name <clusterName> --addon-name eks-pod-identity-agent
   aws eks wait addon-active --cluster-name <clusterName> --addon-name eks-pod-identity-agent
   kubectl -n kube-system get ds eks-pod-identity-agent   # you: DESIRED equals the number of nodes
   ```

   With the node role instead of Pod Identity, use a node group whose instance metadata hop limit
   is 2.
3. **DCGM exporter.** Files: `dcgm-counters.csv` and the template `dcgm-exporter.yaml` ([Files](#files)).
   It creates the `otel-collector` namespace, so apply it first:

   ```bash
   python3 assemble.py dcgm-exporter.yaml > dcgm-exporter.ready.yaml   # you
   kubectl apply -f dcgm-exporter.ready.yaml
   kubectl -n otel-collector rollout status ds/dcgm-exporter --timeout=10m
   ```

   The exporter runs only on the nodes whose `node.kubernetes.io/instance-type` is in
   `<gpuInstanceTypes>`. EKS nodes have no `nvidia.com/gpu` label by default. List every GPU type
   that the node groups or node pools allow, not only the types running now: a node group with
   several instance types launches whichever one has capacity. For a managed node group:

   ```bash
   aws eks describe-nodegroup --cluster-name <clusterName> --nodegroup-name <name> --query nodegroup.instanceTypes
   ```

   Check that the DaemonSet's DESIRED count equals the number of GPU nodes: an exporter that matches
   no node schedules no pod and reports no error. Then check that a GPU that a pod uses carries
   `pod`, `namespace`, and `container`. The image has no shell, so read it through the API server:

   ```bash
   for p in $(kubectl -n otel-collector get pods -l app=dcgm-exporter -o name); do
     kubectl get --raw "/api/v1/namespaces/otel-collector/pods/${p#pod/}:9400/proxy/metrics" \
       | grep -m1 '^DCGM_FI_DEV_GPU_UTIL'
   done
   ```

4. **vLLM.** No change for its metrics. The collector finds vLLM by KServe's `kserve-container`, or
   by a container image whose name contains `vllm`. It scrapes the declared port, else 8080 under
   KServe and 8000 otherwise.
5. **Collector.** Files: `config.yaml` and the template `otel-collector.yaml` ([Files](#files)):

   ```bash
   python3 assemble.py otel-collector.yaml > otel-collector.ready.yaml   # you
   kubectl apply -f otel-collector.ready.yaml
   kubectl -n otel-collector rollout status deploy/otelcol --timeout=5m
   ```

   Keep these parts of `config.yaml`. Each one fixes a measured failure:
   - `metric_start_time` in both metrics pipelines: without it CloudWatch drops counters and
     histograms.
   - `groupbyattrs/dcgm` before `k8sattributes/pod`: without it every GPU gets the exporter's pod.
   - `transform/dcgm_promote` deletes the scrape's `k8s.*` owner keys before it sets the owner from
     the exporter's labels: without it GPUs carry the exporter's container, pod UID, and DaemonSet,
     and an unused GPU is attributed to the exporter.
   - `transform/workload` sets `k8s.workload.name` and `k8s.workload.type`.
   - `resource/cluster` sets `cloud.provider`, `cloud.platform=aws_eks`, `cloud.account.id`,
     `cloud.region`, and `cloud.resource_id` as literals. The `eks` and `ec2` detectors either need
     the API or stamp the collector's own node. Without `cloud.platform` the service shows as
     generic Kubernetes.
   - One replica, and no node filter on the scrapes. More replicas scrape each pod more than once.
   Expected, harmless collector log lines: deprecation notes for the `otlphttp` and `k8sattributes`
   names, OTTL notes that "paths were modified to include their context prefix", and
   one `Partial success response ... "Invalid OTel metric type" ... "dropped_data_points": 0` at a new
   target's first scrape, and `Failed to scrape Prometheus endpoint ... connection refused` while a
   vLLM pod loads its model or shuts down.
   To name the service from a pod label of the customer's, uncomment the pod-label rule in the vLLM
   scrape job.
6. **Optional: container logs,** for the Engine Configuration panel. This collector sends no logs.
   Use any log solution that writes the layout in "What Omni needs" ([ai-inference.md](ai-inference.md)),
   and keep the logs at least 30 days. Do this before the trace change ([ai-inference.md](ai-inference.md)
   Step 4): that change restarts vLLM, and the restart then also writes the startup line. AWS for
   Fluent Bit with the Container Insights configuration writes the layout. It ships the logs of every
   namespace, plus node logs to `/dataplane` and `/host`. It uses the collector's role through Pod
   Identity. Download the pinned manifests yourself and read them before you propose them: check the
   image (`aws-for-fluent-bit:3.0.1`, which supports Pod Identity), the service account `fluent-bit`,
   and that the DaemonSet has no tolerations.

   ```bash
   aws eks create-pod-identity-association --cluster-name <clusterName> \
     --namespace amazon-cloudwatch --service-account fluent-bit \
     --role-arn arn:aws:iam::<accountId>:role/<collectorRoleName>
   curl -fsSLO https://raw.githubusercontent.com/aws-samples/amazon-cloudwatch-container-insights/269ca5348185dd333ecedf7a93ab02e82cd04d2b/k8s-deployment-manifest-templates/deployment-mode/daemonset/container-insights-monitoring/cloudwatch-namespace.yaml   # you
   curl -fsSLO https://raw.githubusercontent.com/aws-samples/amazon-cloudwatch-container-insights/269ca5348185dd333ecedf7a93ab02e82cd04d2b/k8s-deployment-manifest-templates/deployment-mode/daemonset/container-insights-monitoring/fluent-bit/fluent-bit.yaml   # you
   kubectl apply -f cloudwatch-namespace.yaml
   kubectl create configmap fluent-bit-cluster-info -n amazon-cloudwatch \
     --from-literal=cluster.name=<clusterName> --from-literal=logs.region=<region> \
     --from-literal=http.server=On --from-literal=http.port=2020 \
     --from-literal=read.head=Off --from-literal=read.tail=On --dry-run=client -o yaml | kubectl apply -f -
   kubectl apply -f fluent-bit.yaml
   ```

   The Fluent Bit DaemonSet has no tolerations. If the GPU nodes have a taint
   (`kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints[*].key`), Fluent
   Bit does not run beside vLLM, and the panel stays empty with no error. Let it run there:

   ```bash
   kubectl -n amazon-cloudwatch patch ds fluent-bit --type merge \
     -p '{"spec":{"template":{"spec":{"tolerations":[{"operator":"Exists"}]}}}}'
   ```

   Check that a Fluent Bit pod runs on every node with a vLLM pod
   (`kubectl -n amazon-cloudwatch get pods -o wide`); a pod that cannot schedule elsewhere does not
   matter. Fluent Bit creates its log groups with no retention, within a minute or two. When
   `aws logs describe-log-groups --log-group-name-prefix /aws/containerinsights/<clusterName>/` lists
   all three, set one:

   ```bash
   for g in application dataplane host; do
     aws logs put-retention-policy --log-group-name /aws/containerinsights/<clusterName>/$g --retention-in-days 30
   done
   ```

   vLLM writes its startup arguments one time, when it starts. With `read.head=Off`, Fluent Bit reads
   only new output. If vLLM already runs, the panel stays empty until the vLLM pods next restart
   (`kubectl rollout restart deployment/<name> -n <vllmNamespace>`, at a time the user agrees).

## Files

The templates (`dcgm-exporter.yaml` and `otel-collector.yaml`) contain `<contents of FILE>`
placeholders: build them with `assemble.py`, the same tool as in
[ai-inference-ecs.md](ai-inference-ecs.md).

`assemble.py`

```python
#!/usr/bin/env python3
"""Fill the "<contents of FILE>" placeholders of a template with the files next to it.

JSON templates: a string value "<contents of FILE>" becomes the file's text, JSON-escaped
(without its final newline).
YAML templates: a line "<contents of FILE>" becomes the file's lines, at that line's indent.
Usage: python3 assemble.py TEMPLATE > READY
"""
import json, os, re, sys

tpl_path = sys.argv[1]
here = os.path.dirname(os.path.abspath(tpl_path))
text = open(tpl_path).read()
read = lambda name: open(os.path.join(here, name)).read()

if tpl_path.endswith(".json"):
    def fill(v):
        if isinstance(v, str):
            m = re.fullmatch(r"<contents of ([^>]+)>", v)
            return read(m.group(1)).rstrip("\n") if m else v
        if isinstance(v, list):
            return [fill(x) for x in v]
        if isinstance(v, dict):
            return {k: fill(x) for k, x in v.items()}
        return v
    print(json.dumps(fill(json.loads(text)), indent=2))
else:
    def block(m):
        indent, name = m.group(1), m.group(2)
        return "\n".join(indent + line if line else "" for line in read(name).rstrip("\n").split("\n"))
    sys.stdout.write(re.sub(r"^([ \t]*)<contents of ([^>]+)>[ \t]*$", block, text, flags=re.M))
```

`dcgm-counters.csv`

```csv
DCGM_FI_DEV_SM_CLOCK, gauge, SM clock frequency (in MHz).
DCGM_FI_DEV_MEM_CLOCK, gauge, Memory clock frequency (in MHz).
DCGM_FI_DEV_MEMORY_TEMP, gauge, Memory temperature (in C).
DCGM_FI_DEV_GPU_TEMP, gauge, GPU temperature (in C).
DCGM_FI_DEV_POWER_USAGE, gauge, Power draw (in W).
DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION, counter, Total energy consumption since boot (in mJ).
DCGM_FI_DEV_PCIE_REPLAY_COUNTER, counter, Total number of PCIe retries.
DCGM_FI_DEV_GPU_UTIL, gauge, GPU utilization (in %).
DCGM_FI_DEV_MEM_COPY_UTIL, gauge, Memory utilization (in %).
DCGM_FI_DEV_ENC_UTIL, gauge, Encoder utilization (in %).
DCGM_FI_DEV_DEC_UTIL, gauge, Decoder utilization (in %).
DCGM_FI_DEV_XID_ERRORS, gauge, Value of the last XID error encountered.
DCGM_FI_DEV_CLOCKS_EVENT_REASONS, gauge, Bitmask of why the clocks are throttled.
DCGM_FI_DEV_FB_FREE, gauge, Framebuffer memory free (in MiB).
DCGM_FI_DEV_FB_USED, gauge, Framebuffer memory used (in MiB).
DCGM_FI_DEV_FB_RESERVED, gauge, Framebuffer memory reserved (in MiB).
DCGM_FI_DEV_NVLINK_BANDWIDTH_TOTAL, gauge, Total number of NVLink bandwidth counters for all lanes.
DCGM_FI_DEV_VGPU_LICENSE_STATUS, gauge, vGPU License status
DCGM_FI_DEV_UNCORRECTABLE_REMAPPED_ROWS, counter, Number of remapped rows for uncorrectable errors
DCGM_FI_DEV_CORRECTABLE_REMAPPED_ROWS, counter, Number of remapped rows for correctable errors
DCGM_FI_DEV_ROW_REMAP_FAILURE, gauge, Whether remapping of rows has failed
DCGM_FI_DRIVER_VERSION, label, Driver Version
DCGM_FI_PROF_GR_ENGINE_ACTIVE, gauge, Ratio of time the graphics engine is active.
DCGM_FI_PROF_SM_ACTIVE, gauge, Ratio of cycles an SM has at least one warp assigned.
DCGM_FI_PROF_SM_OCCUPANCY, gauge, Ratio of resident warps on an SM to the maximum.
DCGM_FI_PROF_PIPE_TENSOR_ACTIVE, gauge, Ratio of cycles the tensor (HMMA) pipe is active.
DCGM_FI_PROF_DRAM_ACTIVE, gauge, Ratio of cycles the device memory interface is active.
DCGM_FI_PROF_PCIE_TX_BYTES, counter, Bytes of active PCIe tx data including both header and payload.
DCGM_FI_PROF_PCIE_RX_BYTES, counter, Bytes of active PCIe rx data including both header and payload.
```

`dcgm-exporter.yaml`

```yaml
apiVersion: v1
kind: Namespace
metadata: { name: otel-collector }
---
apiVersion: v1
kind: ConfigMap
metadata: { name: dcgm-counters, namespace: otel-collector }
data:
  dcgm-counters.csv: |
    <contents of dcgm-counters.csv>
---
apiVersion: apps/v1
kind: DaemonSet
metadata: { name: dcgm-exporter, namespace: otel-collector }
spec:
  selector: { matchLabels: { app: dcgm-exporter } }
  template:
    metadata: { labels: { app: dcgm-exporter } }
    spec:
      affinity:   # only the GPU nodes (Setup step 3)
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - { key: node.kubernetes.io/instance-type, operator: In, values: [<gpuInstanceTypes>] }
      tolerations: [{ operator: Exists }]
      containers:
        - name: dcgm-exporter
          image: nvcr.io/nvidia/k8s/dcgm-exporter:4.6.0-4.8.3-distroless
          args: [-f, /etc/dcgm-exporter/custom/dcgm-counters.csv]
          env:
            - { name: DCGM_EXPORTER_KUBERNETES, value: "true" }
            - { name: DCGM_EXPORTER_LISTEN, value: ":9400" }
            # Every GPU on the node, without requesting one (a request would take it from vLLM).
            - { name: NVIDIA_VISIBLE_DEVICES, value: "all" }
          ports: [{ containerPort: 9400, name: metrics }]
          securityContext:
            capabilities: { add: ["SYS_ADMIN"] }
          volumeMounts:
            - { name: pod-gpu-resources, mountPath: /var/lib/kubelet/pod-resources, readOnly: true }
            - { name: counters, mountPath: /etc/dcgm-exporter/custom, readOnly: true }
      volumes:
        - name: pod-gpu-resources
          hostPath: { path: /var/lib/kubelet/pod-resources }
        - name: counters
          configMap: { name: dcgm-counters }
```

`config.yaml`

```yaml
receivers:
  otlp:
    protocols:
      http: { endpoint: 0.0.0.0:4318 }

  prometheus/vllm:
    config:
      scrape_configs:
        - job_name: vllm
          scrape_interval: 15s
          # Every namespace. To scope it, use
          #   [{ role: pod, namespaces: { names: [<vllmNamespace>] } }]
          kubernetes_sd_configs: [{ role: pod }]
          relabel_configs:
            # KServe's model container, or any container running a vLLM image.
            - source_labels: [__meta_kubernetes_pod_label_serving_kserve_io_inferenceservice, __meta_kubernetes_pod_container_name, __meta_kubernetes_pod_container_image]
              separator: ";"
              regex: '.+;kserve-container;.*|(?i)[^;]*;[^;]*;.*vllm.*'
              action: keep
            - source_labels: [__meta_kubernetes_pod_container_init]
              regex: "true"
              action: drop
            - source_labels: [__meta_kubernetes_pod_phase]
              regex: Running
              action: keep
            # A declared container port is used as-is. A container declaring none gets the server's
            # default: 8080 for KServe, else vllm serve's 8000.
            - source_labels: [__meta_kubernetes_pod_container_port_number, __meta_kubernetes_pod_label_serving_kserve_io_inferenceservice]
              separator: ";"
              regex: ";.+"
              target_label: __tmp_port
              replacement: "8080"
            - source_labels: [__meta_kubernetes_pod_container_port_number, __meta_kubernetes_pod_label_serving_kserve_io_inferenceservice]
              separator: ";"
              regex: ";"
              target_label: __tmp_port
              replacement: "8000"
            - source_labels: [__meta_kubernetes_pod_ip, __tmp_port]
              separator: ":"
              regex: "(.+:[0-9]+)"
              target_label: __address__
            - source_labels: [__meta_kubernetes_pod_label_serving_kserve_io_inferenceservice]
              target_label: inferenceservice
            - source_labels: [__meta_kubernetes_pod_name]
              target_label: pod
            - source_labels: [__meta_kubernetes_namespace]
              target_label: namespace
            # `job` becomes the service.name resource attribute. Later rules overwrite earlier ones,
            # so the most specific name wins: pod, its controller, the Deployment behind a
            # ReplicaSet, the InferenceService, then your own pod label (the optional rule below).
            - source_labels: [__meta_kubernetes_pod_name]
              target_label: job
            - source_labels: [__meta_kubernetes_pod_controller_name]
              regex: (.+)
              target_label: job
            - source_labels: [__meta_kubernetes_pod_controller_kind, __meta_kubernetes_pod_label_pod_template_hash, __meta_kubernetes_pod_controller_name]
              regex: ReplicaSet;.+;(.+)-[^-]+
              target_label: job
            - source_labels: [__meta_kubernetes_pod_label_serving_kserve_io_inferenceservice]
              regex: (.+)
              target_label: job
            # Optional, highest precedence: name the service from a pod label of yours. Replace
            # <label> with the label key, with every character that is not a letter, digit or _
            # written as _ (for example app.kubernetes.io/name -> app_kubernetes_io_name). If vLLM
            # sends traces, set its OTEL_SERVICE_NAME to the same name.
            # - source_labels: [__meta_kubernetes_pod_label_<label>]
            #   regex: (.+)
            #   target_label: job
            # Temporary label, moved to the aws.service.type resource attribute by
            # transform/vllm_resource. A pod can override it with its own aws.service.type label.
            - target_label: aws_service_type
              replacement: ai_inference
            - source_labels: [__meta_kubernetes_pod_label_aws_service_type]
              regex: (.+)
              target_label: aws_service_type

  prometheus/dcgm:
    config:
      scrape_configs:
        - job_name: dcgm
          scrape_interval: 30s
          kubernetes_sd_configs: [{ role: pod }]
          relabel_configs:
            - source_labels: [__meta_kubernetes_namespace]
              regex: otel-collector
              action: keep
            - source_labels: [__meta_kubernetes_pod_label_app]
              regex: dcgm-exporter
              action: keep
            - source_labels: [__meta_kubernetes_pod_container_port_number]
              regex: "9400"
              action: keep

processors:
  # CloudWatch rejects cumulative datapoints with no start time, which is every counter
  # scraped from a Prometheus endpoint. Without this, gauges arrive and counters are dropped.
  # The registered type (otelcol-contrib components); metricstarttime is its deprecated former name.
  metric_start_time:
    strategy: subtract_initial_point

  # Keep only the engine's own series. `_created` is client_python's per-metric creation
  # timestamp, a constant repeated every scrape; Summaries (http_request_size_bytes,
  # http_response_size_bytes) are rejected by the CloudWatch OTLP endpoint.
  filter/vllm_keep:
    error_mode: ignore
    metrics:
      metric:
        - 'not IsMatch(name, "^(vllm:|http_).*")'
        - 'IsMatch(name, ".*_created$")'
        - 'type == METRIC_DATA_TYPE_SUMMARY'

  # One scrape target is one resource, so pod/namespace can be promoted to resource attributes
  # (which k8sattributes/pod then resolves to deployment and node). Also moves the temporary
  # aws_service_type label to the resource.
  transform/vllm_resource:
    error_mode: ignore
    metric_statements:
      - context: datapoint
        statements:
          - set(resource.attributes["k8s.pod.name"], attributes["pod"]) where attributes["pod"] != nil
          - set(resource.attributes["k8s.namespace.name"], attributes["namespace"]) where attributes["namespace"] != nil
          - set(resource.attributes["service.namespace"], attributes["namespace"]) where attributes["namespace"] != nil
          - set(resource.attributes["inferenceservice"], attributes["inferenceservice"]) where attributes["inferenceservice"] != nil
          - set(resource.attributes["aws.service.type"], attributes["aws_service_type"]) where attributes["aws_service_type"] != nil
          - delete_key(attributes, "aws_service_type")

  # GPU->pod varies per DATAPOINT, so split datapoints into one resource per pod first.
  # k8sattributes on its own resolves the dcgm-exporter's own pod instead of the workload.
  groupbyattrs/dcgm:
    keys: [pod, namespace, container]

  # The scrape gives every GPU the exporter's own k8s.* attributes. Drop them all, then
  # take the owner from the exporter's pod/namespace/container labels. An unclaimed GPU has
  # none, so it keeps no owner; it keeps k8s.node.name.
  transform/dcgm_promote:
    error_mode: ignore
    metric_statements:
      - context: resource
        statements:
          - delete_matching_keys(attributes, "^k8s[.](pod|container|namespace|deployment|replicaset|statefulset|daemonset|job|cronjob|workload)[.]")
          - set(attributes["k8s.pod.name"], attributes["pod"]) where attributes["pod"] != nil
          - set(attributes["k8s.namespace.name"], attributes["namespace"]) where attributes["namespace"] != nil
          - set(attributes["k8s.container.name"], attributes["container"]) where attributes["container"] != nil

  k8sattributes/pod:
    auth_type: serviceAccount
    passthrough: false
    pod_association:
      - sources:
          - { from: resource_attribute, name: k8s.pod.name }
          - { from: resource_attribute, name: k8s.namespace.name }
    extract:
      metadata: [k8s.namespace.name, k8s.pod.name, k8s.pod.uid, k8s.container.name, k8s.deployment.name,
                 k8s.replicaset.name, k8s.statefulset.name, k8s.daemonset.name, k8s.job.name, k8s.node.name]
      labels:
        - { tag_name: host.type, key: node.kubernetes.io/instance-type, from: node }
        - { tag_name: cloud.availability_zone, key: topology.kubernetes.io/zone, from: node }

  # The owning workload, as k8s.workload.name / k8s.workload.type: the
  # Deployment, else the StatefulSet, DaemonSet or Job. Never the ReplicaSet.
  transform/workload:
    error_mode: ignore
    metric_statements:
      - context: resource
        statements:
          - set(attributes["k8s.workload.type"], "Job") where attributes["k8s.job.name"] != nil
          - set(attributes["k8s.workload.name"], attributes["k8s.job.name"]) where attributes["k8s.job.name"] != nil
          - set(attributes["k8s.workload.type"], "DaemonSet") where attributes["k8s.daemonset.name"] != nil
          - set(attributes["k8s.workload.name"], attributes["k8s.daemonset.name"]) where attributes["k8s.daemonset.name"] != nil
          - set(attributes["k8s.workload.type"], "StatefulSet") where attributes["k8s.statefulset.name"] != nil
          - set(attributes["k8s.workload.name"], attributes["k8s.statefulset.name"]) where attributes["k8s.statefulset.name"] != nil
          - set(attributes["k8s.workload.type"], "Deployment") where attributes["k8s.deployment.name"] != nil
          - set(attributes["k8s.workload.name"], attributes["k8s.deployment.name"]) where attributes["k8s.deployment.name"] != nil
    trace_statements:
      - context: resource
        statements:
          - set(attributes["k8s.workload.type"], "Job") where attributes["k8s.job.name"] != nil
          - set(attributes["k8s.workload.name"], attributes["k8s.job.name"]) where attributes["k8s.job.name"] != nil
          - set(attributes["k8s.workload.type"], "DaemonSet") where attributes["k8s.daemonset.name"] != nil
          - set(attributes["k8s.workload.name"], attributes["k8s.daemonset.name"]) where attributes["k8s.daemonset.name"] != nil
          - set(attributes["k8s.workload.type"], "StatefulSet") where attributes["k8s.statefulset.name"] != nil
          - set(attributes["k8s.workload.name"], attributes["k8s.statefulset.name"]) where attributes["k8s.statefulset.name"] != nil
          - set(attributes["k8s.workload.type"], "Deployment") where attributes["k8s.deployment.name"] != nil
          - set(attributes["k8s.workload.name"], attributes["k8s.deployment.name"]) where attributes["k8s.deployment.name"] != nil

  # k8sattributes writes RESOURCE attributes, and CloudWatch's OTLP ingest exposes those only as
  # `@resource.*` — which needs quoted-label syntax to select and which most dashboards cannot
  # express. Copy the useful ones back down to datapoint level so the series carry plain labels.
  transform/dcgm_labels:
    error_mode: ignore
    metric_statements:
      - context: datapoint
        statements:
          - set(attributes["pod"],        resource.attributes["k8s.pod.name"])        where resource.attributes["k8s.pod.name"] != nil
          - set(attributes["namespace"],  resource.attributes["k8s.namespace.name"])  where resource.attributes["k8s.namespace.name"] != nil
          - set(attributes["deployment"], resource.attributes["k8s.deployment.name"]) where resource.attributes["k8s.deployment.name"] != nil
          - set(attributes["node"],       resource.attributes["k8s.node.name"])       where resource.attributes["k8s.node.name"] != nil

  # Cluster-level identity. These are the same for every pod in the cluster, so they are literals:
  # the ec2/eks resource detectors would either need the Kubernetes API or would stamp the
  # COLLECTOR's own node onto every engine's metrics. The per-pod node name comes from
  # k8sattributes instead. Without cloud.platform the backend reports the service as generic
  # Kubernetes rather than EKS.
  resource/cluster:
    attributes:
      - { key: k8s.cluster.name, value: <clusterName>, action: upsert }
      - { key: cloud.provider, value: aws, action: upsert }
      - { key: cloud.platform, value: aws_eks, action: upsert }
      - { key: cloud.account.id, value: "<accountId>", action: upsert }
      - { key: cloud.region, value: <region>, action: upsert }
      - { key: cloud.resource_id, value: arn:aws:eks:<region>:<accountId>:cluster/<clusterName>, action: upsert }

  # Spans arrive with nothing Kubernetes-shaped on them. Resolve the sending pod from the
  # connection's source IP, which only works if nothing NATs or proxies between vLLM and here.
  k8sattributes/traces:
    auth_type: serviceAccount
    passthrough: false
    pod_association:
      - sources: [{ from: connection }]
    extract:
      metadata: [k8s.namespace.name, k8s.pod.name, k8s.pod.uid, k8s.node.name, k8s.deployment.name,
                 k8s.statefulset.name, k8s.daemonset.name, k8s.replicaset.name, k8s.job.name, k8s.cronjob.name]
      labels:
        - { tag_name: inferenceservice, key: serving.kserve.io/inferenceservice, from: pod }
        - { tag_name: revision, key: serving.knative.dev/revision, from: pod }
        - { tag_name: host.type, key: node.kubernetes.io/instance-type, from: node }
        - { tag_name: cloud.availability_zone, key: topology.kubernetes.io/zone, from: node }

  # Without OTEL_SERVICE_NAME the engine reports "unknown_service", which would collapse every
  # vLLM pod onto one service. Fall back to the InferenceService, then the workload, then the pod.
  transform/traces:
    error_mode: ignore
    trace_statements:
      - context: resource
        statements:
          - set(resource.attributes["k8s.cluster.name"], "<clusterName>")
          - set(resource.attributes["service.name"], resource.attributes["inferenceservice"]) where resource.attributes["inferenceservice"] != nil and (resource.attributes["service.name"] == nil or IsMatch(resource.attributes["service.name"], "^unknown_service"))
          - set(resource.attributes["service.name"], resource.attributes["k8s.deployment.name"]) where resource.attributes["k8s.deployment.name"] != nil and (resource.attributes["service.name"] == nil or IsMatch(resource.attributes["service.name"], "^unknown_service"))
          - set(resource.attributes["service.name"], resource.attributes["k8s.statefulset.name"]) where resource.attributes["k8s.statefulset.name"] != nil and (resource.attributes["service.name"] == nil or IsMatch(resource.attributes["service.name"], "^unknown_service"))
          - set(resource.attributes["service.name"], resource.attributes["k8s.daemonset.name"]) where resource.attributes["k8s.daemonset.name"] != nil and (resource.attributes["service.name"] == nil or IsMatch(resource.attributes["service.name"], "^unknown_service"))
          - set(resource.attributes["service.name"], resource.attributes["k8s.job.name"]) where resource.attributes["k8s.job.name"] != nil and (resource.attributes["service.name"] == nil or IsMatch(resource.attributes["service.name"], "^unknown_service"))
          - set(resource.attributes["service.name"], resource.attributes["k8s.replicaset.name"]) where resource.attributes["k8s.replicaset.name"] != nil and (resource.attributes["service.name"] == nil or IsMatch(resource.attributes["service.name"], "^unknown_service"))
          - set(resource.attributes["service.name"], resource.attributes["k8s.pod.name"]) where resource.attributes["k8s.pod.name"] != nil and (resource.attributes["service.name"] == nil or IsMatch(resource.attributes["service.name"], "^unknown_service"))
          # Without this the backend derives the entity as "eks:default", detaching the service
          # from its cluster.
          - set(resource.attributes["deployment.environment"], Concat(["eks:", resource.attributes["k8s.cluster.name"], "/", resource.attributes["k8s.namespace.name"]], "")) where resource.attributes["k8s.namespace.name"] != nil
      - context: span
        statements:
          # Only the engine's own spans are vLLM: "llm_request" is the request span, "vllm:*" the
          # detailed ones.
          - set(span.attributes["gen_ai.system"], "vllm") where span.name == "llm_request" or IsMatch(span.name, "^vllm:")
          # vLLM emits the pre-1.27 semconv token names; publish both.
          - set(span.attributes["gen_ai.usage.input_tokens"], span.attributes["gen_ai.usage.prompt_tokens"]) where span.attributes["gen_ai.usage.prompt_tokens"] != nil
          - set(span.attributes["gen_ai.usage.output_tokens"], span.attributes["gen_ai.usage.completion_tokens"]) where span.attributes["gen_ai.usage.completion_tokens"] != nil

  batch: { send_batch_size: 200, timeout: 10s }

extensions:
  # two signers: the metrics endpoint signs for "monitoring", the traces endpoint for "xray"
  sigv4auth:      { service: monitoring, region: <region> }
  sigv4auth/xray: { service: xray,       region: <region> }

exporters:
  otlphttp/metrics:
    metrics_endpoint: https://monitoring.<region>.amazonaws.com/v1/metrics
    auth: { authenticator: sigv4auth }
    compression: gzip
  otlphttp/traces:
    traces_endpoint: https://xray.<region>.amazonaws.com/v1/traces
    auth: { authenticator: sigv4auth/xray }
    compression: gzip

service:
  extensions: [sigv4auth, sigv4auth/xray]
  pipelines:
    metrics/vllm:
      receivers: [prometheus/vllm]
      processors: [metric_start_time, filter/vllm_keep, transform/vllm_resource, k8sattributes/pod, transform/workload, resource/cluster, batch]
      exporters: [otlphttp/metrics]
    metrics/dcgm:
      receivers: [prometheus/dcgm]
      processors: [metric_start_time, groupbyattrs/dcgm, transform/dcgm_promote, k8sattributes/pod, transform/workload, transform/dcgm_labels, resource/cluster, batch]
      exporters: [otlphttp/metrics]
    traces:
      receivers: [otlp]
      processors: [k8sattributes/traces, transform/workload, transform/traces, resource/cluster, batch]
      exporters: [otlphttp/traces]
```

`otel-collector.yaml`

```yaml
apiVersion: v1
kind: ServiceAccount
metadata: { name: otelcol, namespace: otel-collector }
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata: { name: otelcol }
rules:
  - apiGroups: [""]
    resources: [pods, nodes, namespaces, endpoints, services]
    verbs: [get, list, watch]
  - apiGroups: ["apps"]
    resources: [replicasets, deployments, statefulsets, daemonsets]
    verbs: [get, list, watch]
  - apiGroups: ["batch"]
    resources: [jobs, cronjobs]
    verbs: [get, list, watch]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata: { name: otelcol }
roleRef: { apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: otelcol }
subjects:
  - { kind: ServiceAccount, name: otelcol, namespace: otel-collector }
---
apiVersion: v1
kind: ConfigMap
metadata: { name: otelcol-config, namespace: otel-collector }
data:
  config.yaml: |
    <contents of config.yaml>
---
apiVersion: apps/v1
kind: Deployment
metadata: { name: otelcol, namespace: otel-collector }
spec:
  replicas: 1
  selector: { matchLabels: { app: otelcol } }
  template:
    metadata: { labels: { app: otelcol } }
    spec:
      serviceAccountName: otelcol
      containers:
        - name: otelcol
          image: otel/opentelemetry-collector-contrib:0.160.0
          args: [--config=/conf/config.yaml]
          ports: [{ containerPort: 4318, name: otlp-http }]
          resources:
            requests: { cpu: 200m, memory: 256Mi }
            limits: { cpu: "1", memory: 512Mi }
          volumeMounts: [{ name: cfg, mountPath: /conf }]
      volumes:
        - { name: cfg, configMap: { name: otelcol-config } }
---
apiVersion: v1
kind: Service
metadata: { name: otelcol, namespace: otel-collector }
spec:
  selector: { app: otelcol }
  ports: [{ name: otlp-http, port: 4318, targetPort: 4318 }]
```
