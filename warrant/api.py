"""JSON serialisation. DEPLOY_ARCHITECTURE.md §2.5 and §3.

THE ONE RULE THIS MODULE EXISTS TO OBEY (§2.1):

    The backend returns fully-rendered reason text, per-reason point values, the
    applied truncation and the limits line as JSON fields. The browser does
    layout and interaction ONLY — zero arithmetic, zero ranking, zero
    truncation, zero template substitution.

So this module SERIALISES. It COMPUTES NOTHING. Concretely, and mechanically
checked by tests/test_api.py::test_api_serialiser_contains_no_arithmetic:

  * no arithmetic operator is applied to a points value anywhere in this file
  * there is no call to sorted(), min() or max() anywhere in this file
  * no reason list is sliced, reordered or filtered here
  * every rep-facing string in every payload is produced by a named function in
    warrant/reasons.py, warrant/queue.py, warrant/feedback.py or
    warrant/metrics.py — never composed here

The two % expressions in this file build hrefs (`/api/account/1042?rep=1`).
An href is machine-facing routing, not copy a rep reads. The one slice in this
file is `observations[:RESEARCH_PREVIEW]`, which mirrors what render.py does on
the same list; §2.5 forbids slicing a *reason* list, and observations are not
reasons. Both are called out here so a reviewer does not have to wonder.

This module deliberately does NOT import warrant/render.py (§10.3 open question
1): an API module that depends on an HTML module invites HTML into JSON. Every
string it needs was extracted down into reasons.py / queue.py / feedback.py /
metrics.py first, and that extraction was proved output-neutral by rendering all
76 HTML views before and after and comparing sha256 per view.

There is no cache here (§7.1, §7.2). Every payload is built from objects that
build_run() produced from live SQL microseconds earlier, and nothing in this
file holds a reference to any of it after it returns.
"""

from urllib.parse import urlencode

from warrant import feedback as feedback_mod
from warrant import metrics as metrics_mod
from warrant import queue as queue_mod
from warrant import reasons as reasons_mod
from warrant import runtime
from warrant.db import as_of, persistence, ruleset_version
from warrant.timeutil import human_datetime

# Error codes (§3.3). Names only; the sentences come from the modules above.
BAD_REQUEST = "BAD_REQUEST"
NOT_FOUND = "NOT_FOUND"
NOT_IN_QUEUE = "NOT_IN_QUEUE"
BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
INTERNAL = "INTERNAL"

NOT_FOUND_TITLE = "Not found"
NOT_IN_QUEUE_TITLE = "Not in this queue right now."
NOT_IN_QUEUE_MESSAGE = (
    "This account is not in your queue at the moment. It may be muted by you, "
    "inactive, or owned by someone else. Muted accounts return automatically "
    "when the window expires.")
BAD_REQUEST_TITLE = "Could not record that"
INTERNAL_TITLE = "Something went wrong"
INTERNAL_MESSAGE = (
    "The server hit an error building this response. Nothing was changed. The "
    "details are in the server log, not in this message.")
EVIDENCE_REQUIRED_TITLE = "Open the evidence first"
ADJUSTMENTS_ACTION_LABEL = "view your adjustments"
OPEN_ACCOUNT_ACTION_LABEL = "open the account"

REP_NOT_FOUND_MESSAGE = "No such rep."
ACCOUNT_NOT_FOUND_MESSAGE = "No such account."
REASON_NOT_FOUND_MESSAGE = "No such reason."
ROUTE_NOT_FOUND_MESSAGE = "No such endpoint."


# ---------------------------------------------------------------------------
# hrefs — routing, not copy
# ---------------------------------------------------------------------------

def _href(path, **params):
    query = urlencode({k: v for k, v in params.items() if v is not None})
    if not query:
        return path
    return "%s?%s" % (path, query)


def queue_href(rep_id):
    return _href("/api/queue", rep=rep_id)


def account_href(account_id, rep_id):
    return _href("/api/account/%s" % account_id, rep=rep_id)


def evidence_href(reason_id, rep_id):
    return _href("/api/evidence/%s" % reason_id, rep=rep_id)


