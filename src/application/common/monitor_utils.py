import datetime
import hashlib
import random
import string
import time
import uuid
from datetime import date
from typing import Any

import numpy as np
import psutil
from dependency_injector.wiring import inject, Provide

from src import Config
from src.application.common import logger
from src.application.contracts import IMonitoringStorageService, IAzureCostService
from src.application.dtos import CostConfiguration
from src.domain.enums import BlobOperationType, StopReason
from src.infra.infrastructure import Containers


@inject
def _get_run_id(run_id: str | None = Provide[Containers.config.run_id]) -> str:
    if run_id is not None:
        logger.debug(f"Found run ID '{run_id}' from DI.")
        return run_id

    today = date.today().strftime("%Y-%m-%d")
    suffix = "".join(
        random.choices(string.ascii_uppercase + string.digits, k=Config.RUN_ID_LENGTH)
    )
    run_id = f"{today}-{suffix}"
    logger.info(f"No run ID from DI. Created run ID '{run_id}'")

    return run_id


@inject
def _get_benchmark_run(
    benchmark_run: int = Provide[Containers.config.benchmark_run],
) -> int:
    return benchmark_run


@inject
def _save_run(
    run_id: str,
    benchmark_run: int,
    query_id: str,
    iteration: int,
    total_iterations: int,
    samples: list[dict[str, Any]],
    monitoring_storage_service: IMonitoringStorageService = Provide[
        Containers.monitoring_storage_service
    ],
) -> None:
    iteration = _create_global_iteration(
        iteration=iteration,
        total_iterations=total_iterations,
        benchmark_run=benchmark_run,
    )

    monitoring_storage_service.write_run_to_blob_storage(
        samples=samples,
        query_id=query_id,
        run_id=run_id,
        benchmark_run=benchmark_run,
        iteration=iteration,
    )


@inject
def _save_run_metadata(
    query_id: str,
    run_id: str,
    achieved_iterations: int,
    failed_iterations: int,
    stop_reason: StopReason,
    ci_half_width_seconds: float | None,
    ci_half_width_relative: float | None,
    mean_elapsed_seconds: float | None,
    median_elapsed_seconds: float | None,
    monitoring_storage_service: IMonitoringStorageService = Provide[
        Containers.monitoring_storage_service
    ],
) -> None:
    logger.info("Saving benchmark metadata to blob storage.")
    metadata_id = str(uuid.uuid4())
    timestamp = datetime.datetime.now(datetime.timezone.utc)
    monitoring_storage_service.write_metadata_to_blob_storage(
        metadata_id=metadata_id,
        timestamp=timestamp,
        query_id=query_id,
        run_id=run_id,
        achieved_iterations=achieved_iterations,
        failed_iterations=failed_iterations,
        stop_reason=stop_reason,
        ci_half_width_seconds=ci_half_width_seconds,
        ci_half_width_relative=ci_half_width_relative,
        mean_elapsed_seconds=mean_elapsed_seconds,
        median_elapsed_seconds=median_elapsed_seconds,
    )

    logger.info(f"Benchmark metadata saved with ID '{metadata_id}'.")


