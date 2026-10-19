-- Generated from the actual schema-1 implementation with synthetic data.
BEGIN TRANSACTION;
CREATE TABLE aliases (
 url TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL REFERENCES opportunities(id));
CREATE TABLE annotations (
 opportunity_id TEXT PRIMARY KEY REFERENCES opportunities(id), data TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE applications (
 id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
 status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL);
INSERT INTO "applications" VALUES('legacy-app','ac80549755869bbc','preparing','2030-01-01','2030-01-01','{"legacy_marker":"preserve"}');
CREATE TABLE artifacts (
 id INTEGER PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id),
 relative_path TEXT NOT NULL, sha256 TEXT NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE assessments (
 id INTEGER PRIMARY KEY, opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
 profile_sha256 TEXT NOT NULL, evidence_sha256 TEXT NOT NULL,
 created_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE dossiers (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE events (
 id INTEGER PRIMARY KEY, application_id TEXT NOT NULL REFERENCES applications(id),
 created_at TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE opportunities (
 id TEXT PRIMARY KEY, url TEXT NOT NULL UNIQUE, data TEXT NOT NULL,
 first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new');
INSERT INTO "opportunities" VALUES('ac80549755869bbc','https://institution.example/phd/legacy','{
  "deadline": null,
  "description": "Legacy doctoral opportunity. Deadline: 31 December 2035.\n",
  "title": "Legacy doctoral opportunity"
}
','2026-10-19T18:54:47+00:00','2026-10-19T18:54:47+00:00','new');
CREATE TABLE runs (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL, started_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE snapshots (
 id INTEGER PRIMARY KEY, opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
 sha256 TEXT NOT NULL, raw_path TEXT NOT NULL, text_path TEXT NOT NULL,
 fetched_at TEXT NOT NULL, url TEXT NOT NULL, metadata TEXT NOT NULL);
INSERT INTO "snapshots" VALUES(1,'ac80549755869bbc','c357f4a51c8385188b59c7a03f77f52de30b2e502078c054f4d0ff9e30a3bbd2','evidence/legacy.txt','evidence/legacy.txt','2026-10-19T18:54:47+00:00','https://institution.example/phd/legacy','{}
');
CREATE INDEX snapshots_opportunity ON snapshots(opportunity_id, id);
CREATE INDEX assessments_opportunity ON assessments(opportunity_id, id);
CREATE INDEX applications_opportunity ON applications(opportunity_id);
COMMIT;
PRAGMA user_version=1;
