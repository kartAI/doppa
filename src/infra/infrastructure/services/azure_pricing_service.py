from src.application.contracts import IAzurePricingService
from src.application.dtos import (
    AciPricing,
    BlobStoragePricing,
    DatabasePricing,
    DatabricksPricing,
)


class AzurePricingService(IAzurePricingService):
    """
    Hard-coded Azure Norway East pricing (USD) as of 2026.
    All rates are per-second or per-GB unless noted.

    ACI, Blob Storage, and PostgreSQL are deployed in Norway East under the
    same tenant/subscription. Intra-region, intra-tenant data transfers are
    free, so their network egress rates are $0.00.

    Databricks is deployed in Sweden Central (Norway East does not offer
    Databricks). When Databricks executors read GeoParquet from Blob Storage
    in Norway East, the transfer is inter-region egress billed on the blob
    storage side at the intra-Europe cross-region rate (~$0.02/GB).
    See: https://azure.microsoft.com/pricing/details/bandwidth/
         Section "Intra-continental data transfer" → Zone 1 ↔ Zone 1.

    If resources are later moved to different regions, update the egress rates
    to the applicable Azure Bandwidth tier. Norway East is in Zone 1.
    Zone 1 internet egress (Premium Global Network): $0.087/GB (first 10 TB/month).

    Sources:
        ACI compute:       https://azure.microsoft.com/pricing/details/container-instances/
        Blob Storage:      https://azure.microsoft.com/pricing/details/storage/blobs/
        PostgreSQL:        https://azure.microsoft.com/pricing/details/postgresql/flexible-server/
        Bandwidth/egress:  https://azure.microsoft.com/pricing/details/bandwidth/
        Intra-region free: https://learn.microsoft.com/answers/questions/2279946/
                           "Same region + same tenant: No data transfer charges (intra-tenant traffic)."

    Update these constants when Azure publishes new rates or when the
    infrastructure topology changes.
    """

    # ------------------------------------------------------------------
    # ACI — Norway East, Linux containers
    # ACI bills per vCPU-second and per GB-second of allocated resources.
    # Source: https://azure.microsoft.com/pricing/details/container-instances/
    # ------------------------------------------------------------------
    __ACI_VCPU_PER_SECOND: float = 0.0000143
    __ACI_MEMORY_GB_PER_SECOND: float = 0.0000016
    __ACI_NETWORK_EGRESS_PER_GB: float = 0.0  # Free — intra-region, same tenant

    # ------------------------------------------------------------------
    # Blob Storage — LRS, Hot tier, Norway East
    # Operations are priced per 10 000 operations.
    # Source: https://azure.microsoft.com/pricing/details/storage/blobs/
    #         Region: Norway East, Redundancy: LRS, Tier: Hot
    # ------------------------------------------------------------------
    __BLOB_STORAGE_GB_PER_MONTH: float = 0.022  # $0.022  per GB/month
    __BLOB_READ_PER_10K: float = 0.006  # $0.006  per 10 000 read ops
    __BLOB_WRITE_PER_10K: float = 0.065  # $0.065  per 10 000 write ops
    __BLOB_LIST_PER_10K: float = 0.065  # $0.065  per 10 000 list ops
    __BLOB_INGRESS_PER_GB: float = 0.0  # Free inbound (always free on Azure)
    __BLOB_EGRESS_PER_GB: float = 0.0  # Free — intra-region, same tenant
    __BLOB_CROSS_REGION_EGRESS_PER_GB: float = 0.02  # Intra-Europe cross-region (Zone 1 ↔ Zone 1)

    # ------------------------------------------------------------------
    # Azure Databricks — Sweden Central, Standard tier, Jobs Compute
    # Node type: Standard_D4s_v3 (4 vCores, 16 GiB RAM)
    #
    # DBU rate: Standard_D4s_v3 consumes 0.75 DBU/node/hour for Jobs Compute.
    # DBU price: $0.15/DBU-hour (Standard tier, Jobs Compute, Sweden Central).
    # VM cost: Standard_D4s_v3 pay-as-you-go = $0.204/node/hour (Sweden Central).
    #
    # NOTE: Standard tier is retired on October 1, 2026. Existing workspaces
    # are auto-upgraded to Premium on that date. When upgraded, update
    # __DATABRICKS_DBU_PRICE_PER_HOUR to $0.30 (Premium Jobs Compute,
    # Sweden Central).
    #
    # Sources:
    #   https://azure.microsoft.com/pricing/details/databricks/
    #   https://prices.azure.com/api/retail/prices (swedencentral, DSv3 Series)
    # ------------------------------------------------------------------
    __DATABRICKS_DBU_PER_NODE_PER_HOUR: float = 0.75
    __DATABRICKS_DBU_PRICE_PER_HOUR: float = 0.15
    __DATABRICKS_VM_COST_PER_NODE_PER_HOUR: float = 0.204
    __DATABRICKS_NETWORK_EGRESS_PER_GB: float = 0.0  # Free — intra-region, same tenant

    # ------------------------------------------------------------------
    # PostgreSQL Flexible Server — Norway East
    # SKU: General Purpose, Standard_D4ads_v5 (4 vCores, 16 GiB RAM)
    # Source: Azure Portal → doppa-db → Compute + storage (March 2026)
    #
    # Compute: 4 vCores × $86.87/vCore = $347.48/month ÷ 730 h ≈ $0.476/hour
    # Storage: $0.15 per GiB/month (Premium SSD, 128 GiB = $19.33/month)
    # ------------------------------------------------------------------
    __POSTGRES_COMPUTE_PER_SECOND: float = 0.476 / 3600  # ~$0.000132/s
    __POSTGRES_STORAGE_GB_PER_MONTH: float = 0.15  # $0.15 per GiB/month
    __POSTGRES_EGRESS_PER_GB: float = 0.0  # Free — intra-region, same tenant

    def get_aci_pricing(self) -> AciPricing:
        return AciPricing(
            vcpu_per_second=self.__ACI_VCPU_PER_SECOND,
            memory_gb_per_second=self.__ACI_MEMORY_GB_PER_SECOND,
            network_egress_per_gb=self.__ACI_NETWORK_EGRESS_PER_GB,
        )

    def get_blob_storage_pricing(self) -> BlobStoragePricing:
        return BlobStoragePricing(
            read_operation_cost=self.__BLOB_READ_PER_10K / 10_000,
            write_operation_cost=self.__BLOB_WRITE_PER_10K / 10_000,
            list_operation_cost=self.__BLOB_LIST_PER_10K / 10_000,
            storage_gb_per_month=self.__BLOB_STORAGE_GB_PER_MONTH,
            ingress_per_gb=self.__BLOB_INGRESS_PER_GB,
            egress_per_gb=self.__BLOB_EGRESS_PER_GB,
            cross_region_egress_per_gb=self.__BLOB_CROSS_REGION_EGRESS_PER_GB,
        )

    def get_databricks_pricing(self) -> DatabricksPricing:
        return DatabricksPricing(
            dbu_per_node_per_hour=self.__DATABRICKS_DBU_PER_NODE_PER_HOUR,
            dbu_price_per_hour=self.__DATABRICKS_DBU_PRICE_PER_HOUR,
            vm_cost_per_node_per_hour=self.__DATABRICKS_VM_COST_PER_NODE_PER_HOUR,
            network_egress_per_gb=self.__DATABRICKS_NETWORK_EGRESS_PER_GB,
        )

    def get_database_pricing(self) -> DatabasePricing:
        return DatabasePricing(
            compute_per_second=self.__POSTGRES_COMPUTE_PER_SECOND,
            storage_gb_per_month=self.__POSTGRES_STORAGE_GB_PER_MONTH,
            network_egress_per_gb=self.__POSTGRES_EGRESS_PER_GB,
        )
