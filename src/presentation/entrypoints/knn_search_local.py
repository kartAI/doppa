import warnings

import geopandas as gpd
from shapely.geometry import Point

from src import Config
from src.application.common.monitor import monitor
from src.application.dtos import CostConfiguration
from src.domain.enums import BenchmarkIteration, DatasetSize
from src.presentation.entrypoints._factory import _build_query_id, _get_dataset_size
from src.presentation.entrypoints._shapefile import download_buildings_shapefile


def knn_search_local() -> None:
    """
    Benchmark: k-nearest-neighbour search against the buildings shapefile, executed
    locally via GeoPandas. The Shapefile target is the small dataset only per
    Table 4.2.1, so this entrypoint refuses to run at MEDIUM or LARGE rather than
    silently producing comparable numbers. Downloads the pre-baked shapefile copy
    from blob storage, then ranks rows by planar distance to the fixed
    Trondheim-center reference point and returns the ten nearest. Distance is
    computed in lon/lat degrees on EPSG:4326 geometry to match the DuckDB
    ``ST_Distance`` and PostGIS ``<->`` semantics used by the peer entrypoints.
    """
    dataset_size = _get_dataset_size()
    if dataset_size is not DatasetSize.SMALL:
        raise ValueError(
            f"knn_search_local only supports DatasetSize.SMALL; "
            f"got {dataset_size}. The Shapefile target is small-only per Table 4.2.1."
        )
    download_buildings_shapefile()
    benchmark_fn = _build_benchmark_fn(dataset_size=dataset_size)
    benchmark_fn()


def _build_benchmark_fn(dataset_size: DatasetSize):
    query_id = _build_query_id("knn-search-local", dataset_size)

    @monitor(
        query_id=query_id,
        benchmark_iteration=BenchmarkIteration.KNN_SEARCH,
        cost_configuration=CostConfiguration(include_aci=True, include_blob_storage=False),
    )
    def _benchmark() -> gpd.GeoDataFrame:
        lon, lat = Config.TRONDHEIM_CENTER_WGS84
        reference = Point(lon, lat)

        gdf = gpd.read_file(Config.BUILDINGS_SHAPEFILE)
        gdf = gdf.set_crs(epsg=4326, allow_override=True)

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Geometry is in a geographic CRS",
                category=UserWarning,
            )
            distances = gdf.geometry.distance(reference)
        nearest_idx = distances.nsmallest(Config.KNN_SEARCH_K).index
        return gdf.loc[nearest_idx]

    return _benchmark
