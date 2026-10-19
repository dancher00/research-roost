from __future__ import annotations

import contextlib
import io
import json
from datetime import date, datetime, time, timedelta, timezone

from test_workflows import WorkspaceCase

from phd_search import applications as apps
from phd_search import assessment as assess
from phd_search.cli import main
from phd_search.core import atomic_write, digest, json_text, read_json


class ApplicationRegressionTests(WorkspaceCase):
    def cli(self, *arguments):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = main(["--workspace", str(self.root), *arguments])
        return code, json.loads(output.getvalue() or errors.getvalue())

    def submitted(self, *, variant="main", age=30, attachment=False, external=False):
        application = self.reviewed_application(variant)
        if attachment:
            original = self.base / "transcript.txt"
            original.write_text("Original transcript for the synthetic candidate.\n")
            apps.attach_document(self.store, application["id"], original, "transcript")
            self.review(application)
        if external:
            source = self.root / "research" / "requirements.txt"
            source.write_text("Official application requirements from another source.\n")
            requirements_path = self.root / application["data"]["directory"] / "requirements.json"
            requirements = read_json(requirements_path)
            requirements["external_evidence"] = [{
                "file": "research/requirements.txt", "sha256": digest(source.read_bytes()),
                "quote": "Official application requirements", "url": "https://university.example/requirements",
            }]
            atomic_write(requirements_path, json_text(requirements))
            self.review(application)
        occurred = (date.today() - timedelta(days=age)).isoformat()
        for status in ("drafted", "submitted"):
            code, payload = self.cli("application", "status", application["id"], status,
                                     "--on", occurred, "--note", "Synthetic user-confirmed receipt/review")
            self.assertEqual(code, 0, payload)
        return apps.get_application(self.store, application["id"])

    def event(self, application, kind, details):
        event_file = self.base / "event.json"
        atomic_write(event_file, json_text(details))
        return self.cli("application", "event", application["id"], "--kind", kind, "--file", str(event_file))

    def remove_manifest_anchor_for_legacy_archive(self, application):
        data = application["data"]
        data["submission"].pop("manifest_sha256")
        with self.store.transaction():
            self.store.db.execute("UPDATE applications SET data=? WHERE id=?", (json_text(data), application["id"]))

    def assert_interview_rejected(self, application):
        code, payload = self.cli("interview", application["id"])
        self.assertEqual(code, 2, payload)
        self.assertEqual(payload["type"], "Error")
        self.assertFalse((self.root / application["data"]["directory"] / "interview.md").exists())

    def test_interview_checks_every_archived_file_not_only_profile(self):
        application = self.submitted(attachment=True, external=True)
        archive = self.root / application["data"]["submission"]["archive"]
        manifest = read_json(archive / "manifest.json")
        self.assertEqual(application["data"]["submission"]["manifest_sha256"], digest((archive / "manifest.json").read_bytes()))
        self.assertTrue(any(name.startswith("attachments/") for name in manifest["files"]))
        self.assertTrue(any(name.startswith("supporting-evidence/") for name in manifest["files"]))
        # The submitted evidence is self-contained, even if its live source is removed.
        (self.root / "research" / "requirements.txt").unlink()
        for filename in manifest["files"]:
            with self.subTest(filename=filename):
                path = archive / filename
                original = path.read_bytes()
                path.write_bytes(original + b"\nChanged after submission\n")
                self.assert_interview_rejected(application)
                path.write_bytes(original)
        code, packet = self.cli("interview", application["id"])
        self.assertEqual(code, 0, packet)
        self.assertEqual(packet["basis"], "submitted_archive")

    def test_missing_archive_files_or_manifest_cannot_generate_interview(self):
        application = self.submitted()
        archive = self.root / application["data"]["submission"]["archive"]
        for filename in ("motivation.md", "manifest.json"):
            with self.subTest(filename=filename):
                path = archive / filename
                original = path.read_bytes()
                path.unlink()
                self.assert_interview_rejected(application)
                path.write_bytes(original)

    def test_changed_manifest_cannot_redefine_a_recorded_submission(self):
        application = self.submitted()
        archive = self.root / application["data"]["submission"]["archive"]
        manifest = read_json(archive / "manifest.json")
        (archive / "motivation.md").write_text("A replacement for the submitted application.")
        manifest["files"]["motivation.md"] = digest((archive / "motivation.md").read_bytes())
        atomic_write(archive / "manifest.json", json_text(manifest))
        self.assert_interview_rejected(application)

    def test_legacy_manifest_paths_and_file_inventory_are_verified(self):
        application = self.submitted()
        self.remove_manifest_anchor_for_legacy_archive(application)
        archive = self.root / application["data"]["submission"]["archive"]
        original = read_json(archive / "manifest.json")
        for unsafe in ("../outside.txt", str(self.base / "absolute.txt"), "..\\outside.txt"):
            with self.subTest(path=unsafe):
                manifest = json.loads(json_text(original))
                manifest["files"][unsafe] = digest("outside")
                manifest["support_files"].append(unsafe)
                atomic_write(archive / "manifest.json", json_text(manifest))
                self.assert_interview_rejected(application)
        for removed in ("profile.snapshot.json", "motivation.md"):
            with self.subTest(removed=removed):
                manifest = json.loads(json_text(original))
                del manifest["files"][removed]
                for name in ("submitted_files", "support_files"):
                    manifest[name] = [entry for entry in manifest[name] if entry != removed]
                atomic_write(archive / "manifest.json", json_text(manifest))
                self.assert_interview_rejected(application)
        atomic_write(archive / "manifest.json", json_text(original))
        code, payload = self.cli("interview", application["id"])
        self.assertEqual(code, 0, payload)

    def test_legacy_archive_rejects_symlink_escape_and_wrong_identity(self):
        application = self.submitted()
        self.remove_manifest_anchor_for_legacy_archive(application)
        archive = self.root / application["data"]["submission"]["archive"]
        motivation = archive / "motivation.md"
        original_bytes = motivation.read_bytes()
        outside = self.base / "outside-motivation.md"
        outside.write_bytes(original_bytes)
        motivation.unlink()
        motivation.symlink_to(outside)
        self.assert_interview_rejected(application)
        motivation.unlink()
        motivation.write_bytes(original_bytes)
        manifest = read_json(archive / "manifest.json")
        manifest["application_id"] = "another-application"
        atomic_write(archive / "manifest.json", json_text(manifest))
        self.assert_interview_rejected(application)

    def test_interview_keeps_verified_submission_separate_from_later_work(self):
        application = self.submitted()
        directory = self.root / application["data"]["directory"]
        later = read_json(directory / "profile.snapshot.json")
        later["facts"][0]["claim"] = "A fabricated later achievement."
        atomic_write(directory / "profile.snapshot.json", json_text(later))
        atomic_write(directory / "posting.txt", "Unrelated later posting.")
        atomic_write(directory / "motivation.md", "A rewritten live draft.")
        code, packet = self.cli("interview", application["id"])
        self.assertEqual(code, 0, packet)
        text = (directory / "interview.md").read_text()
        self.assertIn(self.candidate["facts"][0]["claim"], text)
        self.assertNotIn("fabricated later achievement", text)
        self.assertNotIn("Unrelated later posting", text)

    def test_legacy_archive_keeps_external_evidence_independent_of_live_files(self):
        application = self.submitted(external=True)
        self.remove_manifest_anchor_for_legacy_archive(application)
        (self.root / "research" / "requirements.txt").unlink()
        code, packet = self.cli("interview", application["id"])
        self.assertEqual(code, 0, packet)
        self.assertEqual(packet["basis"], "submitted_archive")

    def test_submission_directory_cannot_use_traversal_even_inside_workspace(self):
        application = self.submitted()
        data = application["data"]
        data["submission"]["archive"] = "../" + self.root.name + "/" + data["submission"]["archive"]
        with self.store.transaction():
            self.store.db.execute("UPDATE applications SET data=? WHERE id=?", (json_text(data), application["id"]))
        self.assert_interview_rejected(application)

    def test_briefing_revalidates_current_external_assessment_in_workspace(self):
        source = self.root / "research" / "training.txt"
        source.write_text("The programme offers archival research training.\n")
        assessment = assess.assessment_template(self.record, self.candidate)
        assessment["assessor"] = "Synthetic research reviewer"
        assessment["dimensions"]["environment"].update(
            score=5, reason="Current archived training information.",
            external_evidence=[{
                "file": "research/training.txt", "sha256": digest(source.read_bytes()),
                "quote": "archival research training", "url": "https://university.example/training",
            }],
        )
        assess.save_assessment(self.store, self.record["id"], self.candidate, assessment)
        application = apps.create_application(self.store, self.record["id"], self.candidate, document_kinds=["cv"])
        briefing = (self.root / application["data"]["directory"] / "briefing.md").read_text()
        evaluation = json.loads(briefing.split("```json\n", 1)[1].split("```", 1)[0])
        self.assertEqual(evaluation["assessment_state"], "current")
        self.assertEqual(evaluation["coverage"], 5)

    def test_recent_invitation_status_resets_followup_without_schedule(self):
        application = self.submitted()
        code, payload = self.cli("application", "status", application["id"], "interview",
                                 "--on", date.today().isoformat(), "--note", "Actual invitation received today")
        self.assertEqual(code, 0, payload)
        code, suggestions = self.cli("followup", "--application", application["id"], "--draft")
        self.assertEqual(code, 0, suggestions)
        self.assertEqual(suggestions, [])
        self.assertFalse(list((self.root / application["data"]["directory"]).glob("followup-*")))

    def test_pending_interview_or_assessment_blocks_generic_followup(self):
        for index, (kind, day) in enumerate((
            ("interview_scheduled", date.today()),
            ("interview_scheduled", date.today() + timedelta(days=1)),
            ("assessment_due", date.today() + timedelta(days=8)),
        )):
            with self.subTest(kind=kind, day=day):
                application = self.submitted(variant="scheduled-" + str(index))
                code, payload = self.event(application, kind, {"at": day.isoformat() + "T00:00:00+00:00", "note": "Confirmed scheduled stage"})
                self.assertEqual(code, 0, payload)
                code, suggestions = self.cli("followup", "--application", application["id"], "--draft")
                self.assertEqual(code, 0, suggestions)
                self.assertEqual(suggestions, [])

    def test_scheduled_stage_waiting_period_is_separate_from_actual_contact_age(self):
        application = self.submitted()
        recent = (date.today() - timedelta(days=3)).isoformat() + "T12:00:00+00:00"
        self.assertEqual(self.event(application, "interview_scheduled", {"at": recent, "note": "Recorded interview schedule"})[0], 0)
        self.assertEqual(self.cli("followup", "--application", application["id"])[1], [])
        older = self.submitted(variant="older-stage")
        past = (date.today() - timedelta(days=16)).isoformat() + "T12:00:00+00:00"
        self.assertEqual(self.event(older, "interview_scheduled", {"at": past, "note": "Earlier scheduled stage"})[0], 0)
        code, suggestions = self.cli("followup", "--application", older["id"])
        self.assertEqual(code, 0, suggestions)
        self.assertEqual(suggestions[0]["days_since_contact"], 30)

    def test_schedule_waiting_period_uses_same_calendar_zone_as_today(self):
        instant = datetime.combine(date.today() - timedelta(days=13), time(0, 30)).astimezone()
        for index, offset in enumerate((-12, 14)):
            with self.subTest(offset=offset):
                application = self.submitted(variant="timezone-" + str(index))
                at = instant.astimezone(timezone(timedelta(hours=offset))).isoformat()
                code, payload = self.event(application, "interview_scheduled", {"at": at, "note": "Same scheduled instant in another timezone"})
                self.assertEqual(code, 0, payload)
                self.assertEqual(self.cli("followup", "--application", application["id"])[1], [])

    def test_confirmed_mail_invitation_uses_message_date_not_import_date(self):
        for index, age in enumerate((0, 20)):
            with self.subTest(message_age=age):
                application = self.submitted(variant="mail-" + str(index))
                signal = {"signals": [{
                    "message_id": "invitation-" + str(index), "application_id": application["id"],
                    "source_url": "https://mail.google.com/mail/u/0/#inbox/invitation-" + str(index),
                    "quote": "We invite you to an interview.", "proposed_status": "interview",
                    "occurred_on": (date.today() - timedelta(days=age)).isoformat(),
                }]}
                source = self.base / "mail.json"
                atomic_write(source, json_text(signal))
                code, batch = self.cli("mail", "import", "--file", str(source))
                self.assertEqual(code, 0, batch)
                code, applied = self.cli("mail", "apply", batch["batch_id"], "--approve", signal["signals"][0]["message_id"])
                self.assertEqual(code, 0, applied)
                code, suggestions = self.cli("followup", "--application", application["id"])
                self.assertEqual(code, 0, suggestions)
                if age == 0:
                    self.assertEqual(suggestions, [])
                else:
                    self.assertEqual(len(suggestions), 1)
                    self.assertEqual(suggestions[0]["days_since_contact"], 20)

    def test_recording_metadata_or_unknown_dates_cannot_invent_recent_contact(self):
        application = self.submitted()
        for kind in ("note", "contact_sent", "interview_feedback"):
            self.assertEqual(self.event(application, kind, {"note": "Imported legacy record with unknown event date"})[0], 0)
        apps.set_referees(self.store, application["id"], [])
        code, suggestions = self.cli("followup", "--application", application["id"])
        self.assertEqual(code, 0, suggestions)
        self.assertEqual(suggestions[0]["days_since_contact"], 30)
        self.assertEqual(self.event(application, "contact_sent", {
            "note": "Actual communication twenty days ago", "occurred_on": (date.today() - timedelta(days=20)).isoformat(),
        })[0], 0)
        self.assertEqual(self.cli("followup", "--application", application["id"])[1][0]["days_since_contact"], 20)
        self.assertEqual(self.event(application, "contact_sent", {
            "note": "Actual communication today", "occurred_on": date.today().isoformat(),
        })[0], 0)
        self.assertEqual(self.cli("followup", "--application", application["id"])[1], [])

    def test_future_actual_contact_is_rejected_without_recording_or_hiding_followup(self):
        application = self.submitted()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        before = len(apps.get_application(self.store, application["id"])["events"])
        for kind in ("contact_sent", "followup_sent", "interview_feedback"):
            with self.subTest(kind=kind):
                code, payload = self.event(application, kind, {"occurred_on": tomorrow, "note": "Only planned, not sent"})
                self.assertEqual(code, 2, payload)
                self.assertEqual(payload["type"], "Error")
        self.assertEqual(len(apps.get_application(self.store, application["id"])["events"]), before)
        self.assertEqual(self.cli("followup", "--application", application["id"])[1][0]["days_since_contact"], 30)

    def test_invalid_schedule_timestamps_report_errors_without_recording(self):
        application = self.submitted()
        before = len(apps.get_application(self.store, application["id"])["events"])
        for timestamp in (None, 123, {}, "2026-11-20T14:00:00"):
            with self.subTest(timestamp=timestamp):
                code, payload = self.event(application, "interview_scheduled", {"at": timestamp, "note": "Invalid timestamp"})
                self.assertEqual(code, 2, payload)
                self.assertEqual(payload["type"], "Error")
        self.assertEqual(len(apps.get_application(self.store, application["id"])["events"]), before)
