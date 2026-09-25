"""The structured result returned by instrumentation-config / status operations.

WHY THIS EXISTS
The CRUD and status operation functions (in ``di_crud_tools`` / ``di_status_tools``)
return a human-readable string for both success and failure and never raise. That
text is what the agent reads. But the entry script (``di_instrumentation.py``) also
needs to derive a process exit code from each operation, and historically it did so
by *string-matching* the rendered prose ("Failed to ...", "DELETE ERRORS:", etc.) —
wording owned by several other modules. Rewording any renderer could silently flip a
real failure to exit 0.

``OpResult`` separates the two concerns that the bare string conflated:

* ``ok``   — the STATUS channel. Drives the process exit code (``0`` if ``ok`` else
             ``1``). Set by each operation at the point where success vs. failure is
             actually known (the ``except GatewayError`` site, the early ``ERROR:``
             return, the success render).
* ``text`` — the PRESENTATION channel. The rendered human string, unchanged from
             before; the entry script prints it verbatim.

``ok`` is about whether the *operation* succeeded, NOT about the AWS instrumentation
lifecycle state. A ``check-status`` call that successfully reports a breakpoint in the
ERROR state is ``OpResult(ok=True, ...)`` — the query succeeded; the breakpoint's
status being ERROR is content in ``text``.

This module imports nothing so the entry script and both tools modules can import it
without any risk of an import cycle.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class OpResult:
    """The (status, presentation) pair an operation returns.

    Attributes:
        ok: True when the operation succeeded; False for any input/validation/AWS
            failure. Maps to exit code ``0``/``1`` in the entry script.
        text: The rendered human-readable message the agent reads (printed verbatim).
    """

    ok: bool
    text: str
