from __future__ import annotations

import contextlib
import copy
import csv
import io
import json
import tempfile
import unittest
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from phd_search import applications as apps
from phd_search import assessment as assess
from phd_search import exports, integrations, profile
from phd_search.cli import initialise, main
from phd_search.core import (
    Error,
    atomic_write,
    canonical_url,
    digest,
    json_text,
    read_json,
)
from phd_search.evidence import ingest_file
from phd_search.extract import deadline_state, extract, parse_deadline
from phd_search.store import Store

FIXTURE = Path(__file__).parent / "fixtures" / "opportunity.html"


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "workspace"
        initialise(self.root)
        self.store = Store(self.root)
        self.addCleanup(self.store.db.close)
        self.candidate = profile.load(self.root)
        self.candidate["identity"].update(name="Test Researcher", email="person@example.invalid")
        self.candidate["research"].update(topics=["comparative literature"], methods=["archival analysis"], statement="I investigate translation through archival analysis.")
        self.candidate["education"] = [{"level": "master", "degree": "MA in Literature", "institution": "Example College", "awarded_on": "2025-06-01"}]
        self.candidate["facts"] = [{"id": "f1", "claim": "I analysed a multilingual archive for my master's thesis.", "source": "user-confirmed thesis description", "confirmed": True}]
        atomic_write(self.root / "profile.json", json_text(self.candidate))
        self.record = ingest_file(self.store, FIXTURE, "https://university.example/doctoral/1", mode="html")

    def annotations(self):
        sha = self.record["snapshot"]["sha256"]
        return {"values": {"requirements": {"degree": "master", "reviewed": True}, "funding": {"status": "fully_funded", "tuition_covered": True}, "opportunity_type": "project"},
                "evidence": {"requirements": {"quote": "Applicants need a master's degree.", "evidence_sha256": sha},
                             "funding": {"quote": "Full tuition and a monthly stipend are covered.", "evidence_sha256": sha},
                             "opportunity_type": {"quote": "Doctoral researcher in comparative literature", "evidence_sha256": sha}}}

    def reviewed_application(self, variant="main"):
        self.record = assess.validate_annotations(self.store, self.record["id"], self.annotations())
        app = apps.create_application(self.store, self.record["id"], self.candidate, variant=variant, document_kinds=["cv", "motivation"])
        directory = self.root / app["data"]["directory"]
        motivation = "# Motivation\n\n" + self.candidate["facts"][0]["claim"] + "\n\nI would investigate archival sources and translation.\n"
        atomic_write(directory / "motivation.md", motivation)
        claims = read_json(directory / "claims.json")
        claims["claims"].extend([{"file": "motivation.md", "text": self.candidate["facts"][0]["claim"], "profile_refs": ["/facts/0"]},
                                 {"file": "motivation.md", "text": "I would investigate archival sources and translation.", "posting_quotes": ["Investigate archival sources and translation."]}])
        claims["coverage_reviewed"] = True
        atomic_write(directory / "claims.json", json_text(claims))
        requirements = read_json(directory / "requirements.json")
        requirements["source_quote"] = "Submit an academic CV and motivation letter."
        atomic_write(directory / "requirements.json", json_text(requirements))
        self.review(app)
        return app

    def review(self, app):
        app = apps.get_application(self.store, app["id"])
        directory = self.root / app["data"]["directory"]
        review = read_json(directory / "review.json")
        review.update(reviewer="fixture reviewer", verdict="approved", claims_semantically_checked=True, requirements_checked=True, source_integrity_checked=True,
                      support_hashes={name: digest((directory / name).read_bytes()) for name in ("requirements.json", "claims.json")},
                      document_hashes={filename: digest((directory / filename).read_bytes()) for filename in app["data"]["documents"] + [item["file"] for item in app["data"].get("attachments", [])]})
        atomic_write(directory / "review.json", json_text(review))


