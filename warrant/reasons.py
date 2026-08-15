"""Reason rendering, ranking, truncation and the honest-limits line.

DESIGN_SPEC.md §4.3 (templates), §4.5 (ranking + truncation), §4.6 (limits line).

The templates are hand-authored strings, but every value substituted into them
comes from the same event rows the arithmetic consumed. That is implication #9:
there is no separate "explainer" model. If a reason is on screen, it moved the
score, and by exactly the number printed next to it.
"""

import json

from warrant.scoring import band_from
from warrant.timeutil import (human_date, human_datetime, lag_phrase,
                              relative_phrase)

MAX_SHOWN = 5           # hard ceiling (implication #2)
MAX_SHOWN_POSITIVE = 4  # the 5th slot exists to hold a negative
REASON_FLOOR_TARGET = 3

BAND_LABELS = {
    "ACT_NOW": "ACT NOW",
    "REVIEW": "REVIEW",
    "HOLD": "HOLD",
    # First-person admission, not a category label (§5.4). "Insufficient
    # evidence" reads as a judgement on the account; this reads as a limit on us.
    "INSUFFICIENT_EVIDENCE": "NOT ENOUGH TO SAY",
}

CATEGORY_LABELS = {
    "fit": "FIT",
    "authority": "AUTHORITY",
    "active_evaluation": "ACTIVE EVALUATION",
    "timing": "TIMING",
    "disqualifier": "DISQUALIFIER",
}

SOURCE_LABELS = {
    "website_tracker": "website",
    "product_telemetry": "product telemetry",
    "crm_sync": "crm sync",
    "unify_agent": "unify agent",
    "6sense": "6sense",
    "job_change_feed": "job change feed",
    "email_platform": "email platform",
    "funding_feed": "funding feed",
    "enrichment": "enrichment",
}

NO_SIGNALS_LINE = (
    "We have no signals for this account. It is here because it is assigned "
    "to you, not because we think it is a priority."
)


def band_label(band):
    return BAND_LABELS[band]


def humanise_sources(source_names):
    return ", ".join(SOURCE_LABELS.get(s, s) for s in source_names)


def plural(count, suffix="s"):
    return "" if count == 1 else suffix


def points_label(points, cap_applied=False, max_contribution=None):
    """'+24 pts (capped at 24)' / '+15 pts' / '−7 pts' (§6.2).

    Integer rounding on screen; the two-decimal value stays in the DB and
    appears in the evidence drawer.
    """
    rounded = int(round(abs(points)))
    sign = "−" if points < 0 else "+"
    text = "%s%d pts" % (sign, rounded)
    if cap_applied and max_contribution is not None:
        text += " (capped at %d)" % int(round(abs(max_contribution)))
    return text


def _template_vars(contribution, account, as_of, ctx_extra):
    """Every variable named in DESIGN_SPEC.md §4.3, plus the plural helpers the
    templates in that same table use."""
    person = contribution.top_person or {}
    path = ""
    if contribution.events:
        top = max(contribution.events, key=lambda c: (abs(c.contribution), -c.event_id))
        path = top.detail.get("path", "") or ""
    total_magnitude = int(sum(e.magnitude for e in contribution.events)) if contribution.events else 0

    return {
        "account_name": account["name"],
        "top_person_title": person.get("title", "Someone"),
        "top_person_name": person.get("full_name", "Someone"),
        "event_count": contribution.event_count,
        "event_plural": plural(contribution.event_count),
        "other_user_count": contribution.other_user_count,
        "other_plural": plural(contribution.other_user_count),
        "total_magnitude": total_magnitude,
        "newest_date": human_date(contribution.newest_event_at),
        "newest_relative": relative_phrase(as_of, contribution.newest_event_at),
        "oldest_date": human_date(contribution.oldest_event_at),
        "path": path or "a product page",
        "source_list": humanise_sources(contribution.source_names),
        "field_value": contribution.field_value,
        "refreshed_date": human_date(account["data_last_refreshed_at"]),
        "owner_name": ctx_extra.get("owner_name", "another rep"),
        "days_silent": contribution.field_value or "0",
        "people_count": ctx_extra.get("people_count", 0),
    }


