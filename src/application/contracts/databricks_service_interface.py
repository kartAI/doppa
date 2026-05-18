from abc import ABC, abstractmethod

from src.application.dtos import DatabricksRunResult
from src.domain.enums import DatasetSize


class IDatabricksService(ABC):
    @abstractmethod
    def create_cluster(self, num_workers: int) -> str:
        """
        Provision an interactive cluster, install required libraries, wait for the cluster to
        reach RUNNING state and for all libraries to reach INSTALLED state, and upload the
        benchmark notebook to the workspace.

        :param num_workers: Number of worker nodes to provision for the cluster.
        :return: The Databricks cluster ID, suitable for passing to
            :meth:`submit_to_existing_cluster` and :meth:`terminate_cluster`.
        :rtype: str
        :raises RuntimeError: If the cluster fails to start, a library install fails or is
            skipped, or the notebook upload fails. The partially-provisioned cluster is
            terminated before the exception propagates.
        """
        raise NotImplementedError

    @abstractmethod
    def submit_to_existing_cluster(
        self, cluster_id: str, num_workers: int, dataset_size: DatasetSize
    ) -> DatabricksRunResult:
        """
        Submit a single notebook run against an already-running cluster and block until it
        reaches a terminal state (TERMINATED, SKIPPED, or INTERNAL_ERROR).

        :param cluster_id: The cluster ID returned by :meth:`create_cluster`.
        :param num_workers: Number of worker nodes on the cluster. Used only to label the
            Databricks run (e.g. ``national-scale-spatial-join-8-nodes``).
        :param dataset_size: Which buildings dataset partition the notebook should read
            (``size=small|medium|large`` under the release path).
        :return: DatabricksRunResult with `execution_duration_s`, `cardinality`, and the six
            Spark phase metrics self-reported by the notebook via `dbutils.notebook.exit`
            JSON. `execution_duration_s` measures the spatial join + count() only.
        :rtype: DatabricksRunResult
        :raises RuntimeError: If the run finishes in a non-successful state or the notebook
            does not emit the expected JSON payload.
        """
        raise NotImplementedError

    @abstractmethod
    def terminate_cluster(self, cluster_id: str) -> None:
        """
        Permanently delete the cluster. Safe to call from a ``finally`` block.

        :param cluster_id: The cluster ID returned by :meth:`create_cluster`.
        :raises RuntimeError: If the Databricks API rejects the delete request.
        """
        raise NotImplementedError
