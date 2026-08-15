"""Warrant HTTP server. DESIGN_SPEC.md §6, §9.1.

http.server.ThreadingHTTPServer. Server-rendered HTML, no client framework, no
build step. Every action is a real <form> POST, so everything works with
JavaScript off.

Routes:
  GET  /                              index of reps
  GET  /queue?rep=1                   §6.1
  GET  /account/{id}?rep=1            §6.2
  GET  /evidence/{reason_id}?rep=1    §6.3
  GET  /evidence/observations/{id}    §6.2 "see all research"
  GET  /adjustments?rep=1             §7.3
  GET  /metrics                       §7.5
  GET  /ruleset                       §6.5
  POST /dispute                       §7.2
  POST /adjust                        §7.3
  POST /adjust/revert                 §7.3
  POST /task                          accepted / skipped instrumentation

JSON API (DEPLOY_ARCHITECTURE.md §3), same handler, same live queries:
  GET  /api/health                    §3.4  cheap; never scores
  GET  /api/reps                      §3.5
  GET  /api/queue?rep=1               §3.6
  GET  /api/account/{id}?rep=1        §3.7
  GET  /api/evidence/{reason_id}      §3.8  side effect: writes evidence_opened
  GET  /api/evidence/observations/{id} §3.9
  GET  /api/adjustments?rep=1         §3.10
  GET  /api/metrics                   §3.11
  GET  /api/ruleset                   §3.12
  POST /api/dispute · /api/adjust · /api/adjust/revert · /api/task   §3.13
  OPTIONS *                           §4.4  CORS preflight

Every score on every page is computed from a live query at request time. There
is no cache and no precomputed score literal anywhere in this file. The /api
routes call build_run() exactly like the HTML routes do — serving a queue or a
detail view from the persisted scores/reasons rows would be faster and would
break the guarantee that a dispute is visible on the very next render (§7.2).

---------------------------------------------------------------------------
THE SPLIT ADDED FOR PYTHONANYWHERE — DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md
---------------------------------------------------------------------------

This module used to define one class, `Handler(BaseHTTPRequestHandler)`, that
mixed two things together: the routing/business logic (which URL means which
query, which form field means which write) and the socket-specific plumbing
(reading `self.rfile`, writing `self.wfile`, calling `self.send_response()`).

PythonAnywhere's free tier does not run a raw socket server — it serves a WSGI
application through its own nginx/uwsgi stack, and `BaseHTTPRequestHandler` is
not WSGI. Rather than write a second copy of every route to satisfy that
(which is exactly the two-code-paths failure this whole product exists to
prevent — see `warrant/scoring.py`'s docstring), the routing/business logic
was pulled out into `WarrantRoutes`, a mixin with no socket dependency at all.
`Handler` below is now `BaseHTTPRequestHandler` plus `WarrantRoutes`, and
`wsgi.py` at the repo root is a small WSGI adapter that mixes the same
`WarrantRoutes` into a class with WSGI-shaped plumbing instead. Every route
method — `_queue`, `_detail`, `_api_dispute`, all of them — is defined exactly
once, in `WarrantRoutes`, and is reached by both entry points.

Nothing about local behaviour or the Render path changed: `python app.py`
still starts the same `ThreadingHTTPServer`, on the same routes, with the same
CORS decisions and the same bytes on the wire. This split is internal
structure, not a behaviour change — `tests/test_api.py`'s existing suite,
written against `app.Handler`, keeps passing unmodified against the same
class under its new composition.
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from warrant import api
from warrant import metrics as metrics_mod
from warrant import render
from warrant import runtime
from warrant.db import (as_of, bind_host, connect, origin_allowed, port,
                        ruleset_version)
from warrant.feedback import (DisputeError, disputes_for_account,
                              expired_dispute_banners, new_events_since_dispute,
                              record_dispute, record_review)
from warrant.queue import (BudgetExceeded, budget_usage, build_run,
                           create_adjustment, log_task_event, revert_adjustment)
from warrant.scoring import load_signal_types, requires_evidence_review
from warrant.timeutil import human_date, shift

BANNER = "warrant-app build-marker 2026-08-11 · live SQL per request, no cache"

# Printed at boot so a deploy log proves which build is actually running.
# Learned the hard way: a deploy that "succeeded" is not a deploy that shipped.
DEPLOY_MARKER = ("warrant-api build-marker 2026-08-13 · /api + CORS + do_OPTIONS "
                 "· DEPLOY_ARCHITECTURE.md §3/§4")

# §4.4: preflight permissions are cached for ten minutes. This caches the
# browser's permission decision, not a score, a reason or a row — it is not a
# violation of §7's no-caching rule and must not be removed as if it were.
PREFLIGHT_MAX_AGE = "600"
ALLOW_METHODS = "GET, POST, OPTIONS"
ALLOW_HEADERS = "Content-Type"


def cors_header_lines(origin):
    """§4.6, factored out so app.py's socket Handler and wsgi.py's WSGI
    adapter make byte-identical CORS decisions on every response — one
    function deciding, two transports emitting what it decides.

    `Vary: Origin` is always present. `Access-Control-Allow-Origin` is present
    only when `origin_allowed(origin)` (§4.2) — fail closed, and an Origin
    that is not on the allowlist gets the response without either the header
    or an error status; the browser discards the body itself (the §1.5 trap).
    """
    headers = [("Vary", "Origin")]
    if origin_allowed(origin):
        headers.append(("Access-Control-Allow-Origin", origin))
    return headers


def preflight_header_lines(origin):
    """§4.4's exact preflight response, as a header list rather than a
    sequence of `send_header()` calls, for the same reason as
    `cors_header_lines` above: one decision, shared by both entry points.

    200 with an explicit `Content-Length: 0` — not 204 (RFC 7230 forbids
    Content-Length on a 204, and HTTP/1.1 keep-alive needs every response
    self-framing). `Vary: Origin` always. The four `Access-Control-*` headers
    only when the Origin is on the allowlist; otherwise a disallowed Origin
    gets the same 200/Content-Length:0 with none of them — not a 403 — so the
    server never confirms or denies which origins are configured.
    """
    headers = [("Content-Length", "0"), ("Vary", "Origin")]
    if origin_allowed(origin):
        headers.append(("Access-Control-Allow-Origin", origin))
        headers.append(("Access-Control-Allow-Methods", ALLOW_METHODS))
        headers.append(("Access-Control-Allow-Headers", ALLOW_HEADERS))
        headers.append(("Access-Control-Max-Age", PREFLIGHT_MAX_AGE))
    return headers


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _one(params, key, default=None):
    values = params.get(key)
    return values[0] if values else default


def evidence_opened_this_session(conn, rep_id, account_id, now):
    """The friction gate clears as soon as one evidence drawer is opened.

    "This session" is read as: an evidence_opened task_event at or after the
    current as_of. Recorded in README.md under Deviations — the spec says
    "(rep, account, run)" and every render creates a new run, which would make
    the gate impossible to clear.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM task_events WHERE rep_id = ? AND account_id = ? "
        "AND event_type = ? AND occurred_at >= ?",
        (rep_id, account_id, "evidence_opened", now)).fetchone()
    return (row["n"] or 0) > 0


