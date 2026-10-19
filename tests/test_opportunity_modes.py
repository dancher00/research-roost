from __future__ import annotations

import copy
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from phd_search import assessment, profile
from phd_search.cli import initialise
from phd_search.core import Error
from phd_search.evidence import ingest_file
from phd_search.extract import parse_deadline
from phd_search.opportunities import (
    deadline_entries,
    family,
    normalize_deadlines,
    primary_application,
    rubric_for,
    validate_opportunity_fields,
)
from phd_search.store import Store

NOW = datetime(2098, 1, 1, 12, tzinfo=timezone.utc)
QUOTE = "Research training includes source analysis and a mentored research project."


class OpportunityModesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "workspace"
        initialise(self.root)
        self.store = Store(self.root)
        self.addCleanup(self.store.db.close)
        self.candidate = profile.load(self.root)
        self.candidate["facts"] = [{"id": "archive", "claim": "I analysed archival sources.", "source": "confirmed research record", "confirmed": True}]
        source = self.base / "source.html"
        source.write_text("<html><h1>Research opportunity</h1><p>" + QUOTE + "</p><p>Deadline: 2099-12-31</p></html>")
        self.record = ingest_file(self.store, source, "https://institution.example/research", mode="html")

    def annotate(self, **values):
        sha = self.record["snapshot"]["sha256"]
        self.record = assessment.validate_annotations(self.store, self.record["id"], {
            "values": values, "evidence": {key: {"quote": QUOTE, "evidence_sha256": sha} for key in values}})
        return self.record

    def gates(self, **values):
        self.annotate(requirements={"reviewed": True}, **values)
        return {gate["name"]: gate for gate in assessment.screen(self.record, self.candidate, at=NOW)["gates"]}

    def enrollment(self, level="doctorate", end="2100-01-01", confirmed=True):
        self.candidate["education"] = [{"level": level, "enrollment": {
            "status": "enrolled", "start_date": "2097-09-01", "end_date": end,
            "confirmed": confirmed, "source": "registrar enrollment certificate"}}]

    def screening(self, requirements, **values):
        self.annotate(requirements={"reviewed": True, **requirements}, opportunity_type="research_internship", **values)
        return {gate["name"]: gate for gate in assessment.screen(self.record, self.candidate, at=NOW)["gates"]}

    def test_old_profile_without_optional_fields_remains_valid(self):
        for key in ("availability", "duration_days", "return_to_study", "work_authorization", "home_approval"):
            self.candidate["preferences"].pop(key, None)
        self.assertEqual(profile.validate(self.candidate), [])
        self.assertEqual(family({}), "phd")
        self.assertEqual(rubric_for({})["dimensions"], assessment.DIMENSIONS)

    def test_school_and_internship_have_separate_rubrics(self):
        school = self.annotate(opportunity_type="winter_school")
        packet = assessment.assessment_template(school, self.candidate)
        self.assertEqual(packet["rubric"], {"id": "school", "version": 1, "family": "school"})
        self.assertIn("learning_fit", packet["dimensions"])
        self.assertNotIn("supervisor_fit", packet["dimensions"])
        self.assertEqual(sum(rubric_for(school["annotations"]["values"])["dimensions"].values()), 100)
        internship = self.annotate(opportunity_type="research_internship")
        packet = assessment.assessment_template(internship, self.candidate)
        self.assertIn("project_fit", packet["dimensions"])
        self.assertIn("mentor_fit", packet["dimensions"])

    def test_school_assessment_requires_candidate_learning_evidence(self):
        self.annotate(opportunity_type="summer_school")
        packet = assessment.assessment_template(self.record, self.candidate)
        packet["assessor"] = "Test reviewer"
        packet["dimensions"]["learning_fit"].update(score=4, reason="Supports a confirmed research task", posting_quotes=[QUOTE])
        with self.assertRaisesRegex(Error, "profile evidence"):
            assessment.save_assessment(self.store, self.record["id"], self.candidate, packet)
        packet["dimensions"]["learning_fit"]["profile_refs"] = ["/facts/0"]
        result = assessment.save_assessment(self.store, self.record["id"], self.candidate, packet)
        self.assertEqual(result["coverage"], 30)
        self.assertEqual(result["score_interval"], [24, 94])
        self.assertEqual(result["comparison_group"], "school:v1")

    def test_legacy_assessment_without_rubric_remains_valid_for_phd_only(self):
        packet = assessment.assessment_template(self.record, self.candidate)
        packet.pop("rubric")
        packet["assessor"] = "Legacy reviewer"
        self.assertEqual(assessment.save_assessment(self.store, self.record["id"], self.candidate, packet)["assessment_state"], "current")
        self.annotate(opportunity_type="short_course")
        packet = assessment.assessment_template(self.record, self.candidate)
        packet.pop("rubric")
        packet["assessor"] = "Incorrect legacy reviewer"
        with self.assertRaisesRegex(Error, "rubric"):
            assessment.save_assessment(self.store, self.record["id"], self.candidate, packet)

    def test_changed_family_invalidates_old_assessment(self):
        packet = assessment.assessment_template(self.record, self.candidate)
        packet["assessor"] = "Doctoral reviewer"
        assessment.save_assessment(self.store, self.record["id"], self.candidate, packet)
        self.annotate(opportunity_type="research_school")
        result = assessment.ranking(self.record, self.candidate)
        self.assertEqual(result["assessment_state"], "stale")
        self.assertEqual(result["coverage"], 0)

    def test_current_phd_is_excluded_despite_awarded_masters(self):
        self.enrollment()
        self.candidate["education"].append({"level": "master", "awarded_on": "2097-06-01"})
        gates = self.screening({"degree": "master", "enrollment": {"excluded_levels": ["doctorate"]}})
        self.assertEqual(gates["degree"]["state"], "pass")
        self.assertEqual(gates["enrollment:excluded_levels"]["state"], "fail")

    def test_unconfirmed_enrollment_never_proves_eligibility(self):
        self.enrollment(confirmed=False)
        gates = self.screening({"enrollment": {"required": True, "allowed_levels": ["doctorate"]}})
        self.assertEqual(gates["enrollment:allowed_levels"]["state"], "unknown")

    def test_continuous_enrollment_cannot_end_before_placement(self):
        self.enrollment(end="2098-07-15")
        gates = self.screening({"enrollment": {"allowed_levels": ["doctorate"], "through_end": True}},
                               start_date="2098-07-01", end_date="2098-08-31")
        self.assertEqual(gates["enrollment:through_end"]["state"], "fail")

    def test_unknown_enrollment_end_does_not_prove_continuity(self):
        self.enrollment(end=None)
        gates = self.screening({"enrollment": {"through_end": True}}, start_date="2098-07-01", end_date="2098-08-31")
        self.assertEqual(gates["enrollment:through_end"]["state"], "unknown")

    def test_continuous_confirmed_enrollment_covers_full_placement(self):
        self.enrollment()
        gates = self.screening({"enrollment": {"allowed_levels": ["doctorate"], "through_end": True}},
                               start_date="2098-07-01", end_date="2098-08-31")
        self.assertEqual(gates["enrollment:through_end"]["state"], "pass")

    def test_return_to_study_requires_separate_confirmation(self):
        self.enrollment()
        req = {"enrollment": {"return_to_study": True}}
        self.assertEqual(self.screening(req)["return_to_study"]["state"], "unknown")
        self.candidate["preferences"]["return_to_study"] = {"value": False, "confirmed": True, "source": "candidate confirmed graduation"}
        self.assertEqual(self.screening(req)["return_to_study"]["state"], "fail")

    def test_authorization_is_not_inferred_from_citizenship(self):
        self.candidate["preferences"]["citizenships"] = ["DE"]
        req = {"work_authorization_required": True}
        self.assertEqual(self.screening(req, country="DE")["work_authorization"]["state"], "unknown")
        self.candidate["preferences"]["work_authorization"] = {"value": True, "country": "FR", "confirmed": True, "source": "authorization document"}
        self.assertEqual(self.screening(req, country="DE")["work_authorization"]["state"], "unknown")
        self.candidate["preferences"]["work_authorization"]["country"] = "DE"
        self.assertEqual(self.screening(req, country="DE")["work_authorization"]["state"], "pass")

    def test_authorization_must_last_through_end(self):
        self.candidate["preferences"]["work_authorization"] = {"value": True, "country": "DE", "valid_until": "2098-07-01", "confirmed": True, "source": "permit"}
        gates = self.screening({"work_authorization_required": True}, country="DE", start_date="2098-06-01", end_date="2098-08-31")
        self.assertEqual(gates["work_authorization"]["state"], "fail")

    def test_availability_checks_complete_interval_and_adjacent_windows(self):
        self.candidate["preferences"]["availability"] = [
            {"start_date": "2098-07-01", "end_date": "2098-07-31", "confirmed": True, "source": "confirmed calendar"},
            {"start_date": "2098-08-01", "end_date": "2098-08-31", "confirmed": True, "source": "confirmed calendar"}]
        self.assertEqual(self.screening({}, start_date="2098-07-15", end_date="2098-08-15")["availability"]["state"], "pass")
        self.assertEqual(self.screening({}, start_date="2098-07-15", end_date="2098-09-01")["availability"]["state"], "fail")

    def test_duration_limits_do_not_convert_months_to_days(self):
        self.assertEqual(self.screening({"duration_days": {"min": 60}}, duration_months=2)["duration"]["state"], "unknown")
        self.assertEqual(self.screening({"duration_days": {"min": 60}}, start_date="2098-07-01", end_date="2098-07-31")["duration"]["state"], "fail")
        self.candidate["preferences"]["duration_days"] = {"max": 14}
        self.assertEqual(self.screening({}, duration_days=21)["duration"]["state"], "fail")

    def test_scholarship_deadline_is_separate_from_open_admission(self):
        deadlines = [{"id": "admission", "kind": "application", "deadline": "2099-01-01"},
                     {"id": "scholarship", "kind": "funding", "deadline": "2097-12-01"}]
        self.candidate["preferences"]["require_full_funding"] = True
        gates = self.gates(opportunity_type="summer_school", deadlines=deadlines)
        self.assertEqual(gates["deadline"]["state"], "pass")
        self.assertEqual(gates["deadline:scholarship"]["state"], "fail")
        self.candidate["preferences"]["require_full_funding"] = False
        self.assertNotIn("deadline:scholarship", self.gates(opportunity_type="summer_school", deadlines=deadlines))

    def test_upcoming_school_is_not_ready_to_apply(self):
        gates = self.gates(opportunity_type="winter_school", application_status="upcoming")
        self.assertEqual(gates["application_status"]["state"], "unknown")
        self.assertEqual(self.gates(opportunity_type="winter_school", application_status="closed")["application_status"]["state"], "fail")

    def test_fee_waiver_is_not_full_funding(self):
        self.candidate["preferences"]["require_full_funding"] = True
        gates = self.gates(opportunity_type="summer_school", funding={"status": "fully_funded", "components": {"registration": {"coverage": "covered"}, "living": {"coverage": "not_covered"}}})
        self.assertEqual(gates["funding"]["state"], "fail")

    def test_explicit_sourced_non_applicable_tuition_is_supported(self):
        self.candidate["preferences"]["require_full_funding"] = True
        funding = {"status": "fully_funded", "components": {name: {"coverage": "not_applicable" if name in {"tuition", "registration"} else "covered"} for name in ("tuition", "registration", "living", "accommodation", "travel")}}
        self.assertEqual(self.gates(opportunity_type="research_internship", funding=funding)["funding"]["state"], "pass")
        unbound = copy.deepcopy(self.record)
        unbound["data"].update(unbound["annotations"]["values"])
        unbound["annotations"] = {}
        gates = {gate["name"]: gate for gate in assessment.screen(unbound, self.candidate, at=NOW)["gates"]}
        self.assertEqual(gates["funding"]["state"], "unknown")

    def test_all_not_applicable_costs_do_not_establish_support(self):
        self.candidate["preferences"]["require_full_funding"] = True
        funding = {"status": "fully_funded", "components": {name: {"coverage": "not_applicable"} for name in ("tuition", "registration", "living", "accommodation", "travel")}}
        self.assertEqual(self.gates(opportunity_type="summer_school", funding=funding)["funding"]["state"], "unknown")

    def test_old_phd_funding_contract_stays_valid(self):
        self.candidate["preferences"]["require_full_funding"] = True
        self.assertEqual(self.gates(funding={"status": "fully_funded", "tuition_covered": True})["funding"]["state"], "pass")

    def test_invalid_dates_components_and_deadline_ids_rejected(self):
        for values in ({"end_date": "not-a-date"}, {"start_date": "2099-02-01", "end_date": "2099-01-01"},
                       {"funding": {"status": "partial", "components": {"registration": {"coverage": "covered", "amount": -1}}}},
                       {"deadlines": [{"id": "x", "kind": "application", "deadline": "2099-01-01"}, {"id": "x", "kind": "funding", "deadline": "2098-01-01"}]},
                       {"requirements": {"enrollment": {"allowed_levels": ["anyone"]}}}):
            with self.subTest(values=values), self.assertRaises(Error):
                self.annotate(**values)

    def test_profile_confirmations_require_sources_and_dates(self):
        self.enrollment()
        self.candidate["education"][0]["enrollment"].pop("source")
        self.assertTrue(any("source" in error for error in profile.validate(self.candidate)))
        self.candidate["education"] = []
        self.candidate["preferences"]["availability"] = [{"start_date": "2099-03-01", "end_date": "2099-02-01", "confirmed": True, "source": "calendar"}]
        self.assertTrue(any("precede" in error for error in profile.validate(self.candidate)))

    def test_named_deadlines_preserve_timezone_precision(self):
        entries = deadline_entries({"deadline": parse_deadline("2099-12-31"), "deadlines": [{"kind": "application", "deadline": "2098-02-01T16:00:00+01:00"}, {"kind": "payment", "deadline": "2098-02-05", "required": False}]})
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["deadline"]["precision"], "time")
        self.assertEqual(entries[0]["deadline"]["value"], "2098-02-01T16:00:00+01:00")
        with self.assertRaises(Error):
            normalize_deadlines([{"kind": "application", "deadline": {"raw": "local clock", "value": "2098-02-01T16:00:00", "precision": "time"}}])

    def test_automatic_deadline_ids_survive_reordering(self):
        entries = [{"kind": "funding", "label": "Travel grant", "deadline": "2099-01-01"},
                   {"kind": "payment", "deadline": "2099-02-01"}]
        before = normalize_deadlines(entries)
        after = normalize_deadlines(list(reversed(entries)))
        self.assertEqual({entry["kind"]: entry["id"] for entry in before}, {entry["kind"]: entry["id"] for entry in after})

    def test_primary_application_is_stable_when_named_deadlines_reorder(self):
        entries = [{"id": "second-round", "kind": "application", "deadline": "2099-03-01"},
                   {"id": "first-round", "kind": "application", "deadline": "2099-01-01"}]
        before = primary_application({"deadlines": entries})
        after = primary_application({"deadlines": list(reversed(entries))})
        self.assertEqual(before, after)
        self.assertEqual(before["id"], "first-round")
        self.gates(deadlines=entries)
        original = assessment.screen(self.record, self.candidate, at=NOW)
        self.gates(deadlines=list(reversed(entries)))
        reordered = assessment.screen(self.record, self.candidate, at=NOW)
        self.assertEqual(original["deadline"], reordered["deadline"])

    def test_malformed_degree_or_other_requirement_cannot_remove_gates(self):
        invalid = [{"degree": []}, {"degree": ["master"]}, {"degree": {"level": "master"}},
                   {"other": ["Requires a valid visa"]},
                   {"other": [{"name": "visa", "verdict": [], "reason": "Unreviewed"}]},
                   {"languages": [{"name": "English", "cefr": []}]}]
        for requirements in invalid:
            with self.subTest(requirements=requirements), self.assertRaises(Error):
                self.annotate(requirements={"reviewed": True, **requirements})

    def test_permission_cannot_start_after_participation_begins(self):
        for field in ("work_authorization", "home_approval"):
            with self.subTest(field=field):
                self.candidate["preferences"][field] = {"value": True, "confirmed": True, "source": "dated institutional permission",
                                                       "country": "FI", "valid_from": "2098-07-01", "valid_until": "2098-08-31"}
                gates = self.screening({field + "_required": True}, country="FI", start_date="2098-06-01", end_date="2098-08-31")
                self.assertEqual(gates[field]["state"], "fail")
                self.candidate["preferences"][field]["valid_from"] = "2098-06-01"
                gates = self.screening({field + "_required": True}, country="FI", start_date="2098-06-01", end_date="2098-08-31")
                self.assertEqual(gates[field]["state"], "pass")

    def test_confirmed_future_doctoral_enrollment_overlaps_internship(self):
        self.enrollment(level="master")
        self.candidate["education"].append({"level": "doctorate", "enrollment": {
            "status": "enrolled", "start_date": "2098-05-01", "end_date": "2100-01-01",
            "confirmed": True, "source": "confirmed doctoral enrollment dates"}})
        gates = self.screening({"enrollment": {"allowed_levels": ["master"], "excluded_levels": ["doctorate"], "through_end": True}},
                               start_date="2098-06-01", end_date="2098-08-31")
        self.assertEqual(gates["enrollment:excluded_levels"]["state"], "fail")
        gates = self.screening({"enrollment": {"excluded_levels": ["doctorate"]}})
        self.assertEqual(gates["enrollment:excluded_levels"]["state"], "unknown")

    def test_permission_validity_bounds_are_validated(self):
        self.candidate["preferences"]["home_approval"] = {"value": True, "confirmed": True, "source": "permission",
                                                        "valid_from": "2098-09-01", "valid_until": "2098-08-01"}
        self.assertTrue(any("precede valid_from" in error for error in profile.validate(self.candidate)))

    def test_imported_identity_cannot_be_relabelled_by_annotation(self):
        source = self.base / "identity.html"
        source.write_text("<h1>Research school</h1><p>" + QUOTE + "</p>")
        self.record = ingest_file(self.store, source, "https://institution.example/school", mode="html", edition="2099", session="session-a")
        self.annotate(edition="2099", session_id="session-a")
        with self.assertRaisesRegex(Error, "--edition/--session"):
            self.annotate(edition="2100")
        with self.assertRaisesRegex(Error, "--edition/--session"):
            self.annotate(session_id="session-b")

    def test_unknown_fields_are_not_accepted_as_source_annotations(self):
        with self.assertRaisesRegex(Error, "Unknown annotated"):
            self.annotate(event_dates={"start": "2099-01-01"})
        self.assertTrue(validate_opportunity_fields({"mode": "travel"}))
        self.assertEqual(family({"opportunity_type": "field_school"}), "school")

    def test_rank_groups_families_instead_of_comparing_their_scores(self):
        self.annotate(opportunity_type="short_course")
        packet = assessment.assessment_template(self.record, self.candidate)
        packet["assessor"] = "School reviewer"
        for entry in packet["dimensions"].values():
            entry.update(score=5, reason="Synthetic complete support", posting_quotes=[QUOTE], profile_refs=["/facts/0"])
        assessment.save_assessment(self.store, self.record["id"], self.candidate, packet)
        source = self.base / "doctoral.html"
        source.write_text("<h1>Doctoral opportunity</h1><p>Deadline: 2099-12-31</p>")
        phd = ingest_file(self.store, source, "https://institution.example/doctoral", mode="html")
        rows = assessment.rank_all(self.store, self.candidate)
        self.assertEqual(rows[0]["id"], phd["id"])
        self.assertEqual(rows[1]["family"], "school")
        self.assertNotEqual(rows[0]["comparison_group"], rows[1]["comparison_group"])
