import datetime

from src.application.contracts import IAzureCostService, IAzureMetricService, IAzurePricingService
from src.application.dtos import Cost
from src.domain.enums import BlobOperationType, DatasetSize


class AzureCostService(IAzureCostService):
    __azure_metric_service: IAzureMetricService
    __azure_pricing_service: IAzurePricingService

    def __init__(
            self,
            azure_metric_service: IAzureMetricService,
            azure_pricing_service: IAzurePricingService,
    ):
        self.__azure_metric_service = azure_metric_service
        self.__azure_pricing_service = azure_pricing_service

    def compute_aci_cost(
            self,
            experiment_id: str,
            start_time: datetime.datetime,
            end_time: datetime.datetime,
    ) -> Cost:
        usage = self.__azure_metric_service.get_aci_usage(
            script_id=experiment_id,
            start_time=start_time,
            end_time=end_time,
        )
        pricing = self.__azure_pricing_service.get_aci_pricing()

        vcpu_cost = usage.duration_seconds * usage.vcpu_count * pricing.vcpu_per_second
        memory_cost = usage.duration_seconds * usage.memory_gb * pricing.memory_gb_per_second
        compute_cost = vcpu_cost + memory_cost

        egress_gb = usage.bytes_egress / (1024 ** 3)
        network_cost = egress_gb * pricing.network_egress_per_gb

        return Cost(
            compute_cost=compute_cost,
            storage_cost=0.0,
            network_cost=network_cost,
            operations_cost=0.0,
            total_cost=compute_cost + network_cost,
        )

    def compute_blob_storage_cost(
            self,
            start_time: datetime.datetime,
            end_time: datetime.datetime,
            bytes_ingress: float,
            bytes_egress: float,
            operation_type: BlobOperationType,
            dataset_size: DatasetSize = DatasetSize.SMALL,
            is_cross_region: bool = False,
    ) -> Cost:
        usage = self.__azure_metric_service.get_blob_storage_usage(
            start_time=start_time,
            end_time=end_time,
            bytes_ingress=bytes_ingress,
            bytes_egress=bytes_egress,
            operation_type=operation_type,
            dataset_size=dataset_size,
        )
        pricing = self.__azure_pricing_service.get_blob_storage_pricing()

        duration_seconds = (end_time - start_time).total_seconds()
        seconds_per_month = 30.44 * 24 * 3600
        storage_gb = usage.storage_bytes / (1024 ** 3)
        storage_cost = storage_gb * pricing.storage_gb_per_month * (duration_seconds / seconds_per_month)

        operations_cost = (
                usage.read_transactions * pricing.read_operation_cost
                + usage.write_transactions * pricing.write_operation_cost
                + usage.list_transactions * pricing.list_operation_cost
        )

        egress_rate = (
            pricing.cross_region_egress_per_gb if is_cross_region
            else pricing.egress_per_gb
        )
        ingress_gb = usage.bytes_ingress / (1024 ** 3)
        egress_gb = usage.bytes_egress / (1024 ** 3)
        network_cost = (
                ingress_gb * pricing.ingress_per_gb
                + egress_gb * egress_rate
        )

        total = storage_cost + operations_cost + network_cost

        return Cost(
            compute_cost=0.0,
            storage_cost=storage_cost,
            network_cost=network_cost,
            operations_cost=operations_cost,
            total_cost=total,
        )

    def compute_databricks_cost(
            self,
            start_time: datetime.datetime,
            end_time: datetime.datetime,
            num_workers: int,
            bytes_egress: float,
    ) -> Cost:
        usage = self.__azure_metric_service.get_databricks_usage(
            start_time=start_time,
            end_time=end_time,
            num_workers=num_workers,
            bytes_egress=bytes_egress,
        )
        pricing = self.__azure_pricing_service.get_databricks_pricing()

        duration_hours = usage.duration_seconds / 3600
        total_nodes = usage.num_workers + 1  # workers + driver (same VM type)
        dbu_cost = total_nodes * pricing.dbu_per_node_per_hour * pricing.dbu_price_per_hour * duration_hours
        vm_cost = total_nodes * pricing.vm_cost_per_node_per_hour * duration_hours
        compute_cost = dbu_cost + vm_cost

        egress_gb = usage.bytes_egress / (1024 ** 3)
        network_cost = egress_gb * pricing.network_egress_per_gb

        return Cost(
            compute_cost=compute_cost,
            storage_cost=0.0,
            network_cost=network_cost,
            operations_cost=0.0,
            total_cost=compute_cost + network_cost,
        )

    def compute_database_cost(
            self,
            start_time: datetime.datetime,
            end_time: datetime.datetime,
    ) -> Cost:
        usage = self.__azure_metric_service.get_database_usage(
            start_time=start_time,
            end_time=end_time,
        )
        pricing = self.__azure_pricing_service.get_database_pricing()

        compute_cost = usage.duration_seconds * pricing.compute_per_second

        seconds_per_month = 30.44 * 24 * 3600
        storage_gb = usage.storage_used_bytes / (1024 ** 3)
        storage_cost = storage_gb * pricing.storage_gb_per_month * (usage.duration_seconds / seconds_per_month)

        egress_gb = usage.network_egress_bytes / (1024 ** 3)
        network_cost = egress_gb * pricing.network_egress_per_gb

        total = compute_cost + storage_cost + network_cost

        return Cost(
            compute_cost=compute_cost,
            storage_cost=storage_cost,
            network_cost=network_cost,
            operations_cost=0.0,
            total_cost=total,
        )
