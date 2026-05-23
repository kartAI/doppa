import datetime
import functools
import threading
import time
from typing import Any

import psutil

from src import Config
from src.application.common import logger
from src.application.common.monitor_utils import _get_run_id, _get_benchmark_run, _save_run_metadata, _save_run
from src.domain.enums import BenchmarkIteration, StopReason


def monitor_cpu_and_ram(
        query_id: str,
        benchmark_iteration: BenchmarkIteration,
        interval: float = Config.DEFAULT_SAMPLE_TIMEOUT
):
    """
    Benchmarking decorator with continuous CPU/RAM sampling. Wraps a function in
    warmup + timed iterations, runs a daemon sampler thread that records process and
    per-core CPU + RSS at the given interval, and writes the per-iteration samples
    plus run metadata to blob storage.
    :param query_id: Identifier for the benchmarked query.
    :param benchmark_iteration: Number of timed iterations to run.
    :param interval: Sampling interval in seconds. Default is Config.DEFAULT_SAMPLE_TIMEOUT.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            result = None

            run_id = _get_run_id()
            benchmark_run = _get_benchmark_run()

            process = psutil.Process()

            logger.info(f"Starting benchmark for query '{query_id}' with run ID '{run_id}'.")
            logger.info(f"Executing {Config.BENCHMARK_WARMUP_ITERATIONS} warmup runs.")
            for _ in range(Config.BENCHMARK_WARMUP_ITERATIONS):
                func(*args, **kwargs)

            logger.info(f"Warmup runs completed. Starting {benchmark_iteration.value} benchmark runs.")
            logger.info(f"Benchmarking started with sampling interval of {interval} seconds.")

            start_time = datetime.datetime.now(datetime.UTC)
            for i in range(benchmark_iteration.value):
                iteration = i + 1
                samples: list[dict[str, Any]] = []

                logger.info(f"Starting iteration {iteration}/{benchmark_iteration.value}...")

                _initialize_cpu_metrics(process=process)

                thread, thread_lock, thread_event = _initialize_threading(
                    target=_sampler,
                    process=process,
                    samples=samples,
                    interval=interval
                )

                thread.start()
                try:
                    result = func(*args, **kwargs)
                finally:
                    thread_event.set()
                    thread.join(timeout=1.0)

                _save_run(
                    run_id=run_id,
                    query_id=query_id,
                    benchmark_run=benchmark_run,
                    iteration=iteration,
                    total_iterations=benchmark_iteration.value,
                    samples=samples
                )

                logger.info(f"Iteration {iteration}/{benchmark_iteration.value} completed.")

            end_time = datetime.datetime.now(datetime.UTC)
            logger.info(f"Benchmarking completed in {round((end_time - start_time).total_seconds(), 2)} seconds.")
            _save_run_metadata(
                query_id=query_id,
                run_id=run_id,
                achieved_iterations=benchmark_iteration.value,
                failed_iterations=0,
                stop_reason=StopReason.FIXED,
                ci_half_width_seconds=None,
                ci_half_width_relative=None,
                mean_elapsed_seconds=None,
                median_elapsed_seconds=None,
            )
            logger.info(f"Benchmark run {benchmark_run} completed.")
            return result

        return wrapper

    return decorator


def _sampler(
        process: psutil.Process,
        thread_lock: threading.Lock,
        thread_event: threading.Event,
        samples: list[dict[str, Any]],
        interval: float
) -> None:
    start_timestamp, start_process_cpu_time, _, start_system_cpu_time_per_core = _get_cpu_metrics(process)
    previous_timestamp = start_timestamp
    previous_process_cpu_time = start_process_cpu_time

    while not thread_event.wait(interval):
        try:
            timestamp, process_cpu_time, cpu_percent, system_cpu_time_per_core = _get_cpu_metrics(process)
            rss = _get_rss(process)

            delta_process_cpu_time = process_cpu_time - previous_process_cpu_time
            elapsed_time = timestamp - previous_timestamp

            zeroed_elapsed_time = timestamp - start_timestamp
            core_structs = {
                f"core_{core_id}": {
                    "user": t["user"] - start_system_cpu_time_per_core[core_id]["user"],
                    "system": t["system"] - start_system_cpu_time_per_core[core_id]["system"],
                    "idle": t["idle"] - start_system_cpu_time_per_core[core_id]["idle"],
                    "iowait": t["iowait"] - start_system_cpu_time_per_core[core_id]["iowait"],
                    "percent": t["percent"]
                }
                for core_id, t in system_cpu_time_per_core.items()
            }

            with thread_lock:

                samples.append({
                    "elapsed_time": zeroed_elapsed_time,
                    "delta_time": elapsed_time,
                    "delta_process_cpu_time": delta_process_cpu_time,
                    "process_cpu_percentage": cpu_percent,
                    "rss": rss,
                    **core_structs
                })

            previous_timestamp = timestamp
            previous_process_cpu_time = process_cpu_time
        except Exception as e:
            logger.error(f"Sampling error in _sampler: {e}")


def _initialize_threading(
        target: object | None,
        process: psutil.Process,
        samples: list[dict[str, Any]],
        interval: float
) -> tuple[
    threading.Thread,
    threading.Lock,
    threading.Event
]:
    thread_lock = threading.Lock()
    thread_event = threading.Event()

    kwargs = {
        "process": process,
        "thread_lock": thread_lock,
        "thread_event": thread_event,
        "samples": samples,
        "interval": interval
    }

    thread = threading.Thread(target=target, daemon=True, kwargs=kwargs)

    return thread, thread_lock, thread_event


def _initialize_cpu_metrics(process: psutil.Process) -> None:
    # The initial `cpu_percent` returns a meaningless value. See 'https://psutil.readthedocs.io/en/latest/#psutil.cpu_percent' for more information
    process.cpu_percent(interval=None)
    psutil.cpu_percent(percpu=True)
    time.sleep(0.1)
    process.cpu_percent(interval=None)
    psutil.cpu_percent(percpu=True)


def _get_cpu_metrics(process: psutil.Process) -> tuple[float, float, float, dict[int, dict[str, float]]]:
    cpu_times = process.cpu_times()
    cpu_percent = process.cpu_percent()

    per_core_raw = psutil.cpu_times(percpu=True)
    per_core_percent = psutil.cpu_percent(percpu=True)

    system_metrics_per_core = {
        i + 1: {
            "user": c.user,
            "system": c.system,
            "idle": c.idle,
            "iowait": getattr(c, "iowait", 0.0),
            "percent": per_core_percent[i]
        }
        for i, c in enumerate(per_core_raw)
    }

    user_cpu_time = cpu_times.user
    system_cpu_time = cpu_times.system
    process_cpu_time = user_cpu_time + system_cpu_time

    timestamp = time.perf_counter()

    return timestamp, process_cpu_time, cpu_percent, system_metrics_per_core


def _get_cpu_count() -> int:
    return psutil.cpu_count(logical=True) or 1


def _get_rss(process: psutil.Process) -> float:
    rss = process.memory_info().rss
    return rss
