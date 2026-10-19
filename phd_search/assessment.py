from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone
from pathlib import Path

from .core import Error, digest, json_text, now
from .extract import deadline_state, parse_deadline
from .opportunities import (
    COMPONENTS,
    RUBRICS,
    TYPES,
    deadline_entries,
    family,
    normalize_deadlines,
    primary_application,
    rubric_for,
    rubric_identity,
    validate_opportunity_fields,
)
from .profile import fingerprint
from .store import Store

DIMENSIONS = RUBRICS["phd"]["dimensions"]
ANNOTATED_FIELDS = {"title", "institution", "country", "city", "reference", "opportunity_type", "funding", "requirements",
                    "supervisors", "topics", "methods", "skills", "deadline", "deadlines", "start_date", "end_date", "duration_months",
                    "duration_days", "mode", "application_status", "programme_id", "edition", "session_id", "official_url", "documents", "contact"}
FUNDING_STATUSES = {"fully_funded", "partial", "self_funded", "unknown"}
DEGREES = {"bachelor": 1, "master": 2, "doctorate": 3, "other": 0}
CEFR = {level: index for index, level in enumerate(("A1", "A2", "B1", "B2", "C1", "C2"))}


def merged(record: dict) -> dict:
    result = dict(record["data"])
    annotations = record["annotations"]
    if annotations.get("snapshot_sha256") == record["snapshot"]["sha256"]:
        result.update(annotations.get("values", {}))
    return result


def context_hash(record: dict) -> str:
    return digest(json_text({"data": record["data"], "annotations": record["annotations"]}))


def validate_annotations(store: Store, identifier: str, annotations: dict) -> dict:
    record = store.get(identifier)
    if not isinstance(annotations, dict) or not isinstance(annotations.get("values"), dict) or not isinstance(annotations.get("evidence"), dict):
        raise Error("Annotations require values and evidence objects; see docs/data-model.md")
    unknown = set(annotations["values"]) - ANNOTATED_FIELDS
    if unknown:
        raise Error("Unknown annotated fields: " + ", ".join(sorted(unknown)))
    identity = record["snapshot"].get("metadata", {}).get("identity_context", {})
    if identity:
        for key, identity_key in (("edition", "edition"), ("session_id", "session")):
            if key in annotations["values"] and annotations["values"][key] != identity.get(identity_key):
                raise Error(f"{key} cannot change the imported edition/session identity; import with the correct --edition/--session labels")
    text = (store.root / record["snapshot"]["text_path"]).read_text()
    for key, value in annotations["values"].items():
        support = annotations["evidence"].get(key)
        if not isinstance(support, dict):
            raise Error(f"Missing evidence for {key}")
        if support.get("basis") == "user_confirmed":
            if not support.get("note"):
                raise Error(f"User-confirmed {key} requires a note naming the confirmation")
        elif support.get("quote") and isinstance(support["quote"], str) and support["quote"] in text:
            if support.get("evidence_sha256") != record["snapshot"]["sha256"]:
                raise Error(f"{key} evidence digest must match the current posting snapshot")
        else:
            raise Error(f"{key} must quote the current posting verbatim or carry an explicit user confirmation")
        if key in {"topics", "methods", "skills", "supervisors", "documents"} and (not isinstance(value, list) or any(not isinstance(x, str) for x in value)):
            raise Error(f"{key} must be an array of strings")
        if key == "requirements" and not isinstance(value, dict):
            raise Error("requirements must be an object")
        if key == "requirements":
            if not isinstance(value.get("reviewed", False), bool):
                raise Error("requirements.reviewed must be boolean")
            for field in ("allowed_citizenships", "excluded_citizenships", "languages", "other"):
                if not isinstance(value.get(field, []), list):
                    raise Error(f"requirements.{field} must be an array")
            for rule in value.get("languages", []):
                if not isinstance(rule, dict) or not isinstance(rule.get("name"), str):
                    raise Error("Language requirements require name")
            for field in ("allowed_citizenships", "excluded_citizenships"):
                if any(not isinstance(item, str) for item in value.get(field, [])):
                    raise Error(f"requirements.{field} must contain strings")
        if key == "funding" and value is not None:
            if not isinstance(value, dict) or not isinstance(value.get("status"), str) or value.get("status") not in FUNDING_STATUSES:
                raise Error("funding requires status: fully_funded, partial, self_funded or unknown")
            amount = value.get("amount")
            if amount is not None and (isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount < 0):
                raise Error("Funding amount must be finite and nonnegative")
            if value.get("period") not in (None, "day", "week", "month", "year", "total"):
                raise Error("Funding period must be day, week, month, year, total or null")
        if key == "opportunity_type" and (not isinstance(value, str) or value not in TYPES):
            raise Error("Unknown opportunity type")
        if key in {"title", "institution", "country", "city", "reference", "official_url", "contact"} and value is not None and not isinstance(value, str):
            raise Error(f"{key} must be a string or null")
        if key == "deadline" and value is not None:
            if isinstance(value, str):
                annotations["values"][key] = parse_deadline(value)
            elif not isinstance(value, dict) or not value.get("raw"):
                raise Error("deadline must be an ISO string or parsed deadline object with raw source text")
            else:
                deadline_state(value)
        if key == "deadlines":
            annotations["values"][key] = normalize_deadlines(value)
    candidate = {**record["data"], **annotations["values"]}
    errors = validate_opportunity_fields(candidate)
    if errors:
        raise Error("Invalid opportunity fields: " + "; ".join(errors))
    annotations["updated_at"] = now()
    annotations["snapshot_sha256"] = record["snapshot"]["sha256"]
    return store.annotate(identifier, annotations)


