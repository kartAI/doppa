import geopandas as gpd
from osgeo import ogr
from pyproj import CRS
from dependency_injector.wiring import Provide, inject
from duckdb import DuckDBPyConnection
import numpy as np
import shapely
from sqlalchemy import Engine, text

from src import Config
from src.application.common import logger
from src.application.contracts import (
    IFilePathService,
    IBlobStorageService,
    ITestDatasetService,
    IDatasetSynthesisService,
    IBenchmarkService,
)
from src.domain.enums import StorageContainer, Theme, EPSGCode, DatasetSize
from src.infra.infrastructure import Containers


@inject
def setup_benchmarking_framework(
    test_dataset_service: ITestDatasetService = Provide[
        Containers.test_dataset_service
    ],
    dataset_synthesis_service: IDatasetSynthesisService = Provide[
        Containers.dataset_synthesis_service
    ],
) -> None:
    """
    Provisions the benchmarking framework's input data in six steps: (1) run the
    test dataset pipeline to produce the small buildings dataset, (2) synthesize
    the medium dataset from it, (3) synthesize the large dataset, (4) seed
    PostgreSQL with each ``buildings_<size>`` table plus a GIST spatial index,
    (5) materialize and upload the shapefile copy of the small buildings dataset
    to blob storage, and (6) republish ``municipalities.parquet`` from the
    ``contributions`` container to the ``metadata`` container so the RQ2 spatial
    join benchmarks find it at the expected location.
    """
    logger.info("Starting benchmarking framework setup...")

    logger.info("Step 1/6: Running test dataset pipeline...")
    release = test_dataset_service.run_pipeline()
    logger.info(f"Test dataset pipeline complete. Release: '{release}'")

    logger.info("Step 2/6: Synthesizing medium dataset...")
    dataset_synthesis_service.run_pipeline(release=release, target_size=DatasetSize.MEDIUM)
    logger.info("Medium dataset synthesis complete.")

    logger.info("Step 3/6: Synthesizing large dataset...")
    dataset_synthesis_service.run_pipeline(release=release, target_size=DatasetSize.LARGE)
    logger.info("Large dataset synthesis complete.")

    logger.info("Step 4/6: Seeding Postgres with buildings...")
    _postgres_buildings_seed(release=release)
    logger.info("Postgres seed complete.")

    logger.info("Step 5/6: Creating shapefile copy in blob storage...")
    _create_shapefile_copy(release=release)
    logger.info("Shapefile copy complete.")

    logger.info("Step 6/6: Publishing municipalities.parquet to metadata container...")
    _publish_municipalities()
    logger.info("Municipalities publish complete.")

    logger.info("Benchmarking framework setup complete.")


@inject
def _publish_municipalities(
    blob_storage_service: IBlobStorageService = Provide[
        Containers.blob_storage_service
    ],
) -> None:
    source_blob = Config.MUNICIPALITIES_CONTRIBUTION_BLOB
    destination_blob = Config.DATABRICKS_MUNICIPALITIES_FILE

    logger.info(
        f"Downloading '{source_blob}' from container '{StorageContainer.CONTRIBUTION.value}'..."
    )
    payload = blob_storage_service.download_file(
        container_name=StorageContainer.CONTRIBUTION,
        blob_name=source_blob,
    )

    if payload is None:
        raise RuntimeError(
            f"Source blob '{source_blob}' is missing from container "
            f"'{StorageContainer.CONTRIBUTION.value}'. Run the "
            f"'04-kommuner-contribution' notebook in the 'doppa-data-contribution' "
            f"repository against the target storage account before re-running "
            f"setup_benchmarking_framework."
        )

    blob_storage_service.upload_file(
        container_name=StorageContainer.METADATA,
        blob_name=destination_blob,
        data=payload,
    )
    logger.info(
        f"Uploaded '{destination_blob}' to container '{StorageContainer.METADATA.value}' "
        f"({len(payload)} bytes)."
    )


@inject
def _postgres_buildings_seed(
    release: str | None = None,
    duckdb_context: DuckDBPyConnection = Provide[Containers.duckdb_context],
    postgres_db_context: Engine = Provide[Containers.postgres_context],
    file_path_service: IFilePathService = Provide[Containers.file_path_service],
) -> None:
    effective_release = release or Config.BENCHMARK_DOPPA_DATA_RELEASE

    for size in DatasetSize:
        _seed_postgres_for_size(
            release=effective_release,
            size=size,
            duckdb_context=duckdb_context,
            postgres_db_context=postgres_db_context,
            file_path_service=file_path_service,
        )


