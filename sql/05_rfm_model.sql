-- ============================================================
-- 05_rfm_model.sql —— RFM 打分与用户价值分层
--
-- 阈值从哪来的？（不是拍脑袋，全部来自 04_rfm_dist.sql 的实际分布）
--
--   R —— 依据 [2. R 分布]：
--        0 天占 25.66%、1 天占 20.08%、2-3 天占 24.79%、4-5 天占 17.36%、6 天+ 占 12.11%
--        五档人数相对均衡，直接按天切。
--
--   F —— 依据 [3. F 分布]：
--        恰好 1 次的人占 44.59%，接近一半。这个事实本身就是结论，
--        所以「1 次」必须独占一档，不能和 2 次合并。
--
--   M —— 依据 [5. M 十分位边界]：
--        取 20%/40%/60%/80% 分位点 = 105 / 213 / 382 / 714 元，
--        这样每一档恰好 20% 的人，是标准等频分箱。
--
--   高低判定：打分 1~5，>= 3 记为「高」。
--   2 x 2 x 2 = 8 类，命名沿用经典 CRM 分层体系。
-- ============================================================


-- >>> 建视图：RFM 打分 + 八类分层（后续所有查询与 Python 可视化都复用它）
CREATE VIEW IF NOT EXISTS v_rfm_seg AS
WITH scored AS (
    SELECT
        user_id,
        recency_days,
        frequency,
        monetary,
        -- R：越近越好，所以天数越小分越高
        CASE WHEN recency_days <= 0 THEN 5
             WHEN recency_days = 1  THEN 4
             WHEN recency_days <= 3 THEN 3
             WHEN recency_days <= 5 THEN 2
             ELSE 1 END                                        AS r_score,
        -- F：买得越勤越好
        CASE WHEN frequency = 1  THEN 1
             WHEN frequency = 2  THEN 2
             WHEN frequency = 3  THEN 3
             WHEN frequency <= 5 THEN 4
             ELSE 5 END                                        AS f_score,
        -- M：等频五分位，切点来自十分位边界表
        CASE WHEN monetary < 105  THEN 1
             WHEN monetary < 213  THEN 2
             WHEN monetary < 382  THEN 3
             WHEN monetary < 714  THEN 4
             ELSE 5 END                                        AS m_score
    FROM v_rfm_base
)
SELECT
    user_id,
    recency_days  AS r,
    frequency     AS f,
    monetary      AS m,
    r_score, f_score, m_score,
    r_score + f_score + m_score                                AS rfm_total,
    CASE
        WHEN r_score >= 3 AND f_score >= 3 AND m_score >= 3 THEN '1 重要价值客户'
        WHEN r_score >= 3 AND f_score <  3 AND m_score >= 3 THEN '2 重要发展客户'
        WHEN r_score <  3 AND f_score >= 3 AND m_score >= 3 THEN '3 重要保持客户'
        WHEN r_score <  3 AND f_score <  3 AND m_score >= 3 THEN '4 重要挽留客户'
        WHEN r_score >= 3 AND f_score >= 3 AND m_score <  3 THEN '5 一般价值客户'
        WHEN r_score >= 3 AND f_score <  3 AND m_score <  3 THEN '6 一般发展客户'
        WHEN r_score <  3 AND f_score >= 3 AND m_score <  3 THEN '7 一般保持客户'
        ELSE '8 流失客户'
    END                                                        AS 分层
FROM scored;


-- >>> 1. 打分分布是否合理（每档应该都有人，且不能过度集中）
SELECT 'R' AS 维度, r_score AS 分值, COUNT(*) AS 人数,
       ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM v_rfm_seg), 2) AS 占比_pct,
       ROUND(AVG(m), 2) AS 平均GMV
FROM v_rfm_seg GROUP BY r_score
UNION ALL
SELECT 'F', f_score, COUNT(*),
       ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM v_rfm_seg), 2), ROUND(AVG(m), 2)
FROM v_rfm_seg GROUP BY f_score
UNION ALL
SELECT 'M', m_score, COUNT(*),
       ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM v_rfm_seg), 2), ROUND(AVG(m), 2)