def screen(record: dict, profile: dict, *, at: datetime | None = None) -> dict:
    data = merged(record)
    preferences = profile["preferences"]
    gates = []

    def add(name, state, reason):
        gates.append({"name": name, "state": state, "reason": reason})

    application_status = data.get("application_status")
    if application_status:
        add("application_status", "fail" if application_status == "closed" else "pass" if application_status in {"open", "rolling"} else "unknown",
            "Applications are not yet open" if application_status == "upcoming" else application_status)
    entries = deadline_entries(data)
    primary = primary_application(data)
    deadline = deadline_state(primary["deadline"] if primary else data.get("deadline"), at)
    add("deadline", "fail" if deadline["state"] == "expired" else "unknown" if deadline["state"] == "unknown" else "pass", deadline)
    dated = []
    for entry in entries:
        state = deadline_state(entry["deadline"], at)
        dated.append({**entry, "state": state})
        if primary and entry["id"] == primary["id"]:
            continue
        required = entry["required"] or entry["kind"] == "funding" and preferences.get("require_full_funding") is True
        if required:
            add("deadline:" + entry["id"], "fail" if state["state"] == "expired" else "unknown" if state["state"] == "unknown" else "pass", state)
    country = data.get("country")
    included = {x.casefold() for x in preferences["countries"]}
    excluded = {x.casefold() for x in preferences["excluded_countries"]}
    if included or excluded:
        if not isinstance(country, str):
            add("country", "unknown", "Country is not established")
        else:
            key = country.casefold()
            # Do not veto 'Germany' against 'DE'; canonicalise in sourced annotations.
            comparable = all((len(x) == 2) == (len(key) == 2) for x in included | excluded)
            if not comparable:
                add("country", "unknown", "Country labels use different representations; annotate an ISO code")
            else:
                add("country", "fail" if key in excluded or included and key not in included else "pass", country)
    if preferences["opportunity_types"]:
        kind = data.get("opportunity_type")
        add("opportunity_type", "unknown" if not kind else "pass" if kind in preferences["opportunity_types"] else "fail", kind)
    funding = data.get("funding") or {}
    if preferences.get("require_full_funding") is True:
        status = funding.get("status", "unknown")
        if family(data) != "phd" or "components" in funding:
            parts = funding.get("components", {})
            sourced = _field_sourced(record, "funding")
            values = {name: (parts.get(name) or {}).get("coverage", "unknown") for name in COMPONENTS}
            if status in {"partial", "self_funded"} or any(value in {"partial", "not_covered"} for value in values.values()):
                add("funding", "fail", "Recorded funding leaves part of the relevant participation costs uncovered")
            elif not sourced or status == "unknown" or any(value == "unknown" for value in values.values()):
                add("funding", "unknown", "Source-backed coverage or explicit non-applicability is required for tuition, registration, living, accommodation and travel")
            elif all(value == "not_applicable" for value in values.values()):
                add("funding", "unknown", "All costs marked not applicable do not establish financial support")
            else:
                add("funding", "pass", "Source-backed participation costs are covered or explicitly not applicable; award eligibility and availability remain separate")
        elif status == "unknown":
            add("funding", "unknown", "Funding and fee coverage are not verified")
        elif status != "fully_funded":
            add("funding", "fail", f"Funding is {status}")
        elif funding.get("tuition_covered") is not True:
            add("funding", "unknown" if funding.get("tuition_covered") is None else "fail", "Full tuition coverage must be explicit")
        else:
            add("funding", "pass", "Living support and tuition coverage recorded; check candidate eligibility separately")
    minimum = preferences.get("minimum_funding")
    if minimum:
        if not isinstance(minimum, dict) or not isinstance(minimum.get("amount"), (int, float)):
            raise Error("preferences.minimum_funding requires amount, currency, period and basis")
        comparable = (funding.get("currency") == minimum.get("currency") and funding.get("period") == minimum.get("period")
                      and funding.get("basis") == minimum.get("basis") and funding.get("amount") is not None)
        add("minimum_funding", "pass" if comparable and funding["amount"] >= minimum["amount"] else "fail" if comparable else "unknown",
            "Compared only when currency, period and gross/net basis match; no exchange rate or tax estimate inferred")
    requirements = data.get("requirements") or {}
    add("requirements_reviewed", "pass" if requirements.get("reviewed") is True else "unknown",
        "Requirements have been explicitly reviewed" if requirements.get("reviewed") is True else "The full eligibility requirements have not been reviewed; metadata alone cannot establish eligibility")
    degree = requirements.get("degree")
    if degree:
        if not isinstance(degree, str) or degree not in DEGREES:
            add("degree", "unknown", "Degree requirement needs interpretation")
        else:
            awarded = [x for x in profile["education"] if x.get("awarded_on") and date.fromisoformat(x["awarded_on"]) <= (at or datetime.now(timezone.utc)).date()]
            meets = any(DEGREES.get(x.get("level"), 0) >= DEGREES[degree] for x in awarded)
            add("degree", "pass" if meets else "unknown", "Awarded qualification meets level" if meets else "No confirmed awarded qualification meets this level; equivalence or expected completion needs review")
    for requirement in requirements.get("languages", []):
        lang = requirement.get("name", "")
        candidate = next((x for x in profile["languages"] if x.get("name", "").casefold() == lang.casefold()), None)
        if candidate is None:
            add("language:" + lang, "unknown", "No declared language evidence")
            continue
        if requirement.get("test"):
            test = requirement["test"]
            score = next((x for x in candidate.get("tests", []) if x.get("name") == test and x.get("valid_until") and x["valid_until"] >= (at or datetime.now(timezone.utc)).date().isoformat()), None)
            if score and isinstance(score.get("score"), (int, float)) and isinstance(requirement.get("minimum_score"), (int, float)):
                add("language:" + lang, "pass" if score["score"] >= requirement["minimum_score"] else "fail", "Compared the same test and a recorded validity date; subscore requirements need review")
            else:
                add("language:" + lang, "unknown", "Required test, validity, minimum or exemption is not verified")
        elif requirement.get("cefr") in CEFR and candidate.get("cefr") in CEFR:
            add("language:" + lang, "pass" if CEFR[candidate["cefr"]] >= CEFR[requirement["cefr"]] else "fail", "Compared declared CEFR levels")
        else:
            add("language:" + lang, "unknown", "Language levels are not directly comparable")
    citizenships = {x.casefold() for x in preferences.get("citizenships", [])}
    allowed = {x.casefold() for x in requirements.get("allowed_citizenships", [])}
    disallowed = {x.casefold() for x in requirements.get("excluded_citizenships", [])}
    if allowed or disallowed:
        state = "unknown" if not citizenships else "pass" if (not allowed or citizenships & allowed) and not citizenships & disallowed else "fail"
        add("citizenship", state, "Literal recorded citizenship restriction; ambiguous or dual-nationality rules require source review")
    for rule in requirements.get("other", []):
        if isinstance(rule, dict):
            add("requirement:" + str(rule.get("name", "unspecified")), rule.get("verdict") if rule.get("verdict") in ("pass", "fail") else "unknown", rule.get("reason", "Requires review"))
    if requirements.get("mobility"):
        add("mobility", "unknown", "Evaluate the exact sourced mobility rule against dated residence/activity history; do not infer eligibility from nationality")
    if preferences.get("start_after") or preferences.get("start_before"):
        start = data.get("start_date")
        if not start:
            add("start_date", "unknown", "Start date is not confirmed")
        else:
            try:
                start_day = date.fromisoformat(start)
                outside = bool(preferences.get("start_after") and start_day < date.fromisoformat(preferences["start_after"]) or
                               preferences.get("start_before") and start_day > date.fromisoformat(preferences["start_before"]))
                add("start_date", "fail" if outside else "pass", start)
            except (ValueError, TypeError):
                add("start_date", "unknown", "Start date needs interpretation")
    _screen_participation(record, data, profile, add, at=at)
    if record["annotations"] and record["annotations"].get("snapshot_sha256") != record["snapshot"]["sha256"]:
        add("annotations_current", "unknown", "Posting changed after annotations; verify requirements and funding again")
    overall = "fail" if any(g["state"] == "fail" for g in gates) else "unknown" if any(g["state"] == "unknown" for g in gates) else "pass"
    return {"verdict": overall, "gates": gates, "deadline": deadline, "deadlines": dated, "family": family(data),
            "scope": "Only configured preferences and explicit recorded requirements; absence of a gate is not proof of eligibility"}


