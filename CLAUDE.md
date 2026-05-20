# doppa

Reproducible benchmarking framework comparing cloud-native (DuckDB + GeoParquet, Apache Sedona on Databricks) vs traditional (PostGIS, Shapefile) geospatial query stacks on Azure. Each benchmark is a containerised experiment producing time, network, and cost metrics.

## Stack

Python, DuckDB (spatial), PostGIS on Azure Database for PostgreSQL, Apache Sedona on Databricks, Azure Blob Storage, Azure Container Instances, `dependency_injector`, FastAPI, PMTiles/MVT. See `requirements.txt` for versions.

## Layout (Clean Architecture)

- `src/domain/` — enums only; no dependencies on other layers.
- `src/application/` — `contracts/` (service interfaces), `dtos/`, `common/` (logger, monitor).
- `src/infra/` — `infrastructure/services/` (contract impls), `infrastructure/containers.py` (DI wiring), `persistence/context/` (DuckDB, Postgres, Blob clients).
- `src/presentation/` — `entrypoints/` (one file per benchmark), `configuration/app_config.py` (`initialize_dependencies`), `databricks/` (notebook script), `endpoints/tile_server.py` (FastAPI VMT server).
- `main.py` — outside-ACI orchestrator. Reads `benchmarks.yml`, launches one ACI per experiment.
- `benchmark_runner.py` — in-container dispatcher. Matches `--script-id` to a function in `src/presentation/entrypoints/`.
- `benchmarks.yml` — experiment manifest. Each entry: `id`, `image`, `cpu`, `memory_gb`, `related_script_ids`.
- `src/config.py` — `Config` frozen dataclass; all env vars and constants live here.

## Invariants

- All services are resolved through `dependency_injector`. Wire new services in `src/infra/infrastructure/containers.py` and resolve via `initialize_dependencies`; never instantiate services directly in entrypoints. *Why: keeps entrypoints thin and the container the single source of wiring.*
- Dependency direction: `presentation` → `application` → `domain`; `infra` implements `application/contracts`. No upward imports across layers.
- Env vars and tunable constants belong in `src/config.py` (`Config`). Do not call `os.getenv` from services or entrypoints. *Why: one place to audit secrets and tweak benchmark sizes.*
- Secrets live in `.env` (gitignored) and are forwarded to ACI as `--secure-environment-variables` from `main.py`.
- Benchmark batching: members of a batch list each other bidirectionally in `related_script_ids`. The orchestrator dedupes via `completed_experiments`, so each batch runs once as one parallel `ThreadPoolExecutor` fan-out. A batch must satisfy four constraints simultaneously: (a) same query type, (b) same `dataset_size`, (c) at most one PostGIS member (shared Azure Postgres server), (d) Databricks cluster vCPU sum ≤ 80, computed as `(workers + 1) × 4` per Sedona member on `Standard_D4s_v3`. See `README.md#pairing-and-randomization` for the full batch listing. *Why: peers must execute under the same wall-clock window for fair comparison, without contending on shared infrastructure or breaching regional quota.*
- Adding a benchmark requires three edits in lockstep: file in `src/presentation/entrypoints/`, `case` arm in `benchmark_runner.py`, and an entry in `benchmarks.yml`. Missing any one silently breaks dispatch or orchestration.

## Commands

```
python main.py                                                              # full suite via ACI; needs Azure auth
python benchmark_runner.py --script-id <id> --benchmark-run 1 --run-id dev  # one benchmark locally
```

`<id>` is any `id:` from `benchmarks.yml`. No lint/test/typecheck wired up; `pyrightconfig.json` exists for editor type checks.

<important if="you are adding a new benchmark">
- Create `src/presentation/entrypoints/<name>.py`; re-export from `entrypoints/__init__.py`.
- Add `case "<script-id>":` in `benchmark_runner.py`.
- Append entry to `benchmarks.yml` with `id`, `image`, `cpu`, `memory_gb`, `dataset_size`, `related_script_ids` (list peers both ways; assign to an existing batch that satisfies the four constraints in the batching invariant, or create a new batch).
- If a new service is needed: contract in `application/contracts/`, impl in `infra/infrastructure/services/`, provider in `containers.py`.
</important>

<!-- maintainer: @jathavaan; review quarterly -->
