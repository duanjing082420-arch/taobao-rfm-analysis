-- ============================================================
-- 03_funnel.sql
-- 转化漏斗分析：定位流失环节，并把流失量换算成钱
--
-- 关键区分：
--   宽松口径 —— 只要发生过该行为就算（不管先后顺序）
--   严格口径 —— 必须满足时间先后顺序（先浏览、再加购、最后下单）
-- 严格口径一定 <= 宽松口径，差值就是「行为发生过但顺序不成立」的人
--
-- 特别提醒（很多人会画错的坑）：
--   收藏和加购是「并列」的两种意向表达，不是串联的上下游。
--   本数据里收藏 16,099 人 < 加购 18,868 人，
--   说明有相当多的人只加购不收藏。
--   所以正确的漏斗是：浏览 -> 深度互动(收藏或加购) -> 下单，
--   而不是 浏览 -> 收藏 -> 加购 -> 下单。
-- ============================================================


-- >>> 1. 用户级漏斗（宽松口径：同一个人只算一次，不要求时序）
WITH uf AS (
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
    SUM(has_pv)                                                        AS 浏览人数,
    SUM(CASE WHEN has_fav = 1 OR has_cart = 1 THEN 1 ELSE 0 END)       AS 深度互动人数,
    SUM(has_fav)                                                       AS 收藏人数,
    SUM(has_cart)                                                      AS 加购人数,
    SUM(has_buy)                                                       AS 下单人数,
    ROUND(SUM(CASE WHEN has_fav = 1 OR has_cart = 1 THEN 1 ELSE 0 END)
        * 100.0 / SUM(has_pv), 2)                                      AS 浏览到深度互动_pct,
    ROUND(SUM(has_cart) * 100.0 / SUM(has_pv),   2)                    AS 浏览到加购_pct,
    ROUND(SUM(has_buy)  * 100.0 / SUM(has_cart), 2)                    AS 加购到下单_pct,
    ROUND(SUM(has_buy)  * 100.0 / SUM(has_pv),   2)                    AS 全链路转化_pct
FROM uf;


-- >>> 2. 用户级漏斗（严格口径：首次行为必须满足时间先后顺序）
WITH t AS (
    SELECT
        user_id,
        MIN(CASE WHEN behavior_type = 'pv'   THEN timestamp END) AS first_pv,
        MIN(CASE WHEN behavior_type = 'fav'  THEN timestamp END) AS first_fav,
        MIN(CASE WHEN behavior_type = 'cart' THEN timestamp END) AS first_cart,
        MIN(CASE WHEN behavior_type = 'buy'  THEN timestamp END) AS first_buy
    FROM user_behavior
    GROUP BY user_id
)
SELECT
    COUNT(*)                                                                        AS 总浏览人数,
    SUM(CASE WHEN first_fav  IS NOT NULL AND first_fav  > first_pv   THEN 1 ELSE 0 END) AS 浏览后收藏,
    SUM(CASE WHEN first_cart IS NOT NULL AND first_cart > first_pv   THEN 1 ELSE 0 END) AS 浏览后加购,
    SUM(CASE WHEN first_buy  IS NOT NULL AND first_buy  > first_cart THEN 1 ELSE 0 END) AS 加购后下单,
    SUM(CASE WHEN first_buy  IS NOT NULL AND first_buy  > first_pv   THEN 1 ELSE 0 END) AS 浏览后下单
FROM t;


-- >>> 3. 用户行为路径分布（看人都停在哪一步）
WITH uf AS (
    SELECT
        user_id,
        MAX(CASE WHEN behavior_type = 'fav'  THEN 1 ELSE 0 END) AS has_fav,
        MAX(CASE WHEN behavior_type = 'cart' THEN 1 ELSE 0 END) AS has_cart,
        MAX(CASE WHEN behavior_type = 'buy'  THEN 1 ELSE 0 END) AS has_buy
    FROM user_behavior
    GROUP BY user_id
)
SELECT
    CASE
        WHEN has_buy  = 1                      THEN '1 有购买'
        WHEN has_cart = 1 AND has_fav = 1      THEN '2 收藏+加购未买'
        WHEN has_cart = 1                      THEN '3 仅加购未买'
        WHEN has_fav  = 1                      THEN '4 仅收藏未买'
        ELSE                                        '5 纯浏览'
    END                                             AS 路径,
    COUNT(*)                                        AS 人数,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM uf), 2) AS 占比_pct
FROM uf
GROUP BY 路径
ORDER BY 路径;


