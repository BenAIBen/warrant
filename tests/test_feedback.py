"""DESIGN_SPEC.md §9.3 — T14, T15, T16. The disagreement/override loop.

This is the heart of the feature: brief §4's unoccupied position and
implication #6's "single highest-leverage requirement". These tests assert that
a dispute writes rows, changes the score on the very next render, and can be
reverted.
"""

import unittest

import support
from warrant import reasons as reasons_mod
from warrant.db import connect
from warrant.feedback import (CODE_EFFECTS, record_dispute, record_review)
from warrant.queue import build_run, revert_adjustment
from warrant.timeutil import shift


class TestT14DisputeEffect(unittest.TestCase):
    """T14 — EVIDENCE_WRONG on Kestrel's pricing_page_repeat.

    The spec's expected total after the dispute is 44.92 (= 59.87 - 14.95).
    This build scores Kestrel at 61.24 for the tech_stack_match reason recorded
    in README.md "Deviations", so the expected post-dispute total is
    61.24 - 14.95 = 46.29. The subtraction — which is what T14 is actually
    testing — is asserted exactly.
    """

    def setUp(self):
        self.path, self.conn = support.build_kestrel_db()
        self.signal_type_id = self.conn.execute(
            "SELECT signal_type_id FROM signal_types WHERE code = ?",
            ("pricing_page_repeat",)).fetchone()["signal_type_id"]

    def tearDown(self):
        self.conn.close()

    def test_dispute_writes_exactly_one_row_of_each_kind(self):
        record_dispute(self.conn, 1, support.KESTREL_ACCOUNT_ID, "EVIDENCE_WRONG",
                       support.AS_OF, signal_type_id=self.signal_type_id)
        disagreements = self.conn.execute(
            "SELECT * FROM disagreements WHERE rep_id = 1").fetchall()
        self.assertEqual(len(disagreements), 1)
        self.assertEqual(disagreements[0]["scope"], "reason")
        self.assertEqual(disagreements[0]["signal_type_id"], self.signal_type_id)
        self.assertEqual(disagreements[0]["status"], "applied")

        adjustments = self.conn.execute(
            "SELECT * FROM queue_adjustments WHERE rep_id = 1").fetchall()
        self.assertEqual(len(adjustments), 1)
        self.assertEqual(adjustments[0]["kind"], "suppress_signal_type")
        self.assertIsNotNone(adjustments[0]["account_id"],
                             "EVIDENCE_WRONG must be scoped to this account, "
                             "not the whole patch")
        self.assertEqual(adjustments[0]["expires_at"], shift(support.AS_OF, days=90))
        self.assertEqual(disagreements[0]["resulting_adjustment_id"],
                         adjustments[0]["adjustment_id"])

    def test_next_run_drops_the_points_by_exactly_the_reason_value(self):
        before = support.kestrel_score(self.conn)
        pricing = support.contributions_by_code(before)["pricing_page_repeat"].points
        self.assertAlmostEqual(pricing, 14.95, delta=0.01)

        record_dispute(self.conn, 1, support.KESTREL_ACCOUNT_ID, "EVIDENCE_WRONG",
                       support.AS_OF, signal_type_id=self.signal_type_id)

        after = support.kestrel_score(self.conn)
        self.assertAlmostEqual(after.points, before.points - pricing, delta=0.01)
        self.assertAlmostEqual(after.points, 46.29, delta=0.01)
        self.assertAlmostEqual(after.points_before_adjustment, 61.24, delta=0.01)

    def test_disputed_reason_stays_on_screen_struck_through_in_its_slot(self):
        """§7.4 — silently backfilling the slot would make the disagreement
        feel unregistered."""
        record_dispute(self.conn, 1, support.KESTREL_ACCOUNT_ID, "EVIDENCE_WRONG",
                       support.AS_OF, signal_type_id=self.signal_type_id)
        score = support.kestrel_score(self.conn)
        ctx = {"owner_name": "Sam Okafor", "people_count": score.people_count}
        all_reasons, shown = reasons_mod.build_reasons(self.conn, score, ctx)
        by_code = {r.code: r for r in all_reasons}
        pricing = by_code["pricing_page_repeat"]
        self.assertTrue(pricing.is_suppressed)
        self.assertEqual(pricing.shown, 1, "the disputed reason left its slot")
        self.assertEqual(pricing.rank, 2, "the disputed reason moved rank")
        self.assertEqual(pricing.points, 0.0)
        self.assertAlmostEqual(pricing.points_before_adjustment, 14.95, delta=0.01)
        self.assertIn("suppressed", score.adjustment_flags)

    def test_limits_line_names_the_suppression(self):
        record_dispute(self.conn, 1, support.KESTREL_ACCOUNT_ID, "EVIDENCE_WRONG",
                       support.AS_OF, signal_type_id=self.signal_type_id)
        score = support.kestrel_score(self.conn)
        ctx = {"owner_name": "Sam Okafor", "people_count": score.people_count}
        all_reasons, shown = reasons_mod.build_reasons(self.conn, score, ctx)
        line = reasons_mod.build_limits_line(score, all_reasons, shown)
        self.assertIn('Suppressed by you: "Repeat pricing-page visits".', line)

    def test_T07_still_holds_after_a_dispute(self):
        record_dispute(self.conn, 1, support.KESTREL_ACCOUNT_ID, "EVIDENCE_WRONG",
                       support.AS_OF, signal_type_id=self.signal_type_id)
        score = support.kestrel_score(self.conn)
        total = round(sum(c.points for c in score.contributions), 2)
        self.assertAlmostEqual(total, score.points, delta=0.01)

    def test_dispute_writes_task_events(self):
        record_dispute(self.conn, 1, support.KESTREL_ACCOUNT_ID, "EVIDENCE_WRONG",
                       support.AS_OF, signal_type_id=self.signal_type_id,
                       rank_at_event=1)
        types = [r["event_type"] for r in self.conn.execute(
            "SELECT event_type FROM task_events WHERE rep_id = 1").fetchall()]
        self.assertIn("disputed", types)
        self.assertIn("adjusted", types)


