import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())


@dataclass(frozen=True)
class Config:
    IS_NOTEBOOK: bool = False
    IOU_ROUNDING_DECIMALS: int = 9

    # AZURE
    AZURE_RESOURCE_GROUP: str = "doppa"
    AZURE_RESOURCE_LOCATION: str = "norwayeast"
    AZURE_SUBSCRIPTION_ID: str = os.getenv("AZURE_SUBSCRIPTION_ID")
    AZURE_UAMI_RESOURCE_ID: str = os.getenv("AZURE_UAMI_RESOURCE_ID")

    AZURE_BLOB_STORAGE_HTTPS_URL: str = "https://doppabs.blob.core.windows.net"
    AZURE_BLOB_STORAGE_ACCOUNT_NAME: str = "doppabs"
    AZURE_BLOB_STORAGE_CONNECTION_STRING: str = os.getenv(
        "AZURE_BLOB_STORAGE_CONNECTION_STRING"
    )
    AZURE_BLOB_STORAGE_MAX_CONCURRENCY: int = 1
    AZURE_VMT_SERVER_URL: str = "https://doppa-vmt.azurewebsites.net"
    AZURE_METRICS_REGIONAL_ENDPOINT: str = (
        f"https://{AZURE_RESOURCE_LOCATION}.metrics.monitor.azure.com"
    )

    AZURE_ACI_VCPU_PRICE_PER_SECOND: float = 0.0002
    AZURE_ACI_MEMORY_GB_PRICE_PER_SECOND: float = 0.0002

    AZURE_BLOB_READ_OPERATION_COST: float = 0
    AZURE_BLOB_WRITE_OPERATION_COST: float = 0
    AZURE_BLOB_LIST_OPERATION_COST: float = 0
    AZURE_BLOB_STORAGE_GB_PER_MONTH_COST: float = 0
    AZURE_BLOB_INGRESS_PER_GB_COST: float = 0
    AZURE_BLOB_EGRESS_PER_GB_COST: float = 0

    AZURE_DATABASE_COMPUTE_PRICE_PER_SECOND: float = 0
    AZURE_DATABASE_STORAGE_GB_PER_MONTH_COST: float = 0

    # POSTGRESQL
    POSTGRES_USERNAME: str = os.getenv("POSTGRES_USERNAME")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD")
    POSTGRES_SERVER_NAME: str = os.getenv("POSTGRES_SERVER_NAME")
    POSTGRES_HOST: str = (
        f"{os.getenv('POSTGRES_SERVER_NAME')}.postgres.database.azure.com"
    )
    POSTGRES_DB: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_PAGE_SIZE: int = 10_000

    # DIRECTORIES
    ROOT_DIR: Path = Path.cwd() if not IS_NOTEBOOK else Path.cwd().parent.parent.parent
    LOG_DIR: Path = ROOT_DIR / f"logs"
    BUILDINGS_SHAPEFILE: Path = ROOT_DIR / "resources" / "buildings.shp"
    BUILDINGS_PARQUET_FILE: Path = ROOT_DIR / "resources" / "buildings.parquet"
    BUILDINGS_GEOJSONL_FILE: Path = ROOT_DIR / "resources" / "buildings.geojsonl"
    BUILDINGS_PMTILES_FILE: Path = ROOT_DIR / "resources" / "buildings.pmtiles"
    BUILDINGS_MVT_DIR: Path = ROOT_DIR / "resources" / "buildings_mvt"
    MVT_TILES_PATH: Path = ROOT_DIR / "resources" / "tiles.json"

    # LOGGING
    LOGGING_LEVEL: int = logging.INFO
    LOG_FILE: Path = LOG_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    # GEONORGE
    GEONORGE_BASE_URL: str = "https://api.kartverket.no/kommuneinfo/v1/"

    # METADATA
    RELEASE_FILE_NAME: str = "releases.parquet"
    COUNTY_FILE_NAME: str = "counties.parquet"
    BUILDINGS_SPATIAL_EXTENT: tuple[float, float, float, float] = (
        57.9676151,
        4.509825,
        71.17004,
        31.1565841,
    )
    TRONDHEIM_CENTER_WGS84: tuple[float, float] = (10.395, 63.430)
    KNN_SEARCH_K: int = 10
    POINT_IN_POLYGON_TOTAL_POINTS: int = 10
    POINT_IN_POLYGON_INSIDE_RATIO: float = 0.3
    POINT_IN_POLYGON_PROBE_SEED: int = 42
    VECTOR_TILES_100K_TOTAL_REQUESTS: int = 100_000

    # STAC
    STAC_LICENSE = "CC-BY-4.0"
    STAC_STORAGE_CONTAINER = "https://doppabs.blob.core.windows.net/stac"

    # PARTITIONING
    PARTITION_RESOLUTION: int = 3
    BUILDINGS_BATCH_SIZE: int = 250_000
    GEOPARQUET_ROW_GROUP_SIZE: int = 100_000

    # DATASET SYNTHESIS
    SYNTHESIS_JITTER_DEGREES: float = 1e-5

    # TEST MODE
    SETUP_COUNTY_LIMIT: int | None = (
        int(os.getenv("SETUP_COUNTY_LIMIT")) if os.getenv("SETUP_COUNTY_LIMIT") else None
    )

    # BENCHMARKING
    BENCHMARK_FILE: Path = ROOT_DIR / "benchmarks.yml"
    RUN_ID_LENGTH: int = 6
    DEFAULT_SAMPLE_TIMEOUT: float = 0.01
    BENCHMARK_RUNS: int = 1
    BENCHMARK_WARMUP_ITERATIONS: int = 5
    BENCHMARK_ITERATIONS: int = 100
    BENCHMARK_METADATA_BLOB_NAME: str = "benchmark_metadata.parquet"
    BENCHMARK_DOPPA_DATA_RELEASE: str = "2026-05-16.1"

    # Sequential stopping rule (bootstrapped CI on mean elapsed time)
    BENCHMARK_MIN_ITERATIONS: int = 10
    BENCHMARK_MIN_TIMED_WINDOW_SECONDS: int = 60
    BENCHMARK_MAX_TIMED_WINDOW_SECONDS: int = 3600
    BENCHMARK_TARGET_CI_HALF_WIDTH_RELATIVE: float = 0.05
    BENCHMARK_BOOTSTRAP_RESAMPLES: int = 1000
    BENCHMARK_CI_CONFIDENCE: float = 0.95
    BENCHMARK_MAX_CONSECUTIVE_FAILURES: int = 3

    INGESTION_DELAY_SECONDS: int = 600

    # DATABRICKS
    DATABRICKS_HOST: str = os.getenv("DATABRICKS_HOST")
    DATABRICKS_TOKEN: str = os.getenv("DATABRICKS_TOKEN")
    DATABRICKS_SPARK_VERSION: str = os.getenv(
        "DATABRICKS_SPARK_VERSION", "15.4.x-scala2.12"
    )
    DATABRICKS_NODE_TYPE_ID: str = os.getenv(
        "DATABRICKS_NODE_TYPE_ID", "Standard_D4s_v3"
    )
    DATABRICKS_POLL_INTERVAL_SECONDS: int = 30
    DATABRICKS_HTTP_TIMEOUT_SECONDS: int = 30
    DATABRICKS_DRIVER_MEMORY: str = "9g"
    DATABRICKS_DRIVER_MEMORY_OVERHEAD: str = "512m"
    DATABRICKS_SEDONA_MAVEN_COORDINATES: str = (
        "org.apache.sedona:sedona-spark-shaded-3.5_2.12:1.7.1"
    )
    DATABRICKS_SEDONA_PYPI_PACKAGE: str = "apache-sedona==1.7.1"
    DATABRICKS_GEOPANDAS_PYPI_PACKAGE: str = "geopandas==0.14.4"
    DATABRICKS_LOCAL_SCRIPT_PATH_BROADCAST: str = (
        "src/presentation/databricks/national_scale_spatial_join_broadcast.py"
    )
    DATABRICKS_LOCAL_SCRIPT_PATH_PARTITIONED: str = (
        "src/presentation/databricks/national_scale_spatial_join_partitioned.py"
    )
    DATABRICKS_LOCAL_SCRIPT_PATH_DEFAULT: str = (
        "src/presentation/databricks/national_scale_spatial_join_default.py"
    )
    DATABRICKS_WORKSPACE_NOTEBOOK_PATH_BROADCAST: str = (
        "/Shared/doppa/national_scale_spatial_join_broadcast"
    )
    DATABRICKS_WORKSPACE_NOTEBOOK_PATH_PARTITIONED: str = (
        "/Shared/doppa/national_scale_spatial_join_partitioned"
    )
    DATABRICKS_WORKSPACE_NOTEBOOK_PATH_DEFAULT: str = (
        "/Shared/doppa/national_scale_spatial_join_default"
    )
    DATABRICKS_MUNICIPALITIES_FILE: str = "municipalities.parquet"
    MUNICIPALITIES_CONTRIBUTION_BLOB: str = "municipalities.parquet"
    AZURE_BLOB_STORAGE_ACCOUNT_KEY: str = os.getenv("AZURE_BLOB_STORAGE_ACCOUNT_KEY")
