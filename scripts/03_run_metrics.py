# -*- coding: utf-8 -*-
"""
03_run_metrics.py
------------------------------------------------------------
执行 02_core_metrics.sql 里的全部指标查询，打印结果并落盘 CSV

设计说明：
  SQL 文件里每个查询用 "-- >>> 查询名" 标记分隔，
  本脚本按标记切分后逐条执行。
  这样做的好处是：SQL 归 SQL、Python 归 Python，
  业务方想看口径时直接打开 .sql 文件就行，不用在 Python 里翻字符串。
------------------------------------------------------------
"""
import os
import re
import sqlite3
import sys

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

pd.set_option("display.unicode.east_asian_width", True)
pd.set_option("display.max_columns", 50)
pd.set_option("display.width", 200)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "processed", "taobao.db")
SQL_PATH = os.path.join(BASE_DIR, "sql", "02_core_metrics.sql")
OUT_DIR = os.path.join(BASE_DIR, "output", "metrics")
os.makedirs(OUT_DIR, exist_ok=True)

con = sqlite3.connect(DB_PATH)

# ============================================================
# 按 "-- >>> " 标记切分 SQL
# ============================================================
with open(SQL_PATH, encoding="utf-8") as f:
    raw = f.read()

blocks = re.split(r"^-- >>> ", raw, flags=re.M)[1:]
print(f"共解析出 {len(blocks)} 个查询\n")

results = {}
for i, block in enumerate(blocks, start=1):
    lines = block.split("\n")
    name = lines[0].strip()
    sql = "\n".join(lines[1:])

    df = pd.read_sql_query(sql, con)

    # 单/双行宽表 -> 转置打印，否则列挤在一起没法看
    if len(df) <= 2 and len(df.columns) > 6:
        shown = df.T.reset_index()
        shown.columns = ["指标", "值"]
    else:
        shown = df

    print("=" * 70)
    print(f"[{i}] {name}")
    print("=" * 70)
    print(shown.to_string(index=False))
    print()

    results[name] = df
    df.to_csv(os.path.join(OUT_DIR, f"metrics_{i:02d}.csv"),
              index=False, encoding="utf-8-sig")

con.close()
print(f"[OK] 全部结果已保存到：{OUT_DIR}")
