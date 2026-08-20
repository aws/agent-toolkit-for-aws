# Devices

## Related references

For pricing see [pricing.md](pricing.md) — rates differ per device, so a device choice is also a cost choice; for submitting work as a program set (many programs in one task) see [program-sets.md](program-sets.md); for cost guardrails see [spending-limit.md](spending-limit.md).

## Device status

The ONLINE, OFFLINE, and RETIRED statuses have different semantics:

- **ONLINE** — usable now, subject to its availability window.
- **OFFLINE** — temporarily unusable; task creation is rejected.
- **RETIRED** — permanently unusable. RETIRED devices will still be returned successfully by `GetDevice` and `SearchDevices`.

## How to query devices

Prefer the SDK — it applies filters client-side, performs region fan-out, and other niceties.

| Task | Braket Python SDK (preferred) | AWS CLI (portable) |
|---|---|---|
| Discover and filter devices | `AwsDevice.get_devices(statuses=["ONLINE"], types=["QPU"])` — filters are ANDed; also `arns`, `names`, `provider_names`, `order_by` | `aws braket search-devices --filters '[]' --region <region>` then filter client-side; the API only supports `deviceArn` as filter |
| One device | `AwsDevice(arn)` | `aws braket get-device --device-arn <arn> --region <region>` |
| Read a field | `device.name`, `device.status`, `device.type`, `device.is_available` | `aws braket get-device --device-arn <arn> --region <region> --query '{name:deviceName,status:deviceStatus,type:deviceType}'` |
| Read capabilities | `device.properties` — already a parsed object | `aws braket get-device --device-arn <arn> --region <region> --query 'deviceCapabilities' --output text \| jq '.paradigm.qubitCount, (.action \| keys)'` — a JSON **string**, parse before reading |

Reference docs for correct usage:

