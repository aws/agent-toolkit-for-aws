<!-- markdownlint-disable MD013 -->

# Pulse control

Pulses are the analog signals that control the qubits in a quantum computer. With
certain devices on Amazon Braket, you can access the pulse control feature to
submit circuits using pulses. You can access pulse control through the Braket
SDK, using OpenQASM 3.0, or directly through the Braket APIs.

Support for pulse control varies across devices, so check for support by first doing:

```python
from braket.aws import AwsDevice

device = AwsDevice("<device-arn>")

getattr(device.properties, "pulse", None) is not None  # True if the device supports pulse control
```

For terminology and instructions on pulse controls with code snippets, see [Pulse control on Amazon Braket](https://docs.aws.amazon.com/braket/latest/developerguide/braket-pulse-control.html).
A tutorial with a working example can be found at [Working with Hello Pulse](https://docs.aws.amazon.com/braket/latest/developerguide/braket-hello-pulse.html).
The API reference for pulse control in the Braket SDK can be found at [braket.pulse](https://amazon-braket-sdk-python.readthedocs.io/en/stable/_apidoc/braket.pulse.html).

## Native gates using pulses

Native gates are represented on some devices in terms of a gate name, a qubit set, and a pulse sequence that performs the operation on the device.

For working with native gates using pulses, see [Accessing native gates using pulses](https://docs.aws.amazon.com/braket/latest/developerguide/braket-native-gate-pulse.html).

Support for pulse control varies across devices, so check for supported gates and calibrations by first doing:

```python
from braket.aws import AwsDevice

device = AwsDevice("<device-arn-that-supports-pulse-control>")

calibrations = device.gate_calibrations
```

Hardware providers periodically calibrate the QPU, often more than once a day.
The Braket SDK enables you to obtain the latest gate calibrations:

```python
device.refresh_gate_calibrations()
```

For an end-to-end working example, use [Working with Hello Pulse](https://docs.aws.amazon.com/braket/latest/developerguide/braket-hello-pulse.html) or the [Amazon Braket pulse-control notebook examples](https://github.com/amazon-braket/amazon-braket-examples/tree/main/examples/pulse_control).
For native-gate-specific guidance, see [Accessing native gates using pulses](https://docs.aws.amazon.com/braket/latest/developerguide/braket-native-gate-pulse.html).

## References

- [Pulse Control docs](https://docs.aws.amazon.com/braket/latest/developerguide/braket-pulse-control.html)
- [Notebook examples with pulse control](https://github.com/amazon-braket/amazon-braket-examples/tree/main/examples/pulse_control)
- [Pulse module API in Braket SDK](https://amazon-braket-sdk-python.readthedocs.io/en/stable/_apidoc/braket.pulse.html)
- [Gate calibrations API in Braket SDK](https://amazon-braket-sdk-python.readthedocs.io/en/stable/_apidoc/braket.circuits.gate_calibrations.html)
