import argparse
from typing import Optional
from src.domain.enums import DatasetSize
from src.presentation.configuration import initialize_dependencies
from src.presentation.entrypoints import (
    db_scan_blob_storage,
    db_scan_postgis,
    setup_benchmarking_framework,
    bbox_filtering_advanced_postgis,
    bbox_filtering_advanced_duckdb,
    bbox_filtering_simple_local,
    bbox_filtering_simple_blob_storage,
    bbox_filtering_duckdb,
    bbox_filtering_result_set_sizes_municipality_duckdb,
    bbox_filtering_result_set_sizes_county_duckdb,
    bbox_filtering_postgis,
    bbox_filtering_result_set_sizes_municipality_postgis,
    bbox_filtering_result_set_sizes_county_postgis,
    bbox_filtering_local,
    bbox_filtering_result_set_sizes_municipality_local,
    bbox_filtering_result_set_sizes_county_local,
    vector_tiles_single_tile_pmtiles,
    vector_tiles_single_tile_vmt,
    vector_tiles_100k_vmt,
    vector_tiles_100k_pmtiles,
    spatial_aggregation_grid_duckdb,
    spatial_aggregation_grid_postgis,
    attribute_spatial_compound_filter_duckdb,
    attribute_spatial_compound_filter_local,
    attribute_spatial_compound_filter_postgis,
    knn_search_duckdb,
    knn_search_local,
    knn_search_postgis,
    ordered_range_query_duckdb,
    ordered_range_query_postgis,
    point_in_polygon_lookup_duckdb,
    point_in_polygon_lookup_local,
    point_in_polygon_lookup_postgis,
    national_scale_spatial_join_duckdb,
    national_scale_spatial_join_postgis,
    national_scale_spatial_join_databricks_broadcast_2_nodes,
    national_scale_spatial_join_databricks_broadcast_4_nodes,
    national_scale_spatial_join_databricks_broadcast_8_nodes,
    national_scale_spatial_join_databricks_partitioned_2_nodes,
    national_scale_spatial_join_databricks_partitioned_4_nodes,
    national_scale_spatial_join_databricks_partitioned_8_nodes,
)


