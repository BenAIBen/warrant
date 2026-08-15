"""DESIGN_SPEC.md §9.3 — T01, T02, T03, T04, T07, plus the live-DB proof."""

import os
import sqlite3
import unittest

import support
from warrant.db import connect
from warrant.scoring import (POINT_FLOOR, band_from, compute_confidence,
                             magnitude_factor, score_account)


class TestT01Reproducibility(unittest.TestCase):
    """T01 — seed_db.py run twice produces identical content for accounts,
    people and signal_events."""

    def test_seed_is_reproducible(self):
        first = support.fresh_seeded_db("repro-a")
        second = support.fresh_seeded_db("repro-b")
        self.assertNotEqual(first, second)
        # Table names cannot be bound parameters, so these are three separate
        # literal statements rather than one interpolated one — T20 inspects
        # this file too.
        queries = (("accounts", "SELECT * FROM accounts ORDER BY account_id"),
                   ("people", "SELECT * FROM people ORDER BY person_id"),
                   ("signal_events", "SELECT * FROM signal_events ORDER BY event_id"))
        for table, sql in queries:
            with sqlite3.connect(first) as a, sqlite3.connect(second) as b:
                rows_a = a.execute(sql).fetchall()
                rows_b = b.execute(sql).fetchall()
            self.assertEqual(len(rows_a), len(rows_b), table)
            self.assertEqual(rows_a, rows_b, "%s differs between seeded runs" % table)

    def test_seeded_corpus_has_the_forced_cohorts(self):
        conn = connect(support.build_seeded_db())
        zero = conn.execute(
            "SELECT COUNT(*) AS n FROM accounts a WHERE NOT EXISTS "
            "(SELECT 1 FROM signal_events e WHERE e.account_id = a.account_id)"
        ).fetchone()["n"]
        self.assertGreaterEqual(zero, 10, "no zero-event cohort was generated")
        brand_new = conn.execute(
            "SELECT COUNT(*) AS n FROM accounts WHERE first_seen_at >= ?",
            ("2026-08-01T00:00:00Z",)).fetchone()["n"]
        self.assertGreaterEqual(brand_new, 5, "no brand-new cohort was generated")
        conn.close()


