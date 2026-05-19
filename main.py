import json
import os
import random
import shutil
import string
import subprocess
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
    _run_cmd(["az", "login", "--identity"])

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

    for experiment in experiments:
        experiment_id = experiment["id"]
        if experiment_id in completed_experiments:
            continue

        related_experiment_ids = experiment["related_script_ids"]
        experiments_to_run: list[dict[str, int | str | list[str]]] = [experiment]

        for related_experiment_id in related_experiment_ids:  # type: ignore
            related_experiment = _get_experiment_from_id(
                related_experiment_id, experiments
            )

            experiments_to_run.append(related_experiment)

        with ThreadPoolExecutor(max_workers=10) as pool:
            list(
                pool.map(
                    lambda exp: _run_container_benchmark(
                        experiment=exp, run_id=run_id, benchmark_run=benchmark_run
                    ),
                    experiments_to_run,
                )
            )

        for exp in experiments_to_run:
            completed_experiments.append(str(exp["id"]))

    _clear_all_container_instances(experiments)
    logger.info(f"Completed benchmark run {benchmark_run}/{Config.BENCHMARK_RUNS}.")


def _run_container_benchmark(
    experiment: dict[str, str | int | list[str]], benchmark_run: int, run_id: str
) -> None:
    experiment_id = str(experiment["id"])
    docker_image = str(experiment["image"])
    cpu = str(experiment["cpu"])
    memory_gb = str(experiment["memory_gb"])
    dataset_size = str(experiment.get("dataset_size", "small"))

    container_group_name = f"benchmark-{experiment_id}"
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


# noinspection PyDeprecation
def _run_cmd(cmd: list[str], suppress_error_log: bool = False) -> str:
    az_path = shutil.which(cmd[0])
    if az_path is not None:
        cmd[0] = az_path

    result = subprocess.run(
        cmd, capture_output=True, text=True, check=False, shell=False
    )

    if result.returncode != 0:
        cmd_str = " ".join(cmd)
        if not suppress_error_log:
            stderr = result.stderr.strip()
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
                result.stderr.strip(),
            )

        raise RuntimeError(f"Command failed with exit code {result.returncode}")

    return result.stdout


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
    for line in lines[lines_seen:]:
        parts = line.split(" - ", 2)
        if len(parts) == 3:
            level, message = parts[1].strip().lower(), parts[2]
        else:
            level, message = "info", line

        log_fn = getattr(logger, level, logger.info)
        log_fn("[%s] %s", container_group_name, message)

    return len(lines)


def _check_container_state(
    container_group_name: str, poll_interval_seconds: float = 5
) -> None:
    lines_seen = 0

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
                logger.info(
                    f"Container '{container_group_name}' | State: '{state}' | Benchmark run completed."
                )
                break
            case "Failed":
                time.sleep(5)
                _stream_container_logs(container_group_name, lines_seen)
                error_message = f"Container '{container_group_name}' failed. Please check the logs for more information."
                logger.error(error_message)
                raise RuntimeError(error_message)
            case _:
                lines_seen = _stream_container_logs(container_group_name, lines_seen)
                time.sleep(poll_interval_seconds)


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
        _delete_container_instance(f"benchmark-{experiment_id}")


if __name__ == "__main__":
    main()
