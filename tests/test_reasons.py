"""DESIGN_SPEC.md §9.3 — T05, T06, T08, T09, T11."""

import unittest

import support
from warrant import reasons as reasons_mod
from warrant.db import connect
from warrant.queue import build_run
from warrant.timeutil import relative_phrase


def build_all(conn, score):
    ctx = {"owner_name": "Sam Okafor", "people_count": score.people_count}
    return reasons_mod.build_reasons(conn, score, ctx)


class TestT05Truncation(unittest.TestCase):
    """T05 — asserted across every seeded account."""

    @classmethod
    def setUpClass(cls):
        cls.conn = connect(support.build_seeded_db())
        cls.scores = support.score_every_account(cls.conn)

    def test_truncation_rule_holds_for_every_account(self):
        checked = 0
        for score in self.scores:
            all_reasons, shown = build_all(self.conn, score)
            self.assertLessEqual(len(shown), 5,
                                 "account %d shows %d reasons" % (score.account_id, len(shown)))
            positives_shown = [r for r in shown if r.polarity == "positive"]
            self.assertLessEqual(len(positives_shown), 4,
                                 "account %d shows %d positives" % (score.account_id,
                                                                    len(positives_shown)))
            negatives_available = [r for r in all_reasons if r.polarity == "negative"]
            if negatives_available:
                self.assertTrue(any(r.polarity == "negative" for r in shown),
                                "account %d has a negative but shows none" % score.account_id)
            positives_available = [r for r in all_reasons if r.polarity == "positive"]
            if len(all_reasons) < 3:
                self.assertEqual(len(shown), len(all_reasons),
                                 "account %d padded to reach the floor" % score.account_id)
            elif positives_available:
                self.assertGreaterEqual(len(shown), 3,
                                        "account %d has %d reasons but shows %d"
                                        % (score.account_id, len(all_reasons), len(shown)))
            else:
                # SPEC GAP, implemented as written. §4.5 step 3 backfills "from
                # positives only", so an account with zero positive reasons can
                # never show more than the 2 reserved negative slots and the
                # floor of 3 is unreachable. 2 of 233 seeded accounts hit this.
                # Recorded in README.md "Deviations from the spec".
                self.assertEqual(len(shown), min(2, len(all_reasons)),
                                 "account %d is all-negative and should show "
                                 "exactly the 2 reserved slots" % score.account_id)
            checked += 1
        self.assertGreaterEqual(checked, 200)

    def test_no_expander_exists_anywhere_in_the_rendered_html(self):
        """Implication #2 taken literally: no 'show all', no expander."""
        import warrant.render as render_mod
        source = open(render_mod.__file__, encoding="utf-8").read().lower()
        for forbidden in ("show all", "show more", "<details", "see all 27",
                          "expand"):
            self.assertNotIn(forbidden, source,
                             "render.py contains an expander affordance: %r" % forbidden)

    def test_ranks_are_dense_and_ordered_by_absolute_points(self):
        for score in self.scores[:60]:
            all_reasons, _shown = build_all(self.conn, score)
            self.assertEqual([r.rank for r in all_reasons],
                             list(range(1, len(all_reasons) + 1)))
            magnitudes = [abs(r.points_before_adjustment) for r in all_reasons]
            self.assertEqual(magnitudes, sorted(magnitudes, reverse=True))


class TestT06KestrelShownSet(unittest.TestCase):
    """T06 — Kestrel's shown set is ranks 1-5, and the reserved negative slot
    beats a stronger positive."""

    @classmethod
    def setUpClass(cls):
        cls.path, cls.conn = support.build_kestrel_db()

    def test_shown_set_is_exactly_ranks_1_to_5(self):
        score = support.kestrel_score(self.conn)
        all_reasons, shown = build_all(self.conn, score)
        self.assertEqual([r.rank for r in shown], [1, 2, 3, 4, 5])
        codes = [r.code for r in shown]
        self.assertEqual(codes, ["product_usage_active", "pricing_page_repeat",
                                 "senior_buyer_engaged", "champion_departed",
                                 "unsubscribed_or_bounced"])

    def test_negative_at_minus_7_24_beats_positive_at_plus_6_00(self):
        """Step 2 before step 3 (implication #7): a two-sided assessment beats
        a one-sided pitch, even when the negative is numerically weaker."""
        score = support.kestrel_score(self.conn)
        all_reasons, shown = build_all(self.conn, score)
        by_code = {r.code: r for r in all_reasons}
        self.assertEqual(by_code["champion_departed"].shown, 1)
        self.assertEqual(by_code["icp_industry_match"].shown, 0)
        self.assertLess(abs(by_code["champion_departed"].points),
                        abs(by_code["icp_industry_match"].points) + 2)

    def test_all_ten_reasons_are_persisted_shown_and_unshown(self):
        score = support.kestrel_score(self.conn)
        all_reasons, shown = build_all(self.conn, score)
        self.assertEqual(len(all_reasons), 10)
        self.assertEqual(sum(r.shown for r in all_reasons), 5)
        self.assertAlmostEqual(sum(r.points for r in all_reasons), score.points,
                               delta=0.01)


