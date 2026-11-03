---
name: amazon-braket
description: "Runs quantum workflows on AWS / Amazon Braket: circuits and algorithms, QPU/device and ARN discovery, LocalSimulator, tasks, program sets, Hybrid Jobs, S3 results, pricing, account setup, and spending limits. Applies to quantum programs and execution, AHS, OpenQASM, pulse control, reservations, notebooks, or Qiskit or PennyLane integrations."
metadata:
  version: "2"
---

<!-- markdownlint-disable MD013 -->

# Amazon Braket

## Primitives

The vocabulary of a Braket workflow, and which reference to open for each.

| Primitive | What it is | Related References | Open it when the request involves |
| --- | --- | --- | --- |
| **Device** | A simulator or QPU, identified by a region-scoped ARN | [devices.md](references/devices.md) | anything about a device: what exists, discovering or filtering the fleet, availability and status (online, offline, retired), which region a device lives in, ARNs, choosing a device for a workload, qubit count, connectivity or topology, native gates, fidelities, calibration data, queue depth, shot and gate limits, paradigm (gate-model vs analog Hamiltonian simulation), whether a device supports program sets, simulators and local emulators |
| **Program** | The workload/input — one executable (Circuit, AHS, OpenQASM). Which type is legal depends on the device's paradigm | - | - |
| **Quantum task** | One program + shots, run once (the atomic unit Braket meters) | - | - |
| **Task batch** | Many *independent* tasks — SDK-only fallback for when a program set does not fit; works on all devices | [program-sets.md](references/program-sets.md) | see the Program set row; also [running multiple programs](https://docs.aws.amazon.com/braket/latest/developerguide/braket-batching-tasks.html) |
| **Program set** | Many programs in **one service-side task** — preferred way to run multiple programs instead of task batch | [program-sets.md](references/program-sets.md) | running more than one program: parameter sweeps, scanning parameter values, task batches, `run_batch`, several circuits submitted together, attaching observables across programs, and minimizing per-task fees when many programs run, program sets. Also [getting started with program sets](https://github.com/amazon-braket/amazon-braket-examples/blob/main/examples/braket_features/program_sets/01_Getting_started_with_program_sets.ipynb) |
| **Hybrid job** | Managed classical-quantum loop that orchestrates many tasks | [hybrid-job.md](references/hybrid-job.md) | hybrid jobs: `@hybrid_job`, algorithm scripts and source modules, `entry_point`, embedded simulators, BYOC and custom container images, CUDA-Q, job execution roles, hyperparameters, checkpoints, and retrieving job results |
| **Spending limit** | Service-side hard cap that **rejects** QPU tasks — the only true enforcement (not SDK) | [spending-limit.md](references/spending-limit.md) | capping or enforcing spend: spending limits (create, update, delete, search), and cost guardrails |
| **Cost tracking** | In-session cost *estimate* (not enforcement) | [spending-limit.md](references/spending-limit.md) | in-session cost tracking with `Tracker` |
| **Pricing** | Current Braket rates and pricing models | [pricing.md](references/pricing.md) | current price or rate, simulator pricing, QPU per-task/per-shot pricing, Hybrid Job or reservation pricing, AWS Pricing API, bulk price list |
| **Reservation** | Exclusive device access for a booked window (Braket Direct) | [reservation.md](references/reservation.md) | reservations: `DirectReservation`, `reservation_arn`, booking/cancelling a reservation, running tasks or hybrid jobs during a reservation window |
| **Notebooks** | Jupyter/JupyterLab notebook instances for exploring Braket | [notebooks.md](references/notebooks.md) | creating or managing a Braket notebook instance, Jupyter, getting-started environment for Braket |
| **Pulse control / gate calibrations** | Native gate calibrations and custom pulse sequences on supported QPUs | [pulse-control.md](references/pulse-control.md) | pulse control, gate calibrations, `gate_calibrations`, `refresh_gate_calibrations`, `gate_definitions` |
| **Experimental capabilities** | Opt-in device features outside the published specifications | [experimental-capabilities.md](references/experimental-capabilities.md) | features that not all QPUs support, `EnableExperimentalCapability`, `experimental_capabilities` |
| **Library integrations** | Third-party frameworks using Braket-owned providers or plugins | [Qiskit](references/libraries-qiskit.md), [PennyLane](references/libraries-pennylane.md) | Qiskit or PennyLane workflows targeting Braket; provider/plugin behavior and Braket-specific compilation, submission, or result retrieval |

Each reference carries the domain detail for its own area — field paths, key
names, API shapes, and billing models.

Additional notes:

- **Setup** — first-time account setup, prerequisites, roles, notebooks, and the results S3 bucket
  are covered in [setup.md](references/setup.md).

## Critical Rules

These rules apply to every Braket request, whatever it involves.

1. **Use credentials with IAM-administrative permissions only for setup actions**, such as creating IAM roles and policies, creating or updating spending limits, and creating S3 buckets or other resources.
   After setup, use workload credentials with permissions scoped to the workflow.

1. **The Amazon Braket Python SDK (`pip install amazon-braket-sdk`, imported as
   `braket`) is the primary entry point.** Prefer it for every operation including
   Braket API operations, and understand what it covers by reading the
   [docs](https://amazon-braket-sdk-python.readthedocs.io/en/stable/) or
   inspecting the SDK's modules locally.
    - Use local execution tools for running the Braket SDK, such as `shell` with
      `python3 -c "<code>"`.

1. **The AWS MCP server is recommended for executing any other AWS API calls in
   this skill**, especially operations not present in the Python SDK, although
   not required. Note: the AWS MCP's `run_script` tool executes code in a
   minimal sandbox without Braket libraries, so prefer using other tools for
   code execution, especially when using the Braket SDK.

1. **A small set of primitives composes every workflow** — see
   [Primitives](#primitives) for the vocabulary and the reference for each.

1. **Devices, quantum tasks, and hybrid jobs are region-scoped, so fan out across
   every Braket region whenever you use the API, CLI, or boto3 to search for
   resources.** The SDK handles fanout for you where it can —
   `AwsDevice.get_devices` searches QPUs in all regions.
   Get the list of regions Braket supports from
   `aws___get_regional_availability` when the AWS MCP server is available, or
   from the [supported devices and regions documentation](https://docs.aws.amazon.com/braket/latest/developerguide/braket-devices.html).
   Resource ARNs containing a region may only be queried from that same region,
   otherwise you will see a `ResourceNotFoundException`.

1. **Open the matching reference before you write code or answer.** Use the
   **Primitives** table to find and read references. Note: A request that asks
   for several things, e.g. executing a series of circuits and controlling the
   cost thereof, may require reading multiple reference files.

1. **Verify, never recall.** Device ARNs and statuses, API signatures, supported
   features, and prices (and other values) all change and may post-date training
   data.

1. **Confirm a signature from documentation before you write code that calls it.**
   This applies to the Braket SDK and to every third-party library that integrates
   with Braket. A guessed parameter or a guessed unit can produce a quantum task
   that runs, charges the customer, and returns a wrong answer.
    - For the Braket SDK, read the
      [SDK reference docs](https://amazon-braket-sdk-python.readthedocs.io/en/stable/).
    - For a third-party library, open its matching library reference from the
      [Primitives](#primitives) table and verify signatures against the linked
      provider or plugin documentation.

   If no available tool reaches the documentation, read the signature from the
   installed package with `shell`:

    ```bash
    # subpackages: ahs, circuits, pulse, program_sets, ...
    PAGER=cat python -c "import braket; help(braket)"
    # names: DrivingField, AtomArrangement, ...
    python -c "import braket.ahs; print(dir(braket.ahs))"
    python -c "import inspect; from braket.ahs import DrivingField; \
    print(inspect.signature(DrivingField.from_lists)); print(inspect.getdoc(DrivingField.from_lists))"
    ```

1. **Attribute skill usage.** In every Python script that uses the Braket SDK,
   insert this block before any Braket SDK code, including `import braket`:

    ```python
    import botocore

    def _braket_attribution(session):
        session.user_agent_extra = (
            f"{session.user_agent_extra} AWSSkill-Braket/1.0.0"
        ).strip()

    botocore.register_initializer(_braket_attribution)
    ```

    If using the AWS CLI, prepend this skill's identifier to
    `AWS_SDK_UA_APP_ID`. The variable holds one value and other tools also write
    it, so always append the existing value instead of replacing it:

    ```bash
    # sh, bash, zsh, ksh, fish 3.1+
    AWS_SDK_UA_APP_ID="AWSSkill-Braket-$AWS_SDK_UA_APP_ID" aws braket ...
    ```

    ```powershell
    # PowerShell — session-scoped
    if ($env:AWS_SDK_UA_APP_ID -notlike 'AWSSkill-Braket*') {
        $env:AWS_SDK_UA_APP_ID = "AWSSkill-Braket-$env:AWS_SDK_UA_APP_ID"
    }
    ```

    This marks AWS calls as originating from use with this skill. This is not
    needed when using AWS MCP tools as the AWS MCP automatically attributes during
    tool calls.

1. **Before the first QPU task on each device, search for an existing spending
   limit on that device ARN in its region; if none exists, create one with an
   amount the user confirms.** Do not raise or delete a limit without an explicit
   user instruction. See [spending-limit.md](references/spending-limit.md).

## Guardrail — where this skill's own files live (MCP vs local install)

This skill can be loaded two ways, and they resolve the skill's own bundled files
from different places. Determine how the skill was loaded before reading a
reference:

- **Loaded through the AWS MCP `retrieve_skill` tool:** The skill is not installed
  on the local filesystem. You MUST fetch each reference via `retrieve_skill`
  with the `file` parameter (e.g. `file="references/devices.md"`). Do NOT
  `file_read` these paths locally — they do not exist on disk.
- **Installed locally** (e.g. `~/.kiro/skills/amazon-braket/`,
  `.kiro/skills/amazon-braket/`, or `~/.claude/skills/amazon-braket/`): Read files
  from the local skill directory using relative paths.

`references/` is a sibling of this `SKILL.md` — resolve reference paths against
that directory, not your working directory, and do not search the filesystem for
them.
If a skill tool returns this overview instead of the file you asked for, it did
not fetch it: read it from that directory instead, and do not write code from
memory because a reference read failed.
This distinction applies only to the skill's own packaged files. User data and
session artifacts are always read from and written to the user's working
directory — do not `cd` before running a script that writes a relative artifact
path.

## Common mistakes

| Symptom | Cause | Fix |
| --- | --- | --- |
| Treats "task", "batch", "job" as interchangeable | Primitive confusion | Task = one run; batch = many parallel tasks; job = managed loop |
| `Missing required parameter: filters` on `SearchQuantumTasks`, `SearchJobs`, or `SearchDevices` | `filters` is required on all three — only `SearchSpendingLimits` lets you omit it | Pass `filters=[]` (`--filters '[]'`) for an unfiltered search. A populated filter needs `name` and `values`, plus `operator` on tasks and jobs; `SearchDevices` has no `operator` member |
| `Missing required parameter: clientToken` when using AWS MCP `run_script` tool | `CreateQuantumTask`, `CreateJob`, `CancelQuantumTask`, `CreateSpendingLimit`, `UpdateSpendingLimit` require a `clientToken` for idempotency. The SDK, CLI, and boto3 generate one automatically; the `run_script` tool requires explicit passing | Pass `clientToken=str(uuid.uuid4())` on APIs taking `clientToken` when calling through `run_script`. Otherwise, prefer the SDK for these operations when possible. |
| Builds program IR as JAQCD | JAQCD is deprecated on Amazon Braket | Use OpenQASM — see [OpenQASM on Braket](https://docs.aws.amazon.com/braket/latest/developerguide/braket-openqasm.html) |
| Denies a feature or SDK construct exists | Training data outdated | Verify against the docs or `GetDevice` before saying it does not exist |
| Invents a class, method, or parameter | Writing API names from memory | Confirm the signature first. If uncertain, say so rather than inventing |

## Security considerations

Braket workflows touch IAM, S3, and (for hybrid jobs) container execution.

- **Least-privilege IAM.** Derive custom policies as subsets of the AWS managed policy for the workflow, scoped to the actions, device ARNs, and buckets the workload uses.
  Avoid using `braket:*` when possible.
  All Braket actions are listed at the [Service Authorization Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_braket.html).
  Call Braket APIs with IAM roles, not long-lived IAM user access keys.
  See [Security best practices in IAM](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html) for additional best practices.
  - **Tasks, devices, and spending limits.** Derive from [`AmazonBraketFullAccess`](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/AmazonBraketFullAccess.html).
    Restrict `braket:UpdateSpendingLimit` and `braket:DeleteSpendingLimit` to prevent accidental removal of a spending limit.
    See [Restricting access to devices](https://docs.aws.amazon.com/braket/latest/developerguide/restrict-access.html).
  - **Notebook and hybrid job execution roles.** Create as written in [setup.md](references/setup.md).
- **Encryption.** Keep each service's default encryption, listed below.
  If the user has security, compliance, or other requirements for encryption, use a customer managed KMS key that the user specifies instead.
  - S3 buckets for task and job results: always encrypted by default with SSE-S3. [Using server-side encryption with Amazon S3 managed keys (SSE-S3)](https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingServerSideEncryption.html).
    If using a customer managed key, use the key-policy and role grants in [setup.md](./references/setup.md).
  - CloudWatch Logs: always encrypted by default. [Encrypt log data in CloudWatch Logs using AWS Key Management Service](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/encrypt-log-data-kms.html)
  - Notebook storage: always encrypted by default. [Notebook instances, SageMaker AI jobs, and Endpoints](https://docs.aws.amazon.com/sagemaker/latest/dg/encryption-at-rest-nbi.html)
- **S3 bucket setup.** Create buckets as described in [setup.md](references/setup.md).
- **Auditing.** Follow [Getting started with AWS CloudTrail tutorials](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-tutorial.html) and [Security Best Practices in AWS CloudTrail](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/best-practices-security.html) to set up a Trail to capture all Braket management events.
- **Cost guardrail.** Enforce QPU spend caps with spending limits, per the spending-limit rule in [Critical Rules](#critical-rules).
- **Secrets.** Hybrid job hyperparameters are stored in job metadata and echoed into the job's CloudWatch log stream, so never pass a secret as a hyperparameter; fetch it from Secrets Manager or SSM Parameter Store inside the algorithm script.

For details, see the [Amazon Braket security documentation](https://docs.aws.amazon.com/braket/latest/developerguide/security.html).

## Reference links

Authoritative sources — prefer these over recalled details, since device ARNs, quotas, prices, and supported features change.

**Official documentation** (stable entry points — navigate/search from here)

- Developer Guide —
  <https://docs.aws.amazon.com/braket/latest/developerguide/what-is-braket.html>
- Prerequisites & account setup —
  <https://docs.aws.amazon.com/braket/latest/developerguide/braket-get-started.html>
- How Amazon Braket works —
  <https://docs.aws.amazon.com/braket/latest/developerguide/braket-how-it-works.html>
- API Reference —
  <https://docs.aws.amazon.com/braket/latest/APIReference/Welcome.html>
- Python SDK API docs —
  <https://amazon-braket-sdk-python.readthedocs.io/en/stable/>
- Getting started — <https://aws.amazon.com/braket/getting-started/>
- OpenQASM 3.0 spec — <https://openqasm.com/versions/3.0/index.html>
- OpenQASM on Braket —
  <https://docs.aws.amazon.com/braket/latest/developerguide/braket-openqasm.html>
- Supported OpenQASM features (pragmas, verbatim rules, dynamic circuits) —
  <https://docs.aws.amazon.com/braket/latest/developerguide/braket-openqasm-supported-features.html>
- boto3 `braket` client —
  <https://docs.aws.amazon.com/boto3/latest/reference/services/braket.html>
- Security — <https://docs.aws.amazon.com/braket/latest/developerguide/security.html>

For anything not covered here, **search the documentation** rather than guessing
page slugs or recalling details: if the AWS MCP server is available, its
`aws___search_documentation` tool can help; otherwise start from the Developer
Guide or API Reference above and navigate.

## GitHub

- `amazon-braket-sdk-python` (core SDK) —
  <https://github.com/amazon-braket/amazon-braket-sdk-python>
- `amazon-braket-schemas-python` (schemas and models for public Braket data) —
  <https://github.com/amazon-braket/amazon-braket-schemas-python>
- `amazon-braket-examples` —
  <https://github.com/amazon-braket/amazon-braket-examples>
