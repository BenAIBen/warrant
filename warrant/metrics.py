"""Instrumentation. DESIGN_SPEC.md §7.5.

All computed by live SQL over task_events, disagreements, queue_adjustments,
reasons and scores. Window: trailing 30 days from as_of. Every parameter is
bound with ? — there is no string-interpolated SQL in this module.

On the target number: §2 row 11a of the spec rejects importing Pedowitz Group's
65-75% MQL->SQL figure, because it measures a different handoff with a different
denominator. Top-3 acceptance therefore ships with no target in v1.
"""

from warrant.timeutil import shift

WINDOW_DAYS = 30
FLAG_DISPUTE_RATE = 0.20     # §7.5 flag rule
FLAG_MIN_SHOWS = 30


def window_start(as_of):
    return shift(as_of, days=-WINDOW_DAYS)


def _scalar(conn, sql, params, key="n"):
    row = conn.execute(sql, params).fetchone()
    return (row[key] or 0) if row is not None else 0


def top3_acceptance(conn, as_of):
    """accepted events at rank<=3 / distinct top-3 items rendered.

    Both sides are counted over distinct (rep, account) pairs from task_events,
    because task_events is the only table that records what a rep was actually
    shown at what rank at the time they acted.
    """
    since = window_start(as_of)
    denominator = _scalar(conn,
        "SELECT COUNT(*) AS n FROM (SELECT DISTINCT rep_id, account_id FROM task_events "
        "WHERE event_type = ? AND rank_at_event <= ? AND occurred_at >= ? AND occurred_at <= ?)",
        ("item_viewed", 3, since, as_of))
    numerator = _scalar(conn,
        "SELECT COUNT(*) AS n FROM (SELECT DISTINCT rep_id, account_id FROM task_events "
        "WHERE event_type = ? AND rank_at_event <= ? AND occurred_at >= ? AND occurred_at <= ?)",
        ("accepted", 3, since, as_of))
    return numerator, denominator, _rate(numerator, denominator)


def evidence_open_rate(conn, as_of):
    since = window_start(as_of)
    denominator = _scalar(conn,
        "SELECT COUNT(*) AS n FROM (SELECT DISTINCT rep_id, account_id FROM task_events "
        "WHERE event_type = ? AND occurred_at >= ? AND occurred_at <= ?)",
        ("item_viewed", since, as_of))
    numerator = _scalar(conn,
        "SELECT COUNT(*) AS n FROM (SELECT DISTINCT rep_id, account_id FROM task_events "
        "WHERE event_type = ? AND occurred_at >= ? AND occurred_at <= ?)",
        ("evidence_opened", since, as_of))
    return numerator, denominator, _rate(numerator, denominator)


def item_dispute_rate(conn, as_of):
    since = window_start(as_of)
    denominator = _scalar(conn,
        "SELECT COUNT(*) AS n FROM task_events WHERE event_type = ? "
        "AND occurred_at >= ? AND occurred_at <= ?",
        ("item_viewed", since, as_of))
    numerator = _scalar(conn,
        "SELECT COUNT(*) AS n FROM disagreements WHERE scope = ? "
        "AND created_at >= ? AND created_at <= ?",
        ("item", since, as_of))
    return numerator, denominator, _rate(numerator, denominator)


def revert_rate(conn, as_of):
    since = window_start(as_of)
    denominator = _scalar(conn,
        "SELECT COUNT(*) AS n FROM task_events WHERE event_type = ? "
        "AND occurred_at >= ? AND occurred_at <= ?", ("adjusted", since, as_of))
    numerator = _scalar(conn,
        "SELECT COUNT(*) AS n FROM task_events WHERE event_type = ? "
        "AND occurred_at >= ? AND occurred_at <= ?", ("reverted", since, as_of))
    return numerator, denominator, _rate(numerator, denominator)


def skip_without_dispute_rate(conn, as_of):
    """'reps who skip without telling us why are the ones we are losing'.

    "Same session" is not defined in the spec; this implementation reads it as
    a dispute by the same rep on the same account within one hour of the skip.
    Recorded in README.md under Deviations.
    """
    since = window_start(as_of)
    skips = conn.execute(
        "SELECT rep_id, account_id, occurred_at FROM task_events "
        "WHERE event_type = ? AND occurred_at >= ? AND occurred_at <= ?",
        ("skipped", since, as_of)).fetchall()
    total = len(skips)
    silent = 0
    for skip in skips:
        low = shift(skip["occurred_at"], hours=-1)
        high = shift(skip["occurred_at"], hours=1)
        matched = _scalar(conn,
            "SELECT COUNT(*) AS n FROM disagreements WHERE rep_id = ? AND account_id = ? "
            "AND created_at >= ? AND created_at <= ?",
            (skip["rep_id"], skip["account_id"], low, high))
        if matched == 0:
            silent += 1
    return silent, total, _rate(silent, total)


