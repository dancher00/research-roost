from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlsplit

from .core import (
    Error,
    atomic_write,
    canonical_url,
    json_text,
    now,
    read_json,
    resource,
)
from .evidence import check_html_access, ingest_response
from .extract import MAX_DATA_DEPTH, discover, parse_source_json
from .network import Client
from .store import Store


def validate_source(source: dict) -> None:
    if not isinstance(source, dict) or not isinstance(source.get("id"), str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", source["id"]):
        raise Error("Source id must be a lowercase slug, max 64 characters")
    if not isinstance(source.get("kind"), str) or source["kind"] not in {"html", "rss", "json", "discovery"}:
        raise Error("Source kind must be html, rss, json or discovery")
    canonical_url(source.get("url", "").replace("{query}", "test").replace("{page}", "1"))
    if source["kind"] == "html":
        try:
            pattern = source.get("link_pattern", "")
            if not pattern or len(pattern) > 500:
                raise Error("HTML source requires a bounded link_pattern")
            re.compile(pattern)
        except re.error as exc:
            raise Error(f"Invalid link_pattern: {exc}") from exc
    if source["kind"] == "json":
        for field in ("items_path", "url_field", "title_field"):
            if not isinstance(source.get(field), str):
                raise Error(f"JSON source requires {field}")
    if not isinstance(source.get("enabled", True), bool):
        raise Error("Source enabled must be boolean")
    if "families" in source and (not isinstance(source["families"], list) or not source["families"]
                                or any(not isinstance(item, str) or item not in {"phd", "internship", "school"} for item in source["families"])):
        raise Error("Source families must be a nonempty array of phd, internship or school")


def load_sources(root: Path) -> list[dict]:
    value = read_json(root / "sources.json")
    if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("sources"), list):
        raise Error("sources.json requires schema_version: 1 and a sources array")
    seen = set()
    for source in value["sources"]:
        validate_source(source)
        if source["id"] in seen:
            raise Error(f"Duplicate source ID: {source['id']}")
        seen.add(source["id"])
    return value["sources"]


def add_source(root: Path, source: dict) -> dict:
    validate_source(source)
    sources = load_sources(root)
    if any(item["id"] == source["id"] for item in sources):
        raise Error("Source already exists; edit sources.json explicitly")
    sources.append(source)
    atomic_write(root / "sources.json", json_text({"schema_version": 1, "sources": sources}))
    return source


def install_builtins(root: Path) -> dict:
    configured = load_sources(root)
    present = {item["id"]: item for item in configured}
    shipped = read_json(resource("sources.example.json"))["sources"]
    added = []
    metadata_updated = []
    for item in shipped:
        validate_source(item)
        if item["id"] not in present:
            configured.append(item)
            present[item["id"]] = item
            added.append(item["id"])
        else:
            existing = present[item["id"]]
            if "families" not in existing and item.get("families") and all(existing.get(key) == item.get(key) for key in ("url", "kind")):
                existing["families"] = list(item["families"])
                metadata_updated.append(item["id"])
    if added or metadata_updated:
        atomic_write(root / "sources.json", json_text({"schema_version": 1, "sources": configured}))
    return {"added": added, "family_metadata_added": metadata_updated, "existing_sources_preserved": True, "sources": len(configured)}


def path_value(value, path: str):
    for segment in path.split(".") if path else []:
        if isinstance(value, dict):
            value = value.get(segment)
        elif isinstance(value, list) and segment.isdigit() and int(segment) < len(value):
            value = value[int(segment)]
        else:
            return None
    return value


def feed_links(markup: str, url: str) -> list[dict]:
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", markup, re.I):
        raise Error("RSS/Atom must not contain DTD or entity declarations")
    try:
        tree = ET.fromstring(markup)
    except ET.ParseError as exc:
        raise Error(f"Invalid RSS/Atom XML: {exc}") from exc
    pending = [(tree, 0)]
    while pending:
        node, depth = pending.pop()
        if depth > MAX_DATA_DEPTH:
            raise Error("RSS/Atom exceeds the supported nesting depth")
        pending.extend((child, depth + 1) for child in node)
    links = []
    for item in tree.iter():
        if item.tag.rsplit("}", 1)[-1] not in {"item", "entry"}:
            continue
        title, link = "", None
        for child in item:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "title":
                title = "".join(child.itertext()).strip()
            if tag == "link" and child.attrib.get("rel", "alternate") == "alternate":
                link = child.attrib.get("href") or child.text
        if link:
            try:
                links.append({"url": canonical_url(urljoin(url, link.strip())), "title": title})
            except (Error, ValueError):
                continue
    return links


