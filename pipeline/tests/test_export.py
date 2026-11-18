"""Stage 3 tests: stats.json and stats.js, on the made-up history in conftest.py.

Run from the repo root:  python -m pytest pipeline/tests -q
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import export  # noqa: E402
import transform  # noqa: E402


def stats_for(con):
    return export.build_stats(con, transform.run_checks(con))


def test_every_series_lines_up_with_dates_including_gaps(con):
    s = stats_for(con)
    assert s["dates"] == ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]
    assert s["missing_days"] == ["2026-01-03"]
    assert s["capture_days"] == 3
    assert s["views"]["A"] == [100, 150, None, 300]
    assert s["views"]["C"] == [300, None, None, 400]   # absent on the 2nd, no file on the 3rd
    assert s["views"]["D"] == [None, None, None, None]
    assert all(len(v) == len(s["dates"]) for v in s["views"].values())


def test_top_gains_are_real_one_day_gains_biggest_first(con):
    gains = [(g["date"], g["video_id"], g["daily_view_gain"]) for g in stats_for(con)["top_daily_gains"]]
    # A's +150 and C's +100 span missed days, so they must not appear
    assert gains == [("2026-01-02", "A", 50), ("2026-01-02", "B", -10)]


def test_latest_is_each_videos_most_recent_capture(con):
    latest = {r["video_id"]: (r["date"], r["view_count"]) for r in stats_for(con)["latest"]}
    assert latest == {"A": ("2026-01-04", 300), "B": ("2026-01-04", 250), "C": ("2026-01-04", 400)}


def test_check_results_are_carried_into_the_file(con):
    checks = {c["name"]: c for c in stats_for(con)["checks"]}
    assert checks["duplicate_video_date"]["status"] == "pass"
    assert checks["negative_daily_gain"]["status"] == "warn"
    assert checks["negative_daily_gain"]["problems"] == [
        {"date": "2026-01-02", "video_id": "B", "daily_view_gain": -10}]
    assert checks["missing_day"]["problem_count"] == 1
    assert checks["video_missing_from_snapshot"]["problem_count"] == 4


def test_js_file_holds_exactly_the_json_data(con, tmp_path):
    json_path, js_path = export.write_outputs(stats_for(con), tmp_path)
    js = js_path.read_text(encoding="utf-8")
    assert js.startswith("window.STATS = ") and js.endswith(";\n")
    assert json.loads(js[len("window.STATS = "):-2]) == json.loads(json_path.read_text(encoding="utf-8"))


def test_same_data_gives_byte_identical_files(con, tmp_path):
    export.write_outputs(stats_for(con), tmp_path / "a")
    export.write_outputs(stats_for(con), tmp_path / "b")
    for name in ("stats.json", "stats.js"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_failed_check_means_nothing_is_written(con, tmp_path, monkeypatch):
    con.execute("INSERT INTO fact_daily_stats SELECT * FROM fact_daily_stats LIMIT 1")
    monkeypatch.setattr(export, "OUTPUT_DIR", tmp_path / "out")
    monkeypatch.setattr(export.duckdb, "connect", lambda *a, **k: con)
    monkeypatch.setattr(export.transform, "build", lambda c: None)   # keep the planted duplicate
    assert export.main() == 1
    assert not (tmp_path / "out").exists()
