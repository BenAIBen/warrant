"""HTML rendering. DESIGN_SPEC.md §6.

Plain str templates, html.escape on every interpolated value. No f-string HTML
without escaping, no client framework, no build step. Every action is a real
<form> POST so the whole product works with JavaScript off.

Screen order is fixed by §6.2 and it matters: evidence first, priority second.
Within a reason: category tag -> sentence -> evidence line -> points -> actions.
The point value comes after the evidence, never before it (implication #3).
"""

from html import escape

from warrant import metrics as metrics_mod
from warrant import queue as queue_mod
from warrant import reasons as reasons_mod
from warrant.feedback import CODE_LABELS, wrong_person_label
from warrant.queue import BUDGETS, BUDGET_LABELS
from warrant.timeutil import human_date, human_datetime

CSS = """
body{font:14px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
 max-width:900px;margin:0 auto;padding:24px 18px 80px;color:#101418;background:#fbfbf9}
a{color:#14417a}
h1,h2,h3{font-weight:600;letter-spacing:.02em}
h1{font-size:17px;margin:0 0 2px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.12em;color:#5b6570;
 margin:30px 0 8px;border-bottom:1px solid #e2e2dd;padding-bottom:6px}
.meta{color:#5b6570;font-size:12.5px}
.rule{border:0;border-top:1px solid #e2e2dd;margin:14px 0}
.chip{display:inline-block;border:1px solid #b9bfc6;border-radius:2px;padding:0 6px;
 font-size:11.5px;letter-spacing:.06em;background:#fff}
.chip.act{border-color:#1c6b3c;color:#12522d;background:#eaf6ef}
.chip.rev{border-color:#8a6a12;color:#6b520c;background:#fdf6e6}
.chip.hold{border-color:#5b6570;color:#4a525b;background:#f2f3f4}
.chip.none{border-color:#8b8f95;color:#5b6570;background:#f7f7f5;font-style:italic}
.chip.adj{border-color:#14417a;color:#14417a;background:#eef3fa}
.chip.stale{border-color:#9a3412;color:#7c2d12;background:#fdf0ea}
.row{padding:12px 0;border-top:1px solid #e2e2dd}
.rank{display:inline-block;width:30px;color:#5b6570}
.pts{float:right;font-variant-numeric:tabular-nums}
.reason{padding:14px 0;border-top:1px solid #e2e2dd}
.cat{font-size:11px;letter-spacing:.14em;color:#5b6570}
.sentence{margin:4px 0 2px;font-size:14.5px}
.evidence{color:#5b6570;font-size:12.5px}
.rpts{float:right;font-variant-numeric:tabular-nums;color:#3b4148}
.limits{background:#f4f4f0;border-left:3px solid #b9bfc6;padding:9px 12px;margin:16px 0;
 font-size:13px}
.banner{background:#fdf6e6;border-left:3px solid #8a6a12;padding:9px 12px;margin:12px 0;
 font-size:13px}
.banner.warn{background:#fdf0ea;border-left-color:#9a3412}
.struck{text-decoration:line-through;color:#7a828b}
form{display:inline}
button{font:inherit;font-size:12.5px;padding:2px 9px;border:1px solid #8b8f95;
 background:#fff;border-radius:2px;cursor:pointer}
button:disabled{color:#9aa0a6;border-color:#d6d9dc;cursor:not-allowed}
button.primary{border-color:#1c6b3c;color:#12522d}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid #e8e8e3}
th{color:#5b6570;font-weight:600;font-size:11.5px;letter-spacing:.06em}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.flagged{background:#fdf0ea}
.footer{margin-top:44px;font-size:12px;color:#5b6570}
"""

BAND_CLASS = {"ACT_NOW": "act", "REVIEW": "rev", "HOLD": "hold",
              "INSUFFICIENT_EVIDENCE": "none"}


def e(value):
    return escape("" if value is None else str(value), quote=True)


def page(title, body):
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>%s</title><style>%s</style></head><body>%s</body></html>"
            % (e(title), CSS, body))


