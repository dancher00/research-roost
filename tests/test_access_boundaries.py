from __future__ import annotations

import contextlib
import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from phd_search.cli import main
from phd_search.network import Client
from phd_search.store import Store


class AccessFixture(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.requests.append(self.path)
        if self.path == "/robots.txt":
            status, body, content_type = self.server.robots
        else:
            status, body, content_type = self.server.pages.get(self.path, (404, b"Missing fixture", "text/plain"))
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class AccessBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), AccessFixture)
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
        self.server.requests = []
        self.server.pages = {}
        self.server.robots = (200, b"User-agent: *\nAllow: /\n", "text/plain")
        self.invoke("init")

    def invoke(self, *args, expected=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        # The only transport injection is the existing private-address fixture hook.
        with patch("phd_search.cli.Client", side_effect=lambda root: Client(root, allow_private=True, interval=0, timeout=2)):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                status = main(["--workspace", str(self.root), *map(str, args)])
        self.assertEqual(status, expected, stderr.getvalue() or stdout.getvalue())
        return json.loads(stdout.getvalue() or stderr.getvalue())

    @staticmethod
    def html(body):
        return (200, ("<!doctype html><html><body>" + body + "</body></html>").encode(), "text/html; charset=utf-8")

    @staticmethod
    def article():
        return ("<main><h1>Doctoral fellowship in coastal archives</h1>"
                "<p>The researcher will compare oral histories and regional port records to study changes in coastal communities. "
                "The three year programme provides supervision in archival interpretation, interview design, and historical geography. "
                "Applications must include a research statement, writing sample, and academic curriculum vitae.</p>"
                "<p>Closing date: 30 June 2093</p></main>")

    def register_source(self, identifier, listing, pattern):
        file = self.root.parent / (identifier + ".json")
        file.write_text(json.dumps({"id": identifier, "kind": "html", "enabled": True, "url": self.origin + listing, "link_pattern": pattern}))
        self.invoke("sources", "add", "--file", file)

    def test_html_robots_response_is_unavailable_and_posting_is_not_requested(self):
        variants = [
            (b"<html><body><h1>Checking your browser</h1></body></html>", "text/html"),
            (b"<!-- proxy notice --><html><body>Access gate</body></html>", "text/plain"),
            ("\ufeff<!doctype html><html><form id='challenge-form'></form></html>".encode(), "text/plain"),
        ]
        for body, content_type in variants:
            with self.subTest(content_type=content_type, body=body):
                self.server.robots = (200, body, content_type)
                self.server.pages["/doctoral/public"] = self.html(self.article())
                before = len(self.server.requests)
                result = self.invoke("opportunity", "add", self.origin + "/doctoral/public", expected=2)
                self.assertIn("Cannot establish robots policy", result["error"])
                self.assertIn("HTML", result["error"])
                self.assertEqual(self.server.requests[before:], ["/robots.txt"])
        self.assertEqual(self.invoke("opportunity", "list"), [])

    def test_empty_plain_allow_and_missing_robots_keep_their_semantics(self):
        variants = [
            (200, b"", "text/plain"),
            (200, b" \n# no restrictions\n", "text/plain"),
            (200, b"# A documentation example: <html>\nUser-agent: *\nAllow: /\n", "text/plain"),
            (200, b"User-agent: other-crawler\nDisallow: /\n", "text/plain"),
            (404, b"<html><h1>Not found</h1></html>", "text/html"),
        ]
        for index, policy in enumerate(variants):
            with self.subTest(policy=policy):
                path = f"/doctoral/allowed-{index}"
                self.server.robots = policy
                self.server.pages[path] = self.html(self.article())
                result = self.invoke("opportunity", "add", self.origin + path)
                self.assertEqual(result["title"], "Doctoral fellowship in coastal archives")

    def test_password_login_shell_is_rejected_in_live_and_manual_import(self):
        shell = self.html('<h1>Sign in to continue</h1><p>Your session expired.</p><form method="post" action="/account/login"><input type="email" name="email"><input type="password" name="password"><button>Sign in</button></form>')
        self.server.pages["/doctoral/members"] = shell
        result = self.invoke("opportunity", "add", self.origin + "/doctoral/members", expected=2)
        self.assertIn("authentication form", result["error"])
        saved = self.root.parent / "saved-access-page.html"
        saved.write_bytes(shell[1])
        result = self.invoke("opportunity", "import", "--file", saved, "--url", "https://institution.example/doctoral/members", "--mode", "html", expected=2)
        self.assertIn("authentication form", result["error"])
        self.assertEqual(self.invoke("opportunity", "list"), [])

    def test_email_only_sso_form_is_rejected_without_password_keyword(self):
        self.server.pages["/doctoral/sso"] = self.html('<main><form action="/sso/login" method="post"><label>Institutional email<input type="email" name="username"></label><button>Continue</button></form></main>')
        result = self.invoke("opportunity", "add", self.origin + "/doctoral/sso", expected=2)
        self.assertIn("authentication form", result["error"])

    def test_long_central_authentication_instructions_are_still_a_shell(self):
        instructions = ("Use the email address registered with your applicant account. If your password is unavailable, "
                        "request a reset and check the message delivered to that address. Accounts expire after a period of inactivity. "
                        "The university uses essential cookies to retain your application progress and protect account access. "
                        "Please read the privacy statement before entering personal details. New applicants can create an account, "
                        "while returning applicants can recover access through the admissions support service. "
                        "Support is available during the working hours listed on the university contact page.")
        body = ('<head><title>Sign in</title></head><main><h1>Sign in to continue</h1><p>' + instructions
                + '</p><form action="/login" method="post"><input type="email"><input type="password"><button>Sign in</button></form></main>')
        self.server.pages["/doctoral/long-account-shell"] = self.html(body)
        result = self.invoke("opportunity", "add", self.origin + "/doctoral/long-account-shell", expected=2)
        self.assertIn("authentication form", result["error"])
        self.assertEqual(self.invoke("opportunity", "list"), [])

    def test_stale_jsonld_cannot_make_a_login_shell_readable(self):
        metadata = json.dumps({"@type": "JobPosting", "title": "Doctoral fellowship in coastal archives", "description": "An archived full research description that is no longer accessible without a session."})
        self.server.pages["/doctoral/stale-metadata"] = self.html('<script type="application/ld+json">' + metadata + '</script><main><h1>Account access</h1><form action="/login"><input type="password"></form></main>')
        self.invoke("opportunity", "add", self.origin + "/doctoral/stale-metadata", expected=2)
        self.assertEqual(self.invoke("opportunity", "list"), [])

    def test_real_posting_with_login_link_and_text_mention_remains_available(self):
        body = '<nav><a href="/login">Log in</a></nav>' + self.article() + '<p>Applicants log in to the portal after preparing their documents.</p>'
        self.server.pages["/doctoral/readable"] = self.html(body)
        result = self.invoke("opportunity", "add", self.origin + "/doctoral/readable")
        shown = self.invoke("opportunity", "show", result["id"], "--text")
        self.assertIn("compare oral histories", shown["text"])
        self.assertEqual(shown["data"]["title"], "Doctoral fellowship in coastal archives")

    def test_no_form_text_about_login_and_browser_challenges_is_not_a_veto(self):
        self.server.pages["/doctoral/digital-history"] = self.html('<h1>Doctoral project in digital history</h1><p>Study login experiences and browser challenges in historical web archives.</p>')
        result = self.invoke("opportunity", "add", self.origin + "/doctoral/digital-history")
        self.assertEqual(result["title"], "Doctoral project in digital history")

    def test_readable_posting_with_password_widget_in_navigation_is_kept(self):
        body = '<header><form action="/login"><input type="email"><input type="password"><button>Log in</button></form></header><main><h1>Doctoral heritage studentship</h1><p>Study port records with historical geography. Closing date: 20 July 2094.</p></main>'
        self.server.pages["/doctoral/navigation-widget"] = self.html(body)
        result = self.invoke("opportunity", "add", self.origin + "/doctoral/navigation-widget")
        self.assertEqual(result["title"], "Doctoral heritage studentship")

    def test_readable_posting_with_login_modal_and_application_captcha_is_kept(self):
        body = '<title>Doctoral fellowship in coastal archives</title>' + self.article() + '<dialog><form action="/login"><input type="password"><button>Sign in</button></form></dialog><form action="/apply"><div class="g-recaptcha" data-sitekey="example-key"></div><button>Apply</button></form><script src="https://www.google.com/recaptcha/api.js"></script>'
        self.server.pages["/doctoral/application-widget"] = self.html(body)
        result = self.invoke("opportunity", "add", self.origin + "/doctoral/application-widget")
        self.assertEqual(result["title"], "Doctoral fellowship in coastal archives")

    def test_browser_challenge_shell_is_rejected(self):
        variants = [
            '<form id="challenge-form" action="/cdn-cgi/challenge-platform/verify"><button>Continue</button></form>',
            '<div class="cf-turnstile" data-sitekey="test-key"></div><script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>',
            '<script>window._cf_chl_opt = {token: "synthetic-test"};</script><p>One moment.</p>',
            '<title>Checking your browser</title><h1>Verify you are human</h1><p>Please enable JavaScript and cookies to continue.</p>',
        ]
        for index, body in enumerate(variants):
            path = f"/doctoral/challenge-{index}"
            self.server.pages[path] = self.html(body)
            result = self.invoke("opportunity", "add", self.origin + path, expected=2)
            self.assertIn("browser/CAPTCHA challenge", result["error"])
        self.assertEqual(self.invoke("opportunity", "list"), [])

    def test_browser_research_posting_can_mention_javascript_cookies_and_human_interaction(self):
        body = ('<title>Doctoral research in human interaction</title><main><h1>Doctoral research in human interaction</h1>'
                '<p>The project studies JavaScript interfaces, cookies, and browser challenges using interviews and archival website records. '
                'Researchers will analyse how people respond to the instruction "Please enable JavaScript and cookies to continue" and the heading '
                '"Verify you are human". The research includes accessibility and human interaction across devices.</p></main>')
        self.server.pages["/doctoral/browser-research"] = self.html(body)
        result = self.invoke("opportunity", "add", self.origin + "/doctoral/browser-research")
        self.assertEqual(result["title"], "Doctoral research in human interaction")

    def test_scrape_keeps_auth_and_challenge_errors_local_then_stores_good_source(self):
        self.server.pages["/blocked-list"] = self.html('<a href="/blocked/login">One</a><a href="/blocked/challenge">Two</a>')
        self.server.pages["/blocked/login"] = self.html('<form action="/login"><input type="password"><button>Continue</button></form>')
        self.server.pages["/blocked/challenge"] = self.html('<form id="challenge-form" action="/cdn-cgi/challenge-platform/verify"></form>')
        self.server.pages["/public-list"] = self.html('<a href="/doctoral/real">Available</a>')
        self.server.pages["/doctoral/real"] = self.html(self.article())
        self.register_source("blocked", "/blocked-list", r"/blocked/(?:login|challenge)$")
        self.register_source("public", "/public-list", r"/doctoral/real$")
        result = self.invoke("scrape", "--source", "blocked", "--source", "public", "--limit", "3", "--pages", "1")
        self.assertEqual([report["status"] for report in result["sources"]], ["partial", "ok"])
        self.assertEqual(len(result["sources"][0]["errors"]), 2)
        self.assertEqual(result["sources"][0]["stored"], [])
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(len(self.invoke("opportunity", "list")), 1)
        with Store(self.root) as store:
            saved = store.db.execute("SELECT data FROM runs WHERE kind='scrape'").fetchone()
            self.assertEqual(json.loads(saved[0]), result)

    def test_discovery_health_and_scrape_report_challenge_unavailable_but_keep_valid_listings(self):
        self.server.pages["/challenge-list"] = self.html('<title>Checking your browser</title><h1>Verify you are human</h1><p>Please enable JavaScript and cookies to continue.</p>')
        self.server.pages["/empty-list"] = self.html('<h1>Doctoral opportunities</h1><p>No calls are currently open.</p>')
        self.server.pages["/real-list"] = self.html('<nav><a href="/login">Log in</a></nav><main><h1>Doctoral opportunities</h1><a href="/doctoral/real">Coastal archive studentship</a></main>')
        self.server.pages["/doctoral/real"] = self.html(self.article())
        self.register_source("challenge", "/challenge-list", r"/doctoral/\w+$")
        self.register_source("empty", "/empty-list", r"/doctoral/\w+$")
        self.register_source("real", "/real-list", r"/doctoral/\w+$")
        self.assertEqual(self.invoke("sources", "health", "--source", "challenge")[0]["state"], "unavailable")
        self.assertEqual(self.invoke("sources", "health", "--source", "empty")[0]["state"], "no_links")
        self.assertEqual(self.invoke("sources", "health", "--source", "real")[0]["state"], "ok")
        result = self.invoke("scrape", "--source", "challenge", "--source", "real", "--limit", "2", "--pages", "1")
        self.assertEqual([report["status"] for report in result["sources"]], ["partial", "ok"])
        self.assertIn("browser/CAPTCHA", result["sources"][0]["errors"][0]["message"])
        self.assertEqual(result["sources"][0]["errors"][0]["stage"], "listing")
        self.assertEqual(len(result["matches"]), 1)


if __name__ == "__main__":
    unittest.main()
