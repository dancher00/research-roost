from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .core import Error, canonical_url
from .vendor.posting_guard import guard

MAX_DATA_DEPTH = 30


def parse_source_json(text: str, *, label: str = "source JSON"):
    """Reject malformed, nonfinite and excessively nested external JSON at entry."""
    def invalid_constant(value):
        raise ValueError(f"Nonfinite number {value}")
    try:
        value = json.loads(text, parse_constant=invalid_constant)
    except (ValueError, RecursionError) as exc:
        raise Error(f"Invalid {label}: {exc}") from exc
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > MAX_DATA_DEPTH:
            raise Error(f"{label} exceeds the supported nesting depth ({MAX_DATA_DEPTH})")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, float) and not math.isfinite(item):
            raise Error(f"Invalid {label}: nonfinite number")
    return value


def _jobposting(item: dict) -> bool:
    kind = item.get("@type")
    if kind is None:
        return False
    if isinstance(kind, str):
        return kind == "JobPosting"
    if isinstance(kind, list) and all(isinstance(value, str) for value in kind):
        return "JobPosting" in kind
    raise Error("JSON-LD @type must be a string or an array of strings")


def _text_field(value, field: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise Error(f"JobPosting.{field} must be a string or null")
    return value


def _named_field(value, field: str) -> str | None:
    if isinstance(value, dict):
        return _text_field(value.get("name"), field + ".name")
    return _text_field(value, field)


def _job_location(value) -> dict:
    if value is None:
        return {}
    locations = value if isinstance(value, list) else [value]
    addresses = []
    for location in locations:
        if not isinstance(location, dict):
            raise Error("JobPosting.jobLocation must contain location objects")
        address = location.get("address")
        if address is None or isinstance(address, str):
            addresses.append({})
            continue
        if not isinstance(address, dict):
            raise Error("JobPosting.jobLocation.address must be an object, string or null")
        _named_field(address.get("addressCountry"), "jobLocation.address.addressCountry")
        _text_field(address.get("addressLocality"), "jobLocation.address.addressLocality")
        addresses.append(address)
    return addresses[0] if addresses else {}


class Page(HTMLParser):
    def __init__(self, markup: str):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.metadata = {}
        self.jsonld = []
        self.title = ""
        self.h1 = ""
        self._anchor = None
        self._script = None
        self._capture = None
        self.feed(markup)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "a" and attrs.get("href"):
            self._anchor = {"url": attrs["href"], "title": "", "rel": attrs.get("rel", "")}
        if tag in {"title", "h1"}:
            self._capture = tag
        if tag == "meta" and attrs.get("content"):
            self.metadata[attrs.get("property", attrs.get("name", ""))] = attrs["content"]
        if tag == "script" and attrs.get("type", "").lower() == "application/ld+json":
            self._script = []

    def handle_data(self, data):
        if self._anchor is not None:
            self._anchor["title"] += data
        if self._capture:
            setattr(self, self._capture, getattr(self, self._capture) + data)
        if self._script is not None:
            self._script.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._anchor is not None:
            self._anchor["title"] = " ".join(self._anchor["title"].split())
            self.links.append(self._anchor)
            self._anchor = None
        if tag == self._capture:
            self._capture = None
        if tag == "script" and self._script is not None:
            self.jsonld.append(parse_source_json("".join(self._script), label="JSON-LD"))
            self._script = None


def jsonld_objects(value, depth=0):
    if depth > MAX_DATA_DEPTH:
        raise Error("JSON-LD exceeds the supported nesting depth")
    if isinstance(value, list):
        for child in value:
            yield from jsonld_objects(child, depth + 1)
    elif isinstance(value, dict):
        yield value
        for key in ("@graph", "itemListElement", "item", "mainEntity"):
            if key in value:
                yield from jsonld_objects(value[key], depth + 1)


def _deadline_zone(name: str):
    # Explicit abbreviations specify an offset, not a region's seasonal rules.
    offsets = {"UTC": 0, "GMT": 0, "CET": 1, "CEST": 2, "AOE": -12}
    if name.upper() in offsets:
        return timezone(timedelta(hours=offsets[name.upper()]), name)
    return ZoneInfo(name)


def parse_deadline(raw: str | None, zone: str | None = None) -> dict | None:
    if raw is not None and not isinstance(raw, str):
        raise Error("Deadline must be a string or null")
    if zone is not None and not isinstance(zone, str):
        raise Error("Deadline timezone must be a string or null")
    if not raw:
        return None
    result = {"raw": raw, "value": None, "timezone": zone, "precision": "unknown"}
    text = raw.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            date.fromisoformat(text)
            result.update(value=text, precision="date")
            return result
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo:
            result.update(value=parsed.isoformat(), precision="time", timezone=zone or str(parsed.tzinfo))
            return result
        if zone:
            parsed = parsed.replace(tzinfo=_deadline_zone(zone))
            result.update(value=parsed.isoformat(), precision="time")
            return result
        result.update(local_value=parsed.isoformat(), reason="time_without_timezone")
        return result
    except (ValueError, ZoneInfoNotFoundError):
        pass
    # English month names are parsed without depending on the machine locale.
    months = {name: i for i, name in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
    match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3})[A-Za-z]*\s+(\d{4})", text, re.I)
    if match and match[2].lower() in months:
        try:
            d = date(int(match[3]), months[match[2].lower()], int(match[1]))
            tail = text[match.end():].strip()
            clock = re.search(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b", tail)
            if clock:
                suffix = tail[clock.end():].strip(" \t()[],;.")
                tz = zone or suffix or None
                parsed = datetime(d.year, d.month, d.day, int(clock[1]), int(clock[2]), int(clock[3] or 0))
                result.update(local_value=parsed.isoformat(), timezone=tz)
                if tz:
                    parsed = parsed.replace(tzinfo=_deadline_zone(tz))
                    result.update(value=parsed.isoformat(), timezone=tz, precision="time")
                    result.pop("local_value")
                else:
                    result.update(reason="time_without_timezone")
            else:
                # A date-only zone may appear in parentheses. A clock is never
                # treated as a zone or silently reduced to an all-day date.
                date_zone = re.fullmatch(r"\(([^)]+)\)", tail)
                tz = zone or (date_zone[1] if date_zone else None)
                result.update(value=d.isoformat(), timezone=tz, precision="date")
        except (ValueError, ZoneInfoNotFoundError):
            pass
    return result


def deadline_state(deadline: dict | None, at: datetime | None = None) -> dict:
    at = at or datetime.now(timezone.utc)
    if not deadline or not deadline.get("value"):
        return {"state": "unknown", "days": None, "precision": "unknown"}
    value = deadline["value"]
    if deadline.get("precision") == "time":
        instant = datetime.fromisoformat(value)
        if instant.tzinfo is None:
            return {"state": "unknown", "days": None, "precision": "time_without_timezone"}
        days = (instant - at).total_seconds() / 86400
        return {"state": "expired" if days < 0 else "urgent" if days <= 7 else "open", "days": round(days, 2), "precision": "time"}
    d = date.fromisoformat(value[:10])
    days = (d - at.date()).days
    if deadline.get("timezone"):
        try:
            end = datetime.combine(d + timedelta(days=1), datetime.min.time(), ZoneInfo(deadline["timezone"]))
            expired = at >= end
        except ZoneInfoNotFoundError:
            expired = at > datetime.combine(d + timedelta(days=1), datetime.min.time(), timezone.utc) + timedelta(hours=12)
    else:
        # Last possible end-of-day (UTC-12), not a fabricated midnight UTC cutoff.
        expired = at >= datetime.combine(d + timedelta(days=1), datetime.min.time(), timezone.utc) + timedelta(hours=12)
    return {"state": "expired" if expired else "urgent" if days <= 7 else "open", "days": days,
            "precision": "date", "timezone_known": bool(deadline.get("timezone"))}


def extract(markup: str, url: str, *, mode: str = "html") -> tuple[dict, str, dict]:
    cleaned, findings = guard(markup, mode)
    page = Page(markup) if mode == "html" else None
    jobs = [x for block in (page.jsonld if page else []) for x in jsonld_objects(block) if _jobposting(x)]
    if len(jobs) > 1:
        raise Error("Page contains several JobPosting records; import a specific posting instead of a listing page")
    job = jobs[0] if jobs else {}
    description = _text_field(job.get("description"), "description")
    if isinstance(description, str):
        description = guard(description, "html")[0]
    else:
        description = cleaned
    structured_title = _text_field(job.get("title"), "title")
    title = structured_title or (page.h1.strip() or page.metadata.get("og:title") or page.title.strip() if page else None)
    if not title:
        title = next((line.strip() for line in cleaned.splitlines() if line.strip()), "Untitled opportunity")[:300]
    address = _job_location(job.get("jobLocation"))
    country = _named_field(address.get("addressCountry"), "jobLocation.address.addressCountry")
    institution = _named_field(job.get("hiringOrganization"), "hiringOrganization")
    deadline = parse_deadline(job.get("validThrough"))
    deadline_candidates = [{"origin": "structured", **deadline}] if deadline else []
    provenance = {"title": {"source": url, "locator": "JSON-LD.title" if job.get("title") else "page heading", "quote": title}}
    if job.get("validThrough"):
        provenance["deadline"] = {"source": url, "locator": "JSON-LD.validThrough", "quote": job["validThrough"]}
    for match in re.finditer(r"^[ \t]*(?:Application Deadline|Closing date|Closes|Deadline|Apply by)[ \t]*:?[ \t]*\n?[ \t\n]*([^\n]{5,100})", cleaned, re.I | re.M):
        visible = parse_deadline(match[1].strip())
        if not visible or not (visible.get("value") or visible.get("local_value")):
            continue
        deadline_candidates.append({"origin": "visible", **visible})
        if deadline and deadline.get("conflict"):
            continue
        conflict = bool(visible.get("local_value"))
        if deadline and deadline.get("value") and visible.get("value"):
            if deadline.get("precision") == visible.get("precision") == "time":
                conflict = datetime.fromisoformat(deadline["value"]) != datetime.fromisoformat(visible["value"])
            else:
                conflict = deadline["value"][:10] != visible["value"][:10]
            if not conflict and deadline.get("precision") == "time" and visible.get("precision") == "date":
                instant = datetime.fromisoformat(deadline["value"])
                # A date label cannot erase an explicit non-midnight cutoff.
                # Preserve the existing date-only treatment of machine midnight
                # placeholders when the visible page states only that same date.
                if (instant.hour, instant.minute, instant.second, instant.microsecond) != (0, 0, 0, 0):
                    continue
        if conflict:
            deadline = {"raw": (deadline["raw"] + " | " if deadline else "") + visible["raw"],
                        "value": None, "precision": "unknown", "timezone": None, "conflict": True}
            continue
        deadline = visible
        provenance["deadline"] = {"source": url, "locator": "visible text", "quote": match.group(0)}
    for key, value, locator in (("institution", institution, "hiringOrganization.name"), ("country", country, "jobLocation.address.addressCountry")):
        if value:
            provenance[key] = {"source": url, "locator": "JSON-LD." + locator, "quote": value}
    identifier = job.get("identifier")
    if isinstance(identifier, dict):
        identifier = identifier.get("value")
    if isinstance(identifier, bool) or identifier is not None and not isinstance(identifier, (str, int, float)):
        raise Error("JobPosting.identifier.value must be text, a number or null")
    posted_date = _text_field(job.get("datePosted"), "datePosted")
    data = {"title": title, "institution": institution, "country": country, "city": address.get("addressLocality"),
            "source_url": url, "description": description, "deadline": deadline, "deadline_candidates": deadline_candidates, "posted_date": posted_date,
            "reference": identifier, "opportunity_type": None, "funding": None, "requirements": {},
            "supervisors": [], "topics": [], "methods": [], "skills": [], "provenance": provenance,
            "extraction": {"method": "jsonld" if job else "visible_text", "requires_review": not bool(job),
                           "funding_not_inferred_from_salary": True}}
    if job.get("baseSalary"):
        data["salary_raw"] = job["baseSalary"]
    return data, cleaned, findings


def discover(markup: str, base_url: str, pattern: str) -> tuple[list[dict], str | None]:
    try:
        matcher = re.compile(pattern)
    except re.error as exc:
        raise Error(f"Invalid source URL pattern: {exc}") from exc
    page = Page(markup)
    links = []
    seen = set()
    next_url = None
    base_host = urlsplit_host(base_url)
    for link in page.links:
        try:
            url = canonical_url(urljoin(base_url, link["url"]))
        except (Error, ValueError):
            continue
        if urlsplit_host(url) != base_host:
            continue
        if "next" in link["rel"].split():
            next_url = url
        if matcher.search(url) and url not in seen:
            seen.add(url)
            links.append({"url": url, "title": link["title"]})
    for block in page.jsonld:
        for item in jsonld_objects(block):
            if not _jobposting(item) or not isinstance(item.get("url"), str):
                continue
            try:
                url = canonical_url(urljoin(base_url, item["url"]))
            except (Error, ValueError):
                continue
            if urlsplit_host(url) == base_host and matcher.search(url) and url not in seen:
                seen.add(url)
                links.append({"url": url, "title": item.get("title", "")})
    return links, next_url


def urlsplit_host(url):
    from urllib.parse import urlsplit
    return urlsplit(url).netloc.lower()
