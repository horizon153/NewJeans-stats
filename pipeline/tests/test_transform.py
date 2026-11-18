"""Stage 2 tests: the model and the checks, on the made-up history in conftest.py.

Run from the repo root:  python -m pytest pipeline/tests -q
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import transform  # noqa: E402


def facts(con, vid):
    return con.execute("""SELECT CAST(date AS VARCHAR), view_count, daily_view_gain, days_since_previous
                          FROM fact_daily_stats WHERE video_id = ? ORDER BY date""", [vid]).fetchall()


def checks(con):
    return {r.name: r for r in transform.run_checks(con)}


def test_gain_only_for_consecutive_days(con):
    assert facts(con, "A") == [
        ("2026-01-01", 100, None, None),   # first day: nothing to compare with
        ("2026-01-02", 150, 50, 1),
        ("2026-01-04", 300, None, 2),      # after a missed day: not a 1-day gain
    ]


def test_video_missing_for_a_day_gets_no_fake_gain(con):
    assert facts(con, "C") == [("2026-01-01", 300, None, None), ("2026-01-04", 400, None, 3)]


def test_hidden_likes_become_null_not_an_error(con):
    likes = con.execute("""SELECT like_count FROM fact_daily_stats
                           WHERE video_id = 'B' AND date = DATE '2026-01-02'""").fetchone()[0]
    assert likes is None


def test_dim_date_covers_every_day_and_flags_the_gap(con):
    rows = con.execute("SELECT CAST(date AS VARCHAR), has_snapshot, day_name FROM dim_date ORDER BY date").fetchall()
    assert rows == [("2026-01-01", True, "Thursday"), ("2026-01-02", True, "Friday"),
                    ("2026-01-03", False, "Saturday"), ("2026-01-04", True, "Sunday")]


def test_dim_video_keeps_unreturned_video_and_uses_korean_release_date(con):
    rows = dict(con.execute("SELECT video_id, release_date FROM dim_video").fetchall())
    assert len(rows) == 4
    assert str(rows["A"]) == "2022-07-22"   # 15:00 UTC on the 21st is the 22nd in Seoul
    assert rows["D"] is None


def test_checks_find_each_planted_problem(con):
    c = checks(con)
    assert c["duplicate_video_date"].passed
    assert c["negative_daily_gain"].rows and c["negative_daily_gain"].rows[0][1:] == ("B", -10)
    assert [str(r[0]) for r in c["missing_day"].rows] == ["2026-01-03"]
    missing = {(str(r[0]), r[1]) for r in c["video_missing_from_snapshot"].rows}
    assert missing == {("2026-01-02", "C"),
                       ("2026-01-01", "D"), ("2026-01-02", "D"), ("2026-01-04", "D")}


def test_duplicate_row_is_a_failure(con):
    con.execute("INSERT INTO fact_daily_stats SELECT * FROM fact_daily_stats WHERE video_id = 'A' LIMIT 1")
    dup = checks(con)["duplicate_video_date"]
    assert not dup.passed and dup.severity == "fail"


def test_only_fail_checks_are_fail_severity():
    sev = {c["name"]: c["severity"] for c in transform.load_checks()}
    assert sev == {"duplicate_video_date": "fail", "negative_daily_gain": "warn",
                   "missing_day": "warn", "video_missing_from_snapshot": "warn"}


def test_rebuild_is_repeatable(con, tmp_path):
    before = con.execute("SELECT * FROM fact_daily_stats ORDER BY ALL").fetchall()
    transform.build(con, tmp_path / "raw", tmp_path / "videos.csv")
    assert con.execute("SELECT * FROM fact_daily_stats ORDER BY ALL").fetchall() == before
