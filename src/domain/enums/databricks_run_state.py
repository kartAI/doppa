from enum import Enum


class DatabricksRunLifecycleState(str, Enum):
    """``life_cycle_state`` values returned for Databricks jobs/runs.

    Only the values the service compares against are enumerated.
    """

    TERMINATED = "TERMINATED"
    SKIPPED = "SKIPPED"
    INTERNAL_ERROR = "INTERNAL_ERROR"

    @classmethod
    def terminal_values(cls) -> frozenset[str]:
        """Raw lifecycle strings after which the run will not progress further."""
        return frozenset(
            {cls.TERMINATED.value, cls.SKIPPED.value, cls.INTERNAL_ERROR.value}
        )


class DatabricksRunResultState(str, Enum):
    """``result_state`` values returned once a Databricks run reaches a terminal lifecycle."""

    SUCCESS = "SUCCESS"
