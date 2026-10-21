-- ============================================================
-- 02_core_metrics.sql
-- 核心业务指标
--
-- 核心原则：每个指标都必须先定义「口径」
--   人数口径（user-level）：分母是「多少个人」  -> 回答「拉新/覆盖效果」
--   次数口径（action-level）：分母是「多少次行为」 -> 回答「单次转化效率」
-- 两者差异很大，汇报时必须说清楚用的是哪个
--
-- 每个查询以 "-- >>> 查询名" 开头，由 Python 脚本解析后逐条执行
-- ============================================================


-- >>> 1. 全局总览
SELECT
    COUNT(*)                                                    AS 总行为数,
    COUNT(DISTINCT user_id)                                     AS 总用户数,
    COUNT(DISTINCT item_id)                                     AS 覆盖商品数,
    COUNT(DISTINCT dt)                                          AS 统计天数,
    SUM(CASE WHEN behavior_type = 'pv'   THEN 1 ELSE 0 END)     AS 浏览量_PV,
    SUM(CASE WHEN behavior_type = 'fav'  THEN 1 ELSE 0 END)     AS 收藏数,
    SUM(CASE WHEN behavior_type = 'cart' THEN 1 ELSE 0 END)     AS 加购数,
    SUM(CASE WHEN behavior_type = 'buy'  THEN 1 ELSE 0 END)     AS 下单数,
    ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT user_id), 2)          AS 人均行为数,
    ROUND(SUM(amount), 2)                                       AS GMV
FROM user_behavior;


-- >>> 2. 每日趋势（看活跃度是否有周期性波动）
SELECT
    dt                                                          AS 日期,
    COUNT(DISTINCT user_id)                                     AS 日活_UV,
    SUM(CASE WHEN behavior_type = 'pv'   THEN 1 ELSE 0 END)     AS 浏览量,
    SUM(CASE WHEN behavior_type = 'cart' THEN 1 ELSE 0 END)     AS 加购数,
    SUM(CASE WHEN behavior_type = 'buy'  THEN 1 ELSE 0 END)     AS 订单数,
    COUNT(DISTINCT CASE WHEN behavior_type = 'buy' THEN user_id END) AS 下单人数,
    ROUND(SUM(amount), 2)                                       AS 当日GMV
FROM user_behavior
GROUP BY dt
ORDER BY dt;


-- >>> 3. 用户级转化漏斗（人数口径：同一个人只算一次）
--      回答的问题：每 100 个来逛的人里，最终有多少人掏钱
WITH user_flag AS (
    SELECT
        user_id,
        MAX(CASE WHEN behavior_type = 'pv'   THEN 1 ELSE 0 END) AS has_pv,
        MAX(CASE WHEN behavior_type = 'fav'  THEN 1 ELSE 0 END) AS has_fav,
        MAX(CASE WHEN behavior_type = 'cart' THEN 1 ELSE 0 END) AS has_cart,
        MAX(CASE WHEN behavior_type = 'buy'  THEN 1 ELSE 0 END) AS has_buy
    FROM user_behavior
    GROUP BY user_id
)
SELECT
    SUM(has_pv)                                                             AS 浏览人数,
    SUM(has_fav)                                                            AS 收藏人数,
    SUM(has_cart)                                                           AS 加购人数,
    SUM(has_buy)                                                            AS 下单人数,
    ROUND(SUM(has_fav)  * 100.0 / SUM(has_pv), 2)                           AS 收藏率_pct,
    ROUND(SUM(has_cart) * 100.0 / SUM(has_pv), 2)                           AS 加购率_pct,
    ROUND(SUM(has_buy)  * 100.0 / SUM(has_pv), 2)                           AS 下单转化率_pct,
    ROUND(SUM(has_buy)  * 100.0 / SUM(has_cart), 2)                         AS 加购转下单率_pct
FROM user_flag;


-- >>> 4. 行为级转化（次数口径：每一次行为都算）
--      回答的问题：每 100 次浏览里，能催生出多少笔订单
SELECT
    SUM(CASE WHEN behavior_type = 'pv'   THEN 1 ELSE 0 END)                 AS 浏览次数,
    SUM(CASE WHEN behavior_type = 'cart' THEN 1 ELSE 0 END)                 AS 加购次数,
    SUM(CASE WHEN behavior_type = 'buy'  THEN 1 ELSE 0 END)                 AS 下单次数,
    ROUND(SUM(CASE WHEN behavior_type = 'cart' THEN 1 ELSE 0 END) * 100.0
        / SUM(CASE WHEN behavior_type = 'pv' THEN 1 ELSE 0 END), 2)         AS 加购率_pct,
    ROUND(SUM(CASE WHEN behavior_type = 'buy' THEN 1 ELSE 0 END) * 100.0
        / SUM(CASE WHEN behavior_type = 'pv' THEN 1 ELSE 0 END), 2)         AS 下单转化率_pct
