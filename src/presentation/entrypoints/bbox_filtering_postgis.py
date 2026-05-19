from dependency_injector.wiring import Provide, inject
from sqlalchemy import Engine, text

from src.application.common.monitor import monitor
from src.application.dtos import CostConfiguration
from src.domain.enums import BenchmarkIteration, BoundingBox, DatasetSize
from src.infra.infrastructure import Containers
from src.presentation.entrypoints._factory import _build_query_id, _get_dataset_size


@inject
def bbox_filtering_postgis(
    db_context: Engine = Provide[Containers.postgres_context],
) -> None:
    """
    Benchmark: bounding-box filter at neighborhood scale on the buildings dataset
    using PostGIS. The dataset size is pulled from DI and parameterises the buildings
    table reference. Filters ``buildings_{size}`` by bbox intersection and a minimum
    projected area in EPSG:25832.
    """
    dataset_size = _get_dataset_size()
    benchmark_fn = _build_benchmark_fn(dataset_size=dataset_size)
    benchmark_fn(db_context=db_context)


def _build_benchmark_fn(dataset_size: DatasetSize):
    query_id = _build_query_id("bbox-filtering-postgis", dataset_size)
    buildings_table = f"buildings_{dataset_size.value}"

    @monitor(
        query_id=query_id,
        benchmark_iteration=BenchmarkIteration.BBOX_FILTERING_RESULT_SET_SIZES,
        cost_configuration=CostConfiguration(include_aci=True, include_postgres=True)
    )
    def _benchmark(
        db_context: Engine,
    ) -> list:
        min_lon, min_lat, max_lon, max_lat = BoundingBox.NEIGHBORHOOD_WGS84.value

        sql = text(
            f"""
            SELECT *, ST_Area(ST_Transform(geometry, 25832)) AS area
            FROM {buildings_table}
            WHERE ST_Intersects(
                geometry,
                ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)
            )
            AND ST_Area(ST_Transform(geometry, 25832)) > 10;
            """
        )

        with db_context.connect() as conn:
            return conn.execute(
                sql,
                {
                    "min_lon": min_lon,
                    "min_lat": min_lat,
                    "max_lon": max_lon,
                    "max_lat": max_lat,
                },
            ).fetchall()

    return _benchmark
