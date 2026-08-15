"""Ordering, persistence of a run, and budget enforcement.

DESIGN_SPEC.md §4.2 (ordering), §3.7/§3.8/§3.9 (persistence), §7.3 (budgets).

Three invariants this module holds, all tested:
  1. No adjustment is permanent — expires_at is NOT NULL and expiry is
     evaluated at read time against as_of. There is no cron here.
  2. No adjustment crosses reps — every query below filters rep_id = ?.
  3. No adjustment changes the ruleset — nothing here writes signal_types.
"""

import json

from warrant import reasons as reasons_mod
from warrant.db import ANCHOR_POINTS, ruleset_version
from warrant.scoring import AdjustmentSet, load_active_adjustments, score_queue
from warrant.timeutil import human_date

# §7.3 — deliberately tight. Dietvorst et al. found the adoption effect held
# even when modification was severely restricted, which licenses small budgets.
BUDGETS = {
    "pin": 5,
    "demote": 10,
    "mute_account": 25,
    "suppress_signal_type_global": 3,
    "suppress_signal_type_account": 50,
    "exclude_person": 50,
}

BUDGET_LABELS = {
    "pin": "pins",
    "demote": "demotes",
    "mute_account": "muted accounts",
    "suppress_signal_type_global": "patch-wide signal suppressions",
    "suppress_signal_type_account": "account-scoped signal suppressions",
    "exclude_person": "excluded people",
}


class BudgetExceeded(Exception):
    """Raised instead of silently dropping the oldest adjustment.

    A budget the rep can exceed without noticing is not a bound, and a lever
    that quietly discards the rep's input is worse than no lever (§7.3).
    """

    def __init__(self, key, active, limit, oldest_expiry=None):
        super().__init__("%s budget exceeded: %d/%d" % (key, active, limit))
        self.key = key
        self.active = active
        self.limit = limit
        self.oldest_expiry = oldest_expiry


def budget_exceeded_message(exc):
    """The 409 sentence, extracted down out of render.py per §2.5.

    render.render_budget_exceeded() now calls this and wraps it in HTML; the
    JSON error path calls it directly. One sentence, two transports.

    NOTE — the string is exactly what render.py produced before the extraction,
    not the variant printed in DEPLOY_ARCHITECTURE.md §3.3 ("...or unpin one
    now"). §2.5 says the extraction "changes no rendered output" and §10.1 item
    8 says no rendered sentence changes in this port, so the implemented copy
    wins over the illustrative copy in the design document. Flagged in
    DEPLOY_TEST_OUTPUT.md rather than silently reconciled.
    """
    label = BUDGET_LABELS[exc.key]
    expiry = (" — your oldest expires on %s" % human_date(exc.oldest_expiry)
              if exc.oldest_expiry else "")
    return ("You already have %d %s. They expire on their own%s — or undo one now."
            % (exc.limit, label, expiry))


BUDGET_EXCEEDED_TITLE = "Budget reached"

# The four budgets shown on the queue bar, and the three shown on the detail
# view's adjust block. Order is load-bearing: it is the order both paths print.
BUDGET_BAR_KEYS = ("pin", "demote", "suppress_signal_type_global", "mute_account")
ADJUST_BLOCK_KEYS = ("pin", "demote", "mute_account")


def budget_counts_line(usage, keys):
    """'pins 2/5 · demotes 1/10 · muted accounts 4/25'. One copy, two paths."""
    return " · ".join("%s %d/%d" % (BUDGET_LABELS[key], usage[key][0], usage[key][1])
                      for key in keys)


def budget_bar_text(usage):
    return budget_counts_line(usage, BUDGET_BAR_KEYS)


# The three adjust controls, as (kind, days, label). One definition, so the
# HTML buttons and the JSON `adjust.buttons` cannot offer different windows.
ADJUST_BUTTONS = (
    ("pin", 14, "Pin to top · 14 days"),
    ("demote", 30, "Demote · 30 days"),
    ("mute_account", 60, "Mute · 60 days"),
)


def adjust_confirmation(kind, expires_at, tail=""):
    """§3.13 POST /api/adjust confirmation copy.

    New copy: the HTML app redirects and shows nothing, so there is no existing
    sentence to extract. It lives here rather than in the serialiser because
    §2.5 forbids api.py from composing rep-facing strings. `tail` carries
    runtime.expiry_clause() on an ephemeral host (§6.5 requirement 2).
    """
    when = human_date(expires_at)
    if kind == "pin":
        return "Pinned to the top of your queue until %s%s." % (when, tail)
    if kind == "demote":
        return "Demoted in your queue until %s%s." % (when, tail)
    if kind == "mute_account":
        return ("Muted. This account is out of your queue until %s%s, then it "
                "comes back on its own." % (when, tail))
    return "Adjustment applied until %s%s." % (when, tail)


REVERT_CONFIRMATION = "Undone. The signal counts again from now."


def budget_key(kind, account_id):
    if kind == "suppress_signal_type":
        return "suppress_signal_type_global" if account_id is None else "suppress_signal_type_account"
    return kind