class RenderedReason:
    """A ranked, rendered reason. `points` is the effective contribution and is
    the column T07 sums against scores.points."""

    def __init__(self, contribution, text, evidence_summary, rank, shown,
                 share_of_abs_total):
        self.contribution = contribution
        self.signal_type_id = contribution.signal_type_id
        self.code = contribution.code
        self.display_name = contribution.display_name
        self.category = contribution.category
        self.polarity = contribution.polarity
        self.points = contribution.points
        self.points_before_adjustment = contribution.points_before_adjustment
        self.cap_applied = contribution.cap_applied
        self.is_suppressed = contribution.is_suppressed
        self.text = text
        self.evidence_summary = evidence_summary
        self.rank = rank
        self.shown = shown
        self.share_of_abs_total = share_of_abs_total
        self.newest_event_at = contribution.newest_event_at
        self.oldest_event_at = contribution.oldest_event_at
        self.event_count = contribution.event_count
        self.source_names = contribution.source_names


def render_reason_text(conn, contribution, account, as_of, ctx_extra):
    row = conn.execute(
        "SELECT reason_template, evidence_template FROM signal_types WHERE signal_type_id = ?",
        (contribution.signal_type_id,),
    ).fetchone()
    variables = _template_vars(contribution, account, as_of, ctx_extra)
    return (row["reason_template"].format(**variables),
            row["evidence_template"].format(**variables))


def rank_reasons(contributions):
    """§4.5 ranking: abs(points) DESC, then newest_event_at DESC, then
    signal_type_id ASC.

    Ranks on points_before_adjustment so a reason the rep disputed keeps its
    slot instead of being silently backfilled (§7.4).
    """
    return sorted(
        contributions,
        key=lambda c: (-abs(c.points_before_adjustment),
                       _invert_ts(c.newest_event_at),
                       c.signal_type_id),
    )


def _invert_ts(ts):
    """Sort key that puts the newest timestamp first for an ascending sort."""
    return tuple(-ord(ch) for ch in ts)


def select_shown(ranked):
    """§4.5 truncation rule, implemented in the spec's own step order.

    Step 2 runs before step 3 by design: negatives take their reserved slots
    even when weaker than the 4th and 5th positives (implication #7).
    """
    positives = [c for c in ranked if c.polarity == "positive"]
    negatives = [c for c in ranked if c.polarity == "negative"]

    shown = list(positives[:3])                                   # step 1
    shown += negatives[:2]                                        # step 2
    if len(shown) < MAX_SHOWN:                                    # step 3
        need = MAX_SHOWN - len(shown)
        shown += positives[3:3 + need]
        while len([c for c in shown if c.polarity == "positive"]) > MAX_SHOWN_POSITIVE:
            worst = min((c for c in shown if c.polarity == "positive"),
                        key=lambda c: abs(c.points_before_adjustment))
            shown.remove(worst)
    assert len(shown) <= MAX_SHOWN
    # Step 4: no padding. If fewer than 3 reasons exist above the floor we show
    # what there is; confidence is already low or insufficient by §8.7.
    shown_ids = {id(c) for c in shown}
    return [c for c in ranked if id(c) in shown_ids]


def build_reasons(conn, score, ctx_extra):
    """Rank, truncate and render. Returns (all_reasons, shown_reasons)."""
    ranked = rank_reasons(score.contributions)
    shown_set = {id(c) for c in select_shown(ranked)}
    abs_total = sum(abs(c.points) for c in ranked)

    rendered = []
    for index, contribution in enumerate(ranked, start=1):
        text, evidence = render_reason_text(
            conn, contribution, score.account, score.as_of, ctx_extra)
        share = (abs(contribution.points) / abs_total) if abs_total else 0.0
        rendered.append(RenderedReason(
            contribution=contribution,
            text=text,
            evidence_summary=evidence,
            rank=index,
            shown=1 if id(contribution) in shown_set else 0,
            share_of_abs_total=round(share, 6),
        ))
    return rendered, [r for r in rendered if r.shown]


