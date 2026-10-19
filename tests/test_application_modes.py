"""Public-CLI application lifecycle probes with new, entirely synthetic inputs.

These do not import implementation modules or the old fixture/test helpers.
No network, PDF engine, email or actual submission is used.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path):
    return json.loads(path.read_text())


def write(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


class ApplicationModesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="roost-application-modes-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.workspace = self.base / "private"
        self.cli("init")
        self.profile = read(self.workspace / "profile.json")
        self.profile["identity"].update(name="Mira Example", email="mira@example.invalid")
        self.profile["research"].update(topics=["archaeological imaging"], methods=["photogrammetry"],
                                        statement="I study archaeological imaging using photogrammetry.")
        self.fact = "I documented the image-processing choices in a synthetic archaeology project."
        self.profile["facts"] = [{"id": "imaging", "claim": self.fact,
                                   "source": "Fictional candidate declaration for offline testing", "confirmed": True}]
        self.save_profile()
        self.future = date.today().year + 2
        self.today = date.today().isoformat()

    def cli(self, *arguments, code=0):
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(REPOSITORY)
        result = subprocess.run([sys.executable, "-m", "phd_search", "--workspace", str(self.workspace), *arguments],
                                cwd=self.base, env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, code, (arguments, result.stdout, result.stderr))
        return json.loads(result.stdout or result.stderr)

    def save_profile(self):
        path = self.base / "candidate.json"
        write(path, self.profile)
        self.cli("profile", "import", "--file", str(path))

    def opportunity(self, kind="summer_school", *, reviewed=True):
        mode = "internship" if kind == "research_internship" else "school"
        title = "Archaeological Imaging Research Internship" if mode == "internship" else "Field Imaging " + kind.replace("_", " ").title()
        self.requirement_quote = "Submit a CV and a motivation letter of 100 to 220 words explaining preparation and learning goals."
        self.source_claim = "The programme covers photogrammetry and documentation of archaeological materials."
        self.deadlines = [
            {"id": "admission", "kind": "application", "label": "Admission", "deadline": f"{self.future}-05-15T16:00:00+00:00", "required": True},
            {"id": "aid", "kind": "funding", "label": "Financial aid", "deadline": f"{self.future}-05-01", "required": False},
            {"id": "confirm", "kind": "registration", "label": "Attendance confirmation", "deadline": f"{self.future}-06-01", "required": True},
        ]
        source = (f"<html><head><title>{title}</title></head><body><main><h1>{title}</h1>"
                  f"<p>{self.source_claim}</p><p>{self.requirement_quote}</p>"
                  f"<p>Eligibility: applications are accepted at all career stages; no degree or publication prerequisite. "
                  f"There is no selection interview. All eligibility requirements have been reviewed.</p>"
                  f"<p>Participation starts {self.future}-07-02 and ends {self.future}-07-29.</p>"
                  f"<p>Application {self.future}-05-15T16:00:00+00:00; financial aid {self.future}-05-01; attendance confirmation {self.future}-06-01.</p>"
                  "<p>Host: Fictional Imaging Institute. The page is a local synthetic fixture and is not a real opportunity.</p></main></body></html>")
        self.source_file = self.base / (kind + ".html")
        self.source_file.write_text(source)
        self.source_url = "https://example.invalid/imaging/" + kind
        record = self.cli("opportunity", "import", "--file", str(self.source_file), "--url", self.source_url, "--mode", "html")
        record = self.cli("opportunity", "show", record["id"])
        values = {"opportunity_type": kind, "institution": "Fictional Imaging Institute", "requirements": {"reviewed": reviewed},
                  "start_date": f"{self.future}-07-02", "end_date": f"{self.future}-07-29", "deadlines": self.deadlines}
        self.annotation = {"values": values, "evidence": {key: {"quote": title if key == "opportunity_type" else
                               "All eligibility requirements have been reviewed." if key == "requirements" else
                               "Fictional Imaging Institute" if key == "institution" else
                               f"{self.future}-07-02" if key == "start_date" else f"{self.future}-07-29" if key == "end_date" else
                               f"Application {self.future}-05-15T16:00:00+00:00; financial aid {self.future}-05-01; attendance confirmation {self.future}-06-01.",
                               "evidence_sha256": record["snapshot"]["sha256"]} for key in values}}
        self.annotation_file = self.base / (kind + "-annotation.json")
        write(self.annotation_file, self.annotation)
        self.cli("opportunity", "annotate", record["id"], "--file", str(self.annotation_file))
        return self.cli("opportunity", "show", record["id"])

    def application(self, kind="summer_school", *, reviewed=True, documents=None):
        record = self.opportunity(kind, reviewed=reviewed)
        arguments = ["application", "create", record["id"]]
        if documents is not None:
            arguments.extend(["--documents", *documents])
        app = self.cli(*arguments)
        return app, record

    def prepare(self, app):
        directory = self.workspace / app["data"]["directory"]
        introduction = ("I am applying to develop a careful and reproducible approach to archaeological imaging. "
                        "My immediate goal is to understand which acquisition and processing choices affect the interpretation "
                        "of a reconstructed object. I would use the advertised period to practise these choices, compare their "
                        "limitations and explain the resulting uncertainty to other participants.")
        motivation = ("# Motivation\n\n" + self.fact + "\n\n" + self.source_claim + "\n\n" + introduction + "\n\n"
                      "I would bring the documented decisions from that project into discussions and ask for feedback on "
                      "alternative procedures. I want to leave with a small worked example that records the steps needed "
                      "to reproduce an imaging result. This is a proposed learning outcome; it is not a claim that the host "
                      "has approved a project, supplied resources or awarded funding.\n")
        (directory / "motivation.md").write_text(motivation)
        claims = read(directory / "claims.json")
        claims["claims"].extend([
            {"file": "motivation.md", "text": self.fact, "profile_refs": ["/facts/0"]},
            {"file": "motivation.md", "text": self.source_claim, "posting_quotes": [self.source_claim]},
        ])
        claims["coverage_reviewed"] = True
        write(directory / "claims.json", claims)
        requirements = read(directory / "requirements.json")
        requirements.update(source_quote=self.requirement_quote, plan_state="reviewed")
        requirements["documents"]["motivation.md"].update(exact_prompt=self.requirement_quote, min_words=100, max_words=220)
        write(directory / "requirements.json", requirements)
        self.approve(app)
        return directory

    def approve(self, app):
        directory = self.workspace / app["data"]["directory"]
        review = read(directory / "review.json")
        review.update(reviewer="Synthetic local lifecycle reviewer; not an independent scientific validation", verdict="approved",
                      claims_semantically_checked=True, requirements_checked=True, source_integrity_checked=True,
                      document_hashes={name: sha(directory / name) for name in app["data"]["documents"]},
                      support_hashes={name: sha(directory / name) for name in ("claims.json", "requirements.json")})
        write(directory / "review.json", review)

    def drafted(self, app):
        return self.cli("application", "status", app["id"], "drafted", "--on", self.today, "--note", "Synthetic reviewed packet")

    def submit(self, app, *, code=0):
        return self.cli("application", "status", app["id"], "submitted", "--on", self.today,
                        "--note", "Fictional test receipt; no external submission occurred", "--allow-unknown", code=code)

    def lifecycle(self, kind, expected):
        app, record = self.application(kind)
        self.assertEqual(app["status"], "preparing")
        self.assertEqual(app["data"]["opportunity_family"], expected)
        self.assertEqual(app["data"]["opportunity_type"], kind)
        self.assertEqual(app["data"]["rubric"], {"id": expected, "version": 1, "family": expected})
        self.assertEqual(app["data"]["documents"], ["cv.md", "motivation.md"])
        self.assertEqual([entry["id"] for entry in app["data"]["deadlines"]], ["admission", "aid", "confirm"])
        self.assertEqual(self.cli("application", "verify", app["id"], code=1)["state"], "fail")
        self.cli("application", "status", app["id"], "drafted", "--note", "Cannot approve unfinished packet", "--allow-unknown", code=2)
        directory = self.prepare(app)
        verified = self.cli("application", "verify", app["id"])
        self.assertEqual(verified["state"], "pass", verified)
        self.assertTrue(all(check["state"] == "pass" for check in verified["checks"]))
        rendered = self.cli("application", "render", app["id"])
        for document in rendered["documents"]:
            self.assertTrue(Path(document["tex"]).is_file())
            self.assertTrue(Path(document["html"]).is_file())
        self.drafted(app)
        submitted = self.submit(app)
        archive = self.workspace / submitted["data"]["submission"]["archive"]
        manifest = read(archive / "manifest.json")
        self.assertEqual(manifest["opportunity_family"], expected)
        self.assertEqual(manifest["rubric"], app["data"]["rubric"])
        self.assertEqual(manifest["submitted_files"], ["cv.md", "motivation.md"])
        self.assertIn("rubric.snapshot.json", manifest["support_files"])
        for filename, expected_sha in manifest["files"].items():
            self.assertEqual(sha(archive / filename), expected_sha)
        rubric = read(archive / "rubric.snapshot.json")
        self.assertEqual(rubric["family"], expected)
        self.assertEqual(sum(rubric["dimensions"].values()), 100)
        frozen = (archive / "motivation.md").read_bytes()
        (directory / "motivation.md").write_text("Working copy edited after the fictional submission.\n")
        self.assertEqual((archive / "motivation.md").read_bytes(), frozen)
        interview = self.cli("interview", app["id"])
        self.assertEqual(interview["basis"], "submitted_archive")
        self.assertEqual(interview["opportunity_family"], expected)
        self.assertIn(record["data"]["title"], Path(interview["path"]).read_text())
        return app, directory, archive

    def test_school_complete_application_without_doctoral_proposal(self):
        self.lifecycle("summer_school", "school")

    def test_internship_complete_application_with_frozen_research_context(self):
        self.lifecycle("research_internship", "internship")

    def test_every_school_type_uses_training_rubric_and_provisional_documents(self):
        for kind in ("summer_school", "winter_school", "research_school", "training_school", "field_school", "short_course"):
            with self.subTest(kind=kind):
                app, _ = self.application(kind)
                self.assertEqual(app["data"]["opportunity_family"], "school")
                self.assertEqual(app["data"]["rubric"]["id"], "school")
                self.assertNotIn("proposal.md", app["data"]["documents"])
                self.assertEqual(self.cli("application", "verify", app["id"], code=1)["state"], "fail")

    def test_changed_profile_blocks_submitting_drafted_school_even_with_allow_unknown(self):
        app, _ = self.application()
        self.prepare(app)
        self.drafted(app)
        self.profile["research"]["topics"].append("material culture")
        self.save_profile()
        checks = self.cli("application", "verify", app["id"], code=1)["checks"]
        self.assertEqual(next(check for check in checks if check["name"] == "source_currency")["state"], "fail")
        self.submit(app, code=2)

    def test_changed_annotations_block_submitting_drafted_internship(self):
        app, record = self.application("research_internship")
        self.prepare(app)
        self.drafted(app)
        self.annotation["values"]["requirements"]["reviewed"] = False
        write(self.annotation_file, self.annotation)
        self.cli("opportunity", "annotate", record["id"], "--file", str(self.annotation_file))
        self.submit(app, code=2)
        self.assertEqual(self.cli("application", "show", app["id"])["status"], "drafted")

    def test_changed_posting_blocks_submitting_drafted_school(self):
        app, _ = self.application()
        self.prepare(app)
        self.drafted(app)
        self.source_file.write_text(self.source_file.read_text().replace("no degree or publication prerequisite", "a prior publication is now required"))
        self.cli("opportunity", "import", "--file", str(self.source_file), "--url", self.source_url, "--mode", "html")
        self.submit(app, code=2)

    def test_changed_rubric_snapshot_invalidates_otherwise_reviewed_school_packet(self):
        app, _ = self.application()
        directory = self.prepare(app)
        rubric = read(directory / "rubric.snapshot.json")
        rubric["family"] = "phd"
        write(directory / "rubric.snapshot.json", rubric)
        checks = self.cli("application", "verify", app["id"], code=1)["checks"]
        self.assertEqual(next(check for check in checks if check["name"] == "opportunity_mode")["state"], "fail")
        self.cli("application", "status", app["id"], "drafted", "--note", "Synthetic attempt", "--allow-unknown", code=2)

    def test_revoked_review_blocks_submitting_drafted_school(self):
        app, _ = self.application()
        directory = self.prepare(app)
        self.drafted(app)
        review = read(directory / "review.json")
        review["verdict"] = "revise"
        write(directory / "review.json", review)
        self.submit(app, code=2)

    def test_reviewed_documents_do_not_imply_reviewed_school_eligibility(self):
        app, _ = self.application(reviewed=False)
        self.prepare(app)
        verified = self.cli("application", "verify", app["id"], code=1)
        self.assertEqual(verified["state"], "needs_review")
        self.cli("application", "status", app["id"], "drafted", "--note", "Missing eligibility review", code=2)

    def test_explicit_school_project_documents_are_optional_and_still_unfinished(self):
        app, _ = self.application(documents=["cv", "motivation", "proposal", "research_statement", "statement_of_purpose", "supervisor_email"])
        self.assertIn("proposal.md", app["data"]["documents"])
        self.assertEqual(self.cli("application", "verify", app["id"], code=1)["state"], "fail")
        directory = self.workspace / app["data"]["directory"]
        for kind in ("proposal", "research_statement", "statement_of_purpose", "supervisor_email"):
            self.assertNotIn("Doctoral direction", (directory / (kind + ".md")).read_text())
            self.assertNotIn("doctoral study", (directory / (kind + ".md")).read_text())

    def test_tampered_submitted_rubric_cannot_be_used_for_interview_preparation(self):
        app, _, archive = self.lifecycle("winter_school", "school")
        (self.workspace / app["data"]["directory"] / "interview.md").unlink()
        (archive / "rubric.snapshot.json").write_text('{"family":"phd"}\n')
        self.cli("interview", app["id"], code=2)
        self.assertFalse((self.workspace / app["data"]["directory"] / "interview.md").exists())

    def test_legacy_doctoral_packet_without_mode_metadata_remains_usable(self):
        app, _ = self.application("project", documents=["cv", "motivation"])
        directory = self.prepare(app)
        legacy = dict(app["data"])
        for key in ("opportunity_family", "opportunity_type", "rubric", "rubric_sha256", "deadlines"):
            legacy.pop(key)
        with sqlite3.connect(self.workspace / "phd-search.sqlite3") as database:
            database.execute("UPDATE applications SET data=? WHERE id=?", (json.dumps(legacy), app["id"]))
        (directory / "rubric.snapshot.json").unlink()
        review = read(directory / "review.json")
        review.pop("opportunity_family")
        review.pop("rubric_sha256")
        write(directory / "review.json", review)
        self.assertEqual(self.cli("application", "verify", app["id"])["state"], "pass")
        self.drafted(app)
        submitted = self.submit(app)
        archive = self.workspace / submitted["data"]["submission"]["archive"]
        self.assertNotIn("rubric.snapshot.json", read(archive / "manifest.json")["files"])
        self.assertEqual(self.cli("interview", app["id"])["opportunity_family"], "phd")


if __name__ == "__main__":
    unittest.main()