FROM v_rfm_seg GROUP BY m_score
ORDER BY 维度, 分值;


-- >>> 2. 八类分层：人数占比 vs GMV 占比（这张表是全部结论的落点）
SELECT
    分层,
    COUNT(*)                                                              AS 人数,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM v_rfm_seg), 2)         AS 人数占比_pct,
    ROUND(SUM(m), 2)                                                      AS 该层GMV,
    ROUND(SUM(m) * 100.0 / (SELECT SUM(m) FROM v_rfm_seg), 2)             AS GMV占比_pct,
    -- 价值密度 = GMV 占比 / 人数占比。>1 说明这群人「以少占多」，值得投入
    ROUND((SUM(m) * 100.0 / (SELECT SUM(m) FROM v_rfm_seg))
          / (COUNT(*) * 100.0 / (SELECT COUNT(*) FROM v_rfm_seg)), 2)     AS 价值密度
FROM v_rfm_seg
GROUP BY 分层
ORDER BY 分层;


-- >>> 3. 八类分层画像（知道每层是什么样的人，才知道该做什么动作）
SELECT
    分层,
    COUNT(*)                        AS 人数,
    ROUND(AVG(r), 2)                AS 平均R_距末次购买天数,
    ROUND(AVG(f), 2)                AS 平均F_购买次数,
    ROUND(AVG(m), 2)                AS 平均M_总金额,
    ROUND(AVG(m) / AVG(f), 2)       AS 平均客单价,
    ROUND(AVG(r_score + f_score + m_score), 2) AS 平均RFM总分
FROM v_rfm_seg
GROUP BY 分层
ORDER BY 分层;


-- >>> 4. 按运营动作合并成 4 个包（分层是分析语言，动作包才是执行语言）
-- 分析出 8 类很好看，但运营团队不可能同时执行 8 套策略。
-- 真正落地时要合并：谁要维护、谁要召回、谁要提频、谁先放着。
SELECT
    CASE
        WHEN 分层 = '1 重要价值客户'                       THEN 'A 高价值维护'
        WHEN 分层 IN ('3 重要保持客户', '4 重要挽留客户')  THEN 'B 高价值召回'
        WHEN 分层 IN ('2 重要发展客户', '5 一般价值客户',
                      '6 一般发展客户')                    THEN 'C 提频与培养'
        ELSE 'D 低优先级观察'
    END                                                            AS 运营动作包,
    COUNT(*)                                                       AS 人数,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM v_rfm_seg), 2)  AS 人数占比_pct,
    ROUND(SUM(m), 2)                                               AS 该包GMV,
    ROUND(SUM(m) * 100.0 / (SELECT SUM(m) FROM v_rfm_seg), 2)      AS GMV占比_pct,
    ROUND(AVG(r), 2)                                               AS 平均R,
    ROUND(AVG(f), 2)                                               AS 平均F,
    ROUND(AVG(m), 2)                                               AS 平均M
FROM v_rfm_seg
GROUP BY 运营动作包
ORDER BY 运营动作包;


-- >>> 5. 帕累托检验：头部用户到底贡献了多少 GMV
-- 这是说服业务方投资源最有力的一个数字。
WITH t AS (
    SELECT
        user_id,
        m,
        ROW_NUMBER() OVER (ORDER BY m DESC)      AS rn,
        SUM(m) OVER (ORDER BY m DESC)             AS cum_gmv
    FROM v_rfm_seg
),
tot AS (SELECT COUNT(*) AS n, SUM(m) AS g FROM v_rfm_seg)
SELECT
    CASE
        WHEN rn <= n * 0.05 THEN '1  TOP 5%'
        WHEN rn <= n * 0.10 THEN '2  TOP 5%-10%'
        WHEN rn <= n * 0.20 THEN '3  TOP 10%-20%'
        WHEN rn <= n * 0.50 THEN '4  TOP 20%-50%'
        ELSE '5  后 50%'
    END                                          AS 用户分组,
    COUNT(*)                                     AS 人数,
    ROUND(SUM(m), 2)                             AS 该组GMV,
    ROUND(MAX(cum_gmv) * 100.0 / (SELECT g FROM tot), 2) AS 累计GMV占比_pct