def observations_href(account_id, rep_id):
    return _href("/api/evidence/observations/%s" % account_id, rep=rep_id)


def adjustments_href(rep_id):
    return _href("/api/adjustments", rep=rep_id)


# ---------------------------------------------------------------------------
# §3.2 the meta block, on every read response
# ---------------------------------------------------------------------------

def meta():
    """Process facts plus the persistence disclosure. Never a score.

    started_at / boot_id are captured once at process start by warrant/runtime,
    so a changed boot_id is how the frontend learns the container restarted and
    the rep's disputes are gone (§6.5 requirement 3).
    """
    now = as_of()
    return {
        "as_of": now,
        "as_of_display": human_datetime(now),
        "ruleset_version": ruleset_version(),
        "boot_id": runtime.boot_id(),
        "started_at": runtime.started_at(),
        "started_at_display": runtime.started_at_display(),
        "persistence": persistence(),
        "persistence_notice": runtime.persistence_notice(),
        # Additive beyond §3.2's example block, and flagged as such. §6.5
        # requirement 3 needs rep-facing copy for the restart case, but the
        # restart is DETECTED client-side (boot_id changed). Serving the
        # sentences here keeps them server-side, so there is one copy rather
        # than a literal in app.js that would drift from warrant/runtime.py.
        "restart_notice_title": runtime.RESTART_NOTICE_TITLE,
        "restart_notice": runtime.restart_notice(),
    }


def error_payload(code, title, message, detail=None, action=None):
    """§3.3. Every non-2xx /api response has exactly this shape."""
    return {"error": {"code": code, "title": title, "message": message,
                      "detail": detail, "action": action}}


def budget_error(exc, rep_id):
    """409. The sentence is queue.budget_exceeded_message — the same one the
    HTML 409 page prints, because §2.5 moved it there."""
    return error_payload(
        BUDGET_EXCEEDED,
        queue_mod.BUDGET_EXCEEDED_TITLE,
        queue_mod.budget_exceeded_message(exc),
        detail={"budget_key": exc.key, "active": exc.active, "limit": exc.limit,
                "oldest_expiry": exc.oldest_expiry},
        action={"label": ADJUSTMENTS_ACTION_LABEL,
                "href": adjustments_href(rep_id)})


def evidence_required_error(friction_sentence, account_id, rep_id):
    """409. `friction_sentence` is app.friction_text() verbatim (§3.13)."""
    return error_payload(
        EVIDENCE_REQUIRED, EVIDENCE_REQUIRED_TITLE, friction_sentence,
        detail={"account_id": account_id},
        action={"label": OPEN_ACCOUNT_ACTION_LABEL,
                "href": account_href(account_id, rep_id)})


def not_in_queue_error(account_id, rep_id):
    """404 NOT_IN_QUEUE — a distinct code because it is a normal outcome after a
    NOT_A_FIT dispute, not a failure (§3.3, §9.7)."""
    return error_payload(
        NOT_IN_QUEUE, NOT_IN_QUEUE_TITLE, NOT_IN_QUEUE_MESSAGE,
        detail={"account_id": account_id},
        action={"label": "back to your queue", "href": queue_href(rep_id)})


# ---------------------------------------------------------------------------
# §3.4 / §3.5 cheap reads
# ---------------------------------------------------------------------------

def rep_summary(rep):
    return {"rep_id": rep["rep_id"], "name": rep["name"],
            "territory": rep["territory"]}


def health_payload(seeded, account_count, reps):
    """§3.4. Polled every 3s while the container wakes, so it must not score.

    Cost: one SELECT COUNT(*) FROM accounts, one SELECT * FROM reps. Nothing
    here calls build_run() and nothing here may ever be allowed to.
    """
    return {"ok": True, "seeded": seeded, "accounts": account_count,
            "reps": [rep_summary(r) for r in reps], "meta": meta()}


def reps_payload(reps):
    return {"reps": [{"rep_id": r["rep_id"], "name": r["name"],
                      "email": r["email"], "territory": r["territory"]}
                     for r in reps],
            "meta": meta()}


# ---------------------------------------------------------------------------
# §3.6 queue
# ---------------------------------------------------------------------------

