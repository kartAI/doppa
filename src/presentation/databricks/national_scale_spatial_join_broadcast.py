# Databricks notebook source

# COMMAND ----------

# Thesis terminology -> Spark metric mapping
# - "executor read time"     ~ executor_run_time_ms - shuffleReadTime
#                              (the cold scan + per-record work)
# - "shuffle"                = shuffle_read_bytes + shuffle_write_bytes (volume),
#                              shuffle stage duration (time)
# - "driver collection"      = driver_collection_time_ms (residual,
#                              includes planning + final collect)
#
# Join strategy: broadcast. The 357-polygon municipalities side is wrapped in
# `broadcast()` so Sedona picks `BroadcastIndexJoin` instead of the default
# `SortMergeJoin` Spark would pick for ST_Intersects.
#
# Notes:
# - stage_durations_ms is capped at the first 100 stages (dbutils.notebook.exit
#   has a payload cap around 1 MB); a warning is logged if truncation happens.
# - driver_collection_time_ms is computed as
#   wall_clock_ms - sum(stage_durations_ms); clamped to 0 with a warning if
#   negative (autoscaling can make stages overlap and break the simple
#   decomposition).
# - inputMetrics.bytesRead is post-pushdown decompressed bytes inside the
#   executor, not on-the-wire bytes. The on-the-wire counter comes from the
#   ACI-level psutil.net_io_counters in monitor.py.

# COMMAND ----------

import json
import time

from pyspark.sql import functions as F
from pyspark.sql.functions import broadcast
from sedona.spark import SedonaContext

# COMMAND ----------

account_key = dbutils.widgets.get("account_key")
account_name = dbutils.widgets.get("account_name")
release = dbutils.widgets.get("release")
municipalities_file = dbutils.widgets.get("municipalities_file")
dataset_size = dbutils.widgets.get("dataset_size")

# COMMAND ----------

spark.conf.set(
    f"fs.azure.account.key.{account_name}.dfs.core.windows.net",
    account_key,
)

sedona = SedonaContext.create(spark)

# COMMAND ----------

buildings_path = (
    f"abfss://data@{account_name}.dfs.core.windows.net"
    f"/release/{release}/size={dataset_size}/theme=buildings/region=*/*.parquet"
)
municipalities_path = (
    f"abfss://metadata@{account_name}.dfs.core.windows.net"
    f"/{municipalities_file}"
)

buildings_df = sedona.read.format("geoparquet").load(buildings_path)

municipalities_raw = spark.read.parquet(municipalities_path)
municipalities_df = broadcast(
    municipalities_raw.selectExpr(
        "ST_GeomFromWKB(wkb) AS geometry",
        "region AS municipality_name",
    )
)

# Repartition to match cluster parallelism so all nodes receive work.
# defaultParallelism = num_workers x cores_per_node (e.g. 8 nodes x 4 cores = 32).
parallelism = spark.sparkContext.defaultParallelism
print(f"Cluster parallelism: {parallelism}")
print(f"Buildings partitions before repartition: {buildings_df.rdd.getNumPartitions()}")

buildings_df = buildings_df.repartition(parallelism)

# COMMAND ----------

# MAGIC %scala
# MAGIC import org.apache.spark.scheduler.{
# MAGIC   SparkListener,
# MAGIC   SparkListenerStageCompleted
# MAGIC }
# MAGIC import scala.collection.mutable
# MAGIC
# MAGIC // Single-use listener: instantiated immediately before the timed action.
# MAGIC // Aggregates per-stage metrics across every job the action triggers and
# MAGIC // publishes the result as the global temp view `_phase_metrics`, which
# MAGIC // the following PySpark cell reads.
# MAGIC val phaseListener = new SparkListener {
# MAGIC   private val stages =
# MAGIC     mutable.ArrayBuffer.empty[(Int, Long, Long, Long, Long, Long, Long, Long)]
# MAGIC
# MAGIC   override def onStageCompleted(event: SparkListenerStageCompleted): Unit = {
# MAGIC     val info = event.stageInfo
# MAGIC     val metrics = info.taskMetrics
# MAGIC     val submission = info.submissionTime.getOrElse(0L)
# MAGIC     val completion = info.completionTime.getOrElse(0L)
# MAGIC     val stageDuration = if (completion >= submission) completion - submission else 0L
# MAGIC
# MAGIC     stages.synchronized {
# MAGIC       stages += ((
# MAGIC         info.stageId,
# MAGIC         stageDuration,
# MAGIC         metrics.executorRunTime,
# MAGIC         metrics.executorCpuTime / 1000000L, // ns -> ms
# MAGIC         metrics.inputMetrics.bytesRead,
# MAGIC         metrics.shuffleReadMetrics.totalBytesRead,
# MAGIC         metrics.shuffleWriteMetrics.bytesWritten,
# MAGIC         metrics.resultSize
# MAGIC       ))
# MAGIC
# MAGIC       val snapshot = stages.toSeq
# MAGIC       val df = spark
# MAGIC         .createDataFrame(snapshot)
# MAGIC         .toDF(
# MAGIC           "stage_id",
# MAGIC           "stage_duration_ms",
# MAGIC           "executor_run_time_ms",
# MAGIC           "executor_cpu_time_ms",
# MAGIC           "input_bytes_read",
# MAGIC           "shuffle_read_bytes",
# MAGIC           "shuffle_write_bytes",
# MAGIC           "result_size_bytes"
# MAGIC         )
# MAGIC       df.createOrReplaceGlobalTempView("_phase_metrics")
# MAGIC     }
# MAGIC   }
# MAGIC }
# MAGIC
# MAGIC spark.sparkContext.addSparkListener(phaseListener)
# MAGIC println("Phase-metrics SparkListener registered.")