def reason_dispute_rates(conn, as_of):
    """Per signal type: disputes scoped to that type / times shown (shown=1).

    Also returns the §7.5 flag: >20% of the reps who saw it, over >=30 shows,
    in 30 days -> REVIEW REQUIRED. It is a flag for a human, never an automatic
    weight change.
    """
    since = window_start(as_of)
    types = conn.execute(
        "SELECT signal_type_id, code, display_name FROM signal_types ORDER BY signal_type_id"
    ).fetchall()

    shows = dict(conn.execute(
        "SELECT r.signal_type_id AS sid, COUNT(*) AS n "
        "FROM reasons r JOIN scores s ON s.score_id = r.score_id "
        "JOIN score_runs sr ON sr.run_id = s.run_id "
        "WHERE r.shown = ? AND sr.as_of >= ? AND sr.as_of <= ? "
        "GROUP BY r.signal_type_id", (1, since, as_of)).fetchall())
    saw_reps = dict(conn.execute(
        "SELECT r.signal_type_id AS sid, COUNT(DISTINCT sr.rep_id) AS n "
        "FROM reasons r JOIN scores s ON s.score_id = r.score_id "
        "JOIN score_runs sr ON sr.run_id = s.run_id "
        "WHERE r.shown = ? AND sr.as_of >= ? AND sr.as_of <= ? "
        "GROUP BY r.signal_type_id", (1, since, as_of)).fetchall())
    disputes = dict(conn.execute(
        "SELECT signal_type_id AS sid, COUNT(*) AS n FROM disagreements "
        "WHERE signal_type_id IS NOT NULL AND created_at >= ? AND created_at <= ? "
        "GROUP BY signal_type_id", (since, as_of)).fetchall())
    dispute_reps = dict(conn.execute(
        "SELECT signal_type_id AS sid, COUNT(DISTINCT rep_id) AS n FROM disagreements "
        "WHERE signal_type_id IS NOT NULL AND created_at >= ? AND created_at <= ? "
        "GROUP BY signal_type_id", (since, as_of)).fetchall())
    suppressing_reps = dict(conn.execute(
        "SELECT signal_type_id AS sid, COUNT(DISTINCT rep_id) AS n FROM queue_adjustments "
        "WHERE kind = ? AND is_active = ? AND expires_at > ? GROUP BY signal_type_id",
        ("suppress_signal_type", 1, as_of)).fetchall())

    out = []
    for t in types:
        sid = t["signal_type_id"]
        shown_n = shows.get(sid, 0)
        disputes_n = disputes.get(sid, 0)
        reps_saw = saw_reps.get(sid, 0)
        reps_disputed = dispute_reps.get(sid, 0)
        rep_share = (reps_disputed / reps_saw) if reps_saw else 0.0
        flagged = rep_share > FLAG_DISPUTE_RATE and shown_n >= FLAG_MIN_SHOWS
        out.append({
            "signal_type_id": sid,
            "code": t["code"],
            "display_name": t["display_name"],
            "shown_count": shown_n,
            "dispute_count": disputes_n,
            "dispute_rate": _rate(disputes_n, shown_n),
            "reps_saw": reps_saw,
            "reps_disputed": reps_disputed,
            "suppressing_reps": suppressing_reps.get(sid, 0),
            "suppression_rate": _rate(suppressing_reps.get(sid, 0), reps_saw),
            "flagged": flagged,
            "flag_text": ("REVIEW REQUIRED — %d of %d reps have disputed this"
                          % (reps_disputed, reps_saw)) if flagged else "",
        })
    out.sort(key=lambda r: (-(r["dispute_rate"] or 0.0), r["code"]))
    return out


def ownership_errors(conn, as_of):
    since = window_start(as_of)
    rows = conn.execute(
        "SELECT d.account_id, a.name AS account_name, COUNT(*) AS n "
        "FROM disagreements d JOIN accounts a ON a.account_id = d.account_id "
        "WHERE d.code = ? AND d.created_at >= ? AND d.created_at <= ? "
        "GROUP BY d.account_id, a.name ORDER BY n DESC, a.name ASC",
        ("NOT_MY_PATCH", since, as_of)).fetchall()
    return [dict(r) for r in rows]


# The five headline rates, their labels and their notes, in print order.
# Extracted so the HTML table and the JSON payload cannot label the same number
# two different ways (DEPLOY_ARCHITECTURE.md §2.5, applied to /metrics).
# The HTML page prints the note with a leading " — "; the JSON carries it bare.
METRIC_ROWS = (
    ("top3", "Top-3 acceptance (last 30d)",
     "no target set; v1 establishes baseline"),
    ("evidence_open", "Evidence-open rate", None),
    ("item_dispute", "Item dispute rate", None),
    ("revert", "Revert rate", None),
    ("skip_silent", "Skip with no dispute",
     "reps who skip without telling us why are the ones we are losing"),
)

# README honest-limitations 4 and 5, served as strings so the page cannot show
# synthetic rates without saying they are synthetic (§3.11).
CAVEAT_LINES = (
    "/metrics numbers are computed by live SQL over synthetic instrumentation. "
    "The arithmetic is real; the inputs are seeded.",
    "Per-signal-type show counts only exist once someone has loaded a queue.",
)

FLAG_NOTE = ("A type disputed by more than 20% of the reps who saw it, over at "
             "least 30 shows in 30 days, is flagged REVIEW REQUIRED on /ruleset. "
             "It is a flag for a human, never an automatic weight change.")


def window_line(data):
    """'Trailing 30 days, 12 Jul 2026 to 11 Aug 2026. All figures are live SQL
    over task_events, disagreements, queue_adjustments and reasons.'"""
    from warrant.timeutil import human_date
    return ("Trailing 30 days, %s to %s. All figures are live SQL over "
            "task_events, disagreements, queue_adjustments and reasons."
            % (human_date(data["window_start"]), human_date(data["as_of"])))


def _rate(numerator, denominator):
    if not denominator:
        return None
    return numerator / denominator


def format_rate(rate):
    return "—" if rate is None else "%.1f%%" % (rate * 100.0)


def collect(conn, as_of):
    return {
        "as_of": as_of,
        "window_start": window_start(as_of),
        "top3": top3_acceptance(conn, as_of),
        "evidence_open": evidence_open_rate(conn, as_of),
        "item_dispute": item_dispute_rate(conn, as_of),
        "revert": revert_rate(conn, as_of),
        "skip_silent": skip_without_dispute_rate(conn, as_of),
        "per_type": reason_dispute_rates(conn, as_of),
        "ownership_errors": ownership_errors(conn, as_of),
    }
