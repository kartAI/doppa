import hashlib
import json
import os
import random
import shutil
import string
import subprocess
import threading
import time
from datetime import date
from concurrent.futures import ThreadPoolExecutor

import yaml

from src import Config
from src.application.common import logger
from src.domain.enums import StorageContainer


def main() -> None:
    """
    Orchestrates the full benchmark suite from outside Azure Container Instances.
    Authenticates to Azure, reads the experiments from ``benchmarks.yml``, generates
    a run ID, validates ``related_script_ids`` cross-references, then for each
    benchmark run launches every experiment as a one-shot ACI, streams its logs
    until success or failure, and cleans up container groups before and after.
    """
    _ensure_azure_login()

    with open(Config.BENCHMARK_FILE) as f:
        benchmark_configuration = yaml.safe_load(f)

    run_id = _create_run_id()
    logger.info(f"Started benchmark with run ID '{run_id}'.")

    for benchmark_run in range(1, Config.BENCHMARK_RUNS + 1):
        _run_benchmarks(
            run_id=run_id,
            benchmark_run=benchmark_run,
            benchmark_configuration=benchmark_configuration,
        )


def _run_benchmarks(
    run_id: str,
    benchmark_run: int,
    benchmark_configuration: dict[str, list[dict[str, str | int | list[str]]]],
) -> None:
    logger.info(f"Executing benchmark run {benchmark_run}/{Config.BENCHMARK_RUNS}.")

    experiments = list(benchmark_configuration["experiments"])

    rng = random.Random(benchmark_run)
    rng.shuffle(experiments)

    _assert_related_ids_resolvable(experiments)

    logger.info(
        "Benchmark run %s execution order: %s",
        benchmark_run,
        [exp["id"] for exp in experiments],
    )

    completed_experiments: list[str] = []
    _clear_all_container_instances(experiments)

    total_batches = _count_batches(experiments)
    current_batch = 0
    batch_durations: list[float] = []
    suite_start = time.monotonic()

    for experiment in experiments:
        experiment_id = experiment["id"]
        if experiment_id in completed_experiments:
            continue

        experiment_runs = experiment.get("runs", Config.BENCHMARK_RUNS)
        if benchmark_run > experiment_runs:
            completed_experiments.append(experiment_id)
            for rid in experiment.get("related_script_ids", []):
                completed_experiments.append(str(rid))
            logger.info(
                "Skipping '%s' — benchmark run %s exceeds experiment runs limit %s.",
                experiment_id, benchmark_run, experiment_runs,
            )
            continue

        current_batch += 1

        related_experiment_ids = experiment["related_script_ids"]
        experiments_to_run: list[dict[str, int | str | list[str]]] = [experiment]

        for related_experiment_id in related_experiment_ids:  # type: ignore
            related_experiment = _get_experiment_from_id(
                related_experiment_id, experiments
            )

            experiments_to_run.append(related_experiment)

        batch_ids = [str(exp["id"]) for exp in experiments_to_run]
        pct = (current_batch - 1) / total_batches * 100
        eta = _estimate_eta(batch_durations, total_batches - current_batch + 1)
        logger.info(
            "[%s/%s] %s%% — Starting batch: %s%s",
            current_batch, total_batches, f"{pct:.0f}", batch_ids, eta,
        )

        batch_start = time.monotonic()
        batch_size = len(experiments_to_run)
        batch_done = [0]
        batch_lock = threading.Lock()
        failed_ids: list[str] = []

        def _safe_run(exp: dict[str, str | int | list[str]]) -> None:
            try:
                _run_container_benchmark(
                    experiment=exp, run_id=run_id, benchmark_run=benchmark_run
                )
            except Exception as exc:
                failed_ids.append(str(exp["id"]))
                logger.error(
                    f"Experiment '{exp['id']}' failed at orchestrator level; "
                    f"continuing with remaining experiments. Error: {exc!r}"
                )
            finally:
                with batch_lock:
                    batch_done[0] += 1
                    logger.info(
                        "  [%s/%s in batch] '%s' done",
                        batch_done[0], batch_size, exp["id"],
                    )

        with ThreadPoolExecutor(max_workers=10) as pool:
            list(pool.map(_safe_run, experiments_to_run))

        batch_elapsed = time.monotonic() - batch_start
        batch_durations.append(batch_elapsed)

        if failed_ids:
            total = len(experiments_to_run)
            all_failed = len(failed_ids) == total
            detail = (
                "Entire batch failed; no usable data from this batch."
                if all_failed
                else "Surviving peers ran without matched counterparts; "
                "fair-comparison assumptions may not hold for this batch."
            )
            logger.warning(
                "Batch incomplete: %s of %s members failed (%s). %s",
                len(failed_ids),
                total,
                ", ".join(failed_ids),
                detail,
            )

        for exp in experiments_to_run:
            completed_experiments.append(str(exp["id"]))

        pct = current_batch / total_batches * 100
        eta = _estimate_eta(batch_durations, total_batches - current_batch)
        logger.info(
            "[%s/%s] %s%% — Batch done in %s%s",
            current_batch, total_batches, f"{pct:.0f}",
            _format_duration(batch_elapsed), eta,
        )

    _clear_all_container_instances(experiments)
    total_elapsed = time.monotonic() - suite_start
    logger.info(
        f"Completed benchmark run {benchmark_run}/{Config.BENCHMARK_RUNS} "
        f"in {_format_duration(total_elapsed)}."
    )