def build_limits_line(score, all_reasons, shown_reasons):
    """§4.6. Two variants plus the §8.3 empty case, selected mechanically."""
    if not all_reasons:
        return "No signals found."

    shown_points = round(sum(r.points for r in shown_reasons), 2)
    withheld = [r for r in all_reasons if not r.shown]
    n = len(all_reasons)
    k = len(shown_reasons)
    m = len(withheld)

    if not withheld:
        line = "These are all %d signals we found for this account." % n
    else:
        withheld_sum = round(sum(r.points for r in withheld), 2)
        band_if_shown_only = band_from(shown_points, score.confidence)
        if band_if_shown_only == score.band:
            line = ("Showing the %d strongest of %d signals. The %d not shown are "
                    "worth %+.1f pts combined; they do not change the band."
                    % (k, n, m, withheld_sum))
        else:
            line = ("Showing the %d strongest of %d signals. The %d not shown are worth "
                    "%+.1f pts combined and are part of why this is %s — "
                    "the %d shown alone would rate %s."
                    % (k, n, m, withheld_sum, band_label(score.band), k,
                       band_label(band_if_shown_only)))

    if score.suppressed_display_names:
        names = ", ".join('"%s"' % nm for nm in score.suppressed_display_names)
        line += " Suppressed by you: %s." % names
    return line


def compressed_limits(all_reasons, shown_reasons):
    """Queue-row form: '5 of 10 signals shown' (§6.1)."""
    n = len(all_reasons)
    if n == 0:
        return "no signals"
    return "%d of %d signal%s shown" % (len(shown_reasons), n, plural(n))


def conflict_line(score, all_reasons):
    """§8.5. Template: 'These signals disagree. {top_positive_short}, but
    {top_negative_short}. Read both before you act.'"""
    if not score.conflicted:
        return None
    positives = [r for r in all_reasons if r.points > 0]
    negatives = [r for r in all_reasons if r.points < 0]
    if not positives or not negatives:
        return None
    top_pos = max(positives, key=lambda r: r.points)
    top_neg = min(negatives, key=lambda r: r.points)
    return ("These signals disagree. %s, but %s. Read both before you act."
            % (_short(top_pos.text), _short(top_neg.text)))


def _short(text):
    """First clause of a reason sentence.

    Deliberately does NOT lowercase the leading word: reason templates often
    start with a person's name, and "but noor Belic, our contact here, left"
    reads as a typo to the rep and undermines the sentence.
    """
    return text.split(".")[0].strip()


def thin_data_line(score):
    """§8.1 — the only forward-looking copy in the product."""
    if score.confidence != "insufficient":
        return None
    parts = []
    n = score.distinct_signal_types
    if n == 0:
        return NO_SIGNALS_LINE
    parts.append("We have %d signal%s for this account" % (n, plural(n)))
    if score.senior_people_count == 0:
        parts.append("and no contact at director level or above")
    return " ".join(parts) + ". Not enough to rank it."


def what_would_change_line(score):
    if score.confidence != "insufficient":
        return None
    return ("What would change this: a named contact at director level or above, "
            "or any product or website activity.")


def stale_line(score):
    """§8.2 banner above the reasons."""
    if score.freshest_evidence_at is None:
        return None
    from warrant.timeutil import age_days
    days = int(age_days(score.as_of, score.freshest_evidence_at))
    if days <= 30:
        return None
    return ("No new evidence in %d days. This ranking reflects activity that "
            "ended on %s." % (days, human_date(score.freshest_evidence_at)))


def brand_new_line(score):
    """§8.4 banner."""
    days = int(score.account_age_days)
    if days >= 14:
        return None
    return ("First seen %s. We may be missing history that would change this."
            % ("today" if days == 0 else "%d day%s ago" % (days, plural(days))))


def freshness_chip(score):
    """§6.1 freshness chip: 'evidence 2d old' / 'STALE · 47d' / 'no evidence'."""
    if score.freshest_evidence_at is None:
        return "no evidence"
    from warrant.timeutil import age_days
    days = int(age_days(score.as_of, score.freshest_evidence_at))
    if days > 30:
        return "STALE · %dd" % days
    return "evidence %dd old" % days


