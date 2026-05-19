import random

import geopandas as gpd
from dependency_injector.wiring import Provide, inject
from shapely.geometry import Point, box

from src import Config
from src.application.common.monitor import monitor
from src.application.contracts import IBlobStorageService
from src.application.dtos import CostConfiguration
from src.domain.enums import StorageContainer, BenchmarkIteration, BoundingBox, DatasetSize
from src.infra.infrastructure import Containers
from src.presentation.entrypoints._factory import _build_query_id, _get_dataset_size


def point_in_polygon_lookup_local() -> None:
    """
    Benchmark: point-in-polygon lookups against the buildings shapefile, executed
    locally via GeoPandas. The Shapefile target is the small dataset only per
    Table 4.2.1, so this entrypoint refuses to run at MEDIUM or LARGE rather than
    silently producing comparable numbers. Downloads the pre-baked shapefile copy
    from blob storage, generates a mix of inside and outside Trondheim-area points
    up front, then times per-point ``contains`` counts.
    """
    dataset_size = _get_dataset_size()
    if dataset_size is not DatasetSize.SMALL:
        raise ValueError(
            f"point_in_polygon_lookup_local only supports DatasetSize.SMALL; "
            f"got {dataset_size}. The Shapefile target is small-only per Table 4.2.1."
        )
    _download_data()
    gdf = gpd.read_file(Config.BUILDINGS_SHAPEFILE).set_crs(epsg=4326, allow_override=True)
    points = _generate_points(gdf=gdf)
    benchmark_fn = _build_benchmark_fn(dataset_size=dataset_size, gdf=gdf)
    benchmark_fn(points=points)


def _generate_points(gdf: gpd.GeoDataFrame) -> list[tuple[float, float]]:
    min_lon, min_lat, max_lon, max_lat = BoundingBox.TRONDHEIM_WGS84.value
    n_inside = int(Config.POINT_IN_POLYGON_TOTAL_POINTS * Config.POINT_IN_POLYGON_INSIDE_RATIO)
    n_outside = Config.POINT_IN_POLYGON_TOTAL_POINTS - n_inside

    envelope = box(min_lon, min_lat, max_lon, max_lat)
    inside_buildings = gdf[gdf.geometry.is_valid & gdf.geometry.intersects(envelope)]
    inside_reps = inside_buildings.geometry.representative_point()
    inside_sorted = sorted(
        ((pt.x, pt.y) for pt in inside_reps), key=lambda p: (p[0], p[1])
    )
    inside_points = inside_sorted[:n_inside]

    rng = random.Random(Config.POINT_IN_POLYGON_PROBE_SEED)
    outside_points = [
        (rng.uniform(min_lon, max_lon), rng.uniform(min_lat, max_lat))
        for _ in range(n_outside)
    ]

    combined = list(inside_points) + outside_points
    rng.shuffle(combined)
    return combined


def _build_benchmark_fn(dataset_size: DatasetSize, gdf: gpd.GeoDataFrame):
    query_id = _build_query_id("point-in-polygon-lookup-local", dataset_size)

    @monitor(
        query_id=query_id,
        benchmark_iteration=BenchmarkIteration.POINT_IN_POLYGON_LOOKUP,
        cost_configuration=CostConfiguration(include_aci=True, include_blob_storage=False),
    )
    def _benchmark(points: list[tuple[float, float]]) -> list[int]:
        results: list[int] = []
        for lon, lat in points:
            results.append(int(gdf.geometry.contains(Point(lon, lat)).sum()))
        return results

    return _benchmark


@inject
def _download_data(
    blob_storage_service: IBlobStorageService = Provide[Containers.blob_storage_service],
) -> None:
    Config.BUILDINGS_SHAPEFILE.parent.mkdir(parents=True, exist_ok=True)

    blob_prefix = "copies/shapefile"
    base = Config.BUILDINGS_SHAPEFILE.with_suffix("")
    for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix"):
        blob_name = f"{blob_prefix}/{base.name}{ext}"
        data = blob_storage_service.download_file(
            container_name=StorageContainer.DATA,
            blob_name=blob_name,
        )
        if data is not None:
            base.with_suffix(ext).write_bytes(data)
