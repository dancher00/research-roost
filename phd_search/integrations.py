from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .applications import TRANSITIONS, get_application
from .core import Error, atomic_write, digest, json_text, now, read_json
from .exports import tracker_rows
from .store import Store

MAIL_STATUSES = {"assessment", "interview", "waitlisted", "offer", "rejected"}


def import_mail_signals(store: Store, data: dict) -> dict:
    """Accept read-only connector output; never infer or apply a status from raw email."""
    if not isinstance(data, dict) or not isinstance(data.get("signals"), list):
        raise Error("Mail import requires a signals array; see docs/integrations.md")
    proposals = []
    seen = set()
    applied = set()
    for row in store.db.execute("SELECT data FROM events WHERE kind='email_signal_applied'"):
        applied.add(json.loads(row[0])["message_id"])
    for signal in data["signals"]:
        if not isinstance(signal, dict) or not all(isinstance(signal.get(k), str) and signal[k].strip() for k in ("message_id", "application_id", "source_url", "quote", "proposed_status", "occurred_on")):
            raise Error("Signal requires message_id, application_id, source_url, quote, proposed_status and occurred_on")
        if signal["message_id"] in seen:
            raise Error("Duplicate message_id within a signal batch")
        seen.add(signal["message_id"])
        if signal["proposed_status"] not in MAIL_STATUSES:
            raise Error("Mail may propose assessment/interview/waitlisted/offer/rejected; acceptance, decline and submission are user decisions")
        try:
            if date.fromisoformat(signal["occurred_on"]) > date.today():
                raise ValueError("future outcome")
        except ValueError as exc:
            raise Error("Signal occurred_on must be a nonfuture ISO date") from exc
        try:
            app = get_application(store, signal["application_id"])
            eligible = signal["proposed_status"] in TRANSITIONS[app["status"]]
            state = "already_applied" if signal["message_id"] in applied else "proposed" if eligible else "conflict"
            proposal = {**signal, "application_id": app["id"], "current_status": app["status"], "state": state}
        except Error:
            proposal = {**signal, "state": "unmatched"}
        proposals.append(proposal)
    batch_id = digest(now() + json_text(proposals))[:20]
    result = {"batch_id": batch_id, "created_at": now(), "state": "awaiting_user_review", "proposals": proposals, "tracker_changed": False}
    atomic_write(store.root / "integrations" / "gmail" / (batch_id + ".json"), json_text(result))
    return result


def apply_mail_signals(store: Store, batch_id: str, approved: list[str]) -> dict:
    import re
    if not re.fullmatch(r"[a-f0-9]{20}", batch_id):
        raise Error("Invalid mail batch ID")
    batch = read_json(store.root / "integrations" / "gmail" / (batch_id + ".json"))
    if not approved:
        raise Error("Specify the exact message IDs explicitly approved by the user")
    known = {p["message_id"] for p in batch["proposals"]}
    if set(approved) - known:
        raise Error("Unknown approved message IDs")
    selections = [p for p in batch["proposals"] if p["message_id"] in approved]
    changes = []
    with store.transaction():
        already = {json.loads(row[0])["message_id"] for row in store.db.execute("SELECT data FROM events WHERE kind='email_signal_applied'")}
        for signal in selections:
            if signal["message_id"] in already:
                changes.append({"message_id": signal["message_id"], "state": "already_applied"})
                continue
            if signal["state"] != "proposed":
                raise Error("Only matched, conflict-free proposals may be approved")
            app = get_application(store, signal["application_id"])
            status = signal["proposed_status"]
            if app["status"] != signal["current_status"] or status not in TRANSITIONS[app["status"]]:
                raise Error("Application changed since mail import; review a fresh signal batch")
            store.db.execute("UPDATE applications SET status=?,updated_at=? WHERE id=?", (status, now(), app["id"]))
            store.event(app["id"], "status", {"from": app["status"], "to": status, "occurred_on": signal["occurred_on"], "note": signal["quote"], "source_url": signal["source_url"], "user_approved": True})
            store.event(app["id"], "email_signal_applied", {"message_id": signal["message_id"], "batch_id": batch_id, "user_approved": True})
            already.add(signal["message_id"])
            changes.append({"message_id": signal["message_id"], "application_id": app["id"], "status": status, "state": "applied"})
    batch["last_application"] = {"at": now(), "changes": changes}
    atomic_write(store.root / "integrations" / "gmail" / (batch_id + ".json"), json_text(batch))
    return {"batch_id": batch_id, "changes": changes, "messages_sent": False}


def notion_export(store: Store, profile: dict, target: Path) -> dict:
    rows = tracker_rows(store, profile)
    payload = {"schema_version": 1, "direction": "local_to_notion_only", "created_at": now(),
               "rows": [{"external_id": row["application_id"] or row["id"], "properties": {
                   "Title": row["title"], "Institution": row["institution"], "Country": row["country"], "Status": row["status"],
                   "URL": row["url"], "Deadline": row["deadline"], "Funding": row["funding"], "Score": row["score"],
                   "Eligibility": row["eligibility"], "Last verified": row["last_verified"], "Documents": row["document_filenames"]}}
                        for row in rows],
               "notes": "Connector-neutral payload, not a Notion HTTP request. Use the connected tool's actual schema. Upsert by external_id after user authorisation; upload no personal documents. Local state is authoritative."}
    atomic_write(target, json_text(payload))
    return {"path": str(target), "rows": len(rows), "remote_writes": False}
