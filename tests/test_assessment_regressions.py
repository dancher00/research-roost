from __future__ import annotations

import json

from test_workflows import FIXTURE, WorkspaceCase

from phd_search import assessment as assess
from phd_search import exports
from phd_search.core import atomic_write, digest, json_text
from phd_search.evidence import ingest_file


class AssessmentRegressionTests(WorkspaceCase):
    def test_old_funding_annotation_cannot_hide_a_refreshed_opportunity(self):
        self.candidate["preferences"]["require_full_funding"] = True
        source = self.base / "old.html"
        source.write_text(FIXTURE.read_text().replace(
            "Full tuition and a monthly stipend are covered.", "This position is self-funded."
        ))
        self.record = ingest_file(self.store, source, self.record["url"], mode="html")
        annotation = self.annotations()
        annotation["values"]["funding"] = {"status": "self_funded"}
        annotation["evidence"]["funding"]["quote"] = "This position is self-funded."
        assess.validate_annotations(self.store, self.record["id"], annotation)
        self.assertEqual(assess.rank_all(self.store, self.candidate), [])

        refreshed = ingest_file(self.store, FIXTURE, self.record["url"], mode="html")
        screen = assess.screen(refreshed, self.candidate)
        self.assertNotEqual(screen["verdict"], "fail")
        self.assertEqual(next(g for g in screen["gates"] if g["name"] == "annotations_current")["state"], "unknown")
        self.assertIsNone(assess.merged(refreshed)["funding"])
        self.assertEqual(refreshed["annotations"]["values"]["funding"]["status"], "self_funded")
        self.assertEqual(len(assess.rank_all(self.store, self.candidate)), 1)

        self.record = refreshed
        current = assess.validate_annotations(self.store, refreshed["id"], self.annotations())
        self.assertEqual(assess.merged(current)["funding"]["status"], "fully_funded")
        self.assertEqual(assess.screen(current, self.candidate)["verdict"], "pass")

    def external_assessment(self):
        evidence = self.root / "research" / "training.txt"
        evidence.write_text("The programme provides archival training.")
        packet = assess.assessment_template(self.record, self.candidate)
        packet["assessor"] = "Synthetic regression reviewer"
        packet["dimensions"]["environment"].update(
            score=5, reason="Archived primary evidence of training.",
            external_evidence=[{
                "file": "research/training.txt", "sha256": digest(evidence.read_bytes()),
                "quote": "archival training", "url": "https://university.example/training",
            }],
        )
        ranked = assess.save_assessment(self.store, self.record["id"], self.candidate, packet)
        self.assertEqual(ranked["assessment_state"], "current")
        self.assertEqual(ranked["coverage"], 5)
        return evidence

    def test_deleted_external_evidence_invalidates_ranking_and_export(self):
        evidence = self.external_assessment()
        evidence.unlink()
        ranked = assess.rank_all(self.store, self.candidate)[0]
        self.assertEqual(ranked["assessment_state"], "stale")
        self.assertEqual(ranked["coverage"], 0)
        self.assertEqual(ranked["score_interval"], [0, 100])
        self.assertTrue(ranked["assessment_issues"])
        row = exports.tracker_rows(self.store, self.candidate)[0]
        self.assertEqual(row["assessment_state"], "stale")
        self.assertIsNone(row["score"])
        self.assertEqual(row["coverage"], 0)

    def test_modified_external_evidence_stays_stale_until_original_is_restored(self):
        evidence = self.external_assessment()
        original = evidence.read_bytes()
        evidence.write_text("The programme does not provide archival training.")
        self.assertEqual(assess.rank_all(self.store, self.candidate)[0]["assessment_state"], "stale")
        evidence.write_bytes(original)
        self.assertEqual(assess.rank_all(self.store, self.candidate)[0]["assessment_state"], "current")

    def test_external_assessment_without_workspace_cannot_claim_current(self):
        self.external_assessment()
        ranked = assess.ranking(self.store.get(self.record["id"]), self.candidate)
        self.assertEqual(ranked["assessment_state"], "stale")
        self.assertEqual(ranked["coverage"], 0)

    def test_stale_deadline_annotation_does_not_replace_new_source_deadline(self):
        annotation = self.annotations()
        annotation["values"]["deadline"] = "2020-01-01"
        annotation["evidence"]["deadline"] = {"basis": "user_confirmed", "note": "Synthetic original deadline"}
        self.record = assess.validate_annotations(self.store, self.record["id"], annotation)
        changed = self.base / "changed.html"
        changed.write_text(FIXTURE.read_text().replace("Example University", "Updated Example University"))
        refreshed = ingest_file(self.store, changed, self.record["url"], mode="html")
        self.assertEqual(assess.screen(refreshed, self.candidate)["deadline"]["state"], "open")

    def test_rank_cli_revalidates_external_evidence_after_import(self):
        import contextlib
        import io

        from phd_search.cli import main

        evidence = self.external_assessment()
        atomic_write(self.root / "profile.json", json_text(self.candidate))
        evidence.unlink()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--workspace", str(self.root), "rank"]), 0)
        self.assertEqual(json.loads(output.getvalue())[0]["assessment_state"], "stale")
