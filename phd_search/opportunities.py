"""Opportunity families and explicit, source-backed extension contracts.

These helpers do not infer eligibility, funding or event dates from keywords.
Old records and assessments retain the doctoral interpretation.
"""
from __future__ import annotations

import math
import re
from copy import deepcopy
from datetime import date, datetime

from .core import Error, digest, json_text
from .extract import deadline_state, parse_deadline

PHD_TYPES = {"project", "doctoral_programme", "studentship", "doctoral_network", "scholarship", "supervisor_led", "other"}
SCHOOL_TYPES = {"summer_school", "winter_school", "research_school", "training_school", "field_school", "short_course"}
TYPES = PHD_TYPES | SCHOOL_TYPES | {"research_internship"}
DEADLINE_KINDS = {"application", "funding", "registration", "payment", "reference", "other"}
COMPONENTS = {"tuition", "registration", "living", "accommodation", "travel"}
COVERAGE = {"covered", "partial", "not_covered", "not_applicable", "unknown"}
LEVELS = {"bachelor", "master", "doctorate", "other"}
RUBRICS = {
    "phd": {"id": "phd", "version": 1, "family": "phd", "dimensions": {
        "research_fit": 30, "methods": 20, "supervisor_fit": 15, "preparedness": 15, "funding": 15, "environment": 5}},
    "internship": {"id": "internship", "version": 1, "family": "internship", "dimensions": {
        "project_fit": 30, "methods": 20, "mentor_fit": 15, "preparedness": 15, "funding": 15, "environment": 5}},
    "school": {"id": "school", "version": 1, "family": "school", "dimensions": {
        "learning_fit": 30, "prerequisites": 20, "programme_fit": 15, "funding": 20, "practical_fit": 15}},
}


def family(data: dict) -> str:
    kind = data.get("opportunity_type")
    return "internship" if kind == "research_internship" else "school" if isinstance(kind, str) and kind in SCHOOL_TYPES else "phd"


def rubric_for(data: dict) -> dict:
    return deepcopy(RUBRICS[family(data)])


def rubric_identity(data: dict) -> dict:
    return {key: value for key, value in rubric_for(data).items() if key != "dimensions"}