def _field_sourced(record: dict, field: str) -> bool:
    annotations = record.get("annotations", {})
    if annotations.get("snapshot_sha256") == record["snapshot"]["sha256"] and field in annotations.get("values", {}):
        support = annotations.get("evidence", {}).get(field, {})
        return bool(support.get("quote") and support.get("evidence_sha256") == record["snapshot"]["sha256"] or
                    support.get("basis") == "user_confirmed" and support.get("note"))
    support = record["data"].get("provenance", {}).get(field, {})
    return isinstance(support, dict) and bool(support.get("quote") and support.get("source"))


def _confirmed(value: dict) -> bool:
    return isinstance(value, dict) and value.get("confirmed") is True and isinstance(value.get("source"), str) and bool(value["source"].strip())


def _date(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _screen_participation(record, data, profile, add, *, at=None):
    requirements = data.get("requirements") or {}
    preferences = profile["preferences"]
    today = (at or datetime.now(timezone.utc)).date()
    start, end = _date(data.get("start_date")), _date(data.get("end_date"))
    enrollment = requirements.get("enrollment") or {}
    if enrollment:
        active, participation, uncertain, future_uncertain = [], [], False, False
        for education in profile["education"]:
            item = education.get("enrollment", {})
            first, last = _date(item.get("start_date")), _date(item.get("end_date"))
            if not _confirmed(item):
                if not education.get("awarded_on"):
                    uncertain = True
                continue
            if item.get("status") == "enrolled" and (not first or first <= today) and (not last or last >= today):
                active.append((education.get("level"), item, first, last))
            elif item.get("status") in {"unknown", "on_leave"}:
                uncertain = True
            if item.get("status") == "enrolled" and start:
                if (not first or first <= (end or start)) and (not last or last >= start):
                    participation.append((education.get("level"), item, first, last))
            elif item.get("status") == "enrolled" and first and first > today:
                future_uncertain = True
        excluded = set(enrollment.get("excluded_levels", []))
        allowed = set(enrollment.get("allowed_levels", []))
        if excluded:
            add("enrollment:excluded_levels", "fail" if any(level in excluded for level, *_ in active + participation) else "unknown" if uncertain or future_uncertain or not active else "pass",
                "Compared confirmed enrollment now and during the recorded participation interval, independently of awarded qualifications; unclear institutional reference dates require review")
        candidates = [item for item in active if not allowed or item[0] in allowed]
        if enrollment.get("required") or allowed or enrollment.get("through_end"):
            add("enrollment:allowed_levels", "pass" if candidates else "unknown" if uncertain or not active else "fail",
                "Current enrollment must match the permitted programme levels; a higher awarded degree is not a substitute")
        if enrollment.get("through_end"):
            if not start or not end:
                verdict = "unknown"
            elif any(first and first <= start and last and last >= end for _, _, first, last in candidates):
                verdict = "pass"
            elif candidates and all(last and last < end or first and first > start for _, _, first, last in candidates):
                verdict = "fail"
            else:
                verdict = "unknown"
            add("enrollment:through_end", verdict, "Confirmed enrollment dates must cover the complete participation interval; missing end dates do not prove continued enrollment")
        if enrollment.get("return_to_study"):
            _confirmation_gate(preferences, "return_to_study", add, data, end or start or today, beginning=end or start)
    for field in ("work_authorization", "home_approval"):
        if requirements.get(field + "_required"):
            _confirmation_gate(preferences, field, add, data, end or start or today, beginning=start)
    availability = preferences.get("availability", [])
    if availability:
        intervals = [(_date(item.get("start_date")), _date(item.get("end_date"))) for item in availability if _confirmed(item)]
        intervals = sorted((first, last) for first, last in intervals if first and last)
        if not start or not end or not intervals:
            state = "unknown"
        else:
            covered_end = None
            for first, last in intervals:
                if first <= start <= last or covered_end and first.toordinal() <= covered_end.toordinal() + 1:
                    covered_end = max(covered_end or last, last)
            state = "pass" if covered_end and covered_end >= end else "fail"
        add("availability", state, "Participation dates must fit wholly inside confirmed availability intervals")
    limits = requirements.get("duration_days")
    preferred_limits = preferences.get("duration_days")
    if limits or preferred_limits or family(data) == "internship":
        duration = (end - start).days + 1 if start and end else data.get("duration_days")
        if duration is None:
            state = "unknown"
        elif duration <= 0:
            state = "fail"
        else:
            state = "fail" if any(bound and (duration < bound.get("min", 0) or duration > bound.get("max", math.inf)) for bound in (limits, preferred_limits)) else "pass"
        add("duration", state, "Exact inclusive calendar days are compared where sourced; months are not converted into invented day counts")


def _confirmation_gate(preferences, field, add, data, reference, *, beginning=None):
    value = preferences.get(field)
    state = "unknown"
    if _confirmed(value) and isinstance(value.get("value"), bool):
        state = "pass" if value["value"] else "fail"
        if state == "pass" and field == "work_authorization":
            country = data.get("country")
            if not country or not value.get("country") or value["country"].casefold() != country.casefold():
                state = "unknown"
        if state == "pass" and value.get("valid_until"):
            last = _date(value["valid_until"])
            state = "unknown" if last is None else "fail" if last < reference else "pass"
        if state == "pass" and value.get("valid_from"):
            first = _date(value["valid_from"])
            state = "unknown" if first is None or beginning is None else "fail" if first > beginning else "pass"
    add(field, state, "Requires an explicit source-linked candidate confirmation for this route and applicable dates; nationality is not work authorization")


def pointer(profile: dict, reference: str):
    if not isinstance(reference, str) or not reference.startswith("/"):
        raise Error("Profile evidence references must be JSON pointers beginning with /")
    value = profile
    try:
        for part in reference[1:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            value = value[int(part)] if isinstance(value, list) else value[part]
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise Error(f"Unknown profile reference: {reference}") from exc
    if value is None or value == "" or value == [] or value == {}:
        raise Error(f"Empty profile evidence: {reference}")
    return value


def assessment_template(record: dict, profile: dict) -> dict:
    rubric = rubric_for(merged(record))
    return {"schema_version": 1, "opportunity_id": record["id"], "profile_sha256": fingerprint(profile),
            "evidence_sha256": record["snapshot"]["sha256"], "context_sha256": context_hash(record), "assessor": "",
            "rubric": rubric_identity(merged(record)),
            "method": "agent_semantic", "dimensions": {name: {"score": None, "reason": "Not assessed", "posting_quotes": [], "profile_refs": [], "external_evidence": []} for name in rubric["dimensions"]},
            "strengths": [], "gaps": [], "questions": [], "recommendation": "awaiting_assessment"}


def save_assessment(store: Store, identifier: str, profile: dict, data: dict) -> dict:
    record = store.get(identifier)
    template = assessment_template(record, profile)
    for key in ("opportunity_id", "profile_sha256", "evidence_sha256", "context_sha256"):
        if data.get(key) != template[key]:
            raise Error(f"Assessment {key} is stale or does not match the selected record")
    if not isinstance(data.get("assessor"), str) or not data["assessor"].strip():
        raise Error("Assessment requires an assessor label")
    if data.get("method") not in {"human", "agent_semantic"}:
        raise Error("Assessment method must be human or agent_semantic")
    expected_rubric = template["rubric"]
    actual_rubric = data.get("rubric", rubric_identity({}))
    if actual_rubric != expected_rubric:
        raise Error("Assessment rubric does not match the opportunity family and current version")
    weights = rubric_for(merged(record))["dimensions"]
    dimensions = data.get("dimensions")
    if not isinstance(dimensions, dict) or set(dimensions) != set(weights):
        raise Error("Assessment must cover exactly these dimensions: " + ", ".join(weights))
    posting = (store.root / record["snapshot"]["text_path"]).read_text()
    for name, entry in dimensions.items():
        if not isinstance(entry, dict):
            raise Error(f"{name} must be an object")
        score = entry.get("score")
        if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 5):
            raise Error(f"{name}.score must be null or a finite number from 0 to 5")
        if not entry.get("reason"):
            raise Error(f"{name} requires a reason, including when unknown")
        if not isinstance(entry.get("posting_quotes"), list) or not isinstance(entry.get("profile_refs"), list):
            raise Error(f"{name} requires posting_quotes and profile_refs arrays")
        for quote in entry["posting_quotes"]:
            if not isinstance(quote, str) or not quote.strip() or quote not in posting:
                raise Error(f"{name} has a posting quote absent from the evidence")
        for reference in entry["profile_refs"]:
            pointer(profile, reference)
        if score is not None:
            if not entry["posting_quotes"] and not entry.get("external_evidence"):
                raise Error(f"Scored {name} requires posting or archived external evidence")
            if name in {"research_fit", "project_fit", "methods", "preparedness", "learning_fit", "prerequisites", "practical_fit"} and not entry["profile_refs"]:
                raise Error(f"Scored {name} requires profile evidence")
        external_evidence = entry.get("external_evidence", [])
        if not isinstance(external_evidence, list):
            raise Error(f"{name}.external_evidence must be an array")
        for external in external_evidence:
            from .evidence import verify_external
            verify_external(store.root, external)
    with store.transaction():
        store.db.execute("INSERT INTO assessments(opportunity_id,profile_sha256,evidence_sha256,created_at,data) VALUES (?,?,?,?,?)",
                         (record["id"], fingerprint(profile), record["snapshot"]["sha256"], now(), json_text(data)))
    return ranking(store.get(record["id"]), profile, root=store.root)


def ranking(record: dict, profile: dict, *, root: Path | None = None) -> dict:
    data = merged(record)
    rubric = rubric_for(data)
    eligibility = screen(record, profile)
    assessment = record["assessment"]
    result = {"id": record["id"], "title": data["title"], "institution": data.get("institution"), "url": record["url"],
              "family": family(data), "rubric": rubric_identity(data), "rubric_id": rubric["id"], "comparison_group": f"{rubric['id']}:v{rubric['version']}",
              "comparison_scope": "Scores are comparable only within the same opportunity family and rubric version",
              "eligibility": eligibility, "assessment_state": "missing", "score": None, "score_interval": [0, 100],
              "coverage": 0, "strengths": [], "gaps": [], "last_verified": record["last_seen"]}
    if assessment:
        a = assessment["data"]
        issues = []
        if assessment["profile_sha256"] != fingerprint(profile):
            issues.append("Candidate profile changed after assessment")
        if assessment["evidence_sha256"] != record["snapshot"]["sha256"]:
            issues.append("Posting changed after assessment")
        if a.get("context_sha256") != context_hash(record):
            issues.append("Opportunity data or annotations changed after assessment")
        if a.get("rubric", rubric_identity({})) != rubric_identity(data):
            issues.append("Assessment rubric does not match the opportunity family and current version")
        if not isinstance(a.get("dimensions"), dict) or set(a["dimensions"]) != set(rubric["dimensions"]):
            issues.append("Assessment dimensions do not match the opportunity rubric")
        for name, entry in (a.get("dimensions") or {}).items():
            if not isinstance(entry, dict):
                issues.append(f"{name}: dimension must be an object")
                continue
            external_evidence = entry.get("external_evidence", [])
            if not isinstance(external_evidence, list):
                issues.append(f"{name}: external evidence must be an array")
                continue
            if external_evidence and root is None:
                issues.append(f"{name}: workspace required to revalidate external evidence")
                continue
            for external in external_evidence:
                from .evidence import verify_external
                try:
                    verify_external(root, external)
                except (Error, OSError) as exc:
                    issues.append(f"{name}: {exc}")
        stale = bool(issues)
        result["assessment_issues"] = issues
        result["assessment_state"] = "stale" if stale else "current"
        if not stale:
            low = 0.0
            covered = 0
            for name, weight in rubric["dimensions"].items():
                score = a["dimensions"][name]["score"]
                if score is not None:
                    low += score / 5 * weight
                    covered += weight
            result.update(score=round(low, 1) if covered == 100 else None, score_interval=[round(low, 1), round(low + 100 - covered, 1)],
                          coverage=covered, strengths=a.get("strengths", []), gaps=a.get("gaps", []), recommendation=a.get("recommendation"))
    return result


def rank_all(store: Store, profile: dict, include_failed: bool = False) -> list[dict]:
    rows = [ranking(row, profile, root=store.root) for row in store.list() if row["status"] not in {"archived", "dismissed"}]
    if not include_failed:
        rows = [row for row in rows if row["eligibility"]["verdict"] != "fail"]
    order = {"pass": 0, "unknown": 1, "fail": 2}
    families = {"phd": 0, "internship": 1, "school": 2}
    return sorted(rows, key=lambda row: (families[row["family"]], order[row["eligibility"]["verdict"]], -row["coverage"], -row["score_interval"][0], row["id"]))


def discovery_signals(record: dict, profile: dict) -> dict:
    data = merged(record)
    text = (data["title"] + " " + data.get("description", "")).casefold()
    def matches(terms):
        return [term for term in terms if re.search(r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)", text)]
    return {"id": record["id"], "title": data["title"], "topics": matches(profile["research"]["topics"]),
            "methods": matches(profile["research"]["methods"]), "excluded_topics": matches(profile["research"]["excluded_topics"]),
            "scope": "Literal discovery hints, not a scientific fit assessment or admission probability"}