def band_chip(band):
    return "<span class=\"chip %s\">%s</span>" % (
        BAND_CLASS[band], e(reasons_mod.band_label(band)))


def _points_display(points):
    """§5.1: rounded integer, sign only when negative. 59.87 -> 60.

    Moved to reasons.py::points_display so the JSON path shares the one copy
    (DEPLOY_ARCHITECTURE.md §2.5, §10.3 open question 1). Kept here as a
    delegating alias because this name appears in §2.4's split table.
    """
    return reasons_mod.points_display(points)


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

def render_index(reps):
    rows = "".join(
        "<div class=\"row\"><a href=\"/queue?rep=%s\">%s</a> "
        "<span class=\"meta\">· %s · %s</span></div>"
        % (e(r["rep_id"]), e(r["name"]), e(r["territory"]), e(r["email"]))
        for r in reps)
    body = ("<h1>Warrant</h1><p class=\"meta\">Reason-first prioritisation. "
            "Pick a rep to open their queue.</p>%s"
            "<p class=\"footer\"><a href=\"/metrics\">metrics</a> · "
            "<a href=\"/ruleset\">how the weights are set</a></p>" % rows)
    return page("Warrant", body)


# ---------------------------------------------------------------------------
# §6.1 Queue view
# ---------------------------------------------------------------------------

def budget_bar(usage, rep_id):
    return ("<p class=\"meta\">Your adjustments: <a href=\"/adjustments?rep=%s\">%s</a></p>"
            % (e(rep_id), e(queue_mod.budget_bar_text(usage))))


def render_queue(rep, run_id, items, usage, as_of, ruleset, friction_map):
    header = "<h1>%s</h1>" % e(reasons_mod.queue_header_line(rep))
    stamp = ("<p class=\"meta\">%s</p>"
             % e(reasons_mod.run_stamp(as_of, ruleset, len(items), run_id)))

    rows = []
    for item in items:
        score = item.score
        chips = [band_chip(score.band)]
        adj_chip = reasons_mod.adjustment_chip(score)
        fresh = reasons_mod.freshness_chip(score)

        top_reason = (reasons_mod.truncate_at_word(item.shown_reasons[0].text)
                      if item.shown_reasons else reasons_mod.thin_data_line(score)
                      or reasons_mod.NO_SIGNALS_LINE)

        friction = friction_map.get(score.account_id)
        work_button = ("<button class=\"primary\" type=\"submit\">Work it</button>"
                       if not friction else
                       "<button type=\"submit\" disabled title=\"%s\">Work it</button>" % e(friction))

        rows.append(
            "<div class=\"row\">"
            "<span class=\"pts\">%s pts</span>"
            "<span class=\"rank\">%d.</span> %s "
            "<a href=\"/account/%s?rep=%s\">%s</a> %s"
            "<div class=\"sentence\">%s</div>"
            "<div class=\"meta\"><span class=\"chip %s\">%s</span> "
            "<span style=\"float:right\">%s</span></div>"
            "<div style=\"margin-top:7px\">%s%s"
            "<a href=\"/account/%s?rep=%s#dispute\">Dispute</a></div>"
            "%s"
            "</div>"
            % (e(_points_display(score.points)), item.rank_in_queue,
               "".join(chips), e(score.account_id), e(rep["rep_id"]),
               e(score.account["name"]),
               ("<span class=\"chip adj\">%s</span>" % e(adj_chip)) if adj_chip else "",
               e(top_reason),
               "stale" if fresh.startswith("STALE") else "",
               e(fresh),
               e(reasons_mod.compressed_limits(item.all_reasons, item.shown_reasons)),
               _task_form(rep["rep_id"], score.account_id, item.rank_in_queue,
                          "accepted", work_button),
               _task_form(rep["rep_id"], score.account_id, item.rank_in_queue,
                          "skipped", "<button type=\"submit\">Not now</button>"),
               e(score.account_id), e(rep["rep_id"]),
               ("<div class=\"meta\">%s</div>" % e(friction)) if friction else ""))

    body = (header + stamp + budget_bar(usage, rep["rep_id"]) + "".join(rows)
            + "<p class=\"footer\"><a href=\"/\">all reps</a> · "
              "<a href=\"/metrics\">metrics</a></p>")
    return page("Warrant queue · %s" % rep["name"], body)


