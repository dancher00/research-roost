from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from phd_search import assessment
from phd_search.core import Error
from phd_search.evidence import ingest_file
from phd_search.research import gaps_report, search_plan
from phd_search.store import Store


def candidate() -> dict:
    path = Path(__file__).resolve().parents[1] / "phd_search/resources/profile.example.json"
    return json.loads(path.read_text())


class DiscoveryModesTests(unittest.TestCase):
    def setUp(self):
        self.profile = candidate()

    def test_blank_profile_does_not_create_personal_queries_for_any_mode(self):
        for family in (None, "phd", "internship", "school", "all"):
            with self.subTest(family=family):
                result = search_plan(self.profile, family)
                self.assertEqual(result["state"], "profile_required")
                self.assertEqual(result["queries"], [])
                self.assertTrue(result["templates"])

    def test_legacy_empty_type_selection_keeps_doctoral_search(self):
        self.profile["research"]["topics"] = ["medieval translation"]
        result = search_plan(self.profile)
        self.assertEqual(result["families"], ["phd"])
        self.assertEqual(len(result["queries"]), 7)
        self.assertEqual({row["family"] for row in result["queries"]}, {"phd"})

    def test_confirmed_types_choose_each_family_once(self):
        self.profile["research"]["topics"] = ["oral history"]
        self.profile["preferences"]["opportunity_types"] = ["winter_school", "summer_school", "research_internship"]
        result = search_plan(self.profile)
        self.assertEqual(set(result["families"]), {"internship", "school"})
        rows = result["queries"]
        self.assertEqual(len([row for row in rows if row["family"] == "school"]), 5)
        self.assertEqual(len([row for row in rows if row["family"] == "internship"]), 5)
        self.assertNotIn("findaphd", {row["source"] for row in rows})

    def test_one_off_family_does_not_rewrite_profile_preferences(self):
        self.profile["research"]["topics"] = ["theatre practice"]
        self.profile["preferences"]["opportunity_types"] = ["doctoral_programme"]
        before = copy.deepcopy(self.profile)
        result = search_plan(self.profile, "school")
        self.assertEqual(result["families"], ["school"])
        self.assertEqual(self.profile, before)

    def test_all_mode_retains_separate_family_labels(self):
        self.profile["research"]["topics"] = ["epidemiology"]
        result = search_plan(self.profile, "all")
        self.assertEqual(set(result["families"]), {"phd", "internship", "school"})
        self.assertEqual({row["family"] for row in result["queries"]}, set(result["families"]))
        self.assertEqual(len(result["queries"]), 17)

    def test_humanities_and_practice_queries_include_actual_profile_and_no_invented_country(self):
        self.profile["research"]["topics"] = ["oral history", "performance practice"]
        for family in ("internship", "school"):
            with self.subTest(family=family):
                rows = search_plan(self.profile, family)["queries"]
                self.assertEqual({row["topic"] for row in rows}, set(self.profile["research"]["topics"]))
                self.assertTrue(all(row["country"] == "" for row in rows))
                for row in rows:
                    self.assertIn(row["topic"], row["query"])
                self.assertTrue(any('"fieldwork"' in row["query"] or '"field school"' in row["query"] for row in rows))

    def test_internship_queries_include_enrollment_and_funding_research(self):
        self.profile["research"]["keywords"] = ["robot learning"]
        rows = search_plan(self.profile, "internship")["queries"]
        self.assertTrue(any('"enrolled"' in row["query"] and '"return to study"' in row["query"] for row in rows))
        self.assertTrue(any(row["source"] == "funding" and '"paid"' in row["query"] for row in rows))
        self.assertTrue(any(row["source"] == "mentor" for row in rows))

    def test_school_queries_include_distinct_seasons_training_costs_and_cutoffs(self):
        self.profile["research"]["topics"] = ["archaeology"]
        rows = search_plan(self.profile, "school")["queries"]
        self.assertTrue(any('"summer school"' in row["query"] and '"winter school"' in row["query"] for row in rows))
        self.assertTrue(any('"travel grant"' in row["query"] and '"accommodation"' in row["query"] for row in rows))
        self.assertTrue(any('"registration deadline"' in row["query"] and '"scholarship deadline"' in row["query"] for row in rows))

    def test_explicit_countries_remain_separate_query_combinations(self):
        self.profile["research"]["topics"] = ["public policy"]
        self.profile["preferences"]["countries"] = ["France", "Canada"]
        rows = search_plan(self.profile, "school")["queries"]
        self.assertEqual({row["country"] for row in rows}, {"France", "Canada"})
        self.assertTrue(all(row["country"] in row["query"] for row in rows))

    def test_invalid_family_rejects_without_falling_back_to_doctorates(self):
        with self.assertRaises(Error):
            search_plan(self.profile, "jobs")


class FamilyGapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = Store(self.root, create=True)
        self.addCleanup(self.store.db.close)
        self.profile = candidate()
        self.profile["research"]["topics"] = ["memory and archives"]

    def record(self, kind: str, number: int) -> dict:
        path = self.root / f"source-{number}.html"
        path.write_text(f"<h1>Research opportunity {number}</h1><p>{kind}</p>"
                        "<p>Applicants investigate memory and archives.</p>"
                        "<p>All requirements are stated here.</p>")
        row = ingest_file(self.store, path, f"https://example.invalid/opportunity/{number}", mode="html")
        sha = row["snapshot"]["sha256"]
        return assessment.validate_annotations(self.store, row["id"], {
            "values": {"opportunity_type": kind, "requirements": {"reviewed": True}},
            "evidence": {
                "opportunity_type": {"quote": kind, "evidence_sha256": sha},
                "requirements": {"quote": "All requirements are stated here.", "evidence_sha256": sha},
            },
        })

    def assessed(self, kind: str, number: int) -> dict:
        row = self.record(kind, number)
        packet = assessment.assessment_template(row, self.profile)
        packet["assessor"] = "Synthetic assessment for gap-report boundary"
        packet["gaps"] = ["Develop archival transcription practice"]
        assessment.save_assessment(self.store, row["id"], self.profile, packet)
        return self.store.get(row["id"])

    def test_same_gap_is_grouped_within_family_not_across_different_goals(self):
        rows = [self.assessed(kind, index) for index, kind in enumerate(
            ("project", "research_internship", "summer_school", "winter_school"), 1)]
        result = gaps_report(self.store, self.profile)
        self.assertEqual(len(result["gaps"]), 3)
        groups = {row["family"]: row["opportunities"] for row in result["gaps"]}
        self.assertEqual(set(groups), {"phd", "internship", "school"})
        self.assertEqual(set(groups["school"]), {rows[2]["id"], rows[3]["id"]})
        self.assertEqual(groups["phd"], [rows[0]["id"]])
        self.assertIn("Family: school", (self.root / "reports/gaps.md").read_text())

    def test_stale_assessments_do_not_supply_new_training_claims(self):
        self.assessed("summer_school", 1)
        self.profile["research"]["topics"].append("landscape history")
        result = gaps_report(self.store, self.profile)
        self.assertEqual(result["assessed_opportunities"], [])
        self.assertEqual(result["gaps"], [])

    def test_unassessed_opportunity_does_not_invent_learning_deficiencies(self):
        self.record("research_internship", 1)
        result = gaps_report(self.store, self.profile)
        self.assertEqual(result["gaps"], [])


if __name__ == "__main__":
    unittest.main()
