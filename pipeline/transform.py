"""Transform: rebuild the star schema from data/raw/ and run the quality checks.

Usage:
    python pipeline/transform.py               # build in memory, print report
    python pipeline/transform.py --db x.duckdb # also keep the database to explore

Exit code 1 if any 'fail' check finds problems; warnings never fail the run.
"""

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_DIR = REPO_ROOT / "pipeline"
RAW_DIR = REPO_ROOT / "data" / "raw"
VIDEOS_CSV = PIPELINE_DIR / "videos.csv"


@dataclass
class CheckResult:
    name: str
    severity: str            # "fail" or "warn"
    rule: str
    columns: list[str]
    rows: list[tuple] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.rows


def _sql_path(p: Path) -> str:
    return str(p).replace("'", "''")


def build(con: duckdb.DuckDBPyConnection, raw_dir: Path | None = None,
          videos_csv: Path | None = None) -> None:
    raw_dir = raw_dir or RAW_DIR
    videos_csv = videos_csv or VIDEOS_CSV
    if not any(raw_dir.glob("*.json")):
        raise FileNotFoundError(f"No raw files in {raw_dir}")

    con.execute("SET TimeZone = 'UTC'")  # same results on any machine
    con.execute(f"""
        CREATE OR REPLACE VIEW raw_snapshots AS
        SELECT CAST(regexp_extract(filename, '(\\d{{4}}-\\d{{2}}-\\d{{2}})\\.json$', 1) AS DATE)
                   AS snapshot_date,
               items
        FROM read_json('{_sql_path(raw_dir)}/*.json',
                       columns = {{'items': 'JSON[]'}}, filename = true)
    """)
    con.execute(f"""
        CREATE OR REPLACE VIEW seed_videos AS
        SELECT * FROM read_csv('{_sql_path(videos_csv)}', header = true,
                               columns = {{'video_id': 'VARCHAR', 'song': 'VARCHAR', 'era': 'VARCHAR'}})
    """)
    con.execute((PIPELINE_DIR / "model.sql").read_text(encoding="utf-8"))


def load_checks(path: Path | None = None) -> list[dict]:
    """Split checks.sql into named queries using their '-- name:' headers."""
    text = (path or PIPELINE_DIR / "checks.sql").read_text(encoding="utf-8")
    checks = []
    for block in re.split(r"(?m)^-- name:", text)[1:]:
        name, _, rest = block.partition("\n")
        severity = re.search(r"(?m)^-- severity:\s*(\w+)", rest).group(1)
        rule = re.search(r"(?m)^-- rule:\s*(.+)$", rest).group(1).strip()
        sql = "\n".join(l for l in rest.splitlines() if not l.startswith("--")).strip().rstrip(";")
        if severity not in ("fail", "warn"):
            raise ValueError(f"check {name.strip()}: severity must be fail or warn")
        checks.append({"name": name.strip(), "severity": severity, "rule": rule, "sql": sql})
    return checks


def run_checks(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    results = []
    for c in load_checks():
        rel = con.sql(c["sql"])
        results.append(CheckResult(c["name"], c["severity"], c["rule"],
                                   rel.columns, rel.fetchall()))
    return results


def print_report(con, results: list[CheckResult]) -> None:
    for table in ("dim_video", "dim_date", "fact_daily_stats"):
        n = con.sql(f"SELECT count(*) FROM {table}").fetchone()[0]
        print(f"{table:<18} {n:>5} rows")
    first, last, days = con.sql(
        "SELECT min(date), max(date), count(*) FILTER (WHERE has_snapshot) FROM dim_date").fetchone()
    print(f"captures: {days} day(s), {first} to {last}\n")

    for r in results:
        status = "PASS" if r.passed else ("FAIL" if r.severity == "fail" else "WARN")
        print(f"[{status}] {r.name}: {r.rule}")
        for row in r.rows[:10]:
            print("        " + ", ".join(f"{c}={v}" for c, v in zip(r.columns, row)))
        if len(r.rows) > 10:
            print(f"        ... and {len(r.rows) - 10} more")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", help="save the database to this file (default: in memory)")
    args = ap.parse_args()

    con = duckdb.connect(args.db or ":memory:")
    build(con)
    results = run_checks(con)
    print_report(con, results)
    failed = [r.name for r in results if r.severity == "fail" and not r.passed]
    if failed:
        print(f"\nStopping: failed check(s): {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
