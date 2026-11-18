"""Made-up raw history shared by the Stage 2 and Stage 3 tests.

It's built to set off every check:

  video A  100 -> 150 ->  (no file) -> 300   normal growth, then a missed day
  video B  200 -> 190 ->  (no file) -> 250   views drop (negative gain)
  video C  300 -> (missing from response) -> (no file) -> 400
  video D  in videos.csv but never returned by YouTube
  2026-01-03 has no raw file at all
"""

import json
import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import transform  # noqa: E402


def item(vid, views, likes=10, comments=1, published="2022-07-21T15:00:14Z"):
    stats = {"viewCount": str(views), "commentCount": str(comments)}
    if likes is not None:
        stats["likeCount"] = str(likes)
    return {"kind": "youtube#video", "id": vid,
            "snippet": {"publishedAt": published, "title": f"Title {vid}",
                        "channelTitle": "HYBE LABELS"},
            "statistics": stats}


HISTORY = {
    "2026-01-01": [item("A", 100), item("B", 200), item("C", 300)],
    "2026-01-02": [item("A", 150), item("B", 190, likes=None)],   # B hides likes, C missing
    "2026-01-04": [item("A", 300), item("B", 250), item("C", 400)],
}


@pytest.fixture
def con(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    for day, items in HISTORY.items():
        (raw / f"{day}.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    csv = tmp_path / "videos.csv"
    csv.write_text("video_id,song,era\nA,Song A,Era 1\nB,Song B,Era 1\n"
                   "C,Song C,Era 2\nD,Song D,Era 2\n", encoding="utf-8")
    c = duckdb.connect()
    transform.build(c, raw, csv)
    return c
