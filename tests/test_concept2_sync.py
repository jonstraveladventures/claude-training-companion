"""Concept2 Logbook sync against a fake API: no network, no credentials, no real data.

Run from the repo root: python -m unittest discover -s tests
"""
import io
import json
import os
import stat
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fitness import concept2_sync as c2  # noqa: E402

CREDS = {"CONCEPT2_CLIENT_ID": "id", "CONCEPT2_CLIENT_SECRET": "secret",
         "CONCEPT2_REFRESH_TOKEN": "refresh-1"}


def result(log_id, day, time=12000):
    return {"id": log_id, "date": f"{day} 07:00:00", "distance": 5000, "time": time,
            "type": "rower"}


class FakeAPI:
    """Stands in for urllib.request.urlopen: answers the token exchange and serves
    `pages` of results, recording every request it saw."""

    def __init__(self, pages, new_refresh="refresh-2", token_error=None):
        self.pages, self.new_refresh, self.token_error = pages, new_refresh, token_error
        self.token_requests, self.result_queries = [], []

    def __call__(self, req, *args, **kwargs):
        if req.full_url == c2.TOKEN_URL:
            self.token_requests.append(urllib.parse.parse_qs(req.data.decode()))
            if self.token_error:
                raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {},
                                             io.BytesIO(json.dumps(self.token_error).encode()))
            return io.BytesIO(json.dumps(
                {"access_token": "access", "refresh_token": self.new_refresh}).encode())
        assert req.get_header("Authorization") == "Bearer access"
        q = urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)
        self.result_queries.append(q)
        page = int(q["page"][0])
        return io.BytesIO(json.dumps({
            "data": self.pages[page - 1],
            "meta": {"pagination": {"total_pages": len(self.pages)}}}).encode())


class Concept2SyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "data").mkdir()
        self.env = self.tmp / ".env"
        self.env.write_text("STRAVA_CLIENT_ID=keep\nCONCEPT2_REFRESH_TOKEN=refresh-1\n")
        self.cache = self.tmp / "data" / "concept2_api_cache.json"
        for patch in (mock.patch.object(c2, "ROOT", self.tmp),
                      mock.patch.object(c2, "CACHE", self.cache),
                      mock.patch.dict(os.environ, CREDS)):
            patch.start()
            self.addCleanup(patch.stop)

    def run_sync(self, api, fn=None, **kwargs):
        with mock.patch("urllib.request.urlopen", api):
            return (fn or c2.sync)(**kwargs)

    def cached(self):
        return json.loads(self.cache.read_text())

    def test_rotated_refresh_token_is_written_back(self):
        self.run_sync(FakeAPI([[]]))
        lines = self.env.read_text().splitlines()
        self.assertIn("CONCEPT2_REFRESH_TOKEN=refresh-2", lines)
        self.assertNotIn("CONCEPT2_REFRESH_TOKEN=refresh-1", lines)
        self.assertIn("STRAVA_CLIENT_ID=keep", lines)          # the rest of .env survives
        self.assertEqual(stat.S_IMODE(self.env.stat().st_mode), 0o600)
        self.assertEqual(os.environ["CONCEPT2_REFRESH_TOKEN"], "refresh-2")

    def test_dead_refresh_token_says_so(self):
        api = FakeAPI([[]], token_error={"message": "The refresh token is invalid."})
        with self.assertRaisesRegex(RuntimeError, "HTTP 400: The refresh token is invalid"):
            self.run_sync(api)
        self.assertFalse(self.cache.exists())                   # nothing half-written

    def test_unrotated_token_leaves_env_alone(self):
        before = self.env.read_text()
        self.run_sync(FakeAPI([[]], new_refresh="refresh-1"))
        self.assertEqual(self.env.read_text(), before)

    def test_access_is_read_only(self):
        api = FakeAPI([[]])
        self.run_sync(api)
        self.assertEqual(api.token_requests[0]["scope"], ["user:read,results:read"])
        self.assertFalse(hasattr(c2, "post_result"))

    def test_pagination_and_partial_fetch_merge_into_cache(self):
        self.cache.write_text(json.dumps([result(1, "2026-09-01"), result(2, "2026-09-03")]))
        api = FakeAPI([[result(1, "2026-09-01", time=11900), result(3, "2026-09-05")],
                       [result(4, "2026-09-07")]])
        n = self.run_sync(api, updated_after="2026-08-25")
        self.assertEqual(n, 3)                                  # results fetched, both pages
        self.assertEqual([q["page"] for q in api.result_queries], [["1"], ["2"]])
        self.assertEqual(api.result_queries[0]["updated_after"], ["2026-08-25"])
        rows = self.cached()
        self.assertEqual([r["id"] for r in rows], [1, 2, 3, 4])  # merged, sorted by date
        self.assertEqual(rows[0]["time"], 11900)                # the fresh copy wins

    def test_full_sync_drops_results_deleted_in_the_logbook(self):
        self.cache.write_text(json.dumps([result(i, f"2026-09-0{i}") for i in (1, 2, 3)]))
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            n = self.run_sync(FakeAPI([[result(1, "2026-09-01"), result(3, "2026-09-03")]]))
        self.assertEqual(n, 2)
        self.assertEqual([r["id"] for r in self.cached()], [1, 3])
        self.assertIn("result 2 (2026-09-02 07:00, 5000 m) is no longer in the Logbook", out.getvalue())

    def test_full_sync_refuses_an_empty_listing(self):
        self.cache.write_text(json.dumps([result(1, "2026-09-01"), result(2, "2026-09-02")]))
        before = self.cache.read_text()
        with self.assertRaisesRegex(RuntimeError, "returned 0 results and would drop 2 of 2"):
            self.run_sync(FakeAPI([[]]))
        self.assertEqual(self.cache.read_text(), before)

    def test_full_sync_refuses_to_drop_more_than_ten(self):
        self.cache.write_text(json.dumps([result(i, "2026-09-01") for i in range(1, 13)]))
        before = self.cache.read_text()
        with self.assertRaisesRegex(RuntimeError, "would drop 11 of 12"):
            self.run_sync(FakeAPI([[result(1, "2026-09-01")]]))
        self.assertEqual(self.cache.read_text(), before)

    def test_first_sync_creates_the_data_folder(self):
        (self.tmp / "data").rmdir()
        self.run_sync(FakeAPI([[result(1, "2026-09-01")]]))
        self.assertEqual([r["id"] for r in self.cached()], [1])

    def test_incremental_overlaps_a_week_before_the_newest_result(self):
        self.cache.write_text(json.dumps([result(1, "2026-08-02"), result(2, "2026-09-20")]))
        api = FakeAPI([[]])
        self.run_sync(api, c2.incremental)
        self.assertEqual(api.result_queries[0]["updated_after"], ["2026-09-13"])

    def test_incremental_fetches_everything_on_a_first_run(self):
        api = FakeAPI([[result(1, "2026-09-01")]])
        self.assertEqual(self.run_sync(api, c2.incremental), 1)
        self.assertNotIn("updated_after", api.result_queries[0])

    def test_configured_needs_all_three_credentials(self):
        self.assertTrue(c2.configured())
        for key in CREDS:
            with mock.patch.dict(os.environ, {key: ""}):
                self.assertFalse(c2.configured(), key)

    def test_missing_credential_names_the_variable(self):
        with mock.patch.dict(os.environ, {"CONCEPT2_CLIENT_SECRET": ""}):
            with self.assertRaisesRegex(RuntimeError, "CONCEPT2_CLIENT_SECRET is not set"):
                self.run_sync(FakeAPI([[]]))


if __name__ == "__main__":
    unittest.main()
