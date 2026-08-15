# DEPLOY_ARCHITECTURE.md — Warrant on a GitHub Pages URL

**Stage:** 2 of 4 (design)
**Author:** Designer agent (AI-generated)
**Date:** 13 August 2026
**Input:** `HOSTING_RESEARCH.md` (stage 1), `DESIGN_SPEC.md`, `README.md`, and the source files listed in §0.2
**Working directory:** `C:\Users\DELL Lattitude\Documents\Unify Agent Test`

---

## 0. What this document is, and what it is not

### 0.1 Status

**Nothing here is deployed, live, or verified in production.** Nobody in this pipeline has a cloud account, a credential, or the ability to create one. No GitHub repo exists. No Render service exists. Every URL in this document is a **placeholder** and is written as one:

- `https://<your-username>.github.io/<repo>/` — placeholder, not a real site
- `https://<your-app>.onrender.com` — placeholder, not a real service

The deliverable chain ends in **a repository plus a runbook the user executes themselves** through browser dashboards and plain `git` over HTTPS. `gh`, `docker`, `flyctl`, `render`, `railway`, `vercel`, `netlify`, `aws`, `gcloud` and `psql` are not installed and are not used by anything specified here.

### 0.2 What I read, and what that resolved

`HOSTING_RESEARCH.md` Appendix A items 2 and 4 record two things the researcher could only infer because she read `app.py` lines 1–80 only. Both are now resolved by reading the source. I did not inherit either inference.

| Appendix A item | Researcher's position | Resolved by reading | Answer |
|---|---|---|---|
| **4a — bind address / `$PORT`** | Inferred from `README.md`'s "bound to 127.0.0.1 only" | `app.py` L437–441, `warrant/db.py` L40–41 | **Confirmed, and worse than inferred.** `main()` calls `ThreadingHTTPServer(("127.0.0.1", listen_port), Handler)` with `"127.0.0.1"` as a **hardcoded string literal**, not an env var. `listen_port = port()` reads **`WARRANT_PORT`**, not `PORT`. Render injects `PORT`. So there are **two** changes, not one: the host must become configurable, and the port lookup must fall back to the platform's `PORT`. See §6.3. |
| **4b — response headers** | Inferred "nothing in the documented design sets security headers" | `app.py` L100–112 | **Confirmed.** `_send()` sets exactly `Content-Type` and `Content-Length`. `_redirect()` sets exactly `Location` and `Content-Length`. `BaseHTTPRequestHandler.send_response()` adds `Server:` (from `server_version = "Warrant/1.0"`) and `Date:`. **There is no `X-Frame-Options`, no CSP, no `Cache-Control`, and no CORS header anywhere.** |
| **§1.5 — `do_OPTIONS`** | "`app.py` currently has no `do_OPTIONS` handler at all" | `app.py` L120, L147 | **Confirmed.** Only `do_GET` and `do_POST` exist. An `OPTIONS` request today gets `BaseHTTPRequestHandler`'s default **501 Unsupported method**, with no CORS headers on it. See §4.4. |

One additional fact from the same read that the research did not have, and that constrains §4: **`Handler.protocol_version = "HTTP/1.1"`** (`app.py` L94). Under HTTP/1.1 keep-alive every response must be self-framing. `_redirect()` already demonstrates the required pattern — a `303` with an explicit `Content-Length: 0`. Any new response path, including the preflight response, must do the same or the connection desynchronises.

Also read in full or in relevant part: `warrant/scoring.py`, `warrant/reasons.py`, `warrant/queue.py`, `warrant/feedback.py`, `warrant/metrics.py`, `warrant/db.py`, `warrant/render.py`, `seed_db.py`, `tests/test_scoring.py`, and `DESIGN_SPEC.md` §3, §4, §6, §7, §8, §9.

### 0.3 The two decisions I was given

Two decisions were made before this stage and are **implemented as given**:

1. **Frontend shape: option A** (static shell on Pages + JSON API), with the constraint that the backend returns fully-rendered text and the browser does layout only. §2 states the constraint and its reasoning in full.
2. **Host: Render free tier** as the primary target, with a designed upgrade path to a persistent volume. §1 and §6 state it, §6.5 states the disclosure the UI must carry.

Where I disagree on a factual basis, I implement as stated and record the disagreement in §10. There is one such disagreement and it is minor.

---

## 1. Chosen stack, and what it costs

### 1.1 The stack

| Layer | Choice | Grounded in |
|---|---|---|
| **Frontend host** | GitHub Pages, `/docs` folder on the default branch, no Actions workflow, no build step | HOSTING_RESEARCH §1.2 option 2 — "lets the Pages site live inside the existing Warrant repo without a separate branch or a build step, which is the least a non-expert user has to learn" |
| **Frontend transport** | HTTPS on the default `*.github.io` domain, automatic | §1.3 [VERIFIED] |
| **Backend host** | Render free web service, 750 instance-hours/month, sleeps after 15 min, wakes in "about one minute" | §2.1 [VERIFIED], §6.1 |
| **Backend process** | `app.py` unchanged in shape — `ThreadingHTTPServer`, long-lived, listening on the injected `$PORT`, bound `0.0.0.0` | §2.1, §6.1; the bind change is specified concretely in §6.3 |
| **Database** | SQLite, in-container, in-process, at `WARRANT_DB_PATH` | §4.4 "Keep SQLite. Move the file." |
| **Seeding** | `seed_db.py` at container boot, under the fixed seed `20260811`, **conditional on the database not already existing** | §6.1, extended per §6.2 cost #1 |
| **Dependencies** | **Zero.** Python standard library only. No `requirements.txt` entries, no driver, no framework | §6.1 "Stdlib-only survives" |
| **Frontend↔backend** | `fetch()` cross-origin, CORS allowlist from an env var, form-encoded writes | §1.5 |

### 1.2 Why this and not the alternatives — with the downside named

**Why Render and not a database service (Turso, D1, Neon, Supabase).** HOSTING_RESEARCH §0.1 is the governing finding: a single `GET /queue?rep=1` render issues on the order of **1,400 individual SQL statements**, and that figure is a floor because `warrant/reasons.py`'s query sites were not counted (Appendix A item 5). I read `reasons.py` and can raise the floor: `render_reason_text()` issues **one further `SELECT` against `signal_types` per contribution**, called from `build_reasons()` once per ranked reason per account. At ~10 contributions per account over 53 accounts that is another ~500 statements. **The real figure is closer to 1,900 than 1,400.** Any architecture that puts a network hop between `scoring.py` and the rows is disqualified for the live path, exactly as §0.1 concludes. The database must be in the same process as the Python. That leaves SQLite on local disk, which leaves a container host, which leaves Render as the only free one that runs a `ThreadingHTTPServer` (§2.11 summary table).

**Why not PythonAnywhere**, which §2.9 shows is the only free host with a persistent disk. Because `app.py` is a `BaseHTTPRequestHandler`, not a WSGI application (§2.9, §6.4 blocker 1), and converting it is real work on the one file that routes everything — work that would have to be redone or maintained in parallel. Compounding: a 100 CPU-second/day budget against a ~0.21s queue render is ~475 renders/day (§6.4 blocker 2), and a queue render is not one page view because `GET /account/{id}` re-runs the whole patch too (README deviation 10). And the web app expires on an interval the sources genuinely disagree about, 1 month vs 3 months, unresolved in Appendix A item 14. **I am recording that this is a defensible alternative I rejected, not one I dismissed.** If durability of rep feedback is judged non-negotiable and money is judged non-negotiable, §6.4 of the research points here and this document is wrong.

**Named costs of the Render choice, inherited from §6.2 and not hidden:**

1. **Rep-generated data does not survive a restart.** `disagreements`, `queue_adjustments`, `score_runs`, `scores`, `reasons`, `reason_evidence`, `task_events` are all lost on every spin-down and every redeploy. This is decided explicitly in §6.5, not inherited.
2. **~60-second cold start for most viewers.** §5.2: "a demo link is clicked at unpredictable times… most viewers of a circulated link hit a cold container." Mitigated, not solved, by §5.3 item 3 — the static skeleton. Specified in §9.1.
3. **750 instance-hours/month with a cliff.** Exceeding it suspends all free services until the next month (§2.1 [VERIFIED]). This design **does not recommend keep-alive pings**: §5.3 item 1 shows they consume ~730 of 750 hours, and Appendix A item 3 records that Render's terms position on pinging is unverified in both directions. Do not add a pinger without reading Render's ToS first.
4. **Do not use Render's free Postgres.** It expires 30 days after creation (§2.1, §6.2 cost 4). Nothing in this design touches it.
5. **The "works with JavaScript off" guarantee is lost on the Pages URL.** §1.6 prices option A as "No" on that column and it is correct. The HTML app at the Render origin still works with JS off and is unchanged; the Pages frontend does not. This is the price of decision 1 and it is real. See §10.

### 1.3 Two claims this design depends on that the research could not verify

Stated plainly because the design rests on them:

1. **That Render runs a long-running non-WSGI Python process** (`http.server` calling `serve_forever()`). HOSTING_RESEARCH Appendix A item 2: *"I did not fetch a page confirming a raw `http.server` process is acceptable. **This should be verified before the runbook is written**, because the entire primary recommendation rests on it."* It still rests on it. The runbook stage must confirm this on Render's own docs before the user is asked to sign up. If it turns out to be false, the fallback is §10's open question 1.
2. **That Render offers a Python runtime at 3.14.x.** Not covered by the research at all. `README.md` says "Python 3.14 (tested on 3.14.3)". I read nothing in `warrant/` or `app.py` that requires 3.14 specifically — the code uses `dataclasses`, `%`-formatting, `math.log10`, `json`, `sqlite3`, `http.server`, all long-stable — so my **inference** is that it runs on 3.11–3.13 unchanged. That is an inference, it is untested, and if the runtime differs from 3.14.3 the maker must run `python -m unittest discover tests` on the target version before deploying, not after.

Additionally, HTTPS on `*.onrender.com` is Appendix A item 1 — universally true in practice, but not verified by a fetched sentence. If it were false, §1.4's mixed-content block would make the whole architecture non-functional, so it is worth a 5-second check on the first deploy.

---

## 2. The split — and the one constraint the maker must not deviate from

### 2.1 The rule

> **The backend returns fully-rendered reason text, per-reason point values, the applied truncation, and the limits line as JSON fields. The browser does layout and interaction ONLY — zero arithmetic, zero ranking, zero truncation, zero template substitution.**

### 2.2 Why this rule exists

HOSTING_RESEARCH §1.6 flags a genuine tension and it is right to: *"the obvious 'modern' architecture for a Pages frontend is the one most in conflict with Warrant's core claim."* The conflict is that option A normally puts arithmetic and rendering in two places, which is precisely the MadKudu failure `DESIGN_SPEC.md` §2 row 9 and `STATUS_REPORT.md` §1 record the entire design as existing to prevent.

The resolution is to refuse the second place.

`warrant/scoring.py`'s docstring states the guarantee: *"there is exactly one code path… the score is `sum(c.points)` and the reasons are `render(c)` over the same list. It is not possible to produce a reason that did not contribute points, or a point that produced no reason."* `warrant/reasons.py` renders the sentence and the evidence line from that same contribution list. `warrant/queue.py::_persist_score()` writes both to the database in one pass. Test T07 asserts `sum(reason points) == score.points` to ±0.01 across every account in the corpus, twice — once over in-memory objects and once over the persisted rows (`tests/test_scoring.py::TestT07ExplanationIsTheModel`).

Under this rule, **that entire chain is untouched.** The JSON layer is a serialiser over its output. The browser receives:

```json
{"rank": 2, "text": "VP Engineering viewed /pricing 3x, most recently 2 days ago (9 Aug 2026).",
 "evidence_summary": "2 visits to /pricing between 5 Aug 2026 and 9 Aug 2026 · source: website",
 "points": 14.95, "points_display": "+15 pts", "shown": true, "category_label": "ACTIVE EVALUATION"}
```

and puts it on screen. It never computes `14.95`, never decides that this reason is rank 2, never decides that it is shown, never formats `14.95` into `"+15 pts"`, never picks the band.

