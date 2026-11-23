# Troubleshooting

## Table of contents

- Before you change anything
- Find L2 errors at run time
- LMCache adapter construction failures
- RDMA transfer errors
- ElastiCache cluster issues
- Performance issues
- Data loss and recovery

Commands use `get_pw` and `on_primaries` ([elasticache-setup.md](references/elasticache-setup.md#shell-setup-and-helpers)); both are [secret steps](references/elasticache-setup.md#secret-steps).

## Before you change anything

A fix to a user, an access string, a security group, or the cluster changes production state: show it and get approval first. A new cluster follows the Costly actions rule ([SKILL.md](SKILL.md#rules)): it starts empty, and both bill during the move. For `NOPERM`, add only the one command that the error names; you MUST NOT add `+@all` or `~*`.

## Find L2 errors at run time

This section is the one home for run-time errors. Only start-time errors stop LMCache ([next section](#lmcache-adapter-construction-failures)). After the start, every L2 error (`NOPERM`, `OOM`, full disk, timeout, RDMA failure) is a WARNING or ERROR log line and a miss: no retry, the engine recomputes, and the cache looks empty or slow with no crash. Search with `sudo` (without journal access you see no lines):

```bash
sudo journalctl -u lmcache --since -1h --no-pager \
  | grep -E 'Valkey (SET|GET|EXISTS) (failed|dispatch failed|cancelled|unexpected error)|size mismatch|was revoked'
```

| Log line (LMCache 0.5.8rc1 text) | Meaning |
|---|---|
| `Valkey SET failed (batch task_id=<n>, key idx=<n>): <error>` | A store failed: nothing stored, or (on `rdma` and `blob-tcp`) stored but the `EXPIRE` after it failed |
| `Valkey GET failed ...`, `Valkey EXISTS failed ...` | A load or lookup failed. Counted as a miss |
| `Valkey (SET\|GET\|EXISTS) cancelled ...`, `Valkey (GET\|EXISTS) unexpected error ...` | Cancelled (for example at shutdown) or a client failure; a miss |
| `Valkey (SET\|GET\|EXISTS) dispatch failed after <n>/<n> keys ...` (ERROR) | The batch could not be sent; the rest of it counts as failed |
| `Valkey RDMA GET size mismatch for key <key>: landed <n> bytes, expected <n>; treating as miss.` (also `Valkey BLOB.TCP_GET size mismatch`, `Valkey GET size mismatch`) | The stored object has another size: different KV dtype, model, or TP layout under one `key_prefix` |
| `RDMA region on <thread> was revoked (...); registering the L1 arena again` | A transfer ended without a server reply |

`<error>` is the server reply: `NOPERM` → [Authentication failure](#authentication-failure); `OOM` → [ElastiCache cluster issues](#elasticache-cluster-issues); `ERR CRC mismatch` → [CRC mismatch](#err-crc-mismatch-after-transfer); a timeout → [Single shard unavailable](#single-shard-unavailable) or [RDMA transfer fails after successful HELLO](#rdma-transfer-fails-after-successful-hello).

## LMCache adapter construction failures

LMCache does not start until you fix these (connect, AUTH, topology, RDMA registration, `blob-tcp` probe, config checks). Versions and feature checks: [lmcache-setup.md](references/lmcache-setup.md#software-requirements).

| Error at start | Cause | Fix |
|---|---|---|
| `Valkey RDMA support requires the glide_sync module` | `valkey-glide-sync` is not in the LMCache environment | Install it there ([lmcache-setup.md](references/lmcache-setup.md#install)) |
| `The installed valkey-glide-sync has no RDMA API`, `... was built without RDMA support` | Too old, or a source build without RDMA | Install a published wheel with Python RDMA |
| `valkey-glide-sync has RDMA support but libfabric is not available on this machine` | No EFA stack, or libfabric too old | [client-setup.md](references/client-setup.md#efa-driver-stack); then the [glide check](references/lmcache-setup.md#software-requirements) MUST print `True True` |
| `transport must be one of ...` for `rdma` or `blob-tcp` | No such transport in the build | A release that passes the feature check; until then, `tcp` only |
| `transport='blob-tcp' needs the valkey-large-object module, but the server does not know BLOB.INFO` | Not `cache.i8ge.48xlarge`, or Valkey older than 9.1 (the `--loadmodule` hint is for self-managed Valkey) | [elasticache-setup.md](references/elasticache-setup.md#supported-configuration) |
| `key_prefix must not contain '@'` | `@` in the prefix | Choose a prefix without `@` |
| `rdma_interface must be a string, a list, or omitted` | Wrong type (a comma-separated string is one domain name, and the fabric open fails later) | One domain, or a JSON list |
| `Unable to locate credentials`, Secrets Manager `AccessDenied`, KMS `AccessDeniedException` | Role lacks `secretsmanager:GetSecretValue`, or `kms:Decrypt` on the customer managed key | [client-setup.md](references/client-setup.md#instance-role-permission-for-the-cache-secret) |
| Hugepage shortage | Pool below `--l1-size-gb` × 512 pages | [lmcache-setup.md](references/lmcache-setup.md#registered-memory-and-hugepages) |
| `Registering the L1 arena (<n> MiB) with the fabric failed`, `fi_mr_reg: Cannot allocate memory` | (`num_workers` / devices) × `--l1-size-gb` over the device `max_mr_size` on 4 KiB pages, or memlock limited | Fewer workers, smaller L1, more devices in `rdma_interface`, or hugepages ([lmcache-setup.md](references/lmcache-setup.md#registered-memory-and-hugepages)). Check the memlock of the service, not of your shell ([client-setup.md](references/client-setup.md#verify-efa-readiness)) |

### Connection refused or timeout to ElastiCache

Check: the cache group is on the primary interface ([client-setup.md](references/client-setup.md#security-group)); `startup_nodes` is the configuration endpoint; `tls_enable` and `cluster_mode` are `true` (with `false`, `MOVED` replies make every operation a miss); same VPC, and routes allow the traffic.

```bash
timeout 10 openssl s_client -connect <cluster-endpoint>:6379 -servername <cluster-endpoint> -brief </dev/null
```

Timeout: security group, route, or DNS. `Connection refused`: wrong endpoint or port. `Verification: OK`: TLS works; check authentication.

### Authentication failure

`WRONGPASS` or `NOPERM`. Check in order:

1. **Password.** `get_pw | valkey-cli --tls -h <cluster-endpoint> -p 6379 --user kv-cache-user --askpass PING`. `PONG` with `WRONGPASS` in LMCache: see [WRONGPASS when LMCache connects](#wrongpass-when-lmcache-connects). `WRONGPASS` here: the `SecretString` is JSON (store the password alone, [elasticache-setup.md](references/elasticache-setup.md#cache-password-secret)); the secret and the user differ ([Rotate the password](#rotate-the-password)); or the user is `off` or not in the group (checks 2 and 3).
2. **User.** `aws elasticache describe-users --region $AWS_REGION --user-id ${CLUSTER_NAME}-user --query 'Users[0].{Status:Status,Engine:Engine,Auth:Authentication.Type,Access:AccessString}'`: MUST be `active`, `valkey`, `password`.
3. **Group.** `aws elasticache describe-user-groups --region $AWS_REGION --user-group-id ${CLUSTER_NAME}-ug --query 'UserGroups[0].UserIds'` lists the user, and `aws elasticache describe-replication-groups --region $AWS_REGION --replication-group-id $CLUSTER_NAME --query 'ReplicationGroups[0].UserGroupIds'` lists the group.
4. **Access string.** Compare `AccessString` with the table in [elasticache-setup.md](references/elasticache-setup.md#users-and-acl-setup). Frequent errors:
   - `blob-tcp` without `~__lmcache_blob_tcp_probe__`: LMCache does not start.
   - `rdma` or `blob-tcp` with `ttl_seconds` but without `+EXPIRE`: `Valkey SET failed ... NOPERM` on each store, and objects with no TTL. Keys written before the fix still have no TTL ([Diagnose a full cache](#diagnose-a-full-cache)).
   - `tcp` without `+GET +SET`; a key pattern that does not match `key_prefix`.

   With approval, add the missing command — but only a command that appears in the transport's row of the access-string table in [elasticache-setup.md](references/elasticache-setup.md#users-and-acl-setup). You MUST NOT append `+@all`, `~*`, `@read`, `@keyspace`, `@dangerous`, `KEYS`, or `SCAN`. Example: `aws elasticache modify-user --region $AWS_REGION --user-id ${CLUSTER_NAME}-user --append-access-string "+<command>"`.

### WRONGPASS when LMCache connects

This section is the one home for the credential-order check.

**Cause:** the LMCache build passes the user name first, by position, to `ServerCredentials`, but valkey-glide takes the password first (all transports).

**Check** both sides in the LMCache environment (`-A3`, because the arguments can be on separate lines):

```bash
LMCACHE_PY=/opt/lmcache/venv/bin/python
"$LMCACHE_PY" -c 'import inspect, glide_sync; print(inspect.signature(glide_sync.ServerCredentials.__init__))'
grep -n -A3 "ServerCredentials(" "$("$LMCACHE_PY" -c 'import lmcache, os; print(os.path.dirname(lmcache.__file__))')/v1/distributed/l2_adapters/valkey/worker_pool.py"
```

- User name first by position (for example `ServerCredentials(self._username, self._password)`) **and** the signature starts with `password`: swap. Set `SWAP_CREDENTIALS = True` in the launcher.
- Keyword call (`password=...`, `username=...`), or the orders agree: you MUST NOT swap.

Run the check after every LMCache or valkey-glide upgrade, and remove the swap when the call changes to keywords. If you edit the installed source instead, delete the `__pycache__` folders under both `lib` and `lib64` `site-packages`, and repeat the edit after each reinstall.

**Rotate after a WRONGPASS.** Each failed AUTH sent the password as the user name, which `ACL LOG` can record; a swap left after an upgrade does the same. After the fix, [rotate the password](#rotate-the-password).

### Rotate the password

A user can have two passwords, so there is no downtime. Get approval first. Every step is a secret step ([elasticache-setup.md](references/elasticache-setup.md#secret-steps)). Keep each password in a 0600 file, never in argv: run steps 1 to 3 in one subshell, `( umask 077; ...; trap 'rm -f <files>' EXIT ... )`, so the mask does not stay in the shell and the files go away.

1. Write the new password with the `get-random-password ... | tr -d '\n' > <new-file>` line of [elasticache-setup.md](references/elasticache-setup.md#cache-password-secret) (not `create-secret`), and the old one with `get_pw | tr -d '\n' > <old-file>`.
2. Build `{"UserId": "<user-id>", "AuthenticationMode": {"Type": "password", "Passwords": [<old>, <new>]}}` with `jq --rawfile`, and run `aws elasticache modify-user --region $AWS_REGION --cli-input-json file://<file>`.
3. `aws secretsmanager put-secret-value --region $AWS_REGION --secret-id "$SECRET_ID" --secret-string file://<new-file>`.
4. Restart LMCache on every GPU server in the [start and stop order](references/lmcache-setup.md#start-and-stop-order).
5. In a new subshell, build the input from `get_pw` (the secret now holds the new password) as in "Users and ACL setup", and run `modify-user` again with only the new password.

## RDMA transfer errors

### RDMA transfer fails after successful HELLO

**Symptom:** `BLOB.RDMA_HELLO` succeeds (it uses TLS), but the first RDMA transfer fails or stops: the RDMA error counters grow, or the workers stop and TTFT grows (no RDMA timeout).

**Cause:** the self-referencing ingress or egress rule is missing, or the cache security group is not on every EFA interface of the GPU server.

**Fix:** with approval, add the missing rule (`authorize-security-group-ingress` with the same arguments for ingress). The cluster and every GPU server interface MUST use the group ([client-setup.md](references/client-setup.md#security-group)).

```bash
aws ec2 authorize-security-group-egress --region $AWS_REGION --group-id $SG_ID \
    --ip-permissions "IpProtocol=-1,UserIdGroupPairs=[{GroupId=$SG_ID}]"
```

### "ERR CRC mismatch after transfer"

**Cause:** the received bytes do not match the CRC that the client sent with `BLOB.RDMA_SET`, so the module stored nothing. LMCache logs `Valkey SET failed` and does not retry.

**Action:** any increase of `largeobj_crc_mismatch` fails the integrity gate ([lmcache-setup.md](references/lmcache-setup.md#before-production-traffic)). Stop production traffic to this cache, collect the LMCache log and `on_primaries INFO largeobj`, and escalate to AWS Support.

### "ERR no RDMA session (call BLOB.RDMA_HELLO first)"

**Cause:** a GET or SET came before `BLOB.RDMA_HELLO`: the connection was reset, or a replaced node has no session.

**Action:** check `largeobj_rdma_sessions` on every primary and the ElastiCache events for a node replacement. Then, with approval, restart LMCache in the [start and stop order](references/lmcache-setup.md#start-and-stop-order). A restart empties L1.

## ElastiCache cluster issues

### Diagnose a full cache

Each value is for one node, so read every primary with `on_primaries INFO <section>`:

| Section | Field | Read |
|---|---|---|
| `memory` | `maxmemory_policy` | `volatile-lru` (Option A) or `allkeys-lru` (Option B) |
| `stats` | `evicted_keys`, `expired_keys` | Evictions vs TTL expirations |
| `keyspace` | `keys=`, `expires=` | Under `volatile-lru`, `expires` far below `keys` means keys with no TTL |
| `largeobj` | `largeobj_disk_capacity_exceeded`, `largeobj_dram_pool_exhausted`, `largeobj_disk_staging_buffer_exhausted` | Writes refused |

Recovery from keys with no TTL (a new `ttl_seconds` does not change them), with approval: move to Option B if the cluster holds LMCache keys only ([elasticache-setup.md](references/elasticache-setup.md#eviction-policy-and-ttl)), or create a new cluster with the correct option.

| Error | Cause | Action |
|---|---|---|
| `OOM command not allowed when used memory > 'maxmemory'` | The DRAM tier is full and the policy cannot free space | Do the diagnosis. `noeviction`: use Option A or B. `volatile-lru` with no-TTL keys: the recovery above. Eviction runs: the working set is too large; create a new cluster with more shards ([elasticache-setup.md](references/elasticache-setup.md#shard-count-and-capacity)) |
| `OOM command not allowed when used disk space > 'largeobj.disk-maxmemory'` | The NVMe tier is full (capacity set by the node type). Writes fail; reads work | The same diagnosis and actions |
| `ERR disk staging buffer pool exhausted; retry later` | All NVMe staging buffers are in use by reads and writes. Fails at once; LMCache counts a failed store or a miss | Occasional under a burst is expected. If `largeobj_disk_staging_buffer_exhausted` keeps growing, decrease the concurrent writers (`num_workers` × GPU servers), or create a new cluster with more shards |

**Node replacement loses all data.** Expected (no replicas, no durability); the cache warms up again.

## Performance issues

| Symptom | Cause | Check and fix |
|---|---|---|
| The engine does not start, or waits, at connect to LMCache | Bind, port, scheme, key, or version | `--host` is the address the engine uses (`127.0.0.1` is local only); port 5555 open; `tcp://` for `zmq`, `grpc://` for `grpc`; `LMCACHE_API_KEY_FILE` set; SGLang server has `--supported-transfer-mode auto`; same LMCache version in engine and server |
| High TTFT although the cache is populated | Hit rate, errors, AZ, bandwidth, DRAM, or timeouts | L2 share near zero ([optimization.md](references/optimization.md#lmcache-metrics)); [run-time errors](#find-l2-errors-at-run-time); another AZ: cross-AZ round trip, no RDMA ([client-setup.md](references/client-setup.md#same-az-placement)); "More shards needed" ([optimization.md](references/optimization.md#elasticache-metrics-cloudwatch)); low `LargeObjectDRAMHitRate`; on `blob-tcp`, large chunks over the 5 s `request_timeout` (`Valkey GET failed`) |
| L2 stores grow but L2 loads stay near zero | No missed reuse, keys that do not match, or keys gone | On every server: `PYTHONHASHSEED=0` and the same `--hash-algorithm`, `key_prefix`, model path, TP layout, `--kv-cache-dtype` (else `size mismatch`); no short `ttl_seconds`; no `NOPERM`. If all are correct, L2 does not help this workload |
| Long prompts recompute although the cache holds them | L1 is full, so prefetch cannot stage the whole read; `lmcache_mp_l1_allocation_failure_chunks_total{during="l2_prefetch"}` grows | Increase `--l1-size-gb` (within [the registered-memory rules](references/lmcache-setup.md#registered-memory-and-hugepages)), or lower the eviction watermark |
| Active sessions recompute early turns | `EXISTS` does not refresh LRU order | Expected; more capacity delays it |
| High eviction rate with a falling L2 share | Cache too small (evictions alone are normal after it fills) | Separate `evicted_keys` from `expired_keys` on every primary; under shared `allkeys-lru`, check that evicted keys are LMCache keys. `kvtrace simulate` with more `--cache-node-counts` (a lower bound, [cost-assessment.md](references/cost-assessment.md#estimate-with-kvtrace)); then a new cluster with more shards |

### Hit counters look healthy but answers change

1. **Rule out a configuration error first.** Every server that shares a `key_prefix` MUST have the same `--kv-cache-dtype`, model and revision, TP layout, LMCache version, `--hash-algorithm`, and transport family (`tcp` vs module) ([SKILL.md](SKILL.md#rules)). A difference can load KV of another model or layout. Check the log for [run-time errors](#find-l2-errors-at-run-time).
2. **Then:** loaded KV can differ from computed KV on a few prompts (also with the GPU prefix cache alone); this is expected only after step 1 passes.
3. **Action:** do the test in [lmcache-setup.md](references/lmcache-setup.md#before-production-traffic): two loaded-KV runs on the same host MUST give the same output; compare with a loaded-KV reference on the same host, not with computed KV; the hard gate is 0 integrity errors.

## Data loss and recovery

### Single shard unavailable

**Impact:** its keys are lost; its requests fail after `request_timeout` (5 s) as misses, and RDMA transfers in flight can stop, until valkey-glide gets the new topology. Other shards serve.

**Recovery:** ElastiCache replaces the node and the shard warms up. Check the log, and see [no RDMA session](#err-no-rdma-session-call-blobrdma_hello-first).

### Client disconnect during RDMA transfer

The transfer fails as a miss. The next one on that worker registers L1 again (seconds for a large L1).