class TestT15Revert(unittest.TestCase):
    """T15 — revert restores the score and sets status='reverted'."""

    def test_revert_restores_points_and_status(self):
        path, conn = support.build_kestrel_db()
        signal_type_id = conn.execute(
            "SELECT signal_type_id FROM signal_types WHERE code = ?",
            ("pricing_page_repeat",)).fetchone()["signal_type_id"]
        original = support.kestrel_score(conn).points
        self.assertAlmostEqual(original, 61.24, delta=0.01)

        disagreement_id, adjustment_id = record_dispute(
            conn, 1, support.KESTREL_ACCOUNT_ID, "EVIDENCE_WRONG", support.AS_OF,
            signal_type_id=signal_type_id)
        self.assertAlmostEqual(support.kestrel_score(conn).points, 46.29, delta=0.01)

        revert_adjustment(conn, 1, adjustment_id, support.AS_OF)
        conn.commit()

        restored = support.kestrel_score(conn)
        self.assertAlmostEqual(restored.points, original, delta=0.01)
        self.assertAlmostEqual(restored.points, 61.24, delta=0.01)
        self.assertEqual(restored.adjustment_flags, [])

        row = conn.execute("SELECT status FROM disagreements WHERE disagreement_id = ?",
                           (disagreement_id,)).fetchone()
        self.assertEqual(row["status"], "reverted")
        row = conn.execute("SELECT * FROM queue_adjustments WHERE adjustment_id = ?",
                           (adjustment_id,)).fetchone()
        self.assertEqual(row["is_active"], 0)
        self.assertEqual(row["reverted_at"], support.AS_OF)
        conn.close()


