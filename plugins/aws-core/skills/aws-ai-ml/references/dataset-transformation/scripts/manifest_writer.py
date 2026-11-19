#!/usr/bin/env python3
"""Transformation Manifest writer.

Builds and persists a ``transformation_manifest.json`` file that records
the full chain of operations executed during a Transformation Spec run,
including per-operation statistics and overall transformation-run metadata.

The writer keeps all operations in memory and writes the complete
manifest state to disk on each call to :meth:`write`.  This ensures
the on-disk manifest always reflects the latest transformation-run state —
even if the process crashes mid-run.  Each ``write()`` overwrites
the file with the full current state (not an append).

Usage (as a library)::

    from manifest_writer import ManifestWriter

    writer = ManifestWriter(
        project_dir="/home/user/my-project",
        run_number=1,
        spec_input=["s3://bucket/raw.jsonl"],
        final_output="s3://bucket/transformed/result.jsonl",
    )

    # After each operation, add + write immediately:
    writer.add_operation(
        step=1,
        op_type="ingest",
        instruction="Ingest the raw CSV file",
        input_records=10000,
        output_records=10000,
        output_path="/home/user/my-project/data/transformed/run_001/step_1_ingest.jsonl",
        parameters={"detected_format": "csv"},
    )
    writer.set_status("partial")
    writer.write()  # manifest on disk now has step 1

    writer.add_operation(
        step=2,
        op_type="clean",
        instruction="Normalize text",
        input_records=10000,
        output_records=9500,
        output_path="/home/user/my-project/data/transformed/run_001/step_2_clean.jsonl",
    )
    writer.set_status("completed")
    writer.write()  # manifest on disk now has steps 1 and 2
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import List, Optional, Union


class ManifestWriter:
    """Builds and writes a transformation manifest to disk incrementally.

    Each call to :meth:`write` reads the existing manifest from disk,
    merges operations by step number, updates the global metadata fields,
    and writes the result back. A rerun of a step replaces that step's
    prior statistics instead of leaving stale values in the manifest.

    Parameters
    ----------
    project_dir : str
        Root project directory.  The manifest is written to
        ``<project_dir>/manifests/transformation_manifest_run_NNN.json``.
    run_number : int
        The run number (used for the manifest filename).
    spec_input : str | list[str]
        Original input path(s) from the Transformation Spec.
    final_output : str | list[str]
        Final output destination(s) from the Transformation Spec. May be a
        single string (single-file output) or a list of strings (multi-file
        output, e.g. when the final operation is a ``split`` that produces
        train / val / test files).
    hub_content_arn : str | list[str] | None
        SageMaker Hub content ARN or ARNs, set after successful Hub registration.
    run_directory : str | None
        Path to the run directory for intermediate outputs.  When *None*,
        it is derived from *project_dir* and *run_number*.
    """

    def __init__(
        self,
        project_dir: str,
        run_number: int,
        spec_input,
        final_output: Union[str, List[str]],
        hub_content_arn: Optional[Union[str, List[str]]] = None,
        run_directory: Optional[str] = None,
    ):
        self.project_dir = project_dir
        self.run_number = run_number

        # Normalise spec_input to a list
        if isinstance(spec_input, str):
            self.spec_input = [spec_input]
        else:
            self.spec_input = list(spec_input)

        self.final_output = final_output
        self.hub_content_arn = hub_content_arn

        if run_directory is not None:
            self.run_directory = run_directory
        else:
            self.run_directory = os.path.join(
                project_dir,
                "data",
                "transformed",
                f"run_{run_number:03d}",
            )

        self._pending_operations: list[dict] = []
        self._status: str = "completed"

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: str, project_dir: Optional[str] = None, run_number: Optional[int] = None):
        """Load an existing manifest from disk and return a writer that can append to it.

        This allows the agent to create a new ManifestWriter per step
        without losing previously recorded operations.  The returned
        writer contains all operations from the on-disk manifest.

        Parameters
        ----------
        path : str
            Path to an existing ``transformation_manifest_run_NNN.json``.
        project_dir : str | None
            Override project_dir.  Defaults to the value in the manifest.
        run_number : int | None
            Override run_number.  Defaults to parsing from the filename.

        Returns
        -------
        ManifestWriter
            A writer pre-populated with the on-disk operations.
        """
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        if project_dir is None:
            # Derive from run_directory: strip /data/transformed/run_NNN
            run_dir = data.get("run_directory", "")
            # Walk up 3 levels: run_NNN -> transformed -> data -> project_dir
            project_dir = os.path.dirname(os.path.dirname(os.path.dirname(run_dir)))

        if run_number is None:
            # Parse from filename: transformation_manifest_run_001.json
            basename = os.path.basename(path)
            try:
                run_number = int(basename.split("run_")[1].split(".")[0])
            except (IndexError, ValueError):
                run_number = 1

        writer = cls(
            project_dir=project_dir,
            run_number=run_number,
            spec_input=data.get("spec_input", []),
            final_output=data.get("final_output", ""),
            hub_content_arn=data.get("hub_content_arn"),
            run_directory=data.get("run_directory"),
        )
        writer._pending_operations = data.get("operations", [])
        writer._status = data.get("status", "partial")
        return writer

    def add_operation(
        self,
        step: int,
        op_type: str,
        instruction: str,
        input_records: int,
        output_records: int,
        output_path: str,
        parameters: Optional[dict] = None,
        timestamp: Optional[str] = None,
    ) -> None:
        """Record a single transformation operation in memory.

        The operation is held in memory until :meth:`write` is called,
        at which point it is appended to the on-disk manifest.

        Parameters
        ----------
        step : int
            1-based step number.
        op_type : str
            Inferred operation type (e.g. ``"ingest"``, ``"clean"``,
            ``"schema_transform"``, ``"merge"``, ``"filter"``, ``"split"``).
        instruction : str
            Original natural-language instruction from the spec.
        input_records : int
            Number of **non-blank JSONL lines** entering this operation —
            non-blank lines the parser attempted to load (clean parses
            plus malformed lines that get reported and dropped). It is not
            a raw line count: do not pass ``wc -l`` output here, because
            blank/trailing lines would inflate the count.
        output_records : int
            Number of records successfully emitted by this operation.
        output_path : str
            Path to the step's output file.
        parameters : dict | None
            Operation-specific parameters to record.
        timestamp : str | None
            ISO-8601 timestamp.  Defaults to *now* in UTC.
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat()

        entry = {
            "step": step,
            "type": op_type,
            "instruction": instruction,
            "input_records": input_records,
            "output_records": output_records,
            "records_removed": input_records - output_records,
            "output_path": output_path,
            "timestamp": timestamp,
            "parameters": parameters if parameters is not None else {},
        }
        self._pending_operations.append(entry)

    def set_status(self, status: str) -> None:
        """Set the overall transformation-run status.

        Parameters
        ----------
        status : str
            One of ``"completed"``, ``"partial"``, or ``"failed"``.

        Raises
        ------
        ValueError
            If *status* is not one of the allowed values.
        """
        allowed = {"completed", "partial", "failed"}
        if status not in allowed:
            raise ValueError(f"Invalid status {status!r}; must be one of {sorted(allowed)}")
        self._status = status

    def set_hub_content_arn(self, arn: Union[str, List[str]]) -> None:
        """Record the Hub content ARN or ARNs after successful registration."""
        self.hub_content_arn = arn

    def set_final_output(self, value: Union[str, List[str]]) -> None:
        """Set the final output destination(s) for this run.

        Use a list when the final operation produces multiple files (for
        example, ``split`` produces ``split_train.jsonl`` /
        ``split_val.jsonl`` / ``split_test.jsonl``).  Use a single string
        for single-file output. Both forms serialize naturally as JSON.

        Parameters
        ----------
        value : str | list[str]
            Single destination path or list of destination paths.
        """
        self.final_output = value

    # ------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------

    @property
    def all_operations(self) -> list[dict]:
        """All operations in step order, with the latest rerun winning."""
        operations_by_step = {
            operation["step"]: operation for operation in self._pending_operations
        }
        return [operations_by_step[step] for step in sorted(operations_by_step)]

    @property
    def total_input_records(self) -> int:
        """Input record count of the first operation, or 0 if empty."""
        ops = self.all_operations
        if not ops:
            return 0
        return ops[0]["input_records"]

    @property
    def total_output_records(self) -> int:
        """Output record count of the last operation, or 0 if empty."""
        ops = self.all_operations
        if not ops:
            return 0
        return ops[-1]["output_records"]

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def build(self) -> dict:
        """Return the full manifest as a plain dictionary.

        This includes all operations (flushed + pending).
        """
        ops = self.all_operations
        first_input = ops[0]["input_records"] if ops else 0
        last_output = ops[-1]["output_records"] if ops else 0

        manifest = {
            "spec_input": self.spec_input,
            "final_output": self.final_output,
            "total_input_records": first_input,
            "total_output_records": last_output,
            "run_directory": self.run_directory,
            "hub_content_arn": self.hub_content_arn,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "operations": ops,
            "status": self._status,
        }

        return manifest

    def manifest_path(self) -> str:
        """Return the target file path for the manifest."""
        manifests_dir = os.path.join(self.project_dir, "manifests")
        filename = f"transformation_manifest_run_{self.run_number:03d}.json"
        return os.path.join(manifests_dir, filename)

    def write(self, path: Optional[str] = None) -> str:
        """Write the manifest JSON to disk using read-modify-write.

        Reads the existing manifest from disk (if present), merges pending
        operations by step number, updates global fields, and writes back.
        A pending operation replaces the existing entry for the same step,
        so rerunning a notebook cell refreshes its statistics without
        creating a duplicate manifest entry.

        Parameters
        ----------
        path : str | None
            Override the default manifest path.  When *None*, the manifest
            is written to
            ``<project_dir>/manifests/transformation_manifest_run_NNN.json``.

        Returns
        -------
        str
            The absolute path of the written manifest file.
        """
        if path is None:
            path = self.manifest_path()

        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)

        # Read existing operations from disk
        existing = {}
        existing_ops = []
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
            except json.JSONDecodeError as error:
                raise RuntimeError(
                    f"Existing manifest is invalid JSON; refusing to overwrite {path}"
                ) from error
            except OSError as error:
                raise RuntimeError(
                    f"Existing manifest could not be read; refusing to overwrite {path}"
                ) from error
            if not isinstance(loaded, dict):
                raise RuntimeError(
                    f"Existing manifest is not a JSON object; refusing to overwrite {path}"
                )
            existing = loaded
            existing_ops = existing.get("operations", [])

        # Pending entries replace the same numbered step on disk. Sorting keeps
        # the manifest deterministic even when a prior step is rerun later.
        operations_by_step = {op["step"]: op for op in existing_ops}
        for operation in self._pending_operations:
            operations_by_step[operation["step"]] = operation
        all_ops = [operations_by_step[step] for step in sorted(operations_by_step)]

        # Compute globals from the full operation list
        first_input = all_ops[0]["input_records"] if all_ops else 0
        last_output = all_ops[-1]["output_records"] if all_ops else 0

        manifest = {
            "spec_input": self.spec_input,
            "final_output": self.final_output,
            "total_input_records": first_input,
            "total_output_records": last_output,
            "run_directory": self.run_directory,
            "hub_content_arn": self.hub_content_arn,
            "created_at": existing.get("created_at", datetime.now(timezone.utc).isoformat()),
            "operations": all_ops,
            "status": self._status,
        }

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=directory,
                prefix=".transformation_manifest_",
                suffix=".tmp",
                delete=False,
            ) as fh:
                temp_path = fh.name
                json.dump(manifest, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temp_path, path)
        except Exception:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            raise

        return os.path.abspath(path)