def friction_text(conn, rep_id, account, now):
    """§6.4. Returns the plain-text line, or None when there is no friction.

    Takes the account row rather than the AccountScore it used to take: the
    function never read anything off the score, and POST /api/task needs the
    same sentence for its 409 without having scored the account (§3.13). One
    sentence, one predicate, two call sites.
    """
    if not requires_evidence_review(conn, account, None, rep_id):
        return None
    if evidence_opened_this_session(conn, rep_id, account["account_id"], now):
        return None
    if (account["crm_status"] == "open_opportunity"
            and account["owner_rep_id"] != rep_id):
        owner = conn.execute("SELECT name FROM reps WHERE rep_id = ?",
                             (account["owner_rep_id"],)).fetchone()
        return ("Open evidence on one reason before working this — there is an "
                "open opportunity here owned by %s."
                % (owner["name"] if owner else "another rep"))
    row = conn.execute(
        "SELECT MAX(created_at) AS c FROM disagreements WHERE rep_id = ? "
        "AND account_id = ? AND status IN (?, ?)",
        (rep_id, account["account_id"], "open", "applied")).fetchone()
    when = human_date(row["c"]) if row and row["c"] else "recently"
    return ("Open evidence on one reason before working this — you disputed a "
            "reason on this account on %s." % when)


