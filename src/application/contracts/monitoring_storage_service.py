import datetime
from abc import ABC, abstractmethod
from typing import Any

from src.application.dtos import Cost
from src.domain.enums import StopReason


class IMonitoringStorageService(ABC):
    @abstractmethod
    def write_metadata_to_blob_storage(
            self,
            metadata_id: str,
            timestamp: datetime.datetime,
            query_id: str,
            run_id: str,
            achieved_iterations: int,
            failed_iterations: int,
            stop_reason: StopReason,
            ci_half_width_seconds: float | None,
            ci_half_width_relative: float | None,
            mean_elapsed_seconds: float | None,
            median_elapsed_seconds: float | None,
    ) -> None:
        """
        Save metadata to blob storage. Metadata includes information about the query and the run,
        such as query text, parameters, execution time, etc. The metadata is saved with a Hive
        compatible partition structure to allow for efficient querying and analysis of the data. The
        partition structure is defined as follows: `query_id=<query_id>/run_id=<run_id>/metadata.parquet`.
        This structure allows for easy retrieval of metadata based on query ID and run ID.
        :param metadata_id: A GUID for the metadata entry which is generated in the main method and
            passed to this method.
        :param timestamp: Timestamp of when the metadata entry was created which is generated in the
            main method and passed to this method.
        :param query_id: Query ID associated with the run which is passed from the main method.
        :param run_id: A unique identifier for the run.
        :param achieved_iterations: Number of timed iterations that completed successfully (excludes
            warmup and failed iterations).
        :param failed_iterations: Number of timed iterations that raised an exception. Failed
            iterations are persisted with status="failed" in their per-iteration sample row.
        :param stop_reason: Why the iteration loop stopped (``precision`` met, ``timeout``,
            ``ceiling``, ``fixed`` count for Databricks, ``partial`` for a run that mixed
            successes and failures, or ``failed`` when no successful iteration completed).
        :param ci_half_width_seconds: Absolute half-width of the bootstrapped 95% CI on the mean
            elapsed time, in seconds. None when sequential stopping is disabled or the run failed
            before producing enough samples.
        :param ci_half_width_relative: Same half-width as a fraction of the mean (e.g. 0.05 == 5%).
            None when undefined.
        :param mean_elapsed_seconds: Mean elapsed time across timed iterations. None when no timed
            iteration completed.
        :param median_elapsed_seconds: Median elapsed time across timed iterations. None when no
            timed iteration completed.
        :return: None
        """
        raise NotImplementedError

    @abstractmethod
    def write_run_to_blob_storage(
            self,
            samples: list[dict[str, Any]],
            query_id: str,
            run_id: str,
            benchmark_run: int,
            iteration: int
    ) -> None:
        """
        Save the run to blob storage. A run includes the samples collected during the execution of
        the query. The run is saved with a Hive compatible partition structure to allow for efficient
        querying and analysis of the data. The partition structure is defined as follows:
        `query_id=<query_id>/run_id=<run_id>/benchmark_run=<benchmark_run>/iteration=<iteration>/<filename>.parquet`.
        This structure allows for easy retrieval of runs based on query ID, run ID, and iteration number.
        :param samples: Samples collected during the execution of the query which is passed from the
            main method. Each sample is a dictionary containing information about the system metrics
            at a specific point in time.
        :param query_id: Query ID associated with the run which is passed from the main method.
        :param run_id: A unique identifier for the run which is passed from the main method.
        :param benchmark_run: Benchmark iteration number which is passed from the main method. This
            is used to differentiate between multiple benchmark iterations of the same query.
        :param iteration: Iteration number of the run which is passed from the main method. This is
            used to differentiate between multiple runs of the same query.
        :return: None
        """
        raise NotImplementedError

    @abstractmethod
    def write_cost_analytics_to_blob_storage(
            self,
            cost: Cost,
            query_id: str,
            run_id: str,
            benchmark_run: int,
            file_name: str
    ) -> None:
        """
        Save the cost analytics to blob storage. The cost analytics includes the cost of the
        resources used during the execution of the query. The cost analytics is saved with a Hive
        partition with the run information. The partition structure is defined as follows:
        `query_id=<query_id>/run_id=<run_id>/benchmark_run=<benchmark_run>/cost_analytics.parquet`.
        This structure allows for easy retrieval of cost analytics based on query ID and run ID.
        :param cost: Cost analytics collected during the execution of the query which is passed from
            the main method. The Cost object contains information about the cost of the resources
            used during the execution of the query.
        :param query_id: Query ID associated with the run which is passed from the main method.
        :param run_id: A unique identifier for the run which is passed from the main method.
        :param benchmark_run: Benchmark iteration number which is passed from the main method. This
            is used to differentiate between multiple benchmark iterations of the same query.
        :param file_name: File name must end with `.parquet` and is used to differentiate between
            different types of cost analytics. For example, if there are multiple cost analytics
            collected during the execution of the query, such as ACI cost and Blob Storage cost, the
            file name can be used to differentiate between them. The file name is passed from the
            main method and can be defined as follows: `cost_analytics_<cost_type>.parquet`, where
            `<cost_type>` is a string that describes the type of cost analytics being saved (e.g.,
            `aci`, `blob_storage`, etc.).
        :return: None
        """
        raise NotImplementedError
