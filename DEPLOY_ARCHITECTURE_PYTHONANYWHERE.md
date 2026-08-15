# DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md — a second, card-free deploy path

**Stage:** addendum to stage 2/3 (design + build, combined)
**Author:** Maker agent, AI-generated
**Relationship to the existing documents:** additive. `DEPLOY_ARCHITECTURE.md`,
`DEPLOY_RUNBOOK.md` and `DEPLOY_TEST_OUTPUT.md` describe the Render path and are
**untouched** by this document. Nothing here retires Render as an option — the
user hit a live card-on-file requirement in Render's signup flow that
contradicts Render's own free-tier documentation, and wants a second path that
does not require a card at all. This document, `DEPLOY_RUNBOOK_PYTHONANYWHERE.md`
and `DEPLOY_TEST_OUTPUT_PYTHONANYWHERE.md` are that second path, sitting
alongside the first.
**Input:** `HOSTING_RESEARCH.md` §2.9, §2.11, §6.4; `DEPLOY_ARCHITECTURE.md`
(matched for rigor, not copied); `app.py`, `warrant/db.py`, `start.py`;
primary-source fetches against `help.pythonanywhere.com`, listed in §7.

---

## 0. Status, and what changed between the research and today

`HOSTING_RESEARCH.md` §2.9 recorded PythonAnywhere's free tier as **"viable
with rework"** and named three costs: the WSGI requirement, a 100
CPU-second/day budget, and a contradictory expiry policy (1 month vs 3
months). Before relying on any of that, I re-fetched PythonAnywhere's own
pages directly (2026-08-15, listed in §7) rather than trust it unchecked, per
the brief. Two things came back different from what the research assumed, and
both are corrections, stated plainly rather than folded in silently:

1. **The 1-month expiry wording still stands as of today's fetch** —
   [VERIFIED, re-confirmed]. `help.pythonanywhere.com/pages/FreeAccountsFeatures/`
   still reads, verbatim: *"1 web app with 1 web worker and 1 month expiry."*
   The 3-month renewal cycle HOSTING_RESEARCH flagged as a contradiction from
   an [UNVERIFIED] forum/blog summary could not be corroborated by any
   primary PythonAnywhere page in this fetch pass either. **The contradiction
   is not resolved — it is narrowed.** What is now [VERIFIED] rather than
   [UNVERIFIED] is that the *current, live* help page says 1 month. Treat 1
   month as the number to plan around; treat a possible 3-month renewal
   button as a pleasant surprise if the Web tab shows one, not as the plan.
2. **The 100 CPU-second/day budget does NOT apply to web apps.** [VERIFIED,
   new fetch] `help.pythonanywhere.com/pages/WhatAreCPUSeconds/`, verbatim:
   *"With every PythonAnywhere account, you get a number of CPU-seconds
   included each day. This applies to all code run through our in-browser
   consoles and in your scheduled tasks. **It does not currently apply to
   your web apps.**"* HOSTING_RESEARCH §2.9 and §6.4's "~475 renders/day"
   figure was an **inference** built on the assumption that the CPU-second
   budget throttles web requests — the research labelled it `[INFERENCE]`
   for exactly this reason, and the inference turns out to be wrong. **This
   is corrected here, not silently followed.** §5 below replaces it with the
   real constraint, which is a concurrency limit, not a CPU-time budget.

Everything else nothing in this fetch pass contradicted: free tier, no card,
512 MiB persistent disk, 1 web worker, WSGI-only. HOSTING_RESEARCH's core
recommendation — SQLite in-process, zero dependencies, the same architecture
as Render but WSGI-shaped — still holds and is what this document specifies.

**Nothing here has been deployed.** No PythonAnywhere account exists in this
pipeline. Every claim below is either [VERIFIED] against a page fetched on
2026-08-15 (§7 has the full list), [TESTED LOCALLY] against a real
`wsgiref.simple_server` (not PythonAnywhere itself), or [INFERENCE] from the
two combined. §8 states the one claim that is neither — the load-bearing
unverified assumption of this whole path.

