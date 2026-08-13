# Program sets

## Device support

Program sets run on the local simulator and on all gate-based QPUs. Support is one entry in the device's action map — read it, never guess:

```python
from braket.aws import AwsDevice
from braket.device_schema import DeviceActionType

device = AwsDevice("<device-arn>")
supported = DeviceActionType.OPENQASM_PROGRAM_SET in device.properties.action
```

## Construction

```python
from braket.circuits import Circuit, FreeParameter, Observable
from braket.devices import LocalSimulator
from braket.program_sets import CircuitBinding, ProgramSet

bell = Circuit().h(0).cnot(0, 1)
rotation = Circuit().rx(0, FreeParameter("a")).cnot(0, 1)
entangler = Circuit().h(0).cz(0, 1).ry(1, FreeParameter("phi"))

sweep = CircuitBinding(
    circuit=rotation,
    input_sets={"a": (0.1, 0.2, 0.3)},
)
program_set = ProgramSet([bell, sweep])

# Cartesian product of every circuit under every observable (3 circuits x 2 observables = 6 executables)
# https://amazon-braket-sdk-python.readthedocs.io/en/latest/_apidoc/braket.program_sets.program_set.html#braket.program_sets.program_set.ProgramSet.product
ProgramSet.product([bell, bell, bell], [Observable.Z() @ Observable.I(), Observable.I() @ Observable.X()])

# zip — the nth circuit in circuits list is bound by the nth input_set and the nth observable
# https://amazon-braket-sdk-python.readthedocs.io/en/latest/_apidoc/braket.program_sets.program_set.html#braket.program_sets.program_set.ProgramSet.zip
ProgramSet.zip([rotation, entangler], input_sets=[{"a": 0.1}, {"phi": 0.5}],
               observables=[Observable.Z() @ Observable.I(), Observable.I() @ Observable.X()])

# shots is the TOTAL and must be divisible by program_set.total_executables
task = LocalSimulator().run(program_set, shots=300)
counts = [[r.counts for r in entry] for entry in task.result()]  # indexed result[program][executable]
```

## Contrast with `AwsQuantumTaskBatch`
- Program sets bundle many programs in **one service-side task**, so the per-task fee is only billed once. Supported on all gate-based QPUs.
- [`AwsQuantumTaskBatch`](https://amazon-braket-sdk-python.readthedocs.io/en/latest/_apidoc/braket.aws.aws_quantum_task_batch.html) (`device.run_batch([...], shots=...)`) — many **independent** tasks dispatched in parallel by the SDK, each billed its own per-task fee. Does not require device support.

Always prefer a program set when the device supports it; fall back to `run_batch` if and only if the device doesn't support program sets, as program sets supersede batches in most cases.

## Related references
- [devices.md](devices.md) — device discovery and capabilities
- [pricing.md](pricing.md) — billing models for quantum tasks

## References
- SDK API: 
  - [ProgramSet](https://amazon-braket-sdk-python.readthedocs.io/en/latest/_apidoc/braket.program_sets.program_set.html)
  - [CircuitBinding](https://amazon-braket-sdk-python.readthedocs.io/en/latest/_apidoc/braket.program_sets.circuit_binding.html)
  - [ProgramSetQuantumTaskResult](https://amazon-braket-sdk-python.readthedocs.io/en/latest/_apidoc/braket.tasks.program_set_quantum_task_result.html)
  - [Observables](https://amazon-braket-sdk-python.readthedocs.io/en/latest/_apidoc/braket.circuits.observables.html)
- Notebooks: 
  - [Getting started with program sets](https://github.com/amazon-braket/amazon-braket-examples/blob/main/examples/braket_features/program_sets/01_Getting_started_with_program_sets.ipynb) · 
  - [Expectation value calculations with program sets](https://github.com/amazon-braket/amazon-braket-examples/blob/main/examples/braket_features/program_sets/02_Expectation_value_calculations_with_program_sets.ipynb)
- [Running multiple programs](https://docs.aws.amazon.com/braket/latest/developerguide/braket-batching-tasks.html)
- [GetQuantumTask API](https://docs.aws.amazon.com/braket/latest/APIReference/API_GetQuantumTask.html)
