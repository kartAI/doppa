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
    _bootstrap_ci_half_width,
    _make_bootstrap_rng,
)
from src.application.dtos import CostConfiguration, DatabricksRunResult
from src.domain.enums import (
    BenchmarkIteration,
    BlobOperationType,
    SchemaVersion,
    StopReason,
)


def monitor(
    query_id: str,
    benchmark_iteration: BenchmarkIteration,
    cost_configuration: CostConfiguration,
    skip_warmup: bool = False,
    elapsed_from_result: bool = False,
    use_sequential_stopping: bool = True,
    warmup_iterations: int | None = None,
):
    """
    Benchmarking decorator. Wraps a function in warmup + timed iterations, records
    per-iteration samples, and writes run metadata and cost analytics to blob storage.
    :param query_id: Identifier for the benchmarked query.
    :param benchmark_iteration: Hard ceiling on timed iterations. Under the sequential
        stopping rule this acts as an upper bound; the loop typically stops earlier once
        the bootstrapped CI on the mean elapsed time is within the configured precision
        and the 60-second timed-window floor is met.
    :param cost_configuration: Which Azure cost components to compute and store.
    :param skip_warmup: Disable warmup runs. Use for Databricks, since each run provisions a cluster and warmup would multiply cost. Default is False.
    :param elapsed_from_result: Treat the wrapped function's return value as a (elapsed_seconds, cardinality) tuple instead of using wall-clock time and len(result). Use for Databricks, since the notebook self-reports both. Default is False.
    :param use_sequential_stopping: Run iterations until the bootstrapped CI half-width
        on the mean elapsed time falls within ``Config.BENCHMARK_TARGET_CI_HALF_WIDTH_RELATIVE``,
        bounded below by ``Config.BENCHMARK_MIN_ITERATIONS`` and
        ``Config.BENCHMARK_MIN_TIMED_WINDOW_SECONDS``, and above by ``benchmark_iteration``
        (soft ceiling: kept open until the 60-second floor is met to keep the cost-metric
        window valid) and ``Config.BENCHMARK_MAX_TIMED_WINDOW_SECONDS`` (hard timeout).
        Set to False for Databricks national-scale runs, which use a fixed iteration count.
        Default is True.
    :param warmup_iterations: Override the number of warmup iterations. ``None`` falls back
        to ``Config.BENCHMARK_WARMUP_ITERATIONS``. Long-running benchmarks (national-scale
        spatial joins) typically set this to 1 since one warmup is enough to prime the OS
        page cache / connection / cluster state and additional warmups dominate the
        wall-clock budget. Ignored when ``skip_warmup`` is True.
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

            ceiling = benchmark_iteration.value
            ingress_sum: int = 0
            egress_sum: int = 0
            start_time = datetime.datetime.now(datetime.UTC)
            failure: Exception | None = None
            failure_iteration: int | None = None
            failure_started_at: datetime.datetime | None = None
            failure_ended_at: datetime.datetime | None = None
            failure_partial_sample: dict | None = None

            effective_warmup_iterations = (
                warmup_iterations
                if warmup_iterations is not None
                else Config.BENCHMARK_WARMUP_ITERATIONS
            )

            if skip_warmup:
                logger.info(
                    f"Executing benchmark for '{query_id}' with no warmup (ceiling={ceiling})."
                )
            else:
                logger.info(
                    f"Executing {effective_warmup_iterations} warmup runs."
                )
                for _ in range(effective_warmup_iterations):
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
                    if use_sequential_stopping:
                        logger.info(
                            f"Warmup complete for '{query_id}'. Starting sequential timed iterations "
                            f"(min={Config.BENCHMARK_MIN_ITERATIONS}, ceiling={ceiling}, "
                            f"min_window={Config.BENCHMARK_MIN_TIMED_WINDOW_SECONDS}s, "
                            f"max_window={Config.BENCHMARK_MAX_TIMED_WINDOW_SECONDS}s, "
                            f"target_ci_relative={Config.BENCHMARK_TARGET_CI_HALF_WIDTH_RELATIVE})."
                        )
                    else:
                        logger.info(
                            f"Warmup complete for '{query_id}'. Starting {ceiling} fixed timed iterations."
                        )

            elapsed_samples: list[float] = []
            failed_iterations: int = 0
            consecutive_failures: int = 0
            bootstrap_rng = _make_bootstrap_rng(run_id=run_id, query_id=query_id)
            stop_reason: StopReason | None = None
            soft_ceiling_warned = False
            timed_loop_start = datetime.datetime.now(datetime.UTC)

            if failure is None:
                iteration = 0
                while True:
                    iteration += 1

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
                        failed_iterations += 1
                        consecutive_failures += 1
                        ingress_sum += net_bytes_received
                        egress_sum += net_bytes_sent

                        _save_run(
                            run_id=run_id,
                            benchmark_run=benchmark_run,
                            query_id=query_id,
                            iteration=iteration,
                            total_iterations=ceiling,
                            samples=[
                                {
                                    "status": "failed",
                                    "failure_reason": str(iter_exc),
                                    "elapsed_time": None,
                                    "network_bytes_sent": net_bytes_sent,
                                    "network_bytes_received": net_bytes_received,
                                    "started_at": started_at.isoformat(),
                                    "ended_at": ended_at.isoformat(),
                                    "cpu_time_user_seconds": cpu_time_user_seconds,
                                    "cpu_time_system_seconds": cpu_time_system_seconds,
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

                        logger.warning(
                            f"Iteration {iteration} raised for '{query_id}': {iter_exc!r}. "
                            f"failed_total={failed_iterations}, "
                            f"consecutive={consecutive_failures}. Continuing past failure."
                        )

                        if (
                            consecutive_failures
                            >= Config.BENCHMARK_MAX_CONSECUTIVE_FAILURES
                        ):
                            stop_reason = StopReason.FAILED
                            logger.error(
                                f"Hit {Config.BENCHMARK_MAX_CONSECUTIVE_FAILURES} "
                                f"consecutive iteration failures for '{query_id}'; aborting."
                            )
                            break
                    else:
                        consecutive_failures = 0

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
                        elapsed_samples.append(elapsed_time)

                        _save_run(
                            run_id=run_id,
                            benchmark_run=benchmark_run,
                            query_id=query_id,
                            iteration=iteration,
                            total_iterations=ceiling,
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

                        if elapsed_time >= Config.BENCHMARK_MAX_TIMED_WINDOW_SECONDS:
                            stop_reason = StopReason.TIMEOUT
                            logger.warning(
                                f"Single iteration of '{query_id}' took "
                                f"{elapsed_time:.1f}s, exceeding "
                                f"BENCHMARK_MAX_TIMED_WINDOW_SECONDS="
                                f"{Config.BENCHMARK_MAX_TIMED_WINDOW_SECONDS}s; "
                                f"stopping."
                            )
                            break

                    if not use_sequential_stopping:
                        if iteration >= ceiling:
                            stop_reason = StopReason.FIXED
                            break
                        continue

                    window_seconds = (
                        datetime.datetime.now(datetime.UTC) - timed_loop_start
                    ).total_seconds()

                    if window_seconds >= Config.BENCHMARK_MAX_TIMED_WINDOW_SECONDS:
                        stop_reason = StopReason.TIMEOUT
                        logger.warning(
                            f"Timed window for '{query_id}' reached "
                            f"BENCHMARK_MAX_TIMED_WINDOW_SECONDS="
                            f"{Config.BENCHMARK_MAX_TIMED_WINDOW_SECONDS}s after {iteration} "
                            f"iterations; stopping. Results may be underpowered."
                        )
                        break

                    floor_met = (
                        window_seconds >= Config.BENCHMARK_MIN_TIMED_WINDOW_SECONDS
                    )
                    if (
                        len(elapsed_samples) >= Config.BENCHMARK_MIN_ITERATIONS
                        and floor_met
                    ):
                        mean, _median, half_width = _bootstrap_ci_half_width(
                            samples=elapsed_samples,
                            n_resamples=Config.BENCHMARK_BOOTSTRAP_RESAMPLES,
                            confidence=Config.BENCHMARK_CI_CONFIDENCE,
                            rng=bootstrap_rng,
                        )
                        if mean > 0 and (
                            half_width / mean
                            <= Config.BENCHMARK_TARGET_CI_HALF_WIDTH_RELATIVE
                        ):
                            stop_reason = StopReason.PRECISION
                            logger.info(
                                f"Precision target met for '{query_id}' at iteration "
                                f"{iteration} (mean={mean:.4f}s, half_width={half_width:.4f}s, "
                                f"relative={half_width / mean:.4f})."
                            )
                            break

                    if iteration >= ceiling:
                        if floor_met:
                            stop_reason = StopReason.CEILING
                            logger.info(
                                f"Iteration ceiling {ceiling} reached for '{query_id}' "
                                f"with window {window_seconds:.1f}s; stopping."
                            )
                            break
                        if not soft_ceiling_warned:
                            logger.warning(
                                f"Iteration ceiling {ceiling} reached for '{query_id}' but "
                                f"timed window only {window_seconds:.1f}s "
                                f"(< {Config.BENCHMARK_MIN_TIMED_WINDOW_SECONDS}s). "
                                f"Continuing past ceiling so the cost-metric window stays valid."
                            )
                            soft_ceiling_warned = True

            if failure is not None:
                assert failure_started_at is not None
                assert failure_ended_at is not None
                assert failure_partial_sample is not None
                _save_run(
                    run_id=run_id,
                    benchmark_run=benchmark_run,
                    query_id=query_id,
                    iteration=failure_iteration or 1,
                    total_iterations=ceiling,
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

            if failure is not None:
                stop_reason = StopReason.FAILED
            elif stop_reason is None:
                stop_reason = (
                    StopReason.FIXED if not use_sequential_stopping else StopReason.FAILED
                )

            if stop_reason in (
                StopReason.PRECISION,
                StopReason.CEILING,
                StopReason.FIXED,
                StopReason.TIMEOUT,
            ) and failed_iterations > 0:
                stop_reason = StopReason.PARTIAL

            if elapsed_samples:
                final_mean, final_median, final_half_width = _bootstrap_ci_half_width(
                    samples=elapsed_samples,
                    n_resamples=Config.BENCHMARK_BOOTSTRAP_RESAMPLES,
                    confidence=Config.BENCHMARK_CI_CONFIDENCE,
                    rng=bootstrap_rng,
                )
            else:
                final_mean = None
                final_median = None
                final_half_width = None

            if use_sequential_stopping and final_mean is not None and final_mean > 0:
                ci_half_width_relative = final_half_width / final_mean
                ci_half_width_seconds = final_half_width
            else:
                ci_half_width_relative = None
                ci_half_width_seconds = None

            achieved_iterations = len(elapsed_samples)

            end_time = datetime.datetime.now(datetime.UTC)
            logger.info(
                f"Benchmark runs completed in {round((end_time - start_time).total_seconds(), 2)} "
                f"seconds (achieved_iterations={achieved_iterations}, "
                f"failed_iterations={failed_iterations}, stop_reason={stop_reason.value})."
            )

            _save_run_metadata(
                query_id=query_id,
                run_id=run_id,
                achieved_iterations=achieved_iterations,
                failed_iterations=failed_iterations,
                stop_reason=stop_reason,
                ci_half_width_seconds=ci_half_width_seconds,
                ci_half_width_relative=ci_half_width_relative,
                mean_elapsed_seconds=final_mean,
                median_elapsed_seconds=final_median,
            )
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
