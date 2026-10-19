from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .core import Error, canonical_url, digest, json_text, now

SCHEMA_VERSION = 2
SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
 id TEXT PRIMARY KEY, url TEXT NOT NULL, identity_key TEXT NOT NULL UNIQUE, data TEXT NOT NULL,
 first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new');
CREATE TABLE IF NOT EXISTS aliases (
 url TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL REFERENCES opportunities(id));
CREATE TABLE IF NOT EXISTS snapshots (
 id INTEGER PRIMARY KEY, opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
 sha256 TEXT NOT NULL, raw_path TEXT NOT NULL, text_path TEXT NOT NULL,
 fetched_at TEXT NOT NULL, url TEXT NOT NULL, metadata TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS annotations (
 opportunity_id TEXT PRIMARY KEY REFERENCES opportunities(id), data TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assessments (
 id INTEGER PRIMARY KEY, opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
 profile_sha256 TEXT NOT NULL, evidence_sha256 TEXT NOT NULL,
 created_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS applications (
 id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
 status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id),
 created_at TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS dossiers (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL, started_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS artifacts (
 id INTEGER PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id),
 relative_path TEXT NOT NULL, sha256 TEXT NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS snapshots_opportunity ON snapshots(opportunity_id, id);
CREATE INDEX IF NOT EXISTS assessments_opportunity ON assessments(opportunity_id, id);
CREATE INDEX IF NOT EXISTS applications_opportunity ON applications(opportunity_id);
"""


class Store:
    def __init__(self, root: Path, *, create: bool = False):
        self.root = root
        path = root / "phd-search.sqlite3"
        if not create and not path.exists():
            raise Error("Database missing; initialise a workspace first")
        root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, SCHEMA_VERSION):
            self.db.close()
            raise Error(f"Unsupported database version {version}; do not overwrite it")
        if version == 0:
            if not create:
                self.db.close()
                raise Error("Database has no recognised schema")
            self.db.executescript(SCHEMA)
            self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self.db.commit()
        elif version == 1:
            self._migrate_v1()

    def _migrate_v1(self) -> None:
        backup = self.root / "backups" / ("before-schema-2-" + digest(now() + str(id(self)))[:16] + ".sqlite3")
        self.backup(backup)
        self.db.execute("PRAGMA foreign_keys=OFF")
        try:
            with self.transaction():
                self.db.execute("""CREATE TABLE opportunities_v2 (
                    id TEXT PRIMARY KEY, url TEXT NOT NULL, identity_key TEXT NOT NULL UNIQUE,
                    data TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new')""")
                self.db.execute("""INSERT INTO opportunities_v2
                    SELECT id,url,url,data,first_seen,last_seen,status FROM opportunities""")
                self.db.execute("DROP TABLE opportunities")
                self.db.execute("ALTER TABLE opportunities_v2 RENAME TO opportunities")
                self.db.execute("PRAGMA user_version=2")
                if self.db.execute("PRAGMA foreign_key_check").fetchone():
                    raise Error("Database migration found broken references; original data was restored")
        except BaseException:
            self.db.close()
            raise
        self.db.execute("PRAGMA foreign_keys=ON")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    @contextmanager
    def transaction(self):
        try:
            self.db.execute("BEGIN IMMEDIATE")
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def event(self, application_id: str, kind: str, data: dict) -> None:
        self.db.execute("INSERT INTO events(application_id,created_at,kind,data) VALUES (?,?,?,?)",
                        (application_id, now(), kind, json_text(data)))

    def get(self, identifier: str) -> dict:
        row = self.db.execute("SELECT * FROM opportunities WHERE id=?", (identifier,)).fetchone()
        if row is None:
            candidates = self.db.execute("""SELECT * FROM opportunities WHERE url=? OR id IN
                (SELECT opportunity_id FROM aliases WHERE url=?)""", (identifier, identifier)).fetchall()
            if len(candidates) > 1:
                raise Error("Several editions/sessions use this URL; select an opportunity ID")
            row = candidates[0] if candidates else None
        if row is None:
            rows = self.db.execute("SELECT id FROM opportunities WHERE id LIKE ?", (identifier + "%",)).fetchall()
            if len(rows) == 1:
                return self.get(rows[0][0])
            raise Error(f"Opportunity not found or ambiguous: {identifier}")
        result = dict(row)
        result["data"] = json.loads(result["data"])
        ann = self.db.execute("SELECT data FROM annotations WHERE opportunity_id=?", (row["id"],)).fetchone()
        result["annotations"] = json.loads(ann[0]) if ann else {}
        snapshot = self.db.execute("SELECT * FROM snapshots WHERE opportunity_id=? ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
        result["snapshot"] = dict(snapshot) if snapshot else None
        if snapshot:
            result["snapshot"]["metadata"] = json.loads(snapshot["metadata"])
        assessment = self.db.execute("SELECT * FROM assessments WHERE opportunity_id=? ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
        result["assessment"] = dict(assessment) if assessment else None
        if assessment:
            result["assessment"]["data"] = json.loads(assessment["data"])
        return result

    def list(self, status: str | None = None) -> list[dict]:
        rows = self.db.execute("SELECT id FROM opportunities" + (" WHERE status=?" if status else "") + " ORDER BY first_seen,id",
                               (status,) if status else ()).fetchall()
        return [self.get(row[0]) for row in rows]

    def ingest(self, url: str, data: dict, snapshot: dict, *, edition: str | None = None, session: str | None = None) -> dict:
        url = canonical_url(url)
        for label, value in (("edition", edition), ("session", session)):
            if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 128):
                raise Error(f"{label} must be a nonempty label of at most 128 characters")
        if session and not edition:
            raise Error("A session requires an explicit edition to avoid mixing annual programmes")
        edition = edition.strip() if edition else None
        session = session.strip() if session else None
        identity = url if not edition else json_text({"url": url, "edition": edition, "session": session})
        alias = self.db.execute("""SELECT o.id,o.url,o.identity_key FROM aliases a
            JOIN opportunities o ON o.id=a.opportunity_id WHERE a.url=?""", (url,)).fetchone()
        if alias and alias["identity_key"] != alias["url"]:
            labels = json.loads(alias["identity_key"])
            if not edition:
                raise Error("This alias belongs to an edition/session; supply its explicit --edition and --session to refresh it")
            if (labels.get("edition"), labels.get("session")) == (edition, session):
                identity = alias["identity_key"]
            else:
                alias = None
        elif edition:
            alias = None
        existing = self.db.execute("SELECT id FROM opportunities WHERE identity_key=?", (identity,)).fetchone()
        identifier = alias["id"] if alias else existing[0] if existing else digest(identity)[:16]
        if edition:
            data = {**data, "edition": edition, "session_id": session}
            snapshot = {**snapshot, "metadata": {**snapshot.get("metadata", {}), "identity_context": {
                "edition": edition, "session": session, "basis": "explicit_import_labels; verify institutional cycle separately"}}}
        stamp = now()
        with self.transaction():
            self.db.execute("""INSERT INTO opportunities(id,url,identity_key,data,first_seen,last_seen) VALUES (?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET data=excluded.data,last_seen=excluded.last_seen""",
                (identifier, url, identity, json_text(data), stamp, stamp))
            self.db.execute("""INSERT INTO snapshots(opportunity_id,sha256,raw_path,text_path,fetched_at,url,metadata)
                VALUES (?,?,?,?,?,?,?)""", (identifier, snapshot["sha256"], snapshot["raw_path"], snapshot["text_path"],
                                           snapshot.get("fetched_at", stamp), snapshot.get("url", url), json_text(snapshot.get("metadata", {}))))
        return self.get(identifier)

    def annotate(self, identifier: str, data: dict) -> dict:
        record = self.get(identifier)
        with self.transaction():
            self.db.execute("""INSERT INTO annotations VALUES (?,?,?) ON CONFLICT(opportunity_id)
                DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at""", (record["id"], json_text(data), now()))
        return self.get(record["id"])

    def log_run(self, kind: str, data: dict) -> None:
        with self.transaction():
            self.db.execute("INSERT INTO runs(kind,started_at,data) VALUES (?,?,?)", (kind, now(), json_text(data)))

    def backup(self, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(target) as destination:
            self.db.backup(destination)
