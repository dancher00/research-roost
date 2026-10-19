from __future__ import annotations

import csv
import html
import io
import json
import tempfile
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .applications import list_applications
from .assessment import merged, rank_all
from .core import Error, atomic_write, digest, json_text, now
from .opportunities import deadline_entries, primary_application
from .opportunities import family as opportunity_family
from .store import Store


def safe_cell(value) -> str:
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r")):
        return "'" + text
    return text


def tracker_rows(store: Store, profile: dict) -> list[dict]:
    rankings = {row["id"]: row for row in rank_all(store, profile, True)}
    rows = []
    apps = list_applications(store)
    for record in store.list():
        data = merged(record)
        ranked = rankings.get(record["id"], {})
        deadlines = deadline_entries(data)
        application_deadline = (primary_application(data) or {}).get("deadline", {})
        related = [app for app in apps if app["opportunity_id"] == record["id"]] or [None]
        for app in related:
            rows.append({"id": record["id"], "application_id": app["id"] if app else "", "title": data["title"],
                         "institution": data.get("institution"), "country": data.get("country"), "type": data.get("opportunity_type"),
                         "family": opportunity_family(data), "rubric_id": ranked.get("rubric_id"),
                         "comparison_group": ranked.get("comparison_group"), "edition": data.get("edition"), "session": data.get("session_id"),
                         "start_date": data.get("start_date"), "end_date": data.get("end_date"), "mode": data.get("mode"),
                         "application_status": data.get("application_status", "unknown"),
                         "funding_components": json.dumps((data.get("funding") or {}).get("components", {}), ensure_ascii=False),
                         "deadlines": json.dumps(deadlines, ensure_ascii=False),
                         "url": record["url"], "status": app["status"] if app else record["status"], "funding": (data.get("funding") or {}).get("status", "unknown"),
                         "deadline": application_deadline.get("value"), "deadline_raw": application_deadline.get("raw"),
                         "eligibility": ranked.get("eligibility", {}).get("verdict", "unknown"), "score": ranked.get("score"),
                         "assessment_state": ranked.get("assessment_state", "missing"), "coverage": ranked.get("coverage", 0),
                         "first_seen": record["first_seen"], "last_verified": record["last_seen"],
                         "submitted_on": (app["data"].get("submission") or {}).get("date") if app else None,
                         "document_filenames": "; ".join(app["data"]["documents"]) if app else ""})
    return rows


TRACKER_FIELDS = ["id", "application_id", "title", "institution", "country", "type", "url", "status", "funding", "deadline", "deadline_raw",
                  "family", "rubric_id", "comparison_group", "edition", "session", "start_date", "end_date", "mode", "application_status", "funding_components", "deadlines",
                  "eligibility", "score", "assessment_state", "coverage", "first_seen", "last_verified", "submitted_on", "document_filenames"]


def export_csv(store: Store, profile: dict, target: Path) -> dict:
    rows = tracker_rows(store, profile)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=TRACKER_FIELDS)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: safe_cell(value) for key, value in row.items()})
    atomic_write(target, buffer.getvalue())
    return {"path": str(target), "rows": len(rows)}


