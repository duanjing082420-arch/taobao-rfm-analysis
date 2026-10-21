# -*- coding: utf-8 -*-
"""
04_visualize.py —— 可视化与交互看板
- 静态图：matplotlib，输出到 output/figs/（用于报告/文档嵌入）
- 交互看板：plotly，输出单个 HTML 文件（零安装、可放 GitHub、面试官点开即看）
所有数据均直接查询 taobao.db，保证与 SQL 结果完全一致。
"""
import os
import sqlite3
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

DB = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "taobao.db")
FIG_DIR = os.path.join(os.path.dirname(__file__), "..", "output", "figs")
HTML_OUT = os.path.join(os.path.dirname(__file__), "..", "output", "dashboard.html")
os.makedirs(FIG_DIR, exist_ok=True)

# 中文显示
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 110

con = sqlite3.connect(DB)
con.execute("PRAGMA encoding='utf-8'")

# ============================================================
# 取数
# ============================================================
# 全局总览
overview = pd.read_sql_query("""
SELECT
  COUNT(*) total_events,
  COUNT(DISTINCT user_id) users,
  SUM(behavior_type='pv')   pv,
  SUM(behavior_type='fav')  fav,
  SUM(behavior_type='cart') cart,
  SUM(behavior_type='buy')  buy,
  ROUND(SUM(CASE WHEN behavior_type='buy' THEN amount ELSE 0 END),2) gmv
FROM user_behavior
""", con).iloc[0]

# 用户级漏斗（人数口径，去重）
funnel = pd.read_sql_query("""
WITH uf AS (
  SELECT user_id,
    MAX(behavior_type='pv')   has_pv,
    MAX(behavior_type='fav')  has_fav,
    MAX(behavior_type='cart') has_cart,
    MAX(behavior_type='buy')  has_buy
  FROM user_behavior GROUP BY user_id
)
SELECT
  SUM(has_pv) 浏览人数,
  SUM(has_fav OR has_cart) 深度互动人数,
  SUM(has_buy) 下单人数
FROM uf
""", con).iloc[0]

# 用户行为路径分布
paths = pd.read_sql_query("""
WITH uf AS (
  SELECT user_id,
    MAX(behavior_type='fav')  has_fav,
    MAX(behavior_type='cart') has_cart,
    MAX(behavior_type='buy')  has_buy
  FROM user_behavior GROUP BY user_id
)
SELECT
  CASE
    WHEN has_buy=1 THEN '1 有购买'
    WHEN has_fav=1 AND has_cart=1 THEN '2 收藏+加购未买'
    WHEN has_cart=1 THEN '3 仅加购未买'
    WHEN has_fav=1 THEN '4 仅收藏未买'
    ELSE '5 纯浏览' END 路径,
  COUNT(*) 人数
FROM uf GROUP BY 1 ORDER BY 1
""", con)

# 弃购分析（缺口=弃购人数×客单价，为"若这批人完成下单"的估算口径）
abandon = pd.read_sql_query("""
WITH uf AS (
  SELECT user_id,
    MAX(behavior_type='cart') has_cart,
    MAX(behavior_type='buy')  has_buy
  FROM user_behavior GROUP BY user_id
),
agg AS (
  SELECT
    SUM(has_cart) 加购人数,
    SUM(CASE WHEN has_cart=1 AND has_buy=0 THEN 1 ELSE 0 END) 弃购人数
  FROM uf
)
SELECT
  加购人数, 弃购人数,
  ROUND(弃购人数*100.0/加购人数,2) 弃购率_pct,
  (SELECT ROUND(AVG(amount),2) FROM user_behavior WHERE behavior_type='buy') 客单价,
  ROUND(弃购人数*(SELECT AVG(amount) FROM user_behavior WHERE behavior_type='buy'),2) 弃购GMV缺口
FROM agg
""", con).iloc[0]