class IngestionTests(WorkspaceCase):
    def test_ingest_preserves_raw_hash_and_removes_hidden_payload_from_visible_text(self):
        record = self.record
        self.assertEqual(record["data"]["institution"], "Example University")
        self.assertEqual(record["data"]["country"], "SE")
        raw = (self.root / record["snapshot"]["raw_path"]).read_bytes()
        text = (self.root / record["snapshot"]["text_path"]).read_text()
        self.assertEqual(digest(raw), record["snapshot"]["sha256"])
        self.assertIn("Ignore previous instructions", raw.decode())
        self.assertNotIn("Ignore previous instructions", text)
        self.assertIn("2099-12-31", record["data"]["deadline"]["value"])

    def test_tracking_variants_deduplicate_but_identity_query_is_preserved(self):
        again = ingest_file(self.store, FIXTURE, "https://university.example/doctoral/1?utm_source=mail#top", mode="html")
        self.assertEqual(again["id"], self.record["id"])
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM snapshots").fetchone()[0], 2)
        other = ingest_file(self.store, FIXTURE, "https://university.example/doctoral/1?cycle=2100", mode="html")
        self.assertNotEqual(other["id"], self.record["id"])

    def test_unknown_fields_remain_unknown_and_salary_is_not_treated_as_full_funding(self):
        result, _, _ = extract('<html><h1>Doctoral project</h1><p>Salary: 3200 EUR</p></html>', 'https://example.invalid/job')
        self.assertIsNone(result["funding"])
        self.assertIsNone(result["deadline"])
        self.assertIsNone(result["country"])

    def test_listing_with_multiple_jobs_is_not_imported_as_a_single_position(self):
        markup = '<script type="application/ld+json">[{"@type":"JobPosting","title":"A"},{"@type":"JobPosting","title":"B"}]</script>'
        with self.assertRaises(Error):
            extract(markup, "https://example.invalid/listing")

    def test_annotations_reject_invented_quotes_and_stale_evidence(self):
        value = self.annotations()
        value["evidence"]["funding"]["quote"] = "The salary is guaranteed for all applicants."
        with self.assertRaises(Error):
            assess.validate_annotations(self.store, self.record["id"], value)
        value = self.annotations()
        value["evidence"]["funding"]["evidence_sha256"] = "0" * 64
        with self.assertRaises(Error):
            assess.validate_annotations(self.store, self.record["id"], value)

    def test_failed_write_rolls_back_partial_database_changes(self):
        with self.assertRaises(RuntimeError):
            with self.store.transaction():
                self.store.db.execute("UPDATE opportunities SET status='dismissed'")
                raise RuntimeError("simulated interruption")
        self.assertEqual(self.store.get(self.record["id"])["status"], "new")


class AssessmentTests(WorkspaceCase):
    def test_unknown_funding_does_not_pass_a_full_funding_requirement(self):
        self.candidate["preferences"]["require_full_funding"] = True
        result = assess.screen(self.record, self.candidate)
        self.assertEqual(next(g for g in result["gates"] if g["name"] == "funding")["state"], "unknown")

    def test_preliminary_keyword_hits_never_become_semantic_scores(self):
        self.assertEqual(assess.discovery_signals(self.record, self.candidate)["topics"], ["comparative literature"])
        ranked = assess.ranking(self.record, self.candidate)
        self.assertIsNone(ranked["score"])
        self.assertEqual(ranked["coverage"], 0)

    def test_partial_assessment_has_interval_and_changes_invalidate_it(self):
        packet = assess.assessment_template(self.record, self.candidate)
        packet["assessor"] = "fixture assessor"
        packet["dimensions"]["research_fit"].update(score=4, reason="An explicit topic overlap.", posting_quotes=["Investigate archival sources and translation."], profile_refs=["/research/topics/0"])
        result = assess.save_assessment(self.store, self.record["id"], self.candidate, packet)
        self.assertEqual(result["coverage"], 30)
        self.assertEqual(result["score_interval"], [24.0, 94.0])
        self.assertIsNone(result["score"])
        changed_profile = copy.deepcopy(self.candidate)
        changed_profile["research"]["topics"].append("history")
        self.assertEqual(assess.ranking(self.store.get(self.record["id"]), changed_profile)["assessment_state"], "stale")
        assess.validate_annotations(self.store, self.record["id"], self.annotations())
        self.assertEqual(assess.ranking(self.store.get(self.record["id"]), self.candidate)["assessment_state"], "stale")

    def test_assessment_rejects_nan_and_unsupported_candidate_claims(self):
        packet = assess.assessment_template(self.record, self.candidate)
        packet["assessor"] = "fixture assessor"
        packet["dimensions"]["research_fit"].update(score=float("nan"))
        with self.assertRaises(Error):
            assess.save_assessment(self.store, self.record["id"], self.candidate, packet)
        packet["dimensions"]["research_fit"].update(score=5, posting_quotes=["Investigate archival sources and translation."], profile_refs=["/experience/99"])
        with self.assertRaises(Error):
            assess.save_assessment(self.store, self.record["id"], self.candidate, packet)

    def test_different_country_representations_do_not_create_false_veto(self):
        self.candidate["preferences"]["countries"] = ["Sweden"]
        gate = next(x for x in assess.screen(self.record, self.candidate)["gates"] if x["name"] == "country")
        self.assertEqual(gate["state"], "unknown")


