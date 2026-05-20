import datetime
import functools

from src import Config
from src.application.common import logger
from src.application.common.monitor_utils import (
    _get_run_id,
    _get_benchmark_run,
    _measure_io,
    _save_run,
    _save_run_metadata,
    _save_run_cost_analytics,
)
from src.application.dtos import CostConfiguration, DatabricksRunResult
from src.domain.enums import BenchmarkIteration, BlobOperationType, SchemaVersion


def monitor(
    query_id: str,
    benchmark_iteration: BenchmarkIteration,
    cost_configuration: CostConfiguration,
    skip_warmup: bool = False,
    elapsed_from_result: bool = False,
):
    """
    Benchmarking decorator. Wraps a function in warmup + timed iterations, records
    per-iteration samples, and writes run metadata and cost analytics to blob storage.
    :param query_id: Identifier for the benchmarked query.
    :param benchmark_iteration: Number of timed iterations to run.
    :param cost_configuration: Which Azure cost components to compute and store.
    :param skip_warmup: Disable warmup runs. Use for Databricks, since each run provisions a cluster and warmup would multiply cost. Default is False.
    :param elapsed_from_result: Treat the wrapped function's return value as a (elapsed_seconds, cardinality) tuple instead of using wall-clock time and len(result). Use for Databricks, since the notebook self-reports both. Default is False.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            result = None

            run_id = _get_run_id()
            benchmark_run = _get_benchmark_run()

            logger.info(
                f"Starting benchmark for query '{query_id}' with run ID '{run_id}'."
            )

            ingress_sum: int = 0
            egress_sum: int = 0
            start_time = datetime.datetime.now(datetime.UTC)
            failure: Exception | None = None
            failure_iteration: int | None = None
            failure_started_at: datetime.datetime | None = None
            failure_ended_at: datetime.datetime | None = None
            failure_partial_sample: dict | None = None

            if skip_warmup:
                logger.info(
                    f"Executing {benchmark_iteration.value} benchmark run(s) (no warmup)."
                )
            else:
                logger.info(
                    f"Executing {Config.BENCHMARK_WARMUP_ITERATIONS} warmup runs."
                )
                for _ in range(Config.BENCHMARK_WARMUP_ITERATIONS):
                    warmup_started_at = datetime.datetime.now(datetime.UTC)
                    (
                        _,
                        w_elapsed,
                        w_sent,
                        w_recv,
                        w_cpu_u,
                        w_cpu_s,
                        warmup_exc,
                    ) = _measure_io(func, *args, **kwargs)
                    warmup_ended_at = datetime.datetime.now(datetime.UTC)
                    if warmup_exc is not None:
                        failure = warmup_exc
                        failure_iteration = 0
                        failure_started_at = warmup_started_at
                        failure_ended_at = warmup_ended_at
                        failure_partial_sample = {
                            "network_bytes_sent": w_sent,
                            "network_bytes_received": w_recv,
                            "cpu_time_user_seconds": w_cpu_u,
                            "cpu_time_system_seconds": w_cpu_s,
                            "wall_elapsed_time": w_elapsed,
                        }
                        logger.error(
                            f"Warmup raised for query '{query_id}': {warmup_exc!r}. "
                            f"Skipping timed iterations."
                        )
                        break
                if failure is None:
                    logger.info(
                        f"Warmup runs completed. Starting {benchmark_iteration.value} benchmark runs."
                    )

            if failure is None:
                for i in range(benchmark_iteration.value):
                    iteration = i + 1

                    started_at = datetime.datetime.now(datetime.UTC)
                    (
                        result,
                        wall_elapsed_time,
                        net_bytes_sent,
                        net_bytes_received,
                        cpu_time_user_seconds,
                        cpu_time_system_seconds,
                        iter_exc,
                    ) = _measure_io(func, *args, **kwargs)
                    ended_at = datetime.datetime.now(datetime.UTC)

                    if iter_exc is not None:
                        failure = iter_exc
                        failure_iteration = iteration
                        failure_started_at = started_at
                        failure_ended_at = ended_at
                        failure_partial_sample = {
                            "network_bytes_sent": net_bytes_sent,
                            "network_bytes_received": net_bytes_received,
                            "cpu_time_user_seconds": cpu_time_user_seconds,
                            "cpu_time_system_seconds": cpu_time_system_seconds,
                            "wall_elapsed_time": wall_elapsed_time,
                        }
                        ingress_sum += net_bytes_received
                        egress_sum += net_bytes_sent
                        logger.error(
                            f"Iteration {iteration} raised for query '{query_id}': "
                            f"{iter_exc!r}. Failing fast; skipping remaining iterations."
                        )
                        break

                    executor_input_bytes_read = None
                    executor_run_time_ms = None
                    shuffle_read_bytes = None
                    shuffle_write_bytes = None
                    driver_collection_time_ms = None
                    stage_durations_ms = None

                    if elapsed_from_result:
                        if isinstance(result, DatabricksRunResult):
                            elapsed_time = result.execution_duration_s
                            result_cardinality = result.cardinality
                            executor_input_bytes_read = result.executor_input_bytes_read
                            executor_run_time_ms = result.executor_run_time_ms
                            shuffle_read_bytes = result.shuffle_read_bytes
                            shuffle_write_bytes = result.shuffle_write_bytes
                            driver_collection_time_ms = result.driver_collection_time_ms
                            stage_durations_ms = result.stage_durations_ms
                        else:
                            elapsed_time, result_cardinality = result
                    else:
                        elapsed_time = wall_elapsed_time
                        result_cardinality = len(result) if result is not None else -1

                    ingress_sum += net_bytes_received
                    egress_sum += net_bytes_sent

                    _save_run(
                        run_id=run_id,
                        benchmark_run=benchmark_run,
                        query_id=query_id,
                        iteration=iteration,
                        total_iterations=benchmark_iteration.value,
                        samples=[
                            {
                                "status": "success",
                                "failure_reason": None,
                                "elapsed_time": elapsed_time,
                                "network_bytes_sent": net_bytes_sent,
                                "network_bytes_received": net_bytes_received,
                                "started_at": started_at.isoformat(),
                                "ended_at": ended_at.isoformat(),
                                "cpu_time_user_seconds": cpu_time_user_seconds,
                                "cpu_time_system_seconds": cpu_time_system_seconds,
                                "result_cardinality": result_cardinality,
                                "executor_input_bytes_read": executor_input_bytes_read,
                                "executor_run_time_ms": executor_run_time_ms,
                                "shuffle_read_bytes": shuffle_read_bytes,
                                "shuffle_write_bytes": shuffle_write_bytes,
                                "driver_collection_time_ms": driver_collection_time_ms,
                                "stage_durations_ms": stage_durations_ms,
                                "schema_version": SchemaVersion.V4.value,
                            }
                        ],
                    )

            if failure is not None:
                assert failure_started_at is not None
                assert failure_ended_at is not None
                assert failure_partial_sample is not None
                _save_run(
                    run_id=run_id,
                    benchmark_run=benchmark_run,
                    query_id=query_id,
                    iteration=failure_iteration or 1,
                    total_iterations=benchmark_iteration.value,
                    samples=[
                        {
                            "status": "failed",
                            "failure_reason": str(failure),
                            "elapsed_time": None,
                            "network_bytes_sent": failure_partial_sample["network_bytes_sent"],
                            "network_bytes_received": failure_partial_sample["network_bytes_received"],
                            "started_at": failure_started_at.isoformat(),
                            "ended_at": failure_ended_at.isoformat(),
                            "cpu_time_user_seconds": failure_partial_sample["cpu_time_user_seconds"],
                            "cpu_time_system_seconds": failure_partial_sample["cpu_time_system_seconds"],
                            "result_cardinality": None,
                            "executor_input_bytes_read": None,
                            "executor_run_time_ms": None,
                            "shuffle_read_bytes": None,
                            "shuffle_write_bytes": None,
                            "driver_collection_time_ms": None,
                            "stage_durations_ms": None,
                            "schema_version": SchemaVersion.V4.value,
                        }
                    ],
                )

            end_time = datetime.datetime.now(datetime.UTC)
            logger.info(
                f"Benchmark runs completed in {round((end_time - start_time).total_seconds(), 2)} seconds."
            )

            _save_run_metadata(query_id=query_id, run_id=run_id)
            _save_run_cost_analytics(
                run_id=run_id,
                cost_configuration=cost_configuration,
                query_id=query_id,
                start_time=start_time,
                end_time=end_time,
                bytes_ingress=ingress_sum,
                bytes_egress=egress_sum,
                operation_type=BlobOperationType.READ,
            )

            if failure is not None:
                logger.warning(
                    f"Benchmark run {benchmark_run} for query '{query_id}' recorded as failed; "
                    f"reason: {failure!r}"
                )
                return None

            logger.info(f"Benchmark run {benchmark_run} completed.")
            return result

        return wrapper

    return decorator
