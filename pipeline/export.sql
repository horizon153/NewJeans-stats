-- Publish: the queries behind stats.json. Each one feeds one key of the file.
-- Runs against the tables built by model.sql.

-- name: videos
SELECT video_id, song, era, CAST(release_date AS VARCHAR) AS release_date, title
FROM dim_video
ORDER BY release_date NULLS LAST, song;

-- name: dates
-- every day in range, including missed days, so each series lines up with it
SELECT CAST(date AS VARCHAR) AS date, has_snapshot
FROM dim_date
ORDER BY date;

-- name: series
-- views per video per day; a day with no capture gets NULL
SELECT v.video_id, CAST(d.date AS VARCHAR) AS date, f.view_count
FROM dim_video AS v
CROSS JOIN dim_date AS d
LEFT JOIN fact_daily_stats AS f
       ON f.video_id = v.video_id AND f.date = d.date
ORDER BY v.video_id, d.date;

-- name: latest
-- each video's most recent capture
SELECT f.video_id, CAST(f.date AS VARCHAR) AS date,
       f.view_count, f.like_count, f.comment_count, f.daily_view_gain
FROM fact_daily_stats AS f
QUALIFY row_number() OVER (PARTITION BY f.video_id ORDER BY f.date DESC) = 1
ORDER BY f.view_count DESC;

-- name: top_daily_gains
-- the 10 biggest one-day view gains across all history
SELECT CAST(f.date AS VARCHAR) AS date, f.video_id, v.song, v.era, f.daily_view_gain
FROM fact_daily_stats AS f
JOIN dim_video AS v USING (video_id)
WHERE f.daily_view_gain IS NOT NULL
ORDER BY f.daily_view_gain DESC, f.date, v.song
LIMIT 10;