def count_active(conn, rep_id, key, as_of):
    if key == "suppress_signal_type_global":
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM queue_adjustments "
            "WHERE rep_id = ? AND kind = ? AND account_id IS NULL "
            "  AND is_active = ? AND expires_at > ?",
            (rep_id, "suppress_signal_type", 1, as_of),
        ).fetchone()
    elif key == "suppress_signal_type_account":
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM queue_adjustments "
            "WHERE rep_id = ? AND kind = ? AND account_id IS NOT NULL "
            "  AND is_active = ? AND expires_at > ?",
            (rep_id, "suppress_signal_type", 1, as_of),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM queue_adjustments "
            "WHERE rep_id = ? AND kind = ? AND is_active = ? AND expires_at > ?",
            (rep_id, key, 1, as_of),
        ).fetchone()
    return row["n"] or 0


def oldest_expiry(conn, rep_id, key, as_of):
    kind = "suppress_signal_type" if key.startswith("suppress_signal_type") else key
    row = conn.execute(
        "SELECT MIN(expires_at) AS e FROM queue_adjustments "
        "WHERE rep_id = ? AND kind = ? AND is_active = ? AND expires_at > ?",
        (rep_id, kind, 1, as_of),
    ).fetchone()
    return row["e"]


def budget_usage(conn, rep_id, as_of):
    return {key: (count_active(conn, rep_id, key, as_of), limit)
            for key, limit in BUDGETS.items()}


def create_adjustment(conn, rep_id, kind, as_of, expires_at, account_id=None,
                      signal_type_id=None, person_id=None,
                      source_disagreement_id=None):
    """Server-side budget enforcement (§7.3). Refuses; never silently evicts."""
    key = budget_key(kind, account_id)
    active = count_active(conn, rep_id, key, as_of)
    if active >= BUDGETS[key]:
        raise BudgetExceeded(key, active, BUDGETS[key],
                             oldest_expiry(conn, rep_id, key, as_of))
    cursor = conn.execute(
        "INSERT INTO queue_adjustments "
        "(rep_id, kind, account_id, signal_type_id, person_id, created_at, "
        " expires_at, source_disagreement_id, is_active, reverted_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (rep_id, kind, account_id, signal_type_id, person_id, as_of,
         expires_at, source_disagreement_id, 1, None),
    )
    return cursor.lastrowid


def revert_adjustment(conn, rep_id, adjustment_id, as_of):
    """POST /adjust/revert. Sets is_active=0, reverted_at, and moves any linked
    disagreement to status='reverted' (§7.3)."""
    row = conn.execute(
        "SELECT * FROM queue_adjustments WHERE adjustment_id = ? AND rep_id = ?",
        (adjustment_id, rep_id),
    ).fetchone()
    if row is None:
        return None
    conn.execute(
        "UPDATE queue_adjustments SET is_active = ?, reverted_at = ? "
        "WHERE adjustment_id = ? AND rep_id = ?",
        (0, as_of, adjustment_id, rep_id),
    )
    conn.execute(
        "UPDATE disagreements SET status = ? WHERE resulting_adjustment_id = ? AND rep_id = ?",
        ("reverted", adjustment_id, rep_id),
    )
    log_task_event(conn, rep_id, "reverted", as_of,
                   account_id=row["account_id"],
                   detail={"adjustment_id": adjustment_id, "kind": row["kind"]})
    return dict(row)


def log_task_event(conn, rep_id, event_type, occurred_at, account_id=None,
                   score_id=None, run_id=None, rank_at_event=None, detail=None):
    conn.execute(
        "INSERT INTO task_events "
        "(rep_id, account_id, score_id, run_id, event_type, occurred_at, "
        " rank_at_event, detail_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (rep_id, account_id, score_id, run_id, event_type, occurred_at,
         rank_at_event, json.dumps(detail) if detail else None),
    )


# --------------------------------------------------------------------------
# Ordering (§4.2)
# --------------------------------------------------------------------------

def _order_key(points, freshest_evidence_at, account_id):
    """ORDER BY points DESC, freshest_evidence_at DESC, account_id ASC.

    The third key exists solely so ties are deterministic — a silently
    reordering queue destroys trust faster than a wrong reason does.
    """
    if freshest_evidence_at is None:
        freshness = (1,)                                     # NULLs last
    else:
        freshness = (0,) + tuple(-ord(ch) for ch in freshest_evidence_at)
    return (-points, freshness, account_id)


def order_scores(scores, adjustments):
    """Returns (ordered_scores, rank_before_by_account).

    rank_in_queue: pinned block first, then everything else, then demoted last.
    rank_before_adjustment: ordering by points_before_adjustment alone.
    """
    visible = [s for s in scores if s.account_id not in adjustments.muted]

    before = sorted(visible, key=lambda s: _order_key(
        s.points_before_adjustment, s.freshest_evidence_at, s.account_id))
    rank_before = {s.account_id: i for i, s in enumerate(before, start=1)}

    def bucket(score):
        if score.account_id in adjustments.pinned:
            return 0
        if score.account_id in adjustments.demoted:
            return 2
        return 1

    ordered = sorted(visible, key=lambda s: (
        bucket(s), _order_key(s.points, s.freshest_evidence_at, s.account_id)))
    return ordered, rank_before