def adjustment_chip(score):
    """§6.1 adjustment chip, present only when adjustment_flags is non-empty."""
    flags = score.adjustment_flags
    if not flags:
        return None
    if "pinned" in flags:
        return "PINNED BY YOU"
    if "demoted" in flags:
        return "DEMOTED BY YOU"
    suppressed = len(score.suppressed_display_names)
    if "suppressed" in flags and suppressed:
        return "ADJUSTED · %d signal%s suppressed" % (suppressed, plural(suppressed))
    if "excluded_person" in flags:
        return "ADJUSTED · 1 person excluded"
    return "ADJUSTED"


def truncate_at_word(text, limit=120):
    """§6.1 top-reason truncation: 120 chars at a word boundary with an ellipsis."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > 0:
        cut = cut[:space]
    return cut.rstrip(" ,.;:") + "…"


def source_names_json(reason):
    return json.dumps(reason.source_names)


# ---------------------------------------------------------------------------
# Strings extracted down out of render.py so the HTML path and the JSON path
# share one copy (DEPLOY_ARCHITECTURE.md §2.5).
#
# §2.5 mandates two extractions by name: the budget sentence (which went to
# queue.py) and the rank line. The remaining functions below are the same move
# applied to the rest of the verdict strip and the evidence drawer, because
# §10.3 open question 1 recommends that warrant/api.py never import
# warrant/render.py, and every one of these strings is rep-facing. Extracting
# them is the only way to satisfy both "one copy of every sentence" and "no
# HTML module inside the JSON path".
#
# Every function here returns the byte-identical string render.py produced
# before the extraction. Proved by rendering all 76 HTML views before and after
# and comparing sha256 per view; see DEPLOY_TEST_OUTPUT.md.
# ---------------------------------------------------------------------------

BAND_THRESHOLD_TEXT = {
    "ACT_NOW": "45",
    "REVIEW": "25",
    "HOLD": "5",
    "INSUFFICIENT_EVIDENCE": "not set — this is a data gap",
}

SOURCE_LINK_NOTE = ("Source links are shown as text — this environment has no "
                    "outbound network.")

NO_REFERENCE = "no reference"


def points_display(points):
    """§5.1: rounded integer, sign only when negative. 59.87 -> 60."""
    return "%d" % int(round(points))


def band_threshold_text(band):
    return BAND_THRESHOLD_TEXT[band]


def anchor_note(band):
    """'bar for ACT NOW is 45 · scale anchored at 75' (§6.2)."""
    return ("bar for %s is %s · scale anchored at 75"
            % (band_label(band), band_threshold_text(band)))


def above_anchor_note(score):
    """' (above anchor)' or ''. The anchor is used in no arithmetic (§5.3)."""
    return " (above anchor)" if score.points > 75 else ""


def rank_line(item, total_accounts):
    """'rank 1 of 53 (was 3 before your adjustments)' — §2.5's second mandated
    extraction. render.render_detail called this inline before."""
    line = "rank %d of %d" % (item.rank_in_queue, total_accounts)
    if item.rank_before_adjustment != item.rank_in_queue:
        line += " (was %d before your adjustments)" % item.rank_before_adjustment
    return line


def adjusted_note(score):
    """'was 60 pts before your disagreement', or None."""
    if abs(score.points - score.points_before_adjustment) > 0.005:
        return ("was %s pts before your disagreement"
                % points_display(score.points_before_adjustment))
    return None


def suppressed_points_label(reason):
    """'+15 → 0 pts' for a reason the rep disputed (§7.4).

    The reason keeps its slot and its original value is still shown, because
    silently backfilling the slot would make the disagreement feel unregistered.
    """
    return "%s → 0 pts" % points_label(reason.points_before_adjustment)


def detail_heading(item):
    """'Why this is at the top' only at the top (README deviation 12)."""
    if item.rank_in_queue <= 3:
        return "Why this is at the top"
    return "Why this ranked %d" % item.rank_in_queue


def account_meta_line(account, owner_label):
    """'Data & Analytics · 420 employees · US · CRM: no record · owner: you'."""
    return "%s · %s · %s · CRM: %s · owner: %s" % (
        account["industry"] or "industry unknown",
        ("%s employees" % account["employee_count"]
         if account["employee_count"] is not None else "headcount unknown"),
        account["hq_country"],
        "no record" if account["crm_status"] == "none" else account["crm_status"],
        owner_label)


def expired_dispute_line(banner):
    """§8.6(b): the suppression expired and the signal is counting again."""
    return ("You said \"%s\" was wrong here on %s. That suppression expired on "
            "%s and the signal is counting again."
            % (banner["display_name"], human_date(banner["created_at"]),
               human_date(banner["expires_at"])))


def history_line(row):
    """One row of 'Your history on this account'."""
    line = "%s · you said %s" % (
        human_date(row["created_at"]),
        ('"%s" was wrong.' % row["signal_display_name"]
         if row["signal_display_name"] else "%s." % _code_label(row["code"]).lower()))
    if row["adj_expires_at"]:
        state = "active until" if row["adj_is_active"] else "expired"
        line += " %s %s %s." % (row["adj_kind"], state,
                                human_date(row["adj_expires_at"]))
    return line


def _code_label(code):
    from warrant.feedback import CODE_LABELS
    return CODE_LABELS[code]


# --- evidence drawer (§6.3) -------------------------------------------------

def evidence_header(reason, account):
    """'Evidence · Repeat pricing-page visits · Kestrel Analytics' (§6.3)."""
    return "Evidence · %s · %s" % (reason["display_name"], account["name"])


def evidence_summary_line(reason, as_of):
    """'Reason computed 11 Aug 2026 09:00 UTC from 2 events. Total +14.95 pts
    (cap +18.00).'"""
    return ("Reason computed %s from %d event%s. Total %+.2f pts (cap %+.2f)."
            % (human_datetime(as_of), reason["event_count"],
               plural(reason["event_count"]), reason["points"],
               reason["max_contribution"]))