FROM user_behavior;


-- >>> 5. 复购分析（复购率 = 买过 2 次及以上的人 / 所有买过的人）
WITH buy_stat AS (
    SELECT
        user_id,
        COUNT(*)            AS buy_times,
        ROUND(SUM(amount), 2) AS user_gmv
    FROM user_behavior
    WHERE behavior_type = 'buy'
    GROUP BY user_id
)
SELECT
    COUNT(*)                                                                AS 下单总人数,
    SUM(CASE WHEN buy_times = 1 THEN 1 ELSE 0 END)                          AS 只买一次人数,
    SUM(CASE WHEN buy_times >= 2 THEN 1 ELSE 0 END)                         AS 复购人数,
    ROUND(SUM(CASE WHEN buy_times >= 2 THEN 1 ELSE 0 END) * 100.0
        / COUNT(*), 2)                                                      AS 复购率_pct,
    ROUND(AVG(buy_times), 2)                                                AS 人均下单次数,
    ROUND(AVG(user_gmv), 2)                                                 AS 人均GMV,
    ROUND(MAX(user_gmv), 2)                                                 AS 单用户最高GMV
FROM buy_stat;


-- >>> 6. 分时段分析（0-23 点，找流量高峰和转化高峰是否重合）
SELECT
    hour                                                                    AS 小时,
    COUNT(DISTINCT user_id)                                                 AS UV,
    SUM(CASE WHEN behavior_type = 'pv'   THEN 1 ELSE 0 END)                 AS 浏览量,
    SUM(CASE WHEN behavior_type = 'cart' THEN 1 ELSE 0 END)                 AS 加购数,
    SUM(CASE WHEN behavior_type = 'buy'  THEN 1 ELSE 0 END)                 AS 订单数,
    ROUND(SUM(amount), 2)                                                   AS GMV,
    ROUND(SUM(CASE WHEN behavior_type = 'buy' THEN 1 ELSE 0 END) * 100.0
        / NULLIF(SUM(CASE WHEN behavior_type = 'pv' THEN 1 ELSE 0 END), 0), 3) AS 浏览转下单率_pct
FROM user_behavior
GROUP BY hour
ORDER BY hour;


-- >>> 7. 品类 TOP20（按 GMV 排序，找主推品类）
SELECT
    category_id                                                             AS 类目ID,
    COUNT(DISTINCT user_id)                                                 AS 触达人数,
    SUM(CASE WHEN behavior_type = 'pv'   THEN 1 ELSE 0 END)                 AS 浏览量,
    SUM(CASE WHEN behavior_type = 'cart' THEN 1 ELSE 0 END)                 AS 加购数,
    SUM(CASE WHEN behavior_type = 'buy'  THEN 1 ELSE 0 END)                 AS 订单数,
    ROUND(SUM(amount), 2)                                                   AS GMV,
    ROUND(SUM(CASE WHEN behavior_type = 'buy' THEN 1 ELSE 0 END) * 100.0
        / NULLIF(SUM(CASE WHEN behavior_type = 'pv' THEN 1 ELSE 0 END), 0), 2) AS 转化率_pct
FROM user_behavior
GROUP BY category_id
ORDER BY GMV DESC
LIMIT 20;


-- >>> 8. 跳失用户占比（浏览过但从未产生任何收藏/加购/下单）
WITH user_flag AS (
    SELECT
        user_id,
        MAX(CASE WHEN behavior_type = 'pv'   THEN 1 ELSE 0 END) AS has_pv,
        MAX(CASE WHEN behavior_type IN ('fav','cart','buy') THEN 1 ELSE 0 END) AS has_deep
    FROM user_behavior
    GROUP BY user_id
)
SELECT
    SUM(has_pv)                                                             AS 浏览人数,
    SUM(CASE WHEN has_deep = 0 THEN 1 ELSE 0 END)                           AS 纯浏览人数,
    ROUND(SUM(CASE WHEN has_deep = 0 THEN 1 ELSE 0 END) * 100.0
        / SUM(has_pv), 2)                                                   AS 跳失率_pct
FROM user_flag;