class TestT02KestrelWorkedExample(unittest.TestCase):
    """T02 / T03 — the §4.4 worked example, component by component.

    NOTE ON THE SPEC DISCREPANCY (see README.md "Deviations from the spec"):
    §4.1 defines tech_stack_match as kind='state', weight = cap = +5.0, no
    decay. §4.4's worked example instead treats it as a decayed event with a
    180-day half-life, giving +3.63. This build follows §4.1, the normative
    weight table, so the total is 61.24 rather than the 59.87 printed in §4.4.
    Every other component reproduces to the cent. test_discrepancy_is_isolated
    below proves that tech_stack_match is the only difference.
    """

    @classmethod
    def setUpClass(cls):
        cls.path, cls.conn = support.build_kestrel_db()

    def setUp(self):
        self.score = support.kestrel_score(self.conn)
        self.by_code = support.contributions_by_code(self.score)

    def test_every_component_matches_spec_4_4(self):
        expected = {
            "product_usage_active": 24.00,      # raw 37.73, capped
            "pricing_page_repeat": 14.95,
            "senior_buyer_engaged": 9.36,
            "new_hire_icp_role": 5.79,
            "icp_industry_match": 6.00,
            "icp_size_match": 6.00,
            "third_party_intent_6sense": 4.16,
            "champion_departed": -7.24,
            "unsubscribed_or_bounced": -6.78,
        }
        for code, points in expected.items():
            self.assertIn(code, self.by_code, code)
            self.assertAlmostEqual(self.by_code[code].points, points, delta=0.01,
                                   msg="%s: spec §4.4 says %.2f" % (code, points))

    def test_T02_total_band_and_confidence(self):
        self.assertAlmostEqual(self.score.points, 61.24, delta=0.01)
        self.assertEqual(self.score.band, "ACT_NOW")
        self.assertEqual(self.score.confidence, "high")
        self.assertEqual(self.score.distinct_signal_types, 10)
        self.assertAlmostEqual(self.score.data_completeness, 1.0, delta=0.001)

    def test_discrepancy_is_isolated_to_tech_stack_match(self):
        """Substituting §4.4's own tech_stack_match figure reproduces 59.87.

        This is the whole of the gap between this build and the printed total.
        """
        tech = self.by_code["tech_stack_match"]
        self.assertEqual(tech.kind, "state")
        self.assertAlmostEqual(tech.points, 5.00, delta=0.001)
        as_spec_4_4_printed = round(self.score.points - tech.points + 3.63, 2)
        self.assertAlmostEqual(as_spec_4_4_printed, 59.87, delta=0.01)

    def test_T03_product_usage_is_capped(self):
        usage = self.by_code["product_usage_active"]
        raw = sum(e.contribution for e in usage.events)
        self.assertAlmostEqual(raw, 37.73, delta=0.01)
        self.assertAlmostEqual(usage.points, 24.00, delta=0.001)
        self.assertTrue(usage.cap_applied)
        self.assertLessEqual(abs(usage.points), abs(usage.max_contribution))

    def test_magnitude_factor_matches_the_published_curve(self):
        # §4.2: 1 -> x1.00, 3 -> x1.24, 10 -> x1.50, 40 -> x1.80, 100 -> x2.00
        for magnitude, factor in ((1, 1.00), (3, 1.24), (10, 1.50),
                                  (40, 1.80), (100, 2.00)):
            self.assertAlmostEqual(magnitude_factor(magnitude), factor, delta=0.005)

    def test_band_gate_demotes_high_points_low_confidence(self):
        # Confidence can cost a band, never win one (§4.2).
        self.assertEqual(band_from(60.0, "high"), "ACT_NOW")
        self.assertEqual(band_from(60.0, "medium"), "ACT_NOW")
        self.assertEqual(band_from(60.0, "low"), "REVIEW")
        self.assertEqual(band_from(60.0, "insufficient"), "INSUFFICIENT_EVIDENCE")
        self.assertEqual(band_from(30.0, "high"), "REVIEW")
        self.assertEqual(band_from(10.0, "high"), "HOLD")
        self.assertEqual(band_from(-20.0, "high"), "HOLD")

    def test_confidence_cascade_first_match_wins(self):
        self.assertEqual(compute_confidence(1, 2.0, 1.0, 400), "insufficient")
        self.assertEqual(compute_confidence(9, 2.0, 0.2, 400), "insufficient")
        self.assertEqual(compute_confidence(2, 2.0, 1.0, 400), "low")
        self.assertEqual(compute_confidence(9, 60.0, 1.0, 400), "low")
        self.assertEqual(compute_confidence(3, 20.0, 0.8, 400), "medium")
        self.assertEqual(compute_confidence(6, 2.0, 1.0, 400), "high")
        # brand-new cap applies unconditionally after the cascade (§8.7)
        self.assertEqual(compute_confidence(6, 2.0, 1.0, 3), "medium")


class TestT04Floor(unittest.TestCase):
    """T04 — reasons below the 0.5-point floor produce no row and contribute
    nothing."""

    def test_below_floor_signal_is_dropped_entirely(self):
        path, conn = support.build_kestrel_db()
        # third_party_intent_6sense: weight +4.0, half-life 14d. Push both
        # events far enough back that the total falls under 0.5 pts.
        conn.execute("UPDATE signal_events SET occurred_at = ?, observed_at = ? "
                     "WHERE signal_type_id = (SELECT signal_type_id FROM signal_types "
                     "WHERE code = ?)",
                     ("2026-02-01T09:00:00Z", "2026-02-01T09:00:00Z",
                      "third_party_intent_6sense"))
        conn.commit()
        score = support.kestrel_score(conn)
        codes = {c.code for c in score.contributions}
        self.assertNotIn("third_party_intent_6sense", codes,
                         "a signal worth under 0.5 pts must not create a reason")
        for contribution in score.contributions:
            self.assertGreaterEqual(abs(contribution.points_before_adjustment),
                                    POINT_FLOOR)
        conn.close()