def report(store: Store, profile: dict, target: Path, *, family: str | None = None) -> dict:
    rows = tracker_rows(store, profile)
    if family:
        rows = [row for row in rows if row["family"] == family]
    selected = {row["id"] for row in rows}
    apps = list_applications(store)
    apps = [app for app in apps if app["opportunity_id"] in selected]
    statuses = Counter(app["status"] for app in apps)
    countries = Counter(row["country"] or "Unknown" for row in rows)
    funding = Counter(row["funding"] for row in rows)
    escape = html.escape
    cards = [("Opportunities", len(selected)), ("Applications", len(apps)), ("Submitted", sum(bool(app["data"].get("submission")) for app in apps)),
             ("Interviews", sum(any(e["kind"] == "status" and e["data"].get("to") == "interview" for e in app["events"]) for app in apps)),
             ("Offers", sum(any(e["kind"] == "status" and e["data"].get("to") == "offer" for e in app["events"]) for app in apps))]
    def bars(counter):
        total = max(counter.values(), default=1)
        return "".join(f"<div class='bar-label'><span>{escape(str(key))}</span><strong>{value}</strong></div><div class='bar'><i style='width:{value/total*100:.1f}%'></i></div>" for key, value in counter.most_common()) or "<p>No data yet.</p>"
    table_rows = []
    for row in rows:
        searchable = " ".join(str(row.get(k) or "") for k in ("title", "institution", "country", "status", "funding", "eligibility", "family", "type", "edition")).casefold()
        deadlines = json.loads(row["deadlines"])
        deadline_text = "; ".join(str(item.get("label") or item["kind"]) + ": " + str(item["deadline"].get("value") or item["deadline"].get("raw") or "Unknown") for item in deadlines)
        components = json.loads(row["funding_components"])
        cost_text = "; ".join(name + ": " + value.get("coverage", "unknown") for name, value in components.items())
        edition_text = " · ".join(str(row[k]) for k in ("edition", "session") if row.get(k))
        participation = " – ".join(str(row[k]) for k in ("start_date", "end_date") if row.get(k))
        table_rows.append("<tr data-search='" + escape(searchable, quote=True) + "' data-status='" + escape(row["status"], quote=True) + "' data-family='" + escape(row["family"], quote=True) + "'>"
                          + "<td><a target='_blank' rel='noopener noreferrer' href='" + escape(row["url"], quote=True) + "'>" + escape(row["title"]) + "</a><small>" + escape(row["institution"] or "Institution unverified") + "</small><small>" + escape(row["family"] + (" · " + edition_text if edition_text else "")) + "</small></td>"
                          + "<td>" + escape(row["country"] or "Unknown") + "</td><td><span class='badge'>" + escape(row["status"]) + "</span></td>"
                          + "<td>" + escape(deadline_text or "Unknown") + "<small>" + escape(participation) + "</small><small>Recruitment: " + escape(row["application_status"]) + "</small></td><td>" + escape(row["funding"]) + "<small>" + escape(cost_text) + "</small></td>"
                          + "<td>" + (str(row["score"]) + "/100" if row["score"] is not None else "Unscored") + "<small>Coverage " + str(row["coverage"]) + "% · " + escape(row["assessment_state"]) + "</small><small>" + escape(str(row["rubric_id"] or row["family"])) + "</small></td>"
                          + "<td>" + escape(row["eligibility"]) + "</td></tr>")
    options = "".join("<option>" + escape(s) + "</option>" for s in sorted({row["status"] for row in rows}))
    family_options = "".join("<option>" + escape(s) + "</option>" for s in sorted({row["family"] for row in rows}))
    timeline = []
    for app in apps:
        for event in app["events"][-5:]:
            if event["kind"] == "status":
                timeline.append((event["created_at"], app["data"]["title"], event["data"].get("to", "")))
    events_html = "".join("<li><time>" + escape(stamp[:10]) + "</time><span>" + escape(title) + "</span><strong>" + escape(status) + "</strong></li>" for stamp, title, status in sorted(timeline, reverse=True)[:20]) or "<li>No application events yet.</li>"
    content = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Research Roost · Research opportunities</title>
