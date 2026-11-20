# LMI Troubleshooting

## Common Issues

| Issue | Cause | Resolution |
|-------|-------|------------|
| 429 throttles during scale-up | Traffic doubled faster than 5-min scaling window | Increase MinExecutionEnvironments or lower TargetResourceUtilization |
| Function version stuck in PENDING | Instance launches failing | Check `StateReasonCode`: `INSUFFICIENT_CAPACITY` (add instance types/AZs), `INSUFFICIENT_OPERATOR_ROLE_PERMISSIONS` (fix operator role), `CAPACITY_PROVIDER_SCALING_LIMIT_EXCEEDED` (raise `MaxVCpuCount`) |
| Capacity provider seems stuck in CREATING | Not a real state: a provider is Active once `CreateCapacityProvider` succeeds; bad config is rejected in that call | Check the function version's state reason instead; NAT is not required for instances to come up |
| Architecture mismatch error | Function architecture ≠ capacity provider | Align both to arm64 or x86_64 |
| Cannot terminate EC2 instances | LMI instances managed by capacity provider | Delete capacity provider to destroy instances; cannot use EC2 console |
| High CPU, low throughput | Concurrency too high for CPU-bound work | Reduce PerExecutionEnvironmentMaxConcurrency to 1/vCPU |
| Race conditions in production | Code not thread-safe for multi-concurrency | Review with checklist in thread-safety.md |
| Function version not ACTIVE | Fewer than the minimum execution environments ready (3 by default; 1 for GPU functions) | Check the version's `StateReasonCode` (see the PENDING row above) |
| Unexpected 500 errors | Unhandled concurrent access to shared state | Add thread-safe patterns from migration-patterns.md |
| CloudWatch logs or X-Ray traces missing | No route from the subnets to CloudWatch Logs / X-Ray (instance itself stays healthy) | Add a NAT gateway or CloudWatch Logs / X-Ray VPC endpoints |
| High costs despite low traffic | Minimum 3 instances always running | Evaluate if Lambda Event Functions are more cost-effective |
| Slow scale-out or version publish with a large container image | Full image pull on each new instance | Add a SOCI index and point the image URI at the SOCI-indexed tag (configuration-guide.md) |
| SOCI index pushed but startup unchanged | Image URI still points at the original tag, the index is SOCI v1, or the image index is multi-architecture | Use the SOCI-indexed tag, rebuild the index as v2 (`nerdctl image convert --soci`), push a single-architecture image index, then publish a new version |
| First invocations slower after enabling SOCI | Handler reads libraries or files for the first time, so they are fetched during the invocation | Move imports and file reads into init code |

## Debugging Steps

### Throttling Issues

1. Check throttles metric for the reason for throttles

### Function Not Starting

1. Check the function version's state and state reason: `aws lambda get-function-configuration --function-name <fn>:<version> --query '[State,StateReasonCode,StateReason]'`. Act on the `StateReasonCode` (see Common Issues). A capacity provider is Active once `CreateCapacityProvider` succeeds, so its status rarely explains a version that doesn't start.
2. For `INSUFFICIENT_CAPACITY`: allow more instance types, or subnets in more AZs with available IPs
3. For `INSUFFICIENT_OPERATOR_ROLE_PERMISSIONS`: check the operator role has the required permissions
4. NAT and security group egress are not needed for instances to come up; check them only if logs, traces or the function's own outbound calls fail
5. Check for LMI-managed instances:

   ```bash
   aws ec2 describe-instances --filters "Name=tag-key,Values=aws:lambda:capacity-provider" \
     --query "Reservations[].Instances[].{Id:InstanceId,State:State.Name}"
   ```

### Performance Issues

1. Check CloudWatch metrics (5-min intervals): CPU utilization, memory, concurrency/env
2. If CPU > 80%: reduce concurrency or add vCPUs (increase memory with appropriate ratio)
3. If throttles > 1%: increase MinExecutionEnvironments
4. If CPU < 20%: increase concurrency — resources are underutilized
5. For Python: verify 4:1 or 8:1 ratio (GIL limits CPU parallelism)

### Cost Issues

1. Verify instance count matches actual need (not over-provisioned)
2. Check if Savings Plans or RIs are applied to these instances
3. Compare actual costs against the LMI Pricing Calculator
4. If traffic is lower than expected, consider reducing MaxVCpuCount
5. For dev/test: use ExcludedInstanceTypes to avoid expensive instance families