def _seed_postgres_for_size(
    release: str,
    size: DatasetSize,
    duckdb_context: DuckDBPyConnection,
    postgres_db_context: Engine,
    file_path_service: IFilePathService,
) -> None:
    table_name = f"buildings_{size.value}"
    index_name = f"{table_name}_geometry_idx"

    path = file_path_service.create_release_virtual_filesystem_path(
        storage_scheme="az",
        release=release,
        container=StorageContainer.DATA,
        theme=Theme.BUILDINGS,
        dataset_size=size,
        region="*",
        file_name="*.parquet",
    )

    total_rows = duckdb_context.execute(
        f"SELECT COUNT(*) FROM read_parquet('{path}')"
    ).fetchone()[0]

    if total_rows == 0:
        logger.warning(
            f"No buildings found at blob storage path '{path}' for size '{size.value}'. Skipping table '{table_name}'."
        )
        return

    duckdb_vector_size = 2048
    vectors_per_chunk = max(1, Config.BUILDINGS_BATCH_SIZE // duckdb_vector_size)

    logger.info(
        f"Streaming {total_rows} rows from '{path}' into '{table_name}' in chunks of ~{vectors_per_chunk * duckdb_vector_size}..."
    )

    streaming_result = duckdb_context.execute(
        f"SELECT ST_AsWKB(geometry) AS geometry, * EXCLUDE geometry FROM read_parquet('{path}')"
    )

    inserted_rows = 0
    is_first_chunk = True

    with postgres_db_context.connect() as conn:
        while True:
            chunk_df = streaming_result.fetch_df_chunk(vectors_per_chunk)
            if chunk_df.empty:
                break

            geometry_array = chunk_df["geometry"].to_numpy()
            geometry_array = np.array(
                [bytes(g) if isinstance(g, (memoryview, bytearray)) else g for g in geometry_array],
                dtype=object,
            )
            chunk_df["geometry"] = shapely.from_wkb(geometry_array)

            chunk_gdf = gpd.GeoDataFrame(
                chunk_df,
                geometry="geometry",
                crs=EPSGCode.WGS84.value,
            )

            chunk_gdf.to_postgis(
                name=table_name,
                con=conn,
                if_exists="replace" if is_first_chunk else "append",
                index=False,
            )

            inserted_rows += len(chunk_gdf)
            is_first_chunk = False
            logger.info(
                f"Inserted {inserted_rows} of {total_rows} rows into '{table_name}'"
            )

        logger.info(
            f"Creating GIST spatial index '{index_name}' on '{table_name}.geometry'..."
        )
        conn.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} USING GIST (geometry)"
            )
        )
        conn.execute(text(f"ANALYZE {table_name}"))
        conn.commit()
        logger.info(f"Spatial index '{index_name}' created.")

    logger.info(
        f"Insertion into '{table_name}' completed: {inserted_rows} rows"
    )


@inject
def _create_shapefile_copy(
    release: str | None = None,
    file_path_service: IFilePathService = Provide[Containers.file_path_service],
    benchmark_service: IBenchmarkService = Provide[Containers.benchmark_service],
    blob_storage_service: IBlobStorageService = Provide[
        Containers.blob_storage_service
    ],
) -> None:

    path = file_path_service.create_release_virtual_filesystem_path(
        storage_scheme="az",
        release=release or Config.BENCHMARK_DOPPA_DATA_RELEASE,
        container=StorageContainer.DATA,
        theme=Theme.BUILDINGS,
        dataset_size=DatasetSize.SMALL,
        region="*",
        file_name="*.parquet",
    )

    logger.info("Converting parquet to shapefile locally...")
    benchmark_service.download_parquet_as_shapefile_locally(
        virtual_file_path=path,
        save_path=Config.BUILDINGS_SHAPEFILE,
    )
    logger.info(f"Shapefile written to '{Config.BUILDINGS_SHAPEFILE}'")

    prj_path = Config.BUILDINGS_SHAPEFILE.with_suffix(".prj")
    prj_path.write_text(CRS.from_epsg(4326).to_wkt(version="WKT1_ESRI"))
    logger.info(f"WGS84 .prj file written to '{prj_path}'")

    logger.info("Creating spatial index (.qix)...")
    ogr.UseExceptions()
    ds = ogr.Open(Config.BUILDINGS_SHAPEFILE.as_posix(), update=1)
    ds.ExecuteSQL(f"CREATE SPATIAL INDEX ON {Config.BUILDINGS_SHAPEFILE.stem}")
    ds = None
    logger.info("Spatial index created.")

    blob_prefix = "copies/shapefile"
    base = Config.BUILDINGS_SHAPEFILE.with_suffix("")
    for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix"):
        component = base.with_suffix(ext)
        if not component.exists():
            logger.warning(
                f"Shapefile component '{component.name}' not found, skipping."
            )
            continue

        blob_name = f"{blob_prefix}/{component.name}"
        data = component.read_bytes()
        blob_storage_service.upload_file(
            container_name=StorageContainer.DATA,
            blob_name=blob_name,
            data=data,
        )

        logger.info(
            f"Uploaded '{component.name}' to '{blob_name}' in container '{StorageContainer.DATA.value}'"
        )
