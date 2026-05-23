import geopandas as gpd
from dependency_injector.wiring import Provide, inject
from duckdb import DuckDBPyConnection
from shapely import from_wkb
from sqlalchemy import Engine, text

from src import Config
from src.application.common import logger
from src.application.common.monitor import monitor
from src.application.dtos import CostConfiguration
from src.domain.enums import StorageContainer, BenchmarkIteration, EPSGCode, DatasetSize
from src.infra.infrastructure import Containers
from src.presentation.entrypoints._factory import _build_query_id, _get_dataset_size


@inject
def national_scale_spatial_join_postgis(
    duckdb_context: DuckDBPyConnection = Provide[Containers.duckdb_context],
    postgres_context: Engine = Provide[Containers.postgres_context],
) -> None:
    """
    Benchmark: national-scale spatial join between Norwegian municipalities and the
    buildings dataset using PostGIS. The dataset size is pulled from DI and
    parameterises the buildings table reference. Seeds the ``municipalities`` table
    from blob storage via DuckDB before running the timed per-municipality building
    count aggregation.
    """
    dataset_size = _get_dataset_size()
    _seed_municipalities(
        duckdb_context=duckdb_context, postgres_context=postgres_context
    )
    benchmark_fn = _build_benchmark_fn(dataset_size=dataset_size)
    benchmark_fn(db_context=postgres_context)


def _seed_municipalities(
    duckdb_context: DuckDBPyConnection, postgres_context: Engine
) -> None:
    municipalities_path = (
        f"az://{StorageContainer.METADATA.value}/{Config.DATABRICKS_MUNICIPALITIES_FILE}"
    )

    logger.info(f"Loading municipalities from '{municipalities_path}' into PostgreSQL...")
    df = duckdb_context.execute(f"""
        SELECT region AS municipality_name, wkb AS geometry
        FROM read_parquet('{municipalities_path}')
    """).fetchdf()

    df["geometry"] = df["geometry"].apply(
        lambda g: bytes(g) if isinstance(g, (memoryview, bytearray)) else g
    )
    df["geometry"] = df["geometry"].apply(from_wkb)

    gdf = gpd.GeoDataFrame(df, geometry="geometry", crs=EPSGCode.WGS84.value)

    with postgres_context.connect() as conn:
        gdf.to_postgis("municipalities", con=conn, if_exists="replace", index=False)
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS municipalities_geometry_idx "
            "ON municipalities USING GIST (geometry)"
        ))
        conn.execute(text("ANALYZE municipalities"))
        conn.commit()

    logger.info(f"Seeded {len(gdf)} municipalities into PostgreSQL.")


def _build_benchmark_fn(dataset_size: DatasetSize):
    query_id = _build_query_id("national-scale-spatial-join-postgis", dataset_size)
    buildings_table = f"buildings_{dataset_size.value}"

    @monitor(
        query_id=query_id,
        benchmark_iteration=BenchmarkIteration.NATIONAL_SCALE_SPATIAL_JOIN,
        cost_configuration=CostConfiguration(include_aci=True, include_postgres=True),
        use_sequential_stopping=False,
        warmup_iterations=1,
    )
    def _benchmark(
        db_context: Engine,
    ) -> list:
        sql = text(f"""
            SELECT
                m.municipality_name,
                COUNT(*) AS building_count
            FROM municipalities m
            JOIN {buildings_table} b ON ST_Intersects(m.geometry, b.geometry)
            GROUP BY m.municipality_name
            ORDER BY building_count DESC
        """)

        with db_context.connect() as conn:
            return conn.execute(sql).fetchall()

    return _benchmark
