# HyperPod SSM Access

## Prerequisites

- **`aws` CLI v2**, authenticated for the target account/Region.
- **`session-manager-plugin`** — a separate install from the AWS CLI ([Install the Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)).
- **`jq`** — the scripts build JSON payloads with it.
- **`unbuffer`** (from the `expect` package) — wraps `aws ssm start-session` with a PTY so the session-manager-plugin flushes stdout instead of racing to close. Without it, calls intermittently return empty output with `Cannot perform start session: EOF` even when the command ran. Ask the user before installing anything on their machine; the install is `sudo yum install expect`, `sudo apt install expect`, or `brew install expect`. `ssm-exec.sh` detects and uses it automatically; falls back with a warning if missing.

## SSM Target Format

Target: `sagemaker-cluster:<CLUSTER_ID>_<GROUP_NAME>-<INSTANCE_ID>`

- `CLUSTER_ID`: Last segment of cluster ARN (NOT the cluster name). Extract via `get-cluster-info.sh`.
- `GROUP_NAME`: Instance group name — retrieve via `list-nodes.sh`.
- `INSTANCE_ID`: EC2 instance ID (e.g., `i-0123456789abcdef0`)

## Scripts

Three scripts under `scripts/`. Resolve cluster info and nodes **once**, then execute per node.

**Find the cluster and nodes before asking.** If the user named the cluster, use it. Otherwise run `aws sagemaker list-clusters` and offer what it returns. Then run `list-nodes.sh` and offer its nodes to choose from, instead of asking for instance IDs. If the user named the cluster but no nodes, let them choose; never default to every node.

**Ask before changing a node.** Commands run as root, often on a shared cluster. Run a read-only command on the nodes the user named without asking. For anything else, and before reading a file that may hold secrets, show the exact command, the nodes and whether it can be undone, and wait for the user's yes. The full rule is in the router (see "Rules" in ../../overview.md).

**Region.** Each script passes `--region` only when you give it one. Otherwise the AWS CLI picks the Region: `AWS_REGION`, then `AWS_DEFAULT_REGION`, then the profile. `get-cluster-info.sh` reports the cluster's Region from its ARN; pass that as `--region` to `list-nodes.sh` and `ssm-exec.sh`.

### get-cluster-info.sh — Resolve cluster name → ID (call once)

```bash
scripts/get-cluster-info.sh CLUSTER_NAME [--region REGION]
# Output: {"cluster_id":"...","cluster_arn":"...","cluster_name":"...","region":"..."}
```

### list-nodes.sh — List all nodes with pagination (call once)

```bash
scripts/list-nodes.sh CLUSTER_NAME [--region REGION] [--instance-group GROUP] [--instance-id ID]
# Output: JSON array of ClusterNodeSummaries (InstanceId, InstanceGroupName, InstanceStatus, etc.)
```

`list-cluster-nodes` paginates at 100 nodes. This script handles pagination automatically.

### ssm-exec.sh — Execute command on a node (call per node)

Run a command (with a pre-built target, or with its parts), upload a file, or read a remote file:

```bash
scripts/ssm-exec.sh --target "sagemaker-cluster:CLUSTERID_GROUP-INSTANCEID" 'command' [--region REGION]
scripts/ssm-exec.sh --cluster-id ID --group GROUP --instance-id INSTANCE_ID 'command' [--region REGION]
scripts/ssm-exec.sh --target TARGET --upload LOCAL_PATH REMOTE_PATH [--region REGION]
scripts/ssm-exec.sh --target TARGET --read REMOTE_PATH [--region REGION]
```

`ssm-exec.sh` runs the command through `bash -c` on the node, so pipes, `&&` and redirects work.

`--read` is for viewing a file, not for saving a copy. Through `unbuffer`, its line endings come back as CRLF, and the output includes Session Manager lines such as `Starting session with SessionId: ...`.

## Running Commands Across Many Nodes

SSM `start-session` rate limit: **3 TPS** per account by default ([Systems Manager quotas](https://docs.aws.amazon.com/general/latest/gr/ssm.html); this can change). Start SSM sessions in batches of 3, with a 1-second pause between batches.

`aws ssm send-command` does NOT support `sagemaker-cluster:` targets — only `start-session` works.

## Manual SSM Commands

When the scripts aren't suitable, use `aws ssm start-session` directly with `AWS-StartNonInteractiveCommand`. Wrap every invocation in `unbuffer` — without it, stdout is intermittently empty (see Prerequisites). Write the command to a JSON file first, for example `/tmp/cmd.json` containing `{"command": ["bash -c 'echo hello && whoami'"]}`, then run:

```bash
unbuffer aws ssm start-session \
  --target sagemaker-cluster:{CLUSTER_ID}_{GROUP_NAME}-{INSTANCE_ID} \
  --region REGION \
  --document-name AWS-StartNonInteractiveCommand \
  --parameters file:///tmp/cmd.json
```

- Always use a JSON file for `--parameters` — inline parameters break with special characters.
- The document's `command` parameter is argv, not shell input. Wrap multi-statement scripts in `bash -c '...'` so pipes, semicolons, and redirects evaluate.

## Common Diagnostic Commands

| Task             | Command                                                        |
| ---------------- | -------------------------------------------------------------- |
| Lifecycle logs   | `tail -n 200 /var/log/provision/provisioning.log`              |
| Memory           | `free -h`                                                      |
| Disk/mounts      | `df -h && lsblk`                                               |
| GPU status       | `nvidia-smi`                                                   |
| GPU memory       | `nvidia-smi --query-gpu=memory.used,memory.total --format=csv` |
| EFA/network      | `fi_info -p efa`                                               |
| CloudWatch agent | `sudo systemctl status amazon-cloudwatch-agent`                |
| Top processes    | `ps aux --sort=-%mem \| head -20`                              |

## Key Details

- Default SSM non-interactive user is `root`.
- `start-session` is rate limited (see Running Commands Across Many Nodes).
- Interactive shells are for the user to open in their own terminal. Never start one yourself: you can't drive it, so the session hangs.
- Interactive commands (vim, top) are not supported via `AWS-StartNonInteractiveCommand`.
- Large outputs may be truncated by SSM. Use `tail`, `head` or `grep` to show only the part you need.
- The script's exit status comes from the SSM session and may not be the command's. Read the command's output to tell whether it worked.
- For troubleshooting common errors, see [references/troubleshooting.md](references/troubleshooting.md).