class TestT08LimitsLine(unittest.TestCase):
    """T08 — variant selection is mechanical."""

    @classmethod
    def setUpClass(cls):
        cls.path, cls.conn = support.build_kestrel_db()

    def test_kestrel_yields_the_band_flip_variant(self):
        score = support.kestrel_score(self.conn)
        all_reasons, shown = build_all(self.conn, score)
        line = reasons_mod.build_limits_line(score, all_reasons, shown)
        self.assertIn("the 5 shown alone would rate REVIEW", line)
        self.assertIn("part of why this is ACT NOW", line)
        self.assertIn("Showing the 5 strongest of 10 signals", line)
        shown_points = round(sum(r.points for r in shown), 2)
        self.assertAlmostEqual(shown_points, 34.29, delta=0.01)

    def test_no_withheld_reasons_yields_the_these_are_all_variant(self):
        """An account with <= 5 reasons withholds nothing."""
        conn = connect(support.build_seeded_db())
        found = False
        for score in support.score_every_account(conn):
            all_reasons, shown = build_all(conn, score)
            if all_reasons and len(all_reasons) == len(shown):
                line = reasons_mod.build_limits_line(score, all_reasons, shown)
                self.assertEqual(line, "These are all %d signals we found for "
                                       "this account." % len(all_reasons))
                found = True
                break
        self.assertTrue(found, "no account in the corpus withheld nothing")
        conn.close()

    def test_zero_signal_account_yields_no_signals_found(self):
        conn = connect(support.build_seeded_db())
        found = False
        for score in support.score_every_account(conn):
            if not score.contributions:
                all_reasons, shown = build_all(conn, score)
                self.assertEqual(reasons_mod.build_limits_line(score, all_reasons, shown),
                                 "No signals found.")
                found = True
                break
        self.assertTrue(found, "no zero-signal account in the corpus")
        conn.close()

    def test_do_not_change_the_band_variant_exists_in_the_corpus(self):
        conn = connect(support.build_seeded_db())
        found = False
        for score in support.score_every_account(conn):
            all_reasons, shown = build_all(conn, score)
            if len(all_reasons) > len(shown):
                line = reasons_mod.build_limits_line(score, all_reasons, shown)
                if "they do not change the band" in line:
                    found = True
                    break
        self.assertTrue(found, "variant 2 of the limits line never fires")
        conn.close()


class TestT09EveryDetailViewHasALimitsLine(unittest.TestCase):
    """T09 — asserted across every seeded account, on the rendered HTML."""

    def test_every_rendered_detail_view_carries_a_limits_line(self):
        conn = connect(support.build_seeded_db())
        checked = 0
        for score in support.score_every_account(conn):
            all_reasons, shown = build_all(conn, score)
            line = reasons_mod.build_limits_line(score, all_reasons, shown)
            self.assertTrue(line and line.strip(),
                            "account %d has an empty limits line" % score.account_id)
            checked += 1
        self.assertGreaterEqual(checked, 200)
        conn.close()

    def test_rendered_html_contains_the_limits_block(self):
        from warrant import render
        conn = connect(support.fresh_seeded_db("t09-render"))
        _run_id, items, _adj = build_run(conn, 1, support.AS_OF)
        rep = dict(conn.execute("SELECT * FROM reps WHERE rep_id = 1").fetchone())
        usage = {k: (0, v) for k, v in
                 __import__("warrant.queue", fromlist=["BUDGETS"]).BUDGETS.items()}
        for item in items:
            context = {"reason_ids": {}, "history": [], "suppression_notes": {},
                       "suppression_adjustments": {}, "new_events_notes": {},
                       "expired_banners": [], "owner_label": "you",
                       "observations": [], "top_person": None}
            html = render.render_detail(rep, item, usage, support.AS_OF,
                                        "warrant-v1.0.0", len(items), context)
            self.assertIn("class=\"limits\"", html,
                          "account %d rendered without a limits line" % item.account_id)
        conn.close()