# 加购到下单转化周期
cycle = pd.read_sql_query("""
WITH cart_t AS (SELECT user_id, item_id, MIN(timestamp) t FROM user_behavior WHERE behavior_type='cart' GROUP BY user_id, item_id),
     buy_t  AS (SELECT user_id, item_id, MIN(timestamp) t FROM user_behavior WHERE behavior_type='buy'  GROUP BY user_id, item_id),
     paired AS (
       SELECT c.user_id, c.item_id, MIN(b.t - c.t) diff
       FROM cart_t c JOIN buy_t b ON c.user_id=b.user_id AND c.item_id=b.item_id AND b.t > c.t
       GROUP BY c.user_id, c.item_id)
SELECT
  CASE WHEN diff IS NULL THEN '未形成闭环'
       WHEN diff <= 86400 THEN '当天'
       WHEN diff <= 172800 THEN '1 天后'
       WHEN diff <= 259200 THEN '2 天后'
       ELSE '3 天及以上' END 转化周期,
  COUNT(*) 人数
FROM (SELECT user_id, MIN(diff) diff FROM paired GROUP BY user_id) GROUP BY 1
ORDER BY CASE 转化周期 WHEN '未形成闭环' THEN 0 WHEN '当天' THEN 1
  WHEN '1 天后' THEN 2 WHEN '2 天后' THEN 3 ELSE 4 END
""", con)

# RFM 八类分层（人数 + GMV）
segs = pd.read_sql_query("""
SELECT "分层", COUNT(*) 人数,
       ROUND(SUM(m),0) GMV
FROM v_rfm_seg GROUP BY "分层"
ORDER BY GMV DESC
""", con)
seg_order = ["重要价值客户","重要发展客户","重要保持客户","重要挽留客户",
             "一般价值客户","一般发展客户","一般保持客户","流失客户"]
segs["分层"] = pd.Categorical(segs["分层"], categories=seg_order, ordered=True)
segs = segs.sort_values("分层")
segs["GMV占比"] = (segs["GMV"] / segs["GMV"].sum() * 100).round(1)

# 运营动作包
packs = pd.read_sql_query("""
SELECT
  CASE
    WHEN "分层" IN ('重要价值客户') THEN 'A 高价值维护'
    WHEN "分层" IN ('重要保持客户','重要挽留客户') THEN 'B 高价值召回'
    WHEN "分层" IN ('重要发展客户','一般价值客户','一般发展客户','一般保持客户') THEN 'C 提频与培养'
    ELSE 'D 低优先级观察' END 动作包,
  COUNT(*) 人数,
  ROUND(SUM(m),0) GMV
FROM v_rfm_seg GROUP BY 1
ORDER BY GMV DESC
""", con)
packs["GMV占比"] = (packs["GMV"]/packs["GMV"].sum()*100).round(1)

# 帕累托
pareto = pd.read_sql_query("""
WITH ranked AS (
  SELECT user_id, m,
    NTILE(100) OVER (ORDER BY m DESC) pct
  FROM v_rfm_seg
)
SELECT
  CASE
    WHEN pct<=5 THEN 'TOP 5%'
    WHEN pct<=10 THEN 'TOP 5%-10%'
    WHEN pct<=20 THEN 'TOP 10%-20%'
    WHEN pct<=50 THEN 'TOP 20%-50%'
    ELSE '后 50%' END 用户分组,
  COUNT(*) 人数,
  ROUND(SUM(m),0) 该组GMV
FROM ranked GROUP BY 1
ORDER BY MIN(pct)
""", con)
pareto["累计GMV占比"] = (pareto["该组GMV"].cumsum()/pareto["该组GMV"].sum()*100).round(1)

# 时段（小时）
hourly = pd.read_sql_query("""
SELECT hour,
  SUM(behavior_type='pv')   pv,
  SUM(behavior_type='buy')  buy,
  ROUND(SUM(CASE WHEN behavior_type='buy' THEN amount ELSE 0 END),0) gmv
FROM user_behavior GROUP BY hour ORDER BY hour
""", con)
hourly["浏览转下单率"] = (hourly["buy"] / hourly["pv"] * 100).round(2)

