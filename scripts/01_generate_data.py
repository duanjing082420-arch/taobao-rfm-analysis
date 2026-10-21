# -*- coding: utf-8 -*-
"""
01_generate_data.py
------------------------------------------------------------
生成仿真淘宝用户行为数据集（对齐阿里天池 UserBehavior 真实分布）

为什么不用原始数据？
  天池原数据 1 亿行 / 约 900MB，本机下载受限。
  本项目先用仿真数据把「建表 -> 清洗 -> 指标 -> 漏斗 -> RFM -> 看板」
  整条链路跑通，后续可无缝替换为真实数据（SQL 脚本不用改）。

数据字段（与天池 UserBehavior 一致）：
  user_id        用户 ID
  item_id        商品 ID
  category_id    商品类目 ID
  behavior_type  行为类型：pv 浏览 / fav 收藏 / cart 加购 / buy 下单
  timestamp      行为发生时间
  amount         下单金额（仅 buy 有值；天池原始数据无此字段，为 RFM 的 M 补充）

刻意注入的脏数据（供第 2 步 SQL 清洗使用）：
  1. 完全重复行
  2. 时间超出统计窗口
  3. 空 item_id
  4. 未知行为类型
  5. 金额 <= 0
------------------------------------------------------------
"""
import os
import sys

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ============================================================
# 0. 全局配置
# ============================================================
SEED = 42                      # 固定随机种子 -> 结果可复现（工程习惯）
rng = np.random.default_rng(SEED)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(BASE_DIR, "data", "raw", "user_behavior_raw.csv")

# ---------- 数据规模 ----------
N_TOTAL = 2_000_000            # 总行为数
N_USERS = 20_000               # 用户数
N_ITEMS = 50_000               # 商品数
N_CATS = 500                   # 类目数

# ---------- 时间窗口：2017-11-25 ~ 2017-12-03（共 9 天，与天池一致）----------
N_DAYS = 9
SPAN_DAY = 86_400              # 一天的秒数

# ---------- 行为构成（比例对齐天池真实分布）----------
# 天池 1 亿行真实占比：pv 89.7% / cart 5.5% / fav 2.9% / buy 2.0%
N_BUY = 40_000                 # 2.0%
N_CART = 110_000               # 5.5%
N_FAV = 58_000                 # 2.9%
N_PV = N_TOTAL - N_BUY - N_CART - N_FAV      # 1,792,000 -> 89.6%

# ---------- 转化链路拆解 ----------
# 真实电商里，下单前往往有「加购」或「收藏」动作
CART_TO_BUY = 22_000           # pv -> cart -> buy
FAV_TO_BUY = 8_000             # pv -> fav  -> buy
DIRECT_BUY = N_BUY - CART_TO_BUY - FAV_TO_BUY   # pv -> buy（直接下单）
CART_ONLY = N_CART - CART_TO_BUY                # pv -> cart（加购后放弃）
FAV_ONLY = N_FAV - FAV_TO_BUY                   # pv -> fav（收藏后放弃）

# ---------- 时段权重（0-23 点）----------
# 凌晨低谷、午间小高峰、晚 20-22 点是全天最高峰
HOUR_W = np.array([
    0.9, 0.5, 0.3, 0.2, 0.2, 0.2, 0.3, 0.5, 0.8, 1.0, 1.1, 1.1,
    1.0, 1.0, 1.0, 1.0, 1.1, 1.2, 1.3, 1.5, 1.8, 2.0, 1.9, 1.4,
], dtype=float)
HOUR_W = HOUR_W / HOUR_W.sum()


# ============================================================
# 1. 构造「人群」与「商品」的分布
# ============================================================
def make_pareto_weights(n, alpha):
    """
    帕累托分布（二八定律的数学形态）：
    少数用户贡献大多数行为，少数商品占据大多数曝光。
    真实的电商/互联网数据几乎都是这个形态。
    """
    w = rng.pareto(alpha, size=n) + 1.0
    return w / w.sum()


