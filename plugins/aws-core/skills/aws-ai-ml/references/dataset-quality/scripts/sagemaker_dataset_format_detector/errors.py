"""Error types for the dataset readers.

``DatasetReadError`` subclasses ``ValueError`` so it is specific enough for a
caller to catch on its own, while staying compatible with the package's existing
contract: ``detect_file_format`` already documents raising ``ValueError`` for bad
input, and callers that catch ``ValueError`` keep working.
"""

from __future__ import annotations


class DatasetReadError(ValueError):
    """A dataset file could not be read into records.

    Raised for input the reader cannot turn into rows: a missing or unreadable
    file, a corrupt or non-Parquet file, shards whose schemas disagree, or a
    dataset with no rows or no columns.
    """


__all__ = ["DatasetReadError"]