# 品类 TOP
cat = pd.read_sql_query("""
SELECT category_id 品类, ROUND(SUM(amount),0) GMV, COUNT(*) 订单数
FROM user_behavior WHERE behavior_type='buy'
GROUP BY category_id ORDER BY GMV DESC LIMIT 15
""", con)

# 每日趋势
daily = pd.read_sql_query("""
SELECT dt 日期,
  COUNT(DISTINCT user_id) 日活,
  SUM(behavior_type='buy') 订单数,
  ROUND(SUM(CASE WHEN behavior_type='buy' THEN amount ELSE 0 END),0) GMV
FROM user_behavior GROUP BY dt ORDER BY dt
""", con)

con.close()

# ============================================================
# 1. 静态图（matplotlib）
# ============================================================
C = {"navy":"#1f3b70","blue":"#2e7fd4","teal":"#2bb1a8","orange":"#e8833a",
     "red":"#d1495b","gray":"#9aa3ad","yellow":"#f2c14e"}

def y_fmt(v,_): return f"{v/10000:.0f}万" if v>=10000 else f"{v:.0f}"

# --- 图1 漏斗 ---
fig, ax = plt.subplots(figsize=(8,4.2))
stages = ["浏览","深度互动\n(收藏/加购)","下单"]
vals = [int(funnel["浏览人数"]), int(funnel["深度互动人数"]), int(funnel["下单人数"])]
rates = ["100%",
         f"{vals[1]/vals[0]*100:.1f}%",
         f"{vals[2]/vals[0]*100:.1f}%"]
cols = [C["navy"], C["blue"], C["teal"]]
maxv = vals[0]
for i,(v,r,c) in enumerate(zip(vals,rates,cols)):
    w = v/maxv
    ax.barh(i, w, height=0.62, color=c, edgecolor="white")
    ax.text(w+0.01, i, f"{v:,} 人 ({r})", va="center", fontsize=10, color="#222")
ax.set_yticks(range(3)); ax.set_yticklabels(stages, fontsize=11)
ax.set_xlim(0,1.15); ax.invert_yaxis(); ax.set_xticks([])
for s in ["top","right","bottom"]: ax.spines[s].set_visible(False)
ax.set_title("用户级转化漏斗（人数口径，去重）", fontsize=13, fontweight="bold", color=C["navy"])
ax.annotate(f"深度互动→下单 流失 {vals[1]-vals[2]:,} 人", xy=(0.42,2.32),
            fontsize=9, color=C["red"])
plt.tight_layout(); plt.savefig(f"{FIG_DIR}/01_funnel.png", dpi=110); plt.close()

# --- 图2 RFM八类 人数 + GMV 双轴 ---
fig, ax = plt.subplots(figsize=(9,4.6))
x = np.arange(len(segs))
b1 = ax.bar(x-0.2, segs["人数"], width=0.4, color=C["blue"], label="人数")
ax.set_ylabel("人数", color=C["blue"]); ax.tick_params(axis="y", labelcolor=C["blue"])
ax2 = ax.twinx()
b2 = ax2.bar(x+0.2, segs["GMV"], width=0.4, color=C["orange"], label="GMV")
ax2.set_ylabel("GMV (元)", color=C["orange"]); ax2.tick_params(axis="y", labelcolor=C["orange"])
ax2.yaxis.set_major_formatter(FuncFormatter(y_fmt))
ax.set_xticks(x); ax.set_xticklabels(segs["分层"], rotation=30, ha="right", fontsize=9)
ax.set_title("RFM 八类分层：人数 vs GMV 贡献", fontsize=13, fontweight="bold", color=C["navy"])
for i,v in enumerate(segs["GMV占比"]):
    ax2.text(i+0.2, segs["GMV"].iloc[i], f"{v:.0f}%", ha="center", va="bottom", fontsize=8, color=C["orange"])
plt.tight_layout(); plt.savefig(f"{FIG_DIR}/02_rfm_segment.png", dpi=110); plt.close()