- Braket Python SDK — [`AwsDevice`](https://amazon-braket-sdk-python.readthedocs.io/en/latest/_apidoc/braket.aws.aws_device.html) (`AwsDevice.get_devices`, `AwsDevice.properties`)
- AWS CLI — [`braket search-devices`](https://docs.aws.amazon.com/cli/latest/reference/braket/search-devices.html), [`braket get-device`](https://docs.aws.amazon.com/cli/latest/reference/braket/get-device.html)
- boto3 `braket` client — [`search_devices`](https://docs.aws.amazon.com/boto3/latest/reference/services/braket/client/search_devices.html), [`get_device`](https://docs.aws.amazon.com/boto3/latest/reference/services/braket/client/get_device.html)
- API — [SearchDevices](https://docs.aws.amazon.com/braket/latest/APIReference/API_SearchDevices.html), [GetDevice](https://docs.aws.amazon.com/braket/latest/APIReference/API_GetDevice.html)

## Reading GetDevice

Warning: GetDevice responses are large (10–30 KB per device, mostly `deviceCapabilities`). Do NOT dump the full response into your context — extract only the fields you need. Preferred approaches:

- **SDK:** `device = AwsDevice(arn); device.properties.<path>` (already parsed, access fields directly)
- **AWS CLI + jq:** `aws braket get-device --device-arn <arn> --region <region> --query 'deviceCapabilities' --output text | jq '<path to fields you need>'`

The `deviceCapabilities` field in GetDevice contains all information about a device, like whether it can run program sets, whether it can run OpenQASM gate model programs, etc.
`deviceCapabilities` is returned as a **JSON-encoded string** — parse it before reading (the SDK does this for you via `AwsDevice.properties`).
Inspect `deviceCapabilities` for all relevant fields — action types, `paradigm.qubitCount`, `service.shotsRange`, connectivity, etc. — no matter the device type.
Simulators and QPUs alike populate these fields (e.g. SV1 reports its qubit cap at `paradigm.qubitCount`).
Do not skip a field or substitute null based on assumptions about what a device type "has" — read the payload, and only report a field as missing after actually checking it.

For field **meanings, types, and constraints**, consult the `amazon-braket-schemas-python` repository rather than inferring them from memory.
You can do this by:

- **Read from the web** — fetch the module source directly from the [GitHub repository](https://github.com/amazon-braket/amazon-braket-schemas-python)
- **Install the package** — `pip install --upgrade amazon-braket-schemas` (always the latest), then read the module (e.g. `inspect.getsource`).

Resolve the module from the live payload's `braketSchemaHeader`: dots in `name` → folders under `src/braket/`, then append `_v{version}.py`. Example: `braket.device_schema.iqm.iqm_device_capabilities` v1 → `src/braket/device_schema/iqm/iqm_device_capabilities_v1.py`.

## Paradigms

Braket supports two paradigms that are **not mutually compatible**:

- **Gate model** — quantum circuits (gates + measurements). Most QPUs and all managed simulators.
- **AHS (Analog Hamiltonian Simulation)** — continuous Hamiltonian evolution on neutral-atom arrays. Verify which devices support AHS via `GetDevice` (`deviceCapabilities.paradigm`) rather than assuming a fixed device.

A device accepts one paradigm. The most reliable discriminator is the **action map**, which names the program types the device will accept and covers every paradigm with one pattern:

```python
actions = AwsDevice(arn).properties.action        # keyed by DeviceActionType
"braket.ir.openqasm.program"     in actions      # gate-model OpenQASM
"braket.ir.openqasm.program_set" in actions      # program sets
"braket.ir.ahs.program"          in actions      # analog Hamiltonian simulation
```

`deviceCapabilities.paradigm` carries the physical detail behind that choice — gate-model devices have `nativeGateSet`/`connectivity`, AHS devices have `rydberg`/`lattice`. Submitting a program type absent from the action map causes the program to be rejected.

## Availability windows and maintenance

All information regarding interpreting device availability can be found at https://docs.aws.amazon.com/braket/latest/developerguide/braket-task-when.html.
When a QPU is online but outside its `executionWindows` (availability window), it shows `deviceStatus=ONLINE` and queues tasks until the next window.
Unplanned maintenance or other device events shows `deviceStatus=OFFLINE` and attempts to create the quantum task will be rejected.

[Braket device reservations](https://docs.aws.amazon.com/braket/latest/developerguide/braket-reservations.html) may also affect when tasks are able to run against QPUs.

When a target is OFFLINE or RETIRED, suggest an ONLINE alternative that is also within its availability window.
When a target is outside its availability window, suggest an alternative that is.

## Shot and gate limits

| Field | Present on | SDK access → what it returns |
|---|---|---|
| `service.shotsRange` | every device | `AwsDevice(arn).properties.service.shotsRange` → `(shots_lower, shots_upper)` |
| `service.reservationShotsRange` | devices that support reservations and have different shot ranges | `AwsDevice(arn).properties.service.reservationShotsRange` → `(shots_lower, shots_upper)`, or `None` when absent — a reservation can *lower* the floor, here from 100 shots to 1 |

Some providers apply a further shot minimum when error mitigation is enabled, carried under `provider` rather than `service`. See [error mitigation on IonQ](https://docs.aws.amazon.com/braket/latest/developerguide/error-mitigation-ionq.html).

## Simulators

- **On-demand** (managed by Braket). Duration-billed — see https://docs.aws.amazon.com/braket/latest/developerguide/braket-submit-tasks-simulators.html.
- **Local** (in the SDK, no ARN, no charge): `LocalSimulator(backend=...)`, documented at https://amazon-braket-sdk-python.readthedocs.io/en/latest/_apidoc/braket.devices.local_simulator.html and https://docs.aws.amazon.com/braket/latest/developerguide/braket-send-to-local-simulator.html
- **Noise-aware simulation:** applies only to density-matrix backends — `LocalSimulator("braket_dm")` locally, or the managed on-demand DM1. State-vector backends (`braket_sv`, default) cannot express noise models. See the [example notebook](https://github.com/amazon-braket/amazon-braket-examples/blob/main/examples/braket_features/Simulating_Noise_On_Amazon_Braket.ipynb) and [SDK noise modules](https://amazon-braket-sdk-python.readthedocs.io/en/latest/_apidoc/braket.circuits.noise_model.html).
- `shots=0` has special, simulator-specific behavior (analytical/exact mode): the circuit MUST include explicit result types — e.g. `circuit.probability()`, `circuit.state_vector()`, or `circuit.expectation(observable)` — or the simulator raises an error. QPUs always require `shots > 0`. See https://docs.aws.amazon.com/braket/latest/developerguide/braket-submit-tasks-simulators.html and https://docs.aws.amazon.com/braket/latest/developerguide/braket-result-types.html

### Local quantum device emulator

A local quantum device **emulator** is distinct from the local simulator: it applies a real device's validation rules and noise model to a circuit locally, so you can catch a rejection before running on the QPU.
Learn how to use local device emulators at https://docs.aws.amazon.com/braket/latest/developerguide/braket-local-emulator.html.
In the SDK, the emulator obtained from a method on the `AwsDevice` class as [`AwsDevice.emulator()`](https://amazon-braket-sdk-python.readthedocs.io/en/stable/_apidoc/braket.aws.aws_device.html#module-braket.aws.aws_device).

### Experimental capabilities

Some devices expose features behind an explicit opt-in, called "Experimental Capabilities" on Braket.
Learn how to use experimental capabilities at https://docs.aws.amazon.com/braket/latest/developerguide/braket-experimental-capabilities.html.
See example notebooks for experimental capabilities at https://github.com/amazon-braket/amazon-braket-examples/tree/main/examples/experimental_capabilities

## Pulse-level control and gate calibrations

Some QPUs expose pulse-level access — you can inspect the native gate calibrations the QPU uses and attach custom pulse sequences at run time. Support can be determined from `AwsDevice.properties`.
Learn more about pulse control on Amazon Braket at https://docs.aws.amazon.com/braket/latest/developerguide/braket-pulse-control.html.
See example notebooks for pulse control at https://github.com/amazon-braket/amazon-braket-examples/tree/main/examples/pulse_control.

## Common mistakes

| Symptom | Cause | Fix |
|---|---|---|
| Context overflow / huge tool output | Dumped full GetDevice JSON into context | Use `jq` or `--query` to extract only needed fields; never dump raw `deviceCapabilities` |
| Treats "GetDevice succeeded" as "device is available" | Didn't check `deviceStatus` in response | GetDevice returns successfully for RETIRED devices — you MUST check `deviceStatus` in the response is not `RETIRED` (and not `OFFLINE` if you need currently-runnable devices) |
| Emits an ARN for a device that has since retired | Recall from training data | Verify via `SearchDevices` live |
| Misses a device | Queried SearchDevices in only one region | Query all Braket regions |
| `queueSize`/capabilities parse error | Treated string as int / JSON as object | `queueSize` is a string; deviceCapabilities is a json string - `json.loads(deviceCapabilities)` |
| Wrong availability answer | Looked for a maintenance field | Parse `service.executionWindows` |
| Recommends a `LocalSimulator` backend name from memory | Backend names and their support status change between SDK releases | Enumerate what the installed SDK actually offers before choosing: `python -c "from braket.devices import LocalSimulator; print(LocalSimulator.registered_backends())"` or read https://docs.aws.amazon.com/braket/latest/developerguide/braket-submit-tasks-simulators.html |
| Misses a conditional shot minimum (e.g. IonQ error mitigation) | Only read `service.shotsRange` | Check the device's `provider` properties too — a mitigation scheme can raise the minimum above `service.shotsRange` |

## References

- Amazon Braket Python SDK: https://github.com/amazon-braket/amazon-braket-sdk-python
- Amazon Braket supported regions and devices: https://docs.aws.amazon.com/braket/latest/developerguide/braket-devices.html
- Amazon Braket Python schemas: https://github.com/amazon-braket/amazon-braket-schemas-python
- Amazon Braket reservations (scheduling, queuing, exclusive access): https://docs.aws.amazon.com/braket/latest/developerguide/braket-reservations.html
- Restricting access to devices: https://docs.aws.amazon.com/braket/latest/developerguide/restrict-access.html
- IonQ native gates and error mitigation: https://docs.aws.amazon.com/braket/latest/developerguide/error-mitigation-ionq.html
- IonQ native gate set (provider docs): https://ionq.com/docs/getting-started-with-native-gates
- SearchDevices API: https://docs.aws.amazon.com/braket/latest/APIReference/API_SearchDevices.html
- GetDevice API: https://docs.aws.amazon.com/braket/latest/APIReference/API_GetDevice.html