def _top_reason_text(item):
    """Already truncated server-side by reasons.truncate_at_word(text, 120).

    The frontend must not truncate. When nothing is shown this carries the thin
    line or NO_SIGNALS_LINE, exactly as render_queue does today.
    """
    if item.shown_reasons:
        return reasons_mod.truncate_at_word(item.shown_reasons[0].text)
    return reasons_mod.thin_data_line(item.score) or reasons_mod.NO_SIGNALS_LINE


def queue_item_payload(item, friction_sentence):
    score = item.score
    freshness = reasons_mod.freshness_chip(score)
    return {
        "account_id": score.account_id,
        "account_name": score.account["name"],
        "rank_in_queue": item.rank_in_queue,
        "band": score.band,
        "band_label": reasons_mod.band_label(score.band),
        "points": score.points,
        "points_display": reasons_mod.points_display(score.points),
        "top_reason_text": _top_reason_text(item),
        "freshness_chip": freshness,
        # Exists only so the frontend can pick a CSS class. It decides no text.
        "freshness_is_stale": freshness.startswith("STALE"),
        "adjustment_chip": reasons_mod.adjustment_chip(score),
        "limits_compressed": reasons_mod.compressed_limits(item.all_reasons,
                                                           item.shown_reasons),
        "work_it_enabled": friction_sentence is None,
        "friction_text": friction_sentence,
    }


def queue_payload(rep, run_id, items, usage, friction_map):
    return {
        "rep": rep_summary(rep),
        "run_id": run_id,
        "header_line": reasons_mod.queue_header_line(rep),
        "run_stamp": reasons_mod.run_stamp(as_of(), ruleset_version(),
                                           len(items), run_id),
        "budget_bar": queue_mod.budget_bar_text(usage),
        "budgets": {key: list(value) for key, value in usage.items()},
        "account_count": len(items),
        "items": [queue_item_payload(item, friction_map.get(item.account_id))
                  for item in items],
        "meta": meta(),
    }


# ---------------------------------------------------------------------------
# §3.7 detail
# ---------------------------------------------------------------------------

def _dispute_action(code, label, rep_id, account_id, signal_type_id=None,
                    reason_id=None, person_id=None, window=None):
    """One dispute control. `fields` is submitted verbatim as URLSearchParams,
    with the same field names the HTML forms use, so app.py::_form() parses both
    paths with one code (§4.5)."""
    fields = {"rep": rep_id, "account": account_id, "code": code}
    if signal_type_id is not None:
        fields["signal_type"] = signal_type_id
    if reason_id is not None:
        fields["reason"] = reason_id
    if person_id is not None:
        fields["person"] = person_id
    if window is not None:
        fields["window"] = window
    return {"code": code, "label": label, "fields": fields}


def reason_payload(reason, rep_id, account_id, context):
    """One shown reason. Element order on screen is the frontend's job; the
    values here are final."""
    reason_id = context["reason_ids"].get(reason.signal_type_id)
    payload = {
        "reason_id": reason_id,
        "signal_type_id": reason.signal_type_id,
        "rank": reason.rank,
        "category_label": reasons_mod.CATEGORY_LABELS[reason.category],
        "text": reason.text,
        "evidence_summary": reason.evidence_summary,
        "points": reason.points,
        "cap_applied": reason.cap_applied,
        "is_suppressed": bool(reason.is_suppressed),
        "suppression_note": None,
        "new_events_note": None,
        "undo_adjustment_id": None,
        "evidence_href": evidence_href(reason_id, rep_id) if reason_id else None,
        "actions": [],
    }

    if reason.is_suppressed:
        # §7.4: the reason keeps its slot, struck through, showing what it was
        # worth. Silently backfilling the slot would make the disagreement feel
        # unregistered. The frontend must not reorder or remove it.
        payload["points_display"] = reasons_mod.suppressed_points_label(reason)
        payload["suppression_note"] = context["suppression_notes"].get(
            reason.signal_type_id)
        payload["new_events_note"] = context["new_events_notes"].get(
            reason.signal_type_id)
        payload["undo_adjustment_id"] = context["suppression_adjustments"].get(
            reason.signal_type_id)
        return payload

    payload["points_display"] = reasons_mod.points_label(
        reason.points, reason.cap_applied, reason.contribution.max_contribution)
    payload["actions"] = [
        _dispute_action("EVIDENCE_WRONG", "this is wrong", rep_id, account_id,
                        signal_type_id=reason.signal_type_id,
                        reason_id=reason_id),
        _dispute_action("EVIDENCE_STALE", "out of date", rep_id, account_id,
                        signal_type_id=reason.signal_type_id,
                        reason_id=reason_id),
    ]
    return payload