class TestT16NoCodeIsANoOp(unittest.TestCase):
    """T16 — every one of the seven codes produces an adjustment row, and
    'leave it' produces a status='reviewed' row."""

    def setUp(self):
        self.conn = connect(support.fresh_seeded_db("t16-%s" % self._testMethodName))
        self.accounts = [r["account_id"] for r in self.conn.execute(
            "SELECT account_id FROM accounts WHERE owner_rep_id = 2 AND is_active = 1 "
            "ORDER BY account_id LIMIT 10").fetchall()]
        self.signal_type_id = self.conn.execute(
            "SELECT signal_type_id FROM signal_types WHERE code = ?",
            ("pricing_page_repeat",)).fetchone()["signal_type_id"]

    def tearDown(self):
        self.conn.close()

    def test_all_seven_codes_create_an_adjustment(self):
        for index, code in enumerate(sorted(CODE_EFFECTS)):
            account_id = self.accounts[index]
            person = self.conn.execute(
                "SELECT person_id FROM people WHERE account_id = ? LIMIT 1",
                (account_id,)).fetchone()
            kwargs = {"signal_type_id": self.signal_type_id}
            if code == "WRONG_PERSON":
                if person is None:
                    self.skipTest("no person on account %d" % account_id)
                kwargs["person_id"] = person["person_id"]
                kwargs["reason_id"] = None
            disagreement_id, adjustment_id = record_dispute(
                self.conn, 2, account_id, code, support.AS_OF, **kwargs)
            self.assertIsNotNone(adjustment_id, "%s produced no adjustment" % code)
            row = self.conn.execute(
                "SELECT * FROM queue_adjustments WHERE adjustment_id = ?",
                (adjustment_id,)).fetchone()
            expected_kind, default_days, _allowed = CODE_EFFECTS[code]
            self.assertEqual(row["kind"], expected_kind, code)
            self.assertEqual(row["expires_at"], shift(support.AS_OF, days=default_days),
                             "%s window is wrong" % code)
            self.assertEqual(row["is_active"], 1)
            status = self.conn.execute(
                "SELECT status FROM disagreements WHERE disagreement_id = ?",
                (disagreement_id,)).fetchone()["status"]
            self.assertEqual(status, "applied", code)

    def test_leave_it_writes_a_reviewed_row_and_no_adjustment(self):
        before = self.conn.execute(
            "SELECT COUNT(*) AS n FROM queue_adjustments WHERE rep_id = 2"
        ).fetchone()["n"]
        disagreement_id = record_review(self.conn, 2, self.accounts[0],
                                        self.signal_type_id, support.AS_OF)
        row = self.conn.execute(
            "SELECT * FROM disagreements WHERE disagreement_id = ?",
            (disagreement_id,)).fetchone()
        self.assertEqual(row["status"], "reviewed")
        self.assertIsNone(row["resulting_adjustment_id"])
        after = self.conn.execute(
            "SELECT COUNT(*) AS n FROM queue_adjustments WHERE rep_id = 2"
        ).fetchone()["n"]
        self.assertEqual(after, before, "'leave it' must not create an adjustment")

    def test_bad_timing_honours_the_reps_chosen_window(self):
        for days in (14, 30, 90):
            _d, adjustment_id = record_dispute(
                self.conn, 2, self.accounts[days % 7], "BAD_TIMING", support.AS_OF,
                window_days=days)
            row = self.conn.execute(
                "SELECT expires_at FROM queue_adjustments WHERE adjustment_id = ?",
                (adjustment_id,)).fetchone()
            self.assertEqual(row["expires_at"], shift(support.AS_OF, days=days))

    def test_an_unsupported_window_falls_back_to_the_default(self):
        _d, adjustment_id = record_dispute(
            self.conn, 2, self.accounts[0], "BAD_TIMING", support.AS_OF,
            window_days=9999)
        row = self.conn.execute(
            "SELECT expires_at FROM queue_adjustments WHERE adjustment_id = ?",
            (adjustment_id,)).fetchone()
        self.assertEqual(row["expires_at"], shift(support.AS_OF, days=30))

    def test_mute_removes_the_account_from_the_queue_on_the_next_render(self):
        account_id = self.accounts[0]
        _run, before, _adj = build_run(self.conn, 2, support.AS_OF, persist=False)
        self.assertIn(account_id, [i.account_id for i in before])
        record_dispute(self.conn, 2, account_id, "NOT_A_FIT", support.AS_OF)
        _run, after, _adj = build_run(self.conn, 2, support.AS_OF, persist=False)
        self.assertNotIn(account_id, [i.account_id for i in after])

    def test_wrong_person_without_a_person_is_refused_not_guessed(self):
        from warrant.feedback import DisputeError
        with self.assertRaises(DisputeError):
            record_dispute(self.conn, 2, self.accounts[0], "WRONG_PERSON",
                           support.AS_OF, signal_type_id=self.signal_type_id)

    def test_exclude_person_removes_only_that_persons_events(self):
        path, conn = support.build_kestrel_db()
        before = support.kestrel_score(conn)
        by_code = support.contributions_by_code(before)
        self.assertIn("senior_buyer_engaged", by_code)
        record_dispute(conn, 1, support.KESTREL_ACCOUNT_ID, "WRONG_PERSON",
                       support.AS_OF,
                       signal_type_id=by_code["senior_buyer_engaged"].signal_type_id,
                       person_id=1)                       # Ana Belic
        after = support.kestrel_score(conn)
        after_codes = support.contributions_by_code(after)
        # Ana's events drove product usage, pricing, senior buyer and new hire.
        self.assertEqual(after_codes["senior_buyer_engaged"].points, 0.0)
        self.assertEqual(after_codes["product_usage_active"].points, 0.0)
        # Events with no person, and state signals, are untouched.
        self.assertAlmostEqual(after_codes["third_party_intent_6sense"].points,
                               4.16, delta=0.01)
        self.assertAlmostEqual(after_codes["icp_industry_match"].points, 6.00,
                               delta=0.01)
        self.assertLess(after.points, before.points)
        conn.close()


