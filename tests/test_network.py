from __future__ import annotations

import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from phd_search.cli import initialise
from phd_search.core import Error, atomic_write, json_text
from phd_search.network import MAX_BYTES, Client
from phd_search.sources import feed_links, scrape
from phd_search.store import Store

FIXTURE = (Path(__file__).parent / "fixtures" / "opportunity.html").read_bytes()


class Handler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        type(self).requests.append(self.path)
        if self.path == "/robots.txt":
            return self.reply(200, b"User-agent: *\nAllow: /\nDisallow: /blocked\nDisallow: /search?*\n", "text/plain")
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/blocked")
            self.end_headers()
            return
        if self.path == "/job/4":
            self.send_response(302)
            self.send_header("Location", "/listing")
            self.end_headers()
            return
        if self.path == "/too-large":
            self.send_response(200)
            self.send_header("Content-Length", str(MAX_BYTES + 1))
            self.end_headers()
            return
        if self.path == "/etag":
            if self.headers.get("If-None-Match") == '"fixture-v1"':
                self.send_response(304)
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("ETag", '"fixture-v1"')
                self.end_headers()
                self.wfile.write(b"Original fixture body")
            return
        if self.path == "/listing":
            return self.reply(200, b'<html><a href="/job/1">Doctoral literature project</a><a rel="next" href="/listing?page=2">Next</a><a href="https://external.invalid/job/9">External</a></html>', "text/html")
        if self.path == "/listing?page=2":
            return self.reply(200, b'<html><a href="/job/2">Second project</a><a href="/job/3">Unavailable posting</a></html>', "text/html")
        if self.path in {"/job/1", "/job/2"}:
            return self.reply(200, FIXTURE, "text/html")
        if self.path in {"/job/3", "/blocked"}:
            return self.reply(403, b"Forbidden", "text/plain")
        return self.reply(404, b"Not found", "text/plain")

    def reply(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class NetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "workspace"
        initialise(self.root)
        Handler.requests = []
        self.client = Client(self.root, allow_private=True, interval=0, timeout=2)

    def test_private_network_is_rejected_by_default(self):
        with self.assertRaisesRegex(Error, "public network addresses"):
            Client(self.root).get(self.origin + "/job/1")

    def test_robot_wildcards_are_enforced_and_redirects_cannot_bypass_them(self):
        with self.assertRaisesRegex(Error, "disallows"):
            self.client.get(self.origin + "/search?query=phd")
        with self.assertRaisesRegex(Error, "disallows"):
            self.client.get(self.origin + "/redirect")
        self.assertNotIn("/blocked", Handler.requests)
        self.assertNotIn("/search?query=phd", Handler.requests)

    def test_conditional_cache_revalidates_and_detects_tampered_bodies(self):
        first = self.client.get(self.origin + "/etag")
        second = self.client.get(self.origin + "/etag")
        self.assertFalse(first.cached)
        self.assertTrue(second.cached)
        self.assertEqual(first.body, second.body)
        body_file = next((self.root / "cache").glob("*.body"))
        body_file.write_bytes(b"tampered")
        third = self.client.get(self.origin + "/etag")
        self.assertFalse(third.cached)
        self.assertEqual(third.body, b"Original fixture body")

    def test_response_limit_is_checked_before_reading_a_large_body(self):
        with self.assertRaisesRegex(Error, "exceeds"):
            self.client.get(self.origin + "/too-large")

    def test_scrape_paginates_archives_matches_and_reports_a_failed_detail(self):
        source = {"id": "fixture", "kind": "html", "enabled": True, "url": self.origin + "/listing", "link_pattern": r"/job/\d+$"}
        atomic_write(self.root / "sources.json", json_text({"schema_version": 1, "sources": [source]}))
        with Store(self.root) as store:
            result = scrape(store, self.client, sources=["fixture"], query="translation", limit=5, pages=2)
            report = result["sources"][0]
            self.assertEqual(len(store.list()), 2)
            self.assertEqual(len(report["pages"]), 2)
            self.assertEqual(report["attempted"], 3)
            self.assertEqual(report["status"], "partial")
            self.assertEqual(len(result["matches"]), 2)
            self.assertEqual(report["pages"][0]["query_mode"], "local")
            self.assertTrue(report["not_an_exhaustive_search"])
            self.assertEqual(len(report["errors"]), 1)
            self.assertFalse(any("external.invalid" in request for request in Handler.requests))

    def test_rss_and_atom_preserve_original_urls_and_reject_entities(self):
        rss = '<rss><channel><item><title>Doctoral project</title><link>https://university.example/1</link></item></channel></rss>'
        atom = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>PhD</title><link rel="alternate" href="/2"/></entry></feed>'
        self.assertEqual(feed_links(rss, "https://university.example/feed")[0]["url"], "https://university.example/1")
        self.assertEqual(feed_links(atom, "https://university.example/feed")[0]["url"], "https://university.example/2")
        with self.assertRaises(Error):
            feed_links('<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss>&x;</rss>', "https://university.example/feed")

    def test_expired_posting_redirect_is_not_stored_as_a_live_opportunity(self):
        source = {"id": "fixture", "kind": "json", "enabled": True, "url": self.origin + "/listing", "items_path": "items", "url_field": "url", "title_field": "title"}
        from unittest.mock import patch
        atomic_write(self.root / "sources.json", json_text({"schema_version": 1, "sources": [source]}))
        with Store(self.root) as store, patch("phd_search.sources.source_page", return_value=([{"url": self.origin + "/job/4", "title": "Expired PhD"}], None, {"url": self.origin + "/listing"})):
            result = scrape(store, self.client, sources=["fixture"], query="", limit=1, pages=1)
            self.assertEqual(len(store.list()), 0)
            self.assertIn("redirected to a different page", result["sources"][0]["errors"][0]["message"])


if __name__ == "__main__":
    unittest.main()
