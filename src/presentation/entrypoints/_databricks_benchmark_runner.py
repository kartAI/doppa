from src.application.common.monitor import monitor
from src.application.contracts import IDatabricksService
from src.application.dtos import CostConfiguration, DatabricksRunResult
from src.domain.enums import BenchmarkIteration, DatasetSize


def run_databricks_national_scale_spatial_join(
    databricks_service: IDatabricksService,
    num_workers: int,
    dataset_size: DatasetSize,
) -> None:
    """
    Provision a Databricks cluster once, run the national-scale spatial join benchmark
    (warmup + timed iterations) against it for the given dataset size, then terminate the
    cluster.

    Cluster provisioning happens outside the ``@monitor`` timing window so reported elapsed
    time and reported cost both cover the same span: warmup + timed iterations on a warm
    engine. ``query_id`` encodes ``num_workers`` and (when not ``SMALL``) ``dataset_size``
    so results are keyed unambiguously without renaming existing small-dataset rows.
    """
    cluster_id = databricks_service.create_cluster(num_workers=num_workers)
    try:
        benchmark_fn = _build_benchmark_fn(
            num_workers=num_workers, dataset_size=dataset_size
        )
        benchmark_fn(
            cluster_id=cluster_id,
            num_workers=num_workers,
            dataset_size=dataset_size,
            databricks_service=databricks_service,
        )
    finally:
        databricks_service.terminate_cluster(cluster_id=cluster_id)


def _build_benchmark_fn(num_workers: int, dataset_size: DatasetSize):
    query_id = f"national-scale-spatial-join-databricks-{num_workers}-nodes"
    if dataset_size is not DatasetSize.SMALL:
        query_id += f"-{dataset_size.value}"

    @monitor(
        query_id=query_id,
        benchmark_iteration=BenchmarkIteration.NATIONAL_SCALE_SPATIAL_JOIN,
        cost_configuration=CostConfiguration(
            include_aci=True, include_databricks=True, num_workers=num_workers
        ),
        skip_warmup=False,
        elapsed_from_result=True,
    )
    def _benchmark(
        cluster_id: str,
        num_workers: int,
        dataset_size: DatasetSize,
        databricks_service: IDatabricksService,
    ) -> DatabricksRunResult:
        return databricks_service.submit_to_existing_cluster(
            cluster_id=cluster_id,
            num_workers=num_workers,
            dataset_size=dataset_size,
        )

    return _benchmark
