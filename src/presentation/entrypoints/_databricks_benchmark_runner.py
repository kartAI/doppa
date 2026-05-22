from typing import Literal

from src.application.common.monitor import monitor
from src.application.contracts import IDatabricksService
from src.application.dtos import CostConfiguration, DatabricksRunResult
from src.domain.enums import BenchmarkIteration, DatasetSize
from src.presentation.entrypoints._factory import _build_query_id, _get_dataset_size


NotebookVariant = Literal["broadcast", "partitioned", "default"]


def run_databricks_national_scale_spatial_join(
    databricks_service: IDatabricksService,
    num_workers: int,
    notebook_variant: NotebookVariant,
) -> None:
    """
    Provision a Databricks cluster once, run the national-scale spatial join benchmark
    (warmup + timed iterations) against it for the active dataset size pulled from DI,
    then terminate the cluster.

    Cluster provisioning happens outside the ``@monitor`` timing window. Warmup runs
    execute on the same cluster but before ``@monitor`` opens its cost window, so both
    reported elapsed time and reported cost cover the timed iterations only, on an
    already-warm engine. ``query_id`` encodes ``notebook_variant``, ``num_workers``,
    and (when not ``SMALL``) ``dataset_size`` so each strategy/worker/size combination
    is keyed unambiguously.
    """
    dataset_size = _get_dataset_size()
    cluster_id = databricks_service.create_cluster(
        num_workers=num_workers, notebook_variant=notebook_variant
    )
    try:
        benchmark_fn = _build_benchmark_fn(
            num_workers=num_workers,
            dataset_size=dataset_size,
            notebook_variant=notebook_variant,
        )
        benchmark_fn(
            cluster_id=cluster_id,
            num_workers=num_workers,
            dataset_size=dataset_size,
            notebook_variant=notebook_variant,
            databricks_service=databricks_service,
        )
    finally:
        databricks_service.terminate_cluster(cluster_id=cluster_id)


def _build_benchmark_fn(
    num_workers: int,
    dataset_size: DatasetSize,
    notebook_variant: NotebookVariant,
):
    query_id = _build_query_id(
        f"national-scale-spatial-join-databricks-{notebook_variant}-{num_workers}-nodes",
        dataset_size,
    )

    @monitor(
        query_id=query_id,
        benchmark_iteration=BenchmarkIteration.NATIONAL_SCALE_SPATIAL_JOIN,
        cost_configuration=CostConfiguration(
            include_aci=True, include_databricks=True, num_workers=num_workers
        ),
        skip_warmup=False,
        elapsed_from_result=True,
        use_sequential_stopping=False,
        warmup_iterations=1,
    )
    def _benchmark(
        cluster_id: str,
        num_workers: int,
        dataset_size: DatasetSize,
        notebook_variant: NotebookVariant,
        databricks_service: IDatabricksService,
    ) -> DatabricksRunResult:
        return databricks_service.submit_to_existing_cluster(
            cluster_id=cluster_id,
            num_workers=num_workers,
            dataset_size=dataset_size,
            notebook_variant=notebook_variant,
        )

    return _benchmark