### 2.3 Porting scoring to JavaScript is forbidden

Explicitly, so there is no ambiguity: **do not reimplement `score_account()`, `apply_cap()`, `decay_factor()`, `magnitude_factor()`, `compute_confidence()`, `band_from()`, `rank_reasons()`, `select_shown()`, `build_limits_line()`, `points_label()`, `truncate_at_word()`, `freshness_chip()`, `adjustment_chip()`, or `compressed_limits()` in JavaScript, in whole or in part.**

Two reasons, and the first is fatal on its own:

1. **It would mean shipping the corpus to the client.** Scoring one account requires its `accounts` row, all its `people` rows, every `signal_events` row inside each signal type's lookback window, all 19 `signal_types` rows with their weights and templates, and the rep's active `queue_adjustments`. Scoring a queue requires that for all 53 accounts in the patch. That payload is the database. Warrant's live-query guarantee — `README.md`: *"no cache, no memoisation and no precomputed score literal anywhere"* — would become a lie the moment the browser held a copy, because the copy is a cache by definition. The three tests in `tests/test_scoring.py::TestLiveDatabaseNotFixtures` that mutate the database behind the application's back would still pass, and they would no longer mean anything about what the user sees.
2. **It would recreate the two-code-paths failure.** A JS `applyCap()` and a Python `apply_cap()` are two implementations of one rule. They will drift. T07 would keep passing against the Python one while the browser showed something else. That is exactly the drift `DESIGN_SPEC.md` implication #9 is architected to make impossible.

### 2.4 The split, concretely

| Concern | Where it lives | Note |
|---|---|---|
| Scoring arithmetic (§4.2) | **Server** — `warrant/scoring.py`, unchanged | |
| State predicates (§4.1) | **Server** — `warrant/scoring.py`, unchanged | |
| Confidence cascade, band gate (§8.7, §4.2) | **Server** — `warrant/scoring.py`, unchanged | |
| Reason template rendering (§4.3) | **Server** — `warrant/reasons.py`, unchanged | |
| Ranking and the truncation rule (§4.5) | **Server** — `warrant/reasons.py`, unchanged | |
| Limits line (§4.6) | **Server** — `warrant/reasons.py`, unchanged | |
| Points display formatting (`+15 pts`, `+24 pts (capped at 24)`, `60`) | **Server** — `warrant/reasons.py::points_label`, `warrant/render.py::_points_display` | Both already exist |
| Chips, banners, friction copy | **Server** — `warrant/reasons.py`, `app.py::friction_text` | Already exist |
| Budget enforcement (§7.3) | **Server** — `warrant/queue.py`, unchanged | Server-side refusal, never client-side |
| Dispute→effect mapping (§7.2) | **Server** — `warrant/feedback.py`, unchanged | |
| Metrics SQL (§7.5) | **Server** — `warrant/metrics.py`, unchanged | |
| **JSON serialisation** | **Server** — new `warrant/api.py` | Serialises. Computes nothing. See §2.5 |
| HTML rendering | **Server** — `warrant/render.py`, unchanged, still served at the Render origin | The no-JS app survives at `https://<your-app>.onrender.com/queue?rep=1` |
| DOM construction, hash routing, loading states, error states | **Browser** — `docs/app.js` | |

### 2.5 The rule applied to `warrant/api.py`

`warrant/api.py` is a new module and it is the place the rule is most likely to be broken. Its permitted vocabulary:

- **May** call `build_run()`, `build_reasons()`, `build_limits_line()`, `points_label()`, `compressed_limits()`, `freshness_chip()`, `adjustment_chip()`, `truncate_at_word()`, `thin_data_line()`, `stale_line()`, `brand_new_line()`, `conflict_line()`, `band_label()`, `friction_text()`, `budget_usage()`, `metrics.collect()`, `load_signal_types()` — i.e. exactly the functions `warrant/render.py` already calls.
- **May** read attributes off `AccountScore`, `SignalContribution`, `RenderedReason` and `QueueItem` and copy them into dicts.
- **May not** contain any arithmetic operator applied to a points value, any `sorted()`/`min()`/`max()` over reasons or scores, any slicing of a reason list, any `.format()` or `%` or f-string that produces rep-facing copy, or any `if points >= ...` comparison.
- Every rep-facing string in a payload must be traceable to a function in `warrant/reasons.py`, `warrant/render.py`, `warrant/feedback.py` or `app.py` that already produces it.

**A review question for the maker:** if a string in a JSON payload cannot be pointed at in `warrant/`, it was invented in the serialiser, and that is the drift this whole design exists to prevent.

One consequence: `render.py` currently composes the 409 budget-exceeded sentence (`render_budget_exceeded`) and the `rank 1 of 55 (was 3 before your adjustments)` line inside HTML-producing functions. The JSON path must not rewrite either. **Extract them down**, so both paths share one string:

- Move the budget sentence into `warrant/queue.py` as `budget_exceeded_message(exc) -> str`; `render.render_budget_exceeded()` calls it and wraps it in HTML; the JSON error path calls it directly.
- Move the rank line into `warrant/reasons.py` as `rank_line(item, total_accounts) -> str`; `render.render_detail()` calls it; `api.py` calls it.

This is a refactor that **removes** a future duplication rather than adding one. It changes no rendered output.

---

## 3. HTTP API contract

### 3.1 Shape

- **Base path:** `/api`. The existing HTML routes at `/`, `/queue`, `/account/{id}` etc. are untouched and keep working at the Render origin.
- **Reads:** `GET`, query parameters only.
- **Writes:** `POST`, body `application/x-www-form-urlencoded`. Justified in §4.5.
- **Responses:** `application/json; charset=utf-8`, UTF-8, `Content-Length` always set (HTTP/1.1 framing, §0.2).
- **Caching:** every `/api` response carries `Cache-Control: no-store`. See §7.
- **Numbers:** raw values are JSON numbers; **every number a rep reads is also present as a pre-rendered string**, named `*_display`. The frontend renders the string.

### 3.2 Common envelope conventions

Success responses are the object described per endpoint. Every read response also carries a `meta` block:

```json
"meta": {
  "as_of": "2026-08-11T09:00:00Z",
  "as_of_display": "11 Aug 2026, 09:00 UTC",
  "ruleset_version": "warrant-v1.0.0",
  "boot_id": "b7f2c1a9",
  "started_at": "2026-08-13T11:04:22Z",
  "started_at_display": "13 Aug 2026, 11:04 UTC",
  "persistence": "ephemeral",
  "persistence_notice": "This demo server runs on free hosting with no persistent disk. It last restarted on 13 Aug 2026, 11:04 UTC. Anything a rep filed before then — disputes, pins, mutes — is gone. Everything you file now lasts until the next restart."
}
```

`persistence` is `"ephemeral"` or `"persistent"`, read from `WARRANT_PERSISTENCE`. `persistence_notice` is composed **server-side** and rendered verbatim by the frontend. See §6.5 — this is the disclosure that stops the demo from silently enacting the failure Warrant exists to prevent.

### 3.3 Error shape

Every non-2xx `/api` response is:

```json
{"error": {
  "code": "BUDGET_EXCEEDED",
  "title": "You already have 5 pins",
  "message": "You already have 5 pins. Pins expire on their own — your oldest expires on 18 Aug 2026 — or unpin one now.",
  "detail": {"budget_key": "pin", "active": 5, "limit": 5, "oldest_expiry": "2026-08-18T09:00:00Z"},
  "action": {"label": "view your pins", "href": "/api/adjustments?rep=1"}
}}
```

`title` and `message` are rep-facing copy produced server-side (`queue.budget_exceeded_message`, per §2.5). The frontend renders them verbatim and never composes its own. `action` is optional and may be `null`.

| HTTP | `error.code` | When |
|---|---|---|
| 400 | `BAD_REQUEST` | Missing or unparseable `rep`, `account`, `code`, `action`; unknown dispute code (`feedback.DisputeError`); `WRONG_PERSON` without a `person` (README deviation 11) |
| 404 | `NOT_FOUND` | No such rep, no such account, no such reason, unknown `/api` route |
| 404 | `NOT_IN_QUEUE` | `GET /api/account/{id}` for an account not in this rep's current queue — muted, inactive, or owned by someone else. **This is a distinct code because it is a normal outcome after a `NOT_A_FIT` dispute, not a failure.** See §9.7 |
| 409 | `BUDGET_EXCEEDED` | `queue.BudgetExceeded` (§7.3, T12) |
| 409 | `EVIDENCE_REQUIRED` | `POST /api/task` with `action=accepted` while the §6.4 friction gate applies (README deviation 11 — server-side enforcement, not just a disabled button) |
| 500 | `INTERNAL` | Anything else. `message` is a fixed generic sentence; the exception text goes to `stderr`, not to the browser |
| 501 | — | Must never occur for `OPTIONS` once §4.4 is implemented |

### 3.4 `GET /api/health`

**Purpose:** the cheap endpoint the static skeleton polls while the container wakes (§9.1). It must **not** score anything — a full queue render is ~1,900 SQL statements and polling it during a wake would be absurd.

Query params: none.

```json
{"ok": true,
 "seeded": true,
 "accounts": 240,
 "reps": [{"rep_id": 1, "name": "Dana Whitfield", "territory": "NA-MidMarket"}],
 "meta": { }}
```

`seeded` is `false` if the `accounts` table is empty or missing; the frontend shows §9.6's copy in that case. Cost: one `SELECT COUNT(*) FROM accounts`, one `SELECT * FROM reps`. `200` when reachable at all; there is no `503` — an unreachable backend produces a `fetch` rejection, not a status code, which is the case §9.2 handles.

### 3.5 `GET /api/reps`

Mirrors `GET /` (`app.py::_index`).

```json
{"reps": [{"rep_id": 1, "name": "Dana Whitfield", "email": "dana.whitfield@example-co.test",
           "territory": "NA-MidMarket"}],
 "meta": { }}
```

### 3.6 `GET /api/queue?rep={n}`

Mirrors `GET /queue` (`app.py::_queue` → `render.render_queue`). Calls `build_run()`, which creates a `score_runs` row and persists the whole run — same as today, per `DESIGN_SPEC.md` §3.7. Logs a `queue_viewed` `task_event`.

Query params: `rep` (integer, default `1`).

`404 NOT_FOUND` if the rep does not exist.

```json
{
  "rep": {"rep_id": 1, "name": "Dana Whitfield", "territory": "NA-MidMarket"},
  "run_id": 41,
  "header_line": "Warrant · Dana Whitfield · NA-MidMarket",
  "run_stamp": "Scored 11 Aug 2026, 09:00 UTC · ruleset warrant-v1.0.0 · 53 accounts · run #41",
  "budget_bar": "pins 2/5 · demotes 1/10 · patch-wide signal suppressions 1/3 · muted accounts 4/25",
  "budgets": {"pin": [2, 5], "demote": [1, 10], "mute_account": [4, 25],
              "suppress_signal_type_global": [1, 3],
              "suppress_signal_type_account": [0, 50], "exclude_person": [0, 50]},
  "account_count": 53,
  "items": [
    {
      "account_id": 1042,
      "account_name": "Kestrel Analytics",
      "rank_in_queue": 1,
      "band": "ACT_NOW",
      "band_label": "ACT NOW",
      "points": 61.24,
      "points_display": "61",
      "top_reason_text": "VP Engineering and 2 others used the product across 3 sessions, most recently 2 days ago.",
      "freshness_chip": "evidence 2d old",
      "freshness_is_stale": false,
      "adjustment_chip": null,
      "limits_compressed": "5 of 10 signals shown",
      "work_it_enabled": true,
      "friction_text": null
    }
  ],
  "meta": { }
}
```

Field notes, all load-bearing:

