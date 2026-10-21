# -*- coding: utf-8 -*-
"""
02_load_and_clean.py
------------------------------------------------------------
把原始 CSV 导入 SQLite，执行 SQL 清洗，并产出「清洗审计报告」

为什么要做审计？
  清洗不是「删完剩多少行」就完事。真实项目里你必须能回答：
    - 一共剔除了多少行？
    - 每一行是因为哪条规则被剔除的？
    - 剔除比例是否在合理范围？（如果剔掉 30%，那八成是规则写错了）
  否则业务方一追问「数据准不准」，你就答不上来。
------------------------------------------------------------
"""
import os
import sqlite3
import sys
import time

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_CSV = os.path.join(BASE_DIR, "data", "raw", "user_behavior_raw.csv")
DB_PATH = os.path.join(BASE_DIR, "data", "processed", "taobao.db")
SQL_PATH = os.path.join(BASE_DIR, "sql", "01_create_and_clean.sql")

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# ============================================================
# 1. 读取原始 CSV
# ============================================================
t0 = time.time()
df = pd.read_csv(RAW_CSV)
print(f"[1] 读取原始 CSV：{len(df):,} 行，耗时 {time.time() - t0:.1f}s")

# ============================================================
# 2. 导入 SQLite 的「原始表」（保留全部脏数据，作为清洗的输入）
# ============================================================
con = sqlite3.connect(DB_PATH)
t0 = time.time()
df.to_sql("user_behavior_raw", con, if_exists="replace", index=False, chunksize=50_000)
print(f"[2] 导入 user_behavior_raw，耗时 {time.time() - t0:.1f}s")

# ============================================================
# 3. 清洗审计：逐条规则统计命中数量
# ============================================================
audit_sql = """
SELECT
    COUNT(*)                                                        AS total_raw,
    SUM(CASE WHEN timestamp IS NULL
              OR timestamp <  '2017-11-25 00:00:00'
              OR timestamp >= '2017-12-04 00:00:00'
             THEN 1 ELSE 0 END)                                     AS bad_time,
    SUM(CASE WHEN behavior_type NOT IN ('pv','fav','cart','buy')
             THEN 1 ELSE 0 END)                                     AS bad_behavior,
    SUM(CASE WHEN user_id IS NULL OR item_id IS NULL
             THEN 1 ELSE 0 END)                                     AS bad_id,
    SUM(CASE WHEN behavior_type = 'buy'
              AND (amount IS NULL OR amount <= 0)
             THEN 1 ELSE 0 END)                                     AS bad_amount
FROM user_behavior_raw
"""
a = con.execute(audit_sql).fetchone()
total_raw, bad_time, bad_behavior, bad_id, bad_amount = a

distinct_cnt = con.execute(
    "SELECT COUNT(*) FROM ("
    "  SELECT DISTINCT user_id, item_id, category_id, behavior_type, timestamp, amount"
    "  FROM user_behavior_raw)"
).fetchone()[0]
dup_cnt = total_raw - distinct_cnt

print("\n[3] 清洗审计（基于原始表逐规则统计）")
print(f"    原始行数              : {total_raw:>10,}")
print(f"    完全重复行            : {dup_cnt:>10,}")
print(f"    时间越界              : {bad_time:>10,}")
print(f"    非法行为类型          : {bad_behavior:>10,}")
print(f"    主键缺失(用户/商品)   : {bad_id:>10,}")
print(f"    下单金额异常          : {bad_amount:>10,}")
print("    (注：同一行可能同时命中多条规则，故各项之和 > 实际剔除行数)")

# ============================================================
# 4. 执行清洗 SQL，生成正式表 user_behavior
# ============================================================
with open(SQL_PATH, encoding="utf-8") as f:
    clean_sql = f.read()

t0 = time.time()
con.executescript(clean_sql)
con.commit()
print(f"\n[4] 执行清洗 SQL，耗时 {time.time() - t0:.1f}s")

n_clean = con.execute("SELECT COUNT(*) FROM user_behavior").fetchone()[0]
removed = total_raw - n_clean
print(f"    清洗后行数            : {n_clean:>10,}")
print(f"    实际剔除              : {removed:>10,}  ({removed / total_raw * 100:.2f}%)")

# ============================================================
# 5. 清洗后的行为分布（确认没有把正常数据误杀）
# ============================================================
print("\n[5] 清洗后行为分布")
rows = con.execute(
    "SELECT behavior_type, COUNT(*) AS cnt FROM user_behavior GROUP BY behavior_type ORDER BY cnt DESC"
).fetchall()
for b, c in rows:
    print(f"    {b:5s} {c:>9,}  ({c / n_clean * 100:5.2f}%)")

# ============================================================
# 6. 基础画像：用户数 / 商品数 / 类目数 / 时间跨度
# ============================================================
stat = con.execute(
    "SELECT COUNT(DISTINCT user_id), COUNT(DISTINCT item_id), "
    "COUNT(DISTINCT category_id), MIN(dt), MAX(dt) FROM user_behavior"
).fetchone()
print("\n[6] 数据画像")
print(f"    用户数   : {stat[0]:,}")
print(f"    商品数   : {stat[1]:,}")
print(f"    类目数   : {stat[2]:,}")
print(f"    日期范围 : {stat[3]} ~ {stat[4]}")

# 下单金额总览
amt = con.execute(
    "SELECT COUNT(*), ROUND(SUM(amount),2), ROUND(AVG(amount),2), "
    "ROUND(MIN(amount),2), ROUND(MAX(amount),2) FROM user_behavior WHERE behavior_type='buy'"
).fetchone()
print(f"\n[7] 下单金额")
print(f"    订单数   : {amt[0]:,}")
print(f"    GMV      : {amt[1]:,.2f} 元")
print(f"    客单价   : {amt[2]:,.2f} 元")
print(f"    金额区间 : {amt[3]:,.2f} ~ {amt[4]:,.2f} 元")

con.close()
print(f"\n[8] 数据库文件：{DB_PATH}")
print(f"    大小：{os.path.getsize(DB_PATH) / 1024 / 1024:.1f} MB")
