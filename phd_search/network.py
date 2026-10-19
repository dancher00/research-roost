from __future__ import annotations

import ipaddress
import json
import re
import socket
import time
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote_to_bytes, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

from . import __version__
from .core import Error, atomic_write, canonical_url, digest, json_text, now

# Keep the existing product token so a rename does not change robots selection.
USER_AGENT = f"phd-search/{__version__} (Research Roost; +personal doctoral opportunity research; GET-only)"
MAX_BYTES = 8 * 1024 * 1024
VALIDATORS = {"if-none-match", "if-modified-since"}


def _robots_path(value: str) -> str:
    """Compare URI octets without turning an encoded reserved character into syntax."""
    unreserved = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    def escaped(match):
        char = chr(int(match[0][1:], 16))
        return char if char in unreserved else match[0].upper()
    value = re.sub(r"%[0-9a-fA-F]{2}", escaped, value)
    return "".join(char if ord(char) < 128 else "".join(f"%{byte:02X}" for byte in char.encode("utf-8")) for char in value)


class RobotsPolicy:
    """Own group selection and rule precedence; stdlib's first-match gate is unsuitable."""

    def __init__(self, text: str):
        self.groups = []
        group = None
        has_directives = False
        for raw in text.removeprefix("\ufeff").splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            field, value = (part.strip() for part in line.split(":", 1))
            field = field.casefold()
            if field == "user-agent" and value:
                if group is None or has_directives:
                    group = {"agents": [], "rules": [], "delay": 0}
                    self.groups.append(group)
                    has_directives = False
                group["agents"].append(value.casefold())
            elif group is not None and field in {"allow", "disallow", "crawl-delay"}:
                has_directives = True
                if field == "crawl-delay":
                    if re.fullmatch(r"\d+(?:\.\d+)?", value):
                        group["delay"] = max(group["delay"], float(value))
                elif value:
                    group["rules"].append((value, field == "allow"))

    def matching_groups(self, user_agent: str) -> list[dict]:
        token = user_agent.split("/", 1)[0].casefold()
        matches = [(len(agent), group) for group in self.groups for agent in group["agents"] if agent != "*" and agent in token]
        if matches:
            longest = max(length for length, _ in matches)
            return [group for group in self.groups if any(length == longest and candidate is group for length, candidate in matches)]
        return [group for group in self.groups if "*" in group["agents"]]

    def crawl_delay(self, user_agent: str) -> float:
        return max((group["delay"] for group in self.matching_groups(user_agent)), default=0)

    def allows(self, url: str, user_agent: str = USER_AGENT) -> bool:
        return _robots_rules_allowed([rule for group in self.matching_groups(user_agent) for rule in group["rules"]], url)


def _robots_rules_allowed(rules: list[tuple[str, bool]], url: str) -> bool:
    parts = urlsplit(url)
    path = _robots_path(parts.path + (("?" + parts.query) if parts.query else ""))
    matches = []
    for raw, allowance in rules:
        if not raw:
            continue
        pattern = _robots_path(raw)
        final = pattern.endswith("$")
        expression = "^" + re.escape(pattern[:-1] if final else pattern).replace(r"\*", ".*") + ("$" if final else "")
        if re.search(expression, path):
            specificity = len(unquote_to_bytes(raw.replace("*", "").removesuffix("$")))
            matches.append((specificity, allowance))
    # Allow wins when matching rules have equal specificity.
    return max(matches, default=(0, True))[1]


@dataclass
class Response:
    url: str
    body: bytes
    content_type: str
    headers: dict
    fetched_at: str
    cached: bool = False
    requested_url: str | None = None

    @property
    def text(self) -> str:
        match = re.search(r"charset=([^;\s]+)", self.content_type, re.I)
        charset = match.group(1).strip('"') if match else "utf-8"
        try:
            return self.body.decode(charset, "replace")
        except LookupError:
            return self.body.decode("utf-8", "replace")