- `points_display` is `render._points_display(score.points)` — the rounded integer, sign only when negative (§5.1). The frontend appends the literal word `pts` from its own template chrome; it does **not** round, format or sign anything.
- `top_reason_text` is **already truncated server-side** by `reasons.truncate_at_word(text, 120)` (§6.1). The frontend must not truncate. If the shown-reason list is empty, this carries `reasons.thin_data_line(score)` or `reasons.NO_SIGNALS_LINE`, exactly as `render_queue` does today.
- `freshness_chip` is `reasons.freshness_chip(score)` verbatim — `"evidence 2d old"` / `"STALE · 47d"` / `"no evidence"`. `freshness_is_stale` exists only so the frontend can pick a CSS class; it is not used to decide any text.
- `adjustment_chip` is `reasons.adjustment_chip(score)` or `null`.
- `friction_text` is `app.friction_text()` verbatim; `work_it_enabled` is `friction_text is None`. The frontend disables the button and shows the sentence; it does not evaluate the predicate.
- `budget_bar` is the pre-joined string; `budgets` is the raw map for the detail view's per-block counts. Both come from `queue.budget_usage()`.

**The queue payload does not include unshown reasons.** See §3.7.

### 3.7 `GET /api/account/{account_id}?rep={n}`

Mirrors `GET /account/{id}` (`app.py::_detail` → `render.render_detail`). Calls `build_run()` — a fresh scoring run on every detail view, per README deviation 10 and `DESIGN_SPEC.md` §7.4, which is what makes a dispute visible on the very next render. Logs an `item_viewed` `task_event`.

`404 NOT_FOUND` if the rep does not exist. `404 NOT_IN_QUEUE` if the account is not in this rep's current queue.

```json
{
  "account": {
    "account_id": 1042, "name": "Kestrel Analytics", "domain": "kestrelanalytics.io",
    "meta_line": "Data & Analytics · 420 employees · US · CRM: no record · owner: you"
  },
  "verdict": {
    "band": "ACT_NOW", "band_label": "ACT NOW",
    "points": 61.24, "points_display": "61",
    "above_anchor_note": "",
    "anchor_note": "bar for ACT NOW is 45 · scale anchored at 75",
    "rank_line": "rank 1 of 53",
    "confidence": "high",
    "adjusted_note": null
  },
  "banners": [
    {"kind": "conflict", "level": "notice",
     "text": "These signals disagree. VP Engineering and 2 others used the product across 3 sessions, most recently 2 days ago, but Marcus Iwu, our contact here, left on 30 Jun 2026. Read both before you act.",
     "actions": []}
  ],
  "heading": "Why this is at the top",
  "reasons": [
    {
      "reason_id": 8871,
      "signal_type_id": 1,
      "rank": 1,
      "category_label": "ACTIVE EVALUATION",
      "text": "VP Engineering and 2 others used the product across 3 sessions, most recently 2 days ago.",
      "evidence_summary": "28 sessions between 28 Jul 2026 and 9 Aug 2026 · source: product telemetry",
      "points": 24.0,
      "points_display": "+24 pts (capped at 24)",
      "cap_applied": true,
      "is_suppressed": false,
      "suppression_note": null,
      "new_events_note": null,
      "undo_adjustment_id": null,
      "evidence_href": "/api/evidence/8871?rep=1",
      "actions": [
        {"code": "EVIDENCE_WRONG", "label": "this is wrong",
         "fields": {"rep": 1, "account": 1042, "code": "EVIDENCE_WRONG",
                    "signal_type": 1, "reason": 8871}},
        {"code": "EVIDENCE_STALE", "label": "out of date",
         "fields": {"rep": 1, "account": 1042, "code": "EVIDENCE_STALE",
                    "signal_type": 1, "reason": 8871}}
      ]
    }
  ],
  "limits_line": "Showing the 5 strongest of 10 signals. The 5 not shown are worth +27.0 pts combined and are part of why this is ACT NOW — the 5 shown alone would rate REVIEW.",
  "adjust": {
    "budget_line": "pins 2/5 · demotes 1/10 · muted accounts 4/25",
    "buttons": [
      {"kind": "pin", "days": 14, "label": "Pin to top · 14 days",
       "fields": {"rep": 1, "account": 1042, "kind": "pin", "days": 14}},
      {"kind": "demote", "days": 30, "label": "Demote · 30 days",
       "fields": {"rep": 1, "account": 1042, "kind": "demote", "days": 30}},
      {"kind": "mute_account", "days": 60, "label": "Mute · 60 days",
       "fields": {"rep": 1, "account": 1042, "kind": "mute_account", "days": 60}}
    ]
  },
  "item_dispute": {
    "buttons": [
      {"code": "NOT_A_FIT", "label": "Not a fit",
       "fields": {"rep": 1, "account": 1042, "code": "NOT_A_FIT"}},
      {"code": "WRONG_PERSON", "label": "Wrong person (Ana Belic)",
       "fields": {"rep": 1, "account": 1042, "code": "WRONG_PERSON", "person": 4471}},
      {"code": "BAD_TIMING", "label": "Bad timing",
       "fields": {"rep": 1, "account": 1042, "code": "BAD_TIMING", "window": 30}},
      {"code": "ALREADY_WORKING", "label": "Already working this",
       "fields": {"rep": 1, "account": 1042, "code": "ALREADY_WORKING"}},
      {"code": "NOT_MY_PATCH", "label": "Not my patch",
       "fields": {"rep": 1, "account": 1042, "code": "NOT_MY_PATCH"}}
    ],
    "unavailable_note": null
  },
  "history": [
    {"line": "11 Aug 2026 · you said \"Repeat pricing-page visits\" was wrong. suppress_signal_type active until 9 Nov 2026.",
     "status": "applied", "undo_adjustment_id": 312}
  ],
  "research": {
    "heading": "Agent research (3 observations)",
    "items": [{"summary": "Posted two senior data-platform roles in the last three weeks.",
               "source_name": "Company careers page",
               "retrieved_display": "retrieved 28 Jul 2026",
               "source_url_text": "https://app.example.test/research/obs_00412"}],
    "see_all_href": "/api/evidence/observations/1042?rep=1",
    "empty_note": null
  },
  "no_signals_line": null,
  "source_link_note": "Source links are shown as text — this environment has no outbound network.",
  "meta": { }
}
```

**`reasons` contains only reasons with `shown = 1`.** This is not an optimisation, it is `DESIGN_SPEC.md` implication #2 taken literally: *"the rep UI has no expander, no 'show more', no hover-to-reveal-the-rest… They are never rendered to the rep, under any interaction."* Sending the withheld reasons over the wire would put them one devtools panel away from being visible and would leave a tempting array sitting in the payload for someone to build an expander over. The withheld reasons are disclosed **in aggregate, by `limits_line`, exactly as today**.

**Where this leaves the rep's arithmetic.** The brief asks that a rep can still add up the reason points and get the score. The honest answer, unchanged from the HTML app: the shown points sum to `shown_points`, and `limits_line` states the withheld total explicitly (`"+27.0 pts combined"`). `shown_points + withheld_sum == points`. The rep's addition works, and it works the same way it does today. This design does not improve that and does not degrade it. `reasons.build_limits_line()` is the function that guarantees it and it is unchanged.

Suppressed reasons (§7.4): `is_suppressed` is `true`, `points_display` carries `"+15 → 0 pts"` (from `points_label(points_before_adjustment)` plus the arrow, composed in `render.py` today — extract it to `reasons.py` per §2.5), `suppression_note` carries `"You said this was wrong on 11 Aug 2026. Not counted here until 9 Nov 2026."`, `undo_adjustment_id` carries the adjustment to revert, `actions` is empty, and **the reason stays in its slot** — the API sends it in rank order with the others. The frontend must not reorder or remove it.

`banners` `kind` values: `brand_new`, `stale`, `conflict`, `thin`, `expired_dispute`. `level` is `notice` or `warn` and selects a CSS class only. An `expired_dispute` banner carries two `actions` — `{"code": "EVIDENCE_WRONG", "label": "suppress for another 90 days", ...}` and `{"code": "LEAVE_IT", "label": "leave it — it looks right now", ...}` — with the same `fields` shape as everywhere else.

### 3.8 `GET /api/evidence/{reason_id}?rep={n}`

Mirrors `GET /evidence/{reason_id}` (`app.py::_evidence` → `render.render_evidence`).

**This endpoint has a side effect.** It writes an `evidence_opened` `task_event`, which is what clears the §6.4 friction gate (README deviation 8). That is existing behaviour and this design does not change it. Consequence for the frontend: opening the drawer must be a real request, not a client-side reveal of already-fetched data, or the gate will never clear. **Do not prefetch evidence with the detail view.**

`404 NOT_FOUND` if the reason does not exist. Note that `reason_id`s are per-run: a reason id from a previous run is stale after the next `build_run()`. The frontend always uses the `evidence_href` from the current detail payload.

```json
{
  "header": "Evidence · Repeat pricing-page visits · Kestrel Analytics",
  "summary_line": "Reason computed 11 Aug 2026 09:00 UTC from 2 events. Total +14.95 pts (cap +18.00).",
  "kind": "event",
  "events": [
    {"occurred_display": "9 Aug 2026 14:22 UTC",
     "contribution": 9.0142,
     "contribution_display": "+9.01 pts",
     "magnitude_display": "magnitude 2",
     "detail_display": "{\"path\": \"/pricing\", \"visits\": 2}",
     "person_display": "person: Ana Belic, VP Engineering",
     "source_display": "source: website_tracker · ingested 9 Aug 2026 15:03 UTC (41 min later)",
     "ref_display": "ref: https://app.example.test/evidence/ev_004112"}
  ],
  "state_fallback": null,
  "source_link_note": "Source links are shown as text — this environment has no outbound network.",
  "observations": [{"summary": "...", "source_name": "Engineering blog",
                    "retrieved_display": "retrieved 21 Jul 2026"}],
  "actions": [
    {"code": "EVIDENCE_WRONG", "label": "this reason is wrong", "fields": { }},
    {"code": "EVIDENCE_STALE", "label": "this evidence is out of date", "fields": { }},
    {"code": "WRONG_PERSON", "label": "wrong person", "fields": { }}
  ],
  "back_href": "/api/account/1042?rep=1",
  "meta": { }
}
```

For `kind='state'` reasons there are no `reason_evidence` rows (`DESIGN_SPEC.md` §3.9). `events` is `[]` and `state_fallback` carries the server-composed fallback paragraph `render_evidence` produces today, including the account's `data_last_refreshed_at` stamp. The frontend does not decide which to show — it shows `events` if non-empty, else `state_fallback`, and both are server-supplied.

`ref_display` is deliberately a **string, never rendered as an anchor** (README limitation 11, `DESIGN_SPEC.md` §2 row 10). The frontend must render it as selectable text. A `<a href>` here would 404 by design and is forbidden.

### 3.9 `GET /api/evidence/observations/{account_id}?rep={n}`

Mirrors `GET /evidence/observations/{id}`.

```json
{"account_name": "Kestrel Analytics",
 "count_line": "3 observation(s). Source links are shown as text — this environment has no outbound network.",
 "items": [{"summary": "...", "source_name": "Company careers page",
            "retrieved_display": "retrieved 28 Jul 2026",
            "agent_run_display": "agent run run_2026-07-28_a41c",
            "source_url_text": "https://app.example.test/research/obs_00412"}],
 "back_href": "/api/account/1042?rep=1",
 "meta": { }}
```

### 3.10 `GET /api/adjustments?rep={n}`

Mirrors `GET /adjustments`.

```json
{"rep": {"rep_id": 1, "name": "Dana Whitfield", "territory": "NA-MidMarket"},
 "budget_bar": "pins 2/5 · demotes 1/10 · patch-wide signal suppressions 1/3 · muted accounts 4/25",
 "budgets": {"pin": [2, 5]},
 "rows": [
   {"adjustment_id": 312, "kind": "suppress_signal_type",
    "line": "suppress_signal_type · Kestrel Analytics · Repeat pricing-page visits",
    "created_display": "created 11 Aug 2026",
    "expires_display": "active until 9 Nov 2026",
    "is_active": true,
    "undo_adjustment_id": 312,
    "account_id": 1042}
 ],
 "meta": { }}
```

`line`, `created_display` and `expires_display` are composed server-side from the same joined row `render.render_adjustments` uses today.

### 3.11 `GET /api/metrics`

