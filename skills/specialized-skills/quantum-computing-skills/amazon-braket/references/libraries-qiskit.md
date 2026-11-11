<!-- markdownlint-disable MD013 -->

# qiskit-braket-provider

The `qiskit-braket-provider` package presents Braket devices as Qiskit backends.

Documentation index: [qiskit-braket-provider documentation](https://qiskit-braket-provider.readthedocs.io/en/stable/)

## Running on Braket

Use `BraketSampler` and `BraketEstimator` in place of Qiskit's `Sampler` and `Estimator` primitives to execute on Braket.
Both primitives require targets with program-set support; see [program-sets.md](./program-sets.md).
Ordinary quantum tasks can be submitted by obtaining a backend from `BraketProvider` and calling `backend.run(...)`.

## Example notebooks

### Getting started and running circuits

- Provider setup and first Braket run —
  [Getting started with the Qiskit Braket provider](https://github.com/amazon-braket/amazon-braket-examples/blob/main/examples/qiskit/0_Getting_Started.ipynb)
- Circuit submission, transpilation, and job retrieval —
  [How to run circuits on Braket devices](https://github.com/amazon-braket/qiskit-braket-provider/blob/main/docs/how_tos/1_how_to_run_circuits_on_braket_devices.ipynb)

### Compilation and format conversion

- Compile Braket circuits through Qiskit with `to_braket` and `to_qiskit` —
  [Compilation with the Qiskit Braket provider](https://github.com/amazon-braket/amazon-braket-examples/blob/main/examples/qiskit/1_Compilation_with_the_Qiskit_Braket_provider.ipynb)
- Device-aware transpilation with targets, qubit labels, optimization levels,
  basis gates, and pass managers —
  [Qiskit-Braket provider transpilation tutorial](https://github.com/amazon-braket/qiskit-braket-provider/blob/main/docs/tutorials/5_tutorial_transpilation.ipynb)

### Braket-native primitives

- Run Qiskit estimator and sampler workloads with Braket program sets —
  [Braket-native primitives](https://github.com/amazon-braket/amazon-braket-examples/blob/main/examples/qiskit/8_Braket_Native_Primitives.ipynb)

### Specialized workflows

- Mid-circuit measurement and conditional operations —
  [Dynamic circuits with the Qiskit Braket provider](https://github.com/amazon-braket/amazon-braket-examples/blob/main/examples/experimental_capabilities/dynamic_circuits/4_Dynamic_Circuits_with_Qiskit_Braket_Provider.ipynb)
- Run Qiskit workloads inside Braket Hybrid Jobs —
  [How to run a Qiskit Hybrid Job](https://qiskit-braket-provider.readthedocs.io/en/stable/how_tos/3_how_to_qiskit_hybrid_job.html)

## Gotchas

- Use one `shots` value for every pub in a `BraketSampler` call and one
  `precision` value for every pub in a `BraketEstimator` call. Qiskit's own pubs
  accept per-pub values, but the Braket primitives raise `ValueError` for a mixed
  call.
- Express `qiskit-ionq` native gate angles in turns, as IonQ defines them
  ([IonQ native gates](https://docs.ionq.com/features/getting-started-with-native-gates)).
  The provider multiplies each value by 2π
  ([`gate_mappings.py`](https://github.com/amazon-braket/qiskit-braket-provider/blob/761fc3a48342315894317e40af4bfcde72eb8395/qiskit_braket_provider/providers/gate_mappings.py#L134-L139)), because the Braket native gates take radians (for example, [`GPi`](https://amazon-braket-sdk-python.readthedocs.io/en/stable/_apidoc/braket.circuits.gates.html#braket.circuits.gates.GPi)).
- Mid-circuit measurement and conditional operations use dynamic circuits,
  which are an experimental capability.
  See [Dynamic circuits with the Qiskit Braket provider](https://github.com/amazon-braket/amazon-braket-examples/blob/main/examples/experimental_capabilities/dynamic_circuits/4_Dynamic_Circuits_with_Qiskit_Braket_Provider.ipynb) and [experimental-capabilities.md](./experimental-capabilities.md) for how to enable and use them.

## References

- Provider documentation:
  - [qiskit-braket-provider](https://qiskit-braket-provider.readthedocs.io/en/stable/)
  - [Quickstart guide](https://qiskit-braket-provider.readthedocs.io/en/stable/quickstart_guide.html)
  - [Installation guide](https://qiskit-braket-provider.readthedocs.io/en/stable/installation_guide.html)
  - [Providers API reference](https://qiskit-braket-provider.readthedocs.io/en/stable/apidocs/providers.html)
  - [Tutorial: Braket-native primitives](https://qiskit-braket-provider.readthedocs.io/en/stable/tutorials/6_tutorial_primitives.html)
  - [How-to: verbatim circuits](https://qiskit-braket-provider.readthedocs.io/en/stable/how_tos/4_how_to_verbatim_circuits.html)
- Source and packaging:
  - [GitHub repository](https://github.com/amazon-braket/qiskit-braket-provider)
  - [PyPI project](https://pypi.org/project/qiskit-braket-provider/)
- Developer guide:
  - [Verbatim compilation](https://docs.aws.amazon.com/braket/latest/developerguide/braket-openqasm-verbatim-compilation.html)
  - [Running multiple programs](https://docs.aws.amazon.com/braket/latest/developerguide/braket-batching-tasks.html)
- Upstream:
  - [Qiskit primitives](https://docs.quantum.ibm.com/api/qiskit/primitives)
  - [`EstimatorPub`](https://docs.quantum.ibm.com/api/qiskit/qiskit.primitives.EstimatorPub)
- Local references:
  - [PennyLane plugin](./libraries-pennylane.md)
  - [Devices](./devices.md)
  - [Program sets](./program-sets.md)
