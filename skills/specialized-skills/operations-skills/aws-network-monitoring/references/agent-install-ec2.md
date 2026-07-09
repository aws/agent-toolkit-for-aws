# EC2 Agent Installation Procedure

Two install paths are supported. Prefer **SSM Distributor** when SSM is
available — it lets you target many instances in one call (by tag, instance
ID, or resource group) and integrates with the manage-agent document used to
activate/deactivate agents. Use the **command-line** path when SSM is
unavailable. Activation is only applicable for the SSM path; command-line-installed
agents start publishing as soon as IAM permissions are in place.

## Prerequisites

- IAM permissions configured *before* install (see
  [agent-permissions.md](agent-permissions.md)). Agents install successfully
  without the policy but cannot publish metrics until it is attached.
- Supported Linux distribution (see [AWS documentation](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-NetworkFlowMonitor-agents-versions.html))
- For the SSM path: target EC2 instances must have SSM Agent installed and running

## SSM Distributor install path

## Step 1: Verify SSM connectivity

```bash
aws ssm describe-instance-information \
  --filters "Key=InstanceIds,Values=<instance-id>" \
  --query "InstanceInformationList[].{Id:InstanceId,Ping:PingStatus}" \
  --output table
```

If instances don't appear, ensure the instance has the `AmazonSSMManagedInstanceCore` policy attached.

## Step 2: Install the agent

By instance ID:

```bash
aws ssm send-command \
  --document-name "AWS-ConfigureAWSPackage" \
  --targets "Key=instanceids,Values=<instance-id-1>,<instance-id-2>" \
  --parameters '{"action":["Install"],"name":["AmazonCloudWatchNetworkFlowMonitorAgent"]}' \
  --comment "Install Network Flow Monitor agent"
```

By tag:

```bash
aws ssm send-command \
  --document-name "AWS-ConfigureAWSPackage" \
  --targets "Key=tag:Environment,Values=<your-tag-value>" \
  --parameters '{"action":["Install"],"name":["AmazonCloudWatchNetworkFlowMonitorAgent"]}' \
  --comment "Install Network Flow Monitor agent on tagged instances"
```

## Step 3: Verify installation status

```bash
aws ssm list-command-invocations \
  --command-id "<command-id-from-step-2>" \
  --details \
  --query "CommandInvocations[].{Instance:InstanceId,Status:Status}" \
  --output table
```

## Step 4: Activate the agent

```bash
aws ssm send-command \
  --document-name "AmazonCloudWatch-NetworkFlowMonitorManageAgent" \
  --targets "Key=instanceids,Values=<instance-id-1>,<instance-id-2>" \
  --parameters '{"Action":["Activate"]}' \
  --comment "Activate Network Flow Monitor agent"
```

## Step 5: Verify the agent is publishing

Wait 30-60 seconds (the agent publishes reports every 30 seconds by default,
with up to 5 seconds of jitter), then check agent logs for successful HTTP
responses:

```bash
sudo journalctl -u network-flow-monitor.service | grep HTTP
```

HTTP 200 responses to `networkflowmonitorreports.<region>.api.aws` confirm
the agent is publishing successfully. Any other status code indicates an
error — see [troubleshooting.md](troubleshooting.md).

## Deactivate (without uninstalling)

Deactivating stops metric publishing and the associated billing without
removing the agent.

```bash
aws ssm send-command \
  --document-name "AmazonCloudWatch-NetworkFlowMonitorManageAgent" \
  --targets "Key=instanceids,Values=<instance-id>" \
  --parameters '{"Action":["Deactivate"]}'
```

## Uninstall

```bash
aws ssm send-command \
  --document-name "AWS-ConfigureAWSPackage" \
  --targets "Key=instanceids,Values=<instance-id>" \
  --parameters '{"action":["Uninstall"],"name":["AmazonCloudWatchNetworkFlowMonitorAgent"]}'
```

## Command-line install path (no SSM)

Use when SSM is unavailable. Activation is **not applicable** to this path —
the agent begins publishing as soon as the package is installed and the IAM
policy is attached to the instance role.

**Amazon Linux 2023 (package repository):**

```bash
sudo yum install network-flow-monitor-agent
```

**Amazon Linux 2023 (direct download by architecture):**

```bash
# x86_64
sudo yum install https://networkflowmonitoragent.awsstatic.com/latest/x86_64/network-flow-monitor-agent.rpm

# ARM64 (Graviton)
sudo yum install https://networkflowmonitoragent.awsstatic.com/latest/arm64/network-flow-monitor-agent.rpm
```

**Debian / Ubuntu:**

```bash
# x86_64
wget https://networkflowmonitoragent.awsstatic.com/latest/x86_64/network-flow-monitor-agent.deb
sudo apt-get install ./network-flow-monitor-agent.deb

# ARM64 (Graviton)
wget https://networkflowmonitoragent.awsstatic.com/latest/arm64/network-flow-monitor-agent.deb
sudo apt-get install ./network-flow-monitor-agent.deb
```

**Red Hat / CentOS / SUSE:**

Use the same RPM as Amazon Linux 2023 above (substitute `zypper` for `yum` on
SUSE). The SSM Distributor path also covers these distros and uses the same
RPM internally.

**Verify the agent is running:**

```bash
service network-flow-monitor status
```

The output should show `Loaded: ... enabled` and `Active: active (running)`.

Attach `CloudWatchNetworkFlowMonitorAgentPublishPolicy` to the instance role
(see [agent-permissions.md](agent-permissions.md)) so the agent can publish
metrics.