Mirrors `GET /metrics` (`metrics.collect()`). Every rate is sent as raw numerator/denominator **and** as the `metrics.format_rate()` string, which renders `—` when the denominator is zero.

```json
{
  "window_line": "Trailing 30 days to 11 Aug 2026, 09:00 UTC",
  "rates": [
    {"key": "top3", "label": "Top-3 acceptance rate",
     "numerator": 86, "denominator": 140, "value": 0.6142857, "display": "61.4%",
     "note": "no target set; v1 establishes baseline"},
    {"key": "evidence_open", "label": "Evidence-open rate",
     "numerator": 48, "denominator": 140, "value": 0.3428571, "display": "34.3%", "note": null},
    {"key": "item_dispute", "label": "Item dispute rate", "display": "9.1%", "note": null},
    {"key": "revert", "label": "Revert rate", "display": "7.8%", "note": null},
    {"key": "skip_silent", "label": "Skip-with-no-dispute rate", "display": "—",
     "note": "reps who skip without telling us why are the ones we are losing"}
  ],
  "per_type": [
    {"signal_type_id": 9, "code": "third_party_intent_6sense",
     "display_name": "Third-party intent (6sense)",
     "shown_count": 118, "dispute_count": 11, "dispute_rate_display": "9.3%",
     "reps_saw": 1, "reps_disputed": 1, "suppression_rate_display": "100.0%",
     "flagged": false, "flag_text": ""}
  ],
  "ownership_errors": [{"account_id": 77, "account_name": "Thistle Works", "n": 2}],
  "caveat_lines": [
    "/metrics numbers are computed by live SQL over synthetic instrumentation. The arithmetic is real; the inputs are seeded.",
    "Per-signal-type show counts only exist once someone has loaded a queue."
  ],
  "meta": { }
}
```

`caveat_lines` carries README honest-limitations 4 and 5 as server-supplied strings. They must appear on the page. A metrics page that presents synthetic rates without saying they are synthetic is exactly the overclaim `DESIGN_SPEC.md` §4.6 exists to prevent.

### 3.12 `GET /api/ruleset`

Mirrors `GET /ruleset`.

```json
{
  "header_line": "This is how the weights are set, and how often reps disagree with each one. It is not why any particular account ranked where it did — that is on the account's own page.",
  "ruleset_version": "warrant-v1.0.0",
  "evidence_note": "18 of the 19 weights are reasoned, not measured. Only product_usage_active traces to evidence — Unify's published 9.1% positive-reply benchmark.",
  "anchor_note": "75 is the point total a strong, current, multi-signal account reaches. It is a fixed bar set by RevOps, not a maximum and not a percentile. An account can exceed it.",
  "rows": [
    {"signal_type_id": 1, "code": "product_usage_active",
     "display_name": "Active product usage", "category": "active_evaluation",
     "polarity": "positive", "kind": "event",
     "base_weight": 12.0, "base_weight_display": "+12.0",
     "max_contribution": 24.0, "max_contribution_display": "+24.0",
     "half_life_display": "14 d", "lookback_days": 365,
     "shown_count": 402, "dispute_count": 3, "dispute_rate_display": "0.7%",
     "flagged": false, "flag_text": ""}
  ],
  "meta": { }
}
```

Note README honest-limitation 3: the `REVIEW REQUIRED` flag is unreliable at small n because the rep denominator is the number of reps who have loaded a queue. `flag_text` is passed through unchanged; the frontend does not reinterpret it.

### 3.13 The four writes

All four: `POST`, body `application/x-www-form-urlencoded`, field names **identical to the existing HTML forms** so `app.py::_form()` parses both paths with the same code.

#### `POST /api/dispute`

| Field | Required | Notes |
|---|---|---|
| `rep` | yes | integer |
| `account` | yes | integer |
| `code` | yes | one of the seven §7.1 codes, or `LEAVE_IT` |
| `signal_type` | for reason-scoped | integer |
| `reason` | optional | integer |
| `person` | required for `WRONG_PERSON` | integer. Refused, not guessed, if absent (README deviation 11) |
| `note` | optional | ≤ 280 chars, truncated server-side |
| `window` | optional | integer days; ignored unless in the code's allowed set |
| `rank` | optional | integer, `rank_at_event` |

`200`:

```json
{"ok": true,
 "disagreement_id": 91,
 "effect": {"kind": "suppress_signal_type", "expires_display": "9 Nov 2026",
            "confirmation": "You said \"Repeat pricing-page visits\" was wrong. Suppressed for this account until 9 Nov 2026.",
            "undo_adjustment_id": 312},
 "next": {"view": "account", "href": "/api/account/1042?rep=1"},
 "meta": { }}
```

`409 BUDGET_EXCEEDED` on `queue.BudgetExceeded`. `400 BAD_REQUEST` on `feedback.DisputeError`.

`next.view` is one of `account` or `queue`, **decided server-side**. This matters: `NOT_A_FIT`, `ALREADY_WORKING` and `NOT_MY_PATCH` create a `mute_account` adjustment, and the account leaves the queue immediately, which means `GET /api/account/{id}` will return `404 NOT_IN_QUEUE` on the very next request. Today's HTML app redirects to the account page and the rep gets a 404-ish "Not in this queue" screen. **In the ported UI the server names `queue` as the next view for mute-producing codes and hands back the `effect.confirmation` sentence, so the rep sees the confirmation and the return date that `DESIGN_SPEC.md` §7.2 requires, not an error.** This is a behaviour improvement over the HTML app, forced by porting, and it is called out in §10 as a deliberate divergence.

For `code=LEAVE_IT` (§8.6b) the response carries `"effect": {"kind": "reviewed", "confirmation": "Noted — the signal keeps counting.", "undo_adjustment_id": null}`.

#### `POST /api/adjust`

Fields: `rep`, `account`, `kind` (`pin` | `demote` | `mute_account`), `days` (default 30).

`200`:

```json
{"ok": true, "adjustment_id": 313,
 "effect": {"kind": "pin", "expires_display": "27 Aug 2026",
            "confirmation": "Pinned to the top of your queue until 27 Aug 2026.",
            "undo_adjustment_id": 313},
 "next": {"view": "account", "href": "/api/account/1042?rep=1"},
 "meta": { }}
```

`409 BUDGET_EXCEEDED`. For `mute_account`, `next.view` is `queue`.

#### `POST /api/adjust/revert`

Fields: `rep`, `adjustment` (integer), `account` (optional integer).

`200`:

```json
{"ok": true, "adjustment_id": 312,
 "effect": {"kind": "reverted", "confirmation": "Undone. The signal counts again from now.",
            "undo_adjustment_id": null},
 "next": {"view": "account", "href": "/api/account/1042?rep=1"},
 "meta": { }}
```

If `account` is absent, `next` is `{"view": "adjustments", "href": "/api/adjustments?rep=1"}` — mirroring `app.py::_post_revert`. Note `queue.revert_adjustment()` returns `None` for an adjustment that does not belong to this rep and writes nothing; the API returns `404 NOT_FOUND` in that case rather than a silent `ok: true`. That is a small hardening over today's HTML path, named in §10.

#### `POST /api/task`

Fields: `rep`, `account`, `rank`, `action` (`accepted` | `skipped`).

`200`:

```json
{"ok": true, "next": {"view": "queue", "href": "/api/queue?rep=1"}, "meta": { }}
```

`400 BAD_REQUEST` for an unknown `action`. `409 EVIDENCE_REQUIRED` when `action=accepted` and the §6.4 gate applies:

```json
{"error": {"code": "EVIDENCE_REQUIRED",
           "title": "Open the evidence first",
           "message": "Open evidence on one reason before working this — you disputed a reason on this account on 4 Aug 2026.",
           "detail": {"account_id": 1042},
           "action": {"label": "open the account", "href": "/api/account/1042?rep=1"}}}
```

The `message` is `app.friction_text()` verbatim. The frontend shows it; it does not re-derive it.

### 3.14 What the frontend never has to compute — checklist

The maker should be able to tick every one of these off the payloads above:

rounding · sign · the word `pts` next to a number · `(capped at 24)` · rank order · which reasons are shown · the 120-char truncation · the limits line · the band chip label · `NOT ENOUGH TO SAY` · the confidence word · the anchor sentence · the rank line and its `(was 3 before your adjustments)` clause · the freshness chip and its `STALE · 47d` form · the adjustment chip · `5 of 10 signals shown` · the friction sentence · the budget bar · the budget-exceeded sentence · every banner sentence · the `+15 → 0 pts` suppression display · every dispute button label · the evidence drawer's totals line · every metrics percentage · the `—` for a zero denominator · the ruleset flag text · the ephemeral-storage notice.

---

## 4. CORS policy, precisely

### 4.1 The problem, restated from the research

`https://<your-username>.github.io` and `https://<your-app>.onrender.com` are different origins (§1.5). Without the right response headers the browser fetches the response, refuses to hand it to the script, and **the backend logs a clean 200 while the user sees an empty page** (§1.5, "the trap worth naming now"). Anyone debugging from the server side concludes everything is fine. §9.3 specifies what the user sees so this is not silent.

`https://` on both ends is non-negotiable (§1.4): a Pages site cannot `fetch()` an `http://` backend at all — the request never leaves the browser. Both hosts give HTTPS on their default domains.

### 4.2 Configuration — env var, never hardcoded

The user's GitHub username is not known to anyone in this pipeline, so the allowed origin cannot be a literal in the source.

```
WARRANT_ALLOWED_ORIGINS=https://<your-username>.github.io
```

- Set in the **Render dashboard**, as a plain environment variable. It is not a secret and it is not a credential; it is a configuration value that happens to be user-specific.
- Comma-separated for multiple origins, e.g. a Pages site plus `http://localhost:8000` for local development. Whitespace around commas is stripped.
- **Compared as an exact string** against the request's `Origin` header. No prefix matching, no regex, no suffix matching. `https://evil-<your-username>.github.io` must not match.
- **Default is empty**, and empty means **no CORS headers are emitted at all**. Fail closed. A backend that defaults to permissive is a backend that ships permissive.
- The literal value `*` is accepted as an explicit, documented opt-in for debugging only, and emits `Access-Control-Allow-Origin: *`. This is safe here only because there are no credentials, no cookies and no authentication anywhere in Warrant (`README.md`: *"there are no credentials anywhere in this repo"*). It is still not recommended, and the runbook should say so.

Note that GitHub Pages serves a project site at `https://<user>.github.io/<repo>/`, but the **origin** is `https://<user>.github.io` — no path. Setting the variable to the full page URL will not match and will produce §9.3's failure. Say so in the runbook.

### 4.3 Methods and headers allowed

- `Access-Control-Allow-Methods: GET, POST, OPTIONS`
- `Access-Control-Allow-Headers: Content-Type`

Nothing else. `HEAD` is not advertised because `BaseHTTPRequestHandler` has no `do_HEAD` and `app.py` does not add one — advertising a method that returns 501 is worse than not advertising it. There is no `Authorization` header because there is nothing to authenticate to. `Access-Control-Allow-Credentials` is **not** sent; no request carries credentials.

### 4.4 Preflight — `do_OPTIONS`

`app.py` has no `do_OPTIONS` today (§0.2). Add one.

```
def do_OPTIONS(self):  ->  200, Content-Length: 0, CORS headers, no body
```

**Exact preflight response:**

```
HTTP/1.1 200 OK
Server: Warrant/1.0 Python/3.14.3
Date: <RFC 1123>
Content-Length: 0
Access-Control-Allow-Origin: https://<your-username>.github.io
Access-Control-Allow-Methods: GET, POST, OPTIONS
Access-Control-Allow-Headers: Content-Type
Access-Control-Max-Age: 600
Vary: Origin
```

Three details that are decisions, not incidentals:

