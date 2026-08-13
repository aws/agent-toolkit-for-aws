# Pricing

## Where rates come from

The [Braket pricing page](https://aws.amazon.com/braket/pricing/), [AWS Pricing API](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/price-changes.html), and the [bulk price list](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBraket/current/index.csv) are the authoritative sources for current rates — either is acceptable.
See the [AWS Pricing API](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/price-changes.html) for more details about how pricing information is organized with AWS.
Note that the regions supported by the Pricing API are unrelated to the regions Braket supports.

Quote a specific number only if you have read it this session from one of those sources.
If you cannot reach any of them, give the link and the pricing model only — never a number, and never a placeholder such as `$0.00` standing in for a rate you did not look up.

## Pricing model by resource

### QPUs - Per task + per shot

QPU used under the per-task and per-shot model charge using two distinct pricing products for every task, and each pricing product has its own `productFamily` value.
Both must be included when reasoning about task pricing.

- Quantum tasks created outside of a hybrid job use the `"Quantum Task"` (per-task fee) and `"Quantum Task-Shot"` (per-shot fee) `productFamily` values.
- Quantum tasks created associated with a hybrid job use the `"Braket Managed Jobs QPU Task"` (per-task fee) and `"Braket Managed Jobs QPU Task Shot"` (per-shot fee) `productFamily` values.

CLI examples:
```bash
# Fetch names of QPUs
# QPU names may differ between `SearchDevices` and the Pricing API, so look them up here before getting the corresponding pricing products
aws pricing get-attribute-values --service-code AmazonBraket \
    --attribute-name devicename --region us-east-1

# Prices nest under `terms.OnDemand.*.priceDimensions.*.pricePerUnit.USD`
# Fetch details about pricing products
aws pricing get-products --service-code AmazonBraket --region us-east-1 \
    --filters 'Type=TERM_MATCH,Field=devicename,Value=<devicename-from-previous-command>' \
              'Type=TERM_MATCH,Field=productFamily,Value=Quantum Task-Shot'
```

The price list contains retired devices, so you should check a device's status before attempting to use it.

### On-demand simulators — by duration
On-demand simulators bill by **simulation duration** only with a **minimum charge per task**, under a single `productFamily = "Simulator Task"` (per minute).
Simulators are absent from `devicename` and share that one family, so they are identified by the `usagetype` suffix instead.

CLI examples:
```bash
# Fetch simulator usage types
aws pricing get-attribute-values --service-code AmazonBraket \
    --attribute-name usagetype --region us-east-1 \
    --query "AttributeValues[?contains(Value, 'Completed-Task-ExecutionDuration')].Value"

# Fetch details about one simulator's pricing product
aws pricing get-products --service-code AmazonBraket --region us-east-1 \
    --filters 'Type=TERM_MATCH,Field=usagetype,Value=<usagetype-from-previous-command>'
```

### Local simulators — free
`LocalSimulator` backends in the Braket SDK run on your own machine/instance at no additional charge.

### Hybrid jobs — instance + tasks
A hybrid job bills **classical instance time** (`productFamily = "Braket Managed Jobs Instance"`, per minute) and job storage (`productFamily = "Braket Managed Jobs Volume"`, GB-month) **plus** any quantum task charges. A task on an on-demand simulator inside a job bills under `productFamily = "Braket Managed Jobs Simulator Task"` (per minute).
Classical instance rates can be found in the Hybrid Jobs tab of the Braket pricing page.
An **embedded** simulator inside the job incurs no separate task charge — only the instance time.

### Reservations (Braket Direct) — hourly
Reserved device access is billed **hourly** (1-hour increments) instead of per-task/per-shot, under `productFamily = "Quantum Reservation"` (per hour).
During a reservation, tasks and jobs submitted WITH the reservation ARN incur no additional charge.
Other resources, like S3 buckets, managed notebook compute, or tasks submitted WITHOUT the reservation ARN are billed at on-demand rates.
Learn more about reservations [here](https://docs.aws.amazon.com/braket/latest/developerguide/braket-reservations.html).

### Managed notebooks — SageMaker-billed
A Braket managed notebook is a SageMaker notebook instance, so compute and storage are billed by SageMaker.
Refer to SageMaker documentation for further details.

## Common mistakes

| Symptom | Cause | Fix |
|---|---|---|
| Says simulators bill per task/circuit | Wrong model | On-demand simulators bill by **duration** (per minute, min per task) |
| Writes a rate of `$0.00`, or reports only one of a QPU's two rates | A QPU has **both** a per-task and a per-shot rate, in separate Pricing API product families | If you found one rate you have not finished looking. Never write a placeholder for a rate you did not read, and heed a pagination warning instead of reporting a truncated result |
| Uses `deviceCost` from GetDevice as the bill | Not authoritative for billing | Use the pricing page or the AWS Pricing API |

## References
- Amazon Braket pricing https://aws.amazon.com/braket/pricing/
- Amazon SageMaker pricing https://aws.amazon.com/sagemaker/pricing/
- Amazon Braket reservations https://docs.aws.amazon.com/braket/latest/developerguide/braket-reservations.html
- Amazon Braket developer guide https://docs.aws.amazon.com/braket/latest/developerguide/what-is-braket.html
- AWS Billing user guide for pricing-related APIs (including regions supported) https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/price-changes.html
- AWS CLI https://docs.aws.amazon.com/cli/latest/reference/pricing/
- Boto3 https://docs.aws.amazon.com/boto3/latest/reference/services/pricing.html