user_w = make_pareto_weights(N_USERS, 1.5)     # 用户活跃度：头部用户极活跃
item_w = make_pareto_weights(N_ITEMS, 2.0)     # 商品热度：爆款集中
cat_w = make_pareto_weights(N_CATS, 1.2)       # 类目热度不均

# 每个商品固定归属一个类目
item_cat = rng.choice(N_CATS, size=N_ITEMS, p=cat_w)

# 每个类目一个价格系数（有的类目卖得贵，有的便宜）
cat_price_factor = rng.lognormal(0.0, 0.5, size=N_CATS)

# 每个用户一个「消费力系数」——金额必须因人而异，否则 F 和 M 会退化成同一个信息
#
# 为什么还要跟活跃度反向挂钩？因为真实电商有这个结构：
#   买得越勤的人，越是在买日用品 / 消耗品，单次金额反而低；
#   偶尔才下单的人，更可能是买大件、买贵的，单次金额高。
# 如果消费力与活跃度完全独立，那么每个频次档位内的消费力均值都会趋同，
# 各档「平均客单价」又会变成一个常数（大数定律），RFM 分层照样失去意义。
#
# 做法：活跃度排名越高，消费力按 e^(-0.6 * 排名分位) 衰减，
# 再叠加对数正态的个体随机波动（有人天生手松、有人天生比价）。
_act_rank = np.argsort(np.argsort(user_w)).astype(float) / (N_USERS - 1)
user_power = rng.lognormal(0.0, 0.45, size=N_USERS) * np.exp(-0.6 * _act_rank)
user_power = user_power / user_power.mean()      # 校准：整体客单价量级保持不变


# ============================================================
# 2. 时间生成函数
# ============================================================
def gen_seconds(n):
    """按「天 + 小时权重 + 分 + 秒」生成相对起始时刻的秒数"""
    days = rng.integers(0, N_DAYS, size=n)
    hours = rng.choice(24, size=n, p=HOUR_W)
    mins = rng.integers(0, 60, size=n)
    secs = rng.integers(0, 60, size=n)
    return days * SPAN_DAY + hours * 3600 + mins * 60 + secs


TOTAL_SPAN = N_DAYS * SPAN_DAY


def sample_buy_time(base_sec, max_delay_days=2):
    """
    在 base_sec 之后采样「下单时刻」，且保持时段权重（晚上是高峰）。

    为什么不能简单写成 base_sec + 随机秒数？
        第一版我就是这么写的，结果下单时刻被均匀铺到 24 小时，
        冲掉了「晚 20-22 点是下单高峰」的规律，
        最后算出「凌晨转化率 11%、白天 2%」这种反常识的结论。
        这是仿真数据最容易踩的坑：局部逻辑看着对，整体分布却失真。
    """
    n = len(base_sec)
    day_c = base_sec // SPAN_DAY
    remain = (N_DAYS - 1) - day_c              # 后面还剩几天可以排
    delay = rng.integers(0, np.minimum(max_delay_days, remain) + 1, size=n)

    hour_b = rng.choice(24, size=n, p=HOUR_W)  # 下单时段同样遵循作息规律
    sec_b = hour_b * 3600 + rng.integers(0, 3600, size=n)
    buy_sec = (day_c + delay) * SPAN_DAY + sec_b

    # 兜底：极少数情况采样到了 base 之前，强制往后推
    bad = buy_sec <= base_sec
    if bad.any():
        buy_sec[bad] = np.minimum(
            base_sec[bad] + rng.integers(300, 7_200, size=int(bad.sum())),
            TOTAL_SPAN - 1,
        )
    return buy_sec


# ============================================================
# 3. 生成浏览行为（pv）—— 一切行为的起点
# ============================================================
pv_user = rng.choice(N_USERS, size=N_PV, p=user_w)
pv_item = rng.choice(N_ITEMS, size=N_PV, p=item_w)
pv_sec = gen_seconds(N_PV)