1. **`200`, not `204`.** RFC 7230 forbids `Content-Length` on a `204`, and `Handler.protocol_version = "HTTP/1.1"` means keep-alive is on and framing must be unambiguous. `_redirect()` (`app.py` L108–112) already establishes the safe pattern in this codebase — an explicit `Content-Length: 0`. A `200` with `Content-Length: 0` is valid for a preflight (the CORS spec accepts any 2xx) and cannot desynchronise the connection. Do not "fix" this to `204`.
2. **`Access-Control-Max-Age: 600` is not a cache of data.** It caches the browser's permission decision for ten minutes. It caches no score, no reason, no row. It does not violate §7's no-caching rule and the maker should not remove it thinking it does.
3. **If the `Origin` is not in the allowlist, `do_OPTIONS` returns `200` with `Content-Length: 0` and no CORS headers at all.** Not a `403`. The browser then blocks the actual request, which is the correct outcome, and the server has not leaked which origins are configured.

### 4.5 Do the writes send JSON or form-encoded? — form-encoded, and here is why

**Decision: `application/x-www-form-urlencoded`.** Three reasons, in order of weight:

1. **It reuses `app.py::_form()` exactly.** `_form()` reads `Content-Length`, decodes UTF-8, and `parse_qs(raw, keep_blank_values=True)`. Every existing POST handler then pulls fields through `_one()` and `_int()`. Sending JSON would require a second body parser and a second set of coercions — a second code path doing the same job, which is the same species of mistake decision 1 exists to prevent, one layer down. The HTML form path and the JS path submit **byte-identical bodies** to **one handler**.
2. **It avoids preflight entirely on the hot path.** §1.5 [VERIFIED via MDN]: a request is "simple" for GET/HEAD/POST with only CORS-safelisted headers and a `Content-Type` of `application/x-www-form-urlencoded`, `multipart/form-data` or `text/plain`. `fetch(url, {method:"POST", body: new URLSearchParams({...})})` sets `Content-Type: application/x-www-form-urlencoded;charset=UTF-8` automatically and sends **no preflight**. JSON writes would add an `OPTIONS` round trip to every dispute, every adjust, every revert, every task. On a container that is being woken from sleep, doubling the round trips on the first write is a cost paid for nothing.
3. **`app.py`'s own docstring** says *"Every action is a real `<form>` POST"*. Keeping the wire format identical keeps that sentence true.

**Preflight is still specified and still required**, for three reasons: a future maker may add a custom header and would otherwise get an opaque 501; some browsers and extensions issue `OPTIONS` in situations outside the simple-request rules; and a 501 with no CORS headers is the least debuggable failure in this whole system. `do_OPTIONS` is a correctness backstop, not dead code.

The frontend must **not** set `Content-Type` manually and must **not** send `JSON.stringify`. Using `URLSearchParams` as the body is the specified idiom.

### 4.6 Exact headers on actual responses

Every `/api` response, when `Origin` is present and in the allowlist:

```
HTTP/1.1 200 OK
Server: Warrant/1.0 Python/3.14.3
Date: <RFC 1123>
Content-Type: application/json; charset=utf-8
Content-Length: <bytes>
Cache-Control: no-store
Access-Control-Allow-Origin: https://<your-username>.github.io
Vary: Origin
```

