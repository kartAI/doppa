import geopandas as gpd
from shapely.geometry import box

from src import Config
from src.application.common.monitor import monitor
from src.application.dtos import CostConfiguration
from src.domain.enums import BenchmarkIteration, BoundingBox, DataSource, DatasetSize
from src.presentation.entrypoints._factory import _build_query_id, _get_dataset_size
from src.presentation.entrypoints._shapefile import download_buildings_shapefile


def attribute_spatial_compound_filter_local() -> None:
    """
    Benchmark: compound attribute + spatial filter on the buildings shapefile,
    executed locally via GeoPandas. The Shapefile target is the small dataset only
    per Table 4.2.1, so this entrypoint refuses to run at MEDIUM or LARGE rather
    than silently producing comparable numbers. Downloads the pre-baked shapefile
    copy from blob storage and selects OSM-sourced buildings that intersect the
    neighborhood-scale bounding box.
    """
    dataset_size = _get_dataset_size()
    if dataset_size is not DatasetSize.SMALL:
        raise ValueError(
            f"attribute_spatial_compound_filter_local only supports DatasetSize.SMALL; "
            f"got {dataset_size}. The Shapefile target is small-only per Table 4.2.1."
        )
    download_buildings_shapefile()
    benchmark_fn = _build_benchmark_fn(dataset_size=dataset_size)
    benchmark_fn()


def _build_benchmark_fn(dataset_size: DatasetSize):
    query_id = _build_query_id("attribute-spatial-compound-filter-local", dataset_size)

    @monitor(
        query_id=query_id,
        benchmark_iteration=BenchmarkIteration.ATTRIBUTE_SPATIAL_COMPOUND_FILTER,
        cost_configuration=CostConfiguration(include_aci=True, include_blob_storage=False),
    )
    def _benchmark() -> gpd.GeoDataFrame:
        min_lon, min_lat, max_lon, max_lat = BoundingBox.NEIGHBORHOOD_WGS84.value
        envelope = box(min_lon, min_lat, max_lon, max_lat)

        gdf = gpd.read_file(Config.BUILDINGS_SHAPEFILE).set_crs(epsg=4326, allow_override=True)
        return gdf[(gdf["source"] == DataSource.OSM.value) & gdf.geometry.intersects(envelope)]

    return _benchmark
