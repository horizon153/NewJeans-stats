-- Transform: build the star schema from every raw file.
--
-- The whole model is rebuilt from data/raw/ on each run. Raw files are the
-- source of truth, so rebuilding is always safe and always gives the same result.
--
-- Expects two views created by transform.py:
--   raw_snapshots(snapshot_date DATE, items JSON[])  one row per raw file
--   seed_videos(video_id, song, era)                 pipeline/videos.csv


-- ── Staging: one row per video per snapshot ───────────────────────────────
-- Fields are read out of JSON one by one. If YouTube hides a count (e.g. a
-- video with likes hidden), that field is simply NULL instead of breaking
-- the read.
CREATE OR REPLACE VIEW stg_video_stats AS
SELECT
    r.snapshot_date,
    it ->> 'id'                                           AS video_id,
    it -> 'snippet' ->> 'title'                           AS title,
    TRY_CAST(it -> 'snippet' ->> 'publishedAt' AS TIMESTAMPTZ) AS published_at,
    TRY_CAST(it -> 'statistics' ->> 'viewCount'    AS BIGINT) AS view_count,
    TRY_CAST(it -> 'statistics' ->> 'likeCount'    AS BIGINT) AS like_count,
    TRY_CAST(it -> 'statistics' ->> 'commentCount' AS BIGINT) AS comment_count
FROM raw_snapshots AS r, unnest(r.items) AS u(it);


-- ── dim_video ──────────────────────────────────────────────────────────────
-- Every video in videos.csv, even one YouTube has never returned (title and
-- release_date are then NULL). Title is the most recent one YouTube reported.
-- release_date is the upload day in Korean time, the date NewJeans released it.
CREATE OR REPLACE TABLE dim_video AS
WITH latest AS (
    SELECT video_id, title, published_at
    FROM stg_video_stats
    QUALIFY row_number() OVER (PARTITION BY video_id ORDER BY snapshot_date DESC) = 1
)
SELECT
    s.video_id,
    l.title,
    s.song,
    s.era,
    CAST(timezone('Asia/Seoul', l.published_at) AS DATE) AS release_date
FROM seed_videos AS s
LEFT JOIN latest AS l USING (video_id);


-- ── dim_date ───────────────────────────────────────────────────────────────
-- One row for every calendar day from the first snapshot to the latest,
-- including days with no raw file. has_snapshot = false is the missing-day flag.
CREATE OR REPLACE TABLE dim_date AS
WITH bounds AS (
    SELECT min(snapshot_date) AS first_day, max(snapshot_date) AS last_day
    FROM raw_snapshots
),
days AS (
    SELECT CAST(d AS DATE) AS date
    FROM bounds, generate_series(first_day, last_day, INTERVAL 1 DAY) AS g(d)
)
SELECT
    days.date,
    year(days.date)                       AS year,
    quarter(days.date)                    AS quarter,
    month(days.date)                      AS month,
    monthname(days.date)                  AS month_name,
    day(days.date)                        AS day,
    isodow(days.date)                     AS day_of_week,   -- 1 = Monday
    dayname(days.date)                    AS day_name,
    isodow(days.date) IN (6, 7)           AS is_weekend,
    weekofyear(days.date)                 AS iso_week,
    days.date IN (SELECT snapshot_date FROM raw_snapshots) AS has_snapshot
FROM days;


-- ── fact_daily_stats ───────────────────────────────────────────────────────
-- Grain: one row per video per day it was captured.
--
-- daily_view_gain is views minus that video's previous capture, and only when
-- the previous capture was exactly one day earlier. On the first day, or after
-- a missed day, it is NULL. A gain covering two days would show up as a
-- fake one-day spike. days_since_previous records the gap.
CREATE OR REPLACE TABLE fact_daily_stats AS
WITH ordered AS (
    SELECT
        snapshot_date AS date,
        video_id,
        view_count,
        like_count,
        comment_count,
        lag(snapshot_date) OVER w AS prev_date,
        lag(view_count)    OVER w AS prev_views
    FROM stg_video_stats
    WINDOW w AS (PARTITION BY video_id ORDER BY snapshot_date)
)
SELECT
    date,
    video_id,
    view_count,
    like_count,
    comment_count,
    CASE WHEN date_diff('day', prev_date, date) = 1
         THEN view_count - prev_views END   AS daily_view_gain,
    date_diff('day', prev_date, date)       AS days_since_previous
FROM ordered
ORDER BY date, video_id;
