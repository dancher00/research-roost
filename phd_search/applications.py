from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

from .assessment import context_hash, merged, pointer, ranking, screen
from .core import Error, atomic_write, contained, digest, json_text, now, resource
from .evidence import verify_external
from .opportunities import deadline_entries, family, rubric_for
from .profile import fingerprint, load
from .store import Store

TRANSITIONS = {
    "preparing": {"drafted", "withdrawn", "expired"},
    "drafted": {"preparing", "submitted", "withdrawn", "expired"},
    "submitted": {"assessment", "interview", "waitlisted", "offer", "rejected", "withdrawn", "expired"},
    "assessment": {"interview", "waitlisted", "offer", "rejected", "withdrawn", "expired"},
    "interview": {"interview", "assessment", "waitlisted", "offer", "rejected", "withdrawn", "expired"},
    "waitlisted": {"interview", "offer", "rejected", "withdrawn", "expired"},
    "offer": {"accepted", "declined", "withdrawn", "expired"},
    "accepted": set(), "declined": set(), "rejected": set(), "withdrawn": set(), "expired": set(),
}
PLACEHOLDERS = re.compile(r"\[\[(?:[^\]]|\](?!\]))*\]\]|\[(?:YOUR_|INSERT_|TODO|TBD)[^\]]*\]|\b(?:TODO|TBD)\b")


def get_application(store: Store, identifier: str) -> dict:
    row = store.db.execute("SELECT * FROM applications WHERE id=?", (identifier,)).fetchone()
    if row is None:
        rows = store.db.execute("SELECT id FROM applications WHERE id LIKE ?", (identifier + "%",)).fetchall()
        if len(rows) == 1:
            return get_application(store, rows[0][0])
        raise Error(f"Application not found or ambiguous: {identifier}")
    result = dict(row)
    result["data"] = json.loads(row["data"])
    result["events"] = [{**dict(event), "data": json.loads(event["data"])} for event in store.db.execute("SELECT * FROM events WHERE application_id=? ORDER BY id", (row["id"],))]
    return result


def list_applications(store: Store) -> list[dict]:
    return [get_application(store, row[0]) for row in store.db.execute("SELECT id FROM applications ORDER BY created_at,id")]


def cv_markdown(profile: dict) -> tuple[str, list[dict]]:
    identity = profile["identity"]
    lines = ["# " + (identity.get("name") or "[[CANDIDATE_NAME]]"), "", " · ".join(str(identity[k]) for k in ("email", "location", "orcid", "website") if identity.get(k)), ""]
    claims = []
    if profile["research"].get("statement"):
        lines.extend(["## Research interests", "", profile["research"]["statement"], ""])
        claims.append({"file": "cv.md", "text": profile["research"]["statement"], "profile_refs": ["/research/statement"]})
    for collection, heading in (("education", "Education"), ("experience", "Research and professional experience"), ("outputs", "Research outputs and portfolio")):
        if not profile[collection]:
            continue
        lines.extend(["## " + heading, ""])
        for i, entry in enumerate(profile[collection]):
            text = " — ".join(str(entry[k]) for k in ("title", "degree", "institution", "organisation", "date", "awarded_on", "status", "citation", "doi", "url", "description") if entry.get(k))
            if not text:
                text = str(entry.get("level") or entry.get("role") or "[[DESCRIBE_ENTRY]]")
            lines.extend(["- " + text])
            claims.append({"file": "cv.md", "text": text, "profile_refs": [f"/{collection}/{i}"]})
            for j, item in enumerate(entry.get("achievements", [])):
                lines.append("  - " + str(item))
                claims.append({"file": "cv.md", "text": str(item), "profile_refs": [f"/{collection}/{i}/achievements/{j}"]})
        lines.append("")
    if profile["skills"]:
        text = ", ".join(x if isinstance(x, str) else str(x.get("name", "")) for x in profile["skills"])
        lines.extend(["## Skills", "", text, ""])
        claims.append({"file": "cv.md", "text": text, "profile_refs": ["/skills"]})
    if profile["languages"]:
        lines.extend(["## Languages", ""])
        for i, entry in enumerate(profile["languages"]):
            text = " — ".join(str(entry[k]) for k in ("name", "cefr", "level") if entry.get(k))
            lines.append("- " + text)
            claims.append({"file": "cv.md", "text": text, "profile_refs": [f"/languages/{i}"]})
    return "\n".join(lines) + "\n", claims