FROM t, tot
GROUP BY 用户分组
ORDER BY 用户分组;


-- >>> 6. 每层用户偏好哪些品类（为「主推品类」建议提供依据）
WITH uc AS (
    SELECT s.分层, b.category_id, SUM(b.amount) AS gmv
    FROM v_rfm_seg s
    JOIN user_behavior b
      ON b.user_id = s.user_id AND b.behavior_type = 'buy'
    GROUP BY s.分层, b.category_id
),
rk AS (
    SELECT 分层, category_id, gmv,
           ROW_NUMBER() OVER (PARTITION BY 分层 ORDER BY gmv DESC) AS rn
    FROM uc
)
SELECT 分层, category_id AS 品类ID, ROUND(gmv, 2) AS 该层该类GMV, rn AS 排名
FROM rk
WHERE rn <= 3
ORDER BY 分层, rn;


-- >>> 7. 为什么不用等频分箱（NTILE）？—— 并列值会被强行切开
-- NTILE 按行号切分，遇到大量并列值（比如 6181 个人都只买过 1 次）时，
-- 会把完全相同的人塞进不同的分数档，制造出根本不存在的差异。
-- 查「被分到的分数种类数」：只要 >1，就说明同一个人群被人为拆散了。
WITH t AS (
    SELECT user_id, frequency, NTILE(5) OVER (ORDER BY frequency) AS ntile_score
    FROM v_rfm_base
)
SELECT
    frequency                    AS 购买次数,
    COUNT(*)                     AS 人数,
    MIN(ntile_score)             AS 被分到最低分,
    MAX(ntile_score)             AS 被分到最高分,
    COUNT(DISTINCT ntile_score)  AS 被拆成几种分数
FROM t
WHERE frequency <= 6
GROUP BY frequency
ORDER BY frequency;


-- >>> 8. 两种分箱法的结果差异（业务规则 vs 等频 NTILE）
-- 如果两版结论差很多，说明分层结论对阈值敏感，汇报时必须说明。
WITH ntile_ver AS (
    SELECT
        user_id,
        NTILE(5) OVER (ORDER BY recency_days DESC) AS r_s,
        NTILE(5) OVER (ORDER BY frequency)         AS f_s,
        NTILE(5) OVER (ORDER BY monetary)          AS m_s
    FROM v_rfm_base
),
grp AS (
    SELECT
        CASE
            WHEN r_s >= 3 AND f_s >= 3 AND m_s >= 3 THEN '重要价值客户'
            WHEN r_s >= 3 AND f_s <  3 AND m_s >= 3 THEN '重要发展客户'
            WHEN r_s <  3 AND f_s >= 3 AND m_s >= 3 THEN '重要保持客户'
            WHEN r_s <  3 AND f_s <  3 AND m_s >= 3 THEN '重要挽留客户'
            WHEN r_s >= 3 AND f_s >= 3 AND m_s <  3 THEN '一般价值客户'
            WHEN r_s >= 3 AND f_s <  3 AND m_s <  3 THEN '一般发展客户'
            WHEN r_s <  3 AND f_s >= 3 AND m_s <  3 THEN '一般保持客户'
            ELSE '流失客户'
        END AS 分层
    FROM ntile_ver
)
SELECT
    分层,
    COUNT(*)                                                       AS NTILE版人数,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM grp), 2)        AS NTILE版占比_pct,
    (SELECT COUNT(*) FROM v_rfm_seg s WHERE s.分层 LIKE '%' || SUBSTR(grp.分层, 1, 4) || '%')
                                                                   AS 业务规则版人数,
    ROUND((SELECT COUNT(*) FROM v_rfm_seg s WHERE s.分层 LIKE '%' || SUBSTR(grp.分层, 1, 4) || '%')
          * 100.0 / (SELECT COUNT(*) FROM v_rfm_seg), 2)           AS 业务规则版占比_pct
FROM grp
GROUP BY 分层
ORDER BY 分层;