class LifecycleTests(WorkspaceCase):
    def test_explicit_submitted_file_selection_preserves_the_callers_choice(self):
        app = self.reviewed_application()
        source = self.base / "optional-transcript.txt"
        source.write_text("Not selected for actual submission.")
        attachment = apps.attach_document(self.store, app["id"], source, "transcript")
        self.review(app)
        today = date.today().isoformat()
        apps.transition(self.store, app["id"], "drafted", occurred_on=today, note="reviewed")
        selected = ["cv.md", "motivation.md"]
        submitted = apps.transition(self.store, app["id"], "submitted", occurred_on=today, note="user selected these exact files", submitted_files=selected)
        archive = self.root / submitted["data"]["submission"]["archive"]
        self.assertEqual(read_json(archive / "manifest.json")["submitted_files"], selected)
        self.assertNotIn(attachment["file"], submitted["data"]["submission"]["files"])

    def test_modified_frozen_profile_is_rejected_even_if_a_reviewer_hash_is_unchanged(self):
        app = self.reviewed_application()
        directory = self.root / app["data"]["directory"]
        changed = read_json(directory / "profile.snapshot.json")
        changed["identity"]["name"] = "Unregistered identity change"
        atomic_write(directory / "profile.snapshot.json", json_text(changed))
        result = apps.verify_application(self.store, app["id"])
        self.assertEqual(next(check for check in result["checks"] if check["name"] == "source_archive")["state"], "fail")

    def test_transcripts_are_reviewed_immutable_attachments_and_archived_with_actual_submission(self):
        app = self.reviewed_application()
        source = self.base / "transcript.txt"
        source.write_text("Fictional university transcript, original source.")
        attachment = apps.attach_document(self.store, app["id"], source, "transcript")
        self.assertEqual(apps.verify_application(self.store, app["id"])["state"], "fail")
        self.review(app)
        self.assertEqual(apps.verify_application(self.store, app["id"])["state"], "pass")
        today = date.today().isoformat()
        apps.transition(self.store, app["id"], "drafted", occurred_on=today, note="reviewed with original transcript")
        submitted = apps.transition(self.store, app["id"], "submitted", occurred_on=today, note="user-confirmed submission")
        archive = self.root / submitted["data"]["submission"]["archive"]
        manifest = read_json(archive / "manifest.json")
        self.assertIn(attachment["file"], manifest["submitted_files"])
        self.assertEqual((archive / attachment["file"]).read_bytes(), source.read_bytes())
        with self.assertRaises(Error):
            apps.attach_document(self.store, app["id"], source, "transcript")

    def test_separate_official_requirements_are_checked_and_frozen_as_supporting_evidence(self):
        app = self.reviewed_application()
        directory = self.root / app["data"]["directory"]
        external = self.root / "research" / "programme-requirements.txt"
        atomic_write(external, "For this doctoral programme, submit an academic CV and motivation letter.")
        requirements = read_json(directory / "requirements.json")
        requirements["source_quote"] = ""
        requirements["external_evidence"] = [{"file": str(external.relative_to(self.root)), "sha256": digest(external.read_bytes()),
                                               "quote": "submit an academic CV and motivation letter", "url": "https://university.example/admissions"}]
        atomic_write(directory / "requirements.json", json_text(requirements))
        self.review(app)
        self.assertEqual(apps.verify_application(self.store, app["id"])["state"], "pass")
        today = date.today().isoformat()
        apps.transition(self.store, app["id"], "drafted", occurred_on=today, note="requirements reviewed")
        submitted = apps.transition(self.store, app["id"], "submitted", occurred_on=today, note="receipt")
        archive = self.root / submitted["data"]["submission"]["archive"]
        manifest = read_json(archive / "manifest.json")
        self.assertEqual(len(manifest["external_evidence"]), 1)
        self.assertEqual((archive / manifest["external_evidence"][0]["archived_file"]).read_bytes(), external.read_bytes())

    def test_changed_requirements_and_missing_required_attachments_cannot_keep_an_old_approval(self):
        app = self.reviewed_application()
        directory = self.root / app["data"]["directory"]
        requirements = read_json(directory / "requirements.json")
        requirements["attachments"] = {"attachments/transcript.pdf": {"required": True}}
        atomic_write(directory / "requirements.json", json_text(requirements))
        result = apps.verify_application(self.store, app["id"])
        self.assertEqual(result["state"], "fail")
        self.assertTrue(any(check["name"].startswith("required_attachment:") and check["state"] == "fail" for check in result["checks"]))

    def test_preparing_packet_cannot_be_marked_submitted_and_never_overwrites_drafts(self):
        app = apps.create_application(self.store, self.record["id"], self.candidate)
        with self.assertRaises(Error):
            apps.transition(self.store, app["id"], "submitted", occurred_on=date.today().isoformat(), note="test")
        with self.assertRaises(Error):
            apps.create_application(self.store, self.record["id"], self.candidate)
        self.assertEqual(apps.get_application(self.store, app["id"])["status"], "preparing")

    def test_full_review_submit_interview_offer_lifecycle_uses_immutable_submission(self):
        app = self.reviewed_application()
        result = apps.verify_application(self.store, app["id"])
        self.assertEqual(result["state"], "pass", json_text(result))
        apps.transition(self.store, app["id"], "drafted", occurred_on=date.today().isoformat(), note="reviewed")
        submitted = apps.transition(self.store, app["id"], "submitted", occurred_on=date.today().isoformat(), note="user-confirmed portal receipt")
        archive = self.root / submitted["data"]["submission"]["archive"]
        original = (archive / "motivation.md").read_bytes()
        live = self.root / app["data"]["directory"] / "motivation.md"
        live.write_text("Edited after submission")
        self.assertEqual((archive / "motivation.md").read_bytes(), original)
        self.assertEqual(digest(original), read_json(archive / "manifest.json")["files"]["motivation.md"])
        packet = apps.interview_packet(self.store, app["id"])
        self.assertEqual(packet["basis"], "submitted_archive")
        apps.transition(self.store, app["id"], "interview", occurred_on=date.today().isoformat(), note="Panel invitation")
        apps.transition(self.store, app["id"], "offer", occurred_on=date.today().isoformat(), note="Offer letter")
        accepted = apps.transition(self.store, app["id"], "accepted", occurred_on=date.today().isoformat(), note="User accepted offer")
        self.assertEqual(accepted["status"], "accepted")

    def test_edit_after_review_and_unsupported_claim_both_fail_verification(self):
        app = self.reviewed_application()
        directory = self.root / app["data"]["directory"]
        with (directory / "motivation.md").open("a") as f:
            f.write("I have 100 publications.\n")
        result = apps.verify_application(self.store, app["id"])
        self.assertEqual(next(x for x in result["checks"] if x["name"] == "review")["state"], "fail")
        claims = read_json(directory / "claims.json")
        claims["claims"].append({"file": "motivation.md", "text": "I have 100 publications.", "profile_refs": ["/outputs/99"]})
        atomic_write(directory / "claims.json", json_text(claims))
        self.review(app)
        result = apps.verify_application(self.store, app["id"])
        self.assertEqual(next(x for x in result["checks"] if x["name"] == "claim_registry")["state"], "fail")

    def test_missing_pdf_is_not_reported_as_verified(self):
        app = self.reviewed_application()
        result = apps.verify_application(self.store, app["id"], require_pdf=True)
        self.assertEqual(result["state"], "fail")
        self.assertTrue(any(x["name"].endswith(":pdf") and x["state"] == "fail" for x in result["checks"]))

    def test_followups_are_drafts_and_repeated_generation_is_idempotent(self):
        app = self.reviewed_application()
        apps.transition(self.store, app["id"], "drafted", occurred_on=date.today().isoformat(), note="reviewed")
        old = (date.today() - timedelta(days=30)).isoformat()
        apps.transition(self.store, app["id"], "submitted", occurred_on=old, note="receipt")
        first = apps.followups(self.store, self.candidate, draft=True)
        second = apps.followups(self.store, self.candidate, draft=True)
        self.assertEqual(first[0]["file"], second[0]["file"])
        self.assertEqual(len(list((self.root / app["data"]["directory"]).glob("followup-*"))), 1)
        self.assertFalse(any(e["kind"] == "followup_sent" for e in apps.get_application(self.store, app["id"])["events"]))