<style>:root{--bg:#f5f4f9;--ink:#202037;--muted:#707086;--line:#e4e2ed;--accent:#6552c7}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,sans-serif}header{background:#24213f;color:white;padding:38px max(24px,calc((100vw - 1360px)/2))}header p{color:#cec8e7;margin:5px 0}h1{font-size:32px;letter-spacing:-.8px;margin:8px 0}header .eyebrow{font-size:11px;letter-spacing:2px;color:#c4b4ff}main{max-width:1408px;margin:auto;padding:26px 24px}section{margin-bottom:24px}.cards{display:grid;grid-template-columns:repeat(5,1fr);gap:16px}.card,.panel{background:white;border:1px solid var(--line);border-radius:12px;padding:20px}.card small{display:block;color:var(--muted)}.card strong{font-size:30px}.three{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}h2{font-size:17px;margin:0 0 18px}.bar{background:#f0edf7;height:7px;border-radius:8px;overflow:hidden;margin:4px 0 14px}.bar i{display:block;height:100%;background:var(--accent);border-radius:8px}.bar-label{display:flex;justify-content:space-between;font-size:12px}.toolbar{display:flex;gap:12px;align-items:center;margin-bottom:18px}.toolbar input{flex:1}input,select{font:inherit;padding:10px 12px;border:1px solid var(--line);border-radius:7px;background:white}table{width:100%;border-collapse:collapse;text-align:left}th{font-size:11px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted)}td,th{padding:14px 12px;border-bottom:1px solid var(--line);vertical-align:top}td:first-child{min-width:270px;max-width:450px}td a{font-weight:600;color:var(--ink);text-decoration:none}td a:hover{color:var(--accent)}small{display:block;color:var(--muted);font-size:11px;margin-top:5px}.badge{display:inline-block;background:#eeeaf9;color:#58439d;border-radius:20px;padding:3px 10px;font-size:12px}ul{padding:0;list-style:none}li{display:flex;gap:16px;padding:10px 0;border-bottom:1px solid var(--line)}li time{color:var(--muted);min-width:90px}li span{flex:1}footer{color:var(--muted);font-size:12px;margin:24px 0}.scroll{overflow:auto}#count{white-space:nowrap;color:var(--muted);font-size:12px}@media(max-width:800px){.cards{grid-template-columns:repeat(2,1fr)}.three{grid-template-columns:1fr}.toolbar{flex-wrap:wrap}li{flex-wrap:wrap}h1{font-size:26px}}@media print{input,select{display:none}header{background:white;color:var(--ink)}.panel,.card{break-inside:avoid}}</style></head><body><header><div class="eyebrow">RESEARCH · PEOPLE · POSSIBILITIES</div><h1>Your next research chapter</h1><p>Research Roost · A source-backed view of your PhDs, research internships and schools</p></header><main>"""
    content += "<section class='cards'>" + "".join(f"<div class='card'><small>{label}</small><strong>{value}</strong></div>" for label, value in cards) + "</section>"
    content += "<section class='three'><div class='panel'><h2>Application stages</h2>" + bars(statuses) + "</div><div class='panel'><h2>Countries</h2>" + bars(countries) + "</div><div class='panel'><h2>Funding</h2>" + bars(funding) + "</div></section>"
    content += "<section class='panel'><h2>Opportunities & applications</h2><div class='toolbar'><input id='search' type='search' aria-label='Filter opportunities' placeholder='Search topic, institution, country…'><select id='status' aria-label='Application status'><option value=''>All statuses</option>" + options + "</select><select id='family' aria-label='Opportunity family'><option value=''>All opportunity types</option>" + family_options + "</select><span id='count'></span></div><div class='scroll'><table><thead><tr><th>Opportunity</th><th>Country</th><th>Status</th><th>Deadlines & participation</th><th>Funding & coverage</th><th>Assessment within family</th><th>Eligibility</th></tr></thead><tbody>" + "".join(table_rows) + "</tbody></table></div></section>"
    content += "<section class='panel'><h2>Recent activity</h2><ul>" + events_html + "</ul></section><footer>Generated " + escape(now()) + ". Unknowns remain explicit. Scores are rubric judgments, comparable only within the same family and rubric version, not admission probabilities. Search results are bounded samples. This report uses no external assets or requests.</footer></main>"
    content += """<script>const rows=[...document.querySelectorAll('tbody tr')],q=document.getElementById('search'),s=document.getElementById('status'),f=document.getElementById('family'),c=document.getElementById('count');function filter(){let n=0;for(const r of rows){const visible=r.dataset.search.includes(q.value.toLowerCase())&&(!s.value||r.dataset.status===s.value)&&(!f.value||r.dataset.family===f.value);r.hidden=!visible;if(visible)n++}c.textContent=n+' of '+rows.length}q.addEventListener('input',filter);s.addEventListener('change',filter);f.addEventListener('change',filter);filter();</script></body></html>"""
    atomic_write(target, content)
    return {"path": str(target), "opportunities": len(selected), "applications": len(apps), "family": family, "offline": True}


def ics_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\r", "").replace("\n", r"\n").replace(";", r"\;").replace(",", r"\,")


def fold_line(line: str) -> str:
    pieces = []
    part = ""
    for char in line:
        if len((part + char).encode("utf-8")) > 75:
            pieces.append(part)
            part = " "
        part += char
    pieces.append(part)
    return "\r\n".join(pieces)


def calendar(store: Store, target: Path) -> dict:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Research Roost//Research Opportunities//EN", "CALSCALE:GREGORIAN"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    count = 0
    skipped = 0
    def event(uid, summary, when, *, all_day=False, until=None, url=None, description=""):
        nonlocal count
        count += 1
        lines.extend(["BEGIN:VEVENT", "UID:" + uid + "@phd-search.local", "DTSTAMP:" + stamp])
        if all_day:
            d = date.fromisoformat(when[:10])
            end = date.fromisoformat(until) if until else d
            lines.extend(["DTSTART;VALUE=DATE:" + d.strftime("%Y%m%d"), "DTEND;VALUE=DATE:" + (end + timedelta(days=1)).strftime("%Y%m%d")])
        else:
            at = datetime.fromisoformat(when.replace("Z", "+00:00"))
            if at.tzinfo is None:
                raise Error("Calendar times require an explicit timezone")
            lines.append("DTSTART:" + at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        lines.extend(["SUMMARY:" + ics_escape(summary), "DESCRIPTION:" + ics_escape(description)])
        if url:
            lines.append("URL:" + url)
        lines.append("END:VEVENT")
    for record in store.list():
        if record["status"] in {"dismissed", "archived"}:
            continue
        data = merged(record)
        primary = primary_application(data)
        for entry in deadline_entries(data):
            deadline = entry["deadline"]
            if not deadline.get("value"):
                skipped += 1
                continue
            # Keep historical primary UIDs so a rename does not duplicate
            # events in an already subscribed calendar.
            if primary and entry["id"] == primary["id"]:
                uid = "deadline-" + record["id"]
            else:
                uid = "deadline-" + record["id"] + "-" + digest(entry["kind"] + ":" + entry["id"])[:12]
            label = entry.get("label") or entry["kind"].capitalize()
            event(uid, label + " deadline: " + data["title"], deadline["value"],
                  all_day=deadline.get("precision") != "time", url=record["url"],
                  description="Original deadline: " + str(deadline.get("raw", "")) + "; kind=" + entry["kind"] + "; confirm the institution's timezone and cutoff.")
        if data.get("start_date") and data.get("end_date"):
            event("participation-" + record["id"], opportunity_family(data).capitalize() + " participation: " + data["title"],
                  data["start_date"], until=data["end_date"], all_day=True, url=record["url"],
                  description="Stated participation dates; " + str(data.get("mode") or "mode unknown"))
    for app in list_applications(store):
        if app["status"] in {"rejected", "withdrawn", "expired", "declined"}:
            continue
        for item in app["events"]:
            if item["kind"] in {"interview_scheduled", "assessment_due"}:
                event("event-" + str(item["id"]), item["kind"].replace("_", " ") + ": " + app["data"]["title"], item["data"]["at"], description=item["data"]["note"])
        for person in app["data"].get("referees", []):
            if person.get("due_on") and not person.get("received_on"):
                event("reference-" + app["id"] + "-" + digest(person["name"])[:8], "Reference due: " + person["name"], person["due_on"], all_day=True, description=app["data"]["title"])
    lines.append("END:VCALENDAR")
    atomic_write(target, "\r\n".join(fold_line(line) for line in lines) + "\r\n")
    return {"path": str(target), "events": count, "skipped_unknown_deadlines": skipped}


def backup(store: Store, target: Path) -> dict:
    target = target.expanduser().resolve()
    if target.is_relative_to(store.root):
        raise Error("Backup destination must be outside the workspace to prevent recursive archives")
    if target.exists():
        raise Error("Backup destination already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="phd-backup-") as temporary:
        copy = Path(temporary) / "phd-search.sqlite3"
        store.backup(copy)
        staging = Path(temporary) / "workspace.zip"
        manifest = {}
        with zipfile.ZipFile(staging, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(copy, "phd-search.sqlite3")
            manifest["phd-search.sqlite3"] = digest(copy.read_bytes())
            for path in store.root.rglob("*"):
                if not path.is_file() or path.is_symlink() or path.name.startswith("phd-search.sqlite3") or "cache" in path.relative_to(store.root).parts:
                    continue
                relative = str(path.relative_to(store.root))
                archive.write(path, relative)
                manifest[relative] = digest(path.read_bytes())
            archive.writestr("backup.manifest.json", json_text({"schema_version": 1, "created_at": now(), "files": manifest}))
        atomic_write(target, staging.read_bytes())
    return {"path": str(target), "files": len(manifest), "sha256": digest(target.read_bytes()), "contains_personal_data": True}


def restore(archive_path: Path, target: Path) -> dict:
    target = target.expanduser().resolve()
    if target.exists():
        raise Error("Restore target must be a new directory")
    if not archive_path.is_file() or archive_path.stat().st_size > 1024 ** 3:
        raise Error("Backup missing or larger than 1 GiB")
    with zipfile.ZipFile(archive_path) as archive:
        items = archive.infolist()
        if sum(item.file_size for item in items) > 4 * 1024 ** 3 or len(items) > 100000:
            raise Error("Backup expansion exceeds supported resource bounds")
        for item in items:
            path = (target / item.filename).resolve()
            if not path.is_relative_to(target) or Path(item.filename).is_absolute() or "\\" in item.filename or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise Error("Backup contains an unsafe path or symlink")
        try:
            manifest = json.loads(archive.read("backup.manifest.json"))
        except (ValueError, KeyError) as exc:
            raise Error("Backup manifest missing or malformed") from exc
        for name, sha in manifest["files"].items():
            if digest(archive.read(name)) != sha:
                raise Error("Backup checksum mismatch for " + name)
        if {i.filename for i in items if not i.is_dir()} != set(manifest["files"]) | {"backup.manifest.json"}:
            raise Error("Backup entries and manifest differ")
        target.mkdir(parents=True)
        archive.extractall(target)
    with Store(target) as store:
        result = store.db.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise Error("Restored database integrity check failed: " + result)
    return {"path": str(target), "database_integrity": "ok", "files": len(manifest["files"])}
