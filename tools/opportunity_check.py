#!/usr/bin/env python3
"""Synthetic public-CLI checks for research internships, schools and intake identity.

No package imports, existing test helpers, real portals, model calls or PDF tools
are used. Workspaces and command logs are retained under a new temporary folder.
The author also implemented discovery/workflow code; these checks independently
exercise eligibility, storage, exports and application boundaries written by
other contributors, not author-independent validation of the entire product.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes() -> dict:
    paths = [*ROOT.glob("phd_search/**/*.py"), *ROOT.glob("research_roost/**/*.py"), ROOT / "roost", ROOT / "pyproject.toml"]
    return {str(path.relative_to(ROOT)): sha(path) for path in paths if path.is_file()}


class Check:
    def __init__(self):
        self.base = Path(tempfile.mkdtemp(prefix="research-roost-opportunity-check-"))
        self.results = []
        self.commands = []
        self.counter = 0
        self.year = datetime.now(timezone.utc).year + 2
        self.future = f"{self.year}-12-20"
        self.past = "2001-01-01"
        self.before = source_hashes()

    def check(self, name: str, passed: bool, detail=None) -> None:
        self.results.append({"name": name, "state": "PASS" if passed else "FAIL", "detail": detail})

    def cli(self, workspace: Path, *args: str, expected=0) -> dict:
        launcher = [sys.executable, "-m", "research_roost"] if os.name == "nt" else [str(ROOT / "roost")]
        command = [*launcher, "--workspace", str(workspace), *map(str, args)]
        run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=40)
        try:
            payload = json.loads(run.stdout)
        except json.JSONDecodeError:
            payload = {"raw_stdout": run.stdout}
        entry = {"command": command, "exit_code": run.returncode, "stdout": payload, "stderr": run.stderr}
        self.commands.append(entry)
        expected_codes = {expected} if isinstance(expected, int) else set(expected)
        if run.returncode not in expected_codes:
            raise AssertionError(json.dumps(entry, ensure_ascii=False))
        return {"code": run.returncode, "data": payload}

    def workspace(self, name: str, *, education=None, preferences=None) -> Path:
        workspace = self.base / name
        self.cli(workspace, "init")
        candidate = read(workspace / "profile.json")
        candidate["identity"].update(name="Synthetic Researcher", email="fixture@example.invalid")
        candidate["research"].update(topics=["oral history"], methods=["archival transcription"])
        candidate["facts"] = [{"id": "transcription", "claim": "I transcribed one oral-history interview.",
                               "confirmed": True, "source": "Synthetic candidate supplied for this local CLI check"}]
        if education is not None:
            candidate["education"] = education
        candidate["preferences"].update(preferences or {})
        self.import_profile(workspace, candidate)
        return workspace

    def import_profile(self, workspace: Path, candidate: dict) -> None:
        self.counter += 1
        source = self.base / "inputs" / f"profile-{self.counter}.json"
        write(source, candidate)
        self.cli(workspace, "profile", "import", "--file", str(source))

    def opportunity(self, workspace: Path, kind: str, *, extra=None, title=None, url=None, edition=None) -> dict:
        self.counter += 1
        title = title or f"Synthetic {kind} {self.counter}"
        values = {"opportunity_type": kind, "application_status": "open", "deadline": self.future,
                  "requirements": {"reviewed": True}, **(extra or {})}
        quotes = {key: key + ": " + json.dumps(value, sort_keys=True, ensure_ascii=False) for key, value in values.items()}
        source = self.base / "inputs" / f"posting-{self.counter}.html"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("<!doctype html><html><body><h1>" + html.escape(title) + "</h1>"
                          + "<p>Submit a motivation statement.</p>"
                          + "".join("<p>" + html.escape(quote) + "</p>" for quote in quotes.values())
                          + "</body></html>", encoding="utf-8")
        args = ["opportunity", "import", "--file", str(source), "--url", url or f"https://fixtures.invalid/opportunity/{self.counter}", "--mode", "html"]
        if edition:
            args.extend(["--edition", edition])
        result = self.cli(workspace, *args)["data"]
        identifier = result["id"]
        record = self.cli(workspace, "opportunity", "show", identifier)["data"]
        annotations = {"values": values, "evidence": {
            key: {"quote": quote, "evidence_sha256": record["snapshot"]["sha256"]} for key, quote in quotes.items()}}
        annotation_path = self.base / "inputs" / f"annotations-{self.counter}.json"
        write(annotation_path, annotations)
        self.cli(workspace, "opportunity", "annotate", identifier, "--file", str(annotation_path))
        return {"id": identifier, "source": source, "title": title, "annotations": annotations,
                "annotation_path": annotation_path, "url": url or f"https://fixtures.invalid/opportunity/{self.counter}"}

    def screen(self, workspace: Path, record: dict) -> dict:
        return self.cli(workspace, "screen", record["id"])["data"]

    def assessment(self, workspace: Path, record: dict) -> dict:
        result = self.cli(workspace, "assessment", "packet", record["id"])["data"]
        path = Path(result["assessment"])
        packet = read(path)
        packet["assessor"] = "Synthetic public-CLI boundary assessor; no scientific-quality claim"
        for entry in packet["dimensions"].values():
            entry.update(score=3, reason="Synthetic comparison of the explicitly supplied research topic.",
                         posting_quotes=["Submit a motivation statement."], profile_refs=["/research/topics/0"])
        write(path, packet)
        self.cli(workspace, "assessment", "import", record["id"], "--file", str(path))
        return {"path": path, "packet": packet}

    def level(self, level: str, *, status="enrolled", end=None) -> dict:
        result = {"level": level, "degree": f"Synthetic {level} degree", "institution": "Fixture Institute",
                  "enrollment": {"status": status, "confirmed": True, "source": "Synthetic enrollment letter"}}
        if status == "completed":
            result["awarded_on"] = "2024-05-15"
        else:
            result["status"] = "in_progress"
            result["enrollment"]["start_date"] = "2025-09-01"
        if end:
            result["enrollment"]["end_date"] = end
        return result

    @staticmethod
    def full_school_funding() -> dict:
        return {"status": "fully_funded", "tuition_covered": False,
                "components": {key: {"coverage": "not_applicable" if key == "tuition" else "covered"}
                               for key in ("tuition", "registration", "living", "accommodation", "travel")}}

    def enrolled_doctorate_exclusion(self):
        workspace = self.workspace("doctorate-exclusion", education=[self.level("master", status="completed"), self.level("doctorate")])
        record = self.opportunity(workspace, "research_internship", extra={"requirements": {
            "reviewed": True, "enrollment": {"required": True, "allowed_levels": ["master"], "excluded_levels": ["doctorate"]}}})
        result = self.screen(workspace, record)
        self.check("current_doctorate_excludes_despite_older_master", result["verdict"] == "fail", result)

    def enrollment_through_end(self):
        workspace = self.workspace("enrollment-end", education=[self.level("master", end=f"{self.year}-06-30")])
        record = self.opportunity(workspace, "research_internship", extra={
            "start_date": f"{self.year}-06-01", "end_date": f"{self.year}-08-31",
            "requirements": {"reviewed": True, "enrollment": {"required": True, "through_end": True, "allowed_levels": ["master"]}}})
        result = self.screen(workspace, record)
        self.check("enrollment_ending_before_placement_is_fail", result["verdict"] == "fail", result)
        candidate = read(workspace / "profile.json")
        candidate["education"][0]["enrollment"].pop("end_date")
        self.import_profile(workspace, candidate)
        result = self.screen(workspace, record)
        self.check("missing_enrollment_end_is_unknown_not_pass", result["verdict"] == "unknown", result)

    def school_funding(self):
        workspace = self.workspace("school-funding", preferences={"require_full_funding": True})
        waived = self.opportunity(workspace, "winter_school", extra={"funding": {
            "status": "fully_funded", "components": {"tuition": {"coverage": "not_applicable"}, "registration": {"coverage": "covered"}}}})
        result = self.screen(workspace, waived)
        self.check("fee_waiver_alone_never_full_support_pass", result["verdict"] != "pass", result)
        complete = self.opportunity(workspace, "summer_school", extra={"funding": self.full_school_funding()})
        result = self.screen(workspace, complete)
        self.check("tuition_not_applicable_plus_full_relevant_support_passes", result["verdict"] == "pass", result)

    def availability_and_permissions(self):
        workspace = self.workspace("availability-permissions")
        record = self.opportunity(workspace, "research_internship", extra={
            "country": "GB", "start_date": f"{self.year}-06-01", "end_date": f"{self.year}-08-31",
            "requirements": {"reviewed": True, "work_authorization_required": True,
                             "home_approval_required": True, "enrollment": {"return_to_study": True}}})
        result = self.screen(workspace, record)
        self.check("unknown_permissions_and_return_to_study_do_not_pass", result["verdict"] == "unknown", result)
        candidate = read(workspace / "profile.json")
        evidence = {"confirmed": True, "source": "Synthetic dated permission and study-plan evidence"}
        candidate["preferences"].update(
            work_authorization={**evidence, "value": True, "country": "GB", "valid_until": self.future},
            home_approval={**evidence, "value": True}, return_to_study={**evidence, "value": True},
            availability=[{**evidence, "start_date": f"{self.year}-06-01", "end_date": f"{self.year}-08-31"}])
        self.import_profile(workspace, candidate)
        result = self.screen(workspace, record)
        self.check("confirmed_permissions_and_full_availability_pass", result["verdict"] == "pass", result)
        candidate["preferences"]["availability"][0]["start_date"] = f"{self.year}-07-01"
        self.import_profile(workspace, candidate)
        result = self.screen(workspace, record)
        self.check("partial_availability_does_not_satisfy_whole_placement", result["verdict"] == "fail", result)
        candidate["preferences"]["availability"][0]["start_date"] = f"{self.year}-06-01"
        candidate["preferences"]["work_authorization"]["value"] = False
        self.import_profile(workspace, candidate)
        result = self.screen(workspace, record)
        self.check("confirmed_missing_required_work_permission_fails", result["verdict"] == "fail", result)

    def distinct_deadlines(self):
        workspace = self.workspace("distinct-deadlines", preferences={"require_full_funding": True})
        record = self.opportunity(workspace, "research_school", extra={"funding": self.full_school_funding(), "deadlines": [
            {"id": "apply", "kind": "application", "deadline": self.future, "required": True},
            {"id": "travel-grant", "kind": "funding", "label": "Travel grant application", "deadline": self.past, "required": False}]})
        result = self.screen(workspace, record)
        self.check("required_funding_expiry_not_hidden_by_later_application", result["verdict"] == "fail", result)
        candidate = read(workspace / "profile.json")
        candidate["preferences"]["require_full_funding"] = False
        self.import_profile(workspace, candidate)
        result = self.screen(workspace, record)
        self.check("optional_old_funding_does_not_expire_open_admission", result["verdict"] == "pass", result)

    def upcoming_call(self):
        workspace = self.workspace("upcoming-call")
        record = self.opportunity(workspace, "field_school", extra={"application_status": "upcoming"})
        result = self.screen(workspace, record)
        self.check("upcoming_call_with_future_date_is_not_open_pass", result["verdict"] != "pass", result)

    def calendar_precision(self):
        workspace = self.workspace("calendar-precision")
        self.opportunity(workspace, "winter_school", extra={"deadline": None, "deadlines": [
            {"id": "unknown-zone", "kind": "application", "deadline": f"{self.year}-12-01 12:00"},
            {"id": "utc-cutoff", "kind": "funding", "label": "Travel grant", "deadline": f"{self.year}-11-20T12:00:00+03:00"},
            {"id": "date-only", "kind": "registration", "deadline": f"{self.year}-12-05"}]})
        path = self.base / "calendar.ics"
        result = self.cli(workspace, "export", "calendar", "--out", str(path))["data"]
        text = path.read_text(encoding="utf-8").replace("\n ", "")
        self.check("unknown_timezone_cutoff_is_skipped", result["skipped_unknown_deadlines"] == 1, result)
        self.check("calendar_contains_two_known_named_cutoffs", text.count("BEGIN:VEVENT") == 2, text)
        self.check("offset_time_exported_as_exact_utc", f"DTSTART:{self.year}1120T090000Z" in text, text)
        self.check("date_only_remains_all_day", f"DTSTART;VALUE=DATE:{self.year}1205" in text, text)
        self.check("unknown_zone_never_fabricated_as_midnight_or_noon_utc", f"{self.year}1201T" not in text, text)

    def annual_editions(self):
        workspace = self.workspace("annual-editions")
        url = "https://fixtures.invalid/annual-school"
        first = self.opportunity(workspace, "summer_school", url=url, edition=str(self.year))
        second = self.opportunity(workspace, "summer_school", url=url, edition=str(self.year + 1))
        self.check("same_url_distinct_editions_have_distinct_ids", first["id"] != second["id"])
        args = ["opportunity", "import", "--file", str(first["source"]), "--url", url, "--mode", "html", "--edition", str(self.year)]
        repeated = self.cli(workspace, *args)["data"]
        self.check("same_edition_repeat_deduplicates", repeated["id"] == first["id"])
        for record in (first, second):
            observed = self.cli(workspace, "opportunity", "show", record["id"])["data"]
            self.check("edition_preserves_original_url:" + record["id"], observed["url"] == url)
        ambiguous = self.cli(workspace, "opportunity", "show", url, expected=2)
        self.check("ambiguous_shared_url_requires_id", ambiguous["code"] == 2)
        listed = self.cli(workspace, "opportunity", "list")["data"]
        self.check("both_editions_remain_in_list", len(listed) == 2, listed)

    def mixed_families(self):
        workspace = self.workspace("mixed-families")
        records = {family: self.opportunity(workspace, kind, title="SYNTHETIC-" + family.upper()) for family, kind in
                   (("phd", "project"), ("internship", "research_internship"), ("school", "summer_school"))}
        expected_dimensions = {
            "phd": {"research_fit", "methods", "supervisor_fit", "preparedness", "funding", "environment"},
            "internship": {"project_fit", "methods", "mentor_fit", "preparedness", "funding", "environment"},
            "school": {"learning_fit", "prerequisites", "programme_fit", "funding", "practical_fit"},
        }
        groups = []
        assessments = {}
        for family, record in records.items():
            assessed = self.assessment(workspace, record)
            assessments[family] = assessed
            packet = assessed["packet"]
            self.check("family_rubric_identity:" + family, packet["rubric"]["id"] == family, packet["rubric"])
            self.check("family_rubric_dimensions:" + family, set(packet["dimensions"]) == expected_dimensions[family])
            listed = self.cli(workspace, "opportunity", "list", "--family", family)["data"]
            self.check("opportunity_list_filter:" + family, [row["id"] for row in listed] == [record["id"]], listed)
            ranked = self.cli(workspace, "rank", "--family", family)["data"]
            self.check("rank_filter_and_complete_assessment:" + family,
                       len(ranked) == 1 and ranked[0]["id"] == record["id"] and ranked[0]["coverage"] == 100, ranked)
            groups.append(ranked[0]["comparison_group"])
            output = self.base / ("report-" + family + ".html")
            report = self.cli(workspace, "report", "--family", family, "--out", str(output))["data"]
            markup = output.read_text(encoding="utf-8")
            self.check("report_count_filter:" + family, report["opportunities"] == 1 and report["family"] == family, report)
            self.check("report_has_only_selected_family_title:" + family,
                       record["title"] in markup and all(other["title"] not in markup for kind, other in records.items() if kind != family))
        self.check("cross_family_scores_have_distinct_comparison_groups", len(set(groups)) == 3, groups)
        record = records["school"]
        old_packet = {"assessment": str(assessments["school"]["path"])}
        annotations = copy.deepcopy(record["annotations"])
        annotations["values"]["requirements"]["reviewed"] = False
        write(record["annotation_path"], annotations)
        self.cli(workspace, "opportunity", "annotate", record["id"], "--file", str(record["annotation_path"]))
        ranked = self.cli(workspace, "rank", "--family", "school")["data"]
        self.check("annotation_change_invalidates_previous_assessment", ranked[0]["assessment_state"] == "stale", ranked)
        rejected = self.cli(workspace, "assessment", "import", record["id"], "--file", old_packet["assessment"], expected=2)
        self.check("old_packet_cannot_import_after_annotation_change", rejected["code"] == 2)
        candidate = read(workspace / "profile.json")
        candidate["research"]["topics"].append("memory studies")
        self.import_profile(workspace, candidate)
        ranked = self.cli(workspace, "rank", "--family", "internship")["data"]
        self.check("profile_change_invalidates_other_family_assessment", ranked[0]["assessment_state"] == "stale", ranked)

    def stale_annotation_after_source_refresh(self):
        workspace = self.workspace("source-refresh")
        record = self.opportunity(workspace, "winter_school")
        with record["source"].open("a", encoding="utf-8") as handle:
            handle.write("<p>Edition requirements revised after this local observation.</p>")
        self.cli(workspace, "opportunity", "import", "--file", str(record["source"]), "--url", record["url"], "--mode", "html")
        rejected = self.cli(workspace, "opportunity", "annotate", record["id"], "--file", str(record["annotation_path"]), expected=2)
        self.check("old_snapshot_annotation_rejected_after_source_refresh", rejected["code"] == 2)
        result = self.screen(workspace, record)
        self.check("old_reviewed_requirements_do_not_survive_new_source", result["verdict"] != "pass", result)

    def application_review_boundaries(self):
        workspace = self.workspace("review-boundaries")
        record = self.opportunity(workspace, "field_school")
        app = self.cli(workspace, "application", "create", record["id"], "--documents", "motivation")["data"]
        identifier = app["id"]
        directory = workspace / app["data"]["directory"]
        self.check("school_packet_binds_correct_family", app["data"]["opportunity_family"] == "school", app["data"]["rubric"])
        self.check("school_packet_does_not_force_phd_proposal", app["data"]["documents"] == ["motivation.md"])
        initial = self.cli(workspace, "application", "verify", identifier, expected=1)
        self.check("unfinished_school_application_fails", initial["code"] == 1)
        fact = read(workspace / "profile.json")["facts"][0]["claim"]
        (directory / "motivation.md").write_text("# Motivation\n\n" + fact + "\n\nI propose to develop my transcription practice during this school.\n", encoding="utf-8")
        claims = read(directory / "claims.json")
        claims.update(coverage_reviewed=True, claims=[{"file": "motivation.md", "text": fact, "profile_refs": ["/facts/0"]}])
        write(directory / "claims.json", claims)
        requirements = read(directory / "requirements.json")
        requirements["source_quote"] = "Submit a motivation statement."
        write(directory / "requirements.json", requirements)
        missing = self.cli(workspace, "application", "status", identifier, "drafted", "--allow-unknown", "--note", "Synthetic local boundary check", expected=2)
        self.check("allow_unknown_does_not_bypass_pending_review", missing["code"] == 2)
        review = read(directory / "review.json")
        review.update(reviewer="Synthetic critical pass; not expert scientific review", verdict="approved",
                      claims_semantically_checked=True, requirements_checked=True, source_integrity_checked=True,
                      document_hashes={"motivation.md": sha(directory / "motivation.md")},
                      support_hashes={name: sha(directory / name) for name in ("claims.json", "requirements.json")})
        write(directory / "review.json", review)
        verified = self.cli(workspace, "application", "verify", identifier, expected=(0, 1))
        self.check("completed_synthetic_school_packet_passes_document_checks", verified["code"] == 0, verified["data"])
        self.cli(workspace, "application", "status", identifier, "drafted", "--allow-unknown", "--note", "Synthetic local reviewed packet")
        review["verdict"] = "pending"
        write(directory / "review.json", review)
        blocked = self.cli(workspace, "application", "status", identifier, "submitted", "--allow-unknown", "--note", "Synthetic attempt must fail; nothing submitted externally", expected=2)
        self.check("revoked_review_cannot_submit_even_after_drafted", blocked["code"] == 2)
        observed = self.cli(workspace, "application", "show", identifier)["data"]
        self.check("failed_submission_does_not_create_submission_archive", observed["status"] == "drafted" and observed["data"]["submission"] is None)
        review["verdict"] = "approved"
        write(directory / "review.json", review)
        with (directory / "motivation.md").open("a", encoding="utf-8") as handle:
            handle.write("\nAn unreviewed final edit.\n")
        changed = self.cli(workspace, "application", "verify", identifier, expected=1)
        self.check("document_edit_invalidates_old_review_hash", changed["code"] == 1)

    def run(self) -> dict:
        started = time.monotonic()
        scenarios = [self.enrolled_doctorate_exclusion, self.enrollment_through_end, self.school_funding, self.availability_and_permissions,
                     self.distinct_deadlines, self.upcoming_call, self.calendar_precision, self.annual_editions,
                     self.mixed_families, self.stale_annotation_after_source_refresh, self.application_review_boundaries]
        for scenario in scenarios:
            try:
                scenario()
            except Exception as exc:
                self.check(scenario.__name__ + ":completed", False, str(exc))
        after = source_hashes()
        changed = [name for name in self.before.keys() | after.keys() if self.before.get(name) != after.get(name)]
        self.check("production_sources_stable_during_run", not changed, changed)
        passed = sum(item["state"] == "PASS" for item in self.results)
        result = {"tool": "opportunity_check", "state": "PASS" if passed == len(self.results) else "FAIL",
                  "passed": passed, "failed": len(self.results) - passed, "checks": len(self.results),
                  "cli_commands": len(self.commands), "scenarios": len(scenarios), "seconds": round(time.monotonic() - started, 3),
                  "artifacts": str(self.base), "network": "none; file imports only; no external messages or submissions",
                  "review_scope": "New fixtures and public CLI only. Eligibility/storage/export/application code by other contributors; discovery/workflow author is this reviewer. No claim of whole-product author independence, PDF validation or scientific quality.",
                  "source_sha256_before": self.before, "source_sha256_after": after,
                  "results": self.results}
        write(self.base / "commands.json", {"commands": self.commands})
        write(self.base / "results.json", result)
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="Also write the complete JSON result to this path")
    args = parser.parse_args()
    result = Check().run()
    if args.out:
        write(args.out, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["state"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