class WarrantRoutes:
    """Every route's business logic. No socket, no WSGI environ — nothing
    transport-specific at all.

    This class depends on exactly four methods being supplied by whatever it
    is mixed into: `self._send(status, html, content_type=...)`,
    `self._send_json(status, payload)`, `self._redirect(location)`, and
    `self._json_error(status, payload)` (the last is a one-line alias for
    `_send_json` in both concrete classes, kept separate only for readability
    at call sites). `app.py`'s `Handler` supplies socket-backed versions;
    `wsgi.py`'s WSGI adapter supplies versions that build a status/headers/body
    tuple for `start_response()` instead. Every method below is exactly what
    `Handler` used to contain directly (DEPLOY_ARCHITECTURE.md §2–§3 shaped
    all of it); nothing here was rewritten to make the split possible, only
    moved.
    """

    # -- GET handlers ------------------------------------------------------
    def _rep(self, conn, rep_id):
        row = conn.execute("SELECT * FROM reps WHERE rep_id = ?", (rep_id,)).fetchone()
        return dict(row) if row else None

    def _index(self, conn):
        reps = [dict(r) for r in conn.execute(
            "SELECT * FROM reps ORDER BY rep_id").fetchall()]
        self._send(200, render.render_index(reps))

    def _queue(self, conn, rep_id):
        rep = self._rep(conn, rep_id)
        if rep is None:
            return self._send(404, render.render_error("No such rep", str(rep_id)))
        now = as_of()
        run_id, items, _adj = build_run(conn, rep_id, now)
        log_task_event(conn, rep_id, "queue_viewed", now, run_id=run_id)
        conn.commit()
        friction_map = {i.score.account_id: friction_text(conn, rep_id,
                                                          i.score.account, now)
                        for i in items}
        friction_map = {k: v for k, v in friction_map.items() if v}
        self._send(200, render.render_queue(
            rep, run_id, items, budget_usage(conn, rep_id, now), now,
            ruleset_version(), friction_map))

    def _detail(self, conn, account_id, rep_id):
        rep = self._rep(conn, rep_id)
        if rep is None:
            return self._send(404, render.render_error("No such rep", str(rep_id)))
        now = as_of()
        # A fresh run, so a dispute made a moment ago is reflected here (§7.4).
        run_id, items, _adj = build_run(conn, rep_id, now)
        item = next((i for i in items if i.account_id == account_id), None)
        if item is None:
            return self._send(404, render.render_error(
                "Not in this queue",
                "Account %s is not in rep %s's queue right now. It may be muted, "
                "inactive, or owned by someone else." % (account_id, rep_id)))

        log_task_event(conn, rep_id, "item_viewed", now, account_id=account_id,
                       score_id=item.score_id, run_id=run_id,
                       rank_at_event=item.rank_in_queue)
        conn.commit()

        context = self._detail_context(conn, rep_id, item, now)
        self._send(200, render.render_detail(
            rep, item, budget_usage(conn, rep_id, now), now, ruleset_version(),
            len(items), context))

    def _detail_context(self, conn, rep_id, item, now):
        account_id = item.account_id
        reason_ids = dict(conn.execute(
            "SELECT signal_type_id, reason_id FROM reasons WHERE score_id = ?",
            (item.score_id,)).fetchall())

        history = disputes_for_account(conn, rep_id, account_id)

        suppression_notes = {}
        suppression_adjustments = {}
        new_events_notes = {}
        for row in conn.execute(
                "SELECT qa.adjustment_id, qa.signal_type_id, qa.created_at, "
                "       qa.expires_at, d.code "
                "FROM queue_adjustments qa "
                "LEFT JOIN disagreements d ON d.resulting_adjustment_id = qa.adjustment_id "
                "WHERE qa.rep_id = ? AND qa.kind = ? AND qa.is_active = ? "
                "  AND qa.expires_at > ? AND (qa.account_id = ? OR qa.account_id IS NULL)",
                (rep_id, "suppress_signal_type", 1, now, account_id)).fetchall():
            verb = ("You marked this out of date on %s."
                    if row["code"] == "EVIDENCE_STALE" else
                    "You said this was wrong on %s.")
            suppression_notes[row["signal_type_id"]] = (
                (verb % human_date(row["created_at"]))
                + " Not counted here until %s." % human_date(row["expires_at"]))
            suppression_adjustments[row["signal_type_id"]] = row["adjustment_id"]
            # §8.6(c): report new evidence, never auto-unsuppress.
            count, newest = new_events_since_dispute(
                conn, rep_id, account_id, row["signal_type_id"], row["created_at"], now)
            if count:
                new_events_notes[row["signal_type_id"]] = (
                    "%d new event%s for this signal since you disputed it "
                    "(most recent %s)." % (count, "" if count == 1 else "s",
                                           human_date(newest)))

        firing = {r.signal_type_id for r in item.all_reasons}
        expired_banners = expired_dispute_banners(conn, rep_id, account_id, now, firing)

        owner_id = item.score.account["owner_rep_id"]
        if owner_id == rep_id:
            owner_label = "you"
        elif owner_id is None:
            owner_label = "unassigned"
        else:
            row = conn.execute("SELECT name FROM reps WHERE rep_id = ?",
                               (owner_id,)).fetchone()
            owner_label = row["name"] if row else "another rep"

        observations = [dict(r) for r in conn.execute(
            "SELECT * FROM observations WHERE account_id = ? ORDER BY retrieved_at DESC",
            (account_id,)).fetchall()]

        top_person = None
        for reason in item.shown_reasons:
            if reason.contribution.top_person:
                top_person = reason.contribution.top_person
                break
        if top_person is None:
            row = conn.execute(
                "SELECT * FROM people WHERE account_id = ? ORDER BY person_id LIMIT 1",
                (account_id,)).fetchone()
            top_person = dict(row) if row else None

        return {"reason_ids": reason_ids, "history": history,
                "suppression_notes": suppression_notes,
                "suppression_adjustments": suppression_adjustments,
                "new_events_notes": new_events_notes,
                "expired_banners": expired_banners, "owner_label": owner_label,
                "observations": observations, "top_person": top_person}

    def _evidence(self, conn, reason_id, rep_id):
        row = conn.execute(
            "SELECT r.*, st.display_name, st.max_contribution, st.code, "
            "       s.account_id, s.run_id "
            "FROM reasons r JOIN signal_types st ON st.signal_type_id = r.signal_type_id "
            "JOIN scores s ON s.score_id = r.score_id WHERE r.reason_id = ?",
            (reason_id,)).fetchone()
        if row is None:
            return self._send(404, render.render_error("No such reason", str(reason_id)))
        reason = dict(row)
        account = dict(conn.execute("SELECT * FROM accounts WHERE account_id = ?",
                                    (reason["account_id"],)).fetchone())
        events = [dict(r) for r in conn.execute(
            "SELECT re.contribution, se.*, p.full_name, p.title "
            "FROM reason_evidence re JOIN signal_events se ON se.event_id = re.event_id "
            "LEFT JOIN people p ON p.person_id = se.person_id "
            "WHERE re.reason_id = ? ORDER BY se.occurred_at DESC",
            (reason_id,)).fetchall()]
        observations = [dict(r) for r in conn.execute(
            "SELECT * FROM observations WHERE account_id = ? ORDER BY retrieved_at DESC "
            "LIMIT 3", (reason["account_id"],)).fetchall()]

        now = as_of()
        log_task_event(conn, rep_id, "evidence_opened", now,
                       account_id=reason["account_id"], score_id=reason["score_id"],
                       run_id=reason["run_id"],
                       detail={"signal_type_id": reason["signal_type_id"]})
        conn.commit()
        self._send(200, render.render_evidence(rep_id, reason, account, events, now,
                                               observations))

    def _observations(self, conn, account_id, rep_id):
        account = conn.execute("SELECT * FROM accounts WHERE account_id = ?",
                               (account_id,)).fetchone()
        if account is None:
            return self._send(404, render.render_error("No such account", str(account_id)))
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM observations WHERE account_id = ? ORDER BY retrieved_at DESC",
            (account_id,)).fetchall()]
        self._send(200, render.render_observations(dict(account), rows, rep_id))

    def _adjustments(self, conn, rep_id):
        rep = self._rep(conn, rep_id)
        if rep is None:
            return self._send(404, render.render_error("No such rep", str(rep_id)))
        now = as_of()
        rows = [dict(r) for r in conn.execute(
            "SELECT qa.*, a.name AS account_name, st.display_name AS signal_display_name "
            "FROM queue_adjustments qa "
            "LEFT JOIN accounts a ON a.account_id = qa.account_id "
            "LEFT JOIN signal_types st ON st.signal_type_id = qa.signal_type_id "
            "WHERE qa.rep_id = ? ORDER BY qa.adjustment_id DESC", (rep_id,)).fetchall()]
        self._send(200, render.render_adjustments(
            rep, rows, budget_usage(conn, rep_id, now), now))

    def _metrics(self, conn):
        self._send(200, render.render_metrics(metrics_mod.collect(conn, as_of())))

    def _ruleset(self, conn):
        now = as_of()
        types = load_signal_types(conn)
        per_type = metrics_mod.reason_dispute_rates(conn, now)
        self._send(200, render.render_ruleset(types, per_type, ruleset_version()))

    # -- GET / POST dispatch -------------------------------------------------
    # The one dispatch table for each verb, shared by app.py's Handler and
    # wsgi.py's WSGI adapter. `path` is used only for the 404 message; `parts`
    # / `params` / `form` are already parsed by the caller, because how they
    # are parsed off the wire (self.path + self.rfile vs. environ +
    # wsgi.input) is the one thing that legitimately differs by transport.

    def _route_get(self, conn, path, parts, params):
        if parts and parts[0] == "api":
            return self._api_get(conn, parts[1:], params)
        if not parts:
            return self._index(conn)
        if parts[0] == "queue":
            return self._queue(conn, _int(_one(params, "rep"), 1))
        if parts[0] == "account" and len(parts) == 2:
            return self._detail(conn, _int(parts[1]), _int(_one(params, "rep"), 1))
        if parts[0] == "evidence" and len(parts) == 3 and parts[1] == "observations":
            return self._observations(conn, _int(parts[2]),
                                      _int(_one(params, "rep"), 1))
        if parts[0] == "evidence" and len(parts) == 2:
            return self._evidence(conn, _int(parts[1]), _int(_one(params, "rep"), 1))
        if parts[0] == "adjustments":
            return self._adjustments(conn, _int(_one(params, "rep"), 1))
        if parts[0] == "metrics":
            return self._metrics(conn)
        if parts[0] == "ruleset":
            return self._ruleset(conn)
        return self._send(404, render.render_error("Not found", path))

    def _route_post(self, conn, path, form):
        if path.startswith("/api/"):
            return self._api_post(conn, path, form)
        if path == "/dispute":
            return self._post_dispute(conn, form)
        if path == "/adjust":
            return self._post_adjust(conn, form)
        if path == "/adjust/revert":
            return self._post_revert(conn, form)
        if path == "/task":
            return self._post_task(conn, form)
        return self._send(404, render.render_error("Not found", path))

    # -- POST handlers -----------------------------------------------------
    def _post_dispute(self, conn, form):
        rep_id = _int(_one(form, "rep"))
        account_id = _int(_one(form, "account"))
        code = _one(form, "code")
        now = as_of()

        if code == "LEAVE_IT":
            record_review(conn, rep_id, account_id,
                          _int(_one(form, "signal_type")), now)
            return self._redirect("/account/%d?rep=%d&reviewed=1" % (account_id, rep_id))

        try:
            disagreement_id, _adj = record_dispute(
                conn, rep_id, account_id, code, now,
                reason_id=_int(_one(form, "reason")),
                signal_type_id=_int(_one(form, "signal_type")),
                person_id=_int(_one(form, "person")),
                note=_one(form, "note"),
                window_days=_int(_one(form, "window")),
                rank_at_event=_int(_one(form, "rank")))
        except BudgetExceeded as exc:
            return self._send(409, render.render_budget_exceeded(rep_id, exc))
        except Exception as exc:                       # noqa: BLE001 - shown to the rep
            return self._send(400, render.render_error("Could not record that", str(exc)))

        # §7.4: redirect straight back into a fresh scoring run so the rep sees
        # the reason struck through and the points drop immediately.
        return self._redirect("/account/%d?rep=%d&disputed=%d"
                              % (account_id, rep_id, disagreement_id))

    def _post_adjust(self, conn, form):
        rep_id = _int(_one(form, "rep"))
        account_id = _int(_one(form, "account"))
        kind = _one(form, "kind")
        days = _int(_one(form, "days"), 30)
        now = as_of()
        try:
            adjustment_id = create_adjustment(conn, rep_id, kind, now,
                                              shift(now, days=days),
                                              account_id=account_id)
        except BudgetExceeded as exc:
            return self._send(409, render.render_budget_exceeded(rep_id, exc))
        log_task_event(conn, rep_id, "adjusted", now, account_id=account_id,
                       detail={"kind": kind, "adjustment_id": adjustment_id})
        conn.commit()
        return self._redirect("/account/%d?rep=%d&adjusted=%d"
                              % (account_id, rep_id, adjustment_id))

    def _post_revert(self, conn, form):
        rep_id = _int(_one(form, "rep"))
        adjustment_id = _int(_one(form, "adjustment"))
        account_id = _int(_one(form, "account"))
        revert_adjustment(conn, rep_id, adjustment_id, as_of())
        conn.commit()
        if account_id:
            return self._redirect("/account/%d?rep=%d&reverted=%d"
                                  % (account_id, rep_id, adjustment_id))
        return self._redirect("/adjustments?rep=%d" % rep_id)

    def _post_task(self, conn, form):
        rep_id = _int(_one(form, "rep"))
        account_id = _int(_one(form, "account"))
        rank = _int(_one(form, "rank"))
        action = _one(form, "action")
        if action not in ("accepted", "skipped"):
            return self._send(400, render.render_error("Unknown action", str(action)))
        now = as_of()

        if action == "accepted":
            # The disabled button is a UI affordance; this is the enforcement.
            row = conn.execute("SELECT * FROM accounts WHERE account_id = ?",
                               (account_id,)).fetchone()
            if row is not None:
                account = dict(row)
                if (requires_evidence_review(conn, account, None, rep_id)
                        and not evidence_opened_this_session(conn, rep_id, account_id, now)):
                    return self._send(409, render.render_error(
                        "Open the evidence first",
                        "This account needs one evidence drawer opened before it "
                        "can be worked. See §6.4 of the design spec.",
                        "<p><a href=\"/account/%d?rep=%d\">open the account</a></p>"
                        % (account_id, rep_id)))

        log_task_event(conn, rep_id, action, now, account_id=account_id,
                       rank_at_event=rank)
        conn.commit()
        return self._redirect("/queue?rep=%d" % rep_id)

    # ======================================================================
    # JSON API (DEPLOY_ARCHITECTURE.md §3)
    #
    # These handlers do exactly what their HTML twins do — same build_run(),
    # same task_events, same budget enforcement — and hand the result to
    # warrant/api.py to serialise. No handler here reads a persisted score or
    # reason row instead of re-scoring (§7.2 item 3).
    # ======================================================================

    def _api_get(self, conn, parts, params):
        rep_id = _int(_one(params, "rep"), 1)
        try:
            if parts == ["health"]:
                return self._api_health(conn)
            if parts == ["reps"]:
                return self._api_reps(conn)
            if parts == ["queue"]:
                return self._api_queue(conn, rep_id)
            if len(parts) == 2 and parts[0] == "account":
                return self._api_detail(conn, _int(parts[1]), rep_id)
            if len(parts) == 3 and parts[:2] == ["evidence", "observations"]:
                return self._api_observations(conn, _int(parts[2]), rep_id)
            if len(parts) == 2 and parts[0] == "evidence":
                return self._api_evidence(conn, _int(parts[1]), rep_id)
            if parts == ["adjustments"]:
                return self._api_adjustments(conn, rep_id)
            if parts == ["metrics"]:
                return self._send_json(200, api.metrics_payload(
                    metrics_mod.collect(conn, as_of())))
            if parts == ["ruleset"]:
                return self._api_ruleset(conn)
        except Exception as exc:                       # noqa: BLE001
            return self._api_internal(exc)
        return self._json_error(404, api.error_payload(
            api.NOT_FOUND, api.NOT_FOUND_TITLE, api.ROUTE_NOT_FOUND_MESSAGE))

    def _api_internal(self, exc):
        """§3.3: the exception text goes to stderr, never to the browser."""
        sys.stderr.write("api error: %r\n" % (exc,))
        sys.stderr.flush()
        return self._json_error(500, api.error_payload(
            api.INTERNAL, api.INTERNAL_TITLE, api.INTERNAL_MESSAGE))

    def _api_rep_or_404(self, conn, rep_id):
        rep = self._rep(conn, rep_id)
        if rep is None:
            self._json_error(404, api.error_payload(
                api.NOT_FOUND, api.NOT_FOUND_TITLE, api.REP_NOT_FOUND_MESSAGE,
                detail={"rep_id": rep_id}))
        return rep

    def _api_health(self, conn):
        """§3.4. One COUNT and one SELECT. This endpoint must never score —
        it is polled every 3 seconds while the container wakes, and a queue
        render is ~1,900 SQL statements."""
        try:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM accounts").fetchone()["n"] or 0
            reps = [dict(r) for r in conn.execute(
                "SELECT * FROM reps ORDER BY rep_id").fetchall()]
        except Exception:                              # noqa: BLE001
            # Missing table = the seeder never ran. §9.6 is the rep-facing state.
            count, reps = 0, []
        self._send_json(200, api.health_payload(count > 0, count, reps))

    def _api_reps(self, conn):
        reps = [dict(r) for r in conn.execute(
            "SELECT * FROM reps ORDER BY rep_id").fetchall()]
        self._send_json(200, api.reps_payload(reps))

    def _api_queue(self, conn, rep_id):
        rep = self._api_rep_or_404(conn, rep_id)
        if rep is None:
            return None
        now = as_of()
        run_id, items, _adj = build_run(conn, rep_id, now)
        log_task_event(conn, rep_id, "queue_viewed", now, run_id=run_id)
        conn.commit()
        friction_map = {}
        for item in items:
            sentence = friction_text(conn, rep_id, item.score.account, now)
            if sentence:
                friction_map[item.account_id] = sentence
        self._send_json(200, api.queue_payload(
            rep, run_id, items, budget_usage(conn, rep_id, now), friction_map))

    def _api_detail(self, conn, account_id, rep_id):
        rep = self._api_rep_or_404(conn, rep_id)
        if rep is None:
            return None
        now = as_of()
        # A fresh run, so a dispute made a moment ago is reflected here (§7.4).
        run_id, items, _adj = build_run(conn, rep_id, now)
        item = next((i for i in items if i.account_id == account_id), None)
        if item is None:
            return self._json_error(404,
                                    api.not_in_queue_error(account_id, rep_id))
        log_task_event(conn, rep_id, "item_viewed", now, account_id=account_id,
                       score_id=item.score_id, run_id=run_id,
                       rank_at_event=item.rank_in_queue)
        conn.commit()
        context = self._detail_context(conn, rep_id, item, now)
        self._send_json(200, api.detail_payload(
            rep, item, budget_usage(conn, rep_id, now), len(items), context))

    def _api_evidence(self, conn, reason_id, rep_id):
        """§3.8. Writes evidence_opened, which is what clears the §6.4 gate."""
        row = conn.execute(
            "SELECT r.*, st.display_name, st.max_contribution, st.code, "
            "       s.account_id, s.run_id "
            "FROM reasons r JOIN signal_types st ON st.signal_type_id = r.signal_type_id "
            "JOIN scores s ON s.score_id = r.score_id WHERE r.reason_id = ?",
            (reason_id,)).fetchone()
        if row is None:
            return self._json_error(404, api.error_payload(
                api.NOT_FOUND, api.NOT_FOUND_TITLE, api.REASON_NOT_FOUND_MESSAGE,
                detail={"reason_id": reason_id}))
        reason = dict(row)
        account = dict(conn.execute("SELECT * FROM accounts WHERE account_id = ?",
                                    (reason["account_id"],)).fetchone())
        events = [dict(r) for r in conn.execute(
            "SELECT re.contribution, se.*, p.full_name, p.title "
            "FROM reason_evidence re JOIN signal_events se ON se.event_id = re.event_id "
            "LEFT JOIN people p ON p.person_id = se.person_id "
            "WHERE re.reason_id = ? ORDER BY se.occurred_at DESC",
            (reason_id,)).fetchall()]
        observations = [dict(r) for r in conn.execute(
            "SELECT * FROM observations WHERE account_id = ? ORDER BY retrieved_at DESC "
            "LIMIT 3", (reason["account_id"],)).fetchall()]
        now = as_of()
        log_task_event(conn, rep_id, "evidence_opened", now,
                       account_id=reason["account_id"], score_id=reason["score_id"],
                       run_id=reason["run_id"],
                       detail={"signal_type_id": reason["signal_type_id"]})
        conn.commit()
        self._send_json(200, api.evidence_payload(rep_id, reason, account, events,
                                                  observations))

    def _api_observations(self, conn, account_id, rep_id):
        row = conn.execute("SELECT * FROM accounts WHERE account_id = ?",
                           (account_id,)).fetchone()
        if row is None:
            return self._json_error(404, api.error_payload(
                api.NOT_FOUND, api.NOT_FOUND_TITLE, api.ACCOUNT_NOT_FOUND_MESSAGE,
                detail={"account_id": account_id}))
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM observations WHERE account_id = ? ORDER BY retrieved_at DESC",
            (account_id,)).fetchall()]
        self._send_json(200, api.observations_payload(dict(row), rows, rep_id))

    def _api_adjustments(self, conn, rep_id):
        rep = self._api_rep_or_404(conn, rep_id)
        if rep is None:
            return None
        now = as_of()
        rows = [dict(r) for r in conn.execute(
            "SELECT qa.*, a.name AS account_name, st.display_name AS signal_display_name "
            "FROM queue_adjustments qa "
            "LEFT JOIN accounts a ON a.account_id = qa.account_id "
            "LEFT JOIN signal_types st ON st.signal_type_id = qa.signal_type_id "
            "WHERE qa.rep_id = ? ORDER BY qa.adjustment_id DESC", (rep_id,)).fetchall()]
        self._send_json(200, api.adjustments_payload(
            rep, rows, budget_usage(conn, rep_id, now)))

    def _api_ruleset(self, conn):
        now = as_of()
        self._send_json(200, api.ruleset_payload(
            load_signal_types(conn), metrics_mod.reason_dispute_rates(conn, now)))

    # -- API writes (§3.13) ------------------------------------------------

    def _api_post(self, conn, path, form):
        try:
            if path == "/api/dispute":
                return self._api_dispute(conn, form)
            if path == "/api/adjust":
                return self._api_adjust(conn, form)
            if path == "/api/adjust/revert":
                return self._api_revert(conn, form)
            if path == "/api/task":
                return self._api_task(conn, form)
        except BudgetExceeded as exc:
            return self._json_error(409, api.budget_error(
                exc, _int(_one(form, "rep"), 1)))
        except DisputeError as exc:
            return self._json_error(400, api.error_payload(
                api.BAD_REQUEST, api.BAD_REQUEST_TITLE, str(exc)))
        except Exception as exc:                       # noqa: BLE001
            return self._api_internal(exc)
        return self._json_error(404, api.error_payload(
            api.NOT_FOUND, api.NOT_FOUND_TITLE, api.ROUTE_NOT_FOUND_MESSAGE))

    def _api_bad_request(self, message, detail=None):
        return self._json_error(400, api.error_payload(
            api.BAD_REQUEST, api.BAD_REQUEST_TITLE, message, detail=detail))

    def _api_dispute(self, conn, form):
        rep_id = _int(_one(form, "rep"))
        account_id = _int(_one(form, "account"))
        code = _one(form, "code")
        if rep_id is None or account_id is None or not code:
            return self._api_bad_request(
                "A dispute needs a rep, an account and a code.")
        now = as_of()

        if code == "LEAVE_IT":
            record_review(conn, rep_id, account_id,
                          _int(_one(form, "signal_type")), now)
            return self._send_json(200, api.write_result(
                api.review_effect(), "account",
                api.account_href(account_id, rep_id)))

        disagreement_id, adjustment_id = record_dispute(
            conn, rep_id, account_id, code, now,
            reason_id=_int(_one(form, "reason")),
            signal_type_id=_int(_one(form, "signal_type")),
            person_id=_int(_one(form, "person")),
            note=_one(form, "note"),
            window_days=_int(_one(form, "window")),
            rank_at_event=_int(_one(form, "rank")))

        expires_at = self._expires_of(conn, adjustment_id)
        view, href = api.next_view_for_dispute(code, account_id, rep_id)
        self._send_json(200, api.write_result(
            api.dispute_effect(
                code, expires_at, adjustment_id,
                signal_display_name=self._signal_name(
                    conn, _int(_one(form, "signal_type"))),
                person_name=self._person_name(conn, _int(_one(form, "person")))),
            view, href, disagreement_id=disagreement_id))

    def _api_adjust(self, conn, form):
        rep_id = _int(_one(form, "rep"))
        account_id = _int(_one(form, "account"))
        kind = _one(form, "kind")
        days = _int(_one(form, "days"), 30)
        if rep_id is None or account_id is None or kind not in (
                "pin", "demote", "mute_account"):
            return self._api_bad_request(
                "An adjustment needs a rep, an account and a kind of pin, "
                "demote or mute_account.")
        now = as_of()
        expires_at = shift(now, days=days)
        adjustment_id = create_adjustment(conn, rep_id, kind, now, expires_at,
                                          account_id=account_id)
        log_task_event(conn, rep_id, "adjusted", now, account_id=account_id,
                       detail={"kind": kind, "adjustment_id": adjustment_id})
        conn.commit()
        if kind == "mute_account":
            view, href = "queue", api.queue_href(rep_id)
        else:
            view, href = "account", api.account_href(account_id, rep_id)
        self._send_json(200, api.write_result(
            api.adjust_effect(kind, expires_at, adjustment_id), view, href,
            adjustment_id=adjustment_id))

    def _api_revert(self, conn, form):
        rep_id = _int(_one(form, "rep"))
        adjustment_id = _int(_one(form, "adjustment"))
        account_id = _int(_one(form, "account"))
        if rep_id is None or adjustment_id is None:
            return self._api_bad_request(
                "A revert needs a rep and an adjustment.")
        row = revert_adjustment(conn, rep_id, adjustment_id, as_of())
        conn.commit()
        if row is None:
            # queue.revert_adjustment() returns None for an adjustment that does
            # not belong to this rep and writes nothing. The HTML path still
            # 303s, which reads as success. §10.2 names this 404 as a
            # deliberate, small hardening over today's behaviour.
            return self._json_error(404, api.error_payload(
                api.NOT_FOUND, api.NOT_FOUND_TITLE,
                "No adjustment %s belongs to you." % adjustment_id,
                detail={"adjustment_id": adjustment_id}))
        if account_id:
            view, href = "account", api.account_href(account_id, rep_id)
        else:
            view, href = "adjustments", api.adjustments_href(rep_id)
        self._send_json(200, api.write_result(
            api.revert_effect(), view, href, adjustment_id=adjustment_id))

    def _api_task(self, conn, form):
        rep_id = _int(_one(form, "rep"))
        account_id = _int(_one(form, "account"))
        rank = _int(_one(form, "rank"))
        action = _one(form, "action")
        if action not in ("accepted", "skipped"):
            return self._api_bad_request(
                "Unknown action. Expected accepted or skipped.",
                detail={"action": action})
        now = as_of()
        if action == "accepted":
            # The disabled button is a UI affordance; this is the enforcement
            # (README deviation 11). Both must be present.
            row = conn.execute("SELECT * FROM accounts WHERE account_id = ?",
                               (account_id,)).fetchone()
            if row is not None:
                sentence = friction_text(conn, rep_id, dict(row), now)
                if sentence:
                    return self._json_error(409, api.evidence_required_error(
                        sentence, account_id, rep_id))
        log_task_event(conn, rep_id, action, now, account_id=account_id,
                       rank_at_event=rank)
        conn.commit()
        self._send_json(200, api.write_result(
            None, "queue", api.queue_href(rep_id)))

    def _expires_of(self, conn, adjustment_id):
        row = conn.execute(
            "SELECT expires_at FROM queue_adjustments WHERE adjustment_id = ?",
            (adjustment_id,)).fetchone()
        return row["expires_at"] if row else None

    def _signal_name(self, conn, signal_type_id):
        if signal_type_id is None:
            return None
        row = conn.execute(
            "SELECT display_name FROM signal_types WHERE signal_type_id = ?",
            (signal_type_id,)).fetchone()
        return row["display_name"] if row else None

    def _person_name(self, conn, person_id):
        if person_id is None:
            return None
        row = conn.execute("SELECT full_name FROM people WHERE person_id = ?",
                           (person_id,)).fetchone()
        return row["full_name"] if row else None