def _task_form(rep_id, account_id, rank, action, button_html):
    return ("<form method=\"post\" action=\"/task\">"
            "<input type=\"hidden\" name=\"rep\" value=\"%s\">"
            "<input type=\"hidden\" name=\"account\" value=\"%s\">"
            "<input type=\"hidden\" name=\"rank\" value=\"%s\">"
            "<input type=\"hidden\" name=\"action\" value=\"%s\">%s</form> "
            % (e(rep_id), e(account_id), e(rank), e(action), button_html))


# ---------------------------------------------------------------------------
# §6.2 Detail view
# ---------------------------------------------------------------------------

def render_detail(rep, item, usage, as_of, ruleset, total_accounts, context):
    score = item.score
    account = score.account

    head = ("<h1>%s · %s</h1><p class=\"meta\">%s</p>"
            % (e(account["name"]), e(account["domain"]),
               e(reasons_mod.account_meta_line(account, context["owner_label"]))))

    anchor_note = reasons_mod.anchor_note(score.band)
    above = reasons_mod.above_anchor_note(score)
    rank_line = reasons_mod.rank_line(item, total_accounts)

    verdict = ("<p>%s <strong>%s pts</strong>%s <span class=\"meta\">%s</span></p>"
               "<p class=\"meta\">%s · confidence: %s</p>"
               % (band_chip(score.band), e(_points_display(score.points)), e(above),
                  e(anchor_note), e(rank_line), e(score.confidence)))

    adjusted = reasons_mod.adjusted_note(score)
    if adjusted:
        verdict += "<p class=\"meta\">%s</p>" % e(adjusted)

    banners = []
    for text in (reasons_mod.brand_new_line(score), reasons_mod.stale_line(score),
                 reasons_mod.conflict_line(score, item.all_reasons)):
        if text:
            banners.append("<div class=\"banner\">%s</div>" % e(text))
    thin = reasons_mod.thin_data_line(score)
    # When there are no reasons at all the same sentence is the reasons block
    # itself (§8.3), so it is not repeated as a banner above it.
    if thin and item.all_reasons:
        banners.append("<div class=\"banner warn\">%s<br>%s</div>"
                       % (e(thin), e(reasons_mod.what_would_change_line(score) or "")))
    for banner in context["expired_banners"]:
        banners.append(_expired_banner(rep["rep_id"], score.account_id, banner, as_of))

    if not item.all_reasons:
        reasons_html = ("<div class=\"reason\">%s<div class=\"meta\">%s</div></div>"
                        % (e(reasons_mod.NO_SIGNALS_LINE),
                           e(reasons_mod.what_would_change_line(score) or "")))
    else:
        reasons_html = "".join(
            _render_reason(rep["rep_id"], score, r, context) for r in item.shown_reasons)

    # "Why this is at the top" is only true at the top. Calling a rank-47 item
    # top-of-queue is exactly the kind of small overclaim §4.6 exists to avoid.
    heading = reasons_mod.detail_heading(item)

    limits = "<div class=\"limits\">%s</div>" % e(item.limits_line)

    body = ("".join([head, verdict, "".join(banners),
                     "<h2>%s</h2>" % e(heading), reasons_html, limits,
                     _adjust_block(rep["rep_id"], score.account_id, usage),
                     _item_dispute_block(rep["rep_id"], score.account_id, context),
                     _history_block(rep["rep_id"], context),
                     _research_block(score.account_id, context),
                     "<p class=\"footer\"><a href=\"/queue?rep=%s\">back to queue</a> · "
                     "<a href=\"/ruleset\">How the weights are set</a></p>"
                     % e(rep["rep_id"])]))
    return page("%s · Warrant" % account["name"], body)


