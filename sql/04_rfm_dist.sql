-- ============================================================
-- 04_rfm_dist.sql —— RFM 建模前的分布探查
--
-- 为什么不直接打分？
--   R/F/M 三个指标几乎从不是正态分布，而是长尾的：
--   少数人贡献大部分 GMV，多数人只买过一两次。
--   如果对长尾数据用「平均值一刀切」，阈值会被极端值拉偏。
--   正确顺序：先看分布 → 再依据分布定阈值 → 最后打分分层。
--
-- 口径说明（重要）：
--   R = 数据截止日 - 该用户最后一次下单日期（单位：天，越小越好）
--   F = 该用户在窗口期内的下单次数（不是加购次数，只看真实成交）
--   M = 该用户在窗口期内的下单总金额（GMV 口径，未扣退款）
--   样本范围：只统计「买过的人」。没买过的人不进 RFM，
--             他们属于漏斗环节的问题，不属于价值分层问题。
-- ============================================================


-- >>> 建视图：用户级 RFM 原始值（后续所有查询复用，避免重复写 CTE）
CREATE VIEW IF NOT EXISTS v_rfm_base AS
WITH win AS (
    SELECT MAX(dt) AS max_dt FROM user_behavior
)
SELECT
    b.user_id,
    MAX(b.dt)                                                              AS last_buy_dt,
    CAST(ROUND(julianday((SELECT max_dt FROM win)) - julianday(MAX(b.dt))) AS INTEGER)
                                                                           AS recency_days,
    COUNT(*)                                                               AS frequency,
    ROUND(SUM(b.amount), 2)                                                AS monetary
FROM user_behavior b
WHERE b.behavior_type = 'buy'
GROUP BY b.user_id;


-- >>> 1. 数据窗口与 RFM 基数确认（先看全貌，防止后续口径算错）
SELECT
    (SELECT MIN(dt) FROM user_behavior)                    AS 数据起始日,
    (SELECT MAX(dt) FROM user_behavior)                    AS 数据截止日,
    COUNT(*)                                               AS 有购买用户数,
    SUM(frequency)                                         AS 总订单数,
    ROUND(SUM(monetary), 2)                                AS 总GMV,
    ROUND(AVG(frequency), 2)                               AS 人均订单数,
    ROUND(AVG(monetary), 2)                                AS 人均GMV,
    MIN(recency_days)                                      AS R_最小,
    MAX(recency_days)                                      AS R_最大,
    MIN(frequency)                                         AS F_最小,
    MAX(frequency)                                         AS F_最大,
    ROUND(MIN(monetary), 2)                                AS M_最小,
    ROUND(MAX(monetary), 2)                                AS M_最大
FROM v_rfm_base;


-- >>> 2. R 分布：距最后一次购买多少天
-- 看这张表是为了给 R 定阈值。注意窗口只有 9 天，
-- R 的取值范围天然被压缩在 0~8，区分度有限（后面会讨论这个局限）。
SELECT
    recency_days                                                    AS R_天数,
    COUNT(*)                                                        AS 人数,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM v_rfm_base), 2)  AS 人数占比_pct,
    ROUND(SUM(monetary), 2)                                         AS 该档GMV,
    ROUND(AVG(frequency), 2)                                        AS 平均购买次数,
    ROUND(AVG(monetary), 2)                                         AS 人均GMV
FROM v_rfm_base
GROUP BY recency_days
ORDER BY recency_days;


-- >>> 3. F 分布：窗口期内买过几次
-- 分档展示，避免输出几十行。档位前缀数字仅用于排序。
SELECT
    CASE
        WHEN frequency = 1  THEN '1  恰好1次'
        WHEN frequency = 2  THEN '2  2次'
        WHEN frequency = 3  THEN '3  3次'
        WHEN frequency <= 5 THEN '4  4-5次'
        WHEN frequency <= 8 THEN '5  6-8次'
        WHEN frequency <= 15 THEN '6  9-15次'
        ELSE '7  16次以上'
    END                                                             AS F_档位,
    COUNT(*)                                                        AS 人数,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM v_rfm_base), 2)  AS 人数占比_pct,
    ROUND(SUM(monetary), 2)                                         AS 该档GMV,
    ROUND(SUM(monetary) * 100.0 / (SELECT SUM(monetary) FROM v_rfm_base), 2) AS GMV占比_pct,
    ROUND(AVG(recency_days), 2)                                     AS 平均R_天数,
    ROUND(AVG(monetary), 2)                                         AS 人均GMV
FROM v_rfm_base
GROUP BY F_档位
ORDER BY F_档位;


-- >>> 4. M 分布：窗口期内花了多少钱（分档）
SELECT
    CASE
        WHEN monetary < 100   THEN '1  0-100'
        WHEN monetary < 200   THEN '2  100-200'
        WHEN monetary < 300   THEN '3  200-300'
        WHEN monetary < 500   THEN '4  300-500'
        WHEN monetary < 800   THEN '5  500-800'
        WHEN monetary < 1500  THEN '6  800-1500'
        ELSE '7  1500以上'
    END                                                             AS M_档位,
    COUNT(*)                                                        AS 人数,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM v_rfm_base), 2)  AS 人数占比_pct,
    ROUND(SUM(monetary), 2)                                         AS 该档GMV,
    ROUND(SUM(monetary) * 100.0 / (SELECT SUM(monetary) FROM v_rfm_base), 2) AS GMV占比_pct,
    ROUND(AVG(recency_days), 2)                                     AS 平均R_天数,
    ROUND(AVG(frequency), 2)                                        AS 平均购买次数
FROM v_rfm_base
GROUP BY M_档位
ORDER BY M_档位;


-- >>> 5. M 十分位边界（等频分箱的切分点，用于校准阈值）
-- 如果相邻十分位的边界值几乎一样，说明数据高度集中在低位，
-- 这时用等频分箱会产生大量「同值不同分」的误判。
WITH t AS (
    SELECT
        user_id,
        monetary,
        NTILE(10) OVER (ORDER BY monetary) AS decile
    FROM v_rfm_base
)
SELECT
    decile                    AS 十分位,
    COUNT(*)                  AS 人数,
    ROUND(MIN(monetary), 2)   AS 区间下限,
    ROUND(MAX(monetary), 2)   AS 区间上限,
    ROUND(AVG(monetary), 2)   AS 均值
FROM t
GROUP BY decile
ORDER BY decile;


-- >>> 6. F 与 M 是否高度相关（决定分层能不能简化）
-- 如果买得越勤的人客单价也同步线性上升，F 和 M 就是冗余维度，
-- 分 8 类会人为制造出不存在的群体。看趋势即可判断。
SELECT
    CASE
        WHEN frequency = 1  THEN '1  恰好1次'
        WHEN frequency = 2  THEN '2  2次'
        WHEN frequency = 3  THEN '3  3次'
        WHEN frequency <= 5 THEN '4  4-5次'
        WHEN frequency <= 8 THEN '5  6-8次'
        WHEN frequency <= 15 THEN '6  9-15次'
        ELSE '7  16次以上'
    END                              AS F_档位,
    COUNT(*)                         AS 人数,
    ROUND(AVG(monetary), 2)          AS 平均总GMV,
    ROUND(AVG(monetary) / AVG(frequency), 2) AS 平均客单价
FROM v_rfm_base
GROUP BY F_档位
ORDER BY F_档位;