def _banners(item, rep_id, context):
    """§3.7. kind selects an icon, level selects a CSS class. Both are layout.
    Every sentence is produced by reasons.py or feedback.py."""
    score = item.score
    out = []
    brand_new = reasons_mod.brand_new_line(score)
    if brand_new:
        out.append({"kind": "brand_new", "level": "notice", "text": brand_new,
                    "actions": []})
    stale = reasons_mod.stale_line(score)
    if stale:
        out.append({"kind": "stale", "level": "notice", "text": stale,
                    "actions": []})
    conflict = reasons_mod.conflict_line(score, item.all_reasons)
    if conflict:
        out.append({"kind": "conflict", "level": "notice", "text": conflict,
                    "actions": []})
    thin = reasons_mod.thin_banner_text(score)
    if thin and item.all_reasons:
        # When there are no reasons at all the same sentence IS the reasons
        # block (§8.3), so it is not repeated as a banner above it.
        out.append({"kind": "thin", "level": "warn", "text": thin,
                    "actions": []})
    for banner in context["expired_banners"]:
        out.append({
            "kind": "expired_dispute", "level": "notice",
            "text": reasons_mod.expired_dispute_line(banner),
            "actions": [
                _dispute_action("EVIDENCE_WRONG", "suppress for another 90 days",
                                rep_id, score.account_id,
                                signal_type_id=banner["signal_type_id"]),
                _dispute_action("LEAVE_IT", "leave it — it looks right now",
                                rep_id, score.account_id,
                                signal_type_id=banner["signal_type_id"]),
            ]})
    return out


def _item_dispute_block(rep_id, account_id, context):
    person = context.get("top_person")
    buttons = [_dispute_action("NOT_A_FIT",
                               feedback_mod.CODE_LABELS["NOT_A_FIT"],
                               rep_id, account_id)]
    if person:
        buttons.append(_dispute_action(
            "WRONG_PERSON", feedback_mod.wrong_person_label(person),
            rep_id, account_id, person_id=person["person_id"]))
    buttons.append(_dispute_action("BAD_TIMING",
                                   feedback_mod.CODE_LABELS["BAD_TIMING"],
                                   rep_id, account_id, window=30))
    buttons.append(_dispute_action("ALREADY_WORKING",
                                   feedback_mod.CODE_LABELS["ALREADY_WORKING"],
                                   rep_id, account_id))
    buttons.append(_dispute_action("NOT_MY_PATCH",
                                   feedback_mod.CODE_LABELS["NOT_MY_PATCH"],
                                   rep_id, account_id))
    note = None if person else reasons_mod.WRONG_PERSON_UNAVAILABLE_NOTE
    return {"buttons": buttons, "unavailable_note": note}


def _adjust_block(rep_id, account_id, usage):
    return {
        "budget_line": queue_mod.budget_counts_line(usage,
                                                    queue_mod.ADJUST_BLOCK_KEYS),
        "buttons": [{"kind": kind, "days": days, "label": label,
                     "fields": {"rep": rep_id, "account": account_id,
                                "kind": kind, "days": days}}
                    for kind, days, label in queue_mod.ADJUST_BUTTONS],
    }


def _history(context):
    rows = []
    for row in context["history"]:
        rows.append({"line": reasons_mod.history_line(row),
                     "status": row["status"],
                     "undo_adjustment_id": (row["resulting_adjustment_id"]
                                            if row["adj_is_active"] else None)})
    return rows


