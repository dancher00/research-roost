from __future__ import annotations

import math
import re
from copy import deepcopy
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .core import Error, atomic_write, digest, json_text, now, read_json, resource


def validate(profile: dict) -> list[str]:
    errors = []
    if not isinstance(profile, dict):
        return ["Profile must be a JSON object"]
    template = read_json(resource("profile.example.json"))
    if profile.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    for field in ("identity", "research", "education", "experience", "outputs", "skills", "languages", "preferences", "facts"):
        if not isinstance(profile.get(field), type(template[field])):
            errors.append(f"{field} must be {type(template[field]).__name__}")
    if errors:
        return errors
    try:
        ZoneInfo(profile["identity"].get("timezone", "UTC"))
    except (ZoneInfoNotFoundError, TypeError):
        errors.append("identity.timezone must be a valid IANA timezone")
    for key in ("topics", "methods", "keywords", "excluded_topics", "questions"):
        if not isinstance(profile["research"].get(key), list) or any(not isinstance(x, str) for x in profile["research"].get(key, [])):
            errors.append(f"research.{key} must be an array of strings")
    for key in ("countries", "excluded_countries", "opportunity_types", "citizenships", "residence_history", "constraints"):
        if not isinstance(profile["preferences"].get(key), list):
            errors.append(f"preferences.{key} must be an array")
        elif key != "residence_history" and any(not isinstance(item, str) for item in profile["preferences"][key]):
            errors.append(f"preferences.{key} must contain strings")
    for key in ("name", "email", "location", "timezone", "orcid", "website", "cv_language"):
        if not isinstance(profile["identity"].get(key), str):
            errors.append(f"identity.{key} must be a string")
    interval = profile["preferences"].get("followup_after_days", 14)
    if isinstance(interval, bool) or not isinstance(interval, int) or not 1 <= interval <= 365:
        errors.append("preferences.followup_after_days must be an integer from 1 to 365")
    minimum = profile["preferences"].get("minimum_funding")
    if minimum is not None:
        if not isinstance(minimum, dict):
            errors.append("preferences.minimum_funding must be an object or null")
        else:
            amount = minimum.get("amount")
            if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount < 0:
                errors.append("minimum_funding.amount must be finite and nonnegative")
            if not isinstance(minimum.get("currency"), str) or len(minimum["currency"]) != 3:
                errors.append("minimum_funding.currency requires a three-letter currency code")
            if minimum.get("period") not in {"day", "week", "month", "year", "total"} or minimum.get("basis") not in {"gross", "net", "unspecified"}:
                errors.append("minimum_funding requires period (day/week/month/year/total) and basis (gross/net/unspecified)")
    for item in profile["skills"]:
        if not isinstance(item, (str, dict)) or isinstance(item, dict) and not isinstance(item.get("name"), str):
            errors.append("skills entries must be strings or objects with name")
    if profile["preferences"].get("require_full_funding") is not None and not isinstance(profile["preferences"]["require_full_funding"], bool):
        errors.append("preferences.require_full_funding must be true, false or null")
    ids = set()
    for i, fact in enumerate(profile["facts"]):
        if not isinstance(fact, dict) or not all(isinstance(fact.get(k), str) and fact[k].strip() for k in ("id", "claim", "source")):
            errors.append(f"facts[{i}] requires nonempty id, claim, source")
            continue
        if fact["id"] in ids:
            errors.append(f"Duplicate fact id: {fact['id']}")
        ids.add(fact["id"])
        if fact.get("confirmed") is not True:
            errors.append(f"facts[{i}].confirmed must be true; keep unconfirmed claims in notes")
    for collection in ("education", "experience", "outputs", "languages"):
        for i, entry in enumerate(profile[collection]):
            if not isinstance(entry, dict):
                errors.append(f"{collection}[{i}] must be an object")
    for entry in profile["education"]:
        if isinstance(entry, dict) and entry.get("level") not in {"bachelor", "master", "doctorate", "other"}:
            errors.append("education.level must be bachelor, master, doctorate or other")
        if isinstance(entry, dict) and entry.get("awarded_on"):
            try:
                date.fromisoformat(entry["awarded_on"])
            except (ValueError, TypeError):
                errors.append("education.awarded_on must be ISO YYYY-MM-DD")
        if isinstance(entry, dict) and "enrollment" in entry:
            enrollment = entry["enrollment"]
            if not isinstance(enrollment, dict):
                errors.append("education.enrollment must be an object")
            else:
                if enrollment.get("status") not in ("enrolled", "completed", "withdrawn", "on_leave", "unknown"):
                    errors.append("education.enrollment.status must be enrolled, completed, withdrawn, on_leave or unknown")
                _validate_confirmation(enrollment, "education.enrollment", errors, require_value=False)
                _validate_interval(enrollment, "education.enrollment", errors, require_dates=False)
    for entry in profile["languages"]:
        if not isinstance(entry, dict):
            continue
        if not isinstance(entry.get("name"), str) or not entry["name"].strip():
            errors.append("languages entries require name")
        if entry.get("cefr") not in {None, "A1", "A2", "B1", "B2", "C1", "C2"}:
            errors.append("languages.cefr must be A1–C2 or null")
        if not isinstance(entry.get("tests", []), list):
            errors.append("languages.tests must be an array")
            continue
        for test in entry.get("tests", []):
            if not isinstance(test, dict) or not isinstance(test.get("name"), str):
                errors.append("language tests require a name")
                continue
            if test.get("score") is not None and (isinstance(test["score"], bool) or not isinstance(test["score"], (int, float)) or not math.isfinite(test["score"])):
                errors.append("language test score must be a finite number")
            for key in ("date", "valid_until"):
                if test.get(key):
                    try:
                        date.fromisoformat(test[key])
                    except (ValueError, TypeError):
                        errors.append(f"language test {key} must be an ISO date")
    for key in ("start_after", "start_before"):
        value = profile["preferences"].get(key)
        if value is not None:
            try:
                date.fromisoformat(value)
            except (ValueError, TypeError):
                errors.append(f"preferences.{key} must be ISO YYYY-MM-DD or null")
    availability = profile["preferences"].get("availability", [])
    if not isinstance(availability, list):
        errors.append("preferences.availability must be an array")
    else:
        for entry in availability:
            if not isinstance(entry, dict):
                errors.append("preferences.availability entries must be objects")
                continue
            _validate_confirmation(entry, "preferences.availability", errors, require_value=False)
            _validate_interval(entry, "preferences.availability", errors, require_dates=True)
    for key in ("return_to_study", "work_authorization", "home_approval"):
        value = profile["preferences"].get(key)
        if value is not None:
            _validate_confirmation(value, "preferences." + key, errors)
    limits = profile["preferences"].get("duration_days")
    if limits is not None:
        if not isinstance(limits, dict) or not limits:
            errors.append("preferences.duration_days must specify min and/or max")
        else:
            for key, value in limits.items():
                if key not in {"min", "max"} or isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    errors.append("preferences.duration_days requires positive integer min/max")
            if isinstance(limits.get("min"), int) and isinstance(limits.get("max"), int) and limits["min"] > limits["max"]:
                errors.append("preferences.duration_days.min exceeds max")
    return errors


