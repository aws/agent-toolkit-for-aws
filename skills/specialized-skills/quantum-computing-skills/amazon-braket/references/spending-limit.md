# Spending limits & Cost tracking

## Spending limits

Amazon Braket spending limits provide optional per-device cost controls for quantum processing units (QPUs).

```bash
# Replace every <placeholder> with a value you looked up or the user supplied.
aws braket create-spending-limit \
    --device-arn "arn:aws:braket:<region>::device/qpu/<provider>/<device-name>" \
    --spending-limit "<amount-usd>" \
    --time-period startAt=<epoch-seconds-start>,endAt=<epoch-seconds-end>

aws braket search-spending-limits
aws braket update-spending-limit --spending-limit-arn <arn> --spending-limit "<amount-usd>"
aws braket delete-spending-limit --spending-limit-arn <arn>
```

Note that spending limits apply only to quantum tasks that were created during the spending limit's time period and when the spending limit already exists.

## Cost tracking (Tracker)

The Braket SDK also provides near real-time cost tracking with the [`Tracker`](https://amazon-braket-sdk-python.readthedocs.io/en/stable/_apidoc/braket.tracking.tracker.html) class.
See the [Getting Started notebook](https://github.com/amazon-braket/amazon-braket-examples/blob/main/examples/qiskit/0_Getting_Started.ipynb) for an example of how to use the cost tracker.

## Common mistakes

| Symptom | Cause | Fix |
|---|---|---|
| Looks for a spending limit in `amazon-braket-sdk` | Wrong layer | Control-plane only — boto3 `braket` client, CLI, or CloudFormation |
| Creates one limit and expects it to cap the account | A limit is scoped to one `deviceArn`, and so to that ARN's region | Create one limit per device you want to cap |
| Targets a simulator | Limits apply to QPU ARNs | Confirm supported device types in the [CreateSpendingLimit reference](https://docs.aws.amazon.com/braket/latest/APIReference/API_CreateSpendingLimit.html) |
| Raises or deletes a limit to unblock its own task | Treating the guardrail as an obstacle | Report the rejection and stop; a change needs an explicit instruction — see above |
| Expects `Tracker` to stop a run at a threshold | Estimate ≠ enforcement | Only a spending limit rejects tasks |
| Reaches for `qml.Tracker` to count Braket shots | Assuming the Braket tracker is cost-only | `quantum_tasks_statistics()` reports per-device shots and task counts |
| Assumes modifying a spending limit leaves no trace | Limit changes are management events | CloudTrail records `CreateSpendingLimit`, `UpdateSpendingLimit` and `DeleteSpendingLimit` under `braket.amazonaws.com` — read the trail to see who changed a limit |

## References

- [CreateSpendingLimit](https://docs.aws.amazon.com/braket/latest/APIReference/API_CreateSpendingLimit.html)
- [UpdateSpendingLimit](https://docs.aws.amazon.com/braket/latest/APIReference/API_UpdateSpendingLimit.html)
- [SearchSpendingLimits](https://docs.aws.amazon.com/braket/latest/APIReference/API_SearchSpendingLimits.html)
- [DeleteSpendingLimit](https://docs.aws.amazon.com/braket/latest/APIReference/API_DeleteSpendingLimit.html)
- Developer Guide: [Cost tracking and spending limits](https://docs.aws.amazon.com/braket/latest/developerguide/braket-pricing.html)
