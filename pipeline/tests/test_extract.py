"""Stage 1 tests. They mock the YouTube API, so no key or network is needed.

Run from the repo root:  python -m pytest pipeline/tests -q
"""

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import extract  # noqa: E402

FAKE_KEY = "AIzaFAKE-KEY-must-never-leak-123"

FAKE_BODY = json.dumps({
    "kind": "youtube#videoListResponse",
    "items": [{
        "kind": "youtube#video",
        "id": "ArmDp-zijuc",
        "snippet": {"publishedAt": "2023-07-06T15:00:00Z",
                    "title": "NewJeans (뉴진스) 'Super Shy' Official MV",
                    "channelTitle": "HYBE LABELS"},
        "statistics": {"viewCount": "303101455", "likeCount": "3100000",
                       "commentCount": "180000"},
    }],
    "pageInfo": {"totalResults": 1, "resultsPerPage": 1},
}, ensure_ascii=False, indent=2)


class FakeResponse:
    def __init__(self, status, text):
        self.status_code = status
        self.text = text

    def json(self):
        return json.loads(self.text)


@pytest.fixture
def capture_get(monkeypatch):
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append({"url": url, "params": params, "headers": headers})
        return calls_response[0]

    calls_response = [FakeResponse(200, FAKE_BODY)]
    monkeypatch.setattr(extract.requests, "get", fake_get)
    return calls, calls_response


REAL_RAW_DIR = extract.RAW_DIR


@pytest.fixture
def tmp_repo(monkeypatch, tmp_path):
    before = sorted(REAL_RAW_DIR.glob("*.json"))
    monkeypatch.setattr(extract, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(extract, "REPO_ROOT", tmp_path)
    yield tmp_path
    assert sorted(REAL_RAW_DIR.glob("*.json")) == before, "a test wrote into the real data/raw/"


def test_video_list_is_valid():
    ids = extract.load_video_ids()
    assert len(ids) == 15
    assert all(len(i) == 11 for i in ids), "every YouTube ID is 11 characters"


def test_one_call_for_all_videos_and_key_only_in_header(capture_get):
    calls, _ = capture_get
    ids = extract.load_video_ids()
    extract.fetch_stats(ids, FAKE_KEY)

    assert len(calls) == 1
    call = calls[0]
    assert call["params"]["part"] == "statistics,snippet"
    assert call["params"]["id"].split(",") == ids
    assert call["headers"] == {"X-Goog-Api-Key": FAKE_KEY}
    assert FAKE_KEY not in call["url"]
    assert FAKE_KEY not in json.dumps(call["params"])


def test_raw_file_is_byte_for_byte_the_response(capture_get, tmp_repo):
    body = extract.fetch_stats(["ArmDp-zijuc"], FAKE_KEY)
    path = extract.write_raw(body, dt.date(2026, 11, 18), tmp_repo / "raw")

    assert path.name == "2026-11-18.json"
    assert path.read_text(encoding="utf-8") == FAKE_BODY
    assert not list((tmp_repo / "raw").glob("*.tmp")), "no temp file left behind"


def test_raw_files_are_never_overwritten(tmp_repo):
    raw = tmp_repo / "raw"
    extract.write_raw('{"first": true}', dt.date(2026, 11, 18), raw)
    with pytest.raises(FileExistsError):
        extract.write_raw('{"second": true}', dt.date(2026, 11, 18), raw)
    assert (raw / "2026-11-18.json").read_text() == '{"first": true}'


def test_api_error_writes_nothing_and_does_not_leak_key(capture_get, tmp_repo, monkeypatch, capsys):
    _, responses = capture_get
    responses[0] = FakeResponse(403, json.dumps(
        {"error": {"code": 403, "message": "The request cannot be completed because you have exceeded your quota."}}))
    monkeypatch.setenv("YOUTUBE_API_KEY", FAKE_KEY)

    with pytest.raises(RuntimeError) as err:
        extract.main()

    assert "HTTP 403" in str(err.value)
    assert "quota" in str(err.value)
    assert FAKE_KEY not in str(err.value)
    out = capsys.readouterr()
    assert FAKE_KEY not in out.out + out.err
    assert not (tmp_repo / "raw").exists() or not any((tmp_repo / "raw").iterdir())


def test_missing_key_fails_cleanly(tmp_repo, monkeypatch, capsys):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    assert extract.main() == 1
    assert "YOUTUBE_API_KEY is not set" in capsys.readouterr().err


def test_second_run_same_day_skips_without_calling_api(capture_get, tmp_repo, monkeypatch):
    calls, _ = capture_get
    monkeypatch.setenv("YOUTUBE_API_KEY", FAKE_KEY)

    assert extract.main() == 0
    assert extract.main() == 0
    assert len(calls) == 1, "the second run must not spend quota"
    assert len(list((tmp_repo / "raw").glob("*.json"))) == 1
