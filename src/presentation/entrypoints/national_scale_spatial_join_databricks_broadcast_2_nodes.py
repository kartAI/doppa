from dependency_injector.wiring import Provide, inject

from src.application.contracts import IDatabricksService
from src.infra.infrastructure import Containers
from src.presentation.entrypoints._databricks_benchmark_runner import (
    run_databricks_national_scale_spatial_join,
)


@inject
def national_scale_spatial_join_databricks_broadcast_2_nodes(
    databricks_service: IDatabricksService = Provide[Containers.databricks_service],
) -> None:
    """
    Benchmark: national-scale spatial join between Norwegian municipalities and the
    configured buildings dataset size executed on Azure Databricks with a 2-worker
    cluster, using the explicit broadcast join strategy (small-side broadcast hint
    via ``broadcast(municipalities_df)``). The dataset size is pulled from DI inside
    ``run_databricks_national_scale_spatial_join``. The cluster is provisioned once,
    every warmup and timed iteration runs against it, and the cluster is terminated
    after the benchmark completes.
    """
    run_databricks_national_scale_spatial_join(
        databricks_service=databricks_service,
        num_workers=2,
        notebook_variant="broadcast",
    )