# --------------------------------------------------------------------------
# Building and persisting a run
# --------------------------------------------------------------------------

class QueueItem:
    def __init__(self, score, all_reasons, shown_reasons, limits_line,
                 rank_in_queue, rank_before_adjustment, score_id=None):
        self.score = score
        self.all_reasons = all_reasons
        self.shown_reasons = shown_reasons
        self.limits_line = limits_line
        self.rank_in_queue = rank_in_queue
        self.rank_before_adjustment = rank_before_adjustment
        self.score_id = score_id
        self.account_id = score.account_id


def build_run(conn, rep_id, as_of, persist=True):
    """Score the rep's whole patch from live SQL and write one immutable run.

    A run is created on every GET /queue and every GET /account/{id} (§3.7), so
    dispute rows always have a stable snapshot to point at and the effect of a
    dispute is visible on the very next render (§7.4).
    """
    scores, adjustments = score_queue(conn, rep_id, as_of)
    ordered, rank_before = order_scores(scores, adjustments)

    run_id = None
    if persist:
        cursor = conn.execute(
            "INSERT INTO score_runs (rep_id, as_of, computed_at, ruleset_version, "
            "anchor_points, account_count) VALUES (?, ?, ?, ?, ?, ?)",
            (rep_id, as_of, as_of, ruleset_version(), ANCHOR_POINTS, len(ordered)),
        )
        run_id = cursor.lastrowid

    items = []
    for rank, score in enumerate(ordered, start=1):
        ctx_extra = {
            "owner_name": _owner_name(conn, score.account),
            "people_count": score.people_count,
        }
        all_reasons, shown = reasons_mod.build_reasons(conn, score, ctx_extra)
        limits_line = reasons_mod.build_limits_line(score, all_reasons, shown)
        item = QueueItem(score, all_reasons, shown, limits_line,
                         rank, rank_before[score.account_id])
        if persist:
            item.score_id = _persist_score(conn, run_id, item)
        items.append(item)

    if persist:
        conn.commit()
    return run_id, items, adjustments


def _owner_name(conn, account):
    if account["owner_rep_id"] is None:
        return "another rep"
    row = conn.execute("SELECT name FROM reps WHERE rep_id = ?",
                       (account["owner_rep_id"],)).fetchone()
    return row["name"] if row else "another rep"


def _persist_score(conn, run_id, item):
    score = item.score
    cursor = conn.execute(
        "INSERT INTO scores (run_id, account_id, points, points_before_adjustment, "
        " band, confidence, distinct_signal_types, freshest_evidence_at, "
        " data_completeness, rank_in_queue, rank_before_adjustment, "
        " adjustment_flags, limits_line) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, score.account_id, score.points, score.points_before_adjustment,
         score.band, score.confidence, score.distinct_signal_types,
         score.freshest_evidence_at, score.data_completeness, item.rank_in_queue,
         item.rank_before_adjustment,
         json.dumps(score.adjustment_flags) if score.adjustment_flags else None,
         item.limits_line),
    )
    score_id = cursor.lastrowid

    for reason in item.all_reasons:
        rc = conn.execute(
            "INSERT INTO reasons (score_id, signal_type_id, rank, polarity, points, "
            " points_before_adjustment, share_of_abs_total, text, evidence_summary, "
            " newest_event_at, oldest_event_at, event_count, source_names, shown, "
            " is_suppressed, cap_applied) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (score_id, reason.signal_type_id, reason.rank, reason.polarity,
             reason.points, reason.points_before_adjustment,
             reason.share_of_abs_total, reason.text, reason.evidence_summary,
             reason.newest_event_at, reason.oldest_event_at, reason.event_count,
             json.dumps(reason.source_names), reason.shown,
             1 if reason.is_suppressed else 0, 1 if reason.cap_applied else 0),
        )
        reason_id = rc.lastrowid
        rows = [(reason_id, e.event_id, round(e.contribution, 4))
                for e in reason.contribution.events]
        if rows:
            conn.executemany(
                "INSERT INTO reason_evidence (reason_id, event_id, contribution) "
                "VALUES (?, ?, ?)", rows)
    return score_id


def latest_run_id(conn, rep_id):
    row = conn.execute(
        "SELECT MAX(run_id) AS r FROM score_runs WHERE rep_id = ?", (rep_id,)
    ).fetchone()
    return row["r"]


def active_adjustments_for(conn, rep_id, as_of, account_id=None):
    rows = load_active_adjustments(conn, rep_id, as_of)
    if account_id is None:
        return rows
    return [r for r in rows
            if r["account_id"] == account_id
            or (r["kind"] == "suppress_signal_type" and r["account_id"] is None)]


def adjustment_set(conn, rep_id, as_of):
    return AdjustmentSet(load_active_adjustments(conn, rep_id, as_of))
