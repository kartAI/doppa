import datetime
import time

from azure.core.exceptions import ClientAuthenticationError, ServiceRequestError
from azure.identity import DefaultAzureCredential
from azure.monitor.querymetrics import MetricsClient, MetricAggregationType, MetricsQueryResult

from src import Config
from src.application.common import logger
from src.application.contracts import IAzureMetricService, IBenchmarkConfigurationService, IBlobStorageService, \
    IFilePathService
from src.application.dtos import DatabaseUsage, BlobStorageUsage, AciUsage, DatabricksUsage
from src.domain.enums import AzureMetricNamespace, AzureResourceMetrics, Theme, StorageContainer, BlobOperationType, DatasetSize


class AzureMetricService(IAzureMetricService):
    __metrics_client: MetricsClient
    __benchmark_configuration_service: IBenchmarkConfigurationService
    __blob_storage_service: IBlobStorageService
    __file_path_service: IFilePathService

    def __init__(
            self,
            benchmark_configuration_service: IBenchmarkConfigurationService,
            blob_storage_service: IBlobStorageService,
            file_path_service: IFilePathService
    ):
        credential = DefaultAzureCredential()

        # noinspection PyTypeChecker
        self.__metrics_client = MetricsClient(Config.AZURE_METRICS_REGIONAL_ENDPOINT, credential)
        self.__benchmark_configuration_service = benchmark_configuration_service
        self.__blob_storage_service = blob_storage_service
        self.__file_path_service = file_path_service

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
        if is_waiting_for_ingestion:
            self.__wait_for_ingestion(end_time=end_time)

        max_attempts = 3
        last_exception: Exception | None = None
        for attempt in range(max_attempts):
            try:
                return self.__metrics_client.query_resources(
                    resource_ids=[self.__create_resource_ids(metric_namespace, resource_name)],
                    metric_namespace=metric_namespace.value,
                    metric_names=metric_names.value,
                    timespan=(start_time, end_time),
                    granularity=granularity,
                    aggregations=aggregations,
                )
            except (ClientAuthenticationError, ServiceRequestError) as e:
                last_exception = e
                if attempt == max_attempts - 1:
                    break
                wait = 5 * (3 ** attempt)
                logger.warning(
                    f"Azure metrics query failed (attempt {attempt + 1}/{max_attempts}), "
                    f"retrying in {wait}s: {e}"
                )
                time.sleep(wait)

        raise last_exception

    def get_aci_usage(
            self,
            script_id: str,
            start_time: datetime.datetime,
            end_time: datetime.datetime,
    ) -> AciUsage:
        duration_seconds = (end_time - start_time).total_seconds()
        benchmark_configuration = self.__benchmark_configuration_service.get_experiment_configuration(
            script_id=script_id
        )

        results = self.query_metrics(
            resource_name=f"benchmark-{script_id}",
            metric_namespace=AzureMetricNamespace.CONTAINER_INSTANCES,
            metric_names=AzureResourceMetrics.ACI,
            start_time=start_time,
            end_time=end_time,
            aggregations=[MetricAggregationType.AVERAGE],
        )

        bytes_ingress = self.__sum_rate_metric(results, "NetworkBytesReceivedPerSecond", granularity_seconds=60)
        bytes_egress = self.__sum_rate_metric(results, "NetworkBytesTransmittedPerSecond", granularity_seconds=60)

        return AciUsage(
            duration_seconds=duration_seconds,
            vcpu_count=benchmark_configuration.cpu,
            memory_gb=benchmark_configuration.memory_gb,
            bytes_ingress=bytes_ingress,
            bytes_egress=bytes_egress,
        )

    def get_blob_storage_usage(
            self,
            start_time: datetime.datetime,
            end_time: datetime.datetime,
            bytes_ingress: float,
            bytes_egress: float,
            operation_type: BlobOperationType,
            dataset_size: DatasetSize = DatasetSize.SMALL,
    ) -> BlobStorageUsage:
        path = self.__file_path_service.create_dataset_blob_path(
            release=Config.BENCHMARK_DOPPA_DATA_RELEASE,
            theme=Theme.BUILDINGS,
            region="*",
            file_name="*.parquet",
            dataset_size=dataset_size,
        )

        blob_count, storage_size = self.__blob_storage_service.get_blob_summary(
            container=StorageContainer.DATA,
            path=path
        )

        if operation_type == BlobOperationType.READ:
            read_transactions = blob_count
            write_transactions = 0
        else:
            read_transactions = 0
            write_transactions = blob_count

        return BlobStorageUsage(
            read_transactions=read_transactions,
            write_transactions=write_transactions,
            list_transactions=1,  # the glob/list call itself
            bytes_ingress=bytes_ingress,
            bytes_egress=bytes_egress,
            storage_bytes=storage_size
        )

    def get_databricks_usage(
            self,
            start_time: datetime.datetime,
            end_time: datetime.datetime,
            num_workers: int,
            bytes_egress: float,
    ) -> DatabricksUsage:
        return DatabricksUsage(
            duration_seconds=(end_time - start_time).total_seconds(),
            num_workers=num_workers,
            bytes_egress=bytes_egress,
        )

    def get_database_usage(self, start_time, end_time) -> DatabaseUsage:
        results = self.query_metrics(
            resource_name=Config.POSTGRES_SERVER_NAME,
            metric_namespace=AzureMetricNamespace.POSTGRESQL_FLEXIBLE,
            metric_names=AzureResourceMetrics.POSTGRES,
            start_time=start_time,
            end_time=end_time,
            aggregations=[
                MetricAggregationType.AVERAGE,
                MetricAggregationType.MINIMUM,
                MetricAggregationType.MAXIMUM,
                MetricAggregationType.TOTAL,
            ],
        )

        return DatabaseUsage(
            duration_seconds=(end_time - start_time).total_seconds(),
            avg_cpu_percent=self.__extract_metric_average(results, "cpu_percent"),
            max_cpu_percent=self.__extract_metric_max(results, "cpu_percent"),
            min_cpu_percent=self.__extract_metric_min(results, "cpu_percent"),
            avg_memory_percent=self.__extract_metric_average(results, "memory_percent"),
            max_memory_percent=self.__extract_metric_max(results, "memory_percent"),
            min_memory_percent=self.__extract_metric_min(results, "memory_percent"),
            network_ingress_bytes=self.__extract_metric_total(results, "network_bytes_ingress"),
            network_egress_bytes=self.__extract_metric_total(results, "network_bytes_egress"),
            storage_used_bytes=self.__extract_metric_last(results, "storage_used"),
        )

    @staticmethod
    def __create_resource_ids(azure_metric_namespace: AzureMetricNamespace, resource_name: str) -> str:
        return f"/subscriptions/{Config.AZURE_SUBSCRIPTION_ID}/resourceGroups/{Config.AZURE_RESOURCE_GROUP}/providers/{azure_metric_namespace.value}/{resource_name}"

    @staticmethod
    def __wait_for_ingestion(end_time: datetime.datetime) -> None:
        seconds_since_end = (datetime.datetime.now(datetime.timezone.utc) - end_time).total_seconds()
        if seconds_since_end < Config.INGESTION_DELAY_SECONDS:
            wait = Config.INGESTION_DELAY_SECONDS - int(seconds_since_end)
            logger.info(f"Waiting {wait} seconds for metrics ingestion...")
            time.sleep(wait)

    @staticmethod
    def __extract_metric_total(
            results: list[MetricsQueryResult],
            metric_name: str,
    ) -> float:
        total = 0.0
        for result in results:
            for metric in result.metrics:
                if metric.name != metric_name:
                    continue
                for timeseries in metric.timeseries:
                    for data_point in timeseries.data:
                        if data_point.total is not None:
                            total += data_point.total
                        elif data_point.average is not None:
                            total += data_point.average
        return total

    @staticmethod
    def __extract_metric_average(
            results: list[MetricsQueryResult],
            metric_name: str,
    ) -> float:
        values = []
        for result in results:
            for metric in result.metrics:
                if metric.name != metric_name:
                    continue
                for timeseries in metric.timeseries:
                    for data_point in timeseries.data:
                        if data_point.average is not None:
                            values.append(data_point.average)

        return sum(values) / len(values) if values else 0.0

    @staticmethod
    def __extract_metric_last(
            results: list[MetricsQueryResult],
            metric_name: str,
    ) -> float:
        last_value = 0.0
        for result in results:
            for metric in result.metrics:
                if metric.name != metric_name:
                    continue
                for timeseries in metric.timeseries:
                    for data_point in timeseries.data:
                        if data_point.average is not None:
                            last_value = data_point.average

        return last_value

    @staticmethod
    def __extract_metric_max(results: list[MetricsQueryResult], metric_name: str) -> float:
        max_value = 0.0
        for result in results:
            for metric in result.metrics:
                if metric.name != metric_name:
                    continue
                for timeseries in metric.timeseries:
                    for data_point in timeseries.data:
                        if data_point.maximum is not None:
                            max_value = max(max_value, data_point.maximum)
        return max_value

    @staticmethod
    def __extract_metric_min(results: list[MetricsQueryResult], metric_name: str) -> float:
        min_value = float("inf")
        for result in results:
            for metric in result.metrics:
                if metric.name != metric_name:
                    continue
                for timeseries in metric.timeseries:
                    for data_point in timeseries.data:
                        if data_point.minimum is not None:
                            min_value = min(min_value, data_point.minimum)
        return min_value if min_value != float("inf") else 0.0

    @staticmethod
    def __sum_rate_metric(
            results: list[MetricsQueryResult],
            metric_name: str,
            granularity_seconds: int = 60
    ) -> float:
        total = 0.0
        for result in results:
            for metric in result.metrics:
                if metric.name != metric_name:
                    continue
                for timeseries in metric.timeseries:
                    for data_point in timeseries.data:
                        if data_point.average is not None:
                            total += data_point.average * granularity_seconds
        return total