def _mode_document(kind: str, mode: str, data: dict, url: str) -> str | None:
    """Provide opportunity-specific prompts; the agent must still write the document."""
    if mode == "phd":
        return None
    title = data["title"]
    institution = data.get("institution") or "[[INSTITUTION]]"
    context = f"Opportunity: {title}\nHost: {institution}\nSource: {url}\n\n"
    common = ("[[FOLLOW the exact official prompt, document name, language and limits recorded in requirements.json. "
              "Use confirmed candidate evidence; distinguish completed work from proposed work.]]\n\n")
    if kind == "motivation":
        if mode == "school":
            body = ("[[EXPLAIN which questions or skills you want to develop and why the verified curriculum, methods, "
                    "instructors or field activities address them.]]\n\n"
                    "[[CONNECT concrete preparation from the candidate profile to the actual prerequisites. "
                    "Explain learning needs honestly; do not presume publications or a doctoral project are required.]]\n\n"
                    "[[DESCRIBE a realistic learning outcome and contribution to peer discussions, exercises or practice. "
                    "Add a project idea only if the school requests one.]]\n\n"
                    "[[STATE confirmed availability for the actual event dates and answer any separate financial-aid prompt. "
                    "Keep admission, fee waiver, accommodation and travel funding distinct.]]\n")
        else:
            body = ("[[IDENTIFY the advertised research task and a realistic contribution within the internship duration. "
                    "Connect relevant methods, practice or project evidence to the host's verified work.]]\n\n"
                    "[[DEVELOP a concrete example of your own contribution, evidence, result and limitation. "
                    "Describe the support or training you would need for the proposed short project.]]\n\n"
                    "[[STATE only confirmed availability and enrolment/work-authorisation facts requested by the host. "
                    "Leave unresolved permission, host approval, compensation or placement conditions explicit.]]\n")
        return "# Motivation — " + title + "\n\n" + context + common + body + "\n[[SIGN with the confirmed candidate name.]]\n"
    if kind == "statement_of_purpose":
        direction = ("the specific training objectives, prerequisites, curriculum and how you will use the learning afterward"
                     if mode == "school" else "the research task, your preparation, achievable contribution and learning objectives during the placement")
        return ("# Statement of purpose — " + title + "\n\n" + context + common
                + "[[EXPLAIN " + direction + ". Ground examples in the profile and host claims in verified sources.]]\n\n"
                + "[[ANSWER every actual selection question. Do not invent a multi-year agenda, supervision agreement or achievements.]]\n")
    if kind in {"research_statement", "proposal"}:
        heading = "Research statement" if kind == "research_statement" else "Project proposal"
        scope = ("a bounded exercise, field activity or learning project requested by this school"
                 if mode == "school" else "a feasible research contribution within the actual internship dates and host resources")
        return ("# " + heading + " — " + title + "\n\n" + context + common
                + "## Relevant preparation\n\n[[DESCRIBE supported research, practice or project experience, your own role, methods, outcomes and limitations.]]\n\n"
                + "## Proposed scope\n\n[[FRAME " + scope + ". Include only the sections requested by the host.]]\n\n"
                + "## Approach and feasibility\n\n[[EXPLAIN methods, access, realistic milestones, learning needs, ethics where relevant, and risks. "
                + "Do not imply permission, funding or resources have been granted.]]\n\n"
                + "## Relevant sources\n\n[[CITE only verified works actually used; remove this section if references are not requested or used.]]\n")
    if kind == "supervisor_email":
        recipient = "school organisers" if mode == "school" else "internship supervisor or recruitment contact"
        return ("Subject: " + title + " — [[SPECIFIC QUESTION / ADVERTISED REFERENCE]]\n\n"
                + "[[ADDRESS the verified " + recipient + " according to their contact instructions.]]\n\n"
                + "[[INTRODUCE yourself using confirmed evidence, identify this opportunity and ask one concrete unresolved question. "
                + "Mention relevant preparation without implying existing supervision or admission.]]\n\n"
                + "[[CLOSE with your confirmed name and actual attachments. This is a local draft; sending requires explicit authority.]]\n")
    return None


def create_application(store: Store, identifier: str, profile: dict, *, variant: str = "main", document_kinds: list[str] | None = None) -> dict:
    record = store.get(identifier)
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", variant):
        raise Error("Application variant must be 1–48 letters, digits, underscores or hyphens")
    app_id = record["id"] + "-" + variant
    if store.db.execute("SELECT 1 FROM applications WHERE id=?", (app_id,)).fetchone():
        raise Error("Application already exists; existing drafts are never overwritten")
    data = merged(record)
    mode = family(data)
    rubric = rubric_for(data)
    rubric_identity = {key: rubric[key] for key in ("id", "version", "family")}
    directory = store.root / "applications" / app_id
    if directory.exists():
        raise Error("Application directory already exists; inspect it before retrying")
    kinds = document_kinds if document_kinds is not None else (["cv", "motivation", "research_statement"] if mode == "phd" else ["cv", "motivation"])
    allowed = {"cv", "motivation", "statement_of_purpose", "research_statement", "proposal", "supervisor_email", "portal_answers", "portfolio"}
    if not kinds or set(kinds) - allowed:
        raise Error("Document kinds must be chosen from: " + ", ".join(sorted(allowed)))
    directory.mkdir(parents=True)
    cv, claims = cv_markdown(profile)
    profile_sha = fingerprint(profile)
    app_data = {"directory": str(directory.relative_to(store.root)), "variant": variant,
                "profile_sha256": profile_sha, "evidence_sha256": record["snapshot"]["sha256"],
                "context_sha256": context_hash(record), "opportunity_snapshot_sha256": digest(json_text(record)),
                "opportunity_family": mode, "opportunity_type": data.get("opportunity_type"),
                "rubric": rubric_identity, "rubric_sha256": digest(json_text(rubric)), "deadlines": deadline_entries(data),
                "documents": [kind + ".md" for kind in kinds], "attachments": [], "referees": [],
                "submission": None, "notes": "", "title": data["title"], "institution": data.get("institution")}
    try:
        atomic_write(directory / "profile.snapshot.json", json_text(profile))
        atomic_write(directory / "opportunity.snapshot.json", json_text(record))
        atomic_write(directory / "rubric.snapshot.json", json_text(rubric))
        atomic_write(directory / "posting.txt", (store.root / record["snapshot"]["text_path"]).read_bytes())
        atomic_write(directory / "briefing.md", f"# Application briefing\n\n{data['title']}\n\nSource: {record['url']}\n\n"
                     + f"Opportunity family: {mode}; type: {data.get('opportunity_type') or 'unknown'}.\n\n"
                     + "This packet is PREPARING. Documents containing [[...]] are unfinished. The document plan is provisional until the actual official prompts have been reviewed.\n\n"
                     + "## Evaluation\n\n```json\n" + json_text(ranking(record, profile, root=store.root)) + "```\n\n"
                     + "## Document requirements\n\nRecord the host's exact document names, prompts, language, word/page limits, file formats and submission route in requirements.json before drafting.\n\n"
                     + ("For a school, focus on learning objectives, prerequisites and the actual event dates. A proposal and an interview are only relevant when explicitly requested.\n"
                        if mode == "school" else "For an internship, scope the contribution to the actual placement period and verify enrolment, availability, host approval and work-authorisation conditions that apply.\n"
                        if mode == "internship" else "Select only the documents required by this doctoral route; requirements vary by discipline and institution.\n")
                     + "\n## Deadlines\n\n```json\n" + json_text(deadline_entries(data)) + "```\n")
        requirements = {"schema_version": 1, "source_url": record["url"], "source_quote": "",
                        "opportunity_family": mode, "opportunity_type": data.get("opportunity_type"), "plan_state": "provisional",
                        "deadlines": deadline_entries(data),
                        "documents": {kind + ".md": {"required": True, "language": profile["preferences"].get("document_language", "en"),
                                                        "exact_prompt": None,
                                                        "max_words": None, "min_words": None, "max_pages": None, "require_pdf": False} for kind in kinds}}
        atomic_write(directory / "requirements.json", json_text(requirements))
        for kind in kinds:
            if kind == "cv":
                content = cv
            else:
                template = _mode_document(kind, mode, data, record["url"]) or resource("templates/" + kind + ".md").read_text()
                content = template.replace("{{TITLE}}", data["title"]).replace("{{INSTITUTION}}", data.get("institution") or "[[INSTITUTION]]").replace("{{URL}}", record["url"])
            atomic_write(directory / (kind + ".md"), content)
        atomic_write(directory / "claims.json", json_text({"schema_version": 1, "claims": claims if "cv" in kinds else [], "coverage_reviewed": False,
                                                          "notes": "Add exact factual spans for all documents. Verify every factual claim and citation; matching pointers alone does not establish semantic support."}))
        atomic_write(directory / "review.json", json_text({"schema_version": 1, "reviewer": "", "verdict": "pending", "document_hashes": {},
                                                         "profile_sha256": profile_sha, "evidence_sha256": record["snapshot"]["sha256"],
                                                         "opportunity_family": mode, "rubric_sha256": app_data["rubric_sha256"],
                                                         "claims_semantically_checked": False, "requirements_checked": False, "visual_pdf_checked": False,
                                                         "support_hashes": {}, "source_integrity_checked": False,
                                                         "findings": [], "limitations": []}))
        stamp = now()
        with store.transaction():
            store.db.execute("INSERT INTO applications VALUES (?,?,?,?,?,?)", (app_id, record["id"], "preparing", stamp, stamp, json_text(app_data)))
            store.event(app_id, "created", {"profile_sha256": profile_sha, "evidence_sha256": record["snapshot"]["sha256"]})
    except BaseException:
        shutil.rmtree(directory)
        raise
    return get_application(store, app_id)


