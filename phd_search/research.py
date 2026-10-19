from __future__ import annotations

import json
import re

from .core import Error, atomic_write, digest, json_text, now, slug
from .network import Client
from .opportunities import family as opportunity_family
from .store import Store
from .vendor.posting_guard import guard

SEARCH_TEMPLATES = {
    "phd": [
        {"source": "euraxess", "query": 'site:euraxess.ec.europa.eu/jobs/ ("PhD" OR "doctoral") "{topic}" {country}'},
        {"source": "academicpositions", "query": 'site:academicpositions.com/ad/ ("PhD" OR "doctoral") "{topic}" {country}'},
        {"source": "jobs-ac-uk", "query": 'site:jobs.ac.uk/job/ ("PhD" OR "studentship") "{topic}" {country}'},
        {"source": "findaphd", "query": 'site:findaphd.com/phds/project/ "{topic}" {country}'},
        {"source": "university", "query": '("PhD" OR "doctoral" OR "DPhil") ("admissions" OR "vacancy" OR "funded") "{topic}" {country}'},
        {"source": "supervisor", "query": '"{topic}" ("research group" OR "laboratory" OR "supervision") ("PhD" OR "doctoral") {country}'},
        {"source": "funding", "query": '"{topic}" ("doctoral scholarship" OR "doctoral network" OR "PhD funding") {country}'},
    ],
    "internship": [
        {"source": "university", "query": '"{topic}" ("research internship" OR "research placement" OR "visiting research student") ("university" OR "institute") {country}'},
        {"source": "project", "query": '"{topic}" ("research intern" OR "predoctoral" OR "research traineeship") ("project" OR "archive" OR "fieldwork" OR "practice") {country}'},
        {"source": "mentor", "query": '"{topic}" ("research internship" OR "visiting student") ("mentor" OR "supervisor" OR "research centre") {country}'},
        {"source": "eligibility", "query": '"{topic}" ("research internship" OR "research placement") ("eligibility" OR "enrolled" OR "return to study" OR "work authorization") {country}'},
        {"source": "funding", "query": '"{topic}" ("research internship" OR "research placement") ("funding" OR "stipend" OR "paid" OR "travel support") {country}'},
    ],
    "school": [
        {"source": "organiser", "query": '"{topic}" ("summer school" OR "winter school" OR "research school" OR "field school" OR "short course") ("university" OR "institute" OR "society") {country}'},
        {"source": "programme", "query": '"{topic}" ("summer school" OR "winter school" OR "training school" OR "field school") ("programme" OR "syllabus" OR "methods" OR "practice") {country}'},
        {"source": "eligibility", "query": '"{topic}" ("research school" OR "summer school" OR "winter school" OR "short course") ("eligibility" OR "prerequisites" OR "doctoral" OR "masters" OR "undergraduate") {country}'},
        {"source": "funding", "query": '"{topic}" ("summer school" OR "winter school" OR "field school") ("scholarship" OR "fee waiver" OR "travel grant" OR "accommodation") {country}'},
        {"source": "dates", "query": '"{topic}" ("summer school" OR "winter school" OR "research school" OR "field school") ("application deadline" OR "registration deadline" OR "scholarship deadline") {country}'},
    ],
}


def search_plan(profile: dict, family: str | None = None) -> dict:
    """Prepare queries, never fabricate discoveries or candidate preferences."""
    if family not in {None, "phd", "internship", "school", "all"}:
        raise Error("Search family must be phd, internship, school or all")
    requested_types = profile["preferences"].get("opportunity_types", [])
    if family == "all":
        families = list(SEARCH_TEMPLATES)
    elif family:
        families = [family]
    else:
        selected = {opportunity_family({"opportunity_type": item}) for item in requested_types}
        families = [item for item in SEARCH_TEMPLATES if item in selected] or ["phd"]
    topics = list(dict.fromkeys(profile["research"]["topics"] + profile["research"]["keywords"]))
    countries = profile["preferences"]["countries"] or [""]
    templates = [{**item, "family": kind} for kind in families for item in SEARCH_TEMPLATES[kind]]
    queries = [{"source": item["source"], "family": item["family"], "topic": topic, "country": country,
                "query": item["query"].format(topic=topic.replace('"', ''), country=country).strip()}
               for topic in topics for country in countries for item in templates]
    return {"state": "ready" if topics else "profile_required", "queries": queries,
            "families": families, "requested_opportunity_types": requested_types,
            "templates": templates if not topics else [],
            "scope": "Queries for an agent/search engine, not fetched opportunities; verify every result, current cycle and exact opportunity type on its original page. Family selection does not alter saved preferences."}