def _run_container_benchmark(
    experiment: dict[str, str | int | list[str]], benchmark_run: int, run_id: str
) -> None:
    experiment_id = str(experiment["id"])
    docker_image = str(experiment["image"])
    cpu = str(experiment["cpu"])
    memory_gb = str(experiment["memory_gb"])
    dataset_size = str(experiment.get("dataset_size", "small"))

    container_group_name = _container_group_name(experiment_id)
    _delete_container_instance(container_group_name=container_group_name)
    _create_container_instance(
        run_id=run_id,
        benchmark_run=benchmark_run,
        experiment_id=experiment_id,
        container_group_name=container_group_name,
        docker_image=docker_image,
        cpu=cpu,
        memory_gb=memory_gb,
        dataset_size=dataset_size,
    )
    _check_container_state(container_group_name=container_group_name)
    _delete_container_instance(container_group_name=container_group_name)


def _create_run_id() -> str:
    date_prefix = date.today().isoformat()
    suffix = "".join(
        random.choices(string.ascii_uppercase + string.digits, k=Config.RUN_ID_LENGTH)
    )

    return f"{date_prefix}-{suffix}"


def _container_group_name(experiment_id: str) -> str:
    name = f"benchmark-{experiment_id}"
    if len(name) <= 63:
        return name

    digest = hashlib.sha1(experiment_id.encode()).hexdigest()[:8]
    budget = 63 - len("benchmark-") - 1 - len(digest)
    truncated = experiment_id[:budget].rstrip("-")
    return f"benchmark-{truncated}-{digest}"


def _ensure_azure_login() -> None:
    try:
        _run_cmd(["az", "account", "show"], suppress_error_log=True)
        logger.info("Azure CLI already authenticated; skipping managed-identity login.")
        return
    except RuntimeError:
        pass

    _run_cmd(["az", "login", "--identity"])


# noinspection PyDeprecation
def _run_cmd(
    cmd: list[str],
    suppress_error_log: bool = False,
    retries: int = 3,
    backoff_seconds: float = 10,
) -> str:
    az_path = shutil.which(cmd[0])
    if az_path is not None:
        cmd[0] = az_path

    retries = max(1, retries)
    for attempt in range(1, retries + 1):
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False, shell=False
        )

        if result.returncode == 0:
            return result.stdout

        stderr = result.stderr.strip()
        is_transient = any(
            marker in stderr
            for marker in ("Connection aborted", "ConnectionError", "BadStatusLine", "status code 0")
        )

        if is_transient and attempt < retries:
            cmd_str = " ".join(cmd)
            wait = backoff_seconds * attempt
            logger.warning(
                "Transient failure (attempt %s/%s, exit %s): %s | stderr: %s. "
                "Retrying in %ss.",
                attempt, retries, result.returncode, cmd_str, stderr, wait,
            )
            time.sleep(wait)
            continue

        cmd_str = " ".join(cmd)
        if not suppress_error_log:
            stdout = result.stdout.strip()
            logger.error(
                "Command failed (exit %s): %s | stderr: %s%s",
                result.returncode,
                cmd_str,
                stderr,
                f" | stdout: {stdout}" if stdout else "",
            )
        else:
            logger.debug(
                "Soft-check command failure: %s | stderr: %s",
                cmd_str,
                stderr,
            )

        raise RuntimeError(f"Command failed with exit code {result.returncode}")

    raise RuntimeError("Unreachable: retries exhausted")