def _band_threshold_text(band):
    """Moved to reasons.py::band_threshold_text; delegating alias kept."""
    return reasons_mod.band_threshold_text(band)


def _render_reason(rep_id, score, reason, context):
    cat = reasons_mod.CATEGORY_LABELS[reason.category]

    if reason.is_suppressed:
        note = context["suppression_notes"].get(reason.signal_type_id, "")
        # The disputed reason stays on screen, struck through, in its slot.
        # Silently backfilling the slot would make the disagreement feel
        # unregistered (§7.4).
        pts = reasons_mod.suppressed_points_label(reason)
        undo_id = context["suppression_adjustments"].get(reason.signal_type_id)
        undo = (_revert_form(rep_id, undo_id, score.account_id, "undo")
                if undo_id else "")
        extra = context["new_events_notes"].get(reason.signal_type_id, "")
        return ("<div class=\"reason\"><div class=\"cat\">%s</div>"
                "<div class=\"sentence struck\">%s</div>"
                "<div class=\"evidence\">%s</div>"
                "<div class=\"rpts\">%s</div><div style=\"margin-top:6px\">%s%s</div>"
                "<div style=\"clear:both\"></div></div>"
                % (e(cat), e(reason.text), e(note), e(pts), undo,
                   ("<span class=\"meta\"> %s</span>" % e(extra)) if extra else ""))

    pts = reasons_mod.points_label(reason.points, reason.cap_applied,
                                   reason.contribution.max_contribution)
    reason_id = context["reason_ids"].get(reason.signal_type_id)
    evidence_link = ("<a href=\"/evidence/%s?rep=%s\">see evidence</a>"
                     % (e(reason_id), e(rep_id))) if reason_id else ""
    wrong = _dispute_form(rep_id, score.account_id, "EVIDENCE_WRONG",
                          signal_type_id=reason.signal_type_id,
                          reason_id=reason_id, label="this is wrong")
    stale = _dispute_form(rep_id, score.account_id, "EVIDENCE_STALE",
                          signal_type_id=reason.signal_type_id,
                          reason_id=reason_id, label="out of date")
    return ("<div class=\"reason\"><div class=\"cat\">%s</div>"
            "<div class=\"sentence\">%s</div>"
            "<div class=\"evidence\">%s</div>"
            "<div class=\"rpts\">%s</div>"
            "<div style=\"margin-top:6px\">%s &nbsp; %s %s</div>"
            "<div style=\"clear:both\"></div></div>"
            % (e(cat), e(reason.text), e(reason.evidence_summary), e(pts),
               evidence_link, wrong, stale))


def _dispute_form(rep_id, account_id, code, signal_type_id=None, reason_id=None,
                  person_id=None, window=None, label=None, rank=None):
    hidden = [("rep", rep_id), ("account", account_id), ("code", code)]
    if signal_type_id is not None:
        hidden.append(("signal_type", signal_type_id))
    if reason_id is not None:
        hidden.append(("reason", reason_id))
    if person_id is not None:
        hidden.append(("person", person_id))
    if window is not None:
        hidden.append(("window", window))
    if rank is not None:
        hidden.append(("rank", rank))
    fields = "".join("<input type=\"hidden\" name=\"%s\" value=\"%s\">" % (e(k), e(v))
                     for k, v in hidden)
    return ("<form method=\"post\" action=\"/dispute\">%s"
            "<button type=\"submit\">%s</button></form> "
            % (fields, e(label or CODE_LABELS[code])))


def _revert_form(rep_id, adjustment_id, account_id, label="undo"):
    return ("<form method=\"post\" action=\"/adjust/revert\">"
            "<input type=\"hidden\" name=\"rep\" value=\"%s\">"
            "<input type=\"hidden\" name=\"adjustment\" value=\"%s\">"
            "<input type=\"hidden\" name=\"account\" value=\"%s\">"
            "<button type=\"submit\">%s</button></form> "
            % (e(rep_id), e(adjustment_id), e(account_id), e(label)))