def create_dossier(store: Store, name: str, kind: str) -> dict:
    if kind not in {"supervisor", "lab", "programme", "funding"} or not name.strip():
        raise Error("Dossier requires a name and kind: supervisor, lab, programme, funding")
    identifier = slug(kind + "-" + name)
    if store.db.execute("SELECT 1 FROM dossiers WHERE id=?", (identifier,)).fetchone():
        raise Error("Dossier already exists")
    relative = "research/" + identifier
    data = {"directory": relative, "sources": [], "facts": [], "questions": [], "opportunity_ids": []}
    target = store.root / relative
    target.mkdir(parents=True, exist_ok=True)
    atomic_write(target / "dossier.md", f"# {name}\n\nType: {kind}\n\n"
                 + "## Verified identity and affiliation\n\n[[Add source, exact quote and retrieval date.]]\n\n"
                 + "## Research agenda and representative work\n\n[[Use recent primary sources. Distinguish published work, preprints, grants and proposals.]]\n\n"
                 + "## Scientific fit\n\n[[Compare questions and methods with candidate evidence. Identify concrete contributions and gaps.]]\n\n"
                 + "## Supervision and environment\n\n[[Separate verifiable group information from unknown availability, culture and mentoring.]]\n\n"
                 + "## Funding, access and conditions\n\n[[Quote coverage, duration, fees, eligibility and restrictions. Unknowns remain unknown.]]\n\n"
                 + "## Questions and next action\n\n[[Draft a focused inquiry; never send automatically.]]\n")
    with store.transaction():
        store.db.execute("INSERT INTO dossiers VALUES (?,?,?,?,?)", (identifier, kind, name, json_text(data), now()))
    return {"id": identifier, "name": name, "kind": kind, **data}


def dossier_get(store: Store, identifier: str) -> dict:
    row = store.db.execute("SELECT * FROM dossiers WHERE id=?", (identifier,)).fetchone()
    if not row:
        raise Error("Dossier not found")
    return {**dict(row), "data": json.loads(row["data"])}


def dossier_fetch(store: Store, client: Client, identifier: str, url: str) -> dict:
    dossier = dossier_get(store, identifier)
    response = client.get(url)
    if response.body.startswith(b"%PDF"):
        from .evidence import pdf_text
        content = pdf_text(response.body, store.root)
        cleaned, findings = guard(content, "text")
    else:
        cleaned, findings = guard(response.text, "html" if "html" in response.content_type else "text")
    sha = digest(response.body)
    relative = dossier["data"]["directory"] + "/sources/" + sha
    atomic_write(store.root / (relative + ".raw"), response.body)
    atomic_write(store.root / (relative + ".txt"), cleaned)
    source = {"url": response.url, "fetched_at": response.fetched_at, "raw_sha256": sha, "file": relative + ".txt",
              "sha256": digest(cleaned), "integrity": findings}
    data = dossier["data"]
    data["sources"].append(source)
    with store.transaction():
        store.db.execute("UPDATE dossiers SET data=?,updated_at=? WHERE id=?", (json_text(data), now(), identifier))
    atomic_write(store.root / dossier["data"]["directory"] / "sources.json", json_text(data["sources"]))
    return source


def gaps_report(store: Store, profile: dict) -> dict:
    groups = {}
    opportunities = []
    for record in store.list():
        assessment = record["assessment"]
        if not assessment:
            continue
        from .assessment import merged, ranking
        ranked = ranking(record, profile, root=store.root)
        if ranked["assessment_state"] != "current" or ranked["eligibility"]["verdict"] == "fail":
            continue
        kind = opportunity_family(merged(record))
        for gap in assessment["data"].get("gaps", []):
            text = gap if isinstance(gap, str) else gap.get("text", "")
            if not text:
                continue
            key = (kind, re.sub(r"\s+", " ", text.casefold()).strip())
            if key not in groups:
                groups[key] = {"gap": text, "family": kind, "opportunities": []}
            groups[key]["opportunities"].append(record["id"])
        opportunities.append(record["id"])
    rows = sorted(groups.values(), key=lambda x: (x["family"], -len(x["opportunities"]), x["gap"]))
    result = {"created_at": now(), "assessed_opportunities": opportunities, "gaps": rows,
              "scope": "Exact recorded assessment gaps, grouped separately for PhD, internship and school; no inferred deficiencies from missing profile data",
              "next_step": "For each recurring gap, verify prerequisites/resources, choose a demonstrable output and an achievable study plan; do not invent course links or durations"}
    atomic_write(store.root / "reports" / "gaps.json", json_text(result))
    lines = ["# Research readiness and learning plan", "", result["scope"], ""]
    for row in rows:
        lines.extend(["## " + row["gap"], "", f"Family: {row['family']}. Appears in {len(row['opportunities'])} current assessments.", "", "Evidence: " + ", ".join(row["opportunities"]), "",
                      "Action, verified resources, effort estimate, demonstrable output and target date: [[TO_PLAN]]", ""])
    atomic_write(store.root / "reports" / "gaps.md", "\n".join(lines))
    return result
