"""Extract: fetch today's YouTube statistics for the tracked MVs.

Writes the API response, unmodified, to data/raw/YYYY-MM-DD.json (UTC date).
Raw files are never edited: if today's file already exists, the script exits
without calling the API.

Usage:
    YOUTUBE_API_KEY=... python pipeline/extract.py
"""

import csv
import datetime as dt
import os
import sys
from pathlib import Path

import requests

API_URL = "https://www.googleapis.com/youtube/v3/videos"
REPO_ROOT = Path(__file__).resolve().parent.parent
VIDEOS_CSV = REPO_ROOT / "pipeline" / "videos.csv"
RAW_DIR = REPO_ROOT / "data" / "raw"
MAX_IDS_PER_CALL = 50  # videos.list limit


def load_video_ids(path: Path = VIDEOS_CSV) -> list[str]:
    with path.open(newline="", encoding="utf-8") as f:
        ids = [row["video_id"].strip() for row in csv.DictReader(f)]
    if not ids:
        raise ValueError(f"No video IDs in {path}")
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate video IDs in {path}")
    if len(ids) > MAX_IDS_PER_CALL:
        raise ValueError(f"{len(ids)} IDs exceeds the {MAX_IDS_PER_CALL}-ID limit of one call")
    return ids


def fetch_stats(video_ids: list[str], api_key: str) -> str:
    """Return the raw response body as text.

    The key goes in a header, not the URL, so it can never appear in an
    error message that echoes the request URL.
    """
    resp = requests.get(
        API_URL,
        params={
            "part": "statistics,snippet",
            "id": ",".join(video_ids),
            "maxResults": MAX_IDS_PER_CALL,
        },
        headers={"X-Goog-Api-Key": api_key},
        timeout=30,
    )
    if resp.status_code != 200:
        # Report the status and Google's error reason only, never the request.
        try:
            reason = resp.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            reason = "(no error message in response)"
        raise RuntimeError(f"YouTube API returned HTTP {resp.status_code}: {reason}")
    return resp.text


def write_raw(body: str, run_date: dt.date, raw_dir: Path | None = None) -> Path:
    """Write the response body as-is. Atomic, and refuses to overwrite."""
    raw_dir = raw_dir or RAW_DIR  # looked up at call time, not import time
    raw_dir.mkdir(parents=True, exist_ok=True)
    out = raw_dir / f"{run_date.isoformat()}.json"
    if out.exists():
        raise FileExistsError(out)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(out)
    return out


def main() -> int:
    run_date = dt.datetime.now(dt.timezone.utc).date()
    out = RAW_DIR / f"{run_date.isoformat()}.json"
    if out.exists():
        print(f"{out.name} already exists; raw files are never rewritten. Skipping.")
        return 0

    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        print("YOUTUBE_API_KEY is not set.", file=sys.stderr)
        return 1

    ids = load_video_ids()
    body = fetch_stats(ids, api_key)
    path = write_raw(body, run_date, RAW_DIR)
    print(f"Wrote {path.relative_to(REPO_ROOT)} ({len(ids)} videos requested)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
