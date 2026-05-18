from enum import Enum


class DatabricksClusterState(str, Enum):
    """Cluster ``state`` values returned by the Databricks REST API.

    Only the values the service compares against are enumerated. Any other state seen
    in API responses is treated as a non-terminal "still working" state by the caller.
    """

    RUNNING = "RUNNING"
    ERROR = "ERROR"
    TERMINATED = "TERMINATED"
    TERMINATING = "TERMINATING"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def non_running_terminal_values(cls) -> frozenset[str]:
        """Raw state strings that indicate the cluster reached a terminal state
        without ever entering RUNNING."""
        return frozenset(
            {cls.ERROR.value, cls.TERMINATED.value, cls.TERMINATING.value, cls.UNKNOWN.value}
        )
