-- Starter analytics queries for the screening LLM judge.
-- Run any of these in Snowsight, or ask the Snowflake MCP in Cursor:
--   "Using LLM_JUDGE.SCREENING.V_JUDGE_VS_HUMAN, what's the average rating gap
--    by tenant in the last 14 days?"
-- The MCP's Cortex Analyst / SQL execution tool can answer those directly.

USE SCHEMA LLM_JUDGE.SCREENING;

-- 1. Judge accuracy (rating gap) by tenant, last 14 days.
SELECT
    TENANT,
    COUNT(*)                                            AS RUNS,
    AVG(ABS(RATING_GAP))                                AS MEAN_ABS_GAP,
    AVG(RATING_GAP)                                     AS MEAN_SIGNED_GAP,
    AVG(IFF(ABS(RATING_GAP) <= 1, 1, 0))::FLOAT         AS WITHIN_1_RATE
FROM V_JUDGE_VS_HUMAN
WHERE RUN_AT >= DATEADD(DAY, -14, CURRENT_TIMESTAMP())
  AND HUMAN_RATING IS NOT NULL
  AND LLM_RATING   IS NOT NULL
GROUP BY TENANT
ORDER BY MEAN_ABS_GAP DESC;

-- 2. Effect of context flags (transcript / KB / JD / audio) on issue-category
--    agreement. Useful for deciding which boxes the playground should default on.
SELECT
    INCLUDE_TRANSCRIPT,
    INCLUDE_KB,
    INCLUDE_JD,
    INCLUDE_AUDIO,
    COUNT(*)                                                   AS RUNS,
    AVG(IFF(LLM_PICKED_HUMAN_ISSUE, 1, 0))::FLOAT              AS ISSUE_AGREEMENT_RATE,
    AVG(ABS(RATING_GAP))                                       AS MEAN_ABS_RATING_GAP
FROM V_JUDGE_VS_HUMAN
WHERE HUMAN_RATING IS NOT NULL
  AND LLM_RATING   IS NOT NULL
GROUP BY 1,2,3,4
ORDER BY ISSUE_AGREEMENT_RATE DESC;

-- 3. Prompt-version A/B comparison. PROMPT_VERSION is a short hash of the
--    judge prompt the user ran with; this surfaces which prompt template
--    agrees with humans most often.
SELECT
    PROMPT_VERSION,
    MODEL,
    COUNT(*)                                                    AS RUNS,
    AVG(IFF(LLM_PICKED_HUMAN_ISSUE, 1, 0))::FLOAT               AS ISSUE_AGREEMENT_RATE,
    AVG(ABS(RATING_GAP))                                        AS MEAN_ABS_RATING_GAP,
    SUM(IFF(ERROR IS NOT NULL AND ERROR <> '', 1, 0))           AS ERRORED_RUNS
FROM V_JUDGE_VS_HUMAN
GROUP BY PROMPT_VERSION, MODEL
HAVING RUNS >= 5
ORDER BY ISSUE_AGREEMENT_RATE DESC;

-- 4. Issue-category miss matrix: which human-tagged issues does the judge
--    most often fail to surface? Drives prompt-engineering follow-ups.
WITH exploded AS (
    SELECT
        v.RUN_ID,
        v.PROMPT_VERSION,
        f.value::STRING AS HUMAN_ISSUE,
        v.LLM_ISSUE_CATEGORY,
        v.LLM_PICKED_HUMAN_ISSUE
    FROM V_JUDGE_VS_HUMAN v,
         LATERAL FLATTEN(input => v.HUMAN_ISSUES) f
)
SELECT
    HUMAN_ISSUE,
    COUNT(*)                                       AS HUMAN_FLAGGED,
    SUM(IFF(LLM_PICKED_HUMAN_ISSUE, 1, 0))         AS LLM_AGREED,
    AVG(IFF(LLM_PICKED_HUMAN_ISSUE, 1, 0))::FLOAT  AS RECALL
FROM exploded
GROUP BY HUMAN_ISSUE
ORDER BY HUMAN_FLAGGED DESC;