def _adjust_form(rep_id, account_id, kind, days, label):
    return ("<form method=\"post\" action=\"/adjust\">"
            "<input type=\"hidden\" name=\"rep\" value=\"%s\">"
            "<input type=\"hidden\" name=\"account\" value=\"%s\">"
            "<input type=\"hidden\" name=\"kind\" value=\"%s\">"
            "<input type=\"hidden\" name=\"days\" value=\"%s\">"
            "<button type=\"submit\">%s</button></form> "
            % (e(rep_id), e(account_id), e(kind), e(days), e(label)))


def _adjust_block(rep_id, account_id, usage):
    counts = queue_mod.budget_counts_line(usage, queue_mod.ADJUST_BLOCK_KEYS)
    buttons = "".join(_adjust_form(rep_id, account_id, kind, days, label)
                      for kind, days, label in queue_mod.ADJUST_BUTTONS)
    return ("<h2>Adjust your queue</h2><p class=\"meta\">%s</p><p>%s</p>"
            % (e(counts), buttons))


def _item_dispute_block(rep_id, account_id, context):
    buttons = [
        _dispute_form(rep_id, account_id, "NOT_A_FIT"),
        _dispute_form(rep_id, account_id, "BAD_TIMING", window=30),
        _dispute_form(rep_id, account_id, "ALREADY_WORKING"),
        _dispute_form(rep_id, account_id, "NOT_MY_PATCH"),
    ]
    person = context.get("top_person")
    if person:
        buttons.insert(1, _dispute_form(rep_id, account_id, "WRONG_PERSON",
                                        person_id=person["person_id"],
                                        label=wrong_person_label(person)))
        note = ""
    else:
        # WRONG_PERSON maps to exclude_person, which needs a person. With no
        # contact on file there is nobody to exclude, so the control is not
        # offered rather than guessing which human the rep meant.
        note = ("<p class=\"meta\">%s</p>"
                % e(reasons_mod.WRONG_PERSON_UNAVAILABLE_NOTE))
    return ("<h2 id=\"dispute\">Disagree with the whole item</h2><p>%s</p>%s"
            % ("".join(buttons), note))


def _history_block(rep_id, context):
    rows = context["history"]
    if not rows:
        return ("<h2>Your history on this account</h2><p class=\"meta\">%s</p>"
                % e(reasons_mod.HISTORY_EMPTY_NOTE))
    out = []
    for row in rows:
        line = reasons_mod.history_line(row)
        undo = ""
        if row["adj_is_active"] and row["resulting_adjustment_id"]:
            undo = _revert_form(rep_id, row["resulting_adjustment_id"], row["account_id"])
        out.append("<div class=\"row\">%s [%s] %s</div>"
                   % (e(line), e(row["status"]), undo))
    return "<h2>Your history on this account</h2>%s" % "".join(out)


def _research_block(account_id, context):
    obs = context["observations"]
    if not obs:
        return ("<h2>%s</h2><p class=\"meta\">%s</p>"
                % (e(reasons_mod.research_heading(obs)),
                   e(reasons_mod.RESEARCH_EMPTY_NOTE)))
    rows = "".join(
        "<div class=\"row\">· %s<div class=\"meta\">%s · %s · %s</div></div>"
        % (e(o["summary"]), e(o["source_name"]),
           e(reasons_mod.observation_retrieved_display(o)),
           e(o["source_url"] or reasons_mod.NO_REFERENCE))
        for o in obs[:reasons_mod.RESEARCH_PREVIEW])
    more = ("<p><a href=\"/evidence/observations/%s\">see all research</a></p>"
            % e(account_id)) if len(obs) > reasons_mod.RESEARCH_PREVIEW else ""
    return "<h2>%s</h2>%s%s" % (e(reasons_mod.research_heading(obs)), rows, more)