def _container_exists(container_group_name: str) -> bool:
    check_cmd = [
        "az",
        "container",
        "show",
        "--resource-group",
        Config.AZURE_RESOURCE_GROUP,
        "--name",
        container_group_name,
    ]

    try:
        _run_cmd(check_cmd, suppress_error_log=True)
        return True
    except RuntimeError:
        return False


def _delete_container_instance(container_group_name: str) -> None:
    if not _container_exists(container_group_name):
        logger.debug(
            f"Container group '{container_group_name}' does not exist. Skipping deletion."
        )
        return

    delete_command = [
        "az",
        "container",
        "delete",
        "--resource-group",
        Config.AZURE_RESOURCE_GROUP,
        "--name",
        container_group_name,
        "--yes",
    ]

    _run_cmd(delete_command)
    logger.info(f"Deleted container group '{container_group_name}'")


def _create_container_instance(
    run_id: str,
    benchmark_run: int,
    experiment_id: str,
    container_group_name: str,
    docker_image: str,
    cpu: str,
    memory_gb: str,
    dataset_size: str,
) -> None:
    acr_login_server = os.getenv("ACR_LOGIN_SERVER")

    startup_command = (
        f"python benchmark_runner.py "
        f"--script-id {experiment_id} "
        f"--benchmark-run {benchmark_run} "
        f"--run-id {run_id} "
        f"--dataset-size {dataset_size}"
    )

    create_command = [
        "az",
        "container",
        "create",
        "--resource-group",
        Config.AZURE_RESOURCE_GROUP,
        "--name",
        container_group_name,
        "--image",
        docker_image,
        "--location",
        Config.AZURE_RESOURCE_LOCATION,
        "--restart-policy",
        "Never",
        "--os-type",
        "Linux",
        "--cpu",
        cpu,
        "--memory",
        memory_gb,
        "--command-line",
        startup_command,
        "--assign-identity",
        Config.AZURE_UAMI_RESOURCE_ID,
        "--registry-login-server",
        acr_login_server,
        "--acr-identity",
        Config.AZURE_UAMI_RESOURCE_ID,
        "--environment-variables",
        f"AZURE_SUBSCRIPTION_ID={Config.AZURE_SUBSCRIPTION_ID}",
        f"AZURE_BLOB_STORAGE_BENCHMARK_CONTAINER={StorageContainer.BENCHMARKS.value}",
        f"AZURE_BLOB_STORAGE_METADATA_CONTAINER={StorageContainer.METADATA.value}",
        f"POSTGRES_SERVER_NAME={Config.POSTGRES_SERVER_NAME}",
        "--secure-environment-variables",
        f"AZURE_BLOB_STORAGE_CONNECTION_STRING={Config.AZURE_BLOB_STORAGE_CONNECTION_STRING}",
        f"POSTGRES_USERNAME={Config.POSTGRES_USERNAME}",
        f"POSTGRES_PASSWORD={Config.POSTGRES_PASSWORD}",
        f"DATABRICKS_HOST={Config.DATABRICKS_HOST}",
        f"DATABRICKS_TOKEN={Config.DATABRICKS_TOKEN}",
        f"AZURE_BLOB_STORAGE_ACCOUNT_KEY={Config.AZURE_BLOB_STORAGE_ACCOUNT_KEY}",
        "--no-wait",
    ]

    logger.info(f"Creating container group '{container_group_name}'...")
    _run_cmd(create_command)
    logger.info(
        "Benchmark run %s/%s - Created container group '%s' (experiment=%s, CPU=%s cores, RAM=%s GB, run_id=%s)",
        benchmark_run,
        Config.BENCHMARK_RUNS,
        container_group_name,
        experiment_id,
        cpu,
        memory_gb,
        run_id,
    )