When `Origin` is absent (curl, the runbook's verification step, a same-origin request from the HTML app): identical minus the two CORS lines. When `Origin` is present but **not** in the allowlist: identical minus the two CORS lines — the response is produced normally and the browser discards it. That is the §1.5 trap, and it is why §9.3 exists.

`Vary: Origin` is mandatory whenever the allowlist has more than one entry, and is cheap to always send. Without it any intermediary cache could serve one origin's `Access-Control-Allow-Origin` to another.

The existing HTML routes are unchanged and get no CORS headers. They do not need them; they are same-origin.

`Cache-Control: no-store` is discussed in §7.

---

## 5. Frontend spec

### 5.1 Files — no build step

```
docs/
  index.html        single-page shell; all views live here
  config.js         window.WARRANT_CONFIG = { apiBase: "..." };   <-- the only file the user edits
  app.js            router, fetch, DOM construction
  styles.css        presentation only
  .nojekyll         empty file; required per HOSTING_RESEARCH §1.2
```

Five files, no bundler, no npm, no transpiler, no framework, no Actions workflow. GitHub Pages is pointed at **branch = default, folder = `/docs`** in repo Settings → Pages, which is a dropdown (§1.2 option 2). `.nojekyll` is present because §1.2 notes Jekyll is the default builder for branch sources and will skip paths beginning with an underscore.

`app.js` and `config.js` are plain scripts loaded with `<script src="config.js"></script>` then `<script src="app.js"></script>` — `config.js` first, so `app.js` can read it. No modules, no `type="module"`, because `file://` testing of ES modules fails on CORS and the user will want to open `docs/index.html` locally.

`styles.css` is a copy of the `CSS` constant in `warrant/render.py`. **This is a knowing duplication and it is presentation only** — colours, borders, monospace stack, chip classes. It carries no logic, no threshold, no string a rep reads. If the two drift, the Pages site looks slightly different from the Render HTML site, which is cosmetic. Duplicating anything from `reasons.py` or `scoring.py` would not be cosmetic and is forbidden by §2.

### 5.2 How the frontend learns the backend URL

```js
// docs/config.js
// The only file you edit after deploying the backend.
// Paste your Render service URL here. No trailing slash.
// This is a public URL, not a secret. There are no keys in this project.
window.WARRANT_CONFIG = {
  apiBase: "https://<your-app>.onrender.com"   // placeholder — replace with your own
};
```

Rules:

- **A plain URL string, never a key.** There is nothing to authenticate to (§8).
- **Never a literal buried in application logic.** `app.js` reads `window.WARRANT_CONFIG.apiBase` in exactly one place, into one constant, and every request is built from that constant. Grepping `app.js` for `onrender` must return zero hits.
- If `apiBase` is missing, empty, or still the literal placeholder string containing `<your-app>`, `app.js` renders §9.5's state and makes **no network request at all**. Detecting the unedited placeholder is a substring check for `"<your-app>"`, which is cheap and catches the single most likely user error.
- `config.js` is served by Pages as a static file and is world-readable. That is fine and expected. It is why nothing secret may ever go in it.

### 5.3 Routing

Hash-based, because GitHub Pages has no SPA rewrite and a path-based deep link would 404 on refresh.

| Hash | View | Endpoint |
|---|---|---|
| `#/` (or empty) | Rep index | `GET /api/reps` |
| `#/queue?rep=1` | Queue | `GET /api/queue?rep=1` |
| `#/account/1042?rep=1` | Detail | `GET /api/account/1042?rep=1` |
| `#/evidence/8871?rep=1` | Evidence drawer | `GET /api/evidence/8871?rep=1` |
| `#/research/1042?rep=1` | All observations | `GET /api/evidence/observations/1042?rep=1` |
| `#/adjustments?rep=1` | Adjustments list | `GET /api/adjustments?rep=1` |
| `#/metrics` | Metrics | `GET /api/metrics` |
| `#/ruleset` | Ruleset | `GET /api/ruleset` |

`hashchange` drives the router. Back and forward work. A pasted deep link works.

### 5.4 Rendering rules

1. **`textContent`, never `innerHTML`, for every server-supplied string.** `render.py` escapes with `html.escape` because it emits HTML; JSON does not escape, and account names and rep notes come from data. `innerHTML` anywhere in `app.js` is a bug.
2. **No client-side formatting of any rep-facing value.** The forbidden list, concretely: `Math.round`, `toFixed`, `+"%"`, `"+" + n`, `n + " pts"`, `"rank " + a + " of " + b`, `.slice(0, 120)`, `.sort(...)` over reasons or items, `.filter(r => r.shown)`, any `if (points >= 45)`. If the maker needs one of these, the payload is missing a field and the fix is in `warrant/api.py`, not in `app.js`.
3. The frontend **may** append fixed chrome words that are part of its own layout — the literal `pts` after `points_display`, section headings like `YOUR HISTORY ON THIS ACCOUNT` — because those are labels, not values. Every **value** comes from the server.
4. Element order inside a reason is fixed and must match `DESIGN_SPEC.md` §6.2: **category tag → sentence → evidence line → points → actions.** The points value comes after the evidence, never before it. This is implication #3 and it is not a styling preference.
5. Page order on the detail view is fixed: **evidence first, priority second.** The reasons block is above the fold; the band and points sit in a compact strip beneath the account name, not in a hero position.

### 5.5 What a rep sees — view by view

**Queue view.** Header line, run stamp, budget bar, then rows in `rank_in_queue` order. Each row: rank, band chip, account name (link to `#/account/{id}?rep=N`), points right-aligned, top reason (already truncated), freshness chip, adjustment chip if present, compressed limits (`5 of 10 signals shown`), and the three controls — `Work it` (disabled with `friction_text` as the title and as a visible line when `work_it_enabled` is false), `Not now`, `Dispute` (a link to `#/account/{id}?rep=N` anchored at the dispute block, because item-scoped disputes need the evidence in view first, §6.1).

**Detail view.** Account header and meta line; verdict strip with band chip, points, anchor note, rank line, confidence word, and the `was 60 pts before your disagreement` line when present; banners in payload order; the `Why this is at the top` / `Why this ranked 47` heading; the shown reasons; **the limits line, always, immediately under the reasons**; the adjust block with its budget counts; the item dispute block; `Your history on this account`; the agent research block with `see all research`; a footer link to `#/ruleset`.

**The limits line is mandatory.** Test T09 asserts every rendered detail view contains a non-empty one. The ported frontend must fail visibly rather than render a detail view without it — if `limits_line` is missing or empty in the payload, render the string `"limits line missing — this is a bug"` rather than nothing. A silently absent limits line is the Einstein failure `DESIGN_SPEC.md` §4.6 exists to prevent.

**Evidence drawer.** Rendered as a distinct route, not a client-side reveal (§3.8 — it must issue the request that writes `evidence_opened`). Header, summary line with the two-decimal total and the cap, then one block per event with its `+9.01 pts`, person, source with ingestion lag, and `ref:` as **selectable text, not a link**. Then the source-link note, then the three dispute actions, then a back link.

**The dispute / adjust / revert loop.** Every action button submits its `fields` object as `URLSearchParams` to the matching `POST /api/...`. On `200`, the frontend shows `effect.confirmation` and then navigates to the hash route corresponding to `next.view`, which re-fetches and re-renders — so the rep sees the reason struck through, the points drop, and the band change on the very next render, which is `DESIGN_SPEC.md` §7.4's central behaviour. On `409` it shows `error.title` and `error.message` and, if present, `error.action` as a link. On `4xx`/`5xx` generally it shows `error.message`. **It never disables a control on its own initiative** — the server decides via `work_it_enabled`, `unavailable_note` and the 409s.

Undo: any `undo_adjustment_id` renders an `undo` button posting to `/api/adjust/revert`.

### 5.6 Accessibility and the no-JS reality

The Pages frontend requires JavaScript. That is decision 1's cost and it is stated in §1.2 and §10. Two mitigations, both cheap:

- `docs/index.html` contains a `<noscript>` block naming the Render URL as a working, fully server-rendered alternative: *"This page needs JavaScript. The same product, server-rendered and working without JavaScript, is at `https://<your-app>.onrender.com/queue?rep=1`."* The URL is written into the `<noscript>` block by `app.js`… which cannot run. So the runbook must have the user paste the same URL into `index.html`'s `<noscript>` block, or the block names `config.js` as the place to look. **Simplest correct answer: the `<noscript>` block says "this page needs JavaScript; the server-rendered version is at the backend URL configured in `docs/config.js`."** No duplication of the URL.
- Buttons are real `<button>` elements; links are real `<a href="#/...">`. Keyboard navigation works without extra code.

---

## 6. Data migration plan

### 6.1 Schema and SQL changes: **none. Zero. This is a finding, not an assumption.**

I checked it rather than inheriting §6.1's claim.

| Thing that would normally need migrating | Status | Evidence |
|---|---|---|
| `db/schema.sql` DDL | **Unchanged** | The database stays SQLite. None of HOSTING_RESEARCH §4.1's thirteen Postgres breakages apply, because none of them are triggered by moving a SQLite file to a different machine |
| Every `execute()` string | **Unchanged** | `?` placeholders stay `?`. T20 keeps meaning what it means |
| `cursor.lastrowid` (5+ sites: `queue.py` L116, L229, L273, L289; `feedback.py` L79, L123) | **Unchanged** | Still `sqlite3` |
| `sqlite3.Row` row factory and every `row["col"]` access | **Unchanged** | `db.py` L55 |
| `PRAGMA foreign_keys = ON` (`db.py` L56, L64; `schema.sql`) | **Unchanged** | Still SQLite, still honoured |
| `executescript()` (`db.py` L63) | **Unchanged** | |
| `REAL` precision under T07's exact-equality assertion | **Unchanged** | 8-byte IEEE double, as today. This is the one that matters most — §4.1 breakage #7 puts a single-precision change directly under the product's headline claim, and this design never goes near it |
| `dict(conn.execute(...).fetchall())` in `metrics.py` (L122, L128, L134, L138, L142) | **Unchanged** | §4.1 breakage #9's silent-wrong-answer failure mode does not arise |
| Third-party driver | **None** | `test_every_python_file_imports_only_stdlib_or_local` (T19) keeps passing unchanged |

**"No migration" is the single strongest argument for this stack** and it should be stated in the runbook as a positive, not omitted as a non-event. HOSTING_RESEARCH §4.4: *"If the Python process and the SQLite file are on the same machine, **zero** of §4.1's thirteen breakages apply."*

Two facts from `warrant/db.py` that make the move painless and that I verified rather than assumed:

- `SCHEMA_PATH` (L19–20) is derived from `os.path.abspath(__file__)`, so `apply_schema()` finds `db/schema.sql` regardless of the container's working directory.
- `db_path()` (L23–28) already honours an **absolute** `WARRANT_DB_PATH` verbatim and resolves a relative one from the repo root. So `WARRANT_DB_PATH=/var/data/unify.db` works today, with no code change. That is the whole of the persistent-volume story on the path side.

### 6.2 Boot sequence

New file at the repo root, `start.py`, stdlib only, ~30 lines. It is the Render **Start Command**: `python start.py`.

```
start.py:
  1. resolve target = warrant.db.db_path()
  2. seed_needed = (not os.path.exists(target))  or  WARRANT_FORCE_RESEED == "1"
  3. if seed_needed:  import seed_db; seed_db.main()          # prints its summary to stdout
     else:            print("database already present at <path>, skipping seed")
  4. import app; app.main()                                    # serve_forever()
```

Why `start.py` rather than a shell start command like `python seed_db.py && python app.py`:

- The seed step must be **conditional**, and a conditional in a dashboard text field is a quoting problem waiting to happen.
- It is testable. A shell string in a vendor dashboard is not.
- It is the single line the user types into one field, identical on Render, Railway or Fly, which is what makes §6.4's upgrade a configuration change.

`start.py` imports only `os`, `sys`, `seed_db` and `app`, so **T19 keeps passing and no `requirements.txt` entry is added.**

### 6.3 The `app.py` bind change — exactly two lines of behaviour

Resolved from source (§0.2), not inferred:

Today, `app.py` L438–439:

```python
listen_port = port()                                        # WARRANT_PORT, default 8000
server = ThreadingHTTPServer(("127.0.0.1", listen_port), Handler)
```

Required:

1. **Host from configuration.** Add `bind_host()` to `warrant/db.py` alongside the existing `port()`, reading `WARRANT_BIND_HOST` with default `"127.0.0.1"`. The container sets `WARRANT_BIND_HOST=0.0.0.0`. **The default stays `127.0.0.1`**, so a local `python app.py` behaves exactly as `README.md` documents and nobody accidentally exposes their laptop.
2. **Port from the platform.** Change `warrant/db.py::port()` to read `WARRANT_PORT` first, then `PORT`, then default `8000`. Render injects `PORT`; the codebase's own variable keeps precedence so local behaviour is unchanged. Update the `README.md` table row for `WARRANT_PORT` — it currently says "bound to 127.0.0.1 only", which will no longer be the whole truth.

That is the entire backend hosting change outside the API and CORS work. `serve_forever()`, `ThreadingHTTPServer`, the handler and every route are untouched.

### 6.4 Fixed-seed reproducibility — preserved, and verified

`seed_db.py::main()` calls `rng.seed(seed_value())` where `seed_value()` reads `WARRANT_SEED`, default `20260811`. `WARRANT_AS_OF` defaults to `2026-08-11T09:00:00Z`. **Neither is set in the container**, so the defaults apply and every boot regenerates the identical corpus.

This is what makes the ephemeral disk survivable. HOSTING_RESEARCH §6.1: *"A restart does not lose the demo. It restores it, byte for byte."* Test T01 (`tests/test_scoring.py::TestT01Reproducibility::test_seed_is_reproducible`) asserts exactly this by seeding twice into two files and comparing every row of `accounts`, `people` and `signal_events`.

**How it is verified on the deployed instance**, without a shell:

1. `GET /api/health` returns `accounts: 240`, `seeded: true`, and `meta.as_of == "2026-08-11T09:00:00Z"`.
2. `GET /api/queue?rep=1` returns `account_count: 53` and a rank-1 account. Note this figure: `STATUS_REPORT.md` records "rank 2 of 53" for rep 1's patch, so 53 is the expected number and a different number means the seed or the `as_of` differs.
3. After any redeploy, repeat step 2 and compare the top few `account_name` and `points_display` values. They must be identical. If they are not, either `WARRANT_SEED` or `WARRANT_AS_OF` has been set in the dashboard, or the Python version's `random` module differs — **the second is a real risk and is named in §10.**

`start.py` should print the same summary block `seed_db.main()` already prints (cohort counts, event totals, the verified line) so the Render deploy log is the reproducibility record.

### 6.5 What happens on redeploy — decided, not inherited

HOSTING_RESEARCH §6.2 cost #1 says explicitly: *"The design stage should decide this explicitly rather than inherit it."* Here is the decision.

**Decision: ship on ephemeral storage, and disclose it in the product, in the rep's own sentence, on every view.**

On every spin-down, restart and redeploy, the container loses `disagreements`, `queue_adjustments`, `score_runs`, `scores`, `reasons`, `reason_evidence` and `task_events`. The reference and lead data — `reps`, `accounts`, `people`, `signal_types`, `signal_events`, `observations` and the seeded backdated `task_events` — are regenerated byte-identically. **A dispute a rep filed yesterday is gone today**, and `/metrics` returns to its seeded baseline.

The research is right that this is the exact failure Warrant exists to prevent. `warrant/feedback.py`'s own docstring: *"if disagreement changes nothing, reps stop registering it within weeks."* **A demo that quietly forgets a rep's dispute is enacting that failure.** Quietly is the operative word, and it is the part this design refuses.

So, three requirements, all binding:

1. **`meta.persistence_notice` is on every read response** (§3.2) and the frontend renders it as a persistent line at the top of every view — not a dismissible toast, not a footnote. Copy:

   > *This demo server runs on free hosting with no persistent disk. It last restarted on 13 Aug 2026, 11:04 UTC. Anything a rep filed before then — disputes, pins, mutes — is gone. Everything you file now lasts until the next restart.*

   The restart time is real: `meta.started_at_display`, captured once at process start.

2. **The confirmation after any write says the same thing in one clause.** `effect.confirmation` for a dispute on an ephemeral instance ends with: *"…until 9 Nov 2026, or until this demo server restarts, whichever comes first."* Composed server-side, conditional on `WARRANT_PERSISTENCE`. This is the sentence that matters most, because it is the moment the rep has just extended trust.

3. **`meta.boot_id`** is a short random hex string generated once at process start. The frontend keeps the `boot_id` it last saw; if a response arrives with a different one, the rep is told: *"The demo server restarted. Anything you filed in this session is gone. The queue below has been rebuilt from the same seeded data."* This turns an inexplicable disappearance into an accounted-for one, which is the same principle as §5.2's cold-start argument.

When `WARRANT_PERSISTENCE=persistent`, all three change: `persistence_notice` is `null` and rendered as nothing, the confirmation loses its trailing clause, and the boot-id notice is suppressed. **One env var, three behaviours, zero code branches in the frontend** — the frontend renders what it is given.

### 6.6 The upgrade path — a configuration change, not a rewrite

HOSTING_RESEARCH §6.3 identifies Railway Hobby ($5/month, 5 GB volume) and Fly.io (volumes at $0.15/GB/month) as the same architecture with a persistent disk and no cold start. Railway is browser-driven, which fits the no-CLI constraint; Fly leans on `flyctl`, which is not installed.

Everything in this design is built so that switching is **four dashboard values and nothing else**:

| Variable | Render (free, ephemeral) | Railway Hobby / Fly (persistent volume) |
|---|---|---|
| `WARRANT_DB_PATH` | *(unset — defaults to `data/unify.db` in the container)* | `/var/data/unify.db` (the volume mount path) |
| `WARRANT_PERSISTENCE` | `ephemeral` | `persistent` |
| `WARRANT_BIND_HOST` | `0.0.0.0` | `0.0.0.0` |
| `WARRANT_ALLOWED_ORIGINS` | `https://<your-username>.github.io` | `https://<your-username>.github.io` |
| Start command | `python start.py` | `python start.py` |
| `docs/config.js` `apiBase` | `https://<your-app>.onrender.com` | the new host's URL |

No code change. No schema change. No SQL change. No new dependency. The `start.py` conditional (§6.2 step 2) is what makes the volume case correct: on first boot the volume is empty and `seed_db.main()` runs; on every subsequent boot the file exists and the seed is skipped, so **the reps' disputes survive**. That conditional is the single line that turns the upgrade from a rewrite into a setting, and it must be in the first version, not added later.

`WARRANT_FORCE_RESEED=1` exists as the escape hatch for wiping a persistent volume back to the pristine corpus without shell access. It is off by default and the runbook should mark it as destructive.

**A Postgres migration is explicitly not designed and not recommended.** HOSTING_RESEARCH §6.5 recommends against it for this codebase — thirteen concrete breakages, a mandatory third-party driver that ends stdlib-only, a silent-wrong-answer failure mode on `/metrics`, and a float-precision change sitting under the exact-equality test that carries the product's central claim. I agree, and this document does not open that door.

---

## 7. How the API stays live-query

### 7.1 The property being preserved

`README.md`: *"Every score is computed from live SQL at request time… There is no cache, no memoisation and no precomputed score literal anywhere in `warrant/` or `app.py`."* `warrant/scoring.py::score_account()`: *"No caching, no memoisation: the caller gets what the database says right now."*

Adding a JSON layer is the classic moment a cache gets introduced, because ~1,900 SQL statements per request looks like a performance problem to anyone who has not read why it is the feature. It is not a performance problem here; it is the mechanism by which a dispute is visible on the very next render (`DESIGN_SPEC.md` §7.4) and by which the three live-DB tests mean anything.

### 7.2 What counts as a violation

Any one of these ships a cache and breaks the guarantee:

1. A module-level or class-level dict in `warrant/api.py`, `app.py` or anywhere in `warrant/` keyed by `(rep_id, account_id)` or `run_id` holding scores, reasons or serialised payloads.
2. `functools.lru_cache` / `functools.cache` on anything in the `score_account` → `build_run` → `build_reasons` → `api.serialise` chain, including on `load_signal_types()`.
3. Reusing a `run_id` instead of calling `build_run()` — e.g. serving `GET /api/account/{id}` by reading the persisted `scores` and `reasons` rows from the last run rather than re-scoring. This is the most likely violation because it looks like an obvious optimisation and the rows are right there. `app.py::_detail` calls `build_run()` today for exactly this reason (README deviation 10); the API must too.
4. `Cache-Control` on an `/api` response that is anything other than `no-store`. Also `ETag`, `Last-Modified`, or any conditional-request support. Render sits behind a CDN edge; a cacheable `/api/queue` would be served from that edge and the rep would see a stale queue while the backend logs nothing.
5. Any caching in `app.js`: a `Map` of fetched payloads, a `sessionStorage`/`localStorage` write of queue or detail data, `fetch(url, {cache: "force-cache"})`, or re-rendering a view from a previously fetched object instead of re-fetching.
6. A service worker. Not specified, not wanted, and it would cache the API responses on the Pages origin where nobody would think to look.
7. Prefetching the evidence drawer with the detail view (§3.8) — which both caches and breaks the friction gate.

The frontend rule that follows: **every hash-route navigation issues a fresh request.** Going back to the queue from a detail view re-fetches the queue. That is correct and intended; it is what makes a dispute visible.

### 7.3 The tests that catch it

Existing, unchanged, and they must keep passing:

| Test | Where | What it would catch |
|---|---|---|
| `TestLiveDatabaseNotFixtures::test_mutating_a_magnitude_changes_the_score` | `tests/test_scoring.py` | Any cache of scores or contributions — it mutates `signal_events.magnitude` via a raw `sqlite3` connection the app knows nothing about and asserts the score moved |
| `TestLiveDatabaseNotFixtures::test_deleting_events_removes_the_reason` | same | A cached reason list |
| `TestLiveDatabaseNotFixtures::test_changing_the_weight_table_changes_the_arithmetic` | same | A memoised `load_signal_types()` — it rewrites `signal_types.base_weight` externally and asserts the total drops by exactly 3.0 |
| `TestT07ExplanationIsTheModel` (both methods) | same | Reasons and score computed by different paths |
| T14 / T15 (dispute effect and revert, `tests/test_feedback.py`) | | A stale run being served after a dispute |
| T19 `test_every_python_file_imports_only_stdlib_or_local` | | A cache library sneaking in |

**Three new tests the maker must add**, because the existing suite cannot see the JSON layer:

- `test_api_queue_reflects_a_live_db_mutation` — build the API payload for a rep, mutate `signal_events` with a raw `sqlite3` connection, build it again, assert a `points` value moved. The same proof as the three above, applied to the serialiser.
- `test_api_response_headers_are_no_store` — assert `Cache-Control: no-store` on every `/api` response, and assert no `ETag` or `Last-Modified`.
- `test_api_reason_points_sum_to_score_points` — T07's assertion made against the JSON payload plus the withheld sum, so the invariant is asserted on the wire and not only in memory.

A fourth is worth having: `test_api_serialiser_contains_no_arithmetic` — an `ast` walk over `warrant/api.py` failing on any `BinOp` involving a name containing `points`, and on any call to `sorted`, `min` or `max`. It is in the same family as T19 and T20, which is to say: this codebase already prefers making a rule mechanically checkable over writing it down. Follow the local convention.

---

## 8. Config and secrets

### 8.1 The credential count is zero

`README.md`: *"There are no credentials anywhere in this repo, and no placeholder credentials either — Warrant talks to one local SQLite file and makes no outbound calls, so there is nothing to authenticate to."* `DESIGN_SPEC.md` §9.2 rule 4: *"No credentials, no API keys, no tokens in any file."*

**That remains true after this change, and it is worth stating why it is structurally true rather than merely currently true:**

- The database is a file on the same disk as the process, opened by path. SQLite has no authentication.
- Warrant makes no outbound calls. There is no upstream API to hold a key for.
- There is no login, no session, no cookie, no rep authentication. HOSTING_RESEARCH §1.7 notes Pages' policy that sites "shouldn't be used for sensitive transactions like sending passwords" — moot here, and a hard ceiling on ever adding rep auth to a Pages-fronted deployment.
- The CORS allowlist is a public configuration value, not a secret. Anyone can read `docs/config.js`; anyone can read the `Access-Control-Allow-Origin` header. Neither grants anything, because there is nothing to grant.

The two live URLs — the Pages site and the Render service — are public by construction. **The demo is unauthenticated and world-readable, and the runbook must say so in one plain sentence**, because "reachable by anyone on the internet" is the requirement and someone should have decided it rather than discovered it.

### 8.2 Every environment variable, and where it is set

| Variable | Set where | Value | Secret? |
|---|---|---|---|
| `PORT` | **Render, automatically** | injected by the platform | no |
| `WARRANT_BIND_HOST` | Render dashboard | `0.0.0.0` | no |
| `WARRANT_ALLOWED_ORIGINS` | Render dashboard | `https://<your-username>.github.io` | no |
| `WARRANT_PERSISTENCE` | Render dashboard | `ephemeral` | no |
| `WARRANT_DB_PATH` | *unset on Render*; set on a volume host | `/var/data/unify.db` | no |
| `WARRANT_PORT` | *unset* | falls through to `PORT` | no |
| `WARRANT_SEED` | *unset* | default `20260811` — leave it alone (§6.4) | no |
| `WARRANT_AS_OF` | *unset* | default `2026-08-11T09:00:00Z` — leave it alone | no |
| `WARRANT_RULESET_VERSION` | *unset* | default `warrant-v1.0.0` | no |
| `WARRANT_FORCE_RESEED` | *unset* | `1` only to deliberately wipe a persistent volume | no |

**Nothing in that table is a credential and nothing in it is set in a repo file.** `README.md` already records that nothing reads a `.env` file at runtime — `.env.example` is documentation of variable names, not a file the app parses. That stays true.

`.env.example` gains four lines, names and placeholder values only:

```
WARRANT_BIND_HOST=127.0.0.1
WARRANT_ALLOWED_ORIGINS=
WARRANT_PERSISTENCE=persistent
WARRANT_FORCE_RESEED=
```

Defaults chosen so that a developer copying `.env.example` locally gets the *safe* behaviour: bound to localhost, CORS closed, no restart notice, no reseed.

### 8.3 How the frontend learns the backend URL, without a key

Covered in §5.2. In one line: **`docs/config.js` holds one public URL string, edited by the user after they deploy the backend, read once by `app.js`, and containing nothing else.**

There is no token to exchange, no key to rotate, no secret to leak, and no build-time substitution step. The user edits one line in a text file in the GitHub web editor, commits, and Pages redeploys. That is the whole configuration ceremony, and it is deliberately something a non-expert can do in a browser (§6.1: *"The runbook is executable by a non-expert through a browser"*).

### 8.4 What must never appear in the repo

A one-line CI-less check the maker can add to the existing test suite, in the same spirit as T19 and T20: assert that no file in `docs/` contains any of `api_key`, `apikey`, `token`, `secret`, `password`, `Bearer `, or a string matching a long random-looking base64 run. It will always pass. It exists so that it *keeps* passing when someone later adds an integration.

---

## 9. Edge cases — what the rep actually sees

Specified as state + literal copy, because `DESIGN_SPEC.md` §8's own standard is *"edge cases are where this product dies"* and "show an error" is not a design.

Every state below renders **inside the normal page chrome** — the Warrant header and the persistence notice are present — so the rep is never looking at a bare white page.

### 9.1 Backend cold or asleep — the ~60-second Render wake

This is the common case, not the rare one. HOSTING_RESEARCH §5.2: *"Render spins down after 15 minutes of no traffic… most viewers of a circulated link hit a cold container, not a minority of them."*

**The static skeleton is the mitigation** (§5.3 item 3): *"This is the mitigation that costs nothing and is uniquely available because the frontend is on GitHub Pages… The user then sees 'waking the demo server, this takes about a minute on the free tier' instead of a blank tab."* This is also the specific reason frontend option C (iframe) was rejected — an iframe pointed at a sleeping backend produces a stalled frame with no place to put an explanation.

**Sequence:**

1. Pages serves `index.html` from a CDN with no cold start. **The header, the explanation of what Warrant is, and the loading state paint in milliseconds, before any request is made.**
2. `app.js` issues `GET /api/health` — the cheap endpoint (§3.4), never `/api/queue`, because polling ~1,900 SQL statements during a wake is absurd.
3. If `/api/health` has not resolved within **1.5 seconds**, swap the loading copy to the waking copy. Under 1.5s the container was already awake and the rep sees nothing unusual.
4. Poll `/api/health` every 3 seconds, up to **90 seconds** total.
5. On success, fetch the real view.

**Copy, verbatim:**

Immediately (0–1.5s):

> **Warrant** — reason-first prioritisation.
> Loading…

After 1.5s, replacing it:

> **Warrant** — reason-first prioritisation.
> **Waking the demo server. On free hosting this takes about a minute.**
> Warrant runs live SQL over a real database at the moment you load a page — there is no cache and no precomputed score. The server sleeps after 15 minutes of no traffic, so the first visit pays for starting it up. Nothing is wrong.
> *Waiting 23s…*

The counter ticks. The explanatory paragraph matters more than the spinner: HOSTING_RESEARCH §5.2's argument is that the damage is not the wait but that *"the first thing the system does is behave in a way the user cannot account for"*, on a page that is about to ask them to trust its legibility. The paragraph makes the wait accounted for. It also happens to be the product's own pitch, which is a fair use of sixty seconds.

After 90 seconds with no success, fall through to §9.2.

### 9.2 Backend down, or wake failed

State: `fetch` rejected, or `/api/health` never returned `ok`, after the full 90 seconds.

> **The demo server did not answer.**
> Warrant's frontend is hosted on GitHub Pages and loaded fine — this page is proof of that. The backend, which holds the database and does all the scoring, is not responding.
> The most likely causes, in order: the free-tier server is still starting (it can take longer than a minute under load); the free monthly instance-hour allowance has run out and the service is suspended until next month; or the backend has been shut down.
> Backend configured in `docs/config.js`: `https://<your-app>.onrender.com`
> **[ Try again ]**

`Try again` restarts the §9.1 sequence from step 2. The configured URL is echoed because the single most common failure is that it is wrong, and showing it lets the user diagnose without opening devtools. It is public, so echoing it leaks nothing.

Do not say "the server is down". It might be waking, suspended, or misconfigured, and asserting the wrong one teaches the reader that the system's statements about itself are unreliable — on a page whose subject is exactly that.

### 9.3 CORS misconfigured

This is the nastiest failure in the system and §1.5 names why: *"the response body arrives at the browser. The browser then refuses to hand it to the script. So the backend's own logs will show a clean 200, and the user will see an empty page. Anyone debugging this from the server side will conclude everything is fine."*

**Detection.** A CORS block surfaces in JS as a rejected `fetch` with `TypeError`, indistinguishable at the JS level from "server unreachable". So the frontend cannot tell them apart directly — and must not guess. What it *can* do is disambiguate with a second probe: issue the failing request again with `{mode: "no-cors"}`. A `no-cors` request returns an opaque response and does not throw if the server is reachable; it throws if it is not. **Reachable + opaque success + the real request threw ⇒ almost certainly CORS.** This is a heuristic, not a proof, and the copy must not overclaim.

> **The server answered, but the browser blocked the response.**
> This is almost always a CORS configuration problem, and it is fixable in about a minute.
> The backend has to be told which website is allowed to talk to it. Set the environment variable `WARRANT_ALLOWED_ORIGINS` on your backend host to exactly:
> `https://<your-username>.github.io`
> **Origin only — no path, no repo name, no trailing slash.** Then restart the service.
> This page's origin is: `https://<your-username>.github.io`  *(read from the browser, not hardcoded)*
> **[ Try again ]**

Showing the browser's own `window.location.origin` is the highest-value line in this document's error copy: it removes the guesswork about what exactly to paste, and it catches the single most likely mistake — pasting the full page URL including `/<repo>/`.

The runbook must additionally warn that a `200` in Render's logs is **not** evidence the frontend is working.

### 9.4 Empty results

Three distinct empty states, three distinct sentences. None of them is "no data".

**(a) A rep with no accounts in their patch.** Possible after mutes, or with a rep whose accounts are all inactive.

> **Nothing in your queue right now.**
> Every account assigned to you is either muted by you or inactive. Muted accounts return automatically when their window expires — see your adjustments.
> **[ view your adjustments ]**

Never *"you're all caught up"*. `DESIGN_SPEC.md` §8.3: *"a rep who cannot see their unscored accounts will assume Warrant is hiding work from them."*

**(b) An account with no signals.** Not a frontend state at all — the backend already handles it. `no_signals_line` carries `reasons.NO_SIGNALS_LINE`: *"We have no signals for this account. It is here because it is assigned to you, not because we think it is a priority."* and `limits_line` carries `"No signals found."` The frontend renders both. It must not substitute its own empty state, and it must still render the adjust and dispute controls, per §8.3.

**(c) Empty sub-blocks on the detail view.** `history` empty → `"Nothing yet."` (server-supplied). `research.items` empty → `research.empty_note`: *"No agent observations for this account yet."* `metrics` with a zero denominator → `display` is `"—"`, already handled by `metrics.format_rate()`. Per README limitation 5, per-signal-type show counts render `—` on a freshly seeded database until someone loads a queue — **which is now every restart**, so this state is common on the ephemeral deployment and the metrics view should carry `caveat_lines` prominently rather than at the bottom.

### 9.5 Backend URL not yet configured in `config.js`

State: `apiBase` missing, empty, or still containing the literal `<your-app>`. **No network request is made.**

> **Warrant is deployed here, but not connected to a backend yet.**
> GitHub Pages is serving this page correctly. It has no backend URL to talk to.
> To finish setup: deploy the backend, then edit `docs/config.js` in this repository and replace the placeholder with your backend's URL. It looks like `https://something.onrender.com` — no trailing slash. Commit the change and this page will pick it up within a minute.
> Nothing here is a secret. `config.js` holds one public URL and no keys.
> *Current value in `docs/config.js`:* `https://<your-app>.onrender.com`

The last line shows the unedited placeholder so the reader can see the thing they need to replace.

### 9.6 Backend up, database not seeded

State: `GET /api/health` returns `200` with `"seeded": false`. This means the process started but `seed_db.main()` did not run or did not complete — most likely a read-only or missing directory at `WARRANT_DB_PATH`.

> **The backend is running but has no data.**
> The server started, but the database was not created. The most likely cause is that `WARRANT_DB_PATH` points somewhere the process cannot write — check the deploy logs for the seeding summary; it should list 240 accounts and roughly 6,900 signal events.
> **[ Try again ]**

### 9.7 The account left the queue while the rep was looking at it

State: `GET /api/account/{id}` returns `404 NOT_IN_QUEUE`. Reachable by pasting an old link, by using the back button after a `NOT_A_FIT`, or by opening an account another rep owns.

> **Not in this queue right now.**
> This account is not in your queue at the moment. It may be muted by you, inactive, or owned by someone else. Muted accounts return automatically when the window expires.
> **[ back to your queue ]  [ view your adjustments ]**

The write path avoids reaching this state in the common case, because `next.view` is `queue` for mute-producing dispute codes (§3.13). This state exists for the link-pasting and back-button cases.

### 9.8 Ephemeral-restart data loss — what the visitor is told

Covered as a decision in §6.5. As a rep-facing state, three moments:

**Always present**, at the top of every view, from `meta.persistence_notice`:

> This demo server runs on free hosting with no persistent disk. It last restarted on 13 Aug 2026, 11:04 UTC. Anything a rep filed before then — disputes, pins, mutes — is gone. Everything you file now lasts until the next restart.

**At the moment of a write**, appended to `effect.confirmation`:

> You said "Repeat pricing-page visits" was wrong. Suppressed for this account until 9 Nov 2026, **or until this demo server restarts, whichever comes first.**

**When a restart is detected mid-session** (`meta.boot_id` changed):

> **The demo server restarted.**
> Anything you filed in this session — disputes, pins, mutes — is gone. The queue below has been rebuilt from the same seeded data, so the accounts and their evidence are exactly as they were.
> This is a limitation of the free hosting tier, not of Warrant. On a host with a persistent disk, everything you file survives.

That last sentence is the one that matters. It distinguishes a hosting constraint from a product behaviour, which is the difference between a rep concluding "the free tier forgets" and concluding "this system doesn't take my disagreement seriously". The second conclusion would be the failure `warrant/feedback.py` was written to prevent, arrived at by accident, through a deployment choice.

### 9.9 Budget exceeded, and the friction gate

Not new, but they now cross a network boundary and must survive it.

**409 `BUDGET_EXCEEDED`:** the frontend renders `error.title`, `error.message` and `error.action` verbatim. The message is `DESIGN_SPEC.md` §7.3's literal copy — *"You already have 5 pins. Pins expire on their own — your oldest expires on 18 Aug 2026 — or unpin one now."* The control is **not** disabled client-side to pre-empt this. §7.3 is explicit that refusing rather than silently absorbing is the point, and a greyed-out button the rep cannot interrogate is a worse version of the same idea.

**409 `EVIDENCE_REQUIRED`:** rendered the same way. Note that the disabled `Work it` button in the queue is a UI affordance and the 409 is the enforcement (README deviation 11) — both must be present. The frontend disabling the button is not sufficient and the frontend not disabling it is not sufficient either.

---

## 10. What I am explicitly not doing, and the open questions

### 10.1 Not doing

1. **Not migrating to Postgres, Turso, D1, Neon, Supabase or CockroachDB.** HOSTING_RESEARCH §6.5 recommends against it and §4.1 gives thirteen reasons. The most serious is #7: a `REAL` → `float4` precision change sitting directly under T07, the exact-equality test that carries the product's central claim.
2. **Not restructuring `scoring.py` to batch queries.** That would make Turso viable (§4.2) and it is a redesign of the module the explainability invariant lives in, not a deployment change.
3. **Not converting `app.py` to WSGI/ASGI.** That would open Vercel (§2.6) and PythonAnywhere (§2.9). It is real work on the one file that routes everything, and it is not needed for the chosen host.
4. **Not adding a keep-alive pinger.** §5.3 item 1: it consumes ~730 of 750 free instance-hours with a hard cliff, and Appendix A item 3 records that Render's terms position is unverified in both directions. Someone must read Render's ToS before this is reconsidered.
5. **Not adding authentication.** There is nothing to protect, and §1.7 notes Pages' policy against sensitive transactions makes it a dead end on this host anyway. The demo is public and the runbook must say so.
6. **Not adding a build step, a bundler, a framework, or a GitHub Actions workflow.** §1.2 option 2 needs none of them.
7. **Not adding a dependency.** Zero. `test_every_python_file_imports_only_stdlib_or_local` keeps passing unchanged. `start.py` imports `os`, `sys`, `seed_db`, `app`. If Render's Python runtime detection requires a `requirements.txt` to exist, commit one containing **only a comment** — `# Warrant has no third-party dependencies.` — which declares zero packages and leaves T19 untouched.
8. **Not changing any scoring behaviour, any weight, any threshold, any template, or any rendered sentence.** The port is a transport change. The twelve README deviations, including the Kestrel 61.24 vs 59.87 discrepancy, are carried forward exactly as they are and are not silently corrected here.
9. **Not writing the runbook.** That is stage 3 or 4. This document specifies what must be true; it does not walk the user through Render's signup screens.
10. **Not deploying anything.** Nobody in this pipeline can.

### 10.2 The disagreement I am recording

I was asked to record factual disagreements with the two given decisions rather than deviate silently. There is one, and it is minor.

**On decision 1, option A vs option C.** HOSTING_RESEARCH §1.6 is factually right that option C (iframe) reaches a genuine `github.io` URL with **zero** change to `app.py`, zero change to the explainability path, and — per the header code I read at §0.2, which confirms no `X-Frame-Options` and no CSP — it would in fact frame successfully today. Option A costs a new API layer, a new frontend, a CORS policy, an `OPTIONS` handler, and the loss of the no-JS guarantee on the Pages URL. That is a real cost delta and it is not small.

The reason the decision is nonetheless correct, and why I implement it without reservation: §5.3 item 3 identifies the static skeleton as *"the mitigation that costs nothing and is uniquely available because the frontend is on GitHub Pages"*, and it is available under option C **only with a visible wrapper around the iframe** — a wrapper that cannot know when the framed document has finished loading, cannot show a counter, and cannot fall back to §9.2's diagnostics, because the iframe's load state is opaque to the parent. Given §5.2's argument that the unexplained sixty seconds is a credibility cost and not merely a latency cost, and given that most viewers of a circulated link hit a cold container, the cold-start mitigation is worth more than the code saved. I record the trade-off because it is genuine and because a future reader should know it was weighed rather than assumed.

**Two smaller divergences from current behaviour**, both forced by the port and both improvements, flagged so they are not mistaken for drift:

- After a mute-producing dispute (`NOT_A_FIT`, `ALREADY_WORKING`, `NOT_MY_PATCH`), the HTML app redirects to the account detail view, which then renders "Not in this queue" — a confusing near-error at the moment the rep has just acted. The API returns `next.view: "queue"` plus `effect.confirmation`, so the rep gets the confirmation and the return date that §7.2 actually specifies. **Named as a divergence, not smuggled in.**
- `POST /adjust/revert` currently returns a `303` even when `revert_adjustment()` found nothing and wrote nothing (it returns `None` for an adjustment belonging to another rep). The API returns `404 NOT_FOUND` instead of a silent success.

### 10.3 Open questions for the maker

1. **Where exactly does `warrant/api.py` sit relative to `render.py`?** I have specified that both call the same `reasons.py` functions and that two strings must be extracted down out of `render.py` (§2.5). I have not specified whether `api.py` imports `render.py` for those helpers or whether they move to `reasons.py`. **My recommendation: move them to `reasons.py` and `queue.py` so `api.py` never imports `render.py`** — an API module that depends on an HTML module invites HTML into JSON. But it is a judgement call about module boundaries and the maker is closer to it.
2. **Does `/api/health` need its own connection lifecycle?** `app.py` opens and closes a connection per request in `do_GET`'s `try/finally`. Health is polled every 3 seconds during a wake, by potentially several viewers. My inference is that this is trivially fine given SQLite's in-process connection cost. Untested.
3. **Is 90 seconds the right wake timeout?** Render's own wording is "about one minute" [VERIFIED]; third-party reports say "20–60 seconds" [UNVERIFIED, §5.1]. 90s is a margin over the vendor's own figure. If real cold starts run longer under load, this number moves. It should be a named constant at the top of `app.js`, not scattered.
4. **Does the persistence notice belong on every view or only the first?** I have specified every view, because §6.5's whole argument is that quiet forgetting is the failure. A reasonable person could argue it becomes wallpaper after the third screen and should collapse to a one-line chip. **I would not collapse it, but I would test it if anyone ever tested anything with a rep** — and `STATUS_REPORT.md` §6 records that *"the trust claim itself is untested"*, so this joins a queue of untested copy decisions rather than standing out from it.
5. **Should the queue payload be paginated?** Rep 1's patch is 53 accounts and the payload is maybe 60–100 KB of JSON. Fine. A 500-account patch would not be. Not a v1 problem; naming it so it is not discovered later.

### 10.4 Open questions for the user

1. **$0 or ~$5/month?** HOSTING_RESEARCH §6.3 lists four conditions, any one of which flips the recommendation to a paid host with a persistent volume: the link will be emailed rather than driven live; anyone wants to see a dispute or `/metrics` more than a few hours after filing; the audience is external; or $5/month is not a real constraint. This design ships on free and makes the switch four dashboard values (§6.6). **The user decides, and the honest framing is that free costs the rep's disputes and a minute of every visitor's time.**
2. **Is the demo being public acceptable?** It will be unauthenticated and world-readable, on both URLs (§8.1). The data is synthetic — 240 generated accounts, synthetic `.test` domains, synthetic LinkedIn paths — so there is nothing sensitive in it. But it should be a decision.
3. **Is GitHub Pages' usage policy satisfied?** §1.7 [VERIFIED] records that Pages "is not intended for or allowed to be used as a free web-hosting service to run your online business… or providing commercial software as a service". The researcher's inference is that an internal prototype shown to colleagues is not "primarily directed at facilitating commercial transactions". That is an inference about a policy, made by neither a lawyer nor the account holder. **If Warrant becomes a customer-facing surface, Pages is the wrong host and this clause is the reason.**
4. **Does the user's Render workspace have anything else consuming free instance-hours?** The 750-hour allowance is per workspace and exceeding it suspends *all* free services until the next month (§2.1). A second free service in the same workspace changes the arithmetic.

---

*Designer agent (AI-generated). Stage 2 of 4. Nothing in this document has been deployed, tested, or verified in production. Every URL is a placeholder. Every claim about a hosting provider is inherited from `HOSTING_RESEARCH.md` with its verification label intact; every claim about Warrant's own source is drawn from files read during this session and cited by file and line.*