class TestT07ExplanationIsTheModel(unittest.TestCase):
    """T07 — for every scored account, the reasons sum to the score.

    This is the implication-#9 guarantee. If it fails, the explanation and the
    decision have drifted apart and the whole feature is MadKudu with extra
    steps.
    """

    def test_reasons_sum_to_points_across_the_whole_corpus(self):
        conn = connect(support.build_seeded_db())
        scores = support.score_every_account(conn)
        self.assertGreaterEqual(len(scores), 200)
        for score in scores:
            total = round(sum(c.points for c in score.contributions), 2)
            self.assertAlmostEqual(
                total, score.points, delta=0.01,
                msg="account %d: reasons sum to %.2f but score is %.2f"
                    % (score.account_id, total, score.points))
        conn.close()

    def test_persisted_reason_rows_also_sum_to_the_persisted_score(self):
        """The same guarantee, asserted against what actually landed in the DB
        after a real run — not just the in-memory objects."""
        from warrant.queue import build_run
        conn = connect(support.fresh_seeded_db("t07-persist"))
        run_id, items, _ = build_run(conn, 1, support.AS_OF)
        rows = conn.execute(
            "SELECT s.score_id, s.points, "
            "       (SELECT ROUND(SUM(r.points), 2) FROM reasons r "
            "        WHERE r.score_id = s.score_id) AS reason_sum "
            "FROM scores s WHERE s.run_id = ?", (run_id,)).fetchall()
        self.assertGreater(len(rows), 0)
        for row in rows:
            reason_sum = row["reason_sum"] if row["reason_sum"] is not None else 0.0
            self.assertAlmostEqual(reason_sum, row["points"], delta=0.01,
                                   msg="score_id %d" % row["score_id"])
        conn.close()


class TestLiveDatabaseNotFixtures(unittest.TestCase):
    """Proof that the scoring path reads the database at call time.

    Mutate a row with raw sqlite3, call the same scoring function again, and
    assert the answer moved. If anything were cached, hardcoded or precomputed,
    this test fails.
    """

    def test_mutating_a_magnitude_changes_the_score(self):
        path, conn = support.build_kestrel_db()
        before = support.kestrel_score(conn)
        usage_before = support.contributions_by_code(before)["pricing_page_repeat"].points

        # Raw connection, not the app's — nothing in warrant/ knows this happened.
        raw = sqlite3.connect(path)
        raw.execute(
            "UPDATE signal_events SET magnitude = ? WHERE signal_type_id = "
            "(SELECT signal_type_id FROM signal_types WHERE code = ?)",
            (30.0, "pricing_page_repeat"))
        raw.commit()
        raw.close()

        after = support.kestrel_score(connect(path))
        usage_after = support.contributions_by_code(after)["pricing_page_repeat"].points
        self.assertGreater(usage_after, usage_before,
                           "score did not react to a live DB change")
        self.assertGreater(after.points, before.points)
        conn.close()

    def test_deleting_events_removes_the_reason(self):
        path, conn = support.build_kestrel_db()
        self.assertIn("champion_departed",
                      support.contributions_by_code(support.kestrel_score(conn)))
        raw = sqlite3.connect(path)
        raw.execute("DELETE FROM signal_events WHERE signal_type_id = "
                    "(SELECT signal_type_id FROM signal_types WHERE code = ?)",
                    ("champion_departed",))
        raw.commit()
        raw.close()
        after = support.kestrel_score(connect(path))
        self.assertNotIn("champion_departed", support.contributions_by_code(after))
        conn.close()

    def test_changing_the_weight_table_changes_the_arithmetic(self):
        """The weights live in data, not in Python constants (§3.4). Prove it."""
        path, conn = support.build_kestrel_db()
        before = support.kestrel_score(conn).points
        raw = sqlite3.connect(path)
        raw.execute("UPDATE signal_types SET base_weight = ?, max_contribution = ? "
                    "WHERE code = ?", (3.0, 3.0, "icp_industry_match"))
        raw.commit()
        raw.close()
        after = support.kestrel_score(connect(path)).points
        self.assertAlmostEqual(after, before - 3.0, delta=0.01)
        conn.close()

    def test_db_file_exists_and_is_a_real_sqlite_file(self):
        path = support.build_seeded_db()
        self.assertTrue(os.path.exists(path))
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(15), b"SQLite format 3")


if __name__ == "__main__":
    unittest.main()