def _stream_container_logs(container_group_name: str, lines_seen: int) -> int:
    logs_command = [
        "az",
        "container",
        "logs",
        "--resource-group",
        Config.AZURE_RESOURCE_GROUP,
        "--name",
        container_group_name,
    ]

    try:
        output = _run_cmd(logs_command, suppress_error_log=True)
    except RuntimeError:
        return lines_seen

    lines = [line for line in output.splitlines() if line.strip()]
    last_level = "info"
    for line in lines[lines_seen:]:
        parts = line.split(" - ", 2)
        if len(parts) == 3:
            level, message = parts[1].strip().lower(), parts[2]
            last_level = level
        else:
            level, message = last_level, line

        if level not in ("warning", "error", "critical"):
            continue

        log_fn = getattr(logger, level, logger.warning)
        log_fn("[%s] %s", container_group_name, message)

    return len(lines)


def _check_container_state(
    container_group_name: str,
    poll_interval_seconds: float = 5,
    heartbeat_interval_seconds: float = 300,
) -> None:
    lines_seen = 0
    start = time.monotonic()
    last_heartbeat = start

    while True:
        show_command = [
            "az",
            "container",
            "show",
            "--resource-group",
            Config.AZURE_RESOURCE_GROUP,
            "--name",
            container_group_name,
            "--output",
            "json",
        ]

        data = json.loads(_run_cmd(show_command))
        state = data["instanceView"]["state"]

        match state:
            case "Succeeded":
                time.sleep(5)
                lines_seen = _stream_container_logs(container_group_name, lines_seen)
                elapsed = time.monotonic() - start
                logger.info(
                    f"Container '{container_group_name}' completed in {_format_duration(elapsed)}."
                )
                break
            case "Failed" | "Stopped" | "Terminated":
                time.sleep(5)
                _stream_container_logs(container_group_name, lines_seen)
                error_message = f"Container '{container_group_name}' {state.lower()}. Please check the logs for more information."
                logger.error(error_message)
                raise RuntimeError(error_message)
            case _:
                lines_seen = _stream_container_logs(container_group_name, lines_seen)
                now = time.monotonic()
                if now - last_heartbeat >= heartbeat_interval_seconds:
                    elapsed = now - start
                    logger.info(
                        f"[{container_group_name}] Still running ({_format_duration(elapsed)} elapsed)"
                    )
                    last_heartbeat = now
                time.sleep(poll_interval_seconds)


def _count_batches(experiments: list[dict[str, str | int | list[str]]]) -> int:
    seen: set[str] = set()
    count = 0
    for exp in experiments:
        exp_id = str(exp["id"])
        if exp_id in seen:
            continue
        count += 1
        seen.add(exp_id)
        for rid in exp.get("related_script_ids", []):
            seen.add(str(rid))
    return count


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}min"
    hours = minutes / 60
    return f"{hours:.1f}h"


def _estimate_eta(batch_durations: list[float], remaining: int) -> str:
    if not batch_durations or remaining <= 0:
        return ""
    avg = sum(batch_durations) / len(batch_durations)
    return f" — ETA: {_format_duration(avg * remaining)}"


def _assert_related_ids_resolvable(
    experiments: list[dict[str, str | int | list[str]]],
) -> None:
    known_ids = {str(exp["id"]) for exp in experiments}
    missing: dict[str, list[str]] = {}

    for experiment in experiments:
        experiment_id = str(experiment["id"])
        related_ids = experiment.get("related_script_ids") or []
        unresolved = [
            str(rid) for rid in related_ids if str(rid) not in known_ids  # type: ignore
        ]
        if unresolved:
            missing[experiment_id] = unresolved

    if missing:
        raise ValueError(f"Unresolvable related_script_ids references: {missing}")


def _get_experiment_from_id(
    script_id: str,
    experiments: list[dict[str, str | int | list[str]]],
) -> dict[str, str | int | list[str]]:
    for experiment in experiments:
        if experiment["id"] == script_id:
            return experiment

    raise ValueError(f"Script ID '{script_id}' not found")


def _clear_all_container_instances(
    experiments: list[dict[str, str | int | list[str]]],
) -> None:
    experiment_ids = [exp["id"] for exp in experiments]
    for experiment_id in experiment_ids:
        _delete_container_instance(_container_group_name(str(experiment_id)))


if __name__ == "__main__":
    main()