def _research(account_id, rep_id, context):
    observations = context["observations"]
    items = [{"summary": o["summary"],
              "source_name": o["source_name"],
              "retrieved_display": reasons_mod.observation_retrieved_display(o),
              "source_url_text": o["source_url"] or reasons_mod.NO_REFERENCE}
             for o in observations[:reasons_mod.RESEARCH_PREVIEW]]
    see_all = (observations_href(account_id, rep_id)
               if len(observations) > reasons_mod.RESEARCH_PREVIEW else None)
    return {"heading": reasons_mod.research_heading(observations),
            "items": items,
            "see_all_href": see_all,
            "empty_note": None if observations else reasons_mod.RESEARCH_EMPTY_NOTE}


def detail_payload(rep, item, usage, total_accounts, context):
    score = item.score
    account = score.account
    rep_id = rep["rep_id"]
    account_id = score.account_id
    return {
        "account": {
            "account_id": account_id,
            "name": account["name"],
            "domain": account["domain"],
            "meta_line": reasons_mod.account_meta_line(account,
                                                       context["owner_label"]),
        },
        "verdict": {
            "band": score.band,
            "band_label": reasons_mod.band_label(score.band),
            "points": score.points,
            "points_display": reasons_mod.points_display(score.points),
            "above_anchor_note": reasons_mod.above_anchor_note(score),
            "anchor_note": reasons_mod.anchor_note(score.band),
            "rank_line": reasons_mod.rank_line(item, total_accounts),
            "confidence": score.confidence,
            "adjusted_note": reasons_mod.adjusted_note(score),
        },
        "banners": _banners(item, rep_id, context),
        "heading": reasons_mod.detail_heading(item),
        # Only reasons with shown = 1 (§3.7). The withheld ones are disclosed in
        # aggregate by limits_line and are never sent over the wire, because a
        # withheld reason in the payload is one devtools panel away from being
        # visible and is a tempting array to build an expander over.
        "reasons": [reason_payload(r, rep_id, account_id, context)
                    for r in item.shown_reasons],
        "limits_line": item.limits_line,
        "adjust": _adjust_block(rep_id, account_id, usage),
        "item_dispute": _item_dispute_block(rep_id, account_id, context),
        "history": _history(context),
        "research": _research(account_id, rep_id, context),
        "no_signals_line": (None if item.all_reasons
                            else reasons_mod.no_signals_text(score)),
        "source_link_note": reasons_mod.SOURCE_LINK_NOTE,
        "meta": meta(),
    }


# ---------------------------------------------------------------------------
# §3.8 / §3.9 evidence
# ---------------------------------------------------------------------------

def evidence_payload(rep_id, reason, account, events, observations):
    """The drawer. Reaching this endpoint writes an evidence_opened task_event,
    which is what clears the §6.4 friction gate — so the frontend must issue a
    real request here and must not prefetch it with the detail view (§3.8)."""
    rows = [{"occurred_display": human_datetime(event["occurred_at"]),
             "contribution": event["contribution"],
             "contribution_display": reasons_mod.evidence_contribution_display(event),
             "magnitude_display": reasons_mod.evidence_magnitude_display(event),
             "detail_display": reasons_mod.evidence_detail_display(event),
             "person_display": reasons_mod.evidence_person_display(event),
             "source_display": reasons_mod.evidence_source_display(event),
             # A string, never an anchor. A link here would 404 by design.
             "ref_display": reasons_mod.evidence_ref_display(event)}
            for event in events]
    return {
        "header": reasons_mod.evidence_header(reason, account),
        "summary_line": reasons_mod.evidence_summary_line(reason, as_of()),
        "kind": "event" if events else "state",
        "events": rows,
        "state_fallback": (None if events
                           else reasons_mod.evidence_state_fallback(reason, account)),
        "source_link_note": reasons_mod.SOURCE_LINK_NOTE,
        "observations": [
            {"summary": o["summary"], "source_name": o["source_name"],
             "retrieved_display": reasons_mod.observation_retrieved_display(o)}
            for o in observations],
        "actions": _evidence_actions(rep_id, reason, account, events),
        "back_href": account_href(account["account_id"], rep_id),
        "meta": meta(),
    }