def evidence_contribution_display(event):
    return "%+.2f pts" % event["contribution"]


def evidence_magnitude_display(event):
    return "magnitude %s" % ("%g" % event["magnitude"])


def evidence_detail_display(event):
    return event["detail_json"] or ""


def evidence_person_display(event):
    if event["full_name"]:
        return "person: %s, %s" % (event["full_name"], event["title"])
    return "person: no person on this event"


def evidence_source_display(event):
    return ("source: %s · ingested %s (%s)"
            % (event["source"], human_datetime(event["observed_at"]),
               lag_phrase(event["occurred_at"], event["observed_at"])))


def evidence_ref_display(event):
    """Rendered as selectable text, never as an anchor (README limitation 11).
    There is no outbound network here and a link that 404s in a demo is worse
    than no link."""
    return "ref: %s" % (event["source_url"] or NO_REFERENCE)


EVIDENCE_STATE_INTRO = ("This reason is a state of the account record, not an "
                        "event. It was read from the account fields shown below.")


def evidence_refreshed_display(account):
    return "account record last refreshed %s" % human_date(
        account["data_last_refreshed_at"])


def evidence_state_fallback(reason, account):
    """kind='state' reasons have no reason_evidence rows (§3.9).

    The HTML drawer renders these three parts as three block elements; the JSON
    path gets the same three sentences joined, so both say the same thing and
    neither owns a copy the other does not have.
    """
    return " · ".join([EVIDENCE_STATE_INTRO, reason["evidence_summary"],
                       evidence_refreshed_display(account)])


def observation_retrieved_display(observation):
    return "retrieved %s" % human_date(observation["retrieved_at"])


def observation_agent_run_display(observation):
    return "agent run %s" % observation["agent_run_id"]


def observations_count_line(observations):
    return "%d observation(s). %s" % (len(observations), SOURCE_LINK_NOTE)


def research_heading(observations):
    if not observations:
        return "Agent research"
    return "Agent research (%d observations)" % len(observations)