class ExportAndIntegrationTests(WorkspaceCase):
    def test_doctor_and_backup_work_even_when_the_candidate_profile_is_malformed(self):
        atomic_write(self.root / "profile.json", "{broken JSON")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = main(["--workspace", str(self.root), "doctor"])
        self.assertEqual(result, 1)
        self.assertFalse(json.loads(output.getvalue())["profile_valid"])
        target = self.base / "damaged-profile-backup.zip"
        with contextlib.redirect_stdout(io.StringIO()):
            result = main(["--workspace", str(self.root), "backup", "--out", str(target)])
        self.assertEqual(result, 0)
        self.assertTrue(target.is_file())

    def test_html_and_csv_exports_handle_injection_strings(self):
        data = dict(self.record["data"])
        data["title"] = "=SUM(1,2)<script>alert('x')</script>"
        with self.store.transaction():
            self.store.db.execute("UPDATE opportunities SET data=? WHERE id=?", (json_text(data), self.record["id"]))
        target = self.base / "report.html"
        exports.report(self.store, self.candidate, target)
        markup = target.read_text()
        self.assertNotIn("<script>alert('x')</script>", markup)
        self.assertIn("&lt;script&gt;", markup)
        csv_target = self.base / "tracker.csv"
        exports.export_csv(self.store, self.candidate, csv_target)
        row = next(csv.DictReader(io.StringIO(csv_target.read_text())))
        self.assertTrue(row["title"].startswith("'="))

    def test_calendar_preserves_date_only_deadline_and_folds_unicode(self):
        value = self.annotations()
        value["values"]["deadline"] = "2099-12-31"
        value["evidence"]["deadline"] = {"basis": "user_confirmed", "note": "date-only source fixture"}
        assess.validate_annotations(self.store, self.record["id"], value)
        target = self.base / "deadlines.ics"
        exports.calendar(self.store, target)
        text = target.read_text()
        self.assertIn("DTSTART;VALUE=DATE:20991231", text)
        self.assertNotIn("20991231T000000Z", text)
        for line in exports.fold_line("SUMMARY:" + "Исследование " * 30).split("\r\n"):
            self.assertLessEqual(len(line.encode()), 75)

    def test_backup_restores_consistent_evidence_and_rejects_path_traversal(self):
        target = self.base / "backup.zip"
        exports.backup(self.store, target)
        destination = self.base / "restored"
        exports.restore(target, destination)
        with Store(destination) as restored:
            self.assertEqual(restored.get(self.record["id"])["snapshot"]["sha256"], self.record["snapshot"]["sha256"])
        hostile = self.base / "hostile.zip"
        with zipfile.ZipFile(hostile, "w") as archive:
            archive.writestr("../escape.txt", "bad")
        with self.assertRaises(Error):
            exports.restore(hostile, self.base / "unsafe")
        self.assertFalse((self.base / "escape.txt").exists())

    def test_mail_signals_require_explicit_approval_and_are_idempotent(self):
        app = self.reviewed_application()
        apps.transition(self.store, app["id"], "drafted", occurred_on=date.today().isoformat(), note="reviewed")
        apps.transition(self.store, app["id"], "submitted", occurred_on=date.today().isoformat(), note="receipt")
        signal = {"message_id": "mail-1", "application_id": app["id"], "source_url": "https://mail.google.com/mail/u/0/#inbox/mail-1",
                  "quote": "We would like to invite you to an interview.", "proposed_status": "interview", "occurred_on": date.today().isoformat()}
        batch = integrations.import_mail_signals(self.store, {"signals": [signal]})
        self.assertEqual(apps.get_application(self.store, app["id"])["status"], "submitted")
        with self.assertRaises(Error):
            integrations.apply_mail_signals(self.store, batch["batch_id"], [])
        integrations.apply_mail_signals(self.store, batch["batch_id"], ["mail-1"])
        again = integrations.apply_mail_signals(self.store, batch["batch_id"], ["mail-1"])
        self.assertEqual(again["changes"][0]["state"], "already_applied")
        self.assertEqual(apps.get_application(self.store, app["id"])["status"], "interview")
        signal["proposed_status"] = "accepted"
        with self.assertRaises(Error):
            integrations.import_mail_signals(self.store, {"signals": [signal]})

    def test_init_is_idempotent_and_cli_reports_missing_workspace(self):
        old = (self.root / "profile.json").read_bytes()
        initialise(self.root)
        self.assertEqual((self.root / "profile.json").read_bytes(), old)
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            code = main(["--workspace", str(self.base / "missing"), "rank"])
        self.assertEqual(code, 2)
        self.assertIn("not initialised", errors.getvalue())


