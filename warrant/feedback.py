"""Disputes and the code -> effect mapping. DESIGN_SPEC.md §7.1, §7.2, §8.6.

Every one of the seven codes produces a mechanical, bounded, visible change.
There is no code here that logs and does nothing — implication #11 is explicit
that if disagreement changes nothing, reps stop registering it within weeks.
"""

from warrant.db import ruleset_version
from warrant.queue import BudgetExceeded, create_adjustment, log_task_event
from warrant.timeutil import shift

REASON_SCOPED_CODES = ("EVIDENCE_WRONG", "EVIDENCE_STALE", "WRONG_PERSON")
ITEM_SCOPED_CODES = ("NOT_A_FIT", "BAD_TIMING", "ALREADY_WORKING", "NOT_MY_PATCH",
                     "WRONG_PERSON")

CODE_LABELS = {
    "NOT_A_FIT": "Not a fit",
    "WRONG_PERSON": "Wrong person",
    "BAD_TIMING": "Bad timing",
    "ALREADY_WORKING": "Already working this",
    "EVIDENCE_WRONG": "This is wrong",
    "EVIDENCE_STALE": "Out of date",
    "NOT_MY_PATCH": "Not my patch",
}

# §7.2. (kind, default_window_days, allowed_windows)
CODE_EFFECTS = {
    "EVIDENCE_WRONG":  ("suppress_signal_type", 90,  (90,)),
    "EVIDENCE_STALE":  ("suppress_signal_type", 30,  (30,)),
    "WRONG_PERSON":    ("exclude_person",       90,  (90,)),
    "NOT_A_FIT":       ("mute_account",         60,  (60,)),
    "BAD_TIMING":      ("demote",               30,  (14, 30, 90)),
    "ALREADY_WORKING": ("mute_account",         21,  (21,)),
    "NOT_MY_PATCH":    ("mute_account",         365, (365,)),
}

def wrong_person_label(person):
    """'Wrong person (Ana Belic)'. The control names the human it would exclude,
    because WRONG_PERSON maps to exclude_person and Warrant will not guess."""
    return "Wrong person (%s)" % person["full_name"]


STRUCK_THROUGH_NOTE = {
    "EVIDENCE_WRONG": "You said this was wrong on %s. Not counted here until %s.",
    "EVIDENCE_STALE": "You marked this out of date on %s. Not counted here until %s.",
}


class DisputeError(Exception):
    pass


# --------------------------------------------------------------------------
# Confirmation copy for the JSON write path (DEPLOY_ARCHITECTURE.md §3.13).
#
# New copy, not an extraction: the HTML app answers a dispute with a 303 back
# into a fresh render, so it never composed a confirmation sentence. It lives
# here, next to the code -> effect mapping it describes, because §2.5 forbids
# warrant/api.py from composing any rep-facing string. `tail` carries
# runtime.expiry_clause() so an ephemeral host says so in the same breath as
# the return date (§6.5 requirement 2).
# --------------------------------------------------------------------------

REVIEW_CONFIRMATION = "Noted — the signal keeps counting."

# Which codes take the account out of the queue immediately. §3.13: for these
# the server names 'queue' as the next view, so the rep sees the confirmation
# and the return date instead of a 404-ish "Not in this queue" screen.
MUTE_PRODUCING_CODES = ("NOT_A_FIT", "ALREADY_WORKING", "NOT_MY_PATCH")


def effect_kind(code):
    kind, _default_days, _allowed = CODE_EFFECTS[code]
    return kind


def dispute_confirmation(code, expires_at, signal_display_name=None,
                         person_name=None, tail=""):
    """The sentence the rep reads after a dispute lands."""
    from warrant.timeutil import human_date
    when = human_date(expires_at)
    if code == "EVIDENCE_WRONG":
        return ("You said \"%s\" was wrong. Suppressed for this account until "
                "%s%s." % (signal_display_name or "this signal", when, tail))
    if code == "EVIDENCE_STALE":
        return ("You marked \"%s\" out of date. Not counted for this account "
                "until %s%s." % (signal_display_name or "this signal", when, tail))
    if code == "WRONG_PERSON":
        return ("%s will not count towards this account's score until %s%s."
                % (person_name or "That person", when, tail))
    if code == "NOT_A_FIT":
        return ("Not a fit — this account is out of your queue until %s%s, then "
                "it comes back on its own." % (when, tail))
    if code == "BAD_TIMING":
        return "Demoted in your queue until %s%s." % (when, tail)
    if code == "ALREADY_WORKING":
        return ("Noted — out of your queue until %s%s while you work it."
                % (when, tail))
    if code == "NOT_MY_PATCH":
        return ("Noted — out of your queue until %s%s. RevOps sees this on the "
                "metrics page as an ownership error." % (when, tail))
    return "Recorded. In effect until %s%s." % (when, tail)


