from src.domain.enums import DatasetSize
from src.infra.infrastructure import Containers


def initialize_dependencies(
    run_id: str, benchmark_run: int, dataset_size: DatasetSize
) -> None:
    """
    Initializes the dependency-injection container and wires it into every module that resolves
    services via `@inject`. Sets the runtime identifiers `run_id`, `benchmark_run`, and
    `dataset_size` as DI configuration so they can be injected into the monitoring utilities.
    :param run_id: Identifier for the current benchmark run, propagated to all monitored entrypoints.
    :param benchmark_run: Iteration counter for the run within the broader benchmark suite.
    :param dataset_size: Dataset tier (small/medium/large) for the current benchmark execution.
    :return: None
    """
    container = Containers()

    container.config.run_id.from_value(run_id)
    container.config.benchmark_run.from_value(benchmark_run)
    container.config.dataset_size.from_value(dataset_size.value)

    container.wire(
        modules=[
            "src.application.common.monitor_utils",
            "src.application.common.monitor",

            "src.presentation.entrypoints._factory",
            "src.presentation.entrypoints._shapefile",

            "src.presentation.entrypoints.bbox_filtering_duckdb",
            "src.presentation.entrypoints.bbox_filtering_postgis",
            "src.presentation.entrypoints.bbox_filtering_local",

            "src.presentation.entrypoints.knn_search_duckdb",
            "src.presentation.entrypoints.knn_search_local",
            "src.presentation.entrypoints.knn_search_postgis",

            "src.presentation.entrypoints.point_in_polygon_lookup_duckdb",
            "src.presentation.entrypoints.point_in_polygon_lookup_local",
            "src.presentation.entrypoints.point_in_polygon_lookup_postgis",

            "src.presentation.entrypoints.national_scale_spatial_join_duckdb",
            "src.presentation.entrypoints.national_scale_spatial_join_postgis",

            "src.presentation.entrypoints.national_scale_spatial_join_databricks_broadcast_2_nodes",
            "src.presentation.entrypoints.national_scale_spatial_join_databricks_broadcast_4_nodes",
            "src.presentation.entrypoints.national_scale_spatial_join_databricks_broadcast_8_nodes",
            "src.presentation.entrypoints.national_scale_spatial_join_databricks_broadcast_12_nodes",
            "src.presentation.entrypoints.national_scale_spatial_join_databricks_broadcast_16_nodes",
            "src.presentation.entrypoints.national_scale_spatial_join_databricks_partitioned_2_nodes",
            "src.presentation.entrypoints.national_scale_spatial_join_databricks_partitioned_4_nodes",
            "src.presentation.entrypoints.national_scale_spatial_join_databricks_partitioned_8_nodes",
            "src.presentation.entrypoints.national_scale_spatial_join_databricks_partitioned_12_nodes",
            "src.presentation.entrypoints.national_scale_spatial_join_databricks_partitioned_16_nodes",
            "src.presentation.entrypoints.national_scale_spatial_join_databricks_default_2_nodes",
            "src.presentation.entrypoints.national_scale_spatial_join_databricks_default_8_nodes",
            "src.presentation.entrypoints.national_scale_spatial_join_databricks_default_16_nodes",

            "src.presentation.entrypoints.setup_benchmarking_framework",

            "src.presentation.endpoints.tile_server"
        ]
    )