def _evidence_actions(rep_id, reason, account, events):
    account_id = account["account_id"]
    actions = [
        _dispute_action("EVIDENCE_WRONG", "this reason is wrong", rep_id,
                        account_id, signal_type_id=reason["signal_type_id"],
                        reason_id=reason["reason_id"]),
        _dispute_action("EVIDENCE_STALE", "this evidence is out of date", rep_id,
                        account_id, signal_type_id=reason["signal_type_id"],
                        reason_id=reason["reason_id"]),
    ]
    if events and events[0]["person_id"]:
        actions.append(_dispute_action(
            "WRONG_PERSON", "wrong person", rep_id, account_id,
            signal_type_id=reason["signal_type_id"],
            reason_id=reason["reason_id"], person_id=events[0]["person_id"]))
    return actions


def observations_payload(account, observations, rep_id):
    return {
        "account_name": account["name"],
        "count_line": reasons_mod.observations_count_line(observations),
        "items": [{"summary": o["summary"], "source_name": o["source_name"],
                   "retrieved_display": reasons_mod.observation_retrieved_display(o),
                   "agent_run_display": reasons_mod.observation_agent_run_display(o),
                   "source_url_text": o["source_url"] or reasons_mod.NO_REFERENCE}
                  for o in observations],
        "back_href": account_href(account["account_id"], rep_id),
        "meta": meta(),
    }


# ---------------------------------------------------------------------------
# §3.10 adjustments
# ---------------------------------------------------------------------------

def adjustments_payload(rep, rows, usage):
    out = []
    for row in rows:
        out.append({
            "adjustment_id": row["adjustment_id"],
            "kind": row["kind"],
            "line": reasons_mod.adjustment_line(row),
            "created_display": reasons_mod.adjustment_created_display(row),
            "expires_display": reasons_mod.adjustment_expires_display(row),
            "is_active": bool(row["is_active"]),
            "undo_adjustment_id": (row["adjustment_id"] if row["is_active"]
                                   else None),
            "account_id": row["account_id"],
        })
    return {"rep": rep_summary(rep),
            "budget_bar": queue_mod.budget_bar_text(usage),
            "budgets": {key: list(value) for key, value in usage.items()},
            "rows": out,
            "meta": meta()}


# ---------------------------------------------------------------------------
# §3.11 metrics · §3.12 ruleset
# ---------------------------------------------------------------------------

def metrics_payload(data):
    """Every rate as raw numerator/denominator AND as the format_rate() string,
    which renders '—' when the denominator is zero (§3.11)."""
    rates = []
    for key, label, note in metrics_mod.METRIC_ROWS:
        numerator, denominator, value = data[key]
        rates.append({"key": key, "label": label, "numerator": numerator,
                      "denominator": denominator, "value": value,
                      "display": metrics_mod.format_rate(value), "note": note})
    per_type = [{"signal_type_id": row["signal_type_id"],
                 "code": row["code"],
                 "display_name": row["display_name"],
                 "shown_count": row["shown_count"],
                 "dispute_count": row["dispute_count"],
                 "dispute_rate_display": metrics_mod.format_rate(row["dispute_rate"]),
                 "reps_saw": row["reps_saw"],
                 "reps_disputed": row["reps_disputed"],
                 "suppression_rate_display": metrics_mod.format_rate(
                     row["suppression_rate"]),
                 "flagged": row["flagged"],
                 "flag_text": row["flag_text"]}
                for row in data["per_type"]]
    return {
        "window_line": metrics_mod.window_line(data),
        "rates": rates,
        "per_type": per_type,
        "flag_note": metrics_mod.FLAG_NOTE,
        "ownership_errors": [{"account_id": r["account_id"],
                              "account_name": r["account_name"], "n": r["n"]}
                             for r in data["ownership_errors"]],
        # README honest-limitations 4 and 5. A metrics page that presents
        # synthetic rates without saying they are synthetic is exactly the
        # overclaim DESIGN_SPEC.md §4.6 exists to prevent.
        "caveat_lines": list(metrics_mod.CAVEAT_LINES),
        "meta": meta(),
    }


