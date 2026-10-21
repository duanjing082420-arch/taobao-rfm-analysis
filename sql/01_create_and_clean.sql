-- ============================================================
-- 01_create_and_clean.sql
-- 建表 + 数据清洗
--
-- 清洗思路：先「去重」，再「合法性过滤」，最后「派生分析字段」
-- 每一条规则都必须说得出业务理由，不能为了干净而干净
-- ============================================================

-- ---------- 0. 清掉旧对象，保证脚本可重复执行 ----------
DROP TABLE IF EXISTS user_behavior;
DROP INDEX IF EXISTS idx_ub_user;
DROP INDEX IF EXISTS idx_ub_behavior;
DROP INDEX IF EXISTS idx_ub_dt;
DROP INDEX IF EXISTS idx_ub_hour;
DROP INDEX IF EXISTS idx_ub_cat;
DROP INDEX IF EXISTS idx_ub_user_behavior;


-- ---------- 1. 建清洗后的正式表 ----------
-- 子查询里先 DISTINCT 去重，外层再做合法性过滤
CREATE TABLE user_behavior AS
SELECT
    CAST(user_id      AS INTEGER)                   AS user_id,
    CAST(item_id      AS INTEGER)                   AS item_id,
    CAST(category_id  AS INTEGER)                   AS category_id,
    behavior_type,
    timestamp,
    amount,
    -- 派生字段：提前算好，后面所有分析 SQL 都能直接用
    DATE(timestamp)                                 AS dt,        -- 日期 2017-11-25
    CAST(STRFTIME('%H', timestamp) AS INTEGER)      AS hour       -- 小时 0~23
FROM (
    SELECT DISTINCT
        user_id, item_id, category_id, behavior_type, timestamp, amount
    FROM user_behavior_raw
)
WHERE 1 = 1
    -- 规则 1：时间必须落在统计窗口内
    --   业务理由：统计的是 11-25 ~ 12-03 这 9 天，
    --   窗口外的记录属于数据采集错误，留着会污染日活/留存计算
    AND timestamp IS NOT NULL
    AND timestamp >= '2017-11-25 00:00:00'
    AND timestamp <  '2017-12-04 00:00:00'

    -- 规则 2：行为类型必须是四种合法枚举值
    --   业务理由：unknown 这类值无法归类进漏斗，属于埋点上报错误
    AND behavior_type IN ('pv', 'fav', 'cart', 'buy')

    -- 规则 3：用户 ID 和商品 ID 不能为空
    --   业务理由：主键缺失的行无法归因到任何用户或商品，分析无意义
    AND user_id IS NOT NULL
    AND item_id IS NOT NULL

    -- 规则 4：下单行为必须有正的金额
    --   业务理由：amount <= 0 通常是退款单或测试单，
    --   计入 GMV 会虚增收入；非下单行为金额为 NULL 属正常
    AND (behavior_type <> 'buy' OR (amount IS NOT NULL AND amount > 0));


-- ---------- 2. 建索引 ----------
-- 200 万行数据，没有索引的话每个 GROUP BY 都要全表扫描
CREATE INDEX idx_ub_user     ON user_behavior(user_id);
CREATE INDEX idx_ub_behavior ON user_behavior(behavior_type);
CREATE INDEX idx_ub_dt       ON user_behavior(dt);
CREATE INDEX idx_ub_hour     ON user_behavior(hour);
CREATE INDEX idx_ub_cat      ON user_behavior(category_id);
CREATE INDEX idx_ub_user_behavior ON user_behavior(user_id, behavior_type);