# 抽取转化锚点。
# 范围必须留足后续动作的排队空间：太窄会导致最后几天完全没有加购/下单
early_idx = np.where(pv_sec < TOTAL_SPAN * 0.92)[0]
n_anchor = CART_TO_BUY + FAV_TO_BUY + DIRECT_BUY + CART_ONLY + FAV_ONLY
anchors = rng.choice(early_idx, size=n_anchor, replace=False)
anchors = rng.permutation(anchors)

p = 0
a_cart_buy = anchors[p: p + CART_TO_BUY]; p += CART_TO_BUY
a_fav_buy = anchors[p: p + FAV_TO_BUY]; p += FAV_TO_BUY
a_direct = anchors[p: p + DIRECT_BUY]; p += DIRECT_BUY
a_cart_only = anchors[p: p + CART_ONLY]; p += CART_ONLY
a_fav_only = anchors[p: p + FAV_ONLY]; p += FAV_ONLY


def amount_for(items, users):
    """下单金额 = 商品基础价 × 类目价格系数 × 下单用户的消费力系数

    三项缺一不可：
      - 商品基础价：同一件商品每次买价格有波动（促销、规格）
      - 类目价格系数：3C 就是比日用百货贵
      - 用户消费力系数：有人只买 9.9 包邮，有人专挑贵的买
    """
    base = rng.lognormal(4.9, 0.75, size=len(items))
    factor = cat_price_factor[item_cat[items]]
    return np.round(base * factor * user_power[users], 2)


# ============================================================
# 4. 由锚点派生出收藏 / 加购 / 下单行为
# ============================================================
parts = []          # 收集各个行为的 (user, item, behavior, sec, amount)

# --- 4.1 纯浏览 ---
parts.append((
    pv_user, pv_item, np.full(N_PV, "pv", dtype=object),
    pv_sec, np.full(N_PV, np.nan),
))

# --- 4.2 pv -> cart（加购后放弃）---
u, it, t0 = pv_user[a_cart_only], pv_item[a_cart_only], pv_sec[a_cart_only]
t1 = np.minimum(t0 + rng.integers(60, 7_200, size=len(t0)), TOTAL_SPAN - 1)
parts.append((u, it, np.full(len(u), "cart", dtype=object), t1, np.full(len(u), np.nan)))

# --- 4.3 pv -> fav（收藏后放弃）---
u, it, t0 = pv_user[a_fav_only], pv_item[a_fav_only], pv_sec[a_fav_only]
t1 = np.minimum(t0 + rng.integers(60, 3_600, size=len(t0)), TOTAL_SPAN - 1)
parts.append((u, it, np.full(len(u), "fav", dtype=object), t1, np.full(len(u), np.nan)))

# --- 4.4 pv -> buy（直接下单）---
u, it, t0 = pv_user[a_direct], pv_item[a_direct], pv_sec[a_direct]
t1 = sample_buy_time(t0)
parts.append((u, it, np.full(len(u), "buy", dtype=object), t1, amount_for(it, u)))

# --- 4.5 pv -> cart -> buy ---
u, it, t0 = pv_user[a_cart_buy], pv_item[a_cart_buy], pv_sec[a_cart_buy]
t1 = np.minimum(t0 + rng.integers(60, 7_200, size=len(t0)), TOTAL_SPAN - 1)
t2 = sample_buy_time(t1)
parts.append((u, it, np.full(len(u), "cart", dtype=object), t1, np.full(len(u), np.nan)))
parts.append((u, it, np.full(len(u), "buy", dtype=object), t2, amount_for(it, u)))

# --- 4.6 pv -> fav -> buy ---
u, it, t0 = pv_user[a_fav_buy], pv_item[a_fav_buy], pv_sec[a_fav_buy]
t1 = np.minimum(t0 + rng.integers(60, 3_600, size=len(t0)), TOTAL_SPAN - 1)
t2 = sample_buy_time(t1)
parts.append((u, it, np.full(len(u), "fav", dtype=object), t1, np.full(len(u), np.nan)))
parts.append((u, it, np.full(len(u), "buy", dtype=object), t2, amount_for(it, u)))

