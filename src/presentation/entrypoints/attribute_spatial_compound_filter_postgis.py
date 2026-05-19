from dependency_injector.wiring import Provide, inject
from sqlalchemy import Engine, text

from src.application.common.monitor import monitor
from src.application.dtos import CostConfiguration
from src.domain.enums import BenchmarkIteration, BoundingBox, DataSource, DatasetSize
from src.infra.infrastructure import Containers
from src.presentation.entrypoints._factory import _build_query_id, _get_dataset_size


@inject
def attribute_spatial_compound_filter_postgis(
    db_context: Engine = Provide[Containers.postgres_context],
) -> list:
    """
    Benchmark: compound attribute + spatial filter on the buildings dataset using
    PostGIS. The dataset size is pulled from DI and parameterises the buildings table
    reference. Selects OSM-sourced buildings that intersect the neighborhood-scale
    bounding box from the seeded ``buildings_{size}`` table.
    """
    dataset_size = _get_dataset_size()
    benchmark_fn = _build_benchmark_fn(dataset_size=dataset_size)
    return benchmark_fn(db_context=db_context)


def _build_benchmark_fn(dataset_size: DatasetSize):
    query_id = _build_query_id("attribute-spatial-compound-filter-postgis", dataset_size)
    buildings_table = f"buildings_{dataset_size.value}"

    @monitor(
        query_id=query_id,
        benchmark_iteration=BenchmarkIteration.ATTRIBUTE_SPATIAL_COMPOUND_FILTER,
        cost_configuration=CostConfiguration(include_aci=True, include_postgres=True)
    )
    def _benchmark(
        db_context: Engine,
    ) -> list:
        min_lon, min_lat, max_lon, max_lat = BoundingBox.NEIGHBORHOOD_WGS84.value

        sql = text(
            f"""
            SELECT *
            FROM {buildings_table}
            WHERE source = :source
              AND ST_Intersects(
                    geometry,
                    ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)
                  );
            """
        )

        with db_context.connect() as conn:
            return conn.execute(sql, {
                "source": DataSource.OSM.value,
                "min_lon": min_lon, "min_lat": min_lat,
                "max_lon": max_lon, "max_lat": max_lat,
            }).fetchall()

    return _benchmark
