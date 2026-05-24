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
- Benchmark batching: members of a batch list each other bidirectionally in `related_script_ids`. The orchestrator dedupes via `completed_experiments`, so each batch runs once as one parallel `ThreadPoolExecutor` fan-out. A batch must satisfy four constraints simultaneously: (a) same query type, (b) same `dataset_size`, (c) at most one PostGIS member (shared Azure Postgres server), (d) Databricks cluster vCPU sum ≤ 200, computed as `(workers + 1) × 4` per Sedona member on `Standard_D4s_v3`. See `README.md#pairing-and-randomization` for the full batch listing. *Why: peers must execute under the same wall-clock window for fair comparison, without contending on shared infrastructure or breaching regional quota.*
- Adding a benchmark requires three edits in lockstep: file in `src/presentation/entrypoints/`, `case` arm in `benchmark_runner.py`, and an entry in `benchmarks.yml`. Missing any one silently breaks dispatch or orchestration.
- Stopping rule on `@monitor`: high-frequency single-machine queries use sequential stopping (bootstrapped CI on the mean elapsed time, floors at `BENCHMARK_MIN_ITERATIONS` and `BENCHMARK_MIN_TIMED_WINDOW_SECONDS`, ceiling at the `BenchmarkIteration` value, per-iteration hard timeout at `BENCHMARK_MAX_ITERATION_SECONDS`, cumulative hard timeout at `BENCHMARK_MAX_TIMED_WINDOW_SECONDS`). Long-running low-variance benchmarks (`national_scale_spatial_join_*` for Databricks, DuckDB, and PostGIS) opt out via `use_sequential_stopping=False` and run a small fixed iteration count; they also override `warmup_iterations=1` since one warmup is enough on long-running queries and additional warmups dominate the wall-clock budget. Transient per-iteration failures do not abort the run: failed iterations are recorded as `status="failed"` samples and the loop continues until `BENCHMARK_MAX_CONSECUTIVE_FAILURES` in a row triggers `stop_reason="failed"`; a run that finishes normally but had any failed iterations is tagged `stop_reason="partial"`. *Why: bootstrap CI on <10 samples is uninformative, and the per-iteration cost of those benchmarks (cluster time, shared Postgres) outweighs precision gains. Spark/Azure flakiness is intermittent rather than deterministic — losing 2 of 3 timed iters to one transient executor loss erases data we could have kept.* See `README.md#stopping-rule` for the full rule.

## Commands

```
python main.py                                                              # full suite via ACI; needs Azure auth
python benchmark_runner.py --script-id <id> --benchmark-run 1 --run-id dev  # one benchmark locally
```

`<id>` is any `id:` from `benchmarks.yml`. No lint/test/typecheck wired up; `pyrightconfig.json` exists for editor type checks.

## Thesis integration

The master thesis PDF lives at `~/Downloads/TBA4925_Master_thesis.pdf`. When a code change lands that could affect how the thesis describes the system or methodology, do the following:

1. Read the PDF's table of contents (pages 8–10) to locate relevant chapter/section pages.
2. Read those pages and compare against the code change.
3. Identify any places where the thesis text needs updating (new sections, revised descriptions, corrected numbers, new threats to validity, etc.).
4. Post findings as a comment on the matching GitHub Discussion, prefixed with `## From issue/PR #N` and grouped by section number. Discussions exist per chapter under the "General" category on `kartAI/doppa`:
   - **Ch. 1: Introduction — Notes** (#316)
   - **Ch. 2: Background — Notes** (#317)
   - **Ch. 3: Related Work — Notes** (#318)
   - **Ch. 4: Research Design and Methodology — Notes** (#314)
   - **Ch. 5: System Architecture and Implementation — Notes** (#315)
   - **Ch. 6: Results — Notes** (#319)
   - **Ch. 7: Discussion — Notes** (#320)
   - **Ch. 8: Conclusions — Notes** (#321)
   - If a future chapter is added, create a new discussion following the same `Ch. N: <Title> — Notes` naming convention and body template (Purpose, Sections covered, Key topics, How to use).
5. Split comments that span multiple chapters so each discussion only receives its own sections.

<important if="you are adding a new benchmark">
- Create `src/presentation/entrypoints/<name>.py`; re-export from `entrypoints/__init__.py`.
- Add `case "<script-id>":` in `benchmark_runner.py`.
- Append entry to `benchmarks.yml` with `id`, `image`, `cpu`, `memory_gb`, `dataset_size`, `related_script_ids` (list peers both ways; assign to an existing batch that satisfies the four constraints in the batching invariant, or create a new batch).
- Pick the stopping rule on `@monitor`: leave the default (`use_sequential_stopping=True`) for short-iteration queries where many samples are cheap; set `use_sequential_stopping=False` when each iteration is long-running and low-variance, or the per-iteration cost (cluster time, shared Postgres) makes additional iterations expensive. In the long-running case, also set `warmup_iterations=1` so warmup does not dominate the wall-clock budget.
- If a new service is needed: contract in `application/contracts/`, impl in `infra/infrastructure/services/`, provider in `containers.py`.
</important>

<!-- maintainer: @jathavaan; review quarterly -->
