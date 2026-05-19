import random

from dependency_injector.wiring import Provide, inject
from sqlalchemy import Engine, text

from src import Config
from src.application.common.monitor import monitor
from src.application.dtos import CostConfiguration
from src.domain.enums import BenchmarkIteration, BoundingBox, DatasetSize
from src.infra.infrastructure import Containers
from src.presentation.entrypoints._factory import _build_query_id, _get_dataset_size


@inject
def point_in_polygon_lookup_postgis(
    db_context: Engine = Provide[Containers.postgres_context],
) -> None:
    """
    Benchmark: point-in-polygon lookups against the seeded ``buildings_{size}`` table
    using PostGIS. The dataset size is pulled from DI and parameterises the buildings
    table reference. Generates a mix of probe points guaranteed to fall inside
    buildings and uniformly random points within the Trondheim bounding box (which
    may or may not land on a building) up front, then times per-point
    ``ST_Contains`` counts.
    """
    dataset_size = _get_dataset_size()
    points = _generate_points(db_context=db_context, dataset_size=dataset_size)
    benchmark_fn = _build_benchmark_fn(dataset_size=dataset_size)
    benchmark_fn(points=points, db_context=db_context)


def _generate_points(
    db_context: Engine, dataset_size: DatasetSize
) -> list[tuple[float, float]]:
    min_lon, min_lat, max_lon, max_lat = BoundingBox.TRONDHEIM_WGS84.value
    n_inside = int(Config.POINT_IN_POLYGON_TOTAL_POINTS * Config.POINT_IN_POLYGON_INSIDE_RATIO)
    n_random = Config.POINT_IN_POLYGON_TOTAL_POINTS - n_inside

    buildings_table = f"buildings_{dataset_size.value}"

    # TODO: See if this query can be improved in terms of efficiency
    sql = text(f"""
        WITH buildings_with_point_on_surface AS (
            SELECT *, ST_PointOnSurface(geometry) AS point_on_surface FROM {buildings_table}
        ),

        buildings_inside AS(
            SELECT
                ST_X(bpof.point_on_surface) AS lon,
                ST_Y(bpof.point_on_surface) AS lat
            FROM buildings_with_point_on_surface bpof
            WHERE ST_Intersects(geometry, ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)) AND ST_IsValid(geometry)
            ORDER BY lon, lat
            LIMIT :limit
        )

        SELECT * FROM buildings_inside;
        """)

    with db_context.connect() as conn:
        rows = conn.execute(
            sql,
            {
                "min_lon": min_lon,
                "min_lat": min_lat,
                "max_lon": max_lon,
                "max_lat": max_lat,
                "limit": n_inside,
            },
        ).fetchall()

    inside_points = [(row[0], row[1]) for row in rows]

    # TODO: Explore comments from https://github.com/kartAI/doppa/pull/196
    rng = random.Random(Config.POINT_IN_POLYGON_PROBE_SEED)
    random_bbox_points = [
        (rng.uniform(min_lon, max_lon), rng.uniform(min_lat, max_lat))
        for _ in range(n_random)
    ]

    combined = inside_points + random_bbox_points
    rng.shuffle(combined)
    return combined


def _build_benchmark_fn(dataset_size: DatasetSize):
    query_id = _build_query_id("point-in-polygon-lookup-postgis", dataset_size)
    buildings_table = f"buildings_{dataset_size.value}"

    @monitor(
        query_id=query_id,
        benchmark_iteration=BenchmarkIteration.POINT_IN_POLYGON_LOOKUP,
        cost_configuration=CostConfiguration(include_aci=True, include_postgres=True),
    )
    def _benchmark(
        points: list[tuple[float, float]],
        db_context: Engine,
    ) -> list:
        sql = text(f"""
            SELECT COUNT(*)
            FROM {buildings_table}
            WHERE ST_Contains(geometry, ST_SetSRID(ST_Point(:lon, :lat), 4326))
            """)

        results: list = []
        with db_context.connect() as conn:
            for lon, lat in points:
                results.append(conn.execute(sql, {"lon": lon, "lat": lat}).scalar_one())
        return results

    return _benchmark