def _pdf_check(path: Path, max_pages: int | None) -> dict:
    if not path.is_file():
        return {"state": "fail", "reason": "PDF missing"}
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        pages = len(reader.pages)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        if not shutil.which("pdfinfo") or not shutil.which("pdftotext"):
            return {"state": "unverified", "reason": "Need pypdf or pdfinfo + pdftotext"}
        try:
            info = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, timeout=30, check=True).stdout
            match = re.search(r"^Pages:\s+(\d+)", info, re.M)
            if not match:
                raise Error("pdfinfo did not return a page count")
            pages = int(match[1])
            text = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, timeout=30, check=True).stdout
        except (subprocess.SubprocessError, Error) as exc:
            return {"state": "fail", "reason": str(exc)}
    except Exception as exc:
        return {"state": "fail", "reason": str(exc)}
    bad = "\ufffd" in text or bool(re.search(r"\(cid:\d+\)", text))
    return {"state": "pass" if text.strip() and not bad and (max_pages is None or pages <= max_pages) else "fail",
            "pages": pages, "max_pages": max_pages, "text_characters": len(text), "encoding_noise": bad,
            "visual_review": "requires human/agent rendered-page inspection"}


def verify_application(store: Store, identifier: str, *, require_pdf: bool = False) -> dict:
    app = get_application(store, identifier)
    directory = store.root / app["data"]["directory"]
    checks = []
    hashes = {}
    profile = json.loads((directory / "profile.snapshot.json").read_text())
    posting = (directory / "posting.txt").read_text()
    from .core import read_json
    requirements = read_json(directory / "requirements.json")
    if not isinstance(requirements, dict) or not isinstance(requirements.get("documents"), dict):
        raise Error("requirements.json must contain a documents object")
    for name, limits in requirements["documents"].items():
        contained(directory, name)
        if not isinstance(limits, dict):
            raise Error("Each document requirement must be an object")
        for key in ("max_words", "min_words", "max_pages"):
            value = limits.get(key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < (0 if key == "min_words" else 1)):
                raise Error(f"{name}.{key} must be a positive integer (min_words may be zero) or null")
        if limits.get("required", True) and name not in app["data"]["documents"]:
            checks.append({"name": "required_document:" + name, "state": "fail", "reason": "Required document is not in the active packet inventory"})
    minimum_referees = requirements.get("referees", {}).get("minimum", 0)
    if isinstance(minimum_referees, bool) or not isinstance(minimum_referees, int) or minimum_referees < 0:
        raise Error("Minimum referee count must be a nonnegative integer")
    registry = read_json(directory / "claims.json")
    review = read_json(directory / "review.json")
    archive_ok = (fingerprint(profile) == app["data"]["profile_sha256"] and
                  digest((directory / "opportunity.snapshot.json").read_bytes()) == app["data"]["opportunity_snapshot_sha256"])
    original = read_json(directory / "opportunity.snapshot.json")
    archive_ok = archive_ok and digest(posting) == original["snapshot"]["metadata"]["text_sha256"]
    if app["data"].get("rubric_sha256"):
        rubric_path = directory / "rubric.snapshot.json"
        frozen_rubric = read_json(rubric_path) if rubric_path.is_file() else {}
        frozen_data = merged(original)
        mode_ok = (rubric_path.is_file() and digest(rubric_path.read_bytes()) == app["data"]["rubric_sha256"]
                   and app["data"].get("opportunity_family") == family(frozen_data)
                   and app["data"].get("opportunity_type") == frozen_data.get("opportunity_type")
                   and app["data"].get("deadlines") == deadline_entries(frozen_data)
                   and frozen_rubric.get("family") == app["data"].get("opportunity_family")
                   and app["data"].get("rubric") == {key: frozen_rubric.get(key) for key in ("id", "version", "family")})
        checks.append({"name": "opportunity_mode", "state": "pass" if mode_ok else "fail",
                       "reason": "Packet family, type, rubric and deadlines must match the frozen opportunity and rubric"})
    checks.append({"name": "source_archive", "state": "pass" if archive_ok else "fail", "reason": "Archived profile, posting and opportunity must match their recorded digests"})
    document_texts = {}
    external_requirements = requirements.get("external_evidence", [])
    external_errors = []
    for item in external_requirements:
        try:
            verify_external(store.root, item)
        except Error as exc:
            external_errors.append(str(exc))
    if external_errors:
        checks.append({"name": "requirements_source", "state": "fail", "issues": external_errors})
    elif (not requirements.get("source_quote") or requirements["source_quote"] not in posting) and not external_requirements:
        checks.append({"name": "requirements_source", "state": "unverified", "reason": "Record the exact document requirements quote from the posting; independent official requirements may be archived separately"})
    else:
        checks.append({"name": "requirements_source", "state": "pass"})
    for filename in app["data"]["documents"]:
        path = contained(directory, filename)
        if not path.is_file():
            checks.append({"name": filename, "state": "fail", "reason": "Source document missing"})
            continue
        text = path.read_text()
        document_texts[filename] = text
        hashes[filename] = digest(text)
        limits = requirements.get("documents", {}).get(filename, {})
        words = len(re.findall(r"\S+", text))
        issues = []
        if PLACEHOLDERS.search(text) or not text.strip():
            issues.append("unfinished placeholders or empty content")
        if limits.get("max_words") is not None and words > limits["max_words"]:
            issues.append("word limit exceeded")
        if limits.get("min_words") is not None and words < limits["min_words"]:
            issues.append("below required minimum words")
        checks.append({"name": filename, "state": "fail" if issues else "pass", "words": words, "issues": issues, "sha256": hashes[filename]})
        pdf = directory / "rendered" / (path.stem + ".pdf")
        if require_pdf or limits.get("require_pdf"):
            check = _pdf_check(pdf, limits.get("max_pages"))
            if pdf.is_file():
                hashes["rendered/" + pdf.name] = digest(pdf.read_bytes())
                manifest_path = directory / "rendered" / (path.stem + ".build.json")
                manifest = read_json(manifest_path) if manifest_path.exists() else {}
                if manifest.get("source_sha256") != hashes[filename] or manifest.get("pdf_sha256") != hashes["rendered/" + pdf.name]:
                    check = {"state": "fail", "reason": "PDF build provenance missing or source/PDF changed; rebuild it"}
            checks.append({"name": filename + ":pdf", **check})
    for attachment in app["data"].get("attachments", []):
        filename = attachment["file"]
        path = contained(directory, filename)
        valid = path.is_file() and digest(path.read_bytes()) == attachment["sha256"]
        if path.is_file():
            hashes[filename] = digest(path.read_bytes())
        checks.append({"name": "attachment:" + filename, "state": "pass" if valid else "fail", "kind": attachment["kind"],
                       "reason": "Original attachment must exist and match the registered source digest"})
    for filename, specification in requirements.get("attachments", {}).items():
        registered = next((item for item in app["data"].get("attachments", []) if item["file"] == filename), None)
        if specification.get("required", True) and registered is None:
            checks.append({"name": "required_attachment:" + filename, "state": "fail", "reason": "Required transcript/diploma/sample/other attachment missing"})
    referee_requirement = requirements.get("referees", {})
    if referee_requirement.get("minimum"):
        eligible = [person for person in app["data"].get("referees", []) if person.get("permission_confirmed") is True and
                    (not referee_requirement.get("received_by_submission") or person.get("received_on"))]
        checks.append({"name": "referees", "state": "pass" if len(eligible) >= referee_requirement["minimum"] else "fail", "confirmed": len(eligible), "required": referee_requirement["minimum"]})
    seen_files = set()
    errors = []
    for claim in registry.get("claims", []):
        filename = claim.get("file")
        text = claim.get("text")
        if filename not in document_texts or not isinstance(text, str) or not text.strip() or text not in document_texts[filename]:
            errors.append("Claim span absent from an active document")
            continue
        seen_files.add(filename)
        if not claim.get("profile_refs") and not claim.get("posting_quotes") and not claim.get("external_evidence"):
            errors.append(f"Unsupported claim in {filename}: {text[:70]}")
        for ref in claim.get("profile_refs", []):
            try:
                pointer(profile, ref)
            except Error as exc:
                errors.append(str(exc))
        for quote in claim.get("posting_quotes", []):
            if not isinstance(quote, str) or not quote.strip() or quote not in posting:
                errors.append("Claim posting quote missing from the archived source")
        for external in claim.get("external_evidence", []):
            try:
                verify_external(store.root, external)
            except (KeyError, Error, OSError) as exc:
                errors.append(str(exc))
    if registry.get("coverage_reviewed") is not True:
        errors.append("Claim coverage has not been reviewed")
    for filename in set(document_texts) - seen_files:
        errors.append(f"No factual spans registered for {filename}; explicitly register source support")
    checks.append({"name": "claim_registry", "state": "fail" if errors else "pass", "issues": errors,
                   "scope": "Mechanical source/span consistency; semantic support requires reviewer judgment"})
    review_errors = []
    if review.get("verdict") != "approved" or not review.get("reviewer"):
        review_errors.append("Review pending or not approved")
    if review.get("document_hashes") != hashes:
        review_errors.append("Review does not cover the exact current documents and required PDFs")
    support_hashes = {name: digest((directory / name).read_bytes()) for name in ("requirements.json", "claims.json")}
    if review.get("support_hashes") != support_hashes:
        review_errors.append("Requirements or claim registry changed since review")
    if review.get("source_integrity_checked") is not True:
        review_errors.append("Source integrity findings have not been explicitly reviewed")
    if review.get("profile_sha256") != app["data"]["profile_sha256"] or review.get("evidence_sha256") != app["data"]["evidence_sha256"]:
        review_errors.append("Review profile/evidence bindings do not match the application")
    if app["data"].get("rubric_sha256") and (review.get("opportunity_family") != app["data"]["opportunity_family"] or
                                            review.get("rubric_sha256") != app["data"]["rubric_sha256"]):
        review_errors.append("Review opportunity family/rubric bindings do not match the application")
    if review.get("claims_semantically_checked") is not True or review.get("requirements_checked") is not True:
        review_errors.append("Semantic grounding and institutional requirements review must be explicit")
    if any(item.get("severity") in {"critical", "major"} and item.get("resolved") is not True for item in review.get("findings", [])):
        review_errors.append("Unresolved major or critical findings")
    if any(check["name"].endswith(":pdf") for check in checks) and review.get("visual_pdf_checked") is not True:
        review_errors.append("Required PDFs have not been visually inspected")
    checks.append({"name": "review", "state": "fail" if review_errors else "pass", "issues": review_errors})
    current = store.get(app["opportunity_id"])
    current_profile = load(store.root)
    stale = current["snapshot"]["sha256"] != app["data"]["evidence_sha256"] or context_hash(current) != app["data"]["context_sha256"] or fingerprint(current_profile) != app["data"]["profile_sha256"]
    checks.append({"name": "source_currency", "state": "fail" if stale else "pass", "reason": "Compare source/profile changes and create a revised application variant if needed"})
    eligibility = screen(current, current_profile)
    checks.append({"name": "eligibility", "state": "fail" if eligibility["verdict"] == "fail" else "unverified" if eligibility["verdict"] == "unknown" else "pass", "detail": eligibility})
    result = {"application_id": app["id"], "opportunity_family": app["data"].get("opportunity_family", "phd"),
              "rubric": app["data"].get("rubric"), "state": "fail" if any(x["state"] == "fail" for x in checks) else "needs_review" if any(x["state"] == "unverified" for x in checks) else "pass",
              "checks": checks, "document_hashes": hashes, "checked_at": now()}
    atomic_write(directory / "verification.json", json_text(result))
    return result