def _validate_interval(value, label, errors, *, require_dates):
    days = {}
    for key in ("start_date", "end_date"):
        if value.get(key) is not None:
            try:
                if not isinstance(value[key], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value[key]):
                    raise ValueError()
                days[key] = date.fromisoformat(value[key])
            except (TypeError, ValueError):
                errors.append(f"{label}.{key} must be an ISO date")
        elif require_dates:
            errors.append(f"{label}.{key} is required")
    if "start_date" in days and "end_date" in days and days["end_date"] < days["start_date"]:
        errors.append(f"{label}.end_date must not precede start_date")


def _validate_confirmation(value, label, errors, *, require_value=True):
    if not isinstance(value, dict):
        errors.append(f"{label} must be a source-linked confirmation object")
        return
    if not isinstance(value.get("confirmed"), bool):
        errors.append(f"{label}.confirmed must be boolean")
    if value.get("confirmed") is True and (not isinstance(value.get("source"), str) or not value["source"].strip()):
        errors.append(f"{label}.source is required for confirmed information")
    if require_value and value.get("value") is not None and not isinstance(value["value"], bool):
        errors.append(f"{label}.value must be boolean or null")
    if "country" in value and not isinstance(value["country"], str):
        errors.append(f"{label}.country must be a string")
    bounds = {}
    for key in ("valid_from", "valid_until"):
        if value.get(key) is not None:
            try:
                if not isinstance(value[key], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value[key]):
                    raise ValueError()
                bounds[key] = date.fromisoformat(value[key])
            except ValueError:
                errors.append(f"{label}.{key} must be an ISO date")
    if "valid_from" in bounds and "valid_until" in bounds and bounds["valid_until"] < bounds["valid_from"]:
        errors.append(f"{label}.valid_until must not precede valid_from")


def load(root: Path) -> dict:
    value = read_json(root / "profile.json")
    errors = validate(value)
    if errors:
        raise Error("Invalid profile:\n" + "\n".join(errors))
    return value


def fingerprint(profile: dict) -> str:
    return digest(json_text(profile))


def import_profile(root: Path, source: Path) -> dict:
    value = read_json(source)
    errors = validate(value)
    if errors:
        raise Error("Invalid profile:\n" + "\n".join(errors))
    old = root / "profile.json"
    if old.exists():
        atomic_write(root / "backups" / f"profile-{now().replace(':','-')}-{digest(old.read_bytes())[:8]}.json", old.read_bytes())
    atomic_write(old, json_text(value))
    return {"path": str(old), "sha256": fingerprint(value)}


def add_fact(root: Path, claim: str, source: str, fact_id: str | None = None) -> dict:
    value = deepcopy(load(root))
    fact = {"id": fact_id or "fact-" + digest(claim + source)[:12], "claim": claim,
            "source": source, "confirmed": True, "recorded_at": now()}
    if not claim.strip() or not source.strip():
        raise Error("Fact claim and source must be nonempty")
    if any(x["id"] == fact["id"] for x in value["facts"]):
        raise Error("Fact ID already exists; edit/import the profile to correct it")
    value["facts"].append(fact)
    atomic_write(root / "backups" / f"profile-{digest(json_text(load(root)))[:16]}.json", json_text(load(root)))
    atomic_write(root / "profile.json", json_text(value))
    return fact
