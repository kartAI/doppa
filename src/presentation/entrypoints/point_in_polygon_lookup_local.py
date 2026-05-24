import geopandas as gpd
from shapely.geometry import Point

from src import Config
from src.application.common.monitor import monitor
from src.application.dtos import CostConfiguration
from src.domain.enums import BenchmarkIteration, DatasetSize
from src.presentation.entrypoints._factory import _build_query_id, _get_dataset_size
from src.presentation.entrypoints._shapefile import download_buildings_shapefile


def point_in_polygon_lookup_local() -> None:
    """
    Benchmark: point-in-polygon lookup against the buildings shapefile, executed
    locally via GeoPandas. Tests a single fixed query point against all building
    polygons and returns the containing polygon(s). The Shapefile target is the
    small dataset only per Table 4.2.1.
    """
    dataset_size = _get_dataset_size()
    if dataset_size is not DatasetSize.SMALL:
        raise ValueError(
            f"point_in_polygon_lookup_local only supports DatasetSize.SMALL; "
            f"got {dataset_size}. The Shapefile target is small-only per Table 4.2.1."
        )
    download_buildings_shapefile()
    gdf = gpd.read_file(Config.BUILDINGS_SHAPEFILE).set_crs(epsg=4326, allow_override=True)
    benchmark_fn = _build_benchmark_fn(dataset_size=dataset_size, gdf=gdf)
    benchmark_fn()


def _build_benchmark_fn(dataset_size: DatasetSize, gdf: gpd.GeoDataFrame):
    query_id = _build_query_id("point-in-polygon-lookup-local", dataset_size)

    @monitor(
        query_id=query_id,
        benchmark_iteration=BenchmarkIteration.POINT_IN_POLYGON_LOOKUP,
        cost_configuration=CostConfiguration(include_aci=True, include_blob_storage=False),
    )
    def _benchmark() -> gpd.GeoDataFrame:
        lon, lat = Config.POINT_IN_POLYGON_PROBE_WGS84
        point = Point(lon, lat)
        return gdf[gdf.geometry.contains(point)]

    return _benchmark
