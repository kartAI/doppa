import base64
import json
import time
from pathlib import Path

import requests

from src import Config
from src.application.common import logger
from src.application.contracts import IDatabricksService
from src.application.dtos import DatabricksRunResult
from src.domain.enums import (
    DatabricksClusterState,
    DatabricksLibraryStatus,
    DatabricksRunLifecycleState,
    DatabricksRunResultState,
    DatasetSize,
)


class DatabricksService(IDatabricksService):
    def __init__(self) -> None:
        pass

    @property
    def _host(self) -> str:
        if not Config.DATABRICKS_HOST:
            raise EnvironmentError(
                "DATABRICKS_HOST is not set. Add it to your .env file."
            )
        return Config.DATABRICKS_HOST.rstrip("/")

    @property
    def _headers(self) -> dict:
        if not Config.DATABRICKS_TOKEN:
            raise EnvironmentError(
                "DATABRICKS_TOKEN is not set. Add it to your .env file."
            )
        return {
            "Authorization": f"Bearer {Config.DATABRICKS_TOKEN}",
            "Content-Type": "application/json",
        }

    def create_cluster(self, num_workers: int) -> str:
        cluster_id = self._create_cluster(num_workers=num_workers)
        try:
            self._install_libraries(cluster_id=cluster_id)
            self._wait_for_cluster_running(cluster_id=cluster_id)
            self._wait_for_libraries_installed(cluster_id=cluster_id)
            self._upload_notebook()
        except Exception:
            logger.warning(
                f"Cluster {cluster_id} provisioning failed before it was returned to caller. "
                f"Terminating to avoid orphan resources."
            )
            try:
                self.terminate_cluster(cluster_id=cluster_id)
            except Exception as termination_exc:
                logger.error(
                    f"Failed to terminate partially-provisioned cluster {cluster_id}: "
                    f"{termination_exc}"
                )
            raise
        logger.info(
            f"Cluster {cluster_id} ready with {num_workers} worker(s). "
            f"Libraries installed, notebook uploaded."
        )
        return cluster_id

    def submit_to_existing_cluster(
        self, cluster_id: str, num_workers: int, dataset_size: DatasetSize
    ) -> DatabricksRunResult:
        run_id = self._submit_run(
            cluster_id=cluster_id,
            num_workers=num_workers,
            dataset_size=dataset_size,
        )
        logger.info(
            f"Submitted Databricks run {run_id} on cluster {cluster_id} "
            f"against dataset size '{dataset_size.value}'. Polling for completion."
        )
        task_run_id = self._wait_for_run(run_id)
        return self._fetch_notebook_output(task_run_id)

    def terminate_cluster(self, cluster_id: str) -> None:
        response = requests.post(
            f"{self._host}/api/2.1/clusters/permanent-delete",
            headers=self._headers,
            json={"cluster_id": cluster_id},
            timeout=Config.DATABRICKS_HTTP_TIMEOUT_SECONDS,
        )
        if not response.ok:
            raise RuntimeError(
                f"Failed to permanently delete cluster {cluster_id}: "
                f"{response.status_code}: {response.text}"
            )
        logger.info(f"Permanently deleted cluster {cluster_id}.")

    def _create_cluster(self, num_workers: int) -> str:
        single_user_name = self._get_current_user_name()
        payload = {
            "cluster_name": f"doppa-national-scale-spatial-join-{num_workers}-nodes",
            "spark_version": Config.DATABRICKS_SPARK_VERSION,
            "node_type_id": Config.DATABRICKS_NODE_TYPE_ID,
            "num_workers": num_workers,
            "data_security_mode": "LEGACY_SINGLE_USER",
            "single_user_name": single_user_name,
            "spark_conf": {
                "spark.driver.memory": Config.DATABRICKS_DRIVER_MEMORY,
                "spark.driver.memoryOverhead": Config.DATABRICKS_DRIVER_MEMORY_OVERHEAD,
                f"spark.hadoop.fs.azure.account.auth.type.{Config.AZURE_BLOB_STORAGE_ACCOUNT_NAME}.dfs.core.windows.net": "SharedKey",
                f"spark.hadoop.fs.azure.account.key.{Config.AZURE_BLOB_STORAGE_ACCOUNT_NAME}.dfs.core.windows.net": Config.AZURE_BLOB_STORAGE_ACCOUNT_KEY,
            },
        }
        response = requests.post(
            f"{self._host}/api/2.1/clusters/create",
            headers=self._headers,
            json=payload,
            timeout=Config.DATABRICKS_HTTP_TIMEOUT_SECONDS,
        )
        if not response.ok:
            raise RuntimeError(
                f"Databricks clusters/create failed with {response.status_code}: {response.text}"
            )
        cluster_id: str = str(response.json()["cluster_id"])
        logger.info(
            f"Created cluster {cluster_id} with {num_workers} worker(s) "
            f"(LEGACY_SINGLE_USER mode, single_user_name='{single_user_name}')."
        )
        return cluster_id

    def _get_current_user_name(self) -> str:
        """Resolve the identity attached to the Databricks PAT.

        Workspaces that enforce Unity Catalog reject /clusters/create requests without an
        explicit ``data_security_mode``. Both ``SINGLE_USER`` and ``LEGACY_SINGLE_USER``
        (the mode used here) require ``single_user_name`` to match the caller's identity,
        so we look it up from SCIM ``/Me``.
        """
        response = requests.get(
            f"{self._host}/api/2.0/preview/scim/v2/Me",
            headers=self._headers,
            timeout=Config.DATABRICKS_HTTP_TIMEOUT_SECONDS,
        )
        if not response.ok:
            raise RuntimeError(
                f"Failed to resolve current Databricks identity via SCIM /Me: "
                f"{response.status_code}: {response.text}"
            )
        data = response.json()
        user_name = data.get("userName")
        if not user_name:
            raise RuntimeError(
                f"SCIM /Me did not return a userName. Payload: {data!r}"
            )
        return user_name

    def _install_libraries(self, cluster_id: str) -> None:
        payload = {
            "cluster_id": cluster_id,
            "libraries": [
                {"maven": {"coordinates": Config.DATABRICKS_SEDONA_MAVEN_COORDINATES}},
                {"pypi": {"package": Config.DATABRICKS_SEDONA_PYPI_PACKAGE}},
                {"pypi": {"package": Config.DATABRICKS_GEOPANDAS_PYPI_PACKAGE}},
            ],
        }
        response = requests.post(
            f"{self._host}/api/2.0/libraries/install",
            headers=self._headers,
            json=payload,
            timeout=Config.DATABRICKS_HTTP_TIMEOUT_SECONDS,
        )
        if not response.ok:
            raise RuntimeError(
                f"Databricks libraries/install failed for cluster {cluster_id}: "
                f"{response.status_code}: {response.text}"
            )
        logger.info(f"Requested library install on cluster {cluster_id}.")

    def _wait_for_cluster_running(self, cluster_id: str) -> None:
        while True:
            try:
                response = requests.get(
                    f"{self._host}/api/2.1/clusters/get",
                    headers=self._headers,
                    params={"cluster_id": cluster_id},
                    timeout=Config.DATABRICKS_HTTP_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
            except (requests.ConnectionError, requests.Timeout) as exc:
                logger.warning(
                    f"Transient network error polling cluster {cluster_id}: {exc}. "
                    f"Retrying in {Config.DATABRICKS_POLL_INTERVAL_SECONDS}s."
                )
                time.sleep(Config.DATABRICKS_POLL_INTERVAL_SECONDS)
                continue
            data = response.json()
            state = data.get("state", "")
            logger.info(f"Cluster {cluster_id}: state={state}")
            if state == DatabricksClusterState.RUNNING.value:
                return
            if state in DatabricksClusterState.non_running_terminal_values():
                state_message = data.get("state_message", "")
                raise RuntimeError(
                    f"Cluster {cluster_id} reached unexpected state '{state}' "
                    f"before RUNNING. State message: {state_message}"
                )
            time.sleep(Config.DATABRICKS_POLL_INTERVAL_SECONDS)

    def _wait_for_libraries_installed(self, cluster_id: str) -> None:
        while True:
            try:
                response = requests.get(
                    f"{self._host}/api/2.0/libraries/cluster-status",
                    headers=self._headers,
                    params={"cluster_id": cluster_id},
                    timeout=Config.DATABRICKS_HTTP_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
            except (requests.ConnectionError, requests.Timeout) as exc:
                logger.warning(
                    f"Transient network error polling library status on cluster {cluster_id}: {exc}. "
                    f"Retrying in {Config.DATABRICKS_POLL_INTERVAL_SECONDS}s."
                )
                time.sleep(Config.DATABRICKS_POLL_INTERVAL_SECONDS)
                continue
            data = response.json()
            statuses = data.get("library_statuses", [])
            if not statuses:
                logger.info(
                    f"Cluster {cluster_id}: no library statuses reported yet. Waiting."
                )
                time.sleep(Config.DATABRICKS_POLL_INTERVAL_SECONDS)
                continue

            summary = ", ".join(
                f"{self._library_label(s.get('library', {}))}={s.get('status', '')}"
                for s in statuses
            )
            logger.info(f"Cluster {cluster_id} library status: {summary}")

            failed = [
                s
                for s in statuses
                if s.get("status", "") in DatabricksLibraryStatus.terminal_failure_values()
            ]
            if failed:
                details = "; ".join(
                    f"{self._library_label(s.get('library', {}))} -> {s.get('status', '')} "
                    f"({s.get('messages', [])})"
                    for s in failed
                )
                raise RuntimeError(
                    f"One or more libraries failed to install on cluster {cluster_id}: {details}"
                )

            if all(
                s.get("status", "") == DatabricksLibraryStatus.INSTALLED.value
                for s in statuses
            ):
                return

            time.sleep(Config.DATABRICKS_POLL_INTERVAL_SECONDS)

    @staticmethod
    def _library_label(library: dict) -> str:
        if "maven" in library:
            return library["maven"].get("coordinates", "maven:?")
        if "pypi" in library:
            return library["pypi"].get("package", "pypi:?")
        return next(iter(library.keys()), "library")

    def _upload_notebook(self) -> None:
        folder = str(Path(Config.DATABRICKS_WORKSPACE_NOTEBOOK_PATH).parent)
        mkdirs_response = requests.post(
            f"{self._host}/api/2.0/workspace/mkdirs",
            headers=self._headers,
            json={"path": folder},
            timeout=Config.DATABRICKS_HTTP_TIMEOUT_SECONDS,
        )
        if not mkdirs_response.ok:
            raise RuntimeError(
                f"Failed to create workspace folder: {mkdirs_response.status_code}: {mkdirs_response.text}"
            )

        content = base64.b64encode(
            Path(Config.DATABRICKS_LOCAL_SCRIPT_PATH).read_bytes()
        ).decode("utf-8")
        response = requests.post(
            f"{self._host}/api/2.0/workspace/import",
            headers=self._headers,
            json={
                "path": Config.DATABRICKS_WORKSPACE_NOTEBOOK_PATH,
                "format": "SOURCE",
                "language": "PYTHON",
                "content": content,
                "overwrite": True,
            },
            timeout=Config.DATABRICKS_HTTP_TIMEOUT_SECONDS,
        )
        if not response.ok:
            raise RuntimeError(
                f"Failed to upload notebook to workspace: {response.status_code}: {response.text}"
            )
        logger.info(
            f"Uploaded notebook to '{Config.DATABRICKS_WORKSPACE_NOTEBOOK_PATH}'."
        )

    def _submit_run(
        self, cluster_id: str, num_workers: int, dataset_size: DatasetSize
    ) -> str:
        payload = {
            "run_name": f"national-scale-spatial-join-{num_workers}-nodes-{dataset_size.value}",
            "tasks": [
                {
                    "task_key": "spatial-join",
                    "notebook_task": {
                        "notebook_path": Config.DATABRICKS_WORKSPACE_NOTEBOOK_PATH,
                        "base_parameters": {
                            "account_key": Config.AZURE_BLOB_STORAGE_ACCOUNT_KEY,
                            "account_name": Config.AZURE_BLOB_STORAGE_ACCOUNT_NAME,
                            "release": Config.BENCHMARK_DOPPA_DATA_RELEASE,
                            "municipalities_file": Config.DATABRICKS_MUNICIPALITIES_FILE,
                            "dataset_size": dataset_size.value,
                        },
                    },
                    "existing_cluster_id": cluster_id,
                }
            ],
        }

        response = requests.post(
            f"{self._host}/api/2.1/jobs/runs/submit",
            headers=self._headers,
            json=payload,
            timeout=Config.DATABRICKS_HTTP_TIMEOUT_SECONDS,
        )
        if not response.ok:
            raise RuntimeError(
                f"Databricks runs/submit failed with {response.status_code}: {response.text}"
            )
        run_id: str = str(response.json()["run_id"])
        return run_id

    def _wait_for_run(self, run_id: str) -> str:
        """Poll until terminal state. Logs API-reported durations for diagnostic purposes.

        Returns the task run id (sub-run under the parent job run), which is the id
        required by /api/2.1/jobs/runs/get-output. Passing the parent run id to
        get-output returns 400 Bad Request.
        """
        while True:
            try:
                response = requests.get(
                    f"{self._host}/api/2.1/jobs/runs/get",
                    headers=self._headers,
                    params={"run_id": run_id},
                    timeout=Config.DATABRICKS_HTTP_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
            except (requests.ConnectionError, requests.Timeout) as exc:
                logger.warning(
                    f"Transient network error polling run {run_id}: {exc}. "
                    f"Retrying in {Config.DATABRICKS_POLL_INTERVAL_SECONDS}s."
                )
                time.sleep(Config.DATABRICKS_POLL_INTERVAL_SECONDS)
                continue
            data = response.json()

            state = data.get("state", {})
            life_cycle_state = state.get("life_cycle_state", "")
            result_state = state.get("result_state", "")

            state_msg = f"life_cycle_state={life_cycle_state}"
            if result_state:
                state_msg += f", result_state={result_state}"
            logger.info(f"Run {run_id}: {state_msg}")

            if life_cycle_state in DatabricksRunLifecycleState.terminal_values():
                if result_state != DatabricksRunResultState.SUCCESS.value:
                    raise RuntimeError(
                        f"Databricks run {run_id} finished with result_state='{result_state}'. "
                        f"State message: {state.get('state_message', '')}"
                    )
                execution_duration_ms = data.get("execution_duration", 0)
                setup_duration_ms = data.get("setup_duration", 0)
                cleanup_duration_ms = data.get("cleanup_duration", 0)
                logger.info(
                    f"Databricks run {run_id} completed successfully. "
                    f"setup={setup_duration_ms / 1000:.1f}s, "
                    f"execution={execution_duration_ms / 1000:.1f}s, "
                    f"cleanup={cleanup_duration_ms / 1000:.1f}s"
                )
                tasks = data.get("tasks") or []
                if not tasks:
                    raise RuntimeError(
                        f"Databricks run {run_id} has no tasks in response payload; "
                        f"cannot resolve task run id for notebook output."
                    )
                task_run_id = str(tasks[0].get("run_id"))
                logger.info(
                    f"Resolved task run id {task_run_id} for parent run {run_id}."
                )
                return task_run_id

            time.sleep(Config.DATABRICKS_POLL_INTERVAL_SECONDS)

    def _fetch_notebook_output(self, run_id: str) -> DatabricksRunResult:
        """Fetch the notebook's dbutils.notebook.exit JSON payload and return a DatabricksRunResult.

        run_id here must be the task run id (returned by _wait_for_run), not the parent
        job run id from runs/submit.
        """
        response = requests.get(
            f"{self._host}/api/2.1/jobs/runs/get-output",
            headers=self._headers,
            params={"run_id": run_id},
            timeout=Config.DATABRICKS_HTTP_TIMEOUT_SECONDS,
        )
        if not response.ok:
            raise RuntimeError(
                f"Databricks runs/get-output failed for run {run_id}: "
                f"{response.status_code} {response.reason}: {response.text}"
            )
        payload = response.json()

        notebook_output = payload.get("notebook_output", {})
        raw_result = notebook_output.get("result")
        if not raw_result:
            raise RuntimeError(
                f"Databricks run {run_id} produced no notebook_output.result. "
                f"Expected JSON with execution_duration_s, cardinality, and Spark phase metrics."
            )

        try:
            parsed = json.loads(raw_result)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Databricks run {run_id} notebook_output.result is not valid JSON: {raw_result!r}"
            ) from exc

        try:
            result = DatabricksRunResult(
                execution_duration_s=float(parsed["execution_duration_s"]),
                cardinality=int(parsed["cardinality"]),
                executor_input_bytes_read=int(parsed["executor_input_bytes_read"]),
                executor_run_time_ms=int(parsed["executor_run_time_ms"]),
                shuffle_read_bytes=int(parsed["shuffle_read_bytes"]),
                shuffle_write_bytes=int(parsed["shuffle_write_bytes"]),
                driver_collection_time_ms=int(parsed["driver_collection_time_ms"]),
                stage_durations_ms=str(parsed["stage_durations_ms"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Databricks run {run_id} notebook_output.result missing required fields. "
                f"Got: {parsed!r}"
            ) from exc

        logger.info(
            f"Databricks run {run_id} notebook output: "
            f"execution_duration_s={result.execution_duration_s:.3f}, "
            f"cardinality={result.cardinality}, "
            f"executor_run_time_ms={result.executor_run_time_ms}, "
            f"shuffle_read_bytes={result.shuffle_read_bytes}, "
            f"shuffle_write_bytes={result.shuffle_write_bytes}, "
            f"driver_collection_time_ms={result.driver_collection_time_ms}"
        )
        return result
