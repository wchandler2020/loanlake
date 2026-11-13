# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Set up catalog, schemas and volumes
# MAGIC Idempotent: safe to run on every job run.

# COMMAND ----------

import os
import sys

sys.path.append(os.path.abspath("../src"))  # make src/loanlake importable

from loanlake.config import SCHEMAS, Layout, get_param

catalog = get_param(dbutils, "catalog", "loanlake_dev")
layout = Layout(catalog)

# COMMAND ----------

spark.sql(f"CREATE CATALOG IF NOT EXISTS {catalog}")
for schema in SCHEMAS:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.landing.raw")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.landing.checkpoints")

# COMMAND ----------

# Checkpoint: bronze, silver, gold, landing (+ default, information_schema) and 2 volumes
display(spark.sql(f"SHOW SCHEMAS IN {catalog}"))
display(spark.sql(f"SHOW VOLUMES IN {catalog}.landing"))