-- >>> 4. 弃购分析：加购了但没下单（全站意向最高的一群人）
WITH uf AS (
    SELECT
        user_id,
        MAX(CASE WHEN behavior_type = 'cart' THEN 1 ELSE 0 END) AS has_cart,
        MAX(CASE WHEN behavior_type = 'buy'  THEN 1 ELSE 0 END) AS has_buy
    FROM user_behavior
    GROUP BY user_id
),
agg AS (
    SELECT
        SUM(has_cart)                                                   AS 加购人数,
        SUM(CASE WHEN has_cart = 1 AND has_buy = 0 THEN 1 ELSE 0 END)   AS 弃购人数,
        SUM(CASE WHEN has_cart = 1 AND has_buy = 1 THEN 1 ELSE 0 END)   AS 加购且下单人数
    FROM uf
)
SELECT
    加购人数,
    弃购人数,
    加购且下单人数,
    ROUND(弃购人数 * 100.0 / 加购人数, 2)                                AS 弃购率_pct,
    (SELECT ROUND(AVG(amount), 2) FROM user_behavior WHERE behavior_type = 'buy') AS 客单价,
    ROUND(弃购人数 * (SELECT AVG(amount) FROM user_behavior WHERE behavior_type = 'buy'), 2) AS 弃购GMV缺口
FROM agg;


-- >>> 5. 商品级漏斗：高浏览但零转化（详情页或定价可能有问题）
WITH item_stat AS (
    SELECT
        item_id,
        SUM(CASE WHEN behavior_type = 'pv'   THEN 1 ELSE 0 END) AS pv_cnt,
        SUM(CASE WHEN behavior_type = 'cart' THEN 1 ELSE 0 END) AS cart_cnt,
        SUM(CASE WHEN behavior_type = 'buy'  THEN 1 ELSE 0 END) AS buy_cnt,
        COUNT(DISTINCT user_id)                                 AS uv_cnt
    FROM user_behavior
    GROUP BY item_id
)
SELECT
    item_id            AS 商品ID,
    uv_cnt             AS 触达人数,
    pv_cnt             AS 浏览量,
    cart_cnt           AS 加购数,
    buy_cnt            AS 下单数
FROM item_stat
WHERE pv_cnt >= 50 AND buy_cnt = 0
ORDER BY pv_cnt DESC
LIMIT 20;


-- >>> 6. 加购到下单的转化周期（决定「多久后发催付提醒」）
WITH t AS (
    SELECT
        user_id,
        MIN(CASE WHEN behavior_type = 'cart' THEN timestamp END) AS first_cart,
        MIN(CASE WHEN behavior_type = 'buy'  THEN timestamp END) AS first_buy
    FROM user_behavior
    GROUP BY user_id
)
SELECT
    CASE
        WHEN first_cart IS NULL OR first_buy IS NULL          THEN '未形成闭环'
        WHEN CAST((JULIANDAY(first_buy) - JULIANDAY(first_cart)) AS INTEGER) = 0 THEN '当天'
        WHEN CAST((JULIANDAY(first_buy) - JULIANDAY(first_cart)) AS INTEGER) = 1 THEN '1 天后'
        WHEN CAST((JULIANDAY(first_buy) - JULIANDAY(first_cart)) AS INTEGER) = 2 THEN '2 天后'
        ELSE '3 天及以上'
    END                                     AS 转化周期,
    COUNT(*)                                AS 人数,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM t), 2) AS 占比_pct
FROM t
GROUP BY 转化周期
ORDER BY 人数 DESC;


-- >>> 7. 各环节流失人数与流失率汇总
WITH uf AS (
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
    '浏览 -> 收藏'  AS 环节,
    SUM(has_pv)     AS 进入人数,
    SUM(has_fav)    AS 流失后剩余,
    SUM(has_pv) - SUM(has_fav) AS 流失人数,
    ROUND((SUM(has_pv) - SUM(has_fav)) * 100.0 / SUM(has_pv), 2) AS 流失率_pct
FROM uf
UNION ALL
SELECT
    '浏览 -> 深度互动',
    SUM(has_pv),
    SUM(CASE WHEN has_fav = 1 OR has_cart = 1 THEN 1 ELSE 0 END),
    SUM(has_pv) - SUM(CASE WHEN has_fav = 1 OR has_cart = 1 THEN 1 ELSE 0 END),
    ROUND((SUM(has_pv) - SUM(CASE WHEN has_fav = 1 OR has_cart = 1 THEN 1 ELSE 0 END))
        * 100.0 / SUM(has_pv), 2)
FROM uf
UNION ALL
SELECT
    '浏览 -> 加购',
    SUM(has_pv),
    SUM(has_cart),
    SUM(has_pv) - SUM(has_cart),
    ROUND((SUM(has_pv) - SUM(has_cart)) * 100.0 / SUM(has_pv), 2)
FROM uf
UNION ALL
SELECT
    '加购 -> 下单',
    SUM(has_cart),
    SUM(has_buy),
    SUM(has_cart) - SUM(has_buy),
    ROUND((SUM(has_cart) - SUM(has_buy)) * 100.0 / SUM(has_cart), 2)
FROM uf
UNION ALL
SELECT
    '浏览 -> 下单',
    SUM(has_pv),
    SUM(has_buy),
    SUM(has_pv) - SUM(has_buy),
    ROUND((SUM(has_pv) - SUM(has_buy)) * 100.0 / SUM(has_pv), 2)
FROM uf;