---

## 1. Why a second file, not a rewrite of the Render one

`DEPLOY_ARCHITECTURE.md` §1.1's stack table is Render-specific from the first
row (`ThreadingHTTPServer`, `0.0.0.0:$PORT`, ephemeral disk). Rewriting it in
place to also describe a WSGI process on a persistent disk would either read
as two architectures welded into one document, or force a rewrite of the
Render document the user did not ask for and this task explicitly forbids
("leave the existing Render path and its documents completely untouched").
A second, parallel document, matched for rigor, is the honest shape for "a
second option," not a patch to the first.

---

## 2. The one hard constraint, and the design decision it forces

**PythonAnywhere's free tier serves WSGI applications through its own
nginx/uwsgi stack. `app.py`'s `Handler` is a raw
`http.server.BaseHTTPRequestHandler` bound to a socket via
`ThreadingHTTPServer.serve_forever()` — the opposite shape.** [VERIFIED —
`help.pythonanywhere.com/pages/WebAppBasics/`: web apps are created by
generating a WSGI file from a template, and PythonAnywhere's worker process
calls that file's `application` object, not an arbitrary long-running script.]

Two ways to satisfy this were considered and rejected before the one that
shipped:

- **Reimplement every route as a second, WSGI-shaped copy.** Rejected
  outright. `warrant/scoring.py`'s own docstring states Warrant's central
  guarantee: *"there is exactly one code path… it is not possible to produce
  a reason that did not contribute points, or a point that produced no
  reason."* A second copy of the routing layer is not a second copy of
  scoring, but it is exactly the "two code paths that happen to agree today"
  failure `DEPLOY_ARCHITECTURE.md` §2.3 names for the JavaScript case — the
  same species of risk, one layer down. If the two dispatch tables drifted
  (a route added to one and not the other, a field renamed in one and not
  the other), nothing would catch it until a rep on one platform saw
  something different from a rep on the other.
- **Extract the routing/business logic into a transport-agnostic mixin, and
  give each transport its own thin socket/WSGI plumbing.** This is what
  shipped. See §3.

## 3. The split: `WarrantRoutes`

`app.py`'s `Handler` class used to mix two concerns: **which URL means which
query, which form field means which write** (the actual product logic), and
**how bytes get on and off a socket** (`self.rfile`, `self.wfile`,
`self.send_response()`). Only the second concern is genuinely
transport-specific.

`app.py` now defines:

- **`WarrantRoutes`** — a mixin with **no socket dependency whatsoever**.
  Every route method that existed before — `_index`, `_queue`, `_detail`,
  `_evidence`, `_api_queue`, `_api_dispute`, all of them, including the new
  `_route_get`/`_route_post` dispatch tables extracted from the old
  `do_GET`/`do_POST` bodies — lives here, **moved, not rewritten**. Each one
  depends on exactly four methods being supplied by whatever it is mixed
  into: `self._send(status, html, content_type=...)`,
  `self._send_json(status, payload)`, `self._redirect(location)`, and
  `self._json_error(status, payload)`.
- **`Handler(BaseHTTPRequestHandler, WarrantRoutes)`** — unchanged in
  behaviour from before this work. It supplies the four methods above in
  socket-backed form (`self.send_response()` / `self.send_header()` /
  `self.wfile.write()`), plus `do_GET`/`do_POST`/`do_OPTIONS`/`_form`/
  `log_message`, which are the genuinely socket-specific parts.
- **`wsgi.py`, a new module at the repo root** — `WSGIRequest(WarrantRoutes)`
  supplies the same four methods in WSGI-shaped form: instead of writing to a
  socket mid-call, each one records `(status, headers, body)` on `self`,
  and the module-level `application(environ, start_response)` callable reads
  that back after dispatch and hands it to `start_response()`. `wsgi.py`
  imports `WarrantRoutes` from `app` — it does not redefine a single route.

**What this buys, concretely:** a route added to `WarrantRoutes` reaches both
entry points automatically. A bug fixed in `_api_dispute` is fixed on both
platforms in one edit. There is exactly one dispatch table for GET and one
for POST (`_route_get`/`_route_post`), imported by `wsgi.py`, not duplicated.
`tests/test_wsgi.py::TestScoringParityAcrossTransports` proves this is true
on the wire, not just true by inspection — see `DEPLOY_TEST_OUTPUT_PYTHONANYWHERE.md`
§3.

**What this does not change:** `python app.py` behaves identically to before
this work — same routes, same responses, same CORS decisions, same bytes.
The full existing test suite (`tests/test_api.py`, written against
`app.Handler`) passes unmodified against the reorganised class. This is
internal structure, not a behaviour change, and the Render path is
unaffected by it.

## 4. CORS at the WSGI layer — one decision, two transports

`DEPLOY_ARCHITECTURE.md` §4 specifies CORS precisely for the socket path.
Rather than re-derive or re-describe the policy for WSGI, the **decision
itself** was extracted into two plain functions in `app.py`:

```python
def cors_header_lines(origin) -> list[(name, value)]     # §4.6's per-response rule
def preflight_header_lines(origin) -> list[(name, value)]  # §4.4's exact preflight
```

Both `Handler._cors_headers`/`Handler.do_OPTIONS` (socket) and
`wsgi.py`'s `WSGIRequest._send_json`/`_do_options` (WSGI) call these same two
functions and only differ in *how* they emit the resulting header list —
`send_header()` in a loop versus building the list `start_response()` wants.
The origin-allowlist check itself was already a plain function
(`warrant.db.origin_allowed`), unmodified. **A preflight answered by
`app.py`'s `Handler` and a preflight answered by `wsgi.py`'s `application`
are the same decision, computed once** — not two implementations that
happen to agree today. `tests/test_wsgi.py::TestWsgiCors` mirrors
`tests/test_api.py::TestCors` test-for-test, plus one test
(`test_cors_decision_matches_the_socket_path_for_the_same_configuration`)
that runs both transports side by side against the same allowlist and
asserts the header presence and values are identical.

`WARRANT_ALLOWED_ORIGINS` itself is unchanged — same env var, same exact-match
semantics, same fail-closed default. Nothing about the CORS *policy* differs
between the two hosts; only which process answers the preflight differs.

## 5. What actually throttles a free PythonAnywhere web app

§0 corrected the research's CPU-second inference. Restated precisely:

| Mechanism | Applies to PythonAnywhere web apps? | Source |
|---|---|---|
| 100 CPU-seconds/day | **No** [VERIFIED] | `WhatAreCPUSeconds`: *"It does not currently apply to your web apps."* |
| 1 web worker (free tier) | **Yes** [VERIFIED] | `FreeAccountsFeatures`: *"1 web app with 1 web worker."* |
| Request queue when the worker is busy | **Yes** [VERIFIED] | `HowManyHitsCanMySiteHandle`: *"Free accounts have one worker process handling their requests… if your code takes 0.2 seconds to handle a typical request, then one worker can handle 5 requests/second."* |

**The real constraint is concurrency, not CPU-time.** A free web app has
exactly one worker process — every request is served strictly one at a time;
a second visitor's request queues behind the first until it finishes, and if
the queue backs up for a sustained period the symptom is a slow site and
eventually a `502-backend` from PythonAnywhere's own queue filling up
[VERIFIED, same page]. There is no daily cutoff analogous to Render's 750
instance-hours; a request either gets served (eventually) or the queue
overflows under sustained concurrent load.

**Applying PythonAnywhere's own formula to Warrant's measured numbers:**
`STATUS_REPORT.md` §6 records a full queue render at **~0.21s**. Using
PythonAnywhere's stated model (`1 worker ÷ per-request time = requests/second`):

```
1 worker ÷ 0.21s per queue render  ≈  4.8 queue renders/second, sustained
```

For a controlled demo — one or a handful of people clicking a link, not a
concurrent flash of traffic — this is generous: nothing in this product's
audience looks like sustained multi-request-per-second load. **It is a
different shape of risk than Render's, and it should be disclosed as such,
not engineered around:** a demo link that gets **simultaneous** clicks from
several people at once will serialise them behind the single worker rather
than throttle by a daily budget. The failure mode is "the second visitor
waits a fraction of a second longer," not "the service goes dark for the
rest of the day" — meaningfully milder than what the research's incorrect
inference implied, and the runbook states this plainly (§6.1 of
`DEPLOY_RUNBOOK_PYTHONANYWHERE.md`).

**Named limitation, honestly:** none of the above was measured against a
real PythonAnywhere worker — only against `STATUS_REPORT.md`'s existing
local timing and PythonAnywhere's own documented formula. See §8.

## 6. Persistence: the disk is genuinely better here, and the risk is different

`DEPLOY_ARCHITECTURE.md` §6.5 ships Render on ephemeral storage and
disclosed that as a real cost. PythonAnywhere's disk is **persistent** —
512 MiB [VERIFIED, HOSTING_RESEARCH §2.9] — and nothing about Warrant's code
needs to change to use that fact. `warrant/db.py::db_path()` already honours
an absolute `WARRANT_DB_PATH` verbatim (this was true before this work, and
is the same mechanism `DEPLOY_ARCHITECTURE.md` §6.6 already names as "the
upgrade path" for Render). `start.py`'s conditional seed
(`seed_if_needed()`) is unchanged and does exactly what's needed here: seed
once on first boot, skip on every subsequent one, so a rep's disputes,
pins and mutes **survive a restart** — the one thing Render's ephemeral
disk cannot do.

**Decision: `WARRANT_PERSISTENCE=persistent`** on this path, not `ephemeral`
as on Render. Concretely, this means:

- `meta.persistence_notice` is `null` on every response — no "this demo
  server has no persistent disk" banner, because it would be false here.
- A dispute's confirmation does **not** carry the `", or until this demo
  server restarts, whichever comes first"` clause (`warrant/runtime.py::
  EPHEMERAL_CLAUSE`) — because it doesn't restart the data away.
- No code change was needed for any of this: `warrant/db.py::persistence()`,
  `warrant/runtime.py`'s notices, and `warrant/api.py::meta()` already
  branch on `WARRANT_PERSISTENCE` exactly this way for the Render path.
  Setting the one env var to a different value is the entire mechanism —
  matching `DEPLOY_ARCHITECTURE.md` §6.6's own description of this as "four
  dashboard values and nothing else."

**Genuinely tested, not just claimed:** `DEPLOY_TEST_OUTPUT_PYTHONANYWHERE.md`
§5 files a dispute against a real running `wsgi.application` process, kills
that process, starts a **new** process against the same `WARRANT_DB_PATH`
(a fresh `boot_id`, proving it is genuinely a different process, not the
same one still running), and shows the dispute — the suppressed reason, the
adjusted points, the history entry — is still there. This is the positive
side of this path that the Render path structurally cannot offer.

**The risk that replaces ephemeral-restart-loses-data:** the free web app
**itself expires** and needs a human to click a renewal control on the Web
tab. §0 restates what is and is not settled about the interval (1 month,
[VERIFIED] as of this fetch; a 3-month cycle remains [UNVERIFIED]). If
nobody renews it, **the entire site goes fully offline** — not a sleep/wake
cycle a visitor rides out with a 60-second wait (Render's failure mode,
`DEPLOY_ARCHITECTURE.md` §9.1), but a dead URL until someone with the
account logs in and clicks renew. This is arguably a **worse** failure mode
for an unattended demo than Render's, precisely because the upside
(persistence) and the downside (silent full outage on expiry) are two sides
of the same fact: nothing about this host auto-regenerates the demo the way
Render's from-scratch reseed does. `DEPLOY_RUNBOOK_PYTHONANYWHERE.md` §6.2
states this as plainly as `DEPLOY_RUNBOOK.md` §0.3 states Render's cold-start
cost, with a calendar reminder the user is told to set.

## 7. Environment variables: no dashboard field, no `python-dotenv`

The one new primary-source fact driving the mechanism, fetched directly from
`https://help.pythonanywhere.com/pages/EnvironmentVariables/` on 2026-08-15
[VERIFIED]:

> *"Click over to the Web tab for your web app, and click on the link to
> your WSGI file. In here, you can set your environment variable using
> Python code; this needs to go before the code that actually loads your
> website."*

PythonAnywhere's own page then recommends installing the third-party package
`python-dotenv` and loading a `.env` file, so the same lines don't have to be
typed twice (once for the WSGI file, once for a Bash console's
`postactivate` script).

**That recommendation is not followed here, for two independent reasons,
either of which alone would be sufficient:**

1. **`tests/test_queue.py::TestT19StandardLibraryOnly`** AST-walks every
   `.py` file in this repo (now including `wsgi.py`, extended in §... below)
   and fails on any non-stdlib import. `python-dotenv` would break that test
   the moment it appeared in any file it touches, and Warrant's whole
   "stdlib only, zero dependencies" property (`requirements.txt` declares
   zero packages) would no longer be true.
2. **There is nothing to keep secret.** `README.md`: *"There are no
   credentials anywhere in this repo… Warrant talks to one local SQLite file
   and makes no outbound calls."* `python-dotenv` exists to keep a secret
   out of source control while still being available at runtime. Warrant has
   no secret for it to protect — every `WARRANT_*` variable in
   `DEPLOY_ARCHITECTURE.md` §8.2's table is already marked "no" in the
   Secret column, unchanged for this path (§9 below). The whole reason the
   PythonAnywhere docs reach for `.env` + `python-dotenv` — avoiding a
   secret embedded directly in a file two different tools both read — does
   not apply.

**What is used instead: plain `os.environ.setdefault("WARRANT_...", "...")`
calls, written as literal Python lines directly in the WSGI configuration
file**, the same file PythonAnywhere's own docs already say is where
environment-setting code goes for a web app. This is **simpler** than
Render's mechanism (a dashboard form with one row per variable), not harder,
once the dotenv step is dropped: there is one file, edited once, in a
browser text editor PythonAnywhere already provides. The exact lines the
user pastes are in `DEPLOY_RUNBOOK_PYTHONANYWHERE.md` §5.

**One more consequence of this same fact, and it's a good one:** because the
WSGI configuration file is plain Python, executed once per worker
(re)start, it is also the natural place to call `start.seed_if_needed()` —
**reusing `start.py` exactly as written**, no new seeding code, no
PythonAnywhere-specific seeding path. See `DEPLOY_RUNBOOK_PYTHONANYWHERE.md`
§5 for the literal file contents.

## 8. Python version: a real constraint, found by primary-source fetch

`DEPLOY_ARCHITECTURE.md` §1.3 flagged, for Render: *"That Render offers a
Python runtime at 3.14.x… not covered by the research at all… my inference
is that it runs on 3.11–3.13 unchanged."* That inference is directly load-
bearing here, because PythonAnywhere's own supported-versions page changes
the answer:

**[VERIFIED]** `https://help.pythonanywhere.com/pages/PythonVersions/`
(fetched 2026-08-15): the newest system image ("innit") supports Python
**up to 3.13**. **Python 3.14 is not offered on any PythonAnywhere system
image as of this fetch.** `.python-version` (`3.14.3`, added for the Render
path) has no PythonAnywhere equivalent and is not read by anything on this
path.

Carrying `DEPLOY_ARCHITECTURE.md` §1.3's own inference forward: nothing in
`warrant/` or `app.py` was found to require a 3.14-specific language
feature (`dataclasses`, `%`-formatting, `math.log10`, `json`, `sqlite3`,
`http.server` — all long-stable). **This inference has still only been
tested on 3.14.3** — this machine has no Python 3.13 installed, and none
was installed to test this, so the claim "3.13 behaves identically" is
carried forward from the Render document, not independently re-verified
here. **The one part of that claim with a real, named risk attached**
(`DEPLOY_ARCHITECTURE.md` §6.4 step 3, restated for this path): the fixed-
seed corpus depends on Python's `random` module producing an identical
stream. A materially different Python **could** produce a different
corpus. This was not tested across 3.14.3 → 3.13 locally, for the reason
above. **Decision:** create the PythonAnywhere virtualenv/web app against
**3.13** (the newest available), and the runbook's verification step
(`DEPLOY_RUNBOOK_PYTHONANYWHERE.md` §7) checks the exact same numbers —
240 accounts, 53 in rep 1's queue, the same top few `points_display`
values — that `DEPLOY_ARCHITECTURE.md` §6.4 already specifies checking on
Render, for the same reason.

**Zero dependencies means a virtualenv is optional, not required.**
`requirements.txt` declares no packages; there is nothing to `pip install`.
PythonAnywhere's own docs (`VirtualenvsExplained`) say plainly: *"You don't
need to use virtualenvs to run your code on PythonAnywhere — indeed, when
you're getting started, it's best not to."* The runbook therefore skips
virtualenv creation entirely and pins the Python version at the point
PythonAnywhere's "Manual configuration" web-app wizard asks for it.

## 9. Every environment variable on this path

Extends `DEPLOY_ARCHITECTURE.md` §8.2's table with what changes. Nothing new
is a secret; the credential count is still zero (§8.1 of that document
holds unmodified — SQLite has no authentication, Warrant makes no outbound
calls, there is no login).

| Variable | Set where | Value on this path | Differs from Render? |
|---|---|---|---|
| `WARRANT_ALLOWED_ORIGINS` | WSGI config file, `os.environ.setdefault` | `https://<your-username>.github.io` | Same mechanism, different file |
| `WARRANT_PERSISTENCE` | WSGI config file | `persistent` | **Yes** — `ephemeral` on Render (§6) |
| `WARRANT_DB_PATH` | WSGI config file | `/home/<username>/warrant/data/unify.db` | **Yes** — unset on Render; here it must point at the persistent disk explicitly |
| `WARRANT_BIND_HOST` | *not applicable* | *unused* | WSGI has no socket to bind — PythonAnywhere's own server owns the port. Harmless to set; nothing reads it in the WSGI path. |
| `PORT` / `WARRANT_PORT` | *not applicable* | *unused* | Same reason |
| `WARRANT_FORCE_RESEED` | WSGI config file | unset, or `1` only to deliberately wipe the persistent disk | Same destructive meaning as Render (`DEPLOY_ARCHITECTURE.md` §8.2) |
| `WARRANT_SEED`, `WARRANT_AS_OF`, `WARRANT_RULESET_VERSION` | unset | defaults | Unchanged — leave alone, same reasoning as Render |

## 10. What was verified locally, what rests on documentation, and the one
    thing that is neither

**Verified locally, against a real `wsgiref.simple_server` (stdlib), not
PythonAnywhere itself** — see `DEPLOY_TEST_OUTPUT_PYTHONANYWHERE.md` for the
full transcript:

- `wsgi.application` answers `GET`/`POST`/`OPTIONS` correctly, over a real
  socket, from a separate client process (`curl`).
- CORS and preflight behave identically to the socket path, including the
  fail-closed default and the exact-match origin check.
- The write loop (dispute → score moves → revert → score restored) works
  end to end over the WSGI entry point.
- **The persistence claim itself**, end to end: dispute filed, process
  killed, a genuinely new process started against the same
  `WARRANT_DB_PATH`, dispute still there.
- Scoring parity across the two transports, on the wire, for the seeded
  corpus and for the §4.4 Kestrel worked example.
- The full existing test suite (`tests/test_api.py`, `tests/test_queue.py`,
  etc.) still passes after the `WarrantRoutes` refactor, unchanged in count
  except for the tests this work added.

**Rests on PythonAnywhere's own documentation, fetched directly on
2026-08-15, not independently reproduced:**

- That the free tier requires no card at signup (`pricing/`,
  `FreeAccountsFeatures`).
- The exact wording of the 1-month web-app expiry, and that CPU-seconds do
  not apply to web apps (§0).
- The mechanics of setting environment variables via the WSGI config file
  (§7), the "Manual configuration" web-app wizard existing at all
  (`WebAppBasics`), and `mkvirtualenv --python=python3.13` as the version-
  pinning command if a virtualenv is used (`VirtualenvsExplained`).
- That free accounts can reach `github.com` over HTTPS to clone a public
  repository (`ExternalVCS`).

**Neither verified nor merely documented — the load-bearing unverified
assumption of this entire path, named the way `DEPLOY_ARCHITECTURE.md` §1.3
named "does Render run a raw `ThreadingHTTPServer`" for the Render path:**

> **Nobody in this pipeline has a PythonAnywhere account.** Everything about
> the WSGI-file-editing mechanism, the "Manual configuration" wizard, the
> environment-variable-via-Python-code pattern, and whether any of it works
> identically — or at all — on a **free** account specifically (as opposed
> to a paid one, which is what most of PythonAnywhere's own screenshots and
> forum answers appear to describe) **was not confirmed by any fetch in this
> pipeline.** The pages fetched describe PythonAnywhere's web-app system in
> general; none of them said "and this works the same on the free tier." The
> free tier is documented to have the *same* one-worker WSGI model as every
> other tier (`FreeAccountsFeatures` lists "1 web app," not a different
> mechanism) — so there is no documented reason to expect a difference — but
> "no documented reason to expect a difference" is an inference, not a
> confirmation, and it is the first thing `DEPLOY_RUNBOOK_PYTHONANYWHERE.md`
> asks the user to check before doing anything else.

---

## 11. What changed in the repo, file by file

| File | Change |
|---|---|
| `app.py` | Additive refactor: `Handler`'s route/business methods extracted into a new mixin class `WarrantRoutes`; two new module-level functions `cors_header_lines()`/`preflight_header_lines()`. Behaviour unchanged — see §3. |
| `wsgi.py` | **New.** The WSGI entry point. See §3, §7. |
| `tests/test_queue.py` | `wsgi.py` added to `python_files()` (T19's scanned set) and `"wsgi"` added to `LOCAL_MODULES` (T19's local-import allowlist) — the same treatment `start.py` already got for the Render path. |
| `tests/test_wsgi.py` | **New.** Mirrors `tests/test_api.py`'s real-socket verification bar, fronted by `wsgiref.simple_server` instead of `ThreadingHTTPServer`. See §10 and `DEPLOY_TEST_OUTPUT_PYTHONANYWHERE.md` §3. |
| `DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md` | **New.** This document. |
| `DEPLOY_RUNBOOK_PYTHONANYWHERE.md` | **New.** |
| `DEPLOY_TEST_OUTPUT_PYTHONANYWHERE.md` | **New.** |

**Untouched:** `app.py`'s routes, `warrant/api.py`, `warrant/scoring.py`,
`warrant/reasons.py`, `warrant/render.py`, `warrant/queue.py`,
`warrant/feedback.py`, `warrant/db.py`, `start.py`, `docs/`,
`DEPLOY_ARCHITECTURE.md`, `DEPLOY_RUNBOOK.md`, `DEPLOY_TEST_OUTPUT.md`.

---

*Maker agent, AI-generated. Nothing in this document has been
deployed. Every claim is labelled [VERIFIED] (fetched from PythonAnywhere's
own pages on 2026-08-15), [TESTED LOCALLY] (a real `wsgiref` server on this
machine, not PythonAnywhere), or [INFERENCE]. §10's last item is the one
claim that is none of these, and it is the first thing to check.*
