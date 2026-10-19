from __future__ import annotations

import copy
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from phd_search.cli import initialise
from phd_search.core import Error, atomic_write, json_text
from phd_search.network import Client
from phd_search.sources import scrape
from phd_search.store import Store


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.requests.append((self.path, dict(self.headers)))
        if self.path == "/robots.txt":
            reply = (self.server.robots_status, self.server.robots_text, {})
        else:
            reply = self.server.routes.get(self.path, (404, b"Missing", {}))
            if callable(reply):
                reply = reply(self)
        status, body, headers = reply
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        if "Content-Length" not in headers:
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class SourceBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "workspace"
        initialise(self.root)
        self.server.requests = []
        self.server.routes = {}
        self.server.robots_status = 200
        self.server.robots_text = b"User-agent: *\nAllow: /\n"
        self.client = self.new_client()

    def new_client(self):
        return Client(self.root, allow_private=True, interval=0, timeout=2)

    def html(self, body):
        return (200, body.encode(), {"Content-Type": "text/html"})

    def posting(self, fields=None):
        job = {"@type": "JobPosting", "title": "Doctoral project", "description": "Research archival sources.", "validThrough": "2099-12-31"}
        job.update(fields or {})
        return self.html('<html><script type="application/ld+json">' + json.dumps(job) + '</script><h1>Doctoral project</h1></html>')

    def source(self, identifier, listing, pattern):
        return {"id": identifier, "kind": "html", "url": self.origin + listing, "link_pattern": pattern}

    def configure(self, entries):
        atomic_write(self.root / "sources.json", json_text({"schema_version": 1, "sources": entries}))

    def headers_for(self, path):
        return [{key.lower(): value for key, value in headers.items()} for requested, headers in self.server.requests if requested == path]

    def test_direct_etag_and_last_modified_revalidation_remain_supported(self):
        for path, validator, value in (("/etag", "ETag", '"v1"'), ("/modified", "Last-Modified", "Mon, 19 Oct 2026 08:00:00 GMT")):
            with self.subTest(validator=validator):
                conditional = "If-None-Match" if validator == "ETag" else "If-Modified-Since"
                self.server.routes[path] = lambda request, header=conditional, token=value, name=validator: (
                    (304, b"", {}) if request.headers.get(header) == token else (200, b"Current body", {name: token})
                )
                first = self.client.get(self.origin + path)
                second = self.client.get(self.origin + path)
                self.assertFalse(first.cached)
                self.assertTrue(second.cached)
                self.assertEqual(second.body, first.body)
                self.assertEqual(second.url, self.origin + path)

    def test_unsolicited_304_without_sent_validators_is_rejected(self):
        self.server.routes["/no-cache"] = (304, b"", {})
        with self.assertRaisesRegex(Error, "304.*same cached resource"):
            self.client.get(self.origin + "/no-cache")
        self.server.routes["/no-validator"] = (200, b"Original", {})
        self.client.get(self.origin + "/no-validator")
        self.server.routes["/no-validator"] = (304, b"", {})
        with self.assertRaisesRegex(Error, "304.*same cached resource"):
            self.client.get(self.origin + "/no-validator")
        self.server.routes["/refresh"] = (200, b"Original", {"ETag": '"v1"'})
        self.client.get(self.origin + "/refresh")
        self.server.routes["/refresh"] = (304, b"", {})
        with self.assertRaisesRegex(Error, "304.*same cached resource"):
            self.client.get(self.origin + "/refresh", refresh=True)

    def test_expired_redirect_does_not_revalidate_old_posting_in_full_scrape(self):
        self.server.routes["/listing"] = self.html('<html><a href="/job/1">Project</a></html>')
        status, body, headers = self.posting()
        self.server.routes["/job/1"] = (status, body, {**headers, "ETag": '"shared"', "Last-Modified": "Mon, 19 Oct 2026 08:00:00 GMT"})
        self.configure([self.source("fixture", "/listing", r"/job/\d+$")])
        with Store(self.root) as store:
            first = scrape(store, self.client, sources=None, query="", limit=3, pages=1)
            self.assertEqual(len(first["matches"]), 1)
            self.server.routes["/job/1"] = (302, b"", {"Location": "/search"})
            self.server.routes["/search"] = lambda request: (
                (304, b"", {}) if request.headers.get("If-None-Match") == '"shared"' else self.html("<html><h1>Search listings</h1></html>")
            )
            second = scrape(store, self.client, sources=None, query="", limit=3, pages=1)
            self.assertEqual(second["sources"][0]["status"], "partial")
            self.assertEqual(second["matches"], [])
            self.assertEqual(second["sources"][0]["stored"], [])
            self.assertIn("redirected to a different page", second["sources"][0]["errors"][0]["message"])
            self.assertEqual(store.db.execute("SELECT count(*) FROM snapshots").fetchone()[0], 1)
            final_headers = self.headers_for("/search")[-1]
            self.assertNotIn("if-none-match", final_headers)
            self.assertNotIn("if-modified-since", final_headers)

    def test_forced_304_at_redirect_destination_is_never_accepted(self):
        self.server.routes["/job/1"] = (200, b"Original", {"ETag": '"shared"'})
        self.client.get(self.origin + "/job/1")
        self.server.routes["/job/1"] = (302, b"", {"Location": "/other"})
        self.server.routes["/other"] = (304, b"", {})
        with self.assertRaisesRegex(Error, "304.*same cached resource"):
            self.client.get(self.origin + "/job/1")
        self.assertNotIn("if-none-match", self.headers_for("/other")[-1])

    def test_cached_final_url_does_not_lend_validators_to_alias(self):
        self.server.routes["/alias"] = (302, b"", {"Location": "/actual"})
        self.server.routes["/actual"] = (200, b"Actual", {"ETag": '"actual-v1"'})
        first = self.client.get(self.origin + "/alias")
        second = self.client.get(self.origin + "/alias")
        self.assertEqual(first.url, self.origin + "/actual")
        self.assertFalse(second.cached)
        self.assertTrue(all("if-none-match" not in headers for path in ("/alias", "/actual") for headers in self.headers_for(path)))
        self.server.routes["/actual"] = (304, b"", {})
        with self.assertRaisesRegex(Error, "304.*same cached resource"):
            self.client.get(self.origin + "/alias")

    def test_redirect_to_different_admission_cycle_is_not_ingested(self):
        self.server.routes["/listing"] = self.html('<html><a href="/job/1?cycle=2026">Project</a></html>')
        self.server.routes["/job/1?cycle=2026"] = (302, b"", {"Location": "/job/1?cycle=2027"})
        self.server.routes["/job/1?cycle=2027"] = self.posting()
        self.configure([self.source("fixture", "/listing", r"/job/\d+\?cycle=")])
        with Store(self.root) as store:
            result = scrape(store, self.client, sources=None, query="", limit=1, pages=1)
            self.assertEqual(result["sources"][0]["status"], "partial")
            self.assertEqual(store.list(), [])

    def test_robots_longest_ties_wildcards_and_specific_product_groups(self):
        self.server.routes["/jobs/public/phd"] = (200, b"Allowed", {})
        self.server.routes["/jobs/closed"] = (200, b"Must not fetch", {})
        cases = [
            ("User-agent: *\nDisallow: /jobs/\nAllow: /jobs/public/", "/jobs/public/phd", True),
            ("User-agent: *\nDisallow: /jobs/\nAllow: /jobs/", "/jobs/public/phd", True),
            ("User-agent: *\nDisallow: /jobs/*\nAllow: /jobs/public/*$", "/jobs/public/phd", True),
            ("User-agent: *\nDisallow: /jobs/*", "/jobs/closed", False),
            ("User-agent: *\nDisallow: /\nUser-agent: PHD-SEARCH\nAllow: /jobs/public/", "/jobs/public/phd", True),
            ("User-agent: *\nAllow: /\nUser-agent: phd-search\nDisallow: /jobs/", "/jobs/public/phd", False),
            ("User-agent: unrelated\nDisallow: /", "/jobs/public/phd", True),
            ("User-agent: personal\nDisallow: /", "/jobs/public/phd", True),
            ("User-agent: phd\nDisallow: /\nUser-agent: phd-search\nAllow: /", "/jobs/public/phd", True),
            ("User-agent: phd-search\nDisallow: /jobs/\nUser-agent: PHD-SEARCH\nAllow: /jobs/public/", "/jobs/public/phd", True),
            ("User-agent: *\nDisallow: /jobs/\nUser-agent: *\nAllow: /jobs/public/", "/jobs/public/phd", True),
        ]
        for policy, path, allowed in cases:
            with self.subTest(policy=policy, path=path):
                self.server.robots_text = policy.encode()
                client = self.new_client()
                before = len(self.headers_for(path))
                if allowed:
                    self.assertEqual(client.get(self.origin + path).body, b"Allowed")
                else:
                    with self.assertRaisesRegex(Error, "disallows"):
                        client.get(self.origin + path)
                    self.assertEqual(len(self.headers_for(path)), before)

    def test_robots_missing_is_allowed_but_forbidden_is_unavailable(self):
        self.server.routes["/public"] = (200, b"Public", {})
        self.server.robots_status = 404
        self.assertEqual(self.new_client().get(self.origin + "/public").body, b"Public")
        self.server.robots_status = 403
        with self.assertRaisesRegex(Error, "Cannot establish robots policy.*403"):
            self.new_client().get(self.origin + "/public")

    def test_robots_specific_crawl_delay_does_not_fall_back_to_default_group(self):
        self.server.routes["/public"] = (200, b"Public", {})
        self.server.robots_text = b"User-agent: *\nCrawl-delay: 31\nDisallow: /\nUser-agent: phd-search\nCrawl-delay: 0\nAllow: /\n"
        self.assertEqual(self.client.get(self.origin + "/public").body, b"Public")

    def test_malformed_nested_jobposting_fields_do_not_stop_good_source(self):
        malformed = [
            {"validThrough": ["2099-12-31"]},
            {"@type": {"name": "JobPosting"}},
            {"title": {"name": "Doctoral project"}},
            {"description": ["Not a string"]},
            {"hiringOrganization": {"name": {"bad": "nested"}}},
            {"jobLocation": [7]},
            {"jobLocation": {"address": []}},
            {"jobLocation": {"address": {"addressCountry": {"name": []}}}},
            {"jobLocation": {"address": {"addressLocality": {"bad": "nested"}}}},
            {"identifier": {"value": []}},
            {"datePosted": {}},
        ]
        self.server.routes["/bad-list"] = self.html("<html>" + "".join(f'<a href="/bad/{index}">Malformed</a>' for index in range(len(malformed))) + "</html>")
        for index, fields in enumerate(malformed):
            self.server.routes[f"/bad/{index}"] = self.posting(fields)
        self.server.routes["/good-list"] = self.html('<html><a href="/good/1">Good</a></html>')
        self.server.routes["/good/1"] = self.posting()
        self.configure([self.source("bad", "/bad-list", r"/bad/\d+$"), self.source("good", "/good-list", r"/good/\d+$")])
        with Store(self.root) as store:
            result = scrape(store, self.client, sources=None, query="", limit=30, pages=1)
            self.assertEqual([report["status"] for report in result["sources"]], ["partial", "ok"])
            self.assertEqual(len(result["sources"][0]["errors"]), len(malformed))
            self.assertTrue(all(error["stage"] == "detail" for error in result["sources"][0]["errors"]))
            self.assertEqual(len(store.list()), 1)
            self.assertEqual(len(result["matches"]), 1)
            persisted = store.db.execute("SELECT data FROM runs WHERE kind='scrape'").fetchone()
            self.assertEqual(json.loads(persisted[0]), result)

    def test_deep_or_malformed_json_listing_preserves_partial_run(self):
        deep = {"leaf": "value"}
        for _ in range(40):
            deep = {"nested": deep}
        bad_payloads = [json.dumps({"items": [deep]}), "[" * 1500 + "0" + "]" * 1500, '{"items":[{"url":{"bad":"nested"}}]}', '{"items":[{"url":"/good/1","title":[]}]}', '{"items":[{"url":"/good/1","salary":NaN}]}', '{"items":[{"url":"/good/1","salary":1e999}]}', '{"items":[{"url":"http://["}]}']
        self.server.routes["/good-list"] = self.html('<html><a href="/good/1">Good</a></html>')
        self.server.routes["/good/1"] = self.posting()
        for index, body in enumerate(bad_payloads):
            path = f"/bad-json/{index}"
            self.server.routes[path] = (200, body.encode(), {"Content-Type": "application/json"})
        entries = [{"id": f"bad-{index}", "kind": "json", "url": self.origin + f"/bad-json/{index}", "items_path": "items", "url_field": "url", "title_field": "title"} for index in range(len(bad_payloads))]
        entries.append(self.source("good", "/good-list", r"/good/\d+$"))
        self.configure(entries)
        with Store(self.root) as store:
            result = scrape(store, self.client, sources=None, query="", limit=5, pages=1)
            self.assertTrue(all(report["status"] == "partial" for report in result["sources"][:-1]))
            self.assertEqual(result["sources"][-1]["status"], "ok")
            self.assertEqual(len(store.list()), 1)
            self.assertEqual(store.db.execute("SELECT count(*) FROM runs WHERE kind='scrape'").fetchone()[0], 1)

    def test_valid_structured_jobposting_shapes_remain_usable(self):
        job = {"@type": ["Thing", "JobPosting"], "hiringOrganization": {"name": "University"}, "identifier": {"value": "PHD-1"},
               "jobLocation": [{"address": {"addressCountry": {"name": "DE"}, "addressLocality": "Berlin"}}, {"address": "Second campus"}]}
        self.server.routes["/listing"] = self.html('<html><a href="/job/1">Good</a></html>')
        self.server.routes["/job/1"] = self.posting(copy.deepcopy(job))
        self.configure([self.source("fixture", "/listing", r"/job/\d+$")])
        with Store(self.root) as store:
            result = scrape(store, self.client, sources=None, query="", limit=1, pages=1)
            self.assertEqual(result["sources"][0]["status"], "ok")
            data = store.list()[0]["data"]
            self.assertEqual((data["institution"], data["country"], data["city"], data["reference"]), ("University", "DE", "Berlin", "PHD-1"))


if __name__ == "__main__":
    unittest.main()
