from dependency_injector import containers, providers
from pystac import StacIO

from src.infra.infrastructure.services import (
    BlobStorageService, OpenStreetMapService, OpenStreetMapFileService, FilePathService, ReleaseService, BytesService,
    CountyService, VectorService, StacService, StacIOService, FKBService, ConflationService,
    TestDatasetService, DatasetSynthesisService, MonitoringStorageService,
    AzureCostService, BenchmarkConfigurationService, AzureMetricService, AzurePricingService, BenchmarkService,
    DatabricksService
)
from src.infra.persistence.context import create_duckdb_context, create_blob_storage_context, create_postgres_db_context


class Containers(containers.DeclarativeContainer):
    config = providers.Configuration()

    duckdb_context = providers.Singleton(create_duckdb_context)
    postgres_context = providers.Singleton(create_postgres_db_context)

    blob_storage_context = providers.Singleton(create_blob_storage_context)

    file_path_service = providers.Singleton(
        FilePathService
    )

    bytes_service = providers.Singleton(
        BytesService
    )

    vector_service = providers.Singleton(
        VectorService,
        db_context=duckdb_context
    )

    blob_storage_service = providers.Singleton(
        BlobStorageService,
        blob_storage_context=blob_storage_context,
        file_path_service=file_path_service
    )

    county_service = providers.Singleton(
        CountyService,
        db_context=duckdb_context,
        blob_storage_service=blob_storage_service,
        bytes_service=bytes_service
    )

    osm_file_service = providers.Singleton(
        OpenStreetMapFileService
    )

    stac_io_service = providers.Singleton(
        StacIOService,
        blob_storage_service=blob_storage_service
    )

    stac_service = providers.Singleton(
        StacService,
        blob_storage_service=blob_storage_service,
        file_path_service=file_path_service
    )

    release_service = providers.Singleton(
        ReleaseService,
        blob_storage_service=blob_storage_service,
        bytes_service=bytes_service
    )

    open_street_map_service = providers.Singleton(
        OpenStreetMapService,
        blob_storage_service=blob_storage_service,
        bytes_service=bytes_service
    )

    fkb_service = providers.Singleton(
        FKBService,
        db_context=duckdb_context,
        bytes_service=bytes_service,
        blob_storage_service=blob_storage_service
    )

    conflation_service = providers.Singleton(
        ConflationService,
        db_context=duckdb_context,
        file_path_service=file_path_service,
        blob_storage_service=blob_storage_service
    )

    monitoring_storage_service = providers.Singleton(
        MonitoringStorageService,
        blob_storage_service=blob_storage_service,
        bytes_service=bytes_service,
        file_path_service=file_path_service
    )

    benchmark_service = providers.Singleton(
        BenchmarkService,
        duckdb_context=duckdb_context
    )

    benchmark_configuration_service = providers.Singleton(
        BenchmarkConfigurationService
    )

    azure_pricing_service = providers.Singleton(
        AzurePricingService
    )

    azure_metric_service = providers.Singleton(
        AzureMetricService,
        benchmark_configuration_service=benchmark_configuration_service,
        blob_storage_service=blob_storage_service,
        file_path_service=file_path_service
    )

    azure_cost_service = providers.Singleton(
        AzureCostService,
        azure_pricing_service=azure_pricing_service,
        azure_metric_service=azure_metric_service
    )

    test_dataset_service = providers.Singleton(
        TestDatasetService,
        stac_service=stac_service,
        release_service=release_service,
        vector_service=vector_service,
        file_path_service=file_path_service,
        blob_storage_service=blob_storage_service,
        conflation_service=conflation_service,
        county_service=county_service,
        fkb_service=fkb_service,
        osm_service=open_street_map_service,
    )

    dataset_synthesis_service = providers.Singleton(
        DatasetSynthesisService,
        db_context=duckdb_context,
        file_path_service=file_path_service,
        blob_storage_service=blob_storage_service,
        county_service=county_service,
        vector_service=vector_service,
    )

    databricks_service = providers.Singleton(
        DatabricksService
    )

    StacIO.set_default(stac_io_service)