class Redirects(HTTPRedirectHandler):
    def __init__(self, client):
        self.client = client

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        newurl = canonical_url(urljoin(req.full_url, newurl))
        self.client.check_address(newurl)
        if not self.client.reading_robots:
            self.client.check_robots(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            context = getattr(req, "_phd_request_context", None)
            if canonical_url(req.full_url) != newurl:
                for name, _ in redirected.header_items():
                    if name.casefold() in VALIDATORS:
                        redirected.remove_header(name)
                if context is not None:
                    context["conditional_url"] = None
            redirected._phd_request_context = context
        return redirected


class Client:
    """Bounded GET transport. Robots, redirects, timeouts, caching and rate limits share one owner."""

    def __init__(self, root: Path, *, timeout: float = 18, interval: float = 1.0, allow_private: bool = False):
        self.root = root
        self.timeout = timeout
        self.interval = interval
        self.allow_private = allow_private  # injection point for local HTTP fixture tests only
        self.robots = {}
        self.last_request = {}
        self.reading_robots = False
        self.opener = build_opener(Redirects(self))

    def check_address(self, url: str) -> None:
        parts = urlsplit(canonical_url(url))
        if self.allow_private:
            return
        try:
            addresses = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except OSError as exc:
            raise Error(f"DNS lookup failed for {parts.hostname}: {exc}") from exc
        if any(not ipaddress.ip_address(addr[4][0]).is_global for addr in addresses):
            raise Error("Remote sources must resolve to public network addresses; use import for local evidence")

    def check_robots(self, url: str) -> None:
        p = urlsplit(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in self.robots:
            self.reading_robots = True
            try:
                try:
                    response = self._request(origin + "/robots.txt", {})
                    policy_text = response.text
                    meaningful = "\n".join(line for line in policy_text.splitlines() if not line.lstrip().startswith("#")).strip()
                    sniffed = re.sub(r"<!--.*?-->", "", meaningful, flags=re.S).removeprefix("\ufeff").strip()
                    if meaningful and ("html" in response.content_type.casefold() or re.search(r"(?im)^\s*<(?:!doctype\b|[a-z][\w:-]*(?:\s|>))", sniffed)):
                        raise Error(f"Cannot establish robots policy for {origin}: received an HTML page or browser challenge")
                    parser = RobotsPolicy(policy_text)
                except HTTPError as exc:
                    if exc.code in {404, 410}:
                        parser = RobotsPolicy("User-agent: *\nAllow: /\n")
                    else:
                        raise Error(f"Cannot establish robots policy for {origin}: HTTP {exc.code}") from exc
            finally:
                self.reading_robots = False
            self.robots[origin] = parser
        parser = self.robots[origin]
        if not self._wildcard_allowed(parser, url):
            raise Error(f"robots.txt disallows this URL: {url}")

    @staticmethod
    def _wildcard_allowed(parser: RobotsPolicy | RobotFileParser, url: str) -> bool:
        if isinstance(parser, RobotsPolicy):
            return parser.allows(url)
        # Accept an injected stdlib parser used by older audit/fixture callers.
        if parser.disallow_all:
            return False
        if parser.allow_all:
            return True
        groups = [entry for entry in parser.entries if entry.applies_to(USER_AGENT)]
        if not groups and parser.default_entry:
            groups = [parser.default_entry]
        return _robots_rules_allowed([(rule.path, rule.allowance) for entry in groups for rule in entry.rulelines], url)

    def _request(self, url: str, headers: dict) -> Response:
        self.check_address(url)
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        robots = self.robots.get(origin)
        delay = max(self.interval, (robots.crawl_delay(USER_AGENT) or 0) if robots else 0)
        if delay > 30:
            raise Error(f"Source requires a {delay}s crawl delay; use a saved page or a slower external feed")
        wait = delay - (time.monotonic() - self.last_request.get(origin, 0))
        if wait > 0:
            time.sleep(wait)
        self.last_request[origin] = time.monotonic()
        req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json,application/rss+xml,application/atom+xml,application/pdf;q=0.8,*/*;q=0.2", "Accept-Encoding": "identity", **headers})
        context = {"conditional_url": url if any(name.casefold() in VALIDATORS for name in headers) else None}
        req._phd_request_context = context
        try:
            response = self.opener.open(req, timeout=self.timeout)
        except HTTPError as exc:
            exc._phd_conditional_url = context["conditional_url"]
            raise
        with response:
            size = response.headers.get("Content-Length")
            if size:
                try:
                    length = int(size)
                except ValueError as exc:
                    raise Error("Invalid response Content-Length") from exc
                if length < 0:
                    raise Error("Invalid response Content-Length")
                if length > MAX_BYTES:
                    raise Error(f"Response exceeds {MAX_BYTES} bytes")
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise Error(f"Response exceeds {MAX_BYTES} bytes")
            encoding = response.headers.get("Content-Encoding", "identity")
            if encoding not in {"identity", ""}:
                raise Error(f"Unexpected content encoding {encoding}; source did not honour identity encoding")
            return Response(canonical_url(response.url), body, response.headers.get("Content-Type", ""), dict(response.headers.items()), now(), requested_url=url)

    def get(self, url: str, *, refresh: bool = False) -> Response:
        try:
            url = canonical_url(url)
        except ValueError as exc:
            raise Error(f"Invalid source URL: {exc}") from exc
        cache = self.root / "cache" / digest(url)
        metadata_path = cache.with_suffix(".json")
        body_path = cache.with_suffix(".body")
        old = None
        if metadata_path.exists() and body_path.exists():
            try:
                old = json.loads(metadata_path.read_text())
                if (not isinstance(old, dict) or not all(isinstance(old.get(key), str) for key in ("url", "sha256", "content_type"))
                        or canonical_url(old["url"]) != old["url"] or digest(body_path.read_bytes()) != old["sha256"]):
                    old = None
            except (Error, ValueError, OSError, KeyError, RecursionError):
                old = None
        headers = {}
        # Validators belong to the cached final representation, not a redirecting alias.
        if old and not refresh and old["url"] == url:
            for field, header in (("etag", "If-None-Match"), ("last_modified", "If-Modified-Since")):
                value = old.get(field)
                if isinstance(value, str) and value and "\r" not in value and "\n" not in value:
                    headers[header] = value
        try:
            self.check_robots(url)
            for attempt in range(3):
                try:
                    response = self._request(url, headers)
                    break
                except HTTPError as exc:
                    if exc.code == 304:
                        if (old and headers and canonical_url(exc.geturl()) == old["url"]
                                and getattr(exc, "_phd_conditional_url", None) == old["url"]):
                            body = body_path.read_bytes()
                            if digest(body) != old["sha256"]:
                                raise Error("Cached response changed during revalidation") from exc
                            return Response(old["url"], body, old["content_type"], {}, now(), True, url)
                        raise Error("HTTP 304 did not revalidate the same cached resource with its validators") from exc
                    if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                        raise
                    retry = exc.headers.get("Retry-After", "")
                    if retry.isdigit() and int(retry) > 30:
                        raise Error(f"Source asks to retry after {retry}s; try again later") from exc
                    time.sleep(int(retry) if retry.isdigit() else 2 ** attempt)
        except (HTTPError, URLError, TimeoutError, OSError, HTTPException, ValueError) as exc:
            raise Error(f"Fetch failed for {url}: {exc}") from exc
        lowered = {k.lower(): v for k, v in response.headers.items()}
        atomic_write(body_path, response.body)
        atomic_write(metadata_path, json_text({"url": response.url, "content_type": response.content_type,
                     "sha256": digest(response.body), "etag": lowered.get("etag"), "last_modified": lowered.get("last-modified"),
                     "fetched_at": response.fetched_at}))
        return response