def record_dispute(conn, rep_id, account_id, code, as_of, score_id=None,
                   reason_id=None, signal_type_id=None, person_id=None,
                   note=None, window_days=None, rank_at_event=None):
    """Write the dispute, create its bounded adjustment, link the two.

    Returns (disagreement_id, adjustment_id).
    Raises BudgetExceeded (-> HTTP 409) rather than silently dropping anything.
    """
    if code not in CODE_EFFECTS:
        raise DisputeError("unknown dispute code %r" % (code,))
    if note is not None and len(note) > 280:
        note = note[:280]                       # 280 chars, enforced server-side

    kind, default_days, allowed = CODE_EFFECTS[code]
    days = window_days if window_days in allowed else default_days

    scope = "reason" if (reason_id is not None or code in ("EVIDENCE_WRONG", "EVIDENCE_STALE")) else "item"
    if scope == "reason" and signal_type_id is None:
        raise DisputeError("reason-scoped dispute needs a signal_type_id")
    if kind == "exclude_person" and person_id is None:
        raise DisputeError("WRONG_PERSON needs a person_id — Warrant will not "
                           "guess which human the rep meant")

    cursor = conn.execute(
        "INSERT INTO disagreements (rep_id, account_id, score_id, reason_id, "
        " signal_type_id, person_id, scope, code, note, created_at, "
        " ruleset_version, status, resulting_adjustment_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (rep_id, account_id, score_id, reason_id,
         signal_type_id if scope == "reason" else signal_type_id,
         person_id, scope, code, note, as_of, ruleset_version(), "open", None),
    )
    disagreement_id = cursor.lastrowid

    expires_at = shift(as_of, days=days)
    adj_account_id = account_id
    adj_signal_type_id = signal_type_id if kind == "suppress_signal_type" else None
    adj_person_id = person_id if kind == "exclude_person" else None

    try:
        adjustment_id = create_adjustment(
            conn, rep_id, kind, as_of, expires_at,
            account_id=adj_account_id,
            signal_type_id=adj_signal_type_id,
            person_id=adj_person_id,
            source_disagreement_id=disagreement_id,
        )
    except BudgetExceeded:
        conn.rollback()
        raise

    conn.execute(
        "UPDATE disagreements SET resulting_adjustment_id = ?, status = ? "
        "WHERE disagreement_id = ?",
        (adjustment_id, "applied", disagreement_id),
    )
    log_task_event(conn, rep_id, "disputed", as_of, account_id=account_id,
                   score_id=score_id, rank_at_event=rank_at_event,
                   detail={"code": code,
                           "signal_type_id": signal_type_id,
                           "scope": scope})
    log_task_event(conn, rep_id, "adjusted", as_of, account_id=account_id,
                   score_id=score_id,
                   detail={"kind": kind, "expires_at": expires_at})
    conn.commit()
    return disagreement_id, adjustment_id


def record_review(conn, rep_id, account_id, signal_type_id, as_of, score_id=None):
    """§8.6(b) "leave it — it looks right now".

    Writes a disagreements row with status='reviewed' and no adjustment, so the
    metric records that the rep looked and accepted. Silently resuming a signal
    the rep once rejected, with no notice, is the most direct way to teach them
    that disputes are theatre.
    """
    cursor = conn.execute(
        "INSERT INTO disagreements (rep_id, account_id, score_id, reason_id, "
        " signal_type_id, person_id, scope, code, note, created_at, "
        " ruleset_version, status, resulting_adjustment_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (rep_id, account_id, score_id, None, signal_type_id, None, "reason",
         "EVIDENCE_WRONG", "reviewed and accepted by rep", as_of,
         ruleset_version(), "reviewed", None),
    )
    conn.commit()
    return cursor.lastrowid


def disputes_for_account(conn, rep_id, account_id):
    rows = conn.execute(
        "SELECT d.*, st.display_name AS signal_display_name, "
        "       qa.expires_at AS adj_expires_at, qa.is_active AS adj_is_active, "
        "       qa.kind AS adj_kind "
        "FROM disagreements d "
        "LEFT JOIN signal_types st ON st.signal_type_id = d.signal_type_id "
        "LEFT JOIN queue_adjustments qa ON qa.adjustment_id = d.resulting_adjustment_id "
        "WHERE d.rep_id = ? AND d.account_id = ? "
        "ORDER BY d.disagreement_id DESC",
        (rep_id, account_id),
    ).fetchall()
    return [dict(r) for r in rows]


def expired_dispute_banners(conn, rep_id, account_id, as_of, firing_type_ids):
    """§8.6(b): the rep disputed this, the suppression expired, the signal is
    counting again. Say so instead of resuming silently."""
    rows = conn.execute(
        "SELECT d.disagreement_id, d.signal_type_id, d.created_at, "
        "       st.display_name, qa.expires_at "
        "FROM disagreements d "
        "JOIN queue_adjustments qa ON qa.adjustment_id = d.resulting_adjustment_id "
        "JOIN signal_types st ON st.signal_type_id = d.signal_type_id "
        "WHERE d.rep_id = ? AND d.account_id = ? AND d.scope = ? "
        "  AND qa.kind = ? AND qa.expires_at <= ? AND qa.is_active = ?",
        (rep_id, account_id, "reason", "suppress_signal_type", as_of, 1),
    ).fetchall()
    return [dict(r) for r in rows if r["signal_type_id"] in firing_type_ids]


def new_events_since_dispute(conn, rep_id, account_id, signal_type_id, since, as_of):
    """§8.6(c): new evidence arrived for a suppressed type. Report it; never
    auto-unsuppress. The rep set a window; the system honours it."""
    row = conn.execute(
        "SELECT COUNT(*) AS n, MAX(occurred_at) AS newest FROM signal_events "
        "WHERE account_id = ? AND signal_type_id = ? AND occurred_at > ? "
        "  AND occurred_at <= ?",
        (account_id, signal_type_id, since, as_of),
    ).fetchone()
    return (row["n"] or 0), row["newest"]