def _expired_banner(rep_id, account_id, banner, as_of):
    return ("<div class=\"banner\">%s"
            "<div style=\"margin-top:6px\">%s%s</div></div>"
            % (e(reasons_mod.expired_dispute_line(banner)),
               _dispute_form(rep_id, account_id, "EVIDENCE_WRONG",
                             signal_type_id=banner["signal_type_id"],
                             label="suppress for another 90 days"),
               _review_form(rep_id, account_id, banner["signal_type_id"])))


def _review_form(rep_id, account_id, signal_type_id):
    return ("<form method=\"post\" action=\"/dispute\">"
            "<input type=\"hidden\" name=\"rep\" value=\"%s\">"
            "<input type=\"hidden\" name=\"account\" value=\"%s\">"
            "<input type=\"hidden\" name=\"signal_type\" value=\"%s\">"
            "<input type=\"hidden\" name=\"code\" value=\"LEAVE_IT\">"
            "<button type=\"submit\">leave it — it looks right now</button></form> "
            % (e(rep_id), e(account_id), e(signal_type_id)))


# ---------------------------------------------------------------------------
# §6.3 Evidence drawer
# ---------------------------------------------------------------------------

def render_evidence(rep_id, reason, account, events, as_of, observations):
    head = ("<h1>%s</h1><p class=\"meta\">%s</p>"
            % (e(reasons_mod.evidence_header(reason, account)),
               e(reasons_mod.evidence_summary_line(reason, as_of))))

    if events:
        rows = []
        for ev in events:
            rows.append(
                "<div class=\"row\"><span class=\"pts\">%s</span>"
                "<strong>%s</strong> · %s %s"
                "<div class=\"meta\">%s</div>"
                "<div class=\"meta\">%s</div>"
                "<div class=\"meta\">%s</div></div>"
                % (e(reasons_mod.evidence_contribution_display(ev)),
                   e(human_datetime(ev["occurred_at"])),
                   e(reasons_mod.evidence_magnitude_display(ev)),
                   e(reasons_mod.evidence_detail_display(ev)),
                   e(reasons_mod.evidence_person_display(ev)),
                   e(reasons_mod.evidence_source_display(ev)),
                   e(reasons_mod.evidence_ref_display(ev))))
        body_rows = "".join(rows)
    else:
        # kind='state' reasons have no reason_evidence rows; the drawer falls
        # back to the field values the predicate read, stamped with the
        # enrichment date (§3.9).
        body_rows = ("<div class=\"row\">%s<div class=\"meta\">%s</div>"
                     "<div class=\"meta\">%s</div></div>"
                     % (e(reasons_mod.EVIDENCE_STATE_INTRO),
                        e(reason["evidence_summary"]),
                        e(reasons_mod.evidence_refreshed_display(account))))

    note = "<p class=\"meta\">%s</p>" % e(reasons_mod.SOURCE_LINK_NOTE)

    actions = ("<p>%s%s%s</p>"
               % (_dispute_form(rep_id, account["account_id"], "EVIDENCE_WRONG",
                                signal_type_id=reason["signal_type_id"],
                                reason_id=reason["reason_id"],
                                label="this reason is wrong"),
                  _dispute_form(rep_id, account["account_id"], "EVIDENCE_STALE",
                                signal_type_id=reason["signal_type_id"],
                                reason_id=reason["reason_id"],
                                label="this evidence is out of date"),
                  (_dispute_form(rep_id, account["account_id"], "WRONG_PERSON",
                                 signal_type_id=reason["signal_type_id"],
                                 reason_id=reason["reason_id"],
                                 person_id=events[0]["person_id"],
                                 label="wrong person")
                   if events and events[0]["person_id"] else "")))

    obs_html = ""
    if observations:
        obs_html = ("<h2>Agent observations for this account</h2>%s"
                    % "".join("<div class=\"row\">· %s<div class=\"meta\">%s · %s</div></div>"
                              % (e(o["summary"]), e(o["source_name"]),
                                 e(reasons_mod.observation_retrieved_display(o)))
                              for o in observations))

    back = ("<p class=\"footer\"><a href=\"/account/%s?rep=%s\">back to %s</a></p>"
            % (e(account["account_id"]), e(rep_id), e(account["name"])))
    return page("Evidence · %s" % reason["display_name"],
                head + body_rows + note + actions + obs_html + back)


