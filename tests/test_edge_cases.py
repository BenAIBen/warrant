"""DESIGN_SPEC.md §9.3 — T17, T18, and §8 generally.

The rule underneath all of §8: the system must never manufacture a confident
reason from an absence. Not knowing something is a fact about us, and it is
rendered as one.
"""

import unittest

import support
from warrant import reasons as reasons_mod
from warrant.db import connect
from warrant.queue import build_run, create_adjustment
from warrant.scoring import (evaluate_predicate, requires_evidence_review,
                             score_account)
from warrant.timeutil import shift


def reasons_for(conn, score):
    ctx = {"owner_name": "Sam Okafor", "people_count": score.people_count}
    return reasons_mod.build_reasons(conn, score, ctx)


class TestT17EdgeCases(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.conn = connect(support.build_seeded_db())
        cls.scores = support.score_every_account(cls.conn)

    # -- §8.3 zero signals ------------------------------------------------
    def test_zero_event_account_is_insufficient_and_still_gets_a_row(self):
        zeroes = [s for s in self.scores if not s.contributions]
        self.assertGreater(len(zeroes), 0, "no zero-signal account in the corpus")
        for score in zeroes:
            self.assertEqual(score.points, 0.0)
            self.assertEqual(score.distinct_signal_types, 0)
            self.assertIsNone(score.freshest_evidence_at)
            self.assertEqual(score.confidence, "insufficient")
            self.assertEqual(score.band, "INSUFFICIENT_EVIDENCE")
            all_reasons, shown = reasons_for(self.conn, score)
            self.assertEqual(all_reasons, [])
            self.assertEqual(reasons_mod.build_limits_line(score, all_reasons, shown),
                             "No signals found.")
            self.assertEqual(reasons_mod.thin_data_line(score),
                             reasons_mod.NO_SIGNALS_LINE)

    def test_zero_signal_accounts_are_still_persisted_in_a_run(self):
        conn = connect(support.fresh_seeded_db("t17-persist"))
        _run_id, items, _adj = build_run(conn, 1, support.AS_OF)
        zero_items = [i for i in items if not i.all_reasons]
        self.assertGreater(len(zero_items), 0)
        for item in zero_items:
            row = conn.execute("SELECT * FROM scores WHERE score_id = ?",
                               (item.score_id,)).fetchone()
            self.assertIsNotNone(row, "a zero-signal account was silently dropped")
            self.assertEqual(row["band"], "INSUFFICIENT_EVIDENCE")
            self.assertEqual(row["limits_line"], "No signals found.")
        conn.close()

    # -- §8.4 brand-new guard ---------------------------------------------
    def test_no_engagement_90d_does_not_fire_on_a_brand_new_account(self):
        ctx = {"account_age_days": 20.0, "total_event_count": 1,
               "days_silent": 120.0, "people_count": 3, "senior_people_count": 1}
        fired, _value = evaluate_predicate("no_engagement_90d", {}, 1, ctx)
        self.assertFalse(fired, "penalised an account for not existing long enough")

        ctx["account_age_days"] = 400.0
        fired, value = evaluate_predicate("no_engagement_90d", {}, 1, ctx)
        self.assertTrue(fired, "the guard is swallowing a genuine 90-day silence")
        self.assertEqual(value, "120")

    def test_no_engagement_90d_never_fires_on_a_new_account_in_the_corpus(self):
        for score in self.scores:
            if score.account_age_days < 90:
                codes = {c.code for c in score.contributions}
                self.assertNotIn("no_engagement_90d", codes,
                                 "account %d is %d days old and was penalised for "
                                 "silence" % (score.account_id, score.account_age_days))

    def test_brand_new_accounts_are_capped_at_medium_confidence(self):
        newly_seen = [s for s in self.scores if s.account_age_days < 14]
        self.assertGreater(len(newly_seen), 0, "no brand-new account in the corpus")
        for score in newly_seen:
            self.assertIn(score.confidence, ("insufficient", "low", "medium"))
            self.assertNotEqual(score.confidence, "high")
            line = reasons_mod.brand_new_line(score)
            self.assertIsNotNone(line)
            self.assertIn("We may be missing history", line)

    # -- §4.1 / §8.1 authority guard --------------------------------------
    def test_no_buying_authority_does_not_fire_with_zero_people(self):
        ctx = {"people_count": 0, "senior_people_count": 0, "account_age_days": 400.0,
               "total_event_count": 5, "days_silent": 1.0}
        fired, _value = evaluate_predicate("no_buying_authority_present", {}, 1, ctx)
        self.assertFalse(fired, "an empty contact list is a data gap, not a "
                                "disqualification")
        ctx["people_count"] = 4
        fired, value = evaluate_predicate("no_buying_authority_present", {}, 1, ctx)
        self.assertTrue(fired)
        self.assertEqual(value, "4")

    def test_corpus_never_fires_authority_penalty_on_an_empty_account(self):
        for score in self.scores:
            if score.people_count == 0:
                codes = {c.code for c in score.contributions}
                self.assertNotIn("no_buying_authority_present", codes)

    # -- §8.2 stale --------------------------------------------------------
    def test_stale_accounts_never_render_act_now(self):
        from warrant.timeutil import age_days
        stale = []
        for score in self.scores:
            if score.freshest_evidence_at is None:
                continue
            if age_days(support.AS_OF, score.freshest_evidence_at) > 45:
                stale.append(score)
        self.assertGreater(len(stale), 5, "no stale accounts in the corpus")
        for score in stale:
            self.assertNotEqual(score.band, "ACT_NOW",
                                "account %d has %s-old evidence and shows ACT NOW"
                                % (score.account_id, score.freshest_evidence_at))
            self.assertIn(score.confidence, ("low", "insufficient"))

    def test_stale_banner_names_the_number_of_days(self):
        stale = [s for s in self.scores if reasons_mod.stale_line(s)]
        self.assertGreater(len(stale), 0)
        line = reasons_mod.stale_line(stale[0])
        self.assertIn("No new evidence in", line)
        self.assertIn("This ranking reflects activity that ended on", line)
        chip = reasons_mod.freshness_chip(stale[0])
        self.assertTrue(chip.startswith("STALE · "))

    def test_no_extra_staleness_penalty_is_applied(self):
        """§8.2: decay has already shrunk the points; no flat deduction. If one
        existed, the reasons would no longer sum to the score."""
        for score in self.scores:
            total = round(sum(c.points for c in score.contributions), 2)
            self.assertAlmostEqual(total, score.points, delta=0.01)

    # -- §8.5 conflicting --------------------------------------------------
    def test_conflicting_accounts_render_the_disagree_line(self):
        conflicted = [s for s in self.scores if s.conflicted]
        self.assertGreater(len(conflicted), 0, "no conflicting account in the corpus")
        for score in conflicted[:20]:
            all_reasons, _shown = reasons_for(self.conn, score)
            line = reasons_mod.conflict_line(score, all_reasons)
            self.assertIsNotNone(line, "account %d is conflicted but renders no "
                                       "disagreement line" % score.account_id)
            self.assertTrue(line.startswith("These signals disagree."))
            self.assertIn(", but ", line)
            self.assertTrue(line.endswith("Read both before you act."))

    def test_conflicting_accounts_show_the_negative_not_hide_it(self):
        conflicted = [s for s in self.scores if s.conflicted]
        for score in conflicted[:20]:
            _all, shown = reasons_for(self.conn, score)
            self.assertTrue(any(r.polarity == "negative" for r in shown),
                            "account %d hid its negative" % score.account_id)

    # -- §8.1 thin data ----------------------------------------------------
    def test_thin_accounts_are_never_act_now_and_are_never_padded(self):
        """§8.1 vs §8.7 — a conflict in the spec, resolved in favour of §8.7.

        §8.1 says 1 OR 2 signal types -> confidence 'insufficient'. §8.7's
        cascade says 'insufficient if distinct < 2' and, on the very next line,
        "low if ... distinct_signal_types == 2". Those cannot both hold: under
        §8.1's reading the '== 2' clause in §8.7 would be unreachable dead code.
        This build follows §8.7, the mechanical cascade. See README.md
        "Deviations from the spec".

        The protection §8.1 actually cares about — a thin account must never be
        presented as a certainty — still holds, because 'low' confidence blocks
        ACT_NOW via the §4.2 band gate. That is what is asserted here.
        """
        thin = [s for s in self.scores if 0 < s.distinct_signal_types <= 2]
        self.assertGreater(len(thin), 0, "no thin-data account in the corpus")
        for score in thin:
            self.assertIn(score.confidence, ("insufficient", "low"))
            self.assertNotEqual(score.band, "ACT_NOW",
                                "account %d has %d signal types and shows ACT NOW"
                                % (score.account_id, score.distinct_signal_types))
            all_reasons, shown = reasons_for(self.conn, score)
            # No padding: a fit match on an account with no behaviour is a
            # statement about the segment, not the account.
            self.assertEqual(len(shown), min(len(all_reasons), 5))
            if score.distinct_signal_types < 2:
                self.assertEqual(score.confidence, "insufficient")
                self.assertEqual(score.band, "INSUFFICIENT_EVIDENCE")
                self.assertIn("Not enough to rank it.",
                              reasons_mod.thin_data_line(score))
                self.assertIsNotNone(reasons_mod.what_would_change_line(score))

    def test_low_data_completeness_is_always_insufficient(self):
        """The half of §8.1 that §8.7 agrees with, verbatim."""
        checked = 0
        for score in self.scores:
            if score.data_completeness < 0.4:
                self.assertEqual(score.confidence, "insufficient",
                                 "account %d" % score.account_id)
                self.assertEqual(score.band, "INSUFFICIENT_EVIDENCE")
                checked += 1
        self.assertGreater(checked, 0, "no low-completeness account in the corpus")

    def test_insufficient_confidence_can_never_produce_act_now(self):
        for score in self.scores:
            if score.confidence == "insufficient":
                self.assertEqual(score.band, "INSUFFICIENT_EVIDENCE")

    # -- state predicates --------------------------------------------------
    def test_icp_predicates_read_the_account_fields(self):
        account = {"industry": "Fintech", "employee_count": 420,
                   "tech_stack": '["Snowflake", "Looker"]',
                   "crm_status": "none", "owner_rep_id": 1}
        ctx = {"account_age_days": 400.0, "total_event_count": 3, "days_silent": 1.0,
               "people_count": 3, "senior_people_count": 1, "owner_name": "Sam"}
        self.assertEqual(evaluate_predicate("icp_industry", account, 1, ctx),
                         (True, "Fintech"))
        self.assertEqual(evaluate_predicate("icp_size", account, 1, ctx),
                         (True, "420"))
        self.assertEqual(evaluate_predicate("tech_stack_overlap", account, 1, ctx),
                         (True, "Snowflake"))
        self.assertEqual(evaluate_predicate("outside_icp_size", account, 1, ctx)[0],
                         False)
        account["employee_count"] = 9
        self.assertEqual(evaluate_predicate("outside_icp_size", account, 1, ctx),
                         (True, "9"))
        account["employee_count"] = None
        self.assertEqual(evaluate_predicate("outside_icp_size", account, 1, ctx)[0],
                         False, "unknown headcount must not be penalised")
        self.assertEqual(evaluate_predicate("icp_size", account, 1, ctx)[0], False)

    def test_null_industry_never_synthesises_a_fit_reason(self):
        """§8.3 must-not."""
        account = {"industry": None, "employee_count": None, "tech_stack": None,
                   "crm_status": "none", "owner_rep_id": 1}
        ctx = {"account_age_days": 400.0, "total_event_count": 0, "days_silent": None,
               "people_count": 0, "senior_people_count": 0, "owner_name": "Sam"}
        for name in ("icp_industry", "icp_size", "tech_stack_overlap"):
            self.assertFalse(evaluate_predicate(name, account, 1, ctx)[0], name)

    def test_open_opp_owned_elsewhere_only_fires_for_another_rep(self):
        account = {"crm_status": "open_opportunity", "owner_rep_id": 2,
                   "industry": None, "employee_count": None, "tech_stack": None}
        ctx = {"account_age_days": 400.0, "total_event_count": 1, "days_silent": 1.0,
               "people_count": 1, "senior_people_count": 1, "owner_name": "Sam Okafor"}
        self.assertTrue(evaluate_predicate("open_opp_owned_elsewhere", account, 1, ctx)[0])
        self.assertFalse(evaluate_predicate("open_opp_owned_elsewhere", account, 2, ctx)[0])


class TestT18Friction(unittest.TestCase):
    """T18 — requires_evidence_review() is exactly two clauses."""

    def setUp(self):
        self.conn = connect(support.fresh_seeded_db("t18-%s" % self._testMethodName))

    def tearDown(self):
        self.conn.close()

    def test_true_for_an_open_opportunity_owned_by_another_rep(self):
        row = self.conn.execute(
            "SELECT * FROM accounts WHERE crm_status = ? AND owner_rep_id IS NOT NULL "
            "AND owner_rep_id != ? AND is_active = 1 LIMIT 1",
            ("open_opportunity", 1)).fetchone()
        self.assertIsNotNone(row, "no open opportunity owned elsewhere in the corpus")
        self.assertTrue(requires_evidence_review(self.conn, dict(row), None, 1))

    def test_false_for_a_plain_account_with_no_dispute(self):
        row = self.conn.execute(
            "SELECT * FROM accounts WHERE crm_status = ? AND owner_rep_id = ? "
            "AND is_active = 1 LIMIT 1", ("none", 2)).fetchone()
        self.assertIsNotNone(row)
        self.assertFalse(requires_evidence_review(self.conn, dict(row), None, 2))

    def test_true_once_the_rep_has_an_open_dispute_on_the_account(self):
        from warrant.feedback import record_dispute
        row = self.conn.execute(
            "SELECT * FROM accounts WHERE crm_status = ? AND owner_rep_id = ? "
            "AND is_active = 1 LIMIT 1", ("none", 2)).fetchone()
        account = dict(row)
        self.assertFalse(requires_evidence_review(self.conn, account, None, 2))
        signal_type_id = self.conn.execute(
            "SELECT signal_type_id FROM signal_types WHERE code = ?",
            ("pricing_page_repeat",)).fetchone()["signal_type_id"]
        record_dispute(self.conn, 2, account["account_id"], "EVIDENCE_STALE",
                       support.AS_OF, signal_type_id=signal_type_id)
        self.assertTrue(requires_evidence_review(self.conn, account, None, 2))

    def test_friction_applies_to_a_small_minority_of_the_queue(self):
        """§6.4 claims the predicate is true for roughly 4-6% of queue items.
        This asserts the shape (a narrow minority), not the exact figure."""
        _run, items, _adj = build_run(self.conn, 1, support.AS_OF, persist=False)
        flagged = sum(1 for i in items
                      if requires_evidence_review(self.conn, i.score.account, None, 1))
        share = flagged / len(items)
        self.assertLess(share, 0.25,
                        "friction is applied to %.0f%% of the queue — that is "
                        "creep, not a narrow class" % (share * 100))


class TestT17bDisputedLeadSubCases(unittest.TestCase):
    """§8.6 — the three sub-cases of a lead the rep has already disputed."""

    def test_a_new_events_after_a_dispute_do_not_auto_unsuppress(self):
        from warrant.feedback import new_events_since_dispute, record_dispute
        path, conn = support.build_kestrel_db()
        signal_type_id = conn.execute(
            "SELECT signal_type_id FROM signal_types WHERE code = ?",
            ("pricing_page_repeat",)).fetchone()["signal_type_id"]
        dispute_at = shift(support.AS_OF, days=-3)
        record_dispute(conn, 1, support.KESTREL_ACCOUNT_ID, "EVIDENCE_WRONG",
                       dispute_at, signal_type_id=signal_type_id)
        # a new event lands after the dispute
        conn.execute(
            "INSERT INTO signal_events (account_id, person_id, signal_type_id, "
            " occurred_at, observed_at, source, magnitude, detail_json, source_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (support.KESTREL_ACCOUNT_ID, 1, signal_type_id,
             shift(support.AS_OF, days=-1), shift(support.AS_OF, days=-1),
             "website_tracker", 4.0, '{"path": "/pricing", "visits": 4}', None))
        conn.commit()

        count, newest = new_events_since_dispute(
            conn, 1, support.KESTREL_ACCOUNT_ID, signal_type_id, dispute_at,
            support.AS_OF)
        # Two pricing events post-date a dispute made 3 days before as_of: the
        # existing 9 Aug visit and the one just inserted for 10 Aug.
        expected = conn.execute(
            "SELECT COUNT(*) AS n FROM signal_events WHERE account_id = ? "
            "AND signal_type_id = ? AND occurred_at > ? AND occurred_at <= ?",
            (support.KESTREL_ACCOUNT_ID, signal_type_id, dispute_at,
             support.AS_OF)).fetchone()["n"]
        self.assertEqual(count, expected)
        self.assertEqual(count, 2)
        self.assertIsNotNone(newest)

        score = support.kestrel_score(conn)
        by_code = support.contributions_by_code(score)
        self.assertTrue(by_code["pricing_page_repeat"].is_suppressed,
                        "new data silently overrode the rep's own decision")
        self.assertEqual(by_code["pricing_page_repeat"].points, 0.0)
        conn.close()

    def test_b_expired_suppression_is_announced_not_resumed_silently(self):
        from warrant.feedback import expired_dispute_banners, record_dispute
        path, conn = support.build_kestrel_db()
        signal_type_id = conn.execute(
            "SELECT signal_type_id FROM signal_types WHERE code = ?",
            ("pricing_page_repeat",)).fetchone()["signal_type_id"]
        old = shift(support.AS_OF, days=-120)
        record_dispute(conn, 1, support.KESTREL_ACCOUNT_ID, "EVIDENCE_WRONG",
                       old, signal_type_id=signal_type_id)
        score = support.kestrel_score(conn)
        firing = {c.signal_type_id for c in score.contributions}
        banners = expired_dispute_banners(conn, 1, support.KESTREL_ACCOUNT_ID,
                                          support.AS_OF, firing)
        self.assertEqual(len(banners), 1)
        self.assertEqual(banners[0]["display_name"], "Repeat pricing-page visits")
        # and the suppression really has lapsed
        self.assertFalse(support.contributions_by_code(score)["pricing_page_repeat"]
                         .is_suppressed)
        conn.close()


if __name__ == "__main__":
    unittest.main()