@inject
def _save_run_cost_analytics(
    query_id: str,
    run_id: str,
    cost_configuration: CostConfiguration,
    start_time: datetime.datetime,
    end_time: datetime.datetime,
    bytes_ingress: float | None = None,
    bytes_egress: float | None = None,
    operation_type: BlobOperationType | None = None,
    azure_cost_service: IAzureCostService = Provide[Containers.azure_cost_service],
    monitoring_storage_service: IMonitoringStorageService = Provide[
        Containers.monitoring_storage_service
    ],
) -> None:
    benchmark_run = _get_benchmark_run()
    if cost_configuration.include_aci:
        aci_cost = azure_cost_service.compute_aci_cost(query_id, start_time, end_time)
        logger.info(f"Computed ACI cost: {aci_cost.to_dict()}")
        monitoring_storage_service.write_cost_analytics_to_blob_storage(
            query_id=query_id,
            run_id=run_id,
            benchmark_run=benchmark_run,
            file_name="aci_cost.parquet",
            cost=aci_cost,
        )

    is_blob_params_present = (
        bytes_ingress is not None
        and bytes_egress is not None
        and operation_type is not None
    )
    if cost_configuration.include_blob_storage and is_blob_params_present:
        blob_cost = azure_cost_service.compute_blob_storage_cost(
            start_time, end_time, bytes_ingress, bytes_egress, operation_type
        )
        logger.info(f"Computed Blob Storage cost: {blob_cost.to_dict()}")
        monitoring_storage_service.write_cost_analytics_to_blob_storage(
            query_id=query_id,
            run_id=run_id,
            benchmark_run=benchmark_run,
            file_name="blob_cost.parquet",
            cost=blob_cost,
        )

    if cost_configuration.include_postgres:
        postgres_cost = azure_cost_service.compute_database_cost(start_time, end_time)
        logger.info(f"Computed PostgreSQL cost: {postgres_cost.to_dict()}")
        monitoring_storage_service.write_cost_analytics_to_blob_storage(
            query_id=query_id,
            run_id=run_id,
            benchmark_run=benchmark_run,
            file_name="postgres_cost.parquet",
            cost=postgres_cost,
        )

    if cost_configuration.include_databricks:
        egress = bytes_egress if bytes_egress is not None else 0.0
        databricks_cost = azure_cost_service.compute_databricks_cost(
            start_time=start_time,
            end_time=end_time,
            num_workers=cost_configuration.num_workers,
            bytes_egress=egress,
        )
        logger.info(f"Computed Databricks cost: {databricks_cost.to_dict()}")
        monitoring_storage_service.write_cost_analytics_to_blob_storage(
            query_id=query_id,
            run_id=run_id,
            benchmark_run=benchmark_run,
            file_name="databricks_cost.parquet",
            cost=databricks_cost,
        )


def _create_global_iteration(
    iteration: int, total_iterations: int, benchmark_run: int
) -> int:
    return iteration + total_iterations * (benchmark_run - 1)


def _make_bootstrap_rng(run_id: str, query_id: str) -> np.random.Generator:
    """
    Deterministic seed for bootstrap resampling per (run_id, query_id), so the
    stopping rule is reproducible across reruns of the same benchmark.
    """
    digest = hashlib.blake2b(
        f"{run_id}::{query_id}".encode(), digest_size=8
    ).digest()
    seed = int.from_bytes(digest, "big")
    return np.random.default_rng(seed)


def _bootstrap_ci_half_width(
    samples: list[float],
    n_resamples: int,
    confidence: float,
    rng: np.random.Generator,
) -> tuple[float, float, float]:
    """
    Non-parametric bootstrap CI on the sample mean. Returns
    (mean, median, abs_half_width_on_mean).
    """
    arr = np.asarray(samples, dtype=np.float64)
    n = arr.size
    indices = rng.integers(0, n, size=(n_resamples, n))
    resample_means = arr[indices].mean(axis=1)
    alpha = 1.0 - confidence
    lower = float(np.quantile(resample_means, alpha / 2.0))
    upper = float(np.quantile(resample_means, 1.0 - alpha / 2.0))
    half_width = (upper - lower) / 2.0
    return float(arr.mean()), float(np.median(arr)), half_width


def _measure_io(
    func, *args, **kwargs
) -> tuple[Any, float, int, int, float, float, Exception | None]:
    process = psutil.Process()
    net_before = psutil.net_io_counters()
    cpu_before = process.cpu_times()
    start_time = time.perf_counter()

    result: Any = None
    exception: Exception | None = None
    try:
        result = func(*args, **kwargs)
    except Exception as exc:
        exception = exc

    end_time = time.perf_counter()
    cpu_after = process.cpu_times()
    net_after = psutil.net_io_counters()

    elapsed_time = end_time - start_time
    network_bytes_sent = net_after.bytes_sent - net_before.bytes_sent
    network_bytes_received = net_after.bytes_recv - net_before.bytes_recv
    cpu_time_user_seconds = cpu_after.user - cpu_before.user
    cpu_time_system_seconds = cpu_after.system - cpu_before.system

    return (
        result,
        elapsed_time,
        network_bytes_sent,
        network_bytes_received,
        cpu_time_user_seconds,
        cpu_time_system_seconds,
        exception,
    )