def transition(store: Store, identifier: str, status: str, *, occurred_on: str, note: str, allow_unknown: bool = False, submitted_files: list[str] | None = None) -> dict:
    app = get_application(store, identifier)
    if status not in TRANSITIONS or status not in TRANSITIONS[app["status"]]:
        raise Error(f"Invalid transition {app['status']} → {status}; allowed: {', '.join(sorted(TRANSITIONS[app['status']])) or 'terminal state'}")
    try:
        day = date.fromisoformat(occurred_on)
    except ValueError as exc:
        raise Error("Event date must be YYYY-MM-DD") from exc
    if day > date.today():
        raise Error("An outcome/submission event cannot be in the future; use a deadline or interview schedule instead")
    if not note.strip():
        raise Error("Record a note/source for the event")
    data = dict(app["data"])
    directory = store.root / data["directory"]
    archive_relative = None
    if status in {"drafted", "submitted"}:
        verification = verify_application(store, identifier)
        if verification["state"] == "fail" or verification["state"] == "needs_review" and not allow_unknown:
            raise Error("Application verification is " + verification["state"] + "; resolve failures, or explicitly record --allow-unknown for unresolved eligibility/requirements only")
        if status == "submitted":
            requirements = json.loads((directory / "requirements.json").read_text())
            chosen = list(submitted_files) if submitted_files else [("rendered/" + Path(name).stem + ".pdf") if requirements.get("documents", {}).get(name, {}).get("require_pdf") else name for name in data["documents"]]
            if submitted_files is None:
                chosen += [attachment["file"] for attachment in data.get("attachments", []) if attachment["file"] not in chosen]
            if any(name not in verification["document_hashes"] for name in chosen):
                raise Error("Submitted files must be exact reviewed artifacts. Set require_pdf for submitted PDFs and review their hashes first")
            archive_relative = f"{data['directory']}/submissions/{occurred_on}-{digest(now() + json_text(verification))[:10]}"
            archive = store.root / archive_relative
            archive.mkdir(parents=True, exist_ok=False)
            files = list(dict.fromkeys(chosen + data["documents"] + ["profile.snapshot.json", "opportunity.snapshot.json", "posting.txt", "requirements.json", "claims.json", "review.json", "verification.json"]))
            if data.get("rubric_sha256"):
                files.append("rubric.snapshot.json")
            manifest = {}
            for filename in files:
                path = contained(directory, filename)
                if path.is_file():
                    content = path.read_bytes()
                    atomic_write(archive / filename, content)
                    manifest[filename] = digest(content)
            registry = json.loads((directory / "claims.json").read_text())
            external_items = list(requirements.get("external_evidence", [])) + [item for claim in registry.get("claims", []) for item in claim.get("external_evidence", [])]
            evidence_map = []
            for item in external_items:
                source_path = verify_external(store.root, item)
                relative = "supporting-evidence/" + item["sha256"] + ".txt"
                content = source_path.read_bytes()
                atomic_write(archive / relative, content)
                manifest[relative] = digest(content)
                evidence_map.append({"original_file": item["file"], "archived_file": relative, "url": item["url"], "sha256": item["sha256"]})
            manifest_text = json_text({"application_id": app["id"], "submitted_on": occurred_on, "recorded_at": now(), "source": note,
                                      "opportunity_family": data.get("opportunity_family", "phd"), "rubric": data.get("rubric"),
                                      "submitted_files": chosen, "support_files": [name for name in manifest if name not in chosen], "external_evidence": evidence_map, "files": manifest})
            atomic_write(archive / "manifest.json", manifest_text)
            data["submission"] = {"date": occurred_on, "archive": archive_relative, "source": note, "allow_unknown": allow_unknown,
                                  "files": chosen, "manifest_sha256": digest(manifest_text)}
    with store.transaction():
        store.db.execute("UPDATE applications SET status=?,updated_at=?,data=? WHERE id=?", (status, now(), json_text(data), app["id"]))
        store.event(app["id"], "status", {"from": app["status"], "to": status, "occurred_on": occurred_on, "note": note, "archive": archive_relative, "allow_unknown": allow_unknown})
    return get_application(store, app["id"])