def _deadline(value) -> dict:
    if isinstance(value, str) and value.strip():
        return parse_deadline(value)
    if not isinstance(value, dict) or not isinstance(value.get("raw"), str) or not value["raw"].strip():
        raise Error("Each deadline requires source text or a parsed deadline object with raw text")
    if value.get("precision", "unknown") not in ("unknown", "date", "time"):
        raise Error("Deadline precision must be unknown, date or time")
    if value.get("value") is not None and not isinstance(value["value"], str):
        raise Error("Deadline value must be a string or null")
    if value.get("timezone") is not None and not isinstance(value["timezone"], str):
        raise Error("Deadline timezone must be a string or null")
    try:
        if value.get("value"):
            if value.get("precision") == "date":
                _day(value["value"])
            elif value.get("precision") == "time":
                if datetime.fromisoformat(value["value"]).tzinfo is None:
                    raise ValueError("a precise time needs an explicit timezone")
            else:
                raise ValueError("a parsed value requires date or time precision")
        deadline_state(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise Error(f"Invalid parsed deadline: {exc}") from exc
    return deepcopy(value)


def normalize_deadlines(value) -> list[dict]:
    if not isinstance(value, list):
        raise Error("deadlines must be an array")
    result, identifiers = [], set()
    for entry in value:
        if not isinstance(entry, dict) or not isinstance(entry.get("kind"), str) or entry.get("kind") not in DEADLINE_KINDS:
            raise Error("Each deadline requires kind: " + ", ".join(sorted(DEADLINE_KINDS)))
        parsed = _deadline(entry.get("deadline"))
        identity = {"kind": entry["kind"], "label": entry.get("label") or None}
        if not identity["label"]:
            identity["deadline"] = parsed
        identifier = entry.get("id", entry["kind"] + "-" + digest(json_text(identity))[:12])
        if not isinstance(identifier, str) or not identifier.strip() or identifier in identifiers:
            raise Error("Deadline IDs must be nonempty and unique")
        identifiers.add(identifier)
        if "required" in entry and not isinstance(entry["required"], bool):
            raise Error("deadline.required must be boolean")
        if "label" in entry and not isinstance(entry["label"], str):
            raise Error("deadline.label must be a string")
        result.append({**entry, "id": identifier, "deadline": parsed,
                       "required": entry.get("required", entry["kind"] in {"application", "registration"})})
    return result


def deadline_entries(data: dict) -> list[dict]:
    entries = normalize_deadlines(data.get("deadlines", []))
    # A reviewed application deadline supersedes the generic single-deadline
    # extractor, which cannot distinguish payment and scholarship cutoffs.
    if data.get("deadline") and not any(entry["kind"] == "application" for entry in entries):
        identifier = "application-primary"
        used = {entry["id"] for entry in entries}
        while identifier in used:
            identifier += "-legacy"
        entries.insert(0, {"id": identifier, "kind": "application", "label": "Application",
                           "deadline": _deadline(data["deadline"]), "required": True})
    return entries


def primary_application(data: dict) -> dict | None:
    """Select a primary event independently of a named-deadline array's order."""
    entries = [entry for entry in deadline_entries(data) if entry["kind"] == "application"]
    return min(entries, key=lambda entry: entry["id"]) if entries else None


def _day(value) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("must be an ISO date")
    return date.fromisoformat(value)


def validate_opportunity_fields(data: dict) -> list[str]:
    """Validate fields used by deterministic screening; absent stays unknown."""
    errors = []
    if data.get("opportunity_type") is not None and (not isinstance(data["opportunity_type"], str) or data["opportunity_type"] not in TYPES):
        errors.append("Unknown opportunity type")
    for key in ("start_date", "end_date"):
        if data.get(key) is not None:
            try:
                _day(data[key])
            except (ValueError, TypeError):
                errors.append(f"{key} must be an ISO date or null")
    try:
        if data.get("start_date") and data.get("end_date") and _day(data["end_date"]) < _day(data["start_date"]):
            errors.append("end_date must not precede start_date")
    except (ValueError, TypeError):
        pass
    for key in ("duration_months", "duration_days"):
        value = data.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0):
            errors.append(f"{key} must be a positive finite number or null")
    if data.get("mode") not in (None, "onsite", "online", "hybrid", "unknown"):
        errors.append("mode must be onsite, online, hybrid or unknown")
    if data.get("application_status") not in (None, "open", "upcoming", "closed", "rolling", "unknown"):
        errors.append("application_status must be open, upcoming, closed, rolling or unknown")
    for key in ("programme_id", "edition", "session_id"):
        if data.get(key) is not None and (not isinstance(data[key], str) or not data[key].strip()):
            errors.append(f"{key} must be a nonempty string or null")
    if "deadlines" in data:
        try:
            normalize_deadlines(data["deadlines"])
        except Error as exc:
            errors.append(str(exc))
    funding = data.get("funding")
    if isinstance(funding, dict) and "components" in funding:
        parts = funding["components"]
        if not isinstance(parts, dict) or set(parts) - COMPONENTS:
            errors.append("funding.components must name tuition, registration, living, accommodation or travel")
        else:
            for name, part in parts.items():
                if not isinstance(part, dict) or not isinstance(part.get("coverage"), str) or part.get("coverage") not in COVERAGE:
                    errors.append(f"funding.components.{name} requires a valid coverage")
                    continue
                amount = part.get("amount")
                if amount is not None and (isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount < 0):
                    errors.append(f"funding.components.{name}.amount must be finite and nonnegative")
                if part.get("currency") is not None and (not isinstance(part["currency"], str) or len(part["currency"]) != 3 or not part["currency"].isalpha()):
                    errors.append(f"funding.components.{name}.currency must be a three-letter code")
                if part.get("period") not in (None, "day", "week", "month", "year", "total"):
                    errors.append(f"funding.components.{name}.period is invalid")
                if part.get("basis") not in (None, "gross", "net", "unspecified"):
                    errors.append(f"funding.components.{name}.basis is invalid")
                if part.get("conditions") is not None and not isinstance(part["conditions"], str):
                    errors.append(f"funding.components.{name}.conditions must be a string")
    requirements = data.get("requirements") or {}
    if data.get("requirements") is not None and not isinstance(data["requirements"], dict):
        errors.append("requirements must be an object")
    if isinstance(requirements, dict):
        degree = requirements.get("degree")
        if degree is not None and (not isinstance(degree, str) or not degree.strip()):
            errors.append("requirements.degree must be a nonempty string or null")
        if "reviewed" in requirements and not isinstance(requirements["reviewed"], bool):
            errors.append("requirements.reviewed must be boolean")
        for key in ("allowed_citizenships", "excluded_citizenships"):
            values = requirements.get(key, [])
            if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
                errors.append(f"requirements.{key} must contain nonempty strings")
        other = requirements.get("other", [])
        if not isinstance(other, list):
            errors.append("requirements.other must be an array")
        else:
            for rule in other:
                if not isinstance(rule, dict) or not isinstance(rule.get("name"), str) or not rule["name"].strip():
                    errors.append("requirements.other entries require a nonempty name")
                    continue
                if rule.get("verdict") not in ("pass", "fail", "unknown"):
                    errors.append("requirements.other.verdict must be pass, fail or unknown")
                if not isinstance(rule.get("reason"), str) or not rule["reason"].strip():
                    errors.append("requirements.other entries require a nonempty reason")
        languages = requirements.get("languages", [])
        if not isinstance(languages, list):
            errors.append("requirements.languages must be an array")
        else:
            for rule in languages:
                if not isinstance(rule, dict) or not isinstance(rule.get("name"), str) or not rule["name"].strip():
                    errors.append("requirements.languages entries require a nonempty name")
                    continue
                for key in ("cefr", "test"):
                    if rule.get(key) is not None and (not isinstance(rule[key], str) or not rule[key].strip()):
                        errors.append(f"requirements.languages.{key} must be a nonempty string or null")
                minimum = rule.get("minimum_score")
                if minimum is not None and (isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or not math.isfinite(minimum) or minimum < 0):
                    errors.append("requirements.languages.minimum_score must be finite and nonnegative")
    enrollment = requirements.get("enrollment") if isinstance(requirements, dict) else None
    if enrollment is not None:
        if not isinstance(enrollment, dict):
            errors.append("requirements.enrollment must be an object")
        else:
            for key in ("allowed_levels", "excluded_levels"):
                levels = enrollment.get(key, [])
                if not isinstance(levels, list) or any(not isinstance(level, str) or level not in LEVELS for level in levels):
                    errors.append(f"requirements.enrollment.{key} must contain degree levels")
            for key in ("required", "through_end", "return_to_study"):
                if key in enrollment and not isinstance(enrollment[key], bool):
                    errors.append(f"requirements.enrollment.{key} must be boolean")
    if isinstance(requirements, dict):
        for key in ("work_authorization_required", "home_approval_required"):
            if key in requirements and not isinstance(requirements[key], bool):
                errors.append(f"requirements.{key} must be boolean")
        limits = requirements.get("duration_days")
        if limits is not None:
            if not isinstance(limits, dict) or not limits:
                errors.append("requirements.duration_days requires min and/or max")
            else:
                for key, value in limits.items():
                    if key not in {"min", "max"} or isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                        errors.append("requirements.duration_days bounds must be positive integers")
                if isinstance(limits.get("min"), int) and isinstance(limits.get("max"), int) and limits["min"] > limits["max"]:
                    errors.append("requirements.duration_days.min exceeds max")
    return errors
