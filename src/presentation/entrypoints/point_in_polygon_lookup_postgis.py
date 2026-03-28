import random

from dependency_injector.wiring import Provide, inject
from sqlalchemy import Engine, text

from src.application.common.monitor_network import monitor_network
from src.application.dtos import CostConfiguration
from src.domain.enums import BenchmarkIteration, BoundingBox
from src.infra.infrastructure import Containers

TOTAL_POINTS: int = 10
INSIDE_RATIO: float = 0.3
SEED: int = 42


@inject
def point_in_polygon_lookup_postgis(
        db_context: Engine = Provide[Containers.postgres_context],
) -> None:
    points = _generate_points(db_context=db_context)
    _benchmark(points=points)


def _generate_points(db_context: Engine) -> list[tuple[float, float]]:
    min_lon, min_lat, max_lon, max_lat = BoundingBox.TRONDHEIM_WGS84.value
    n_inside = int(TOTAL_POINTS * INSIDE_RATIO)
    n_outside = TOTAL_POINTS - n_inside

    sql = text(
        """
        SELECT ST_X(ST_Centroid(geometry)) AS lon, ST_Y(ST_Centroid(geometry)) AS lat
        FROM buildings
        WHERE ST_Intersects(geometry, ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326))
          AND ST_IsValid(geometry)
        ORDER BY lon, lat
        LIMIT :limit
        """
    )

    with db_context.connect() as conn:
        rows = conn.execute(sql, {
            "min_lon": min_lon, "min_lat": min_lat,
            "max_lon": max_lon, "max_lat": max_lat,
            "limit": n_inside,
        }).fetchall()

    inside_points = [(row[0], row[1]) for row in rows]

    rng = random.Random(SEED)
    outside_points = [
        (rng.uniform(min_lon, max_lon), rng.uniform(min_lat, max_lat))
        for _ in range(n_outside)
    ]

    combined = inside_points + outside_points
    rng.shuffle(combined)
    return combined


@inject
@monitor_network(
    query_id="point-in-polygon-lookup-postgis",
    benchmark_iteration=BenchmarkIteration.POINT_IN_POLYGON_LOOKUP,
    cost_configuration=CostConfiguration(include_aci=True, include_postgres=True)
)
def _benchmark(
        points: list[tuple[float, float]],
        db_context: Engine = Provide[Containers.postgres_context],
) -> None:
    sql = text(
        """
        SELECT COUNT(*)
        FROM buildings
        WHERE ST_Contains(geometry, ST_SetSRID(ST_Point(:lon, :lat), 4326))
        """
    )

    with db_context.connect() as conn:
        for lon, lat in points:
            conn.execute(sql, {"lon": lon, "lat": lat})
