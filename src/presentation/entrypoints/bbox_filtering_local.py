import geopandas as gpd

from src import Config
from src.application.common.monitor import monitor
from src.application.dtos import CostConfiguration
from src.domain.enums import BenchmarkIteration, BoundingBox, DatasetSize
from src.presentation.entrypoints._factory import _build_query_id, _get_dataset_size
from src.presentation.entrypoints._shapefile import download_buildings_shapefile


def bbox_filtering_local() -> None:
    """
    Benchmark: bounding-box filter at neighborhood scale over the buildings
    shapefile, executed locally via GeoPandas. The Shapefile target is the small
    dataset only per Table 4.2.1, so this entrypoint refuses to run at MEDIUM or
    LARGE rather than silently producing comparable numbers. Downloads the
    pre-baked shapefile copy from blob storage before running the timed
    area-filter pipeline.
    """
    dataset_size = _get_dataset_size()
    if dataset_size is not DatasetSize.SMALL:
        raise ValueError(
            f"bbox_filtering_local only supports DatasetSize.SMALL; "
            f"got {dataset_size}. The Shapefile target is small-only per Table 4.2.1."
        )
    download_buildings_shapefile()
    benchmark_fn = _build_benchmark_fn(dataset_size=dataset_size)
    benchmark_fn()


def _build_benchmark_fn(dataset_size: DatasetSize):
    query_id = _build_query_id("bbox-filtering-local", dataset_size)

    @monitor(
        query_id=query_id,
        benchmark_iteration=BenchmarkIteration.BBOX_FILTERING_RESULT_SET_SIZES,
        cost_configuration=CostConfiguration(include_aci=True, include_blob_storage=False)
    )
    def _benchmark() -> None:
        min_lon, min_lat, max_lon, max_lat = BoundingBox.NEIGHBORHOOD_WGS84.value

        gdf = gpd.read_file(
            Config.BUILDINGS_SHAPEFILE,
            bbox=(min_lon, min_lat, max_lon, max_lat),
        )
        gdf = gdf.set_crs(epsg=4326, allow_override=True).to_crs(epsg=25832)
        gdf["area"] = gdf.geometry.area
        gdf = gdf[gdf["area"] > 10]

    return _benchmark