# COMMAND ----------

start_time = time.perf_counter()

result = (
    buildings_df.alias("b")
    .join(
        municipalities_df.alias("m"),
        F.expr("ST_Intersects(m.geometry, b.geometry)"),
    )
    .groupBy(F.col("m.municipality_name"))
    .agg(F.count(F.col("b.geometry")).alias("building_count"))
    .orderBy(F.desc("building_count"))
)

cardinality = result.count()
elapsed_seconds = time.perf_counter() - start_time

print(f"Spatial join complete. Regions with matched buildings: {cardinality}")
print(f"Elapsed seconds: {elapsed_seconds:.3f}")

# COMMAND ----------

_STAGE_DURATION_CAP = 100

phase_df = spark.read.table("global_temp._phase_metrics").orderBy("stage_id")

aggregates = phase_df.agg(
    F.coalesce(F.sum("input_bytes_read"), F.lit(0)).alias("executor_input_bytes_read"),
    F.coalesce(F.sum("executor_run_time_ms"), F.lit(0)).alias("executor_run_time_ms"),
    F.coalesce(F.sum("shuffle_read_bytes"), F.lit(0)).alias("shuffle_read_bytes"),
    F.coalesce(F.sum("shuffle_write_bytes"), F.lit(0)).alias("shuffle_write_bytes"),
    F.coalesce(F.sum("stage_duration_ms"), F.lit(0)).alias("sum_stage_duration_ms"),
).collect()[0]

stage_durations_rows = phase_df.select("stage_duration_ms").collect()
stage_durations_all = [int(row["stage_duration_ms"]) for row in stage_durations_rows]
if len(stage_durations_all) > _STAGE_DURATION_CAP:
    print(
        f"WARNING: {len(stage_durations_all)} stages observed; truncating "
        f"stage_durations_ms to first {_STAGE_DURATION_CAP} to stay under the "
        f"dbutils.notebook.exit payload cap."
    )
    stage_durations = stage_durations_all[:_STAGE_DURATION_CAP]
else:
    stage_durations = stage_durations_all

wall_clock_ms = int(round(elapsed_seconds * 1000.0))
sum_stage_duration_ms = int(aggregates["sum_stage_duration_ms"])
residual_ms = wall_clock_ms - sum_stage_duration_ms
if residual_ms < 0:
    print(
        f"WARNING: stage durations sum ({sum_stage_duration_ms} ms) exceeds "
        f"wall-clock ({wall_clock_ms} ms); clamping driver_collection_time_ms "
        f"to 0. Stages likely overlapped (autoscaling)."
    )
    driver_collection_time_ms = 0
else:
    driver_collection_time_ms = residual_ms

payload = {
    "execution_duration_s": elapsed_seconds,
    "cardinality": int(cardinality),
    "executor_input_bytes_read": int(aggregates["executor_input_bytes_read"]),
    "executor_run_time_ms": int(aggregates["executor_run_time_ms"]),
    "shuffle_read_bytes": int(aggregates["shuffle_read_bytes"]),
    "shuffle_write_bytes": int(aggregates["shuffle_write_bytes"]),
    "driver_collection_time_ms": driver_collection_time_ms,
    "stage_durations_ms": json.dumps(stage_durations),
}

print(f"Phase-metric payload: {payload}")

dbutils.notebook.exit(json.dumps(payload))