def attach_document(store: Store, identifier: str, source: Path, kind: str) -> dict:
    app = get_application(store, identifier)
    if app["status"] not in {"preparing", "drafted"}:
        raise Error("Attach files during preparation; submitted archives are immutable")
    if kind not in {"transcript", "diploma", "writing_sample", "portfolio", "language_test", "reference", "other"}:
        raise Error("Unknown attachment kind")
    if not source.is_file() or source.stat().st_size > 30 * 1024 * 1024:
        raise Error("Attachment missing or larger than 30 MiB")
    from .core import slug
    content = source.read_bytes()
    sha = digest(content)
    relative = "attachments/" + slug(source.stem) + "-" + sha[:8] + source.suffix.lower()
    if any(item["file"] == relative for item in app["data"].get("attachments", [])):
        raise Error("This attachment is already registered")
    directory = store.root / app["data"]["directory"]
    atomic_write(directory / relative, content)
    entry = {"file": relative, "kind": kind, "sha256": sha, "original_name": source.name, "registered_at": now()}
    data = dict(app["data"])
    data.setdefault("attachments", []).append(entry)
    with store.transaction():
        store.db.execute("UPDATE applications SET data=?,updated_at=? WHERE id=?", (json_text(data), now(), app["id"]))
        store.event(app["id"], "attachment_added", entry)
    return entry


