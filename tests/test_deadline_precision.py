from __future__ import annotations

import json
import unittest
from datetime import datetime

from phd_search.extract import deadline_state, extract, parse_deadline


class DeadlinePrecisionTests(unittest.TestCase):
    def posting(self, structured, *visible):
        job = {"@type": "JobPosting", "title": "Doctoral project in urban history", "validThrough": structured}
        markup = '<html><script type="application/ld+json">' + json.dumps(job) + '</script><h1>Doctoral project in urban history</h1>'
        markup += ''.join('<p>Closing date: ' + value + '</p>' for value in visible) + '</html>'
        return extract(markup, "https://university.example/doctoral/urban-history")[0]

    def test_visible_date_does_not_extend_explicit_non_midnight_cutoff(self):
        data = self.posting("2031-06-10T16:37:00+00:00", "10 June 2031")
        self.assertEqual(data["deadline"]["precision"], "time")
        self.assertEqual(data["deadline"]["value"], "2031-06-10T16:37:00+00:00")
        self.assertEqual(deadline_state(data["deadline"], datetime.fromisoformat("2031-06-10T17:00:00+00:00"))["state"], "expired")
        self.assertEqual(len(data["deadline_candidates"]), 2)
        self.assertEqual(data["provenance"]["deadline"]["locator"], "JSON-LD.validThrough")

    def test_exact_cutoff_preserves_its_source_timezone(self):
        data = self.posting("2031-06-10T18:15:00+05:30", "10 June 2031")
        self.assertEqual(data["deadline"]["value"], "2031-06-10T18:15:00+05:30")
        self.assertEqual(deadline_state(data["deadline"], datetime.fromisoformat("2031-06-10T13:00:00+00:00"))["state"], "expired")

    def test_machine_midnight_keeps_existing_visible_date_only_contract(self):
        data = self.posting("2031-06-10T00:00:00+00:00", "10 June 2031")
        self.assertEqual(data["deadline"]["precision"], "date")
        self.assertEqual(deadline_state(data["deadline"], datetime.fromisoformat("2031-06-10T12:00:00+00:00"))["state"], "urgent")

    def test_conflicting_exact_times_are_unknown_not_last_one_wins(self):
        data = self.posting("2031-06-10T18:00:00+00:00", "10 June 2031 - 19:00 (UTC)")
        self.assertTrue(data["deadline"]["conflict"])
        self.assertEqual(deadline_state(data["deadline"])["state"], "unknown")

    def test_same_instant_in_different_timezones_is_not_a_conflict(self):
        data = self.posting("2031-06-10T23:30:00-02:00", "11 June 2031 - 01:30 (UTC)")
        self.assertEqual(data["deadline"]["precision"], "time")
        self.assertFalse(data["deadline"].get("conflict", False))

    def test_visible_time_without_timezone_does_not_become_all_day(self):
        deadline = parse_deadline("10 June 2031 - 18:00")
        self.assertIsNone(deadline["value"])
        self.assertEqual(deadline["local_value"], "2031-06-10T18:00:00")
        data = self.posting("2031-06-10T00:00:00+00:00", "10 June 2031 - 18:00")
        self.assertEqual(deadline_state(data["deadline"])["state"], "unknown")

    def test_iso_visible_time_without_timezone_remains_unknown(self):
        data = self.posting("2031-06-10T18:00:00+00:00", "2031-06-10T17:00:00")
        self.assertEqual(deadline_state(data["deadline"])["state"], "unknown")

    def test_parenthesized_time_and_cet_are_an_exact_fixed_offset(self):
        data = self.posting(None, "Tuesday, 27 October 2031 (16:00 CET)")
        self.assertEqual(data["deadline"]["value"], "2031-10-27T16:00:00+01:00")
        self.assertEqual(data["deadline"]["precision"], "time")
        self.assertEqual(deadline_state(data["deadline"], datetime.fromisoformat("2031-10-27T15:01:00+00:00"))["state"], "expired")
        summer = parse_deadline("10 June 2031 (16:00 CET)")
        self.assertTrue(summer["value"].endswith("+01:00"))

    def test_aoe_suffix_preserves_exact_next_day_utc_cutoff(self):
        deadline = parse_deadline("31 October 2031, 23:59 AoE")
        self.assertEqual(deadline["value"], "2031-10-31T23:59:00-12:00")
        self.assertEqual(deadline_state(deadline, datetime.fromisoformat("2031-11-01T11:58:00+00:00"))["state"], "urgent")
        self.assertEqual(deadline_state(deadline, datetime.fromisoformat("2031-11-01T12:00:00+00:00"))["state"], "expired")

    def test_parenthesized_time_with_unknown_zone_cannot_become_all_day(self):
        deadline = parse_deadline("10 June 2031 (18:00 LOCAL)")
        self.assertIsNone(deadline["value"])
        self.assertEqual(deadline["precision"], "unknown")
        self.assertEqual(deadline["local_value"], "2031-06-10T18:00:00")
        self.assertEqual(deadline_state(deadline)["state"], "unknown")

    def test_parenthesized_time_without_zone_remains_unknown(self):
        deadline = parse_deadline("10 June 2031 (18:00)")
        self.assertIsNone(deadline["value"])
        self.assertEqual(deadline["reason"], "time_without_timezone")

    def test_conflict_retains_all_candidates_and_cannot_be_cleared_by_later_label(self):
        data = self.posting("2031-06-10T18:00:00+00:00", "11 June 2031", "10 June 2031")
        self.assertTrue(data["deadline"]["conflict"])
        self.assertEqual(len(data["deadline_candidates"]), 3)
        self.assertEqual(deadline_state(data["deadline"])["state"], "unknown")