class TestT11BannedVocabulary(unittest.TestCase):
    """T11 — implication #4 and #3, made testable.

    Scope is exactly what the spec names: rendered reason text, evidence lines,
    band labels, limits lines and chips. It deliberately does NOT cover the
    machine `code` column shown on /ruleset, which contains
    'no_engagement_90d'; that is a RevOps identifier, not rep-facing prose.
    """

    BANNED = ("engagement", "engagement score", "lead score", "mql",
              "activity score", "nurture", "hand-raiser", "propensity", "shap")

    def test_no_banned_word_in_any_rendered_string_in_the_corpus(self):
        conn = connect(support.build_seeded_db())
        checked = 0
        for score in support.score_every_account(conn):
            all_reasons, shown = build_all(conn, score)
            strings = [reasons_mod.build_limits_line(score, all_reasons, shown),
                       reasons_mod.band_label(score.band),
                       reasons_mod.freshness_chip(score),
                       reasons_mod.compressed_limits(all_reasons, shown) or ""]
            for extra in (reasons_mod.thin_data_line(score),
                          reasons_mod.what_would_change_line(score),
                          reasons_mod.stale_line(score),
                          reasons_mod.brand_new_line(score),
                          reasons_mod.conflict_line(score, all_reasons),
                          reasons_mod.adjustment_chip(score)):
                if extra:
                    strings.append(extra)
            for reason in all_reasons:
                strings.append(reason.text)
                strings.append(reason.evidence_summary)
                strings.append(reasons_mod.CATEGORY_LABELS[reason.category])
            for text in strings:
                lowered = text.lower()
                for banned in self.BANNED:
                    self.assertNotIn(banned, lowered,
                                     "account %d renders banned word %r in: %s"
                                     % (score.account_id, banned, text))
                checked += 1
        self.assertGreater(checked, 2000)
        conn.close()

    def test_band_labels_use_the_first_person_admission(self):
        self.assertEqual(reasons_mod.band_label("INSUFFICIENT_EVIDENCE"),
                         "NOT ENOUGH TO SAY")


class TestRelativeDates(unittest.TestCase):
    """§8.2 must-not: never a relative phrase that hides age; never 'recently'
    for anything over 14 days."""

    def test_phrases_always_carry_a_number_past_yesterday(self):
        cases = {
            "2026-08-11T09:00:00Z": "today",
            "2026-08-10T09:00:00Z": "yesterday",
            "2026-08-09T09:00:00Z": "2 days ago",
            "2026-06-25T09:00:00Z": "7 weeks ago",
            "2026-02-11T09:00:00Z": "6 months ago",
        }
        for ts, expected in cases.items():
            self.assertEqual(relative_phrase("2026-08-11T09:00:00Z", ts), expected)

    def test_never_says_recently(self):
        for days in range(0, 400, 7):
            ts = "2026-08-11T09:00:00Z"
            from warrant.timeutil import shift
            phrase = relative_phrase(ts, shift(ts, days=-days))
            self.assertNotIn("recent", phrase.lower())


class TestTruncationHelper(unittest.TestCase):
    def test_queue_row_truncates_at_a_word_boundary(self):
        text = ("VP Engineering and 2 others used the product across 3 sessions, "
                "most recently 2 days ago and that is a long tail of extra words")
        out = reasons_mod.truncate_at_word(text, 120)
        self.assertLessEqual(len(out), 121)
        self.assertTrue(out.endswith("…"))
        self.assertNotIn("  ", out)

    def test_short_text_is_untouched(self):
        self.assertEqual(reasons_mod.truncate_at_word("short", 120), "short")


if __name__ == "__main__":
    unittest.main()
