# -*- coding: utf-8 -*-
"""
run_sql_blocks.py —— 通用 SQL 执行器

用法：
    python run_sql_blocks.py sql/03_funnel.sql output/funnel

约定：
    SQL 文件里每个查询以 "-- >>> 查询名" 开头，
    本脚本按标记切分后逐条执行，打印结果并落盘 CSV。

为什么把执行器抽出来？
    分析脚本会越写越多（指标、漏斗、RFM……），
    如果每个都复制一份执行逻辑，改打印格式时要改 N 处。
    SQL 归 SQL、执行归执行，这是工程上的基本分工。
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
pd.set_option("display.width", 220)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "processed", "taobao.db")


# 不返回结果集的语句（建视图/建表/插入），走 con.execute 而不是 read_sql_query
DDL_PREFIX = ("create", "drop", "insert", "update", "delete", "pragma")


def is_ddl(sql: str) -> bool:
    """去掉注释和空行后，看第一个词是不是 DDL/DML 动词。"""
    for line in sql.split("\n"):
        s = line.strip()
        if not s or s.startswith("--"):
            continue
        return s.split()[0].lower().strip("(") in DDL_PREFIX
    return False


def run(sql_path, out_dir):
    with open(sql_path, encoding="utf-8") as f:
        raw = f.read()

    blocks = re.split(r"^-- >>> ", raw, flags=re.M)[1:]
    os.makedirs(out_dir, exist_ok=True)
    con = sqlite3.connect(DB_PATH)

    print(f"SQL 文件：{os.path.basename(sql_path)}")
    print(f"共解析出 {len(blocks)} 个查询\n")

    frames = {}
    for i, block in enumerate(blocks, start=1):
        lines = block.split("\n")
        name = lines[0].strip()
        sql = "\n".join(lines[1:])
        try:
            if is_ddl(sql):
                con.execute(sql)
                con.commit()
                print("=" * 70)
                print(f"[{i}] {name}")
                print("=" * 70)
                print("  (DDL 执行成功，无结果集)\n")
                continue
            df = pd.read_sql_query(sql, con)
        except Exception as e:
            print(f"[ERROR] 第 {i} 个查询执行失败：{name}\n        {e}\n")
            continue

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

        frames[name] = df
        df.to_csv(os.path.join(out_dir, f"q{i:02d}.csv"),
                  index=False, encoding="utf-8-sig")

    con.close()
    print(f"[OK] 结果已保存到：{out_dir}")
    return frames


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法：python run_sql_blocks.py <sql文件路径> <输出目录>")
        sys.exit(1)
    run(os.path.join(BASE_DIR, sys.argv[1]), os.path.join(BASE_DIR, sys.argv[2]))