def benchmark_runner() -> None:
    """
    In-container entrypoint executed by each Azure Container Instance. Parses the
    ``--script-id``, ``--benchmark-run`` and ``--run-id`` CLI arguments, initializes
    the dependency injection container, and dispatches to the matching benchmark
    function in ``src/presentation/entrypoints/``. Raises ``ValueError`` if the
    script ID is unknown.
    """
    script_id, benchmark_run, run_id, dataset_size = _get_args()
    initialize_dependencies(
        run_id=run_id, benchmark_run=benchmark_run, dataset_size=dataset_size
    )

    match script_id:
        case "db-scan-blob-storage":
            db_scan_blob_storage()
            return
        case "db-scan-postgis":
            db_scan_postgis()
            return
        case "bbox-filtering-advanced-duckdb":
            bbox_filtering_advanced_duckdb()
            return
        case "bbox-filtering-advanced-postgis":
            bbox_filtering_advanced_postgis()
            return
        case "bbox-filtering-simple-local":
            bbox_filtering_simple_local()
            return
        case "bbox-filtering-simple-blob-storage":
            bbox_filtering_simple_blob_storage()
            return
        case "bbox-filtering-duckdb":
            bbox_filtering_duckdb()
            return
        case "bbox-filtering-result-set-sizes-municipality-duckdb":
            bbox_filtering_result_set_sizes_municipality_duckdb()
            return
        case "bbox-filtering-result-set-sizes-county-duckdb":
            bbox_filtering_result_set_sizes_county_duckdb()
            return
        case "bbox-filtering-postgis":
            bbox_filtering_postgis()
            return
        case "bbox-filtering-result-set-sizes-municipality-postgis":
            bbox_filtering_result_set_sizes_municipality_postgis()
            return
        case "bbox-filtering-result-set-sizes-county-postgis":
            bbox_filtering_result_set_sizes_county_postgis()
            return
        case "bbox-filtering-local":
            bbox_filtering_local()
            return
        case "bbox-filtering-result-set-sizes-municipality-local":
            bbox_filtering_result_set_sizes_municipality_local()
            return
        case "bbox-filtering-result-set-sizes-county-local":
            bbox_filtering_result_set_sizes_county_local()
            return
        case "vector-tiles-single-tile-pmtiles":
            vector_tiles_single_tile_pmtiles()
            return
        case "vector-tiles-single-tile-vmt":
            vector_tiles_single_tile_vmt()
            return
        case "vector-tiles-100k-pmtiles":
            vector_tiles_100k_pmtiles()
            return
        case "vector-tiles-100k-vmt":
            vector_tiles_100k_vmt()
            return
        case "spatial-aggregation-grid-duckdb":
            spatial_aggregation_grid_duckdb()
            return
        case "spatial-aggregation-grid-postgis":
            spatial_aggregation_grid_postgis()
            return
        case "attribute-spatial-compound-filter-duckdb":
            attribute_spatial_compound_filter_duckdb()
            return
        case "attribute-spatial-compound-filter-local":
            attribute_spatial_compound_filter_local()
            return
        case "attribute-spatial-compound-filter-postgis":
            attribute_spatial_compound_filter_postgis()
            return
        case "knn-search-duckdb":
            knn_search_duckdb()
            return
        case "knn-search-local":
            knn_search_local()
            return
        case "knn-search-postgis":
            knn_search_postgis()
            return
        case "ordered-range-query-duckdb":
            ordered_range_query_duckdb()
            return
        case "ordered-range-query-postgis":
            ordered_range_query_postgis()
            return
        case "point-in-polygon-lookup-duckdb":
            point_in_polygon_lookup_duckdb()
            return
        case "point-in-polygon-lookup-local":
            point_in_polygon_lookup_local()
            return
        case "point-in-polygon-lookup-postgis":
            point_in_polygon_lookup_postgis()
            return
        case "national-scale-spatial-join-duckdb":
            national_scale_spatial_join_duckdb()
            return
        case "national-scale-spatial-join-postgis":
            national_scale_spatial_join_postgis()
            return
        case "national-scale-spatial-join-databricks-broadcast-2-nodes":
            national_scale_spatial_join_databricks_broadcast_2_nodes()
            return
        case "national-scale-spatial-join-databricks-broadcast-4-nodes":
            national_scale_spatial_join_databricks_broadcast_4_nodes()
            return
        case "national-scale-spatial-join-databricks-broadcast-8-nodes":
            national_scale_spatial_join_databricks_broadcast_8_nodes()
            return
        case "national-scale-spatial-join-databricks-partitioned-2-nodes":
            national_scale_spatial_join_databricks_partitioned_2_nodes()
            return
        case "national-scale-spatial-join-databricks-partitioned-4-nodes":
            national_scale_spatial_join_databricks_partitioned_4_nodes()
            return
        case "national-scale-spatial-join-databricks-partitioned-8-nodes":
            national_scale_spatial_join_databricks_partitioned_8_nodes()
            return
        case "setup-framework":
            setup_benchmarking_framework()
            return
        case _:
            raise ValueError("Script ID is invalid")


def _get_args() -> tuple[str, int, Optional[str], DatasetSize]:
    parser = argparse.ArgumentParser("doppa-data")
    parser.add_argument(
        "--script-id",
        required=True,
        help="Script identifier. Must be one of the specified IDs",
    )

    parser.add_argument(
        "--benchmark-run",
        required=True,
        help="Identifier for benchmark iteration. Must be an integer greater than or equal to 1",
    )

    parser.add_argument(
        "--run-id",
        help="Run identifier. Randomly generated and prefixed with today's date",
    )

    parser.add_argument(
        "--dataset-size",
        choices=[size.value for size in DatasetSize],
        default=DatasetSize.SMALL.value,
        help="Dataset tier the benchmark runs against (small/medium/large). Defaults to 'small'.",
    )

    args = parser.parse_args()
    return (
        args.script_id,
        int(args.benchmark_run),
        args.run_id,
        DatasetSize(args.dataset_size),
    )


if __name__ == "__main__":
    benchmark_runner()
