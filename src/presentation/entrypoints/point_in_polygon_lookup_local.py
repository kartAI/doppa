import random

import geopandas as gpd
from shapely.geometry import Point, box

from src import Config
from src.application.common.monitor import monitor
from src.application.dtos import CostConfiguration
from src.domain.enums import BenchmarkIteration, BoundingBox, DatasetSize
from src.presentation.entrypoints._factory import _build_query_id, _get_dataset_size
from src.presentation.entrypoints._shapefile import download_buildings_shapefile


def point_in_polygon_lookup_local() -> None:
    """
    Benchmark: point-in-polygon lookups against the buildings shapefile, executed
    locally via GeoPandas. The Shapefile target is the small dataset only per
    Table 4.2.1, so this entrypoint refuses to run at MEDIUM or LARGE rather than
    silently producing comparable numbers. Downloads the pre-baked shapefile copy
    from blob storage, generates a mix of probe points guaranteed to fall inside
    buildings and uniformly random points within the Trondheim bounding box (which
    may or may not land on a building) up front, then times per-point
    ``contains`` counts.
    """
    dataset_size = _get_dataset_size()
    if dataset_size is not DatasetSize.SMALL:
        raise ValueError(
            f"point_in_polygon_lookup_local only supports DatasetSize.SMALL; "
            f"got {dataset_size}. The Shapefile target is small-only per Table 4.2.1."
        )
    download_buildings_shapefile()
    gdf = gpd.read_file(Config.BUILDINGS_SHAPEFILE).set_crs(epsg=4326, allow_override=True)
    points = _generate_points(gdf=gdf)
    benchmark_fn = _build_benchmark_fn(dataset_size=dataset_size, gdf=gdf)
    benchmark_fn(points=points)


def _generate_points(gdf: gpd.GeoDataFrame) -> list[tuple[float, float]]:
    min_lon, min_lat, max_lon, max_lat = BoundingBox.TRONDHEIM_WGS84.value
    n_inside = int(Config.POINT_IN_POLYGON_TOTAL_POINTS * Config.POINT_IN_POLYGON_INSIDE_RATIO)
    n_random = Config.POINT_IN_POLYGON_TOTAL_POINTS - n_inside

    envelope = box(min_lon, min_lat, max_lon, max_lat)
    inside_buildings = gdf[gdf.geometry.is_valid & gdf.geometry.intersects(envelope)]
    inside_reps = inside_buildings.geometry.representative_point()
    inside_sorted = sorted(
        ((pt.x, pt.y) for pt in inside_reps), key=lambda p: (p[0], p[1])
    )
    inside_points = inside_sorted[:n_inside]

    rng = random.Random(Config.POINT_IN_POLYGON_PROBE_SEED)
    random_bbox_points = [
        (rng.uniform(min_lon, max_lon), rng.uniform(min_lat, max_lat))
        for _ in range(n_random)
    ]

    combined = list(inside_points) + random_bbox_points
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