class DeadlineTests(unittest.TestCase):
    def test_visible_date_only_deadline_overrides_machine_midnight_without_inventing_a_cutoff(self):
        markup = '<script type="application/ld+json">{"@type":"JobPosting","title":"PhD","validThrough":"2026-11-15T00:00:00+00:00"}</script><h1>PhD</h1><p>Closes:</p><p>15th November 2026</p>'
        data, _, _ = extract(markup, "https://university.example/job/1")
        self.assertEqual(data["deadline"]["precision"], "date")
        self.assertEqual(data["deadline"]["value"], "2026-11-15")
        self.assertEqual(len(data["deadline_candidates"]), 2)

    def test_named_timezone_and_unknown_timezone_have_distinct_semantics(self):
        value = parse_deadline("2 Nov 2026 - 23:59 (Europe/Lisbon)")
        self.assertEqual(value["precision"], "time")
        self.assertIn("23:59", value["value"])
        self.assertIsNone(parse_deadline("2026-11-02T23:59:00")["value"])

    def test_date_only_deadline_is_not_expired_at_midnight_utc(self):
        value = parse_deadline("2026-11-02")
        self.assertNotEqual(deadline_state(value, datetime(2026, 11, 3, 0, 1, tzinfo=timezone.utc))["state"], "expired")
        self.assertEqual(deadline_state(value, datetime(2026, 11, 3, 13, tzinfo=timezone.utc))["state"], "expired")

    def test_canonical_url_rejects_embedded_credentials(self):
        with self.assertRaises(Error):
            canonical_url("https://official.example@attacker.example/job")


if __name__ == "__main__":
    unittest.main()