# --- 图3 帕累托 ---
fig, ax = plt.subplots(figsize=(8,4.2))
x = np.arange(len(pareto))
ax.bar(x, pareto["人数"], color=C["gray"], label="人数")
ax.set_ylabel("人数", color=C["gray"])
ax2 = ax.twinx()
ax2.plot(x, pareto["累计GMV占比"], color=C["red"], marker="o", lw=2, label="累计GMV占比")
ax2.set_ylabel("累计 GMV 占比 (%)", color=C["red"]); ax2.set_ylim(0,105)
for i,v in enumerate(pareto["累计GMV占比"]):
    ax2.text(i, v+2, f"{v:.0f}%", ha="center", fontsize=9, color=C["red"])
ax.set_xticks(x); ax.set_xticklabels(pareto["用户分组"], fontsize=9)
ax.set_title("帕累托检验：头部用户贡献的 GMV 占比", fontsize=13, fontweight="bold", color=C["navy"])
plt.tight_layout(); plt.savefig(f"{FIG_DIR}/03_pareto.png", dpi=110); plt.close()

# --- 图4 时段趋势 ---
fig, ax = plt.subplots(figsize=(9,4.2))
ax.bar(hourly["hour"], hourly["gmv"], color=C["teal"], alpha=0.85, label="GMV")
ax.set_ylabel("GMV (元)"); ax.yaxis.set_major_formatter(FuncFormatter(y_fmt))
ax2 = ax.twinx()
ax2.plot(hourly["hour"], hourly["浏览转下单率"], color=C["red"], marker="o", lw=2, label="浏览转下单率")
ax2.set_ylabel("浏览转下单率 (%)", color=C["red"]); ax2.set_ylim(0,4)
ax.set_xticks(range(0,24,2)); ax.set_xlabel("小时")
ax.set_title("分时段：GMV 与 浏览转下单率", fontsize=13, fontweight="bold", color=C["navy"])
plt.tight_layout(); plt.savefig(f"{FIG_DIR}/04_hourly.png", dpi=110); plt.close()

# --- 图5 品类 TOP ---
fig, ax = plt.subplots(figsize=(8,4.4))
top = cat.head(10).iloc[::-1]
ax.barh(top["品类"].astype(str), top["GMV"], color=C["blue"])
ax.xaxis.set_major_formatter(FuncFormatter(y_fmt))
ax.set_title("品类 GMV TOP10", fontsize=13, fontweight="bold", color=C["navy"])
plt.tight_layout(); plt.savefig(f"{FIG_DIR}/05_category.png", dpi=110); plt.close()

print("静态图已生成：", os.listdir(FIG_DIR))

# ============================================================
# 2. 交互看板（plotly 单 HTML）
# ============================================================
palette = ["#1f3b70","#2e7fd4","#2bb1a8","#e8833a","#d1495b","#f2c14e","#7d5ba6","#9aa3ad"]

# KPI cards
kpi_html = f"""
<div class="kpi-row">
  <div class="kpi"><div class="kpi-v">{overview['gmv']/10000:.0f}万</div><div class="kpi-l">总 GMV (元)</div></div>
  <div class="kpi"><div class="kpi-v">{int(overview['users']):,}</div><div class="kpi-l">总用户数</div></div>
  <div class="kpi"><div class="kpi-v">{funnel['下单人数']/funnel['浏览人数']*100:.1f}%</div><div class="kpi-l">用户级转化率</div></div>
  <div class="kpi"><div class="kpi-v">{int(abandon['弃购人数']):,}</div><div class="kpi-l">弃购人数 (缺口 {abandon['弃购GMV缺口']/10000:.0f}万)</div></div>
</div>"""

def div(fig):
    return fig.to_html(full_html=False, include_plotlyjs=False, config={"displayModeBar":False})

# 漏斗
f_funnel = go.Figure(go.Funnel(
    y=["浏览","深度互动(收藏/加购)","下单"],
    x=[int(funnel["浏览人数"]),int(funnel["深度互动人数"]),int(funnel["下单人数"])],
    textinfo="value+percent initial"))
f_funnel.update_layout(title="用户级转化漏斗", height=360, margin=dict(t=50,b=20,l=20,r=20))

