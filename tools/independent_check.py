#!/usr/bin/env python3
"""Independent public-CLI checks with synthetic evidence and localhost HTTP only.

No package internals, repository test helpers, real profiles, or remote websites
are used. The proxy never forwards requests. An optional JSON report contains
the fixture inputs and complete CLI observations needed to inspect each check.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[1]
CHALLENGE = (
    "<!doctype html><html><title>Checking your browser</title>"
    "<h1>Verify you are human</h1>"
    "<p>Please enable JavaScript and cookies to continue.</p></html>"
)
LOGIN_HELP = (
    "Enter the email address associated with your applicant account and your "
    "password to continue. If you have forgotten your password, select the reset "
    "option and follow the instructions sent to your registered email. New "
    "applicants should create an account before returning to this page. Your "
    "session will expire after a period of inactivity. We use essential cookies "
    "to keep your account secure and to remember your application progress. "
    "Information entered here is processed according to the university privacy "
    "policy. For assistance accessing your account, please contact the admissions "
    "support team during normal office hours."
)
LOGIN_FORM = (
    '<form action="/login" method="post">'
    '<label>Email<input type="email" name="email"></label>'
    '<label>Password<input type="password" name="password"></label>'
    "<button>Sign in</button></form>"
)
LOGIN = (
    "<!doctype html><html><title>Sign in</title><main>"
    "<h1>Sign in to continue</h1><p>Sign in to view this doctoral vacancy.</p>"
    + LOGIN_FORM
    + "</main></html>"
)
LONG_LOGIN = (
    "<!doctype html><html><title>Sign in</title><main>"
    "<h1>Sign in to continue</h1><p>"
    + LOGIN_HELP
    + "</p>"
    + LOGIN_FORM
    + "</main></html>"
)
ADVERT = (
    "<!doctype html><html><title>PhD in Maritime Anthropology</title>"
    "<aside><h2>Applicant account</h2>" + LOGIN_FORM + "</aside><main>"
    "<h1>PhD in Maritime Anthropology</h1><p>This funded doctoral studentship "
    "explores how coastal communities preserve and communicate knowledge about "
    "changing marine environments. The successful researcher will combine oral "
    "history interviews, participant observation and archival analysis in a "
    "comparative study of two ports. Candidates should have experience with "
    "qualitative research and be interested in collaborative fieldwork. "
    "Applicants must submit an academic CV, a short statement of motivation and "
    "a writing sample. The project is hosted by the Department of Anthropology "
    "and runs for three years. The deadline is 15 December 2027. Shortlisted "
    "applicants will be invited to discuss their research interests with the "
    "selection panel. The full project description and eligibility requirements "
    "are visible on this page without signing in.</p></main></html>"
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def source_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((REPO / "phd_search").rglob("*.py"))
    }


class Check:
    def __init__(self, root: Path, env: dict[str, str]):
        self.root = root
        self.env = env
        self.checks: list[dict] = []
        self.commands: list[dict] = []
        self.fixtures: dict[str, str] = {}

    def check(self, name: str, passed: bool, observed: object = None) -> None:
        self.checks.append(
            {"name": name, "status": "PASS" if passed else "FAIL", "observed": observed}
        )

    def cli(self, workspace: Path, *args: str) -> tuple[int, object]:
        command = [str(REPO / "phd"), "--workspace", str(workspace), *args]
        result = subprocess.run(
            command,
            cwd=REPO,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        self.commands.append(
            {
                "command": command,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        try:
            data = json.loads(result.stdout)
        except ValueError:
            data = None
        return result.returncode, data

    def fixture(self, name: str, text: str) -> Path:
        self.fixtures[name] = text
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def http(self, requests: list[str]) -> None:
        ws = self.root / "http-workspace"
        code, _ = self.cli(ws, "init")
        self.check("HTTP fixture workspace initialises", code == 0)
        cases = [
            ("HTTP200 login wall", "http://8.8.8.8/login-required", False),
            ("long central authentication shell", "http://8.8.8.8/long-login", False),
            ("HTTP200 browser challenge", "http://8.8.8.8/challenge", False),
            ("HTML challenge instead of robots", "http://9.9.9.9/advert", False),
            ("robots disallow", "http://1.1.1.1/advert", False),
            ("robots 404", "http://1.0.0.1/advert", True),
            ("empty text robots policy", "http://208.67.222.222/advert", True),
            ("HTML robots with text/plain type", "http://208.67.220.220/advert", False),
            ("real long advert with ancillary login", "http://8.8.8.8/advert", True),
        ]
        for name, url, allowed in cases:
            code, data = self.cli(ws, "opportunity", "add", url)
            self.check(name, (code == 0) == allowed, {"exit_code": code, "data": data})
        code, items = self.cli(ws, "opportunity", "list")
        wanted = {url for _, url, allowed in cases if allowed}
        stored = {item["url"] for item in items} if isinstance(items, list) else set()
        self.check(
            "only readable adverts are stored", code == 0 and stored == wanted, items
        )
        forbidden = {
            url
            for _, url, _ in cases
            if urlsplit(url).hostname in {"9.9.9.9", "1.1.1.1", "208.67.220.220"}
        }
        self.check(
            "robots failures prevent detail requests", forbidden.isdisjoint(requests)
        )
        self.check(
            "actual HTTP responses exercised the content checks",
            all(
                url in requests
                for _, url, _ in cases
                if urlsplit(url).hostname == "8.8.8.8"
            ),
        )
        saved = self.fixture("saved-login.html", LOGIN)
        code, data = self.cli(
            ws,
            "opportunity",
            "import",
            "--file",
            str(saved),
            "--url",
            "https://institution.example/saved-login",
            "--mode",
            "html",
        )
        self.check("saved HTML login is rejected", code != 0, data)
        for source_id, path in [
            ("login-detail", "/list"),
            ("challenge-list", "/challenge-list"),
        ]:
            source = {
                "id": source_id,
                "name": "Independent synthetic fixture",
                "kind": "html",
                "enabled": True,
                "url": "http://8.8.8.8" + path,
                "link_pattern": "/login-required$",
                "verified_on": "2026-10-19",
                "notes": "Local non-forwarding proxy; not an actual doctoral source.",
            }
            file = self.fixture(source_id + ".json", json.dumps(source))
            code, _ = self.cli(ws, "sources", "add", "--file", str(file))
            self.check(source_id + " source registers", code == 0)
            code, data = self.cli(
                ws, "scrape", "--source", source_id, "--limit", "1", "--pages", "1"
            )
            rows = data.get("sources", []) if isinstance(data, dict) else []
            row = rows[0] if rows else {}
            self.check(
                source_id + " scraping reports access failure",
                bool(row.get("errors"))
                and not row.get("stored")
                and row.get("status") != "ok",
                {"exit_code": code, "data": data},
            )
        code, health = self.cli(ws, "sources", "health", "--source", "challenge-list")
        row = health[0] if isinstance(health, list) and health else {}
        self.check(
            "challenge health is unavailable rather than no_links",
            row.get("state") in {"unavailable", "blocked", "error", "failed"},
            {"exit_code": code, "data": health},
        )

    def semantic(self) -> None:
        ws = self.root / "semantic-workspace"
        code, _ = self.cli(ws, "init")
        self.check("semantic fixture workspace initialises", code == 0)
        profile = json.loads((ws / "profile.json").read_text(encoding="utf-8"))
        profile["preferences"]["require_full_funding"] = True
        profile["preferences"]["minimum_funding"] = {
            "amount": 1800,
            "currency": "EUR",
            "period": "month",
            "basis": "net",
        }
        file = self.fixture("synthetic-profile.json", json.dumps(profile))
        code, _ = self.cli(ws, "profile", "import", "--file", str(file))
        self.check("synthetic funding preferences import", code == 0)
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(microsecond=0)
        future_year = datetime.now(timezone.utc).year + 2
        cases = [
            (
                "precise_visible",
                f"{future_year}-03-04T15:45:00+05:30",
                f"4 March {future_year}",
                f"{future_year}-03-04T15:45:00+05:30",
                "time",
                "UTC+05:30",
            ),
            (
                "precise_alone",
                f"{future_year}-03-04T15:45:00+05:30",
                None,
                f"{future_year}-03-04T15:45:00+05:30",
                "time",
                "UTC+05:30",
            ),
            (
                "midnight_alone",
                f"{future_year}-03-04T00:00:00-04:00",
                None,
                f"{future_year}-03-04T00:00:00-04:00",
                "time",
                "UTC-04:00",
            ),
            (
                "midnight_visible",
                f"{future_year}-03-04T00:00:00-04:00",
                f"4 March {future_year}",
                f"{future_year}-03-04",
                "date",
                None,
            ),
            (
                "date_only",
                f"{future_year}-03-04",
                None,
                f"{future_year}-03-04",
                "date",
                None,
            ),
            (
                "local_time",
                f"{future_year}-03-04T15:45:00",
                None,
                None,
                "unknown",
                None,
            ),
            (
                "past_exact_visible",
                past.isoformat(),
                past.strftime("%d %B %Y"),
                past.isoformat(),
                "time",
                "UTC",
            ),
            (
                "date_conflict",
                f"{future_year}-03-04T15:45:00+05:30",
                f"5 March {future_year}",
                None,
                "unknown",
                None,
            ),
            (
                "salary_only",
                f"{future_year}-03-04",
                None,
                f"{future_year}-03-04",
                "date",
                None,
            ),
        ]
        ids = {}
        for key, stamp, visible, expected, precision, zone in cases:
            schema = {
                "@context": "https://schema.org",
                "@type": "JobPosting",
                "title": "PhD in Archival Studies " + key,
                "description": "Doctoral research on historical archives. Please submit a CV.",
                "validThrough": stamp,
            }
            if key == "salary_only":
                schema["baseSalary"] = {
                    "@type": "MonetaryAmount",
                    "currency": "EUR",
                    "value": {
                        "@type": "QuantitativeValue",
                        "value": 2400,
                        "unitText": "MONTH",
                    },
                }
            text = (
                '<!doctype html><html><script type="application/ld+json">'
                + json.dumps(schema)
                + "</script><body><h1>"
                + schema["title"]
                + "</h1>"
            )
            if visible:
                text += "<p>Closing date: " + visible + "</p>"
            text += "<p>Doctoral research on historical archives. Please submit a CV.</p></body></html>"
            file = self.fixture(key + ".html", text)
            code, item = self.cli(
                ws,
                "opportunity",
                "import",
                "--file",
                str(file),
                "--url",
                "https://institution.example/independent/" + key,
                "--mode",
                "html",
            )
            if code != 0 or not isinstance(item, dict) or "id" not in item:
                self.check(key + " evidence import", False, item)
                continue
            ids[key] = item["id"]
            _, shown = self.cli(ws, "opportunity", "show", item["id"])
            deadline = shown["data"]["deadline"] or {}
            self.check(
                key + " preserves cutoff precision and timezone",
                (
                    deadline.get("value"),
                    deadline.get("precision"),
                    deadline.get("timezone"),
                )
                == (expected, precision, zone),
                deadline,
            )
            _, screen = self.cli(ws, "screen", item["id"])
            funding = [gate for gate in screen["gates"] if "fund" in gate["name"]]
            self.check(
                key + " funding remains unknown",
                len(funding) == 2
                and all(gate["state"] == "unknown" for gate in funding)
                and (key == "past_exact_visible" or screen["verdict"] == "unknown"),
                {
                    "funding": shown["data"]["funding"],
                    "gates": funding,
                    "verdict": screen["verdict"],
                },
            )
            if key == "past_exact_visible":
                self.check(
                    "past exact cutoff is expired",
                    screen["deadline"]["state"] == "expired",
                    screen["deadline"],
                )
            if key == "local_time":
                self.check(
                    "unlocated time retains raw evidence and uncertainty",
                    deadline.get("raw") == stamp
                    and screen["deadline"]["state"] == "unknown",
                    screen["deadline"],
                )
            if key == "salary_only":
                funding_data = shown["data"]["funding"]
                self.check(
                    "salary alone does not establish full funding",
                    funding_data is None
                    or funding_data.get("status") in {None, "unknown"},
                    funding_data,
                )
        if "precise_alone" in ids:
            self.application(ws, ids["precise_alone"])
        else:
            self.check("application fixture has imported evidence", False)
        calendar = self.root / "deadlines.ics"
        code, _ = self.cli(ws, "export", "calendar", "--out", str(calendar))
        self.check("calendar export succeeds", code == 0)
        ics = calendar.read_text(encoding="utf-8").replace("\n ", "")
        events = {}
        for block in ics.split("BEGIN:VEVENT")[1:]:
            lines = block.splitlines()
            url = next((line[4:] for line in lines if line.startswith("URL:")), None)
            if url:
                events[url.rsplit("/", 1)[-1]] = lines
        self.check(
            "calendar converts precise offsets to UTC",
            all(
                f"DTSTART:{future_year}0304T101500Z" in events.get(key, [])
                for key in ["precise_alone", "precise_visible"]
            ),
        )
        self.check(
            "calendar retains actual midnight",
            f"DTSTART:{future_year}0304T040000Z" in events.get("midnight_alone", []),
        )
        self.check(
            "calendar keeps dates as all-day events",
            all(
                f"DTSTART;VALUE=DATE:{future_year}0304" in events.get(key, [])
                for key in ["date_only", "midnight_visible"]
            ),
        )
        self.check(
            "calendar omits unknown and conflicting cutoffs",
            "local_time" not in events and "date_conflict" not in events,
        )

    def named_deadlines(self) -> None:
        ws = self.root / "named-deadline-workspace"
        code, _ = self.cli(ws, "init")
        self.check("named deadline fixture workspace initialises", code == 0)
        year = datetime.now(timezone.utc).year + 2
        weekday_date = datetime(year, 10, 27).strftime("%A, %d %B %Y")
        cases = [
            (
                "cet_parentheses",
                weekday_date + " (16:00 CET)",
                f"{year}-10-27T15:00:00+00:00",
                timedelta(hours=1),
            ),
            (
                "cet_summer",
                f"27 July {year} (16:00 CET)",
                f"{year}-07-27T15:00:00+00:00",
                timedelta(hours=1),
            ),
            (
                "cet_suffix",
                f"27 July {year} 16:00 CET",
                f"{year}-07-27T15:00:00+00:00",
                timedelta(hours=1),
            ),
            (
                "aoe_parentheses",
                f"31 December {year} (23:59 AoE)",
                f"{year + 1}-01-01T11:59:00+00:00",
                timedelta(hours=-12),
            ),
            (
                "aoe_comma_suffix",
                f"31 December {year}, 23:59 AoE",
                f"{year + 1}-01-01T11:59:00+00:00",
                timedelta(hours=-12),
            ),
            ("ambiguous_cst", f"27 July {year} (16:00 CST)", None, None),
        ]
        for key, raw, expected_utc, offset in cases:
            text = (
                "<html><h1>PhD in Cultural History "
                + key
                + "</h1><p>Doctoral research in cultural history. Please submit a CV.</p>"
                + "<p>Deadline: "
                + raw
                + "</p></html>"
            )
            file = self.fixture(key + ".html", text)
            code, item = self.cli(
                ws,
                "opportunity",
                "import",
                "--file",
                str(file),
                "--url",
                "https://institution.example/named-deadline/" + key,
                "--mode",
                "html",
            )
            if code != 0 or not isinstance(item, dict) or "id" not in item:
                self.check(key + " named deadline import", False, item)
                continue
            _, shown = self.cli(ws, "opportunity", "show", item["id"])
            deadline = shown["data"]["deadline"] or {}
            if expected_utc is None:
                _, screen = self.cli(ws, "screen", item["id"])
                passed = (
                    deadline.get("value") is None
                    and deadline.get("precision") == "unknown"
                    and deadline.get("timezone") is None
                    and deadline.get("raw") == raw
                    and screen["deadline"]["state"] == "unknown"
                )
            else:
                try:
                    value = datetime.fromisoformat(deadline["value"])
                    passed = (
                        deadline.get("precision") == "time"
                        and deadline.get("raw") == raw
                        and value.utcoffset() == offset
                        and value.astimezone(timezone.utc).isoformat() == expected_utc
                    )
                except (KeyError, TypeError, ValueError):
                    passed = False
            self.check(key + " preserves named timezone meaning", passed, deadline)
        calendar = self.root / "named-deadlines.ics"
        code, _ = self.cli(ws, "export", "calendar", "--out", str(calendar))
        self.check("named deadline calendar exports", code == 0)
        ics = calendar.read_text(encoding="utf-8").replace("\n ", "")
        events = {}
        for block in ics.split("BEGIN:VEVENT")[1:]:
            lines = block.splitlines()
            url = next((line[4:] for line in lines if line.startswith("URL:")), None)
            if url:
                events[url.rsplit("/", 1)[-1]] = lines
        for key, _raw, expected_utc, _offset in cases:
            if expected_utc is None:
                self.check(
                    "ambiguous named timezone has no calendar cutoff", key not in events
                )
            else:
                start = datetime.fromisoformat(expected_utc).strftime("%Y%m%dT%H%M%SZ")
                self.check(
                    key + " calendar contains exact UTC",
                    "DTSTART:" + start in events.get(key, []),
                    events.get(key),
                )

    def application(self, ws: Path, opportunity_id: str) -> None:
        code, app = self.cli(
            ws, "application", "create", opportunity_id, "--documents", "cv"
        )
        self.check(
            "new packet is preparing", code == 0 and app.get("status") == "preparing"
        )
        app_id = app["id"]
        _, verification = self.cli(ws, "application", "verify", app_id)
        self.check(
            "unfinished packet verification fails",
            verification.get("state") == "fail",
            verification,
        )
        for status in ["drafted", "submitted"]:
            code, _ = self.cli(
                ws,
                "application",
                "status",
                app_id,
                status,
                "--note",
                "Synthetic negative gate probe; no real submission",
                "--allow-unknown",
            )
            self.check("unfinished packet cannot become " + status, code != 0)
        _, apps = self.cli(ws, "application", "list")
        actual = next(row for row in apps if row["id"] == app_id)
        self.check(
            "failed transitions preserve preparing",
            actual["status"] == "preparing" and actual["data"]["submission"] is None,
        )
        packet = ws / app["data"]["directory"]
        (packet / "cv.md").write_text(
            "# Research CV\n\nDoctoral research on historical archives.\n",
            encoding="utf-8",
        )
        requirements = json.loads(
            (packet / "requirements.json").read_text(encoding="utf-8")
        )
        requirements["source_quote"] = "Please submit a CV."
        write_json(packet / "requirements.json", requirements)
        write_json(
            packet / "claims.json",
            {
                "schema_version": 1,
                "coverage_reviewed": True,
                "claims": [
                    {
                        "file": "cv.md",
                        "text": "Doctoral research on historical archives.",
                        "profile_refs": [],
                        "posting_quotes": ["Doctoral research on historical archives."],
                        "external_evidence": [],
                    }
                ],
            },
        )
        code, verification = self.cli(ws, "application", "verify", app_id)
        failures = [
            row["name"] for row in verification["checks"] if row["state"] == "fail"
        ]
        self.check(
            "review alone blocks mechanically grounded fixture",
            code == 1 and failures == ["review"],
            failures,
        )
        code, _ = self.cli(
            ws,
            "application",
            "status",
            app_id,
            "drafted",
            "--note",
            "Synthetic negative review probe",
            "--allow-unknown",
        )
        self.check("allow-unknown cannot bypass missing review", code != 0)
        review = json.loads((packet / "review.json").read_text(encoding="utf-8"))
        review.update(
            {
                "reviewer": "Independent synthetic fixture reviewer; same-agent mechanical critical pass",
                "verdict": "approved",
                "document_hashes": {
                    "cv.md": hashlib.sha256((packet / "cv.md").read_bytes()).hexdigest()
                },
                "support_hashes": {
                    name: hashlib.sha256((packet / name).read_bytes()).hexdigest()
                    for name in ["requirements.json", "claims.json"]
                },
                "claims_semantically_checked": True,
                "requirements_checked": True,
                "source_integrity_checked": True,
                "visual_pdf_checked": False,
                "findings": [],
                "limitations": [
                    "Synthetic quoted programme fragment tests lifecycle gates; not a real candidate CV or academic quality review."
                ],
            }
        )
        write_json(packet / "review.json", review)
        code, drafted = self.cli(
            ws,
            "application",
            "status",
            app_id,
            "drafted",
            "--note",
            "Synthetic fixture review; acknowledge unresolved eligibility only",
            "--allow-unknown",
        )
        self.check(
            "reviewed fixture reaches drafted with unknown acknowledgement",
            code == 0
            and isinstance(drafted, dict)
            and drafted.get("status") == "drafted",
        )
        review["verdict"] = "pending"
        write_json(packet / "review.json", review)
        code, _ = self.cli(
            ws,
            "application",
            "status",
            app_id,
            "submitted",
            "--note",
            "Negative synthetic probe; no real submission",
            "--allow-unknown",
        )
        self.check("submission rechecks revoked review from drafted", code != 0)
        _, apps = self.cli(ws, "application", "list")
        actual = next(row for row in apps if row["id"] == app_id)
        self.check(
            "revoked review preserves drafted without archive",
            actual["status"] == "drafted" and actual["data"]["submission"] is None,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, help="Write complete fixture, command and result JSON"
    )
    args = parser.parse_args()
    initial_hashes = source_hashes()
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            target = urlsplit(self.path)
            status, content_type = 200, "text/html"
            if target.path == "/robots.txt":
                content_type = "text/plain"
                if target.hostname in {"9.9.9.9", "208.67.220.220"}:
                    body = CHALLENGE
                    if target.hostname == "9.9.9.9":
                        content_type = "text/html"
                elif target.hostname == "1.1.1.1":
                    body = "User-agent: *\nDisallow: /\n"
                elif target.hostname == "1.0.0.1":
                    status, body = 404, "Missing"
                elif target.hostname == "208.67.222.222":
                    body = ""
                else:
                    body = "User-agent: *\nAllow: /\n"
            else:
                body = {
                    "/login-required": LOGIN,
                    "/long-login": LONG_LOGIN,
                    "/challenge": CHALLENGE,
                    "/challenge-list": CHALLENGE,
                    "/list": '<html><h1>Vacancies</h1><a href="/login-required">PhD vacancy</a></html>',
                    "/advert": ADVERT,
                }.get(target.path)
                if body is None:
                    status, body = 404, "No local fixture; this proxy never forwards"
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.lower().endswith("_proxy")
    }
    proxy = "http://127.0.0.1:" + str(server.server_port)
    env.update(
        {
            "http_proxy": proxy,
            "HTTP_PROXY": proxy,
            "https_proxy": proxy,
            "HTTPS_PROXY": proxy,
            "no_proxy": "",
            "NO_PROXY": "",
        }
    )
    try:
        with tempfile.TemporaryDirectory(prefix="phd-independent-") as directory:
            run = Check(Path(directory), env)
            run.fixtures.update(
                {
                    "short-login.html": LOGIN,
                    "long-login.html": LONG_LOGIN,
                    "challenge.html": CHALLENGE,
                    "real-advert.html": ADVERT,
                }
            )
            for name, suite in [
                ("HTTP suite completes", lambda: run.http(requests)),
                ("semantic suite completes", run.semantic),
                ("named deadline suite completes", run.named_deadlines),
            ]:
                try:
                    suite()
                except (
                    OSError,
                    ValueError,
                    KeyError,
                    TypeError,
                    StopIteration,
                    subprocess.SubprocessError,
                ) as exc:
                    run.check(name, False, f"{type(exc).__name__}: {exc}")
            run.check(
                "production source snapshot remains stable",
                initial_hashes == source_hashes(),
            )
            failed = sum(row["status"] == "FAIL" for row in run.checks)
            report = {
                "status": "FAIL" if failed else "PASS",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "repository": str(REPO),
                "python": sys.version,
                "network": "Local non-forwarding proxy only; literal public IP targets avoid external DNS queries.",
                "limitations": [
                    "Synthetic fixtures; no live portals or personal CV.",
                    "No PDF engine, scientific-fit evaluation or actual submission exercised.",
                ],
                "checks": run.checks,
                "commands": run.commands,
                "fixtures": run.fixtures,
                "requests": requests,
                "source_sha256": initial_hashes,
            }
            if args.out:
                write_json(args.out, report)
            print(
                json.dumps(
                    {
                        "status": report["status"],
                        "passed": len(run.checks) - failed,
                        "failed": failed,
                        "checks": [
                            {"name": row["name"], "status": row["status"]}
                            for row in run.checks
                        ],
                        "report": str(args.out.resolve()) if args.out else None,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1 if failed else 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