class Handler(BaseHTTPRequestHandler, WarrantRoutes):
    """The socket transport. Everything route-shaped lives in `WarrantRoutes`
    above; everything here is specifically about being a
    `BaseHTTPRequestHandler` — reading `self.rfile`, writing `self.wfile`,
    calling `self.send_response()`. `wsgi.py`'s WSGI adapter is the other
    transport over the same `WarrantRoutes`.
    """

    server_version = "Warrant/1.0"
    protocol_version = "HTTP/1.1"

    # -- plumbing ----------------------------------------------------------
    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status, html, content_type="text/html; charset=utf-8"):
        payload = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # -- CORS (§4) ---------------------------------------------------------
    def _cors_headers(self):
        """Emit the two CORS lines only when this request's Origin is on the
        allowlist (§4.6). Absent Origin, or an Origin that is not allowed, gets
        the response without them — the response is produced normally and the
        browser discards it. That is the §1.5 trap, and it is why the frontend
        has a dedicated CORS state (§9.3).

        Vary: Origin is always sent. Without it an intermediary cache could
        hand one origin's Access-Control-Allow-Origin to another.

        The decision itself lives in `cors_header_lines()` above, shared with
        wsgi.py, so this method is only the socket-specific act of emitting it.
        """
        for name, value in cors_header_lines(self.headers.get("Origin")):
            self.send_header(name, value)

    def _send_json(self, status, payload):
        """§3.1/§4.6. Content-Length always set — protocol_version is HTTP/1.1,
        keep-alive is on, and every response must be self-framing."""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # §7.2 item 4: no-store, and no ETag or Last-Modified. Render sits
        # behind a CDN edge; a cacheable /api/queue would be served from that
        # edge and the rep would see a stale queue while the backend logs
        # nothing at all.
        self.send_header("Cache-Control", "no-store")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _json_error(self, status, payload):
        self._send_json(status, payload)

    def do_OPTIONS(self):
        """§4.4. 200 with Content-Length: 0 — NOT 204.

        RFC 7230 forbids Content-Length on a 204, and protocol_version is
        HTTP/1.1, so framing must be unambiguous or the connection
        desynchronises. _redirect() already established this pattern in this
        codebase. The CORS spec accepts any 2xx for a preflight. Do not "fix"
        this to 204.

        An Origin that is not on the allowlist gets the same 200 with no CORS
        headers — not a 403. The browser then blocks the real request, which is
        the correct outcome, and the server has not leaked which origins are
        configured.

        The header list is `preflight_header_lines()` above, shared with
        wsgi.py — this method only emits it over the socket.
        """
        origin = self.headers.get("Origin")
        self.send_response(200)
        for name, value in preflight_header_lines(origin):
            self.send_header(name, value)
        self.end_headers()

    def _form(self):
        length = _int(self.headers.get("Content-Length"), 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        return parse_qs(raw, keep_blank_values=True)

    # -- routing -------------------------------------------------------------
    # Both methods below do nothing but parse the socket-specific request
    # shape into (conn, path, parts/params/form) and hand off to
    # WarrantRoutes._route_get / _route_post — the one dispatch table, shared
    # with wsgi.py.
    def do_GET(self):
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        params = parse_qs(parsed.query)
        conn = connect()
        try:
            return self._route_get(conn, self.path, parts, params)
        finally:
            conn.close()

    def do_POST(self):
        parsed = urlparse(self.path)
        form = self._form()
        conn = connect()
        try:
            return self._route_post(conn, parsed.path, form)
        finally:
            conn.close()


def main():
    listen_port = port()
    host = bind_host()
    server = ThreadingHTTPServer((host, listen_port), Handler)
    print(BANNER)
    print(DEPLOY_MARKER)
    print("Warrant listening on http://%s:%d/queue?rep=1" % (host, listen_port))
    print("as_of=%s ruleset=%s" % (as_of(), ruleset_version()))
    print(runtime.describe())
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
