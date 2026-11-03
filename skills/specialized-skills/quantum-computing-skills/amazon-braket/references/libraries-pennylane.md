<!-- markdownlint-disable MD013 -->

# amazon-braket-pennylane-plugin

The `amazon-braket-pennylane-plugin` package makes Braket devices usable with PennyLane.

Documentation index: [Amazon Braket PennyLane plugin documentation](https://amazon-braket-pennylane-plugin-python.readthedocs.io/en/stable/)

Throughout PennyLane SDK code and documentation, `import pennylane as qp` and `import pennylane as qml` are both valid alias conventions, although `qp` is newer and preferred ([PennyLane announcement](https://pennylane.ai/blog/2026/03/import-pennylane-as-qp-growing-beyond-just-qml/)).

## Running on Braket

Refer to the example notebooks for runnable Braket workflows:

- [Getting started with PennyLane](https://github.com/amazon-braket/amazon-braket-examples/blob/main/examples/pennylane/0_Getting_started/0_Getting_started.ipynb)
- [Parallelized optimization of quantum circuits](https://github.com/amazon-braket/amazon-braket-examples/blob/main/examples/pennylane/1_Parallelized_optimization_of_quantum_circuits/1_Parallelized_optimization_of_quantum_circuits.ipynb)
- [Using PennyLane with Braket Hybrid Jobs](https://github.com/amazon-braket/amazon-braket-examples/blob/main/examples/hybrid_jobs/2_Using_PennyLane_with_Braket_Hybrid_Jobs/Using_PennyLane_with_Braket_Hybrid_Jobs.ipynb)

Use [`qp.execute`](https://docs.pennylane.ai/en/stable/code/api/pennylane.execute.html) to execute a collection of independent tapes. On a device that supports program sets, the plugin submits them as one program set.

The plugin registers four devices:

| Device | Runs on | Program type |
| --- | --- | --- |
| `braket.aws.qubit` | the Braket service | gate model |
| `braket.aws.ahs` | the Braket service | analog Hamiltonian simulation |
| `braket.local.qubit` | the local machine | gate model |
| `braket.local.ahs` | the local machine | analog Hamiltonian simulation |

## References

- Plugin documentation:
  - [Amazon Braket PennyLane plugin](https://amazon-braket-pennylane-plugin-python.readthedocs.io/en/stable/)
  - [Installation](https://amazon-braket-pennylane-plugin-python.readthedocs.io/en/stable/installation.html)
  - [API reference](https://amazon-braket-pennylane-plugin-python.readthedocs.io/en/stable/code.html)
  - [Remote qubit device](https://amazon-braket-pennylane-plugin-python.readthedocs.io/en/stable/devices/braket_remote.html)
  - [Local qubit device](https://amazon-braket-pennylane-plugin-python.readthedocs.io/en/stable/devices/braket_local.html)
  - [Remote AHS device](https://amazon-braket-pennylane-plugin-python.readthedocs.io/en/stable/devices/ahs_remote.html)
  - [Local AHS device](https://amazon-braket-pennylane-plugin-python.readthedocs.io/en/stable/devices/ahs_local.html)
- Source and packaging:
  - [GitHub repository](https://github.com/amazon-braket/amazon-braket-pennylane-plugin-python)
  - [PyPI project](https://pypi.org/project/amazon-braket-pennylane-plugin/)
- Developer guide:
  - [Using PennyLane with Amazon Braket](https://docs.aws.amazon.com/braket/latest/developerguide/hybrid.html)
  - [Quantum task batching and PennyLane](https://docs.aws.amazon.com/braket/latest/developerguide/braket-batching-tasks.html#braket-batching-pennylane)
  - [PennyLane embedded simulators](https://docs.aws.amazon.com/braket/latest/developerguide/pennylane-embedded-simulators.html)
- Upstream:
  - [PennyLane documentation](https://docs.pennylane.ai/)
  - [`qp.Tracker`](https://docs.pennylane.ai/en/stable/code/api/pennylane.Tracker.html)
- Local references:
  - [Qiskit provider](./libraries-qiskit.md)
  - [Devices](./devices.md)
  - [Program sets](./program-sets.md)
  - [Spending limits and cost tracking](./spending-limit.md)