# 路径分布
f_path = go.Figure(go.Bar(
    x=paths["人数"], y=paths["路径"], orientation="h",
    marker_color=[C["teal"] if p.startswith("1") else C["gray"] for p in paths["路径"]]))
f_path.update_layout(title="用户行为路径分布（停在哪一步）", height=360,
                     margin=dict(t=50,b=20,l=120,r=20), yaxis=dict(autorange="reversed"))

# RFM 八类
f_seg = make_subplots(specs=[[{"secondary_y":True}]])
f_seg.add_bar(x=segs["分层"].astype(str), y=segs["人数"], name="人数",
              marker_color=C["blue"], secondary_y=False)
f_seg.add_bar(x=segs["分层"].astype(str), y=segs["GMV"], name="GMV",
              marker_color=C["orange"], secondary_y=True)
f_seg.update_layout(title="RFM 八类分层：人数 vs GMV", height=400,
                    barmode="group", margin=dict(t=50,b=80,l=20,r=20))
f_seg.update_yaxes(title_text="人数", secondary_y=False)
f_seg.update_yaxes(title_text="GMV", secondary_y=True)

# 帕累托
f_par = make_subplots(specs=[[{"secondary_y":True}]])
f_par.add_bar(x=pareto["用户分组"], y=pareto["人数"], name="人数",
              marker_color=C["gray"], secondary_y=False)
f_par.add_scatter(x=pareto["用户分组"], y=pareto["累计GMV占比"], name="累计GMV占比",
                  mode="lines+markers", line=dict(color=C["red"],width=3), secondary_y=True)
f_par.update_layout(title="帕累托检验：头部用户贡献的 GMV", height=360,
                    margin=dict(t=50,b=40,l=20,r=20))
f_par.update_yaxes(title_text="人数", secondary_y=False)
f_par.update_yaxes(title_text="累计GMV占比(%)", secondary_y=True, range=[0,105])

# 时段
f_hour = make_subplots(specs=[[{"secondary_y":True}]])
f_hour.add_bar(x=hourly["hour"], y=hourly["gmv"], name="GMV",
               marker_color=C["teal"], secondary_y=False)
f_hour.add_scatter(x=hourly["hour"], y=hourly["浏览转下单率"], name="浏览转下单率",
                   mode="lines+markers", line=dict(color=C["red"],width=2.5), secondary_y=True)
f_hour.update_layout(title="分时段：GMV 与 浏览转下单率", height=380,
                     margin=dict(t=50,b=40,l=20,r=20))
f_hour.update_xaxes(title_text="小时", dtick=2)
f_hour.update_yaxes(title_text="GMV", secondary_y=False)
f_hour.update_yaxes(title_text="浏览转下单率(%)", secondary_y=True, range=[0,4])

# 品类
f_cat = go.Figure(go.Bar(
    x=cat.head(12)["GMV"], y=cat.head(12)["品类"].astype(str), orientation="h",
    marker_color=C["blue"]))
f_cat.update_layout(title="品类 GMV TOP12", height=400, margin=dict(t=50,b=20,l=60,r=20),
                    yaxis=dict(autorange="reversed"))

# 每日趋势
f_day = go.Figure()
f_day.add_trace(go.Scatter(x=daily["日期"], y=daily["GMV"], name="GMV",
              line=dict(color=C["navy"],width=3), mode="lines+markers"))
f_day.add_trace(go.Bar(x=daily["日期"], y=daily["订单数"], name="订单数",
              marker_color=C["yellow"], opacity=0.6, yaxis="y2"))
f_day.update_layout(title="每日趋势", height=340, margin=dict(t=50,b=40,l=20,r=20),
                    yaxis=dict(title="GMV"), yaxis2=dict(title="订单数", overlaying="y", side="right"))
f_day.update_xaxes(categoryorder="category ascending")

# 动作包
f_pack = make_subplots(specs=[[{"secondary_y":True}]])
f_pack.add_bar(x=packs["动作包"], y=packs["人数"], name="人数",
               marker_color=palette[:len(packs)], secondary_y=False)