def render_observations(account, observations, rep_id):
    rows = "".join(
        "<div class=\"row\">· %s<div class=\"meta\">%s · %s · %s"
        "<br>ref: %s</div></div>"
        % (e(o["summary"]), e(o["source_name"]),
           e(reasons_mod.observation_retrieved_display(o)),
           e(reasons_mod.observation_agent_run_display(o)),
           e(o["source_url"] or reasons_mod.NO_REFERENCE))
        for o in observations)
    body = ("<h1>Agent research · %s</h1><p class=\"meta\">%s</p>%s"
            "<p class=\"footer\"><a href=\"/account/%s?rep=%s\">back</a></p>"
            % (e(account["name"]),
               e(reasons_mod.observations_count_line(observations)), rows,
               e(account["account_id"]), e(rep_id)))
    return page("Research · %s" % account["name"], body)


# ---------------------------------------------------------------------------
# Adjustments list
# ---------------------------------------------------------------------------

def render_adjustments(rep, rows, usage, as_of):
    counts = "".join(
        "<tr><td>%s</td><td class=\"num\">%d</td><td class=\"num\">%d</td></tr>"
        % (e(BUDGET_LABELS[k]), usage[k][0], usage[k][1]) for k in BUDGETS)
    body_rows = []
    for row in rows:
        label = reasons_mod.adjustment_line(row)
        state = reasons_mod.adjustment_state(row)
        undo = (_revert_form(rep["rep_id"], row["adjustment_id"], row["account_id"])
                if row["is_active"] else "")
        body_rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                         % (e(label), e(human_date(row["created_at"])),
                            e(human_date(row["expires_at"])), e(state), undo))
    body = ("<h1>Your adjustments · %s</h1>"
            "<p class=\"meta\">Every adjustment expires. Expiry is evaluated when "
            "the queue is read, against %s — there is no background job.</p>"
            "<table><tr><th>Budget</th><th>Used</th><th>Limit</th></tr>%s</table>"
            "<h2>All adjustments</h2>"
            "<table><tr><th>What</th><th>Created</th><th>Expires</th><th>State</th>"
            "<th></th></tr>%s</table>"
            "<p class=\"footer\"><a href=\"/queue?rep=%s\">back to queue</a></p>"
            % (e(rep["name"]), e(human_datetime(as_of)), counts,
               "".join(body_rows) or "<tr><td colspan=\"5\">None yet.</td></tr>",
               e(rep["rep_id"])))
    return page("Adjustments · %s" % rep["name"], body)


# ---------------------------------------------------------------------------
# §7.5 Metrics
# ---------------------------------------------------------------------------

def render_metrics(data):
    fmt = metrics_mod.format_rate

    def line(label, triple, suffix=""):
        num, den, rate = triple
        return ("<tr><td>%s</td><td class=\"num\">%s</td>"
                "<td class=\"meta\">%d / %d%s</td></tr>"
                % (e(label), e(fmt(rate)), num, den, e(suffix)))

    headline = "<table>%s</table>" % "".join(
        line(label, data[key], (" — %s" % note) if note else "")
        for key, label, note in metrics_mod.METRIC_ROWS)

    rows = "".join(
        "<tr class=\"%s\"><td>%s</td><td class=\"num\">%d</td><td class=\"num\">%d</td>"
        "<td class=\"num\">%s</td><td class=\"num\">%s</td><td>%s</td></tr>"
        % ("flagged" if r["flagged"] else "", e(r["display_name"]), r["shown_count"],
           r["dispute_count"], e(fmt(r["dispute_rate"])), e(fmt(r["suppression_rate"])),
           e(r["flag_text"]))
        for r in data["per_type"])

    owners = "".join("<tr><td>%s</td><td class=\"num\">%d</td></tr>"
                     % (e(r["account_name"]), r["n"]) for r in data["ownership_errors"])

    body = ("<h1>Warrant · metrics</h1>"
            "<p class=\"meta\">%s</p>"
            "%s"
            "<h2>Per signal type</h2>"
            "<p class=\"meta\">%s</p>"
            "<table><tr><th>Signal type</th><th>Shown</th><th>Disputes</th>"
            "<th>Dispute rate</th><th>Suppression rate</th><th></th></tr>%s</table>"
            "<h2>Ownership errors</h2><table>%s</table>"
            "<p class=\"footer\"><a href=\"/\">home</a> · <a href=\"/ruleset\">ruleset</a></p>"
            % (e(metrics_mod.window_line(data)), headline,
               e(metrics_mod.FLAG_NOTE), rows,
               owners or "<tr><td class=\"meta\">None reported.</td></tr>"))
    return page("Warrant metrics", body)


