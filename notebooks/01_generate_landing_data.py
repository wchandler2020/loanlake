# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Land one month of upstream files
# MAGIC Stands in for the vendor. Each run lands the next business month.

# COMMAND ----------

import os
import sys

sys.path.append(os.path.abspath("../src"))

from loanlake import generator
from loanlake.config import Layout, get_param

catalog = get_param(dbutils, "catalog", "loanlake_dev")
layout = Layout(catalog)

# COMMAND ----------

batch = generator.next_batch(layout.landing_raw)
result = generator.generate_batch(layout.landing_raw, batch)
print(result)

# COMMAND ----------

# Checkpoint: one folder per month landed so far
display(dbutils.fs.ls(f"{layout.landing_raw}/payments"))