def source_page(client: Client, source: dict, query: str, page: int = 1) -> tuple[list[dict], str | None, dict]:
    url = source["url"].replace("{query}", quote_plus(query)).replace("{page}", str(page))
    response = client.get(url)
    if source["kind"] == "html":
        check_html_access(response.text, headers=response.headers)
        links, next_url = discover(response.text, response.url, source["link_pattern"])
    elif source["kind"] == "rss":
        links, next_url = feed_links(response.text, response.url), None
    elif source["kind"] == "json":
        payload = parse_source_json(response.text)
        items = path_value(payload, source["items_path"])
        if not isinstance(items, list):
            raise Error("Source items_path did not resolve to an array")
        links = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise Error(f"Source JSON item {index} must be an object")
            link = path_value(item, source["url_field"])
            title = path_value(item, source["title_field"])
            if link is not None and not isinstance(link, str):
                raise Error(f"Source JSON item {index} URL must be a string or null")
            if title is not None and not isinstance(title, str):
                raise Error(f"Source JSON item {index} title must be a string or null")
            if isinstance(link, str):
                try:
                    posting_url = canonical_url(urljoin(response.url, link))
                except ValueError as exc:
                    raise Error(f"Source JSON item {index} contains an invalid posting URL: {exc}") from exc
                links.append({"url": posting_url, "title": title if isinstance(title, str) else ""})
        next_url = None
    else:
        raise Error("Discovery-only sources provide search links for an agent/browser; they do not claim an automated adapter")
    return links, next_url, {"url": response.url, "fetched_at": response.fetched_at, "bytes": len(response.body), "query_mode": "remote" if "{query}" in source["url"] else "local"}


def scrape(store: Store, client: Client, *, sources: list[str] | None, query: str, limit: int, pages: int,
           family: str | None = None) -> dict:
    if not 1 <= limit <= 100 or not 1 <= pages <= 10:
        raise Error("limit must be 1–100 and pages 1–10")
    configured = load_sources(store.root)
    if family not in {None, "phd", "internship", "school"}:
        raise Error("Source family must be phd, internship or school")
    if sources:
        missing = set(sources) - {x["id"] for x in configured}
        if missing:
            raise Error("Unknown sources: " + ", ".join(sorted(missing)))
    reports = []
    matches = []
    global_seen = set()
    for source in configured:
        if sources and source["id"] not in sources or not sources and not source.get("enabled", True):
            continue
        if family and source.get("families") and family not in source["families"]:
            if sources:
                raise Error(f"Source {source['id']} does not cover the selected family {family}")
            continue
        report = {"source": source["id"], "pages": [], "discovered": 0, "attempted": 0, "stored": [], "matches": [], "errors": [],
                  "coverage": "bounded_sample", "not_an_exhaustive_search": True}
        reports.append(report)
        if source["kind"] == "discovery":
            report.update(status="browser_required", url=source["url"].replace("{query}", quote_plus(query)),
                          reason=source.get("notes", "No automated adapter configured"))
            continue
        current = dict(source)
        visited_pages = set()
        for page in range(1, pages + 1):
            try:
                links, next_url, metadata = source_page(client, current, query, page)
                if metadata["url"] in visited_pages:
                    break
                visited_pages.add(metadata["url"])
                report["pages"].append(metadata)
                report["discovered"] += len(links)
                if not links:
                    report["errors"].append({"stage": "discovery", "message": "No posting links found; page may be empty, changed, or require a browser"})
                for link in links:
                    if report["attempted"] >= limit:
                        break
                    if link["url"] in global_seen:
                        continue
                    global_seen.add(link["url"])
                    report["attempted"] += 1
                    try:
                        response = client.get(link["url"])
                        requested = canonical_url(link["url"])
                        actual = urlsplit(canonical_url(response.url))
                        expected = urlsplit(requested)
                        if (actual.scheme, actual.netloc, actual.path.rstrip("/"), actual.query) != (expected.scheme, expected.netloc, expected.path.rstrip("/"), expected.query):
                            raise Error(f"Posting redirected to a different page; original identity is not established: {requested} → {response.url}")
                        if source["kind"] == "html" and not re.search(source["link_pattern"], response.url):
                            raise Error("Final response is not a posting URL for the configured source")
                        record = ingest_response(store, response, source=source["id"])
                        report["stored"].append(record["id"])
                        haystack = (record["data"]["title"] + " " + record["data"]["description"]).casefold()
                        if not query or query.casefold() in haystack:
                            report["matches"].append(record["id"])
                            matches.append({"id": record["id"], "title": record["data"]["title"], "url": record["url"]})
                    except Error as exc:
                        report["errors"].append({"stage": "detail", "url": link["url"], "message": str(exc)})
                if report["attempted"] >= limit:
                    break
                if next_url:
                    if urlsplit(next_url).netloc != urlsplit(source["url"]).netloc:
                        raise Error("Pagination left the configured source host")
                    current["url"] = next_url
                elif "{page}" not in source["url"]:
                    break
            except Error as exc:
                report["errors"].append({"stage": "listing", "message": str(exc)})
                break
        report["status"] = "partial" if report["errors"] else "ok"
    result = {"query": query, "family": family, "sources": reports, "matches": matches, "created_at": now()}
    store.log_run("scrape", result)
    return result


def health(root: Path, client: Client, ids: list[str] | None = None) -> list[dict]:
    results = []
    configured = load_sources(root)
    missing = set(ids or []) - {source["id"] for source in configured}
    if missing:
        raise Error("Unknown sources: " + ", ".join(sorted(missing)))
    for source in configured:
        if ids and source["id"] not in ids:
            continue
        if source["kind"] == "discovery":
            results.append({"id": source["id"], "state": "browser_required", "notes": source.get("notes")})
            continue
        try:
            links, _, metadata = source_page(client, source, "", 1)
            results.append({"id": source["id"], "state": "ok" if links else "no_links", "links": len(links), **metadata})
        except Error as exc:
            results.append({"id": source["id"], "state": "unavailable", "reason": str(exc), "checked_at": now()})
    return results