# ============================================================
# 5. 合并为 DataFrame
# ============================================================
df = pd.DataFrame({
    "user_id": np.concatenate([x[0] for x in parts]),
    "item_id": np.concatenate([x[1] for x in parts]),
    "behavior_type": np.concatenate([x[2] for x in parts]),
    "_sec": np.concatenate([x[3] for x in parts]),
    "amount": np.concatenate([x[4] for x in parts]),
})

df["user_id"] = df["user_id"] + 100_000          # 100000 ~ 119999
df["item_id"] = df["item_id"] + 500_000          # 500000 ~ 549999
df["category_id"] = item_cat[df["item_id"].values - 500_000] + 1

START = pd.Timestamp("2017-11-25 00:00:00")
df["timestamp"] = START + pd.to_timedelta(df["_sec"], unit="s")
df = df.drop(columns=["_sec"])

df = df[["user_id", "item_id", "category_id", "behavior_type", "timestamp", "amount"]]
df = df.sort_values("timestamp", kind="mergesort").reset_index(drop=True)

print(f"[1] 干净数据生成完毕：{len(df):,} 行")
print("    行为分布：")
for b, c in df["behavior_type"].value_counts().items():
    print(f"      {b:5s} {c:>9,}  ({c / len(df) * 100:5.2f}%)")

# 自检：客单价必须因人而异，否则后面的 RFM 分层会失真
_aov = df[df["behavior_type"] == "buy"].groupby("user_id")["amount"].mean()
print(f"\n[自检] 买家客单价分布（若各分位数几乎相同，说明金额没做到因人而异）")
print(f"    P5={_aov.quantile(0.05):7.1f}  P25={_aov.quantile(0.25):7.1f}  "
      f"中位数={_aov.median():7.1f}  P75={_aov.quantile(0.75):7.1f}  P95={_aov.quantile(0.95):7.1f}")
print(f"    最高/最低倍数：{_aov.quantile(0.95) / _aov.quantile(0.05):.1f}x\n")

# ============================================================
# 6. 注入脏数据（让第 2 步的清洗有东西可洗）
# ============================================================
n = len(df)

# 6.1 完全重复行 0.3%
dup_idx = rng.choice(n, size=int(n * 0.003), replace=False)
df = pd.concat([df, df.iloc[dup_idx]], ignore_index=True)

# 6.2 时间越界：改到 2016 年（早于窗口）或 2018 年（晚于窗口）
bad_time_idx = rng.choice(n, size=int(n * 0.001), replace=False)
half = len(bad_time_idx) // 2
df.loc[bad_time_idx[:half], "timestamp"] = pd.Timestamp("2016-05-01 10:00:00")
df.loc[bad_time_idx[half:], "timestamp"] = pd.Timestamp("2018-08-08 10:00:00")

# 6.3 空 item_id
null_idx = rng.choice(n, size=800, replace=False)
df.loc[null_idx, "item_id"] = np.nan

# 6.4 未知行为类型
unk_idx = rng.choice(n, size=500, replace=False)
df.loc[unk_idx, "behavior_type"] = "unknown"

# 6.5 金额 <= 0
buy_pos = df.index[df["behavior_type"] == "buy"].to_numpy()
bad_amt_idx = rng.choice(buy_pos, size=300, replace=False)
df.loc[bad_amt_idx, "amount"] = -1.0

# 打乱顺序，模拟真实日志的混乱程度
df = df.sample(frac=1.0, random_state=SEED).reset_index(drop=True)

print(f"[2] 注入脏数据后：{len(df):,} 行")
print(f"    重复行 {len(dup_idx):,} | 越界时间 {len(bad_time_idx):,} | "
      f"空 item_id {len(null_idx):,} | 未知行为 {len(unk_idx):,} | 金额异常 {len(bad_amt_idx):,}")

# ============================================================
# 7. 落盘
# ============================================================
os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
df.to_csv(OUT_PATH, index=False, encoding="utf-8")

size_mb = os.path.getsize(OUT_PATH) / 1024 / 1024
print(f"[3] 已写入：{OUT_PATH}")
print(f"    文件大小：{size_mb:.1f} MB")
print("\n前 5 行预览：")
print(df.head(5).to_string(index=False))