# ---------------------------------------------------------------------------
# §6.5 Ruleset
# ---------------------------------------------------------------------------

# Moved to reasons.py so the JSON path serves the same sentences without
# importing this module (§2.5, §10.3 open question 1). Aliased, not duplicated.
RULESET_HEADER = reasons_mod.RULESET_HEADER
ANCHOR_NOTE = reasons_mod.ANCHOR_NOTE
WEIGHTS_NOTE = reasons_mod.WEIGHTS_NOTE


def render_ruleset(signal_types, per_type, ruleset):
    flags = {r["signal_type_id"]: r for r in per_type}
    rows = []
    for st in signal_types:
        flag = flags.get(st["signal_type_id"], {})
        rows.append(
            "<tr class=\"%s\"><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td class=\"num\">%s</td><td class=\"num\">%s</td>"
            "<td class=\"num\">%s</td><td class=\"num\">%s</td><td>%s</td></tr>"
            % ("flagged" if flag.get("flagged") else "",
               e(st["display_name"]), e(st["code"]), e(st["category"]),
               e(st["kind"]), e(reasons_mod.weight_display(st["base_weight"])),
               e(reasons_mod.weight_display(st["max_contribution"])),
               e(reasons_mod.half_life_display(st)),
               e(metrics_mod.format_rate(flag.get("dispute_rate"))),
               e(flag.get("flag_text", ""))))
    body = ("<h1>Warrant ruleset · %s</h1><div class=\"limits\">%s</div>"
            "<table><tr><th>Signal</th><th>Code</th><th>Category</th><th>Kind</th>"
            "<th>Weight</th><th>Cap</th><th>Half-life (d)</th><th>Dispute rate</th>"
            "<th></th></tr>%s</table>"
            "<h2>The anchor</h2><p>%s</p>"
            "<h2>Where these weights come from</h2><p>%s</p>"
            "<h2>What this score does not claim</h2><p>%s</p>"
            "<p class=\"footer\"><a href=\"/\">home</a> · <a href=\"/metrics\">metrics</a></p>"
            % (e(ruleset), e(RULESET_HEADER), "".join(rows), e(ANCHOR_NOTE),
               e(WEIGHTS_NOTE), e(NOT_CLAIMED)))
    return page("Warrant ruleset", body)


NOT_CLAIMED = reasons_mod.NOT_CLAIMED


def render_error(title, message, links=""):
    return page(title, "<h1>%s</h1><p>%s</p>%s"
                       "<p class=\"footer\"><a href=\"/\">home</a></p>"
                % (e(title), e(message), links))


def render_budget_exceeded(rep_id, exc):
    """The sentence itself now lives in queue.budget_exceeded_message (§2.5),
    so the HTML 409 and the JSON 409 cannot drift apart."""
    links = ("<p><a href=\"/adjustments?rep=%s\">view your adjustments</a></p>"
             % e(rep_id))
    return render_error(queue_mod.BUDGET_EXCEEDED_TITLE,
                        queue_mod.budget_exceeded_message(exc), links)
