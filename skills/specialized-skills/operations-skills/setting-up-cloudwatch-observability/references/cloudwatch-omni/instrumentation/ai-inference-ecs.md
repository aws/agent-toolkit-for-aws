# vLLM AI inference on Amazon ECS

The ECS steps and files of [ai-inference.md](ai-inference.md). Read that file first: it holds the
rules, the path choice, the placeholders, the trace settings, and Verify. Write the files under
[Files](#files) into one working directory with the names shown, fill the placeholders, and build
the templates with `assemble.py`. In the blocks below, the lines marked `# you` are local or
read-only, and you run them. Present the rest to the user, in order, with every value filled in:
each one creates or changes something in AWS.

## Setup

1. **GPU capacity.** EC2 GPU container instances with the ECS-optimized GPU AMI. In user data, make
   the NVIDIA runtime the Docker default, so the DCGM exporter reads the GPUs without a GPU
   reservation. The lines merge into the existing `/etc/docker/daemon.json`, keeping its other
   settings:

   ```bash
   #!/bin/bash
   python3 - <<'PY'
   import json, os
   p = "/etc/docker/daemon.json"
   cfg = json.load(open(p)) if os.path.exists(p) and os.path.getsize(p) else {}
   cfg["default-runtime"] = "nvidia"
   cfg.setdefault("runtimes", {}).setdefault(
       "nvidia", {"path": "/usr/bin/nvidia-container-runtime", "runtimeArgs": []})
   json.dump(cfg, open(p, "w"), indent=2)
   PY
   systemctl restart docker
   echo "ECS_CLUSTER=<ecsClusterName>" >> /etc/ecs/ecs.config
   ```

   User data runs only when an instance first boots. For instances already in the cluster, add
   the lines to a new launch template version and replace the instances: set each container
   instance to `DRAINING` so ECS moves its tasks, then start an Auto Scaling instance refresh. On
   an instance that must stay, drain it, then run the same lines on it (for example with SSM Run
   Command); restarting Docker stops every container on the instance.
   On EC2 an `awsvpc` task gets no public IP. Give the tasks a NAT gateway or VPC endpoints, to pull
   images and model weights and to reach CloudWatch and X-Ray.
2. **Task role.** The collector signs its calls with the task role (`taskRoleArn` of the vLLM task
   definition). It also reads the task's own GPU IDs with `DescribeTasks`, because the task metadata
   endpoint does not show them:

   ```bash
   aws iam attach-role-policy --role-name <taskRoleName> \
     --policy-arn arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy
   aws iam put-role-policy --role-name <taskRoleName> --policy-name read-own-task-gpu-ids \
     --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
       "Action":"ecs:DescribeTasks",
       "Resource":"arn:aws:ecs:<region>:<accountId>:task/<ecsClusterName>/*"}]}'
   ```

   Never widen a role that other workloads share, such as an account-wide `ecsTaskExecutionRole`
   used as the task role. Create a role for this task instead, give it the two policies above, and
   pass it to `merge_taskdef.py --task-role-arn` (step 5). The execution role stays as it is:

   ```bash
   aws iam create-role --role-name <taskRoleName> --assume-role-policy-document '{"Version":"2012-10-17",
     "Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole",
       "Condition":{"StringEquals":{"aws:SourceAccount":"<accountId>"}}}]}'
   ```

3. **DCGM exporter.** One `DAEMON` service with `host` networking and no GPU reservation, on port
   9400. Files: `dcgm-counters.csv` and the template `dcgm-exporter-taskdef.json` ([Files](#files)). The
   task definition family is named after the cluster, because families are account-wide and another
   cluster may already use `dcgm-exporter`. If the cluster already runs a DCGM exporter (Step 1 of
   [ai-inference.md](ai-inference.md): a `DAEMON` service, such as one an earlier setup created),
   reuse it and skip this step: a second exporter cannot start (Rule 4), and these commands would
   collide with the first one. Then, for an `awsvpc` task, only check that its security-group rule
   lets this task's security group reach port 9400. A `host` task has no security group of its own
   and scrapes the exporter on its own instance, so it needs no rule.

   ```bash
   python3 assemble.py dcgm-exporter-taskdef.json > dcgm-exporter-taskdef.ready.json   # you
   aws ecs register-task-definition --cli-input-json file://dcgm-exporter-taskdef.ready.json
   aws ecs create-service --cluster <ecsClusterName> --service-name dcgm-exporter \
     --task-definition <ecsClusterName>-dcgm-exporter --scheduling-strategy DAEMON --launch-type EC2
   ```

   Allow TCP 9400 into the instance security group from the vLLM task's security group:

   ```bash
   aws ec2 authorize-security-group-ingress --group-id <instance security group> \
     --protocol tcp --port 9400 --source-group <task security group>
   ```

   The exporter is running when both numbers of the second command equal the first, the number of
   container instances. Do not use `aws ecs wait services-stable` here: a new `DAEMON` service
   reports 0 of 0 tasks for its first seconds, and the waiter returns at once.

   ```bash
   aws ecs list-container-instances --cluster <ecsClusterName> --query 'length(containerInstanceArns)'
   aws ecs describe-services --cluster <ecsClusterName> --services dcgm-exporter \
     --query 'services[0].[desiredCount,runningCount]' --output text
   ```

   Do not register the exporter in Cloud Map: each task scrapes only its own host, which it finds in
   IMDS. The exporter's task definition has no log configuration. To check it on the host, use SSM:
   `curl -s localhost:9400/metrics | grep -c '^DCGM_FI_PROF'` (expect the 7 profiling fields), or
   `docker logs` of the exporter container.
4. **vLLM container.** Leave it as it is. Use the task definition family as the service name, unless
   the family is not stable (step 7). Send its logs to the log group `/ecs/<CUSTOMER_SERVICE_NAME>` with the stream prefix `ecs`. Omni reads
   the engine configuration there. Create the group first: the usual execution
   role cannot create log groups, and a missing group stops the whole task from starting. Anything
   that reads the old log group stops getting vLLM's lines; tell the user.

   ```bash
   aws logs create-log-group --log-group-name /ecs/<CUSTOMER_SERVICE_NAME>
   aws logs put-retention-policy --log-group-name /ecs/<CUSTOMER_SERVICE_NAME> --retention-in-days 30
   ```

   The setting in the vLLM container (the merge script in step 5 writes it):

   ```json
   "logConfiguration": {
     "logDriver": "awslogs",
     "options": {
       "awslogs-group": "/ecs/<CUSTOMER_SERVICE_NAME>",
       "awslogs-region": "<region>",
       "awslogs-stream-prefix": "ecs"
     }
   }
   ```

5. **Collector sidecar.** Files: `config-init.sh` ([Both collectors](#both-collectors)) and, per
   collector, [CloudWatch agent](#cloudwatch-agent) or [OpenTelemetry Collector](#opentelemetry-collector).
   Merge the containers and the volume of `collector-containers.ready.json` into the vLLM task
   definition with `merge_taskdef.py` ([Tools](#tools)). First check that the family's latest
   revision is the one the service runs (`aws ecs describe-services`, `taskDefinition`): the merge
   starts from the latest. The user registers the new revision and deploys it:

   ```bash
   python3 assemble.py collector-containers.json > collector-containers.ready.json   # you
   aws ecs describe-task-definition --task-definition <CUSTOMER_SERVICE_NAME> --query taskDefinition > current.json   # you
   python3 merge_taskdef.py current.json collector-containers.ready.json <vLLM container name> <region> \
     > new-revision.json   # you, without traces
   python3 merge_taskdef.py current.json collector-containers.ready.json <vLLM container name> <region> \
     --traces <CUSTOMER_APPLICATION_NAME> > new-revision.json   # you, with traces instead
   aws ecs register-task-definition --cli-input-json file://new-revision.json
   aws ecs update-service --cluster <ecsClusterName> --service <ECS service name> \
     --task-definition <CUSTOMER_SERVICE_NAME>:<new revision>
   # No free GPU next to the old task (below): add
   #   --deployment-configuration minimumHealthyPercent=0,maximumPercent=200
   ```

   `--traces` also adds the trace settings ([ai-inference.md](ai-inference.md) Step 4) to the vLLM
   container, so one deployment covers both. On a `bridge` task the script also links the agent to
   vLLM and points the traces at the per-host collector (step 6). Add `--task-role-arn <arn>` for a
   new task role (step 2), and `--service-name <name>` for a family that is not stable (step 7).
   The deployment is done when its `rolloutState` is `COMPLETED` and vLLM has logged
   `Application startup complete` in its new log group. `aws ecs wait services-stable` returns
   earlier, while the model is still loading.

   ```bash
   aws ecs describe-services --cluster <ecsClusterName> --services <ECS service name> \
     --query 'services[0].deployments[0].rolloutState' --output text
   aws logs filter-log-events --log-group-name /ecs/<CUSTOMER_SERVICE_NAME> --log-stream-name-prefix ecs/<vLLM container name> \
     --filter-pattern '"Application startup complete"' --start-time $(( ($(date +%s) - 900) * 1000 )) \
     --query 'events[].message' --output text
   ```

   The second command prints the startup line once vLLM is up, and nothing before that.
   The deployment replaces the vLLM task, so vLLM restarts and reloads its model: agree a time with
   the user. If the instances have no free GPU, the new task cannot start next to the old one: check
   the GPU in `remainingResources` (`aws ecs describe-container-instances`), and whether the capacity
   provider can add an instance. Then deploy with
   `--deployment-configuration minimumHealthyPercent=0,maximumPercent=200`: ECS stops the old task
   first, and the service is down until the new task is ready. The setting stays on the service; tell
   the user, with its earlier values, which a later `update-service --deployment-configuration` restores. A `maximumPercent` of 100 or less is rejected when Availability Zone rebalancing is on.
   - `config-init` writes the collector configuration at task start. It reads the host IP from IMDS
     (the DCGM scrape target; in `bridge` mode without IMDS, the bridge gateway), the task family from the task metadata endpoint (the scrape job name,
     so the metrics' `service.name`, unless step 7 sets another name), the task's ECS service (`aws.ecs.service.name`, which the ECS
     detector does not set; left out for a standalone task), and the task's GPU IDs with
     `DescribeTasks` (the scrape keeps only those GPUs). It always exits 0.
   - The collector starts after `config-init` completes. Both are non-essential.
   - CloudWatch agent: keep `replacement: unused` in the relabel rule, or the agent exits with
     `environment variable "1" has invalid name`: without a replacement, the agent writes the
     default `$1` into its OTel configuration, and agent 1.300074.0 and later also turn an empty
     one into `$1`. Any value without a `$` works; `keep` ignores it. Keep the `.yml` name of the scrape file: the agent
     loads every `*.yaml` file in `/etc/cwagentconfig` as an OTel configuration.
     `resource_attributes` sets `aws.ecs.task.family`, because the agent's ECS detector does not.
   - OpenTelemetry Collector: keep the `metric_start_time` processor, or CloudWatch drops every
     counter and histogram while gauges still arrive.
   - Keep the `service_name` label lines. Omni's ECS views still read that label, next to the
     resource attribute `service.name`.
   - Expected, harmless CloudWatch agent log lines: `unable to scan config dir /etc/cwagentconfig ...
     unable to parse json` (the agent tries `prometheus.yml` as JSON first), two `E! ... using
     deprecated field "blocking"` lines at start, and a `Partial success response ... Summary
     datapoints are not supported` warning every few seconds to a minute (vLLM's HTTP size summaries).
   - Expected, harmless OpenTelemetry Collector log lines: the same Summary warning; `Partial success
     response ... "Invalid OTel metric type" ... "dropped_data_points": 0`; deprecation notes for the
     `otlphttp` and `resourcedetection` names; an OTTL note that "paths were modified to include
     their context prefix"; and `Failed to scrape Prometheus endpoint ... connection refused` while
     vLLM loads its model.
   - Fill `<vllmHost>` and `<vllmPort>` in the scrape file before you assemble it. Do not assume
     `localhost:8000`.
   - A task-level `memory` must cover vLLM and the sidecars, or ECS rejects the revision or cannot
     place it. `merge_taskdef.py` adds the sidecars' memory to it; vLLM's own memory is unchanged.
     Check that the instances still have room.
   - `config-init` has no dollar-brace variable forms. CloudFormation lint (E1029) flags them when the
     script is embedded in a CloudFormation or CDK template, which is how a generator ships it.
6. **Bridge network mode.** A `bridge` task (on EC2 also a task with no `networkMode`) does not share
   `localhost` between containers. Metrics still work from the sidecar; traces need a collector that
   vLLM can reach at a fixed address.
   - **Metrics:** the agent container links to vLLM (`"links": ["<vLLM container name>:vllm"]`, which
     `merge_taskdef.py` adds) and scrapes `vllm:<vllmPort>`. The link makes the agent start after
     vLLM. Never link vLLM to a collector: vLLM would wait for it.
   - **DCGM:** `config-init` reads the host IP from IMDS. If IMDS is blocked, it uses the bridge
     gateway, which is the host.
   - **Traces:** vLLM pushes spans, and in bridge mode it cannot reach the sidecar: the sidecar's IP
     and any dynamic host port are unknown when vLLM starts. Send them to one collector on each host,
     at the bridge gateway: `--otlp-traces-endpoint=http://172.17.0.1:4318/v1/traces`. Check the
     gateway on a host (`ip -4 addr show docker0`); a custom Docker `bip` changes it.
   - **The per-host collector** is a `DAEMON` service, so a fixed host port never conflicts. Prefer
     the cluster's existing agent `DAEMON` if there is one: keep its network mode (`bridge` works),
     add the port mapping `4318:4318`, and give it its own task role with
     `CloudWatchAgentServerPolicy`. If it runs with `USE_DEFAULT_CONFIG=True`, a custom configuration
     replaces the default: keep the Container Insights metrics (for example a disk-space alarm on
     `instance_filesystem_utilization`) by including the `ecs` section:

     ```json
     {
       "agent": { "region": "<region>" },
       "logs": { "metrics_collected": { "ecs": {} } },
       "opentelemetry": { "collect": { "otlp": { "http_endpoint": "0.0.0.0:4318" } } }
     }
     ```

     Pass it in the `CW_CONFIG_CONTENT` environment variable. In `bridge` mode Docker publishes 4318
     on every host interface: the instance security group must not allow 4318 inbound. With `host`
     networking, bind to the gateway instead (`"http_endpoint": "172.17.0.1:4318"`).
   - **Alternative without a per-host collector:** give the sidecar agent the port mapping
     `4318:4318`. Then at most one such task can run on each host: ECS treats the port as a
     placement constraint. That holds anyway on a one-GPU instance with one-GPU tasks; on multi-GPU
     instances it blocks the second task.
   - Who owns what: the cluster owner runs the DCGM `DAEMON` and the per-host collector; the task
     definition carries the sidecars; the vLLM command carries the trace flag.
7. **A family that is not a stable name.** Omni attributes GPUs by `aws.ecs.task.family` equal to
   `service.name`. If the family is a hash or changes with each version, choose a stable name and
   pass it with `merge_taskdef.py --service-name <name>`: `config-init` then sets both
   `service.name` (the scrape job) and `aws.ecs.task.family` on the metrics to it, and the trace
   settings use it too. Every log group stays `/ecs/<task family>`: in the files and the log-group
   commands, `<CUSTOMER_SERVICE_NAME>` is still the family, and the stable name takes its place only
   in the Verify queries and in Omni. A generator that builds task
   definitions for tenants should put all of this behind an opt-in that is off by default, leave the
   tenant's image and command as they are (the tenant adds `--otlp-traces-endpoint`), and prove with
   a test that its output is unchanged when the opt-in is off.
8. **Host network mode.** A `host` task shares the instance's network. `localhost` reaches vLLM and
   the sidecar as in `awsvpc`, `config-init` reads the host IP from IMDS, and the task needs no
   container link. Tested with both collectors, one task per instance.
   - **The ports are the instance's.** vLLM's port, the receiver's `4318`, and the OpenTelemetry
     Collector's own telemetry port `8888` bind on the instance, and `hostPort` equals
     `containerPort`. ECS does not place a second task that declares a port in use
     (`RESOURCE:PORTS`, `Port 8000 in use.`), so at most one such task runs on each instance. That
     holds anyway on a one-GPU instance with one-GPU tasks. On a multi-GPU instance, give each task
     its own ports: vLLM `--port` and `containerPort`, the scrape target, the receiver
     `http_endpoint`, and the trace endpoint (not tested).
   - **The receiver is open on the instance.** `0.0.0.0:4318` listens on every instance interface, IPv4 and IPv6:
     the instance security group must not allow 4318 inbound, nor the OpenTelemetry Collector's
     8888. Or bind the receiver to
     `127.0.0.1:4318`. That works in `host` mode, where vLLM sends to `localhost`, but not in
     `bridge` mode.
   - **The task role.** A `host` task with a task role requires the instance attribute
     `com.amazonaws.ecs.capability.task-iam-role-network-host` (it is in the task definition's
     `requiresAttributes`), which the ECS agent sets only with
     `ECS_ENABLE_TASK_IAM_ROLE_NETWORK_HOST=true`. The ECS-optimized AMIs set it. On an instance
     without it, ECS does not place the task; add the setting to `/etc/ecs/ecs.config`. Check it
     read-only: each instance ID should be listed with the attribute.

     ```bash
     aws ecs describe-container-instances --cluster <ecsClusterName> \
       --container-instances $(aws ecs list-container-instances --cluster <ecsClusterName> --query 'containerInstanceArns' --output text) \
       --query 'containerInstances[].[ec2InstanceId, attributes[?name==`com.amazonaws.ecs.capability.task-iam-role-network-host`].name | [0]]' --output text
     ```

   - **Next to the per-host collector of step 6**, which publishes `4318` on the instance, the sidecar
     cannot bind `4318`: give its receiver another port, and use that port in the trace endpoint.

## Files

The templates (`dcgm-exporter-taskdef.json` and `collector-containers.json`) contain
`<contents of FILE>` placeholders: build them with `assemble.py`. Use the `collector-containers.json`
of the collector that the user chose.

### Tools

Python 3, standard library only (the Verify script in [ai-inference.md](ai-inference.md) also needs
`boto3` and `requests`). `assemble.py` builds the templates. `merge_taskdef.py` adds the ECS collector to the vLLM task definition.

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

`merge_taskdef.py`

```python
#!/usr/bin/env python3
"""Add the collector to an ECS task definition, ready for register-task-definition.

  aws ecs describe-task-definition --task-definition <family> --query taskDefinition > current.json
  python3 merge_taskdef.py current.json collector-containers.ready.json <vllm container> <region> \
    [--traces <application>] [--service-name <name>] [--task-role-arn <arn>] [--trace-endpoint <url>] > new-revision.json

Appends the collector containers and volumes, points the vLLM container's logs at
/ecs/<family> (stream prefix "ecs"), and with --traces adds the vLLM trace settings. On a bridge-mode
task (no networkMode, or "bridge") it links the collector to the vLLM container as "vllm", and the
trace endpoint is the per-host collector on the bridge gateway (Setup step 6). It raises a task-level
memory by the added containers' memory, so vLLM keeps its own. --service-name sets the name when the
family is not stable (Setup step 7); --task-role-arn sets a task role for this task (Setup step 2).
Everything else in the task definition stays as it is.
"""
import json, sys

READ_ONLY = ["taskDefinitionArn", "revision", "status", "requiresAttributes", "compatibilities",
             "registeredAt", "registeredBy", "deregisteredAt"]
AGENTS = ("cwagent", "otel-collector")
args = sys.argv[1:]
opts = {}
for flag in ("--traces", "--service-name", "--task-role-arn", "--trace-endpoint"):
    if flag in args:
        i = args.index(flag); opts[flag] = args[i + 1]; del args[i:i + 2]
current_path, collector_path, vllm_name, region = args
td = json.load(open(current_path))
td = td.get("taskDefinition", td)
for k in READ_ONLY:
    td.pop(k, None)
col = json.load(open(collector_path))
family = td["family"]
service = opts.get("--service-name", family)
bridge = td.get("networkMode", "bridge") == "bridge"
names = {c["name"] for c in td["containerDefinitions"]}
if vllm_name not in names:
    sys.exit(f"container {vllm_name} not found in {family}")
added_memory = 0
for c in col["containerDefinitions"]:
    if c["name"] in names:
        sys.exit(f"container {c['name']} already exists in {family}")
    if bridge and c["name"] in AGENTS:
        # No shared localhost in bridge mode. The agent waits for vLLM; vLLM waits for nothing.
        c["links"] = [f"{vllm_name}:vllm"]
    if "--service-name" in opts and c["name"] == "config-init":
        c.setdefault("environment", []).append({"name": "SERVICE_NAME", "value": service})
    added_memory += c.get("memory", c.get("memoryReservation", 0))
    td["containerDefinitions"].append(c)
if td.get("memory"):
    td["memory"] = str(int(td["memory"]) + added_memory)
if "--task-role-arn" in opts:
    td["taskRoleArn"] = opts["--task-role-arn"]
vols = {v["name"] for v in td.get("volumes", [])}
td["volumes"] = td.get("volumes", []) + [v for v in col.get("volumes", []) if v["name"] not in vols]
vllm = next(c for c in td["containerDefinitions"] if c["name"] == vllm_name)
vllm["logConfiguration"] = {"logDriver": "awslogs", "options": {
    "awslogs-group": f"/ecs/{family}", "awslogs-region": region, "awslogs-stream-prefix": "ecs"}}
if "--traces" in opts:
    endpoint = opts.get("--trace-endpoint", "http://172.17.0.1:4318/v1/traces" if bridge
                        else "http://localhost:4318/v1/traces")
    cmd = vllm.setdefault("command", [])
    if not any(a.startswith("--otlp-traces-endpoint") for a in cmd):
        cmd.append(f"--otlp-traces-endpoint={endpoint}")
    env = [e for e in vllm.get("environment", []) if e["name"] not in
           ("OTEL_SERVICE_NAME", "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL", "OTEL_RESOURCE_ATTRIBUTES")]
    env += [{"name": "OTEL_SERVICE_NAME", "value": service},
            {"name": "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL", "value": "http/protobuf"},
            {"name": "OTEL_RESOURCE_ATTRIBUTES",
             "value": f"service.name={service},aws.service.type=ai_inference,service.namespace={opts['--traces']}"}]
    vllm["environment"] = env
print(json.dumps(td, indent=2))
```

### Both collectors

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

`dcgm-exporter-taskdef.json`

```json
{
  "family": "<ecsClusterName>-dcgm-exporter",
  "networkMode": "host",
  "requiresCompatibilities": [
    "EC2"
  ],
  "volumes": [
    {
      "name": "dcgm-config",
      "host": {}
    }
  ],
  "containerDefinitions": [
    {
      "name": "csv-init",
      "image": "public.ecr.aws/docker/library/busybox:stable",
      "essential": false,
      "memoryReservation": 64,
      "command": [
        "sh",
        "-c",
        "printf '%s' \"$DCGM_CSV\" > /cfg/dcgm-counters.csv"
      ],
      "environment": [
        {
          "name": "DCGM_CSV",
          "value": "<contents of dcgm-counters.csv>"
        }
      ],
      "mountPoints": [
        {
          "sourceVolume": "dcgm-config",
          "containerPath": "/cfg"
        }
      ]
    },
    {
      "name": "dcgm-exporter",
      "image": "nvcr.io/nvidia/k8s/dcgm-exporter:4.6.0-4.8.3-distroless",
      "essential": true,
      "linuxParameters": {
        "capabilities": {
          "add": [
            "SYS_ADMIN"
          ]
        }
      },
      "memoryReservation": 512,
      "command": [
        "-f",
        "/cfg/dcgm-counters.csv"
      ],
      "environment": [
        {
          "name": "DCGM_EXPORTER_LISTEN",
          "value": ":9400"
        },
        {
          "name": "DCGM_EXPORTER_KUBERNETES",
          "value": "false"
        },
        {
          "name": "NVIDIA_VISIBLE_DEVICES",
          "value": "all"
        },
        {
          "name": "NVIDIA_DRIVER_CAPABILITIES",
          "value": "utility"
        }
      ],
      "dependsOn": [
        {
          "containerName": "csv-init",
          "condition": "COMPLETE"
        }
      ],
      "mountPoints": [
        {
          "sourceVolume": "dcgm-config",
          "containerPath": "/cfg",
          "readOnly": true
        }
      ]
    }
  ]
}
```

`config-init.sh`

```bash
# Best effort: this container ALWAYS exits 0, so the collector always starts and nothing we add
# can stop the task. Any lookup that fails degrades the GPU metrics instead of failing.
# No dollar-brace variable forms: CloudFormation lint (E1029) flags them inside a template.
log() { echo "config-init: $*"; }
META=$(curl -s --max-time 5 "$ECS_CONTAINER_METADATA_URI_V4/task" || true)
field() { printf '%s' "$META" | sed -n "s/.*\"$1\": *\"\([^\"]*\)\".*/\1/p" | head -1; }
FAMILY=$(field Family); REV=$(field Revision); ARN=$(field TaskARN); CLUSTER=$(field Cluster)
NETMODE=$(field NetworkMode)
# The ECS service of the task. A standalone task has none, and its attribute line is dropped.
ECS_SERVICE=$(field ServiceName)
[ -n "$FAMILY" ] || { FAMILY=unknown-service; log "WARN no task metadata; service name unknown"; }
[ -n "$REV" ] || REV=0
# The service name: the task family, or SERVICE_NAME when the family is not stable (Setup step 7).
SVC=$SERVICE_NAME
[ -n "$SVC" ] || SVC=$FAMILY
REGION=$(printf '%s' "$ARN" | cut -d: -f4)
# The container instance IP: the host-network DCGM DAEMON's scrape target (IMDSv2).
TOKEN=$(curl -s --max-time 3 -X PUT -H "X-aws-ec2-metadata-token-ttl-seconds: 300" http://169.254.169.254/latest/api/token || true)
HOST=$(curl -s --max-time 3 -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/local-ipv4 || true)
# Bridge networking without IMDS: the bridge gateway is the host.
if ! printf '%s' "$HOST" | grep -Eq '^[0-9]+(\.[0-9]+){3}$' && [ "$NETMODE" = bridge ]; then
  HOST=""
  while read -r IFACE DEST GW REST; do
    if [ "$DEST" = 00000000 ] && printf '%s' "$GW" | grep -Eq '^[0-9A-Fa-f]{8}$'; then
      # Little-endian hex, for example 010011AC -> 172.17.0.1.
      HOST=$(printf '%d.%d.%d.%d' "0x$(printf '%s' "$GW" | cut -c7-8)" "0x$(printf '%s' "$GW" | cut -c5-6)" \
        "0x$(printf '%s' "$GW" | cut -c3-4)" "0x$(printf '%s' "$GW" | cut -c1-2)"); break
    fi
  done < /proc/net/route
  [ -z "$HOST" ] || log "no host IP from IMDS; using the bridge gateway $HOST"
fi
if ! printf '%s' "$HOST" | grep -Eq '^[0-9]+(\.[0-9]+){3}$'; then
  log "WARN no host IP from IMDS; GPU metrics disabled"; HOST=127.0.0.1
fi
# The GPUs ECS assigned to this task. The task metadata endpoint does not expose them.
GPUS=""
if [ -n "$ARN" ] && [ -n "$CLUSTER" ]; then
  for i in 1 2 3 4 5 6 7 8 9 10; do
    GPUS=$(aws ecs describe-tasks --region "$REGION" --cluster "$CLUSTER" --tasks "$ARN" \
             --query 'tasks[0].containers[].gpuIds[]' --output text 2>/dev/null | tr -s '\t ' '|' | sed 's/^|//; s/|$//')
    [ -n "$GPUS" ] && [ "$GPUS" != None ] && break
    GPUS=""; sleep 3
  done
fi
if ! printf '%s' "$GPUS" | grep -Eq '^GPU-[0-9a-f-]+(\|GPU-[0-9a-f-]+)*$'; then
  log "WARN no GPU IDs from DescribeTasks; GPU metrics disabled"; GPUS=NO-GPU-ASSIGNED
fi
SVC_EXPR="/__ECS_SERVICE_NAME__/d"
[ -z "$ECS_SERVICE" ] || SVC_EXPR="s#__ECS_SERVICE_NAME__#$ECS_SERVICE#g"
# aws.ecs.task.family is Omni's GPU owner key and must equal service.name: both get SVC.
fill() {
  printf '%s' "$1" | sed -e "s#__SERVICE_NAME__#$SVC#g" -e "s#__TASK_FAMILY__#$SVC#g" -e "s#__TASK_REVISION__#$REV#g" \
    -e "s#__GPU_UUIDS__#$GPUS#g" -e "s#__HOST_IP__#$HOST#g" -e "$SVC_EXPR"
}
[ -z "$CWAGENT_JSON" ]   || fill "$CWAGENT_JSON"   > /out/cwagentconfig.json
[ -z "$PROMETHEUS_YML" ] || fill "$PROMETHEUS_YML" > /out/prometheus.yml
[ -z "$OTEL_YAML" ]      || fill "$OTEL_YAML"      > /out/otel.yaml
log "service.name=$SVC family=$FAMILY revision=$REV ecs.service=$ECS_SERVICE network=$NETMODE host=$HOST gpus=$GPUS"
exit 0
```

### CloudWatch agent

`cwagent-config.json`

```json
{
  "agent": { "region": "<region>" },
  "opentelemetry": {
    "collect": {
      "prometheus": { "config_path": "/etc/cwagentconfig/prometheus.yml" },
      "otlp": { "http_endpoint": "0.0.0.0:4318" }
    },
    "resource_attributes": {
      "aws.ecs.service.name": "__ECS_SERVICE_NAME__",
      "aws.ecs.task.family": "__TASK_FAMILY__",
      "aws.ecs.task.revision": "__TASK_REVISION__",
      "service.namespace": "<CUSTOMER_APPLICATION_NAME>",
      "aws.service.type": "ai_inference"
    }
  }
}
```

`prometheus.yml`

```yaml
scrape_configs:
  - job_name: __SERVICE_NAME__
    scrape_interval: 15s
    static_configs:
      - targets: ['<vllmHost>:<vllmPort>']
        labels:
          service_name: __SERVICE_NAME__
  - job_name: dcgm
    scrape_interval: 15s
    static_configs:
      - targets: ['__HOST_IP__:9400']
        labels:
          service_name: __SERVICE_NAME__
    metric_relabel_configs:
      # Keep only the GPUs that ECS gave this task.
      - source_labels: [UUID]
        regex: '__GPU_UUIDS__'
        action: keep
        replacement: unused  # keep ignores it; it must not be empty or contain a $
```

`collector-containers.json`

```json
{
  "containerDefinitions": [
      {
        "name": "config-init",
        "image": "public.ecr.aws/aws-cli/aws-cli:2.31.9",
        "essential": false,
        "memoryReservation": 128,
        "entryPoint": ["sh", "-c"],
        "command": ["<contents of config-init.sh>"],
        "environment": [
          { "name": "CWAGENT_JSON", "value": "<contents of cwagent-config.json>" },
          { "name": "PROMETHEUS_YML", "value": "<contents of prometheus.yml>" }
        ],
        "logConfiguration": { "logDriver": "awslogs", "options": { "awslogs-group": "/ecs/<CUSTOMER_SERVICE_NAME>", "awslogs-region": "<region>", "awslogs-stream-prefix": "collector" } },
      "mountPoints": [ { "sourceVolume": "collector-config", "containerPath": "/out" } ]
      },
      {
        "name": "cwagent",
        "image": "public.ecr.aws/cloudwatch-agent/cloudwatch-agent:1.300073.2b1889",
        "essential": false,
        "memoryReservation": 1024,
        "dependsOn": [ { "containerName": "config-init", "condition": "COMPLETE" } ],
        "environment": [ { "name": "RUN_IN_CONTAINER", "value": "True" } ],
        "logConfiguration": { "logDriver": "awslogs", "options": { "awslogs-group": "/ecs/<CUSTOMER_SERVICE_NAME>", "awslogs-region": "<region>", "awslogs-stream-prefix": "collector" } },
      "mountPoints": [ { "sourceVolume": "collector-config", "containerPath": "/etc/cwagentconfig", "readOnly": true } ]
      }
  ],
  "volumes": [ { "name": "collector-config", "host": {} } ]
}
```

### OpenTelemetry Collector

`otel.yaml`

```yaml
receivers:
  prometheus/vllm:
    config:
      scrape_configs:
        - job_name: __SERVICE_NAME__
          scrape_interval: 15s
          static_configs:
            - targets: ['<vllmHost>:<vllmPort>']
              labels:
                service_name: __SERVICE_NAME__
                # Temporary: moved to the aws.service.type resource attribute below.
                aws_service_type: ai_inference
  prometheus/dcgm:
    config:
      scrape_configs:
        - job_name: dcgm
          scrape_interval: 15s
          static_configs:
            - targets: ['__HOST_IP__:9400']
              labels:
                service_name: __SERVICE_NAME__
          metric_relabel_configs:
            # Keep only the GPUs that ECS gave this task.
            - source_labels: [UUID]
              regex: '__GPU_UUIDS__'
              action: keep
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318

processors:
  # CloudWatch drops counters and histograms that have no start time.
  # The registered type (otelcol-contrib components); metricstarttime is its deprecated former name.
  metric_start_time:
    strategy: subtract_initial_point
  # Mark the vLLM metrics as AI inference. The GPU metrics get no marker.
  transform/service_type:
    error_mode: ignore
    metric_statements:
      - context: datapoint
        statements:
          - set(resource.attributes["aws.service.type"], attributes["aws_service_type"]) where attributes["aws_service_type"] != nil
          - delete_key(attributes, "aws_service_type")
  # Adds aws.ecs.task.family, aws.ecs.cluster.arn, and host.id (not aws.ecs.cluster.name).
  resourcedetection/ecs:
    detectors: [env, ecs, ec2]
    timeout: 5s
    override: false
  resource/namespace:
    attributes:
      - key: service.namespace
        value: <CUSTOMER_APPLICATION_NAME>
        action: upsert
      # The ECS service of the task, from config-init. One line: it is dropped for a standalone task.
      - {key: aws.ecs.service.name, value: __ECS_SERVICE_NAME__, action: insert}
      # Omni's GPU owner key; equals service.name (Setup step 7). The ECS detector sets the family.
      - {key: aws.ecs.task.family, value: __TASK_FAMILY__, action: upsert}
  batch:
    send_batch_size: 200
    timeout: 10s

exporters:
  otlphttp/metrics:
    metrics_endpoint: https://monitoring.<region>.amazonaws.com/v1/metrics
    auth: { authenticator: sigv4auth/monitoring }
    compression: gzip
  otlphttp/traces:
    traces_endpoint: https://xray.<region>.amazonaws.com/v1/traces
    auth: { authenticator: sigv4auth/xray }
    compression: gzip

extensions:
  sigv4auth/monitoring: { service: monitoring, region: <region> }
  sigv4auth/xray: { service: xray, region: <region> }

service:
  extensions: [sigv4auth/monitoring, sigv4auth/xray]
  pipelines:
    metrics:
      receivers: [prometheus/vllm, prometheus/dcgm]
      processors: [metric_start_time, transform/service_type, resourcedetection/ecs, resource/namespace, batch]
      exporters: [otlphttp/metrics]
    traces:
      receivers: [otlp]
      processors: [resourcedetection/ecs, resource/namespace, batch]
      exporters: [otlphttp/traces]
```

`collector-containers.json`

```json
{
  "containerDefinitions": [
      {
        "name": "config-init",
        "image": "public.ecr.aws/aws-cli/aws-cli:2.31.9",
        "essential": false,
        "memoryReservation": 128,
        "entryPoint": ["sh", "-c"],
        "command": ["<contents of config-init.sh>"],
        "environment": [ { "name": "OTEL_YAML", "value": "<contents of otel.yaml>" } ],
        "logConfiguration": { "logDriver": "awslogs", "options": { "awslogs-group": "/ecs/<CUSTOMER_SERVICE_NAME>", "awslogs-region": "<region>", "awslogs-stream-prefix": "collector" } },
      "mountPoints": [ { "sourceVolume": "collector-config", "containerPath": "/out" } ]
      },
      {
        "name": "otel-collector",
        "image": "otel/opentelemetry-collector-contrib:0.160.0",
        "essential": false,
        "memoryReservation": 512,
        "command": ["--config=/config/otel.yaml"],
        "dependsOn": [ { "containerName": "config-init", "condition": "COMPLETE" } ],
        "logConfiguration": { "logDriver": "awslogs", "options": { "awslogs-group": "/ecs/<CUSTOMER_SERVICE_NAME>", "awslogs-region": "<region>", "awslogs-stream-prefix": "collector" } },
      "mountPoints": [ { "sourceVolume": "collector-config", "containerPath": "/config", "readOnly": true } ]
      }
  ],
  "volumes": [ { "name": "collector-config", "host": {} } ]
}
```
