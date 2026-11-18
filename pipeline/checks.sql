-- Data quality checks. Each query returns the rows that break the rule.
-- No rows = check passed.
--
-- severity: fail  -> the run stops (the data can't be trusted)
-- severity: warn  -> the run continues; the problem is reported and recorded

-- name: duplicate_video_date
-- severity: fail
-- rule: at most one row per video per day
SELECT date, video_id, count(*) AS row_count
FROM fact_daily_stats
GROUP BY date, video_id
HAVING count(*) > 1
ORDER BY date, video_id;

-- name: negative_daily_gain
-- severity: warn
-- rule: views shouldn't go down. They can, when YouTube removes fake views, so this only warns.
SELECT date, video_id, daily_view_gain
FROM fact_daily_stats
WHERE daily_view_gain < 0
ORDER BY date, video_id;

-- name: missing_day
-- severity: warn
-- rule: there is a raw file for every day between the first and latest capture
SELECT date
FROM dim_date
WHERE NOT has_snapshot
ORDER BY date;

-- name: video_missing_from_snapshot
-- severity: warn
-- rule: every tracked video appears in every capture (missing = deleted, private, or wrong ID)
SELECT d.date, v.video_id, v.song
FROM dim_date AS d
CROSS JOIN dim_video AS v
LEFT JOIN fact_daily_stats AS f
       ON f.date = d.date AND f.video_id = v.video_id
WHERE d.has_snapshot AND f.video_id IS NULL
ORDER BY d.date, v.song;