def record_event(store: Store, identifier: str, kind: str, details: dict) -> dict:
    app = get_application(store, identifier)
    if kind not in {"note", "contact_sent", "followup_sent", "interview_scheduled", "interview_feedback", "assessment_due", "reference_requested", "reference_received"}:
        raise Error("Unknown event kind")
    if not isinstance(details, dict) or not details.get("note"):
        raise Error("Event details require a source/note")
    if "occurred_on" in details:
        try:
            if not isinstance(details["occurred_on"], str):
                raise ValueError("date must be text")
            day = date.fromisoformat(details["occurred_on"])
            if day.isoformat() != details["occurred_on"] or day > date.today():
                raise ValueError("future event")
        except (ValueError, TypeError) as exc:
            raise Error("Actual event occurred_on must be a nonfuture YYYY-MM-DD date; use at for a scheduled event") from exc
    if kind in {"interview_scheduled", "assessment_due"}:
        try:
            if not isinstance(details.get("at"), str):
                raise ValueError("timestamp must be text")
            timestamp = datetime.fromisoformat(details["at"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("timezone missing")
        except (ValueError, KeyError, TypeError) as exc:
            raise Error("Scheduled event requires an ISO at timestamp with timezone") from exc
    with store.transaction():
        store.event(app["id"], kind, details)
    return get_application(store, app["id"])


def set_referees(store: Store, identifier: str, referees: list[dict]) -> dict:
    app = get_application(store, identifier)
    if not isinstance(referees, list):
        raise Error("Referees must be an array")
    names = set()
    for person in referees:
        if not isinstance(person, dict) or not person.get("name") or not isinstance(person.get("permission_confirmed"), bool):
            raise Error("Each referee requires name and permission_confirmed (true/false)")
        if person["name"] in names:
            raise Error("Duplicate referee name")
        names.add(person["name"])
        for field in ("requested_on", "due_on", "received_on"):
            if person.get(field):
                try:
                    date.fromisoformat(person[field])
                except ValueError as exc:
                    raise Error(f"Referee {field} must be YYYY-MM-DD") from exc
    data = dict(app["data"])
    data["referees"] = referees
    with store.transaction():
        store.db.execute("UPDATE applications SET data=?,updated_at=? WHERE id=?", (json_text(data), now(), app["id"]))
        store.event(app["id"], "referees_updated", {"count": len(referees), "messages_sent": False})
    return get_application(store, app["id"])


def followups(store: Store, profile: dict, identifier: str | None = None, *, draft: bool = False) -> list[dict]:
    days = profile["preferences"].get("followup_after_days", 14)
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 365:
        raise Error("followup_after_days must be 1–365")
    apps = [get_application(store, identifier)] if identifier else list_applications(store)
    result = []
    today = date.today()
    current_time = datetime.now(timezone.utc)

    def actual_day(value):
        # Recording/import time is not evidence of when communication occurred.
        try:
            parsed = date.fromisoformat(value) if isinstance(value, str) else None
        except ValueError:
            return None
        return parsed if parsed is not None and parsed <= today else None

    for app in apps:
        if app["status"] not in {"submitted", "assessment", "interview", "waitlisted"} or not app["data"].get("submission"):
            continue
        sent = [e for e in app["events"] if e["kind"] == "followup_sent" and
                ("occurred_on" not in e["data"] or actual_day(e["data"]["occurred_on"]) is not None)]
        if len(sent) >= 2:
            continue
        submitted_on = actual_day(app["data"]["submission"].get("date"))
        if submitted_on is None:
            continue
        last_dates = [submitted_on]
        scheduled_dates = []
        pending_stage = False
        for event in app["events"]:
            details = event["data"]
            if event["kind"] in {"interview_scheduled", "assessment_due"}:
                try:
                    at = datetime.fromisoformat(details["at"].replace("Z", "+00:00"))
                    if at.tzinfo is None:
                        continue
                except (KeyError, TypeError, ValueError, AttributeError):
                    continue
                pending_stage = pending_stage or at >= current_time
                scheduled_dates.append(at.astimezone().date())
            elif event["kind"] in {"followup_sent", "interview_feedback", "contact_sent"} or (
                event["kind"] == "status" and details.get("to") in {"assessment", "interview", "waitlisted"}
            ):
                occurred = actual_day(details.get("occurred_on"))
                if occurred is not None:
                    last_dates.append(occurred)
        # A scheduled stage is not proof of completed contact. It does establish
        # that a generic status inquiry should wait until after that stage.
        if pending_stage or scheduled_dates and (today - max(scheduled_dates)).days < days:
            continue
        age = (today - max(last_dates)).days
        if age < days:
            continue
        item = {"application_id": app["id"], "title": app["data"]["title"], "days_since_contact": age, "followups_recorded": len(sent), "action": "draft_only"}
        if draft:
            filename = f"followup-{len(sent) + 1}.md"
            path = store.root / app["data"]["directory"] / filename
            if not path.exists():
                atomic_write(path, f"Subject: Application update — {app['data']['title']}\n\nDear admissions/recruitment team,\n\n"
                             + f"I am writing to ask whether there is an update on my application for {app['data']['title']}, submitted on {app['data']['submission']['date']}. "
                             + "I remain interested in the opportunity and would be happy to provide any additional information.\n\n"
                             + "Thank you for your time.\n\n" + (profile["identity"].get("name") or "[[CANDIDATE_NAME]]") + "\n")
            item["file"] = str(path)
        result.append(item)
    return result


def _verified_submission_archive(store: Store, app: dict) -> Path:
    from .core import read_json

    submission = app["data"]["submission"]
    directory = contained(store.root, app["data"]["directory"])
    try:
        if not isinstance(submission, dict) or not isinstance(submission.get("archive"), str):
            raise Error("Submission archive metadata is missing or invalid")
        if Path(submission["archive"]).is_absolute() or ".." in Path(submission["archive"]).parts or "\\" in submission["archive"]:
            raise Error("Submission archive contains an unsafe directory path")
        base = contained(store.root, submission["archive"])
        archive_root = (directory / "submissions").resolve()
        if base == archive_root or not base.is_relative_to(archive_root):
            raise Error("Submission archive must be inside this application's submissions directory")
        manifest_path = contained(base, "manifest.json")
        manifest_bytes = manifest_path.read_bytes()
        expected = submission.get("manifest_sha256")
        if expected is not None and digest(manifest_bytes) != expected:
            raise Error("Submission manifest digest does not match the recorded submission")
        manifest = read_json(manifest_path)
        if (not isinstance(manifest, dict) or manifest.get("application_id") != app["id"] or
                manifest.get("submitted_on") != submission.get("date") or manifest.get("source") != submission.get("source")):
            raise Error("Submission manifest identity/date/source does not match the recorded submission")
        files = manifest.get("files")
        if not isinstance(files, dict) or not files:
            raise Error("Submission manifest requires a nonempty files inventory")
        for name in ("submitted_files", "support_files"):
            if not isinstance(manifest.get(name), list) or any(not isinstance(item, str) for item in manifest[name]):
                raise Error("Submission manifest requires submitted_files and support_files inventories")
        submitted = set(manifest["submitted_files"])
        supporting = set(manifest["support_files"])
        if submitted != set(submission.get("files", [])) or submitted & supporting or submitted | supporting != set(files):
            raise Error("Submission manifest file inventories do not match the recorded submission")
        required = set(app["data"]["documents"]) | submitted | {
            "profile.snapshot.json", "opportunity.snapshot.json", "posting.txt", "requirements.json", "claims.json", "review.json", "verification.json",
        }
        if app["data"].get("rubric_sha256"):
            required.add("rubric.snapshot.json")
            if manifest.get("opportunity_family") != app["data"].get("opportunity_family") or manifest.get("rubric") != app["data"].get("rubric"):
                raise Error("Submission manifest family/rubric differs from the recorded application")
        if not required <= set(files):
            raise Error("Submission manifest is missing required archived files")
        for filename, expected_digest in files.items():
            if not isinstance(filename, str) or Path(filename).is_absolute() or ".." in Path(filename).parts or "\\" in filename:
                raise Error("Submission manifest contains an unsafe file path")
            if not isinstance(expected_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
                raise Error("Submission manifest contains an invalid file digest")
            path = contained(base, filename)
            if not path.is_file() or digest(path.read_bytes()) != expected_digest:
                raise Error(f"Submission archive file is missing or its digest changed: {filename}")
        external = manifest.get("external_evidence", [])
        if not isinstance(external, list):
            raise Error("Submission manifest external_evidence must be an array")
        for item in external:
            if not isinstance(item, dict) or item.get("archived_file") not in files or files[item["archived_file"]] != item.get("sha256"):
                raise Error("Submission manifest external evidence does not match its archived file")
        frozen_profile = read_json(base / "profile.snapshot.json")
        original = read_json(base / "opportunity.snapshot.json")
        if fingerprint(frozen_profile) != app["data"]["profile_sha256"] or digest((base / "opportunity.snapshot.json").read_bytes()) != app["data"]["opportunity_snapshot_sha256"]:
            raise Error("Submission archive source/profile differs from the recorded application")
        if digest((base / "posting.txt").read_bytes()) != original["snapshot"]["metadata"]["text_sha256"]:
            raise Error("Submission archive posting differs from its recorded snapshot")
        if app["data"].get("rubric_sha256") and digest((base / "rubric.snapshot.json").read_bytes()) != app["data"]["rubric_sha256"]:
            raise Error("Submission archive rubric differs from its recorded snapshot")
        return base
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise Error(f"Cannot verify submission archive: {exc}") from exc


def interview_packet(store: Store, identifier: str) -> dict:
    app = get_application(store, identifier)
    directory = contained(store.root, app["data"]["directory"])
    target = directory / "interview.md"
    if target.exists():
        raise Error("Interview preparation already exists; edit it or archive it before creating a new round")
    submission = app["data"].get("submission")
    base = _verified_submission_archive(store, app) if submission else directory
    posting = (base / "posting.txt").read_text()
    profile = json.loads((base / "profile.snapshot.json").read_text())
    original = json.loads((base / "opportunity.snapshot.json").read_text())
    mode = family(merged(original))
    if mode == "school":
        pitch = ("## Learning goals and preparation\n\n[[Explain why this curriculum or field activity fits your questions, "
                 "your evidenced prerequisites and what you want to learn during the event.]]\n\n"
                 "## Participation plan\n\n[[Prepare a concise explanation of actual availability, learning needs and peer contribution. "
                 "Discuss a project or research proposal only if the organisers request one.]]\n\n")
        likely = ("- Which part of the programme addresses your learning goals?\n"
                  "- What preparation and practical experience will you bring?\n"
                  "- What do you want to learn, and how will you use it afterward?\n")
        questions = ("- Which prerequisites, exercises and preparation are expected?\n"
                     "- What are the participation dates, attendance requirements and accessibility arrangements?\n"
                     "- Which fees, housing and travel costs are covered, and when is financial aid decided?\n")
        note = "Selection interviews are optional for schools. This requested preparation does not establish that an interview is required or scheduled.\n\n"
    elif mode == "internship":
        pitch = ("## Research contribution and learning goals\n\n[[Prepare a 60-second and a 3-minute account of relevant, "
                 "evidenced work and a realistic contribution within the placement period.]]\n\n"
                 "## Methods, scope and collaboration\n\n[[Discuss suitable methods, alternatives, limitations, ethics where relevant, "
                 "mentoring needs and milestones within the actual internship dates.]]\n\n")
        likely = ("- Which experience prepares you for this specific research task?\n"
                  "- What could you achieve during the advertised period, and what support would you need?\n"
                  "- How would you investigate an unexpected result and communicate it to the team?\n")
        questions = ("- How are mentoring, feedback, project scope and evaluation organised?\n"
                     "- Which dates, enrolment, home-institution approval and work-authorisation conditions apply?\n"
                     "- What compensation, housing and travel support are provided, and under which conditions?\n")
        note = "Use the host's actual selection process; no interview is inferred from a placement listing.\n\n"
    else:
        pitch = ("## Research pitch\n\n[[WRITE a 60-second and a 3-minute explanation grounded in the submitted statement.]]\n\n"
                 "## Research questions and methodological choices\n\n[[Compare the project's question, evidence, methods, alternatives, limitations, ethics and feasibility.]]\n\n")
        likely = ("- Why this problem and this research environment?\n- What is your strongest relevant contribution?\n"
                  "- How would you investigate a negative or ambiguous result?\n- What do you need to learn, and how would you learn it?\n")
        questions = ("- How are supervision, feedback and progress reviews organised?\n"
                     "- What resources, training, teaching and fieldwork are expected?\n"
                     "- What exactly does the funding cover, for how long, and under which conditions?\n")
        note = ""
    content = ("# Interview preparation\n\n" + app["data"]["title"] + "\n\n"
               + f"Materials: {base.relative_to(store.root)}\n\nUse the exact submitted version; distinguish proposed work from completed work.\n\n"
               + note + pitch
               + "## Examples from candidate evidence\n\n")
    for fact in profile["facts"]:
        content += f"- {fact['claim']} (source: {fact['source']})\n"
    content += ("\n## Likely questions\n\n" + likely
                + "\n## Questions for the panel\n\n" + questions
                + "\n## Panel and recent work\n\n[[Verify names, affiliations and relevant recent outputs from primary sources; do not invent publications.]]\n\n"
                + "## Mock interview and feedback\n\n[[Run one question at a time. Record answers, evidence gaps and concrete revisions.]]\n\n"
                + "## Archived posting\n\n" + posting + "\n")
    atomic_write(target, content)
    return {"application_id": app["id"], "opportunity_family": mode, "path": str(target),
            "basis": "submitted_archive" if submission else "current_draft", "state": "preparation_scaffold"}