def queue_header_line(rep):
    """'Warrant · Dana Whitfield · NA-MidMarket' (§6.1)."""
    return "Warrant · %s · %s" % (rep["name"], rep["territory"])


def run_stamp(as_of, ruleset, account_count, run_id):
    """'Scored 11 Aug 2026, 09:00 UTC · ruleset warrant-v1.0.0 · 53 accounts ·
    run #41' (§6.1)."""
    return ("Scored %s · ruleset %s · %d accounts · run #%s"
            % (human_datetime(as_of), ruleset, account_count, run_id))


def thin_banner_text(score):
    """§8.1's two sentences as one paragraph, for the JSON banner.

    The HTML path renders the same two sentences as two lines inside one
    banner. Same sentences, same source functions, different separator — the
    separator is layout and belongs to the transport.
    """
    thin = thin_data_line(score)
    if not thin:
        return None
    return " ".join([thin, what_would_change_line(score) or ""]).strip()


def no_signals_text(score):
    """§8.3's block when an account has no reasons at all."""
    return " ".join([NO_SIGNALS_LINE, what_would_change_line(score) or ""]).strip()


def weight_display(value):
    """'+12.0' / '−7.0' as printed on /ruleset."""
    return "%+.1f" % value


def half_life_display(signal_type):
    """The /ruleset half-life cell: '14', or '—' for a state signal."""
    if not signal_type["half_life_days"]:
        return "—"
    return "%g" % signal_type["half_life_days"]


# --- published ruleset copy (§6.5) ------------------------------------------
# Moved down out of render.py so the JSON path can serve the same sentences
# without importing the HTML module (§10.3 open question 1).

RULESET_HEADER = ("This is how the weights are set, and how often reps disagree "
                  "with each one. It is not why any particular account ranked "
                  "where it did — that is on the account's own page.")

ANCHOR_NOTE = ("75 is the point total a strong, current, multi-signal account "
               "reaches. It is a fixed bar set by RevOps, not a maximum and not "
               "a percentile. An account can exceed it.")

WEIGHTS_NOTE = ("product_usage_active carries the highest positive weight because "
                "Unify's own published benchmark puts product usage signals at a "
                "9.1% positive reply rate, the highest-performing signal type. The "
                "other 18 weights are reasoned, not measured: v1 ships weights that "
                "are defensible rather than validated, and /metrics is the "
                "instrument for correcting them.")

NOT_CLAIMED = ("This is not a probability of closing. It is not calibrated "
               "against closed-won outcomes, because there is no outcome data "
               "here to calibrate against. It is a weighted count of evidence, "
               "and every point of it is on the account's own page.")

# --- the adjustments list (§7.3) --------------------------------------------

def adjustment_line(row):
    """'suppress_signal_type · Kestrel Analytics · "Repeat pricing-page visits"'."""
    line = "%s%s" % (row["kind"],
                     (" · %s" % row["account_name"]) if row["account_name"]
                     else " · patch-wide")
    if row["signal_display_name"]:
        line += " · \"%s\"" % row["signal_display_name"]
    return line


def adjustment_state(row):
    if row["is_active"]:
        return "active"
    return "reverted" if row["reverted_at"] else "expired"


def adjustment_created_display(row):
    return "created %s" % human_date(row["created_at"])


def adjustment_expires_display(row):
    """'active until 9 Nov 2026' / 'expired 9 Nov 2026' / 'reverted — was until
    9 Nov 2026'. The HTML table splits date and state into two columns; the JSON
    row carries one sentence because a list item has no column headers."""
    when = human_date(row["expires_at"])
    state = adjustment_state(row)
    if state == "active":
        return "active until %s" % when
    if state == "reverted":
        return "reverted — was until %s" % when
    return "expired %s" % when


RESEARCH_PREVIEW = 3     # observations shown inline before "see all research"
RESEARCH_EMPTY_NOTE = "No agent observations for this account yet."
HISTORY_EMPTY_NOTE = "Nothing yet."
WRONG_PERSON_UNAVAILABLE_NOTE = ("\"Wrong person\" is not available here — no "
                                 "contact is on file for this account.")