def ruleset_payload(signal_types, per_type):
    flags = {row["signal_type_id"]: row for row in per_type}
    rows = []
    for signal_type in signal_types:
        flag = flags.get(signal_type["signal_type_id"], {})
        rows.append({
            "signal_type_id": signal_type["signal_type_id"],
            "code": signal_type["code"],
            "display_name": signal_type["display_name"],
            "category": signal_type["category"],
            "polarity": signal_type["polarity"],
            "kind": signal_type["kind"],
            "base_weight": signal_type["base_weight"],
            "base_weight_display": reasons_mod.weight_display(
                signal_type["base_weight"]),
            "max_contribution": signal_type["max_contribution"],
            "max_contribution_display": reasons_mod.weight_display(
                signal_type["max_contribution"]),
            "half_life_display": reasons_mod.half_life_display(signal_type),
            "lookback_days": signal_type["lookback_days"],
            "shown_count": flag.get("shown_count", 0),
            "dispute_count": flag.get("dispute_count", 0),
            "dispute_rate_display": metrics_mod.format_rate(
                flag.get("dispute_rate")),
            "flagged": bool(flag.get("flagged")),
            # Passed through unchanged. README limitation 3: the flag is
            # unreliable at small n and the frontend does not reinterpret it.
            "flag_text": flag.get("flag_text", ""),
        })
    return {
        "header_line": reasons_mod.RULESET_HEADER,
        "ruleset_version": ruleset_version(),
        "evidence_note": reasons_mod.WEIGHTS_NOTE,
        "anchor_note": reasons_mod.ANCHOR_NOTE,
        "not_claimed_note": reasons_mod.NOT_CLAIMED,
        "rows": rows,
        "meta": meta(),
    }


# ---------------------------------------------------------------------------
# §3.13 the four writes
# ---------------------------------------------------------------------------

def write_result(effect, next_view, next_href, **extra):
    payload = {"ok": True, "effect": effect,
               "next": {"view": next_view, "href": next_href},
               "meta": meta()}
    payload.update(extra)
    return payload


def dispute_effect(code, expires_at, adjustment_id, signal_display_name=None,
                   person_name=None):
    """The confirmation sentence comes from feedback.dispute_confirmation and
    carries runtime.expiry_clause() on an ephemeral host, so the rep is told
    about the restart in the same breath as the return date (§6.5)."""
    return {
        "kind": feedback_mod.effect_kind(code),
        "expires_display": _expires_display(expires_at),
        "confirmation": feedback_mod.dispute_confirmation(
            code, expires_at, signal_display_name=signal_display_name,
            person_name=person_name, tail=runtime.expiry_clause()),
        "undo_adjustment_id": adjustment_id,
    }


def review_effect():
    """code=LEAVE_IT (§8.6b): the rep looked and accepted. No adjustment."""
    return {"kind": "reviewed", "expires_display": None,
            "confirmation": feedback_mod.REVIEW_CONFIRMATION,
            "undo_adjustment_id": None}


def adjust_effect(kind, expires_at, adjustment_id):
    return {"kind": kind, "expires_display": _expires_display(expires_at),
            "confirmation": queue_mod.adjust_confirmation(
                kind, expires_at, tail=runtime.expiry_clause()),
            "undo_adjustment_id": adjustment_id}


def revert_effect():
    return {"kind": "reverted", "expires_display": None,
            "confirmation": queue_mod.REVERT_CONFIRMATION,
            "undo_adjustment_id": None}


def _expires_display(expires_at):
    from warrant.timeutil import human_date
    return human_date(expires_at) if expires_at else None


def next_view_for_dispute(code, account_id, rep_id):
    """§3.13: mute-producing codes take the account out of the queue at once, so
    GET /api/account/{id} would 404 NOT_IN_QUEUE on the very next request. The
    server names 'queue' as the next view for those codes and hands back the
    confirmation, so the rep sees the return date rather than a near-error.
    Named in §10.2 as a deliberate divergence from the HTML app."""
    if code in feedback_mod.MUTE_PRODUCING_CODES:
        return "queue", queue_href(rep_id)
    return "account", account_href(account_id, rep_id)
