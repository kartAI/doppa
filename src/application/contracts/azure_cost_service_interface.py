import datetime
from abc import abstractmethod, ABC

from src.application.dtos import Cost
from src.domain.enums import BlobOperationType, DatasetSize


class IAzureCostService(ABC):

    @abstractmethod
    def compute_aci_cost(
            self,
            experiment_id: str,
            start_time: datetime.datetime,
            end_time: datetime.datetime,
    ) -> Cost:
        """
        Computes the cost of running the Azure Container Instance benchmark identified by `experiment_id`
        over the given window. The cost is the sum of vCPU compute, memory compute, and network egress
        derived from the ACI usage and pricing.
        :param experiment_id: Script identifier of the benchmark experiment used to look up ACI usage.
        :param start_time: Start of the benchmark window.
        :param end_time: End of the benchmark window.
        :return: Cost DTO with compute, storage, network, operations, and total cost. Storage and
            operations costs are 0 for ACI.
        :rtype: Cost
        """
        raise NotImplementedError

    @abstractmethod
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
        """
        Computes the blob storage cost for the benchmark window. The cost includes prorated storage
        (per-GB/month scaled to the window), per-operation costs for reads/writes/lists, and ingress/egress
        network costs.
        :param start_time: Start of the benchmark window.
        :param end_time: End of the benchmark window.
        :param bytes_ingress: Bytes uploaded to blob storage during the benchmark.
        :param bytes_egress: Bytes downloaded from blob storage during the benchmark.
        :param operation_type: Whether the benchmark performs READ or WRITE operations against blob storage.
        :param dataset_size: Dataset size tier used to count blobs for operation cost estimation.
        :param is_cross_region: When True, uses cross-region egress pricing instead of intra-region.
        :return: Cost DTO with compute, storage, network, operations, and total cost. Compute cost is 0
            for blob storage.
        :rtype: Cost
        """
        raise NotImplementedError

    @abstractmethod
    def compute_database_cost(
            self,
            start_time: datetime.datetime,
            end_time: datetime.datetime,
    ) -> Cost:
        """
        Computes the PostgreSQL Flexible Server cost for the benchmark window. The cost includes compute
        (per-second), prorated storage, and network egress derived from the database usage and pricing.
        :param start_time: Start of the benchmark window.
        :param end_time: End of the benchmark window.
        :return: Cost DTO with compute, storage, network, operations, and total cost. Operations cost
            is 0 for the database.
        :rtype: Cost
        """
        raise NotImplementedError

    @abstractmethod
    def compute_databricks_cost(
            self,
            start_time: datetime.datetime,
            end_time: datetime.datetime,
            num_workers: int,
            bytes_egress: float,
    ) -> Cost:
        """
        Computes the Azure Databricks cost for the benchmark window. The compute cost is the sum of
        DBU charges and VM charges over the run duration, scaled by the number of workers. The network
        cost is derived from the egress bytes and Databricks egress pricing.
        :param start_time: Start of the benchmark window.
        :param end_time: End of the benchmark window.
        :param num_workers: Number of Databricks worker nodes provisioned for the run.
        :param bytes_egress: Bytes egressed from the Databricks cluster during the benchmark.
        :return: Cost DTO with compute, storage, network, operations, and total cost. Storage and
            operations costs are 0 for Databricks.
        :rtype: Cost
        """
        raise NotImplementedError
