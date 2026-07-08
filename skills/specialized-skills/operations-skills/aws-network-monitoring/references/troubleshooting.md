# Troubleshooting Network Flow Monitor

## SSM command fails or instance not reachable via SSM

Verify the SSM Agent is running on the instance and the instance can reach
SSM endpoints. For isolated subnets, ensure VPC endpoints for SSM
(`com.amazonaws.<region>.ssm`, `.ssmmessages`, `.ec2messages`) are configured.
The instance role also needs `AmazonSSMManagedInstanceCore` attached.

## Agent installed but never activated (SSM path only)

Installation and activation are separate steps when using the SSM Distributor
path. After installing via SSM Distributor, you must explicitly activate the
agent using the `AmazonCloudWatch-NetworkFlowMonitorManageAgent` SSM document
with `Action: Activate`. See [agent-install-ec2.md](agent-install-ec2.md) Step 4.

This does NOT apply to command-line installs (yum/apt-get). Agents installed
via command-line begin publishing as soon as the package is installed and the
IAM policy is attached — no activation step is needed.

## Stopping and starting the agent

```bash
sudo service network-flow-monitor stop
sudo service network-flow-monitor start
```

## Verify agent status

```bash
sudo service network-flow-monitor status
```

## Verify endpoint connectivity and IAM permissions

Check agent logs for HTTP errors:

```bash
sudo journalctl -f -u network-flow-monitor.service | grep -i HTTP
```

Any status code other than 200 indicates an error.

### HTTP 403 — Missing/insufficient IAM permissions

```json
{
    "level": "INFO",
    "message": "HTTP request complete",
    "status": 403,
    "target": "nfm_agent::reports::publisher_endpoint",
    "timestamp": "XXXX"
}
```

**Fix:** Attach `CloudWatchNetworkFlowMonitorAgentPublishPolicy` to the instance role. See [agent-permissions.md](agent-permissions.md).

### Connection error — Network connectivity issue

```json
{
    "level": "ERROR",
    "message": "Error sending request: error sending request for url (https://networkflowmonitorreports.<region>.api.aws/publish)",
    "target": "nfm_agent::reports::publisher_endpoint",
    "timestamp": "XXXX"
}
```

**Fix:** Verify connectivity to the Network Flow Monitor endpoint:

```bash
nc -zv networkflowmonitorreports.<region>.api.aws 443
```

Or perform an authenticated TLS check:

```bash
curl -v https://networkflowmonitorreports.<region>.api.aws/
```

If using private subnets, ensure a VPC endpoint or NAT gateway is configured for the Network Flow Monitor service endpoint.
