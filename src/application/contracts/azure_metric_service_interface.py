import datetime
from abc import ABC, abstractmethod

from azure.monitor.querymetrics import MetricAggregationType, MetricsQueryResult

from src.application.dtos import AciUsage, BlobStorageUsage, DatabaseUsage, DatabricksUsage
from src.domain.enums import AzureMetricNamespace, AzureResourceMetrics, BlobOperationType, DatasetSize


class IAzureMetricService(ABC):
    @abstractmethod
    def query_metrics(
            self,
            resource_name: str,
            metric_namespace: AzureMetricNamespace,
            metric_names: AzureResourceMetrics,
            start_time: datetime.datetime,
            end_time: datetime.datetime,
            aggregations: list[MetricAggregationType],
            granularity: datetime.timedelta = datetime.timedelta(minutes=1),
            is_waiting_for_ingestion: bool = True
    ) -> list[MetricsQueryResult]:
        """
        Queries Azure Monitor for resource metrics over the given timespan. The call is retried up to
        three times with exponential backoff on `ClientAuthenticationError` and `ServiceRequestError`.
        :param resource_name: Name of the Azure resource (e.g. ACI container group, PostgreSQL server) to query.
        :param metric_namespace: Azure metric namespace identifying the resource type.
        :param metric_names: Enum value whose `.value` is the comma-separated list of metric names to query.
        :param start_time: Start of the metric query window.
        :param end_time: End of the metric query window.
        :param aggregations: List of aggregation types to apply (e.g. AVERAGE, TOTAL, MINIMUM, MAXIMUM).
        :param granularity: Time grain for the metric query. Defaults to 1 minute.
        :param is_waiting_for_ingestion: When True, sleeps until the Azure Monitor ingestion delay has
            elapsed since `end_time` before querying. Defaults to True.
        :return: List of MetricsQueryResult objects, one per queried resource.
        :rtype: list[MetricsQueryResult]
        :raises Exception: Re-raises the last Azure SDK exception after exhausting retries.
        """
        raise NotImplementedError

    @abstractmethod
    def get_aci_usage(
            self,
            script_id: str,
            start_time: datetime.datetime,
            end_time: datetime.datetime,
    ) -> AciUsage:
        """
        Returns the Azure Container Instance resource usage for the benchmark identified by `script_id`.
        The vCPU and memory allocations are read from the benchmark configuration. The network ingress
        and egress are computed by summing the per-second network metrics from Azure Monitor over the
        benchmark window.
        :param script_id: Script identifier used to look up the ACI configuration and resource name
            (`benchmark-{script_id}`).
        :param start_time: Start of the benchmark window.
        :param end_time: End of the benchmark window.
        :return: AciUsage DTO with duration, vCPU count, memory in GB, and network bytes ingress/egress.
        :rtype: AciUsage
        """
        raise NotImplementedError

    @abstractmethod
    def get_blob_storage_usage(
            self,
            start_time: datetime.datetime,
            end_time: datetime.datetime,
            bytes_ingress: float,
            bytes_egress: float,
            operation_type: BlobOperationType,
            dataset_size: DatasetSize = DatasetSize.SMALL,
    ) -> BlobStorageUsage:
        """
        Returns the blob storage usage for the benchmark window. The transaction counts are derived from
        the number of blobs under the dataset path for the configured release. Either the read or write
        transaction count is set based on `operation_type`, while a single list transaction is always
        recorded for the glob/list call itself.
        :param start_time: Start of the benchmark window.
        :param end_time: End of the benchmark window.
        :param bytes_ingress: Bytes uploaded to blob storage during the benchmark.
        :param bytes_egress: Bytes downloaded from blob storage during the benchmark.
        :param operation_type: Whether the benchmark performs READ or WRITE operations against blob storage.
        :param dataset_size: Dataset size tier used to resolve the blob path for counting blobs.
        :return: BlobStorageUsage DTO with transaction counts, network bytes, and storage size in bytes.
        :rtype: BlobStorageUsage
        """
        raise NotImplementedError

    @abstractmethod
    def get_database_usage(
            self,
            start_time: datetime.datetime,
            end_time: datetime.datetime,
    ) -> DatabaseUsage:
        """
        Returns the PostgreSQL Flexible Server resource usage for the benchmark window. CPU and memory
        percentages, network bytes, and storage size are aggregated from Azure Monitor metrics.
        :param start_time: Start of the benchmark window.
        :param end_time: End of the benchmark window.
        :return: DatabaseUsage DTO with duration, CPU/memory percentages (avg/min/max), network bytes
            ingress/egress, and storage used in bytes.
        :rtype: DatabaseUsage
        """
        raise NotImplementedError

    @abstractmethod
    def get_databricks_usage(
            self,
            start_time: datetime.datetime,
            end_time: datetime.datetime,
            num_workers: int,
            bytes_egress: float,
    ) -> DatabricksUsage:
        """
        Returns the Databricks resource usage for the benchmark window. Duration is computed from the
        window bounds, and the worker count and egress bytes are forwarded from the caller.
        :param start_time: Start of the benchmark window.
        :param end_time: End of the benchmark window.
        :param num_workers: Number of Databricks worker nodes provisioned for the run.
        :param bytes_egress: Bytes egressed from the Databricks cluster during the benchmark.
        :return: DatabricksUsage DTO with duration, worker count, and egress bytes.
        :rtype: DatabricksUsage
        """
        raise NotImplementedError
