from __future__ import annotations

import csv
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from phd_search import exports, profile, sources
from phd_search.cli import initialise
from phd_search.core import Error, digest, json_text, read_json, resource
from phd_search.extract import parse_deadline
from phd_search.network import Client
from phd_search.store import Store

PROJECT = Path(__file__).resolve().parents[1]


class ModeStorageExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "private"
        initialise(self.root)
        self.candidate = profile.load(self.root)

    def posting(self, store, kind="winter_school", *, edition=None, session=None, **fields):
        body = "Synthetic research opportunity. All financial and participation details require review."
        (self.root / "evidence" / "fixture.txt").write_text(body)
        return store.ingest("https://institution.example/research-programme", {
            "title": "History methods school" if kind != "research_internship" else "Research internship",
            "opportunity_type": kind, "description": body, "requirements": {"reviewed": True},
            "deadline": parse_deadline("2035-01-01"), **fields}, {
            "sha256": digest(body), "raw_path": "evidence/fixture.txt", "text_path": "evidence/fixture.txt",
            "url": "https://institution.example/research-programme", "metadata": {}}, edition=edition, session=session)

    def test_actual_legacy_database_migrates_with_backup_and_preserves_references(self):
        legacy = self.base / "legacy"
        legacy.mkdir()
        path = legacy / "phd-search.sqlite3"
        with sqlite3.connect(path) as db:
            db.executescript((PROJECT / "tests/fixtures/workspace-v1.sql").read_text())
            before = db.execute("SELECT id,url,data,first_seen,last_seen,status FROM opportunities").fetchall()
            applications = db.execute("SELECT * FROM applications").fetchall()
        with Store(legacy) as store:
            self.assertEqual(store.db.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual([tuple(row) for row in store.db.execute("SELECT id,url,data,first_seen,last_seen,status FROM opportunities")], before)
            self.assertEqual([tuple(row) for row in store.db.execute("SELECT * FROM applications")], applications)
            self.assertEqual(store.db.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(store.get(before[0][0])["id"], before[0][0])
        backups = list((legacy / "backups").glob("before-schema-2-*.sqlite3"))
        self.assertEqual(len(backups), 1)
        with sqlite3.connect(backups[0]) as backup:
            self.assertEqual(backup.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(backup.execute("SELECT * FROM applications").fetchall(), applications)
        with Store(legacy):
            pass
        self.assertEqual(list((legacy / "backups").glob("*.sqlite3")), backups)

    def test_failed_migration_rolls_back_and_keeps_the_original_database(self):
        legacy = self.base / "broken-legacy"
        legacy.mkdir()
        path = legacy / "phd-search.sqlite3"
        with sqlite3.connect(path) as db:
            db.executescript((PROJECT / "tests/fixtures/workspace-v1.sql").read_text())
            db.execute("UPDATE applications SET opportunity_id='missing-record'")
            db.commit()
        with self.assertRaises(Error):
            Store(legacy)
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT opportunity_id FROM applications").fetchone()[0], "missing-record")
            self.assertEqual(db.execute("SELECT count(*) FROM opportunities").fetchone()[0], 1)
        self.assertEqual(len(list((legacy / "backups").glob("*.sqlite3"))), 1)

    def test_annual_editions_and_sessions_at_one_real_url_are_distinct_and_repeatable(self):
        with Store(self.root) as store:
            records = [self.posting(store, edition=year, session=session) for year, session in
                       (("2034", "winter"), ("2035", "winter"), ("2035", "summer"))]
            self.assertEqual(len({record["id"] for record in records}), 3)
            self.assertEqual(len({record["url"] for record in records}), 1)
            self.assertEqual(self.posting(store, edition="2035", session="summer")["id"], records[2]["id"])
            self.assertEqual(len(store.list()), 3)
            with self.assertRaisesRegex(Error, "Several editions"):
                store.get(records[0]["url"])
            self.assertEqual(store.get(records[1]["id"])["snapshot"]["metadata"]["identity_context"]["edition"], "2035")

    def test_session_without_edition_cannot_accidentally_merge_cycles(self):
        with Store(self.root) as store:
            with self.assertRaisesRegex(Error, "edition"):
                self.posting(store, session="winter")
            self.assertEqual(store.list(), [])

    def test_alias_cannot_erase_an_edition_and_explicit_other_year_stays_separate(self):
        with Store(self.root) as store:
            record = self.posting(store, edition="2035", session="winter")
            alias_url = "https://institution.example/alias-programme"
            with store.transaction():
                store.db.execute("INSERT INTO aliases VALUES (?,?)", (alias_url, record["id"]))
            original = store.get(record["id"])
            with self.assertRaisesRegex(Error, "explicit --edition"):
                store.ingest(alias_url, {"title": "Changed annual page"}, record["snapshot"])
            self.assertEqual(store.get(record["id"]), original)
            refreshed = store.ingest(alias_url, record["data"], record["snapshot"], edition="2035", session="winter")
            self.assertEqual(refreshed["id"], record["id"])
            separate = store.ingest(alias_url, {**record["data"], "title": "Next year"}, record["snapshot"], edition="2036", session="winter")
            self.assertNotEqual(separate["id"], record["id"])
            self.assertEqual(store.get(record["id"])["data"]["edition"], "2035")
            with self.assertRaisesRegex(Error, "Several editions"):
                store.get(alias_url)

    def test_secondary_deadlines_and_participation_export_with_distinct_uids(self):
        with Store(self.root) as store:
            self.posting(store, edition="2035", start_date="2035-02-01", end_date="2035-02-12", mode="onsite",
                         deadlines=[
                             {"id": "apply", "kind": "application", "deadline": "2035-01-10T16:00:00+01:00"},
                             {"id": "grant", "kind": "funding", "deadline": "2034-12-15T23:59:00-12:00"},
                             {"id": "register", "kind": "registration", "deadline": "2035-01-15"},
                             {"id": "pay", "kind": "payment", "deadline": "2035-01-20"},
                             {"id": "reference", "kind": "reference", "deadline": "2035-01-12"},
                             {"id": "unknown", "kind": "other", "deadline": "Date to be confirmed"},
                         ])
            target = self.base / "calendar.ics"
            result = exports.calendar(store, target)
            content = target.read_text()
            self.assertEqual(result["events"], 6)
            self.assertEqual(result["skipped_unknown_deadlines"], 1)
            self.assertIn("DTSTART:20350110T150000Z", content)
            self.assertIn("DTSTART:20341216T115900Z", content)
            self.assertIn("DTSTART;VALUE=DATE:20350201", content)
            self.assertIn("DTEND;VALUE=DATE:20350213", content)
            self.assertNotIn("DTSTART;VALUE=DATE:20350101", content)
            uids = [line for line in content.splitlines() if line.startswith("UID:")]
            self.assertEqual(len(uids), len(set(uids)))

    def test_rebranding_keeps_the_primary_calendar_uid(self):
        with Store(self.root) as store:
            record = self.posting(store)
            target = self.base / "calendar.ics"
            exports.calendar(store, target)
            self.assertIn("UID:deadline-" + record["id"] + "@phd-search.local", target.read_text())

    def test_reordering_application_rounds_does_not_reassign_calendar_uids(self):
        deadlines = [{"id": "round-b", "kind": "application", "label": "Second round", "deadline": "2035-01-20"},
                     {"id": "round-a", "kind": "application", "label": "First round", "deadline": "2035-01-10"}]
        with Store(self.root) as store:
            mappings = []
            for entries in (deadlines, list(reversed(deadlines))):
                self.posting(store, deadlines=entries)
                target = self.base / "rounds.ics"
                exports.calendar(store, target)
                mappings.append({next(line for line in event.splitlines() if line.startswith("UID:")):
                                 next(line for line in event.splitlines() if line.startswith("SUMMARY:"))
                                 for event in target.read_text().split("BEGIN:VEVENT")[1:]})
            self.assertEqual(mappings[0], mappings[1])

    def test_family_report_filters_opportunities_and_shows_component_costs(self):
        with Store(self.root) as store:
            self.posting(store, edition="school", funding={"status": "partial", "components": {
                "registration": {"coverage": "covered"}, "accommodation": {"coverage": "not_covered"}}})
            self.posting(store, "research_internship", edition="internship")
            target = self.base / "school.html"
            result = exports.report(store, self.candidate, target, family="school")
            html = target.read_text()
            self.assertEqual(result["opportunities"], 1)
            self.assertIn("History methods school", html)
            self.assertNotIn("Research internship</a>", html)
            self.assertIn("accommodation: not_covered", html)
            self.assertIn("data-family='school'", html)
            self.assertIn("Research Roost", html)
            self.assertIn("same family and rubric version", html)

    def test_csv_retains_all_deadline_and_funding_fields(self):
        with Store(self.root) as store:
            self.posting(store, edition="2035", session="winter", end_date="2035-03-01", deadlines=[
                {"id": "grant", "kind": "funding", "deadline": "2034-12-10"}])
            target = self.base / "tracker.csv"
            exports.export_csv(store, self.candidate, target)
            with target.open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["family"], "school")
            self.assertEqual(rows[0]["session"], "winter")
            self.assertEqual(rows[0]["end_date"], "2035-03-01")
            self.assertEqual(json.loads(rows[0]["deadlines"])[0]["kind"], "application")
            self.assertEqual(json.loads(rows[0]["deadlines"])[1]["kind"], "funding")

    def test_csv_uses_reviewed_application_deadline_instead_of_generic_extraction(self):
        with Store(self.root) as store:
            self.posting(store, deadlines=[{"id": "apply", "kind": "application", "deadline": "2034-12-10"}])
            rows = exports.tracker_rows(store, self.candidate)
            self.assertEqual(rows[0]["deadline"], "2034-12-10")
            self.assertEqual(rows[0]["deadline_raw"], "2034-12-10")

    def test_source_install_is_additive_and_repeatable(self):
        existing = {"id": "msr-internships", "kind": "discovery", "enabled": False,
                    "families": ["internship"], "url": "https://institution.example/my-source"}
        (self.root / "sources.json").write_text(json_text({"schema_version": 1, "sources": [existing]}))
        result = sources.install_builtins(self.root)
        self.assertNotIn("msr-internships", result["added"])
        configured = sources.load_sources(self.root)
        self.assertEqual(next(item for item in configured if item["id"] == existing["id"]), existing)
        self.assertEqual(sources.install_builtins(self.root)["added"], [])

    def test_malformed_source_family_metadata_cannot_poison_the_registry(self):
        before = (self.root / "sources.json").read_bytes()
        for families in ([{}], [[]], [], "school", None):
            with self.subTest(families=families), self.assertRaises(Error):
                sources.add_source(self.root, {"id": "invalid", "kind": "discovery", "url": "https://institution.example", "families": families})
        self.assertEqual((self.root / "sources.json").read_bytes(), before)

    def test_existing_shipped_board_gets_family_metadata_without_overwriting_settings(self):
        legacy = read_json(resource("sources.example.json"))["sources"][0]
        legacy.pop("families")
        legacy["enabled"] = False
        (self.root / "sources.json").write_text(json_text({"schema_version": 1, "sources": [legacy]}))
        result = sources.install_builtins(self.root)
        current = next(item for item in sources.load_sources(self.root) if item["id"] == legacy["id"])
        self.assertEqual(current["families"], ["phd"])
        self.assertFalse(current["enabled"])
        self.assertEqual({k: v for k, v in current.items() if k != "families"}, legacy)
        self.assertIn(legacy["id"], result["family_metadata_added"])

    def test_school_discovery_handoff_cannot_look_like_successful_scraping(self):
        with Store(self.root) as store:
            result = sources.scrape(store, Client(self.root), sources=None, query="oral history", limit=2, pages=1, family="school")
            self.assertEqual(len(result["sources"]), 2)
            self.assertEqual({item["status"] for item in result["sources"]}, {"browser_required"})
            self.assertEqual(result["matches"], [])
            self.assertEqual(store.list(), [])

    def test_new_and_legacy_modules_obey_workspace_precedence(self):
        env = dict(os.environ, PYTHONPATH=str(PROJECT))
        env["RESEARCH_ROOST_WORKSPACE"] = str(self.root)
        env["PHD_SEARCH_WORKSPACE"] = str(self.base / "wrong-legacy")
        before = (self.root / "profile.json").read_bytes()
        for module in ("research_roost", "phd_search"):
            result = subprocess.run([sys.executable, "-m", module, "doctor"], cwd=self.base,
                                    env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["workspace"], str(self.root))
            selected = self.base / (module + "-explicit")
            result = subprocess.run([sys.executable, "-m", module, "--workspace", str(selected), "init"], cwd=self.base,
                                    env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["workspace"], str(selected))
        self.assertEqual((self.root / "profile.json").read_bytes(), before)

    def test_fresh_workspace_has_no_invented_personal_preferences(self):
        self.assertEqual(self.candidate["preferences"]["opportunity_types"], [])
        self.assertEqual(read_json(resource("profile.example.json")), self.candidate)


if __name__ == "__main__":
    unittest.main()