f_pack.add_bar(x=packs["动作包"], y=packs["GMV"], name="GMV",
               marker_color=palette[::-1][:len(packs)], secondary_y=True)
f_pack.update_layout(title="运营动作包：人数 vs GMV", height=360, barmode="group",
                     margin=dict(t=50,b=40,l=20,r=20))
f_pack.update_yaxes(title_text="人数", secondary_y=False)
f_pack.update_yaxes(title_text="GMV", secondary_y=True)

html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>淘宝用户行为 & RFM 分层分析看板</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  body{{font-family:'Microsoft YaHei','Segoe UI',sans-serif;margin:0;background:#f4f6f9;color:#1f2d3d}}
  .wrap{{max-width:1100px;margin:0 auto;padding:24px}}
  h1{{color:#1f3b70;font-size:24px;margin-bottom:4px}}
  .sub{{color:#6b7785;font-size:13px;margin-bottom:20px}}
  .kpi-row{{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:22px}}
  .kpi{{flex:1;min-width:180px;background:#fff;border-radius:12px;padding:16px 18px;
        box-shadow:0 1px 4px rgba(0,0,0,.08)}}
  .kpi-v{{font-size:26px;font-weight:700;color:#1f3b70}}
  .kpi-l{{font-size:12px;color:#6b7785;margin-top:4px}}
  .card{{background:#fff;border-radius:12px;padding:14px 18px;margin-bottom:18px;
         box-shadow:0 1px 4px rgba(0,0,0,.08)}}
  .sec-title{{font-size:15px;font-weight:700;color:#1f3b70;margin:0 0 10px}}
  .grid2{{display:flex;gap:18px;flex-wrap:wrap}}
  .grid2 .card{{flex:1;min-width:430px}}
  .note{{font-size:12px;color:#6b7785;margin-top:8px;line-height:1.6}}
</style></head><body><div class="wrap">
<h1>淘宝用户行为 & RFM 价值分层分析</h1>
<div class="sub">数据源：仿真电商行为数据集（200万行，对齐天池真实分布）｜ SQLite + SQL + Python ｜ 分析口径说明见各图注</div>
{kpi_html}
<div class="card"><div class="sec-title">一、转化漏斗</div>{div(f_funnel)}</div>
<div class="grid2">
  <div class="card"><div class="sec-title">二、用户行为路径分布</div>{div(f_path)}</div>
  <div class="card"><div class="sec-title">三、加购→下单转化周期</div>
    {div(go.Figure(go.Bar(x=cycle['人数'], y=cycle['转化周期'], orientation='h',
        marker_color=C['orange'], text=cycle['人数'], textposition='auto'))
        .update_layout(height=360, margin=dict(t=20,b=20,l=100,r=20), yaxis=dict(autorange='reversed')))}</div>
</div>
<div class="card"><div class="sec-title">四、RFM 八类分层</div>{div(f_seg)}
  <div class="note">重要价值/发展/保持/挽留 四类合计占买家 {segs[segs['分层'].isin(['重要价值客户','重要发展客户','重要保持客户','重要挽留客户'])]['GMV占比'].sum():.1f}% 的 GMV。</div></div>
<div class="grid2">
  <div class="card"><div class="sec-title">五、帕累托检验</div>{div(f_par)}</div>
  <div class="card"><div class="sec-title">六、运营动作包</div>{div(f_pack)}</div>
</div>
<div class="card"><div class="sec-title">七、分时段趋势</div>{div(f_hour)}</div>
<div class="grid2">
  <div class="card"><div class="sec-title">八、品类 GMV TOP</div>{div(f_cat)}</div>
  <div class="card"><div class="sec-title">九、每日趋势</div>{div(f_day)}</div>
</div>
<div class="note">说明：用户级漏斗为去重口径（一人多行为只算一次）；行为级转化率见分析报告。客单价随购买频次递减（高频买日用品、低频买大件），故 F 与 M 为独立维度。</div>
</div></body></html>"""

with open(HTML_OUT, "w", encoding="utf-8") as f:
    f.write(html)
print("交互看板已生成：", HTML_OUT)