class TestDisputeNoteLimit(unittest.TestCase):
    def test_notes_are_capped_at_280_characters_server_side(self):
        path, conn = support.build_kestrel_db()
        signal_type_id = conn.execute(
            "SELECT signal_type_id FROM signal_types WHERE code = ?",
            ("pricing_page_repeat",)).fetchone()["signal_type_id"]
        disagreement_id, _adj = record_dispute(
            conn, 1, support.KESTREL_ACCOUNT_ID, "EVIDENCE_WRONG", support.AS_OF,
            signal_type_id=signal_type_id, note="x" * 500)
        row = conn.execute("SELECT note FROM disagreements WHERE disagreement_id = ?",
                           (disagreement_id,)).fetchone()
        self.assertEqual(len(row["note"]), 280)
        conn.close()


class TestRulesetIsNeverWritten(unittest.TestCase):
    """§7.3 invariant 3 / build rule 5 — signal_types is never written by a
    rep-facing route."""

    def test_no_rep_facing_module_writes_signal_types(self):
        import os
        for name in ("app.py", os.path.join("warrant", "feedback.py"),
                     os.path.join("warrant", "queue.py"),
                     os.path.join("warrant", "scoring.py"),
                     os.path.join("warrant", "render.py"),
                     os.path.join("warrant", "metrics.py")):
            path = os.path.join(support.REPO_ROOT, name)
            text = open(path, encoding="utf-8").read().lower()
            for statement in ("update signal_types", "insert into signal_types",
                              "delete from signal_types"):
                self.assertNotIn(statement, text, "%s writes signal_types" % name)


if __name__ == "__main__":
    unittest.main()
