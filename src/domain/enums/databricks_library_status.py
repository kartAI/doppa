from enum import Enum


class DatabricksLibraryStatus(str, Enum):
    """Library installation ``status`` values returned by the Databricks REST API.

    Only the values the service compares against are enumerated.
    """

    INSTALLED = "INSTALLED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"

    @classmethod
    def terminal_failure_values(cls) -> frozenset[str]:
        """Raw status strings that indicate the library install will not succeed."""
        return frozenset({cls.FAILED.value, cls.SKIPPED.value})
