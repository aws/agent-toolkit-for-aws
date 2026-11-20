# LMCache Setup and Configuration

## Table of contents

- Overview
- Software requirements
- Install
- Start the server (API key and metrics endpoint, launcher, systemd units, `tcp` and `blob-tcp`)
- Flag and adapter reference
- Registered memory and hugepages
- NUMA placement
- Connect vLLM
- Connect SGLang
- Multi-server deployments
- L2 store and prefetch policies
- Start and stop order
- Before production traffic

## Overview

LMCache runs as a multiprocess (MP) server between the engine (over ZMQ or gRPC) and ElastiCache. L1 is host CPU RAM; L2 is the shared cluster. New chunks go from L1 to L2 asynchronously, and an L1 miss loads from L2 into L1. Transports: [SKILL.md](SKILL.md#transports).

## Software requirements

This table is the one home for versions. Install the latest release of each component; the minimum is the first release with the feature. After each install or upgrade, run the feature checks and stop if one fails. If a check fails, or the [LMCache docs](https://docs.lmcache.ai/mp/l2_storage/valkey.html) or [valkey-glide release notes](https://github.com/valkey-io/valkey-glide/releases) disagree with this skill, follow the docs.

| Component | Minimum (first release with the feature) | Feature check |
|---|---|---|
| LMCache, `rdma` and `blob-tcp` | 0.5.8rc1 (a pre-release) | `rdma_worker_pool.py` and `blob_tcp_worker_pool.py` in `lmcache/v1/distributed/l2_adapters/valkey/`. Without them, only `tcp`; if no release has `rdma`, say so and offer `tcp` for functional tests only |
| valkey-glide-sync, `rdma` | 2.6.0 (first with Python RDMA) | `rdma_available()` and `rdma_usable()` print `True True`. LMCache does not install it |
| libfabric (EFA installer) | 2.4 | [client-setup.md](references/client-setup.md#efa-driver-stack) |
| vLLM | A release with `LMCacheMPConnector` | [Connect vLLM](#connect-vllm) |
| SGLang | 0.5.13 (first with `--lmcache-config-file`) | [Connect SGLang](#connect-sglang) |

```bash
LMCACHE_PY=/opt/lmcache/venv/bin/python
"$LMCACHE_PY" -c "import lmcache, pathlib; p = pathlib.Path(lmcache.__file__).parent / 'v1/distributed/l2_adapters/valkey'; print(sorted(f.name for f in p.glob('*worker_pool.py')))"
"$LMCACHE_PY" -c 'import glide_sync as g; print(g.GlideClient.rdma_available(), g.GlideClient.rdma_usable())'   # MUST print True True
```

**Credential order.** After every LMCache or valkey-glide install or upgrade, you MUST run the credential-order check in [troubleshooting.md](references/troubleshooting.md#wrongpass-when-lmcache-connects) and set `SWAP_CREDENTIALS` in the launcher from its result.

After the server starts, do [Before production traffic](#before-production-traffic).

## Install

For the platform (CUDA, ROCm, Intel XPU), follow the [LMCache installation guide](https://docs.lmcache.ai/getting_started/installation.html). Install from a private mirror first ([SKILL.md](SKILL.md#security-considerations)), test a new version in a scratch environment, and give the engine image and every server the same versions.

`pip install lmcache` gives the latest final release, which can lack `rdma`. Install the newest release at or above the table minimum: a specifier with a pre-release (`'lmcache>=0.5.8rc1'`) admits pre-releases of `lmcache` only. You MUST NOT pass `--pre`, which admits them for every dependency.

The venv belongs to root and the service user can read it; the subshell sets `umask 022` for the install only (`sudo` keeps a stricter umask). The venv MUST use a Python that the LMCache release supports (`requires-python`; 3.10 to 3.14 for 0.5.8rc1), for example `python3.12`; on some AMIs `python3` is older:

```bash
sudo useradd --system --no-create-home --shell /sbin/nologin lmcache   # the service user
( umask 022
  sudo install -d -m 0755 -o root -g root /opt/lmcache
  sudo python3.12 -m venv /opt/lmcache/venv
  sudo /opt/lmcache/venv/bin/pip index versions lmcache --pre     # newest release and pre-release
  sudo /opt/lmcache/venv/bin/pip install --upgrade 'lmcache>=0.5.8rc1' valkey-glide-sync boto3 )  # boto3: launcher
sudo -u lmcache /opt/lmcache/venv/bin/python -c 'import lmcache, glide_sync' && echo PASS   # then the feature checks
```

## Start the server

`<private_ip>` is the private VPC IP of the host, or `127.0.0.1` when the engine is on the same host. You MUST NOT bind to `0.0.0.0`. The rule for the bind is in the next section.

### API key and metrics endpoint

This section is the one home for LMCache server exposure and the metrics endpoint.

- If `lmcache server --help` lists `--api-key-file`, use it. The key then guards the ZMQ and gRPC request channel and the HTTP API (every path except `/` and `/healthcheck`, so also `/metrics`). Without it, any process that reaches the port can store, read, or delete KV data.
- The request channel (ZMQ or gRPC) has no TLS. Bind `--host` to `<private_ip>` only with `--api-key-file`, and the other security groups of the host MUST NOT allow port 5555. Without `--api-key-file`, `--host` MUST be `127.0.0.1`.
- Metrics are at `/metrics` on the HTTP API (`--http-host`, `--http-port`, default `127.0.0.1:8080`); `lmcache server` does not open `--prometheus-port`. The HTTP API also serves cache-management calls, so you MUST NOT expose it without authentication: keep it on loopback, or use the key and allow the port only from the scraper (`Authorization: Bearer <key>`).

```bash
# Secret step (see "Secret steps" in elasticache-setup.md)
sudo install -d -m 0750 -o root -g lmcache /etc/lmcache
head -c 32 /dev/urandom | base64 | tr -d '\n' | sudo tee /etc/lmcache/api.key >/dev/null
sudo chown root:lmcache /etc/lmcache/api.key && sudo chmod 0440 /etc/lmcache/api.key

# Read /metrics. The header goes through stdin (curl -H @-), so the key is in no argv.
# Without an API key, drop the sudo part and the -H @-.
lmc_metrics() { sudo sh -c 'printf "Authorization: Bearer %s\n" "$(cat /etc/lmcache/api.key)"' \
  | curl -sf --max-time 10 -H @- http://127.0.0.1:8080/metrics; }
```

The engine reads the key from `LMCACHE_API_KEY_FILE=/etc/lmcache/api.key`, so the engine user MUST be able to read it: `sudo usermod -aG lmcache <engine-user>` and restart the engine (group changes apply to new processes only), or give it a 0400 copy.

### Launcher (password from Secrets Manager)

Other users can read a command line with `ps` or from `/proc`, so the password MUST NOT be in argv or on disk. The launcher reads the secret in-process, builds the `--l2-adapter` JSON, and calls the entry point `lmcache.cli.main.main` (change the import if the version names another). You MUST set both REQUIRED values; it does not run until you do.

```python
#!/usr/bin/env python3
# lmcache-launch.py: start the LMCache server without the password in argv.
import json
import sys

import boto3
from lmcache.cli.main import main  # the `lmcache` console-script entry point

# REQUIRED: the result of the credential-order check (troubleshooting.md,
# "WRONGPASS when LMCache connects"). Check again after every upgrade.
SWAP_CREDENTIALS = <True-or-False>
# REQUIRED: an integer for Option A (volatile-lru), None for Option B (allkeys-lru).
# See elasticache-setup.md, "Eviction policy and TTL".
TTL_SECONDS = <seconds-or-None>

secret = boto3.client("secretsmanager", region_name="<region>").get_secret_value(
    SecretId="<SECRET_ID>"  # see elasticache-setup.md, "Shell setup and helpers"
)["SecretString"]
username, password = "kv-cache-user", secret
if SWAP_CREDENTIALS:
    username, password = password, username

adapter = {
    "type": "valkey",
    "transport": "rdma",
    "cluster_mode": True,
    "startup_nodes": "<elasticache-config-endpoint>:6379",
    "username": username,
    "password": password,
    "tls_enable": True,
    "num_workers": 8,
    "rdma_provider": "efa-direct",
    "rdma_interface": ["<efa-domain-1>", "<efa-domain-2>"],
    "key_prefix": "<model_version_tp_keytype>",
    "max_capacity_gb": 0,
}
if TTL_SECONDS is not None:
    adapter["ttl_seconds"] = TTL_SECONDS
sys.exit(main(["server", *sys.argv[1:], "--l2-adapter", json.dumps(adapter)]))
```

Install them as root, so the service user cannot change them:

```bash
sudo install -m 0755 -o root -g root lmcache-launch.py /opt/lmcache/lmcache-launch.py
sudo chown -R root:root /opt/lmcache/venv
```

### systemd unit

Run the launcher as the service user, not root. It reads the secret through the instance role ([client-setup.md](references/client-setup.md#instance-role-permission-for-the-cache-secret)), which every process on the host can use: require IMDSv2 with hop limit 1 when containers must not reach it.

```ini
# /etc/systemd/system/lmcache.service
[Unit]
Description=LMCache MP server
After=network-online.target lmcache-hugepages.service
Wants=network-online.target
Requires=lmcache-hugepages.service

[Service]
User=lmcache
Environment=PYTHONHASHSEED=0
LimitMEMLOCK=infinity
ExecStart=/usr/bin/numactl --cpunodebind=<node> --preferred=<node> \
    /opt/lmcache/venv/bin/python /opt/lmcache/lmcache-launch.py \
    --host 127.0.0.1 --port 5555 --l1-size-gb <l1_size_gb> \
    --no-l1-use-lazy --l1-use-hugepages --eviction-policy LRU \
    --chunk-size 256 --hash-algorithm sha256_cbor \
    --supported-transfer-mode auto \
    --api-key-file /etc/lmcache/api.key
Restart=on-failure
RestartSec=10
NoNewPrivileges=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
```

- Install `numactl` first ([NUMA placement](#numa-placement)).
- `--host 127.0.0.1` is the default for the co-located layout (engine and LMCache on the same host). Change to `<private_ip>` only when the engine is on a separate host, and only with `--api-key-file`.
- Remove `--l1-use-hugepages` and the `lmcache-hugepages.service` lines when the tier fits on 4 KiB pages. If the build lacks `--api-key-file`, remove it and follow the bind rule of [API key and metrics endpoint](#api-key-and-metrics-endpoint).
- Add `ProtectSystem=strict` and `ProtectHome=yes` only after a test shows that `/dev/infiniband`, `/dev/nvidia*`, and `/dev/shm` still work.

After the first start, the log MUST NOT contain the password (`get_pw` from [elasticache-setup.md](references/elasticache-setup.md#shell-setup-and-helpers)). If the check finds it, stop LMCache and [rotate the password](references/troubleshooting.md#rotate-the-password):

```bash
# Secret step (see "Secret steps" in elasticache-setup.md). An empty pattern would count 0, so read the secret first.
if get_pw >/dev/null; then n=$(sudo journalctl -u lmcache --no-pager | grep -F -c -f <(get_pw) || true)
  [ "$n" = 0 ] && echo "PASS: no password in the journal" || echo "STOP: password found in $n journal lines"
else echo "STOP: cannot read the secret"; fi
```

### Hugepage reservation at boot

Reserves the pool before LMCache starts after a reboot (`<pages>`, `<node>`: [Registered memory and hugepages](#registered-memory-and-hugepages)):

```ini
# /etc/systemd/system/lmcache-hugepages.service
[Unit]
Description=Hugepages for LMCache L1
Before=lmcache.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'echo <pages> > /sys/devices/system/node/node<node>/hugepages/hugepages-2048kB/nr_hugepages'
ExecStartPost=/bin/sh -c 'test $(cat /sys/devices/system/node/node<node>/hugepages/hugepages-2048kB/free_hugepages) -ge <pages>'

[Install]
WantedBy=multi-user.target
```

### `tcp` and `blob-tcp`

Same launcher: set `"transport"` to `"tcp"` or `"blob-tcp"` (always set it; without it, `tcp` is used), and remove `rdma_provider` and `rdma_interface`. No `--no-l1-use-lazy` or hugepages are needed. Use the access string of the transport ([elasticache-setup.md](references/elasticache-setup.md#users-and-acl-setup)).

## Flag and adapter reference

LMCache server flags:

| Flag | Value | Notes |
|---|---|---|
| `--host`, `--port` | Private IP or `127.0.0.1`, `5555` | Engine request channel. Never `0.0.0.0` |
| `--transport` | `zmq` (default) or `grpc` | Request channel protocol. MUST match the scheme of `lmcache.mp.host` in the engine |
| `--api-key-file` | `/etc/lmcache/api.key` | See [API key and metrics endpoint](#api-key-and-metrics-endpoint) |
| `--l1-size-gb` | About half of the DRAM on the NUMA node of LMCache | Below the pinned-memory limit; much larger than the GPU KV capacity; holds the prefetch of the longest prompt plus pending stores (a nearly full tier cannot stage reads). A few GB is for functional tests only. On `rdma`: [Registered memory and hugepages](#registered-memory-and-hugepages) |
| `--no-l1-use-lazy` | Required for `rdma` | EFA cannot register the unfilled pages of the lazy allocator |
| `--l1-use-hugepages` | `rdma` with a large tier | L1 from the reserved 2 MiB pool. Needs `--no-l1-use-lazy` |
| `--chunk-size` | `256` | You MUST NOT use 1,024. A minimum: the connector can raise it. A prompt shorter than one chunk writes nothing to L2 |
| `--hash-algorithm` | `sha256_cbor` | The same on every LMCache server. MUST NOT be `builtin` |
| `--eviction-policy` | `LRU` | L1 eviction. `noop` with the `skip_l1` policies |
| `--eviction-trigger-watermark`, `--eviction-ratio` | `0.8`, `0.2` (defaults) | Start here. A lower watermark (for example 0.6) is tuning: measure it |
| `--supported-transfer-mode` | `auto` | Required when SGLang uses the server |
| `--separate-object-groups` | Hybrid models | See [optimization.md](references/optimization.md#hybrid-models-attention--recurrent-layers) |
| `--http-host`, `--http-port` | `127.0.0.1`, `8080` (defaults) | HTTP API and `/metrics`. Keep on loopback |
| `--isolated-ipc` | Containers without a shared IPC namespace | Also `lmcache.mp.isolated_ipc` on vLLM (or share the host IPC namespace) |

Adapter fields (in the `--l2-adapter` JSON with `"type": "valkey"`):

| Field | Default | Notes |
|-------|---------|-------|
| `startup_nodes` | (required) | Configuration endpoint, `"host:port"` |
| `cluster_mode` | `false` | MUST be `true` |
| `transport` | `"tcp"` | `"tcp"`, `"blob-tcp"`, or `"rdma"`. Always set it |
| `tls_enable` | `false` | MUST be `true` |
| `username`, `password` | `""` | Set by the launcher |
| `num_workers` | `8` | Worker threads, each with a valkey-glide client: the I/O concurrency. More give throughput but raise server latency. Use fewer when the [registered-memory rule](#registered-memory-and-hugepages) fails, the host is small (for example g6: 2-4, because the threads take CPU and GIL time from vLLM), hosts × workers × shards near the Valkey connection limit, or few requests are in flight |
| `key_prefix` | `""` | MUST NOT be empty or contain `@`. One per model, model version, TP layout, KV dtype, and key type; `tcp` MUST NOT share one with `rdma` or `blob-tcp` |
| `ttl_seconds` | (none) | Required for Option A, optional for Option B ([elasticache-setup.md](references/elasticache-setup.md#eviction-policy-and-ttl)) |
| `max_capacity_gb` | `0` | Keep `0`. You MUST NOT combine LMCache-side eviction with node eviction or TTL. > 0 only when one LMCache writer owns the cluster |
| `request_timeout`, `connection_timeout` | `5.0`, `10.0` | Seconds per request, and for the first connection |
| `rdma_provider` | `"efa-direct"` | `rdma` only. `"tcp"` is the libfabric software provider, for development only |
| `rdma_interface` | (unset) | `rdma` only. One domain, or a JSON list (not a comma-separated string): a `domain:` value of `/opt/amazon/efa/bin/fi_info -p efa -f efa-direct` (for example `rdmap79s0-rdm`). List the devices on the server's NUMA node (LMCache does not select by NUMA); make `num_workers` a multiple of the list length. Unset: the first domain |

## Registered memory and hugepages

This section is the one home for the registered-memory rules.

- On `rdma`, each worker registers the whole L1 on its device. On 4 KiB pages, (`num_workers` / devices in `rdma_interface`) × `--l1-size-gb` MUST stay below the device `max_mr_size` (`ibv_devinfo -v | grep max_mr_size`). Example: `max_mr_size` 384 GiB and 8 workers on one device: L1 below 48 GiB; a 128 GiB L1 allows at most 2 workers per device.
- For a larger tier, back L1 with 2 MiB hugepages (`--l1-use-hugepages --no-l1-use-lazy`). Keep `--l1-size-gb` below the host's pinned-memory limit also with hugepages.
- The memlock limit of the service MUST be unlimited ([client-setup.md](references/client-setup.md#memlock-limits)).
- Over either limit, LMCache stops at start with `Registering the L1 arena (<n> MiB) with the fabric failed`.
- Reserve `<pages>` = `--l1-size-gb` × 512 (2 MiB pages per GiB) on the NUMA node of the EFA devices, soon after boot (free memory fragments), with the [boot unit](#hugepage-reservation-at-boot); its `ExecStartPost` checks that `free_hugepages` is at least `<pages>`. On a host with one NUMA node, `vm.nr_hugepages` in `/etc/sysctl.d/` also works. LMCache stops at start if the pool is short.

## NUMA placement

Pin only the LMCache server to the NUMA node of its EFA devices (`numactl` in the unit; `--preferred` spills to other nodes when full), and reserve the hugepage pool there. You MUST NOT start `lmcache server` directly with `--l2-adapter`: that puts the password in argv. Node of each device:

```bash
for d in /sys/class/infiniband/*; do echo "$(basename $d) numa_node=$(cat $d/device/numa_node)"; done
```

You MUST NOT bind vLLM with `--membind` or `--cpunodebind` when its GPUs are on more than one NUMA node (for example, TP8 on an 8-GPU server). Run one LMCache server per NUMA node only when the GPU server runs one vLLM replica per node; then give each server only the devices of its node.

## Connect vLLM

Start vLLM after the LMCache server:

```bash
PYTHONHASHSEED=0 LMCACHE_API_KEY_FILE=/etc/lmcache/api.key vllm serve <model> \
    --host 127.0.0.1 --port 8000 \
    --enable-prefix-caching \
    --kv-transfer-config '{
        "kv_connector": "LMCacheMPConnector",
        "kv_connector_module_path": "lmcache.integration.vllm.lmcache_mp_connector",
        "kv_role": "kv_both",
        "kv_load_failure_policy": "<recompute-or-fail>",
        "kv_connector_extra_config": {
            "lmcache.mp.host": "tcp://<lmcache-server-host>",
            "lmcache.mp.port": 5555
        }
    }'
```

- `kv_connector_module_path` loads the connector of the installed LMCache (same version as the server).
- The `lmcache.mp.host` scheme selects the request channel: `tcp://` for ZMQ, `grpc://` for gRPC (server: `--transport grpc`). It does not change the L2 transport.
- Every server that shares a cache SHOULD have the same `--kv-cache-dtype` (`fp8` halves the KV bytes but changes numerics: validate accuracy), and MUST have `--enable-prefix-caching` and the same `--gpu-memory-utilization`, `--max-model-len`, and TP. Keep TP at or below the KV head count ([optimization.md](references/optimization.md#kv-bytes-per-token)).
- Set `kv_load_failure_policy` (`recompute` or `fail`) in the JSON, because the default changes between vLLM versions. `recompute` can give wrong output in some cases ([vLLM issue 49250](https://github.com/vllm-project/vllm/issues/49250), [LMCache issue 5653](https://github.com/LMCache/LMCache/issues/5653)). LMCache treats an L2 load failure as a miss, so both recompute whatever the policy ([troubleshooting.md](references/troubleshooting.md#find-l2-errors-at-run-time)).
- Keep the engine's existing `--host`, `--api-key`, TLS, and other exposure flags: the example defaults to `127.0.0.1`. Use `<private_ip>` when a load balancer or router must reach the engine, and pass `--api-key` — the all-traffic security group makes the port reachable across the fleet. Clear inherited `VLLM_*` and `LMCACHE_*` variables, except `VLLM_API_KEY` (vLLM uses it when `--api-key` is absent) and `LMCACHE_API_KEY_FILE`. Under systemd: `After=lmcache.service`, `Requires=lmcache.service`, `Environment=PYTHONHASHSEED=0`.

## Connect SGLang

```yaml
# lmcache_config.yaml
mp_host: <lmcache-server-host>   # grpc://<lmcache-server-host> for gRPC (server: --transport grpc)
mp_port: 5555
```

```bash
PYTHONHASHSEED=0 LMCACHE_API_KEY_FILE=/etc/lmcache/api.key python -m sglang.launch_server \
    --model-path <model> --host 127.0.0.1 --port 30000 \
    --enable-lmcache --lmcache-config-file lmcache_config.yaml
```

- The LMCache server needs `--supported-transfer-mode auto`. Do not set `--hicache-storage-backend` or `--enable-hierarchical-cache` (LMCache replaces HiCache). Keep the engine's existing `--host` and `--api-key`. Use `<private_ip>` when a router must reach the engine, and pass `--api-key` — the all-traffic security group makes the port reachable across the fleet.
- Every server that shares a cache MUST have the same model and revision, TP, KV dtype, page size, LMCache version, and `PYTHONHASHSEED=0`; a difference gives misses or wrong KV with no error. One LMCache server per engine.
- `LMCache MP config must define mp_host` at start: SGLang did not read the file; check the `--lmcache-config-file` path.

## Multi-server deployments

When one server is a bottleneck (large TP), in the vLLM `kv_connector_extra_config`, replace `lmcache.mp.host` and `lmcache.mp.port` with `"lmcache.mp.server_urls": "tcp://<host1>:5555,tcp://<host2>:5555"`. The vLLM world size MUST be divisible by the number of servers; each worker connects only to its assigned server. Multi-server mode supports tensor parallelism only.

## L2 store and prefetch policies

- `--l2-store-policy default` keeps the key in L1 after the L2 store (one replica, or session-affine routing). `skip_l1` deletes it, so L1 is only a write buffer; pair with `--eviction-policy noop` (small L1, or routing that sends returning requests elsewhere).
- `--l2-prefetch-policy default` keeps loaded keys in L1. `skip_l1` deletes each after its reader finishes; pair with `--l2-store-policy skip_l1`.

Presets: [optimization.md](references/optimization.md#tuning-presets).

## Start and stop order

- **Start:** start LMCache first. RDMA readiness gate: on `rdma`, the log MUST show `ValkeyRdmaWorkerPool: provider=efa-direct` and `ValkeyL2Adapter ready: transport=rdma` (with workers, cluster mode, TLS, `key_prefix`) before you start the engine. `transport=tcp`, or no such lines: wrong data path; stop and check the adapter config.

  ```bash
  sudo journalctl -u lmcache --no-pager | grep -E 'ValkeyRdmaWorkerPool: provider=|ready: transport='
  ```

- **Stop:** stop the engine first. Wait (at most 5 minutes) until no `lmcache_mp_num_inflight_l2_stores` sample is above 0, then stop LMCache. The series is absent when nothing is in flight; it updates about every 10 s, so wait 15 s first:

  ```bash
  # Reads /metrics with the API key (see "Secret steps" in elasticache-setup.md)
  inflight_done() { local m; m=$(lmc_metrics) || return 1
    ! printf '%s\n' "$m" | grep -Eq '^lmcache_mp_num_inflight_l2_stores(\{[^}]*\})? [1-9]'; }
  sleep 15; retry 60 5 inflight_done || echo "STOP: L2 stores still in flight (or /metrics unreadable)"
  ```

- After a node replacement, confirm one RDMA transfer before traffic.

## Before production traffic

This is the end-to-end L2 read proof. A repeat on the same server hits the GPU prefix cache or L1, so the test restarts both.

1. Send prompts longer than `--chunk-size` (for example 1,000 tokens or more), at temperature 0. LMCache stores them in L2.
2. Restart vLLM and the LMCache server in the [start and stop order](#start-and-stop-order). L0 and L1 are now empty.
3. Send the same prompts. Pass only if `lmcache_mp_lookup_hit_l2_tokens_total` grows ([optimization.md](references/optimization.md#lmcache-metrics)), and, summed over every primary, `largeobj_rdma_read_bytes` (stores) and `largeobj_rdma_write_bytes` (loads) are both above 0 (`on_primaries INFO largeobj`, [elasticache-setup.md](references/elasticache-setup.md#verify-the-cluster)). Record the outputs.
4. Repeat steps 2 and 3. The two loaded-KV runs MUST give the same output.

Loaded KV can differ from computed KV on a few prompts, also with the GPU prefix cache alone: compare with a loaded-KV reference on the same host.

The hard gate is 0 integrity errors: `largeobj_crc_mismatch` = 0 on every primary, and no `Valkey SET failed`, `Valkey GET failed`, or `size mismatch` lines in the LMCache log ([troubleshooting.md](references/troubleshooting.md#find-l2-errors-at-run-time)). Record the LMCache, valkey-glide-sync, and engine versions that passed, and run this test again after each upgrade.
