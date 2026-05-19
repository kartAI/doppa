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

            "src.presentation.entrypoints.db_scan_blob_storage",
            "src.presentation.entrypoints.db_scan_postgis",

            "src.presentation.entrypoints.bbox_filtering_advanced_duckdb",
            "src.presentation.entrypoints.bbox_filtering_advanced_postgis",

            "src.presentation.entrypoints.bbox_filtering_simple_local",
            "src.presentation.entrypoints.bbox_filtering_simple_blob_storage",

            "src.presentation.entrypoints.bbox_filtering_result_set_sizes_neighborhood_duckdb",
            "src.presentation.entrypoints.bbox_filtering_result_set_sizes_municipality_duckdb",
            "src.presentation.entrypoints.bbox_filtering_result_set_sizes_county_duckdb",

            "src.presentation.entrypoints.bbox_filtering_result_set_sizes_neighborhood_postgis",
            "src.presentation.entrypoints.bbox_filtering_result_set_sizes_municipality_postgis",
            "src.presentation.entrypoints.bbox_filtering_result_set_sizes_county_postgis",

            "src.presentation.entrypoints.bbox_filtering_result_set_sizes_neighborhood_local",
            "src.presentation.entrypoints.bbox_filtering_result_set_sizes_municipality_local",
            "src.presentation.entrypoints.bbox_filtering_result_set_sizes_county_local",

            "src.presentation.entrypoints.vector_tiles_single_tile_pmtiles",
            "src.presentation.entrypoints.vector_tiles_single_tile_vmt",

            "src.presentation.entrypoints.vector_tiles_100k_vmt",
            "src.presentation.entrypoints.vector_tiles_100k_pmtiles",

            "src.presentation.entrypoints.spatial_aggregation_grid_duckdb",
            "src.presentation.entrypoints.spatial_aggregation_grid_postgis",

            "src.presentation.entrypoints.attribute_spatial_compound_filter_duckdb",
            "src.presentation.entrypoints.attribute_spatial_compound_filter_postgis",

            "src.presentation.entrypoints.ordered_range_query_duckdb",
            "src.presentation.entrypoints.ordered_range_query_postgis",

            "src.presentation.entrypoints.point_in_polygon_lookup_duckdb",
            "src.presentation.entrypoints.point_in_polygon_lookup_postgis",

            "src.presentation.entrypoints.national_scale_spatial_join_duckdb",
            "src.presentation.entrypoints.national_scale_spatial_join_postgis",

            "src.presentation.entrypoints.national_scale_spatial_join_databricks_2_nodes",
            "src.presentation.entrypoints.national_scale_spatial_join_databricks_4_nodes",
            "src.presentation.entrypoints.national_scale_spatial_join_databricks_8_nodes",

            "src.presentation.entrypoints.setup_benchmarking_framework",

            "src.presentation.endpoints.tile_server"
        ]
    )
