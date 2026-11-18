"""Publish: build the model, run the checks, write the site's data files.

Writes two files to data/output/:
    stats.json  the aggregated data
    stats.js    the same data as `window.STATS = {...};`, which the site loads
                with a <script> tag (browsers block fetch() on pages opened
                straight from disk)

Nothing is written if a 'fail' check fails; the site keeps the last good data.
The output has no timestamp of its own, so it only changes when the data does.

Usage:
    python pipeline/export.py
"""

import json
import re
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import transform  # noqa: E402

OUTPUT_DIR = transform.REPO_ROOT / "data" / "output"
SCHEMA_VERSION = 1
MAX_CHECK_ROWS = 20  # enough to show what's wrong without bloating the file


def load_queries(path: Path | None = None) -> dict[str, str]:
    text = (path or transform.PIPELINE_DIR / "export.sql").read_text(encoding="utf-8")
    queries = {}
    for block in re.split(r"(?m)^-- name:", text)[1:]:
        name, _, rest = block.partition("\n")
        sql = "\n".join(l for l in rest.splitlines() if not l.startswith("--")).strip().rstrip(";")
        queries[name.strip()] = sql
    return queries


def records(con, sql) -> list[dict]:
    rel = con.sql(sql)
    return [dict(zip(rel.columns, row)) for row in rel.fetchall()]


def jsonable(v):
    return v if v is None or isinstance(v, (bool, int, float, str)) else str(v)


def build_stats(con: duckdb.DuckDBPyConnection, checks: list[transform.CheckResult]) -> dict:
    q = load_queries()
    dates = records(con, q["dates"])
    date_list = [d["date"] for d in dates]

    views_by_video: dict[str, list] = {}
    for r in records(con, q["series"]):
        views_by_video.setdefault(r["video_id"], []).append(r["view_count"])

    captured = [d["date"] for d in dates if d["has_snapshot"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "first_date": date_list[0],
        "last_date": date_list[-1],
        "capture_days": len(captured),
        "missing_days": [d["date"] for d in dates if not d["has_snapshot"]],
        "videos": records(con, q["videos"]),
        "dates": date_list,
        # views[video_id][i] is the view count on dates[i] (null = not captured)
        "views": views_by_video,
        "latest": records(con, q["latest"]),
        "top_daily_gains": records(con, q["top_daily_gains"]),
        "checks": [
            {
                "name": c.name,
                "severity": c.severity,
                "status": "pass" if c.passed else c.severity,
                "rule": c.rule,
                "problem_count": len(c.rows),
                "problems": [{k: jsonable(v) for k, v in zip(c.columns, row)}
                             for row in c.rows[:MAX_CHECK_ROWS]],
            }
            for c in checks
        ],
    }


def write_outputs(stats: dict, out_dir: Path | None = None) -> tuple[Path, Path]:
    out_dir = out_dir or OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    body = json.dumps(stats, ensure_ascii=False, separators=(",", ":"))
    json_path, js_path = out_dir / "stats.json", out_dir / "stats.js"
    for path, text in ((json_path, body + "\n"),
                       (js_path, f"window.STATS = {body};\n")):
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    return json_path, js_path


def main() -> int:
    con = duckdb.connect()
    transform.build(con)
    checks = transform.run_checks(con)
    failed = [c.name for c in checks if c.severity == "fail" and not c.passed]
    if failed:
        print(f"Not exporting: failed check(s): {', '.join(failed)}", file=sys.stderr)
        return 1

    stats = build_stats(con, checks)
    json_path, js_path = write_outputs(stats)
    warns = [c["name"] for c in stats["checks"] if c["status"] == "warn"]
    print(f"Wrote {json_path.relative_to(transform.REPO_ROOT)} "
          f"({json_path.stat().st_size / 1024:.1f} KB) and {js_path.name}")
    print(f"{len(stats['videos'])} videos, {stats['capture_days']} capture day(s), "
          f"{stats['first_date']} to {stats['last_date']}; "
          f"warnings: {', '.join(warns) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
