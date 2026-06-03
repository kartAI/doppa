# doppa: A Framework for Comparing Traditional & CNG Queries

doppa is a reproducible benchmarking framework for evaluating traditional geospatial query stacks
(PostGIS, shapefiles) against cloud-native geospatial (CNG) alternatives (DuckDB over GeoParquet in
blob storage and Apache Sedona on Databricks) across a range of real-world
spatial query patterns: point-in-polygon lookups, k-nearest-neighbour search, bounding-box filtering,
and a national-scale spatial join.

Each query is packaged as an independent container image, executed on Azure Container Instances via
an orchestrator, and produces cost and runtime metrics written back to blob storage for downstream
analysis. The framework is designed to make the trade-offs between traditional and CNG approaches
measurable and reproducible on identical datasets and hardware.

<div align="center">

[![Push containers to Azure Container Registry](https://github.com/kartAI/doppa-data/actions/workflows/push-containers-to-acr.yml/badge.svg)](https://github.com/kartAI/doppa-data/actions/workflows/push-containers-to-acr.yml)

</div>

## Related repositories

doppa is the middle stage of a three-repository pipeline built for the thesis (TBA4925, NTNU Geomatics).
The repos depend on each other end to end: datasets are published upstream, benchmarked here, and analysed
downstream.

```
doppa-data-contribution  ──►  doppa  ──►  doppa-analytics
   publish datasets          (this repo)    read results, build
   to blob storage           run engines    thesis figures/tables
                             write metrics
```

| Repository | Role | Link |
|------------|------|------|
| **doppa-data-contribution** | Downloads OSM, FKB, Microsoft Buildings, and municipality boundaries, normalizes them to the shared GeoParquet schema, and publishes them to the `contributions` blob container that this framework reads | [kartAI/doppa-data-contribution](https://github.com/kartAI/doppa-data-contribution) |
| **doppa** | Reproducible benchmarking framework. Consumes the published datasets, runs the spatial-query benchmarks on Azure, and writes per-iteration samples and cost rows back to blob storage *(this repo)* | — |
| **doppa-analytics** | Reads the benchmark result Parquet from blob storage, runs the statistical tests (Wilcoxon, bootstrapped CIs, Vargha–Delaney Â12), and generates the thesis figures and LaTeX tables | [kartAI/doppa-analytics](https://github.com/kartAI/doppa-analytics) |

## Table of contents

- [Related repositories](#related-repositories)
- [Research gaps addressed](#research-gaps-addressed)
- [Benchmarking framework](#benchmarking-framework)
    - [Measurement loop](#measurement-loop)
    - [Engines under test](#engines-under-test)
    - [Databricks cluster lifecycle](#databricks-cluster-lifecycle)
    - [Pairing and randomization](#pairing-and-randomization)
    - [Test matrix](#test-matrix)
- [Dataset layout](#dataset-layout)
    - [Sizes and synthesis](#sizes-and-synthesis)
    - [Postgres tables](#postgres-tables)
- [Setup](#setup)
    - [Azure Resources](#azure-resources)
        - [Resource naming](#resource-naming)
        - [Resource group](#resource-group)
        - [Blob storage](#blob-storage)
        - [User-Assigned Managed Identity (UAMI)](#user-assigned-managed-identity-uami)
        - [Container registry](#container-registry)
        - [PostgreSQL database](#postgresql-database)
        - [Web app for containers](#web-app-for-containers)
        - [Databricks](#databricks)
    - [Local development](#local-development)
    - [GitHub Actions](#github-actions)
    - [Setup runtime and test mode](#setup-runtime-and-test-mode)
- [Running the framework](#running-the-framework)
- [References](#references)

## Research gaps addressed

The framework is built around the three gaps identified in chapter 3 of the accompanying thesis.

**Network transfer accounting.** Most spatial benchmarks treat network communication as a system-design concern (Tang
et al. 2020) rather than a reported experimental metric. Cloud delivery cost, however, is partly driven by transferred
bytes (Folkerts et al. 2013). doppa records `network_bytes_sent` and `network_bytes_received` per iteration as primary
outputs alongside elapsed time. The Databricks notebook additionally reports executor input bytes and shuffle read /
write bytes via the `SparkListener`. PostgreSQL ingress and egress are read from Azure Monitor. `AzureCostService`
derives `network_cost` directly from these counters when it computes per-benchmark cost rows, so the link from
format internals to client-observed cost is measured end to end.

**Cloud-native vector formats vs. traditional formats on cloud storage.** Empirical comparisons in the literature
(Holmes 2023; Flatgeobuf 2024) measure write times and file sizes on local disk and do not place cloud-native and
traditional formats side by side on cloud storage. doppa benchmarks GeoParquet over Azure Blob Storage (via DuckDB)
against PostGIS on Azure Database for PostgreSQL, across the active
catalog of query patterns: point-in-polygon lookups, k-nearest-neighbour search, bounding-box filtering, and a
national-scale spatial join. The local-Shapefile entrypoints sit on the side as a laptop-workflow reference, with the
Shapefile downloaded ahead of the timed scope to emulate that workflow rather than to bench the format on cloud
storage.

**Single-node vs. distributed engines on the same vector workload.** Prior comparisons restrict themselves either to
Spark-based systems (Pandey et al. 2018) or to single-node engines (Jackpine; Ray et al. 2011). doppa runs the same
national-scale spatial join through DuckDB, PostGIS, and Apache Sedona on Databricks at five cluster sizes (2, 4, 8,
12, and 16 workers), against the same `counties.parquet` boundary set and the same `BENCHMARK_DOPPA_DATA_RELEASE`
building dataset. Two Sedona join-strategy variants are compared at each cluster size: `broadcast` (small-side
`broadcast()` hint forcing `BroadcastIndexJoin`) and `partitioned` (Sedona KDB-tree partitioner forcing `RangeJoin`).
A third variant, `default` (no hint; Spark's cost-based optimizer picks the plan), was considered as an untuned
baseline but dropped because iterations consistently timed out or failed at this workload scale, making reliable
measurement infeasible within the study's budget and time constraints (issue #254). With the cluster-reuse
measurement window in place, every
engine reports elapsed time and cost over the same span — warmup outside the window, timed iterations on a warm engine
— so the comparison is symmetric. Distributed-only metrics (shuffle bytes, stage durations, driver collection time)
are recorded as additional columns rather than as replacements for the cross-engine ones.

The methodological gap noted in the thesis — the absence of effect-size reporting and uncertainty quantification in
spatial benchmarks — is handled in downstream analysis. The framework's contribution is to persist every iteration's
raw sample so distributions, Wilcoxon rank-sum tests, bootstrapped confidence intervals, and Vargha–Delaney Â12 effect
sizes can be computed without re-running the benchmark.

## Benchmarking framework

The framework runs every benchmark under a uniform measurement protocol so that single-node and distributed engines can
be compared on the same axes (elapsed time, network bytes, cost). Each benchmark lives as an independent container
image, orchestrated by `main.py`, dispatched by `benchmark_runner.py`, and implemented in `src/presentation/entrypoints/`.

### Measurement loop

Every entrypoint is wrapped by the `@monitor` decorator in `src/application/common/monitor.py`. One execution proceeds
as:

1. **Warmup iterations** run `Config.BENCHMARK_WARMUP_ITERATIONS` times (default 5). Results are discarded. Warmup
   primes the OS page cache, DuckDB and PostgreSQL connection state, and any JIT-compiled hot paths in the engine.
2. **Timed iterations** record per-iteration:
    - wall-clock elapsed time (`time.perf_counter`),
    - process CPU user and system seconds (`psutil.Process.cpu_times`),
    - container network bytes sent and received (`psutil.net_io_counters`),
    - result cardinality.
   The loop stops via one of two rules depending on the benchmark (see [Stopping rule](#stopping-rule) below).
3. **Cost analytics** are computed once per benchmark over the wall-clock window that covers the timed iterations only.
   Warmup is excluded. Pricing constants live in `src/infra/infrastructure/services/azure_pricing_service.py`, pinned
   to 2026 Norway East rates with source URLs and update notes.

Per-iteration samples and per-benchmark cost rows are written as Parquet to the `benchmarks` blob container in a
hive-partitioned layout, so downstream analysis can read full distributions rather than point averages.

#### Stopping rule

High-frequency single-machine queries (point-in-polygon lookup, kNN search, bbox filtering) use a **sequential
stopping rule** so the iteration count is bound to measured variance rather than fixed up front. After every timed
iteration the decorator computes a non-parametric bootstrapped 95% confidence interval on the mean elapsed time
(`Config.BENCHMARK_BOOTSTRAP_RESAMPLES=1000` resamples drawn with replacement from the elapsed-time samples
collected so far). The loop stops as soon as all of these hold:

- at least `Config.BENCHMARK_MIN_ITERATIONS=10` iterations have completed (so the CI estimate is itself stable),
- the timed window is at least `Config.BENCHMARK_MIN_TIMED_WINDOW_SECONDS=60` seconds (so the Azure Monitor
  one-minute metric buckets that feed the cost model contain a usable data point), and
- the bootstrapped CI half-width is within `Config.BENCHMARK_TARGET_CI_HALF_WIDTH_RELATIVE=0.05` of the sample mean
  (5% relative precision).

The per-query value in `BenchmarkIteration` (for example `POINT_IN_POLYGON_LOOKUP=2500`, `KNN_SEARCH=4000`) acts as
an **upper bound** on iterations. If iterations hit the ceiling but the 60-second window floor has not yet been met,
the loop continues past the ceiling and logs a one-time warning, so the cost-metric window stays valid. A separate
hard cap `Config.BENCHMARK_MAX_TIMED_WINDOW_SECONDS=21600` (6 hours) protects against runaway runs and trips
`stop_reason="timeout"` if it fires. The bootstrap RNG is seeded deterministically from `(run_id, query_id)`
(`blake2b` digest in `_make_bootstrap_rng`), so identical reruns reproduce the same stopping point.

National-scale spatial joins (`national_scale_spatial_join_databricks_*`, `national_scale_spatial_join_duckdb`,
`national_scale_spatial_join_postgis`) opt out via `use_sequential_stopping=False` on `@monitor` and run a small
fixed count (`NATIONAL_SCALE_SPATIAL_JOIN=3`). These queries are long-running and low-variance: a bootstrapped CI on
fewer than `MIN_ITERATIONS` samples would be uninformative, and the cost of additional iterations is significant on
Databricks (cluster runtime × workers) and on the shared Postgres instance. The per-iteration timeout
(`BENCHMARK_MAX_TIMED_WINDOW_SECONDS`) still applies — any single iteration (including warmup) exceeding 90 minutes
triggers `stop_reason="timeout"`. These same entrypoints
override `warmup_iterations=1` on `@monitor`: one warmup is enough to prime the OS page cache, JDBC/PostGIS
connection state, and Spark Catalyst plans on a warm Databricks cluster, while additional warmups would dominate
the wall-clock budget (`Config.BENCHMARK_WARMUP_ITERATIONS=5` is the decorator default and applies to the
high-frequency single-machine queries).

Transient per-iteration failures (Spark `ExecutorLost`, blob-storage hiccups, JVM startup races) no longer abort the
whole run. When an iteration raises, the decorator records a `status="failed"` sample at the per-iteration level,
increments a counter, and continues with the next iteration. Only `Config.BENCHMARK_MAX_CONSECUTIVE_FAILURES=3`
failures in a row abort the loop with `stop_reason="failed"` (interpreting a streak as "the cluster is genuinely
broken now," not "one bad scheduling decision"). A run that completed via the normal stopping conditions but had at
least one iteration fail along the way records `stop_reason="partial"` so analysis can tell mixed-result runs apart
from clean ones.

The achieved iteration count (successful only), failed iteration count, mean, median, bootstrapped CI half-width
(both absolute seconds and as a fraction of the mean), and `stop_reason` (`precision`, `timeout`, `ceiling`, `fixed`,
`partial`, or `failed`) are persisted alongside the existing identifiers in `benchmark_metadata.parquet`, so
downstream analysis can filter or report on each benchmark's stopping condition. Mean, median, and the CI half-width
are always computed over the successful samples only — failed iterations contribute to `failed_iterations` but never
to the elapsed-time distribution.

### Engines under test

| Engine                  | Layer                            | Storage                                                                                |
|-------------------------|----------------------------------|----------------------------------------------------------------------------------------|
| DuckDB                  | Single-node, in-container        | GeoParquet over Azure Blob Storage (`read_parquet('az://...')`)                        |
| PostGIS                 | Single-node, managed service     | Azure Database for PostgreSQL Flexible Server                                          |
| GeoPandas + Shapefile   | Single-node, local-disk baseline | Shapefile pre-downloaded to the container before the timed scope                       |
| Apache Sedona           | Distributed                      | Azure Databricks, 2 / 4 / 8 / 12 / 16 `Standard_D4s_v3` workers, reading GeoParquet via ABFS |

DuckDB and PostGIS each run inside an Azure Container Instance with 4 vCPU and 16 GB RAM, so CPU and memory baselines
match between the single-node engines.

### Databricks cluster lifecycle

The Databricks national-scale spatial join uses a deliberately warm cluster, mirroring the warmup discipline applied to
the single-node engines:

1. `DatabricksService.create_cluster` provisions one cluster, installs the Sedona Maven coordinate and the
   `apache-sedona` and `geopandas` PyPI packages via the libraries API, and waits for `RUNNING`. This happens before
   `@monitor`'s timing window opens.
2. The `@monitor` warmup and timed iterations all submit notebook runs against the same `existing_cluster_id`.
   Subsequent iterations see warm executors, primed Catalyst plans, and cached broadcast variables.
3. `DatabricksService.terminate_cluster` runs in a `finally` block after the timed iterations complete, so the cluster
   is torn down even if the benchmark raises.

Cluster provisioning and termination are deliberately outside the cost window. The thesis question is the cost of
running queries on an optimally warm engine, not the cost of cold-starting one per query. Provisioning is a one-time
setup cost in any production deployment, amortized over many queries rather than billed per query.

Two notebook variants live under `src/presentation/databricks/`:
`national_scale_spatial_join_broadcast.py` (wraps `broadcast()` around the small side) and
`national_scale_spatial_join_partitioned.py` (sets the Sedona KDB-tree partitioner).
Each registers a `SparkListener` that aggregates per-stage metrics — executor input bytes,
shuffle read and write bytes, stage durations, executor run time — and returns them alongside the query result via
`dbutils.notebook.exit`. These phase metrics are persisted on the per-iteration sample so the distributed runtime can
be decomposed into read, shuffle, and driver collection time.

### Pairing and randomization

`main.py` shuffles the experiment list with `random.Random(benchmark_run)` before launching containers. Experiments
that should share a wall-clock window declare each other under `related_script_ids` in `benchmarks.yml` and are
launched concurrently via a `ThreadPoolExecutor`. Running paired benchmarks in the same window controls for
short-term cloud variability between the engines being compared.

Concretely, the outer orchestrator loop is serial: it picks the next experiment that has not yet completed, fans out
its peer batch in parallel, waits for the whole batch to finish, marks every member completed, and moves on. At any
moment one batch is in flight; within that batch every member runs on its own ACI in parallel.

The 51 experiments are packed into 17 batches under four constraints that the `related_script_ids` graph encodes:

1. **Same query type** per batch — `point-in-polygon-lookup`, `knn-search`, `bbox-filtering`, or
   `national-scale-spatial-join` never mix.
2. **Same dataset size** per batch — `small`, `medium`, and `large` never overlap, so storage cache state and
   regional VM pressure are comparable across batch members.
3. **At most one PostGIS experiment** per batch — Azure Database for PostgreSQL is a single shared instance and two
   concurrent PostGIS queries would contend on shared buffers, OS page cache, and CPU.
4. **At most 200 Databricks cluster vCPU** per batch — `Standard_D4s_v3` is 4 vCPU per node, each Sedona cluster
   uses `(workers + 1) × 4` vCPU (driver + workers), and the Databricks workspace's regional quota for that VM
   family is 200. DuckDB, Shapefile, and PostGIS draw from a separate ACI quota and do not count.

DuckDB and Shapefile experiments are process-local inside their own ACI, so multiple of either may run concurrently
without disturbing each other. Each Sedona variant provisions its own Databricks cluster on disjoint VMs, so two
Sedona experiments in the same batch do not share any runtime state beyond the regional vCPU pool already capped
by constraint 4.

### Test matrix

The matrix below is the active set of 51 experiments grouped into 17 parallel batches. Each cell lists the engines
or Sedona configurations that launch together in the same wall-clock window; size suffixes (`-small`, `-medium`,
`-large`) are appended to the experiment ids in `benchmarks.yml` and forwarded to each container as `--dataset-size`.
Shapefile (`local`) only participates at the `small` tier per the thesis methodology — it represents the
laptop-workflow reference, not a scalable engine.

**RQ1 — Single-machine query benchmarks** (15 experiments, 6 batches)

| Query type                | `small` (3-way)          | `large` (2-way)  |
|---------------------------|--------------------------|------------------|
| `point-in-polygon-lookup` | duckdb · postgis · local | duckdb · postgis |
| `knn-search`              | duckdb · postgis · local | duckdb · postgis |
| `bbox-filtering`          | duckdb · postgis · local | duckdb · postgis |

The medium tier was dropped from the surviving RQ1 queries and `attribute-spatial-compound-filter` was removed
across the board (issue #281); the 13 freed cells are reinvested in RQ2.

**RQ2 — National-scale spatial join** (36 experiments, 11 batches)

| Engine / strategy   | `small`                      | `medium`                     | `large`                      |
|---------------------|------------------------------|------------------------------|------------------------------|
| Single-node         | duckdb · postgis             | duckdb · postgis             | duckdb · postgis             |
| Sedona `broadcast`  | 2 / 4 / 8 / 12 / 16 nodes   | 2 / 4 / 8 / 12 / 16 nodes   | 2 / 4 / 8 / 12 / 16 nodes   |
| Sedona `partitioned`| 2 / 4 / 8 / 12 / 16 nodes   | 2 / 4 / 8 / 12 / 16 nodes   | 2 / 4 / 8 / 12 / 16 nodes   |

Within each size column, single-node and Sedona experiments are packed into the same batches up to the 200 vCPU
Databricks budget — the table groups by strategy for readability, not by batch membership. Concrete batch
membership is whatever `related_script_ids` in `benchmarks.yml` declares; see the batch listing below.

A `default` strategy (no hint; Spark's CBO picks the plan) was originally planned as an untuned baseline but was
dropped entirely because iterations consistently timed out or failed at this workload scale, making reliable
measurement infeasible (issue #254).

**Batch listing.** Seventeen batches in total. The Databricks vCPU column sums `(workers + 1) × 4` over Sedona members
of the batch; single-node and DuckDB/Shapefile ACIs draw from a separate quota. Sequential execution order follows
the seeded shuffle.

| Batch | Type                        | Size   | Databricks vCPU | Members |
|-------|-----------------------------|--------|-----------------|---------|
| P1    | point-in-polygon-lookup     | small  | 0               | duckdb · postgis · local |
| P2    | point-in-polygon-lookup     | large  | 0               | duckdb · postgis |
| K1    | knn-search                  | small  | 0               | duckdb · postgis · local |
| K2    | knn-search                  | large  | 0               | duckdb · postgis |
| B1    | bbox-filtering              | small  | 0               | duckdb · postgis · local |
| B2    | bbox-filtering              | large  | 0               | duckdb · postgis |
| A_S1  | national-scale-spatial-join | small  | 200             | broadcast-2 · broadcast-8 · broadcast-12 · partitioned-2 · partitioned-8 · partitioned-12 · duckdb · postgis |
| A_S2  | national-scale-spatial-join | small  | 176             | broadcast-4 · broadcast-16 · partitioned-4 · partitioned-16 |
| A_M1  | national-scale-spatial-join | medium | 176             | broadcast-8 · broadcast-12 · partitioned-8 · partitioned-12 · duckdb · postgis |
| A_M2  | national-scale-spatial-join | medium | 176             | broadcast-4 · broadcast-16 · partitioned-4 · partitioned-16 |
| A_M3  | national-scale-spatial-join | medium | 24              | broadcast-2 · partitioned-2 |
| A_L1  | national-scale-spatial-join | large  | 80              | broadcast-16 · broadcast-2 |
| A_L2  | national-scale-spatial-join | large  | 80              | partitioned-16 · partitioned-2 |
| A_L3  | national-scale-spatial-join | large  | 72              | broadcast-12 · broadcast-4 |
| A_L4  | national-scale-spatial-join | large  | 72              | partitioned-12 · partitioned-4 |
| A_L5  | national-scale-spatial-join | large  | 72              | broadcast-8 · partitioned-8 |
| A_L6  | national-scale-spatial-join | large  | 0               | duckdb · postgis |

## Dataset layout

Benchmark datasets are stored in the `data` blob container partitioned by release, size, theme, and region:

```
az://data/release/{release}/size={small|medium|large}/theme=buildings/region={region}/part_XXXXX.parquet
```

The `size=` segment is required for all conflated and synthesized building data. Raw OSM/FKB partitions (under
the `raw` container) do not carry the `size=` segment.

Files are written as GeoParquet 1.1.0 with:

- `geometry_encoding="WKB"`
- `schema_version="1.1.0"`
- `write_covering_bbox=True` (adds a `bbox` struct column with `xmin`, `ymin`, `xmax`, `ymax`)
- `row_group_size=100_000`
- Rows sorted by `partition_key` (geohash precision 3 over the LAEA Europe centroid)

### Sizes and synthesis

| Size     | Target row count | Source                                                                                                  |
|----------|------------------|---------------------------------------------------------------------------------------------------------|
| `small`  | ~5M              | Conflation of OSM + FKB. Written directly by `TestDatasetService` during setup.                         |
| `medium` | ~40M             | `DatasetSynthesisService`: 9 clones per source polygon (translate + rotate + jitter, drop invalid).     |
| `large`  | ~100M            | `DatasetSynthesisService`: 23 clones per source polygon.                                                |

Per-polygon clone counts are exposed on the enum (`DatasetSize.MEDIUM.clones_per_polygon == 9`). Synthetic clones
carry the same schema as originals, with non-geometry attributes (e.g. `building_type`, `building_id`, `source`)
left `NULL`. The `partition_key` is recomputed for clones from the new centroid.

Attribute filters (e.g. `WHERE source = 'osm'` in the compound-filter benchmark) match only the ~5M original rows
on `size=medium` / `size=large`. This is acceptable for scaling benchmarks.

### Postgres tables

`setup_benchmarking_framework` seeds three Postgres tables, one per size:

- `buildings_small` (~5M rows)
- `buildings_medium` (~40M rows)
- `buildings_large` (~100M rows)

Each has a matching GIST spatial index named `buildings_{size}_geometry_idx`. The seed streams rows from blob
storage via DuckDB `fetch_df_chunk` to avoid materializing the full dataset in memory.

## Setup

### Azure Resources

This project utilizes several Azure resources. Some are created and deleted during runtime, whilst others have to be
created manually. This section will give a brief walkthrough on the resources that have to be configured and how to do
so.

> [!NOTE]
> Set up all resources in **Norway East** *except Azure Databricks*. Norway East often lacks
> sufficient `Standard_D4s_v3` quota for the multi-node clusters, so the Databricks workspace
> must live in **Sweden Central** (see [Databricks](#databricks)). Cross-region egress between
> blob storage (Norway East) and Databricks compute (Sweden Central) adds minor latency but
> does not affect benchmark validity.

#### Resource naming

The resource names used throughout this section (`doppa`, `doppabs`, `doppaacr`, `doppa-uami`,
`doppa-db`, `doppa-databricks`) are baked into source and configuration. Keep them
as-is for the simplest setup; this is also what the thesis deployment uses, so reproducing the
published results requires these exact names.

If you need to rename a resource, the following references must be updated together:

| Location                            | What is hardcoded                                                              |
|-------------------------------------|--------------------------------------------------------------------------------|
| `src/config.py`                     | Default values for resource group, blob URL/account, STAC container            |
| `benchmarks.yml`                    | ACR image references (`doppaacr.azurecr.io/<image>:latest`) for every benchmark |

`src/config.py` defaults can also be overridden via the corresponding environment variables
(see [Local development](#local-development) and [GitHub Actions](#github-actions)) without
editing the file. `benchmarks.yml` and the workflow file require direct edits.

#### Resource group

Start by creating a resource group named `doppa`. Ensure that you can configure Kubernetes and Databricks with your
current subscription and roles.

#### Blob storage

Blob storage is an essential part of this benchmarking framework. Everything from benchmarking results to the actual
datasets are stored here. Create a storage account named `doppabs`. Under *Data protection* disable everything.
All other settings can be left as default.

> [!IMPORTANT]
> Disabling all data protection options (soft delete for blobs and containers) is required. If these features are
> enabled the Databricks ABFS driver will fail with a 409 error when reading data via the `dfs.core.windows.net`
> endpoint.

There is no need to create the containers
as these are created during runtime. Each container is created with the `Container` access level. If you wish to make
this stricter make the following changes in the `ensure_container` function in [
`BlobStorageService`](./src/infra/infrastructure/services/blob_storage_service.py).

```python
# Public container access
self.__blob_storage_context.create_container(container_name.value, public_access=PublicAccess.CONTAINER)  
```

```python
# Private container access
self.__blob_storage_context.create_container(container_name.value, public_access=PublicAccess.BLOB)
```

#### User-Assigned Managed Identity (UAMI)

To provide the correct access to Azure resources when running the script from GitHub Actions a UAMI has to be
configured. The Actions will sign in to Azure and execute the scripts using the UAMI. Create a UAMI named
`doppa-uami` and navigate to the *Federated credentials* setting. Create two federated credentials with the
following setup:

<div style="display:flex; justify-content:center; align-items:flex-start; gap:20px;">
  <img src=".github/docs/img/github-ci-fc-main.png" width="45%" />
  <img src=".github/docs/img/github-ci-fc-pr.png" width="45%" />
</div>

Change the fields according to your setup.

The next step is to give the UAMI a `Contributor` in the resource group. Navigate to the *Azure role assignments*
setting and press *Add role assignment*. Select the scope `Resource group` and then the resource group `doppa`. Pick the
role `Contributor` and press *Save*.

To view the `AZURE_UAMI_RESOURCE_ID` (needed for later) run the following command:

```powershell
az identity show -g doppa -n doppa-uami --query id -o tsv
```

#### Container registry

Create a container registry named `doppaacr`. The Docker images will be saved here. To ensure that the Actions are able
to pull the images give the UAMI created in the last step a `AcrPull` and `AcrPush` role. In the `doppaacr` resource
navigate to

*Access control (IAM)* and press *Add* > *Add role assignment*. Select the role `AcrPull` and continue. On the next
screen select *Managed identity* under *Assign access to*, and select the `doppa-uami` UAMI under *Members*.
Navigate to the last step and press *Create*.

Repeat the same steps for the `AcrPush` role.

#### PostgreSQL database

Create
an [Azure database for PostgreSQL](https://portal.azure.com/#view/Microsoft_Azure_Marketplace/GalleryItemDetailsBladeNopdl/id/Microsoft.PostgreSQLServer/selectionMode~/false/resourceGroupId//resourceGroupLocation//dontDiscardJourney~/false/selectedMenuId/home/launchingContext~/%7B%22galleryItemId%22%3A%22Microsoft.PostgreSQLServer%22%2C%22source%22%3A%5B%22GalleryFeaturedMenuItemPart%22%2C%22VirtualizedTileDetails%22%5D%2C%22menuItemId%22%3A%22home%22%2C%22subMenuItemId%22%3A%22Search%20results%22%2C%22telemetryId%22%3A%22a28a8a60-8a59-43fd-8def-fc6cba1ca11f%22%7D/searchTelemetryId/0a3db32e-00e8-4ba8-b921-45bc0a7a5a28)
with the following configuration:

Under *Basics*:

- Server name: `doppa-db`
- Region: `Norway East`
- Workload type: `Production`
- Compute + Storage: Disable `Geo-Redundancy`
    - Cluster: Set *Cluster options* to `Server`
    - Compute: Set *Compute tier* to `Burstable` and set *Compute size* to `Standard_B2ms`
    - Storage: Set *Storage type* to `Premium SSD`, *Storage size* to `128 GiB` and *Performance tier* to `P10`
    - Business critical: Set *Zonal resiliency* to `Disabled`
- Authentication method: `PostgreSQL authentication only`

Under *Networking*:

- Firewall rules: Check the box *Allow public access from any Azure service within Azure to this server*.
- Add current IP address to Firewall rules

Navigate to *Review and create* and create the resource.

After the database has been deployed navigate to the setting *Server parameters* and search for `azure.extensions`. In
the drop-down menu select `POSTGIS`. This enables the script to install PostGIS automatically during run-time. Under the
same setting change the following:

- `shared_buffers`: `2097152`
- `effective_cache_size`: `6291456`
- `work_mem`: `65536`

#### Databricks

The national-scale spatial join benchmarks run on Azure Databricks using Apache Sedona. A separate Databricks
workspace is required.

> [!NOTE]
> Norway East often has insufficient `Standard_D4s_v3` quota for multi-node clusters. Create the workspace in
> **Sweden Central** instead. Cross-region data access (blob storage in Norway East, compute in Sweden Central)
> adds minor latency but does not affect benchmark validity.

##### 1. Request vCPU quota

The benchmarks run clusters with 2, 4, 8, 12, and 16 worker nodes. Each `Standard_D4s_v3` node uses 4 vCPUs, so the
16-node cluster requires 64 vCPUs (plus the driver, 4 vCPU). The default quota in most regions is 10 vCPUs.

To request a quota increase:

1. Navigate to the [Azure Portal](https://portal.azure.com) → **Subscriptions** → your subscription →
   **Settings** → **Usage + quotas**
2. Filter by region (e.g. Sweden Central) and search for `Standard DSv3 Family vCPUs`
3. Click the pencil icon and request at least **200 vCPUs** to accommodate concurrent multi-node clusters within a batch
4. Provide a justification (e.g. "Running distributed Spark benchmarks") and submit

Quota increases for small VM families are typically approved automatically within minutes.

##### 2. Create the workspace

1. In the Azure Portal create a new **Azure Databricks** resource
2. Under *Basics*:
   - Resource group: `doppa`
   - Workspace name: `doppa-databricks`
   - Region: **Sweden Central** (or another region with sufficient quota)
   - Pricing tier: `Premium`
3. Leave all other settings as default and press *Review + create*

##### 3. Generate an access token

1. Open the Databricks workspace
2. Navigate to your user icon (top right) → **Settings** → **Developer** → **Access tokens**
3. Click *Generate new token*, give it a name and a suitable expiry, and copy the token value

##### 4. Environment variables

Add the following to your `.env` file:

```dotenv
DATABRICKS_HOST=https://<workspace-id>.azuredatabricks.net
DATABRICKS_TOKEN=<personal-access-token>
AZURE_BLOB_STORAGE_ACCOUNT_KEY=<storage-account-access-key>
```

- `DATABRICKS_HOST`: the full URL of your workspace (visible in the browser address bar after opening the workspace)
- `DATABRICKS_TOKEN`: the token generated in the previous step
- `AZURE_BLOB_STORAGE_ACCOUNT_KEY`: found in Azure Portal → Storage account `doppabs` → **Security + networking** → **Access keys** → copy either `key1` or `key2`

The notebook script is automatically uploaded to the Databricks workspace at run time. No manual upload is required.

##### 5. Publish municipality boundaries

The RQ2 national-scale spatial join benchmarks require a ~360-feature Norwegian municipality polygon
set (`municipalities.parquet`) in the `metadata` blob storage container. This file is produced by the
`04-kommuner-contribution` notebook in the [doppa-data-contribution](https://github.com/kartAI/doppa-data-contribution)
repository, which writes it to the `contributions` blob storage container.

**One-time prerequisite:** run the `04-kommuner-contribution` notebook once against the target storage
account. After it succeeds, Step 6 of `setup_benchmarking_framework` (`setup-framework` benchmark)
copies `municipalities.parquet` from `contributions` to `metadata` automatically — no manual upload
required. If the source blob is missing, the setup step fails fast with an actionable error pointing
back at the notebook.

### Local development

> [!NOTE]
> This does not run fully locally, so ensure that all the Azure resources have been configured

Clone the repository from [GitHub](https://github.com/kartAI/doppa-data) and navigate to the project root.

```powershell
git clone https://github.com/kartAI/doppa-data.git
cd doppa-data
```

Create a virtual environment and install the dependencies in the [requirements](./requirements.txt)-file.

```bash
python -m venv venv                          # Create virtual environment
source venv/bin/activate                     # Activate venv (Linux/macOS)
# .\venv\Scripts\Activate.ps1                # Activate venv (Windows PowerShell)
pip install -r requirements.txt              # Install dependencies
```

Add the following `.env` file to the project root directory. Swap out the values enclosed by `<>` with the actual
secrets. The containers `dev-benchmarks` and `dev-metadata` ensure that results from the test runs do not disrupt
results from actual runs.

```dotenv
AZURE_SUBSCRIPTION_ID=<azure-subscription-id>
AZURE_UAMI_RESOURCE_ID=<azure-user-assigned-managed-identity-resource-id>

AZURE_BLOB_STORAGE_CONNECTION_STRING=<azure-blob-storage-connection-string>
AZURE_BLOB_STORAGE_ACCOUNT_KEY=<azure-blob-storage-account-key>
AZURE_BLOB_STORAGE_BENCHMARK_CONTAINER=dev-benchmarks
AZURE_BLOB_STORAGE_METADATA_CONTAINER=dev-metadata

ACR_LOGIN_SERVER=<azure-container-registry-login-server>

POSTGRES_SERVER_NAME=<postgres-server-name>
POSTGRES_USERNAME=<postgres-username>
POSTGRES_PASSWORD=<postgres-password>

DATABRICKS_HOST=https://<workspace-id>.azuredatabricks.net
DATABRICKS_TOKEN=<personal-access-token>

AZURE_LOG_ANALYTICS_WORKSPACE_ID=<log-analytics-workspace-id>
AZURE_LOG_ANALYTICS_WORKSPACE_KEY=<log-analytics-primary-shared-key>
```

### GitHub Actions

In your repository navigate to *Secrets and variables* under *Settings*. Add the following **secrets**:

- `AZURE_UAMI_RESOURCE_ID`
- `AZURE_BLOB_STORAGE_CONNECTION_STRING`
- `AZURE_BLOB_STORAGE_ACCOUNT_KEY`
- `POSTGRES_USERNAME`
- `POSTGRES_PASSWORD`
- `DATABRICKS_HOST`
- `DATABRICKS_TOKEN`
- `AZURE_LOG_ANALYTICS_WORKSPACE_KEY`

and add the following **variables**:

- `ACR_NAME`
- `ACR_LOGIN_SERVER`
- `AZURE_BLOB_STORAGE_BENCHMARK_CONTAINER`
- `AZURE_BLOB_STORAGE_METADATA_CONTAINER`
- `AZURE_CLIENT_ID`
- `AZURE_RESOURCE_GROUP`
- `AZURE_SUBSCRIPTION_ID`
- `AZURE_TENANT_ID`
- `AZURE_LOG_ANALYTICS_WORKSPACE_ID`
- `POSTGRES_SERVER_NAME`

These values can be found under the Azure resources previously created. The workflows should now work!

### Setup runtime and test mode

A full `setup_benchmarking_framework` run on real Azure resources is dominated by Postgres seeding of
`buildings_large` (multi-hour wall on the B2ms tier). Approximate per-step runtimes for the full Norway dataset:

| Step | Description                              | Approximate runtime |
|------|------------------------------------------|---------------------|
| 1    | `test_dataset_service.run_pipeline()`    | 25–55 min           |
| 2    | Synthesize medium (~40M rows)            | 30–50 min           |
| 3    | Synthesize large (~100M rows)            | 60–110 min          |
| 4    | Postgres seed (small + medium + large)   | 3.5–7 hr            |
| 5    | Shapefile copy                           | 3–5 min             |
| 6    | Publish municipalities.parquet           | 5–15 s              |

For faster iteration during development, set `SETUP_COUNTY_LIMIT=N` in `.env`. When set, `TestDatasetService`
and `DatasetSynthesisService` slice their per-county loops to the first `N` Norwegian counties, and the Postgres
seed naturally picks up only those counties' parquet partitions. A run with `SETUP_COUNTY_LIMIT=1` (Oslo only)
completes end-to-end in ~10 minutes.

```dotenv
SETUP_COUNTY_LIMIT=1
```

Leave `SETUP_COUNTY_LIMIT` unset (or remove it) for the full Norway run.

## Running the framework

To run the entire script simply run `python main.py` or `python -m main` and to run a single benchmark run
`python benchmark_runner.py --script-id <script-id> --benchmark-run <int >= 1> --run-id <run-id> --dataset-size <small|medium|large>`.
See the table below for more information about the available flags.

| Flag              | Format / Pattern             | Meaning                                                                                                                                                       |
|-------------------|------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `--script-id`     | `<query-type>-<service>`     | Identifies which query is being executed. `<query-type>` examples: `point-in-polygon-lookup`, `bbox-filtering`, `knn-search`, `national-scale-spatial-join`. `<service>` examples: `duckdb`, `postgis`, `local`.              |
| `--benchmark-run` | `int`                        | Identifier that tells which iteration of the benchmarking is currently running. This is to run the benchmarks on multiple container instances.                |
| `--run-id`        | `<current-date>-<random-id>` | Identifies a benchmark run. Shared across all queries in a single orchestrated run. Date format: `yyyy-mm-dd`; random ID: 6-character uppercase alphanumeric. |
| `--dataset-size`  | `small\|medium\|large`       | Dataset tier the benchmark runs against. Defaults to `small`. Bound to `container.config.dataset_size` and rehydrated as `DatasetSize` via `_get_dataset_size()`. |

## References

Flatgeobuf. (2024). *FlatGeobuf performance benchmarks (geozero-bench)*. Retrieved from
<https://flatgeobuf.org/>

Folkerts, E., Alexandrov, A., Sachs, K., Iosup, A., Markl, V., & Tosun, C. (2013). Benchmarking in the cloud: What it
should, can, and cannot be. In *Selected topics in performance evaluation and benchmarking (TPCTC 2012)* (Vol. 7755,
pp. 173–188). Springer. <https://doi.org/10.1007/978-3-642-36727-4_12>

Holmes, C. (2023, August). *Performance explorations of GeoParquet (and DuckDB)*. Cloud-Native Geospatial Foundation.
<https://cloudnativegeo.org/blog/2023/08/performance-explorations-of-geoparquet-and-duckdb/>

Pandey, V., Kipf, A., Neumann, T., & Kemper, A. (2018). How good are modern spatial analytics systems? *Proceedings of
the VLDB Endowment*, 11(11), 1661–1673. <https://doi.org/10.14778/3236187.3236213>

Ray, S., Simion, B., & Demke Brown, A. (2011). Jackpine: A benchmark to evaluate spatial database performance. *2011
IEEE 27th International Conference on Data Engineering (ICDE)*, 1139–1150.
<https://doi.org/10.1109/ICDE.2011.5767929>

Tang, M., Yu, Y., Malluhi, Q. M., Ouzzani, M., & Aref, W. G. (2020). LocationSpark: In-memory distributed spatial query
processing and optimization. *Frontiers in Big Data*, 3. <https://doi.org/10.3389/fdata.2020.00030>
