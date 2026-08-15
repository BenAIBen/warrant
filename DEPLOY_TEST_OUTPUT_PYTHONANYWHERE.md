# DEPLOY_TEST_OUTPUT_PYTHONANYWHERE.md — what was actually run, and what actually happened

**Companion to:** `DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md` (the design),
`DEPLOY_RUNBOOK_PYTHONANYWHERE.md` (the steps)
**Machine:** Windows 11, Python 3.14.3 at
`C:\Users\DELL Lattitude\AppData\Local\Python\pythoncore-3.14-64\python.exe`
**Date:** 15 August 2026

---

## 0. Scope, stated before any output

Everything in this document was run for real, on this machine, against a
real seeded SQLite database and, where stated, a real `wsgiref.simple_server`
process on a real local port hit with real `curl`/`urlopen` requests over a
real socket. **Nothing was run against an actual PythonAnywhere account** —
none exists in this pipeline. Section 5 is the closest approximation
available: a manual harness that sets environment variables and calls
`start.seed_if_needed()` exactly the way PythonAnywhere's WSGI config file is
instructed to (`DEPLOY_RUNBOOK_PYTHONANYWHERE.md` §6 step 7), then serves
`wsgi.application` with the same stdlib `wsgiref` server the automated tests
use — not PythonAnywhere's own nginx/uwsgi stack, which this pipeline cannot
reach. Section 6 states precisely what that gap means.

---

## 1. Baseline, before touching anything

The existing suite was run first, unmodified, to establish ground truth
before any PythonAnywhere-path code was written.

```
$ python -m unittest discover tests -v 2>&1 | tail -20
...
======================================================================
FAIL: test_no_credential_with_a_value_in_prose_or_documentation (test_queue.TestNoSecrets.test_no_credential_with_a_value_in_prose_or_documentation)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "...\tests\test_queue.py", line 418, in test_no_credential_with_a_value_in_prose_or_documentation
    self.assertEqual(offenders, [],
AssertionError: Lists differ: [('DEPLOY_TEST_OUTPUT.md', '<redacted — see note below>')] != []

----------------------------------------------------------------------
Ran 146 tests in 48.420s

FAILED (failures=1)
```

(The matched string is redacted in this paste, deliberately — reproducing it
verbatim here would make this document match the same scanner it is
describing, for the same reason given two sentences below, and would turn an
honest report of a pre-existing failure into a second, new one. Nothing
about the underlying transcript is altered; only that one already-known
trigger string is not repeated a second time.)

**This failure is pre-existing and unrelated to this work.** It fires on
`DEPLOY_TEST_OUTPUT.md` line 229, which contains a synthetic, AWS-access-key-
shaped example string — an `aws_access_key_id=` name immediately followed by
a value — used there as that document's own negative-control example,
illustrating what the credential scanner is supposed to catch, quoted
verbatim in its own prose. `DEPLOY_TEST_OUTPUT.md` is a Render-path document
this task requires leaving **completely untouched**, so this failure is
carried forward, named honestly, and not fixed here.

**Baseline: 146 tests, 145 passed, 1 pre-existing failure.** The brief that
opened this work assumed a clean 146/146; that assumption was wrong before a
single line of this work was written, and is corrected here rather than
carried forward silently.

---

## 2. The `app.py` → `WarrantRoutes` refactor, checked for regressions

After extracting `WarrantRoutes` out of `Handler` (`app.py`) — moving every
route method, changing nothing about what any of them do — the full suite
was run again, **before** any new WSGI-specific code or tests existed, to
confirm the refactor alone introduced zero behavioural change:

```
$ python -m unittest discover tests -v 2>&1 | tail -30
...
Ran 146 tests in 47.732s

FAILED (failures=1)
```

Same count, same single pre-existing failure, same test name. The refactor
is behaviour-preserving — every test written against `app.Handler`'s
routes, CORS handling, and write loop passed exactly as before, because
`Handler` still has every method it had, reached through inheritance instead
of directly.

A targeted check of just the AST-based stdlib-only test, after adding
`wsgi.py` to its scanned file list (`tests/test_queue.py::python_files()`)
and `"wsgi"` to its local-module allowlist:

```
$ python -m unittest discover tests -p "test_queue.py" 2>&1 | tail -6
...
----------------------------------------------------------------------
Ran 23 tests in 10.011s

FAILED (failures=1)
```

Same pre-existing failure only — `wsgi.py` passed the stdlib-only scan on
its first run, because it imports only `sys`, `http.HTTPStatus`,
`urllib.parse.parse_qs`, `app`, and `warrant.db` — all stdlib or local.

---

## 3. `tests/test_wsgi.py` — written, run, and one real bug caught by running it

Nineteen new tests were added, mirroring `tests/test_api.py`'s real-socket
verification bar but fronted by `wsgiref.simple_server` (stdlib) instead of
`ThreadingHTTPServer` directly — a genuine second WSGI server process, not an
in-process call to `wsgi.application()`.

### 3.1 First run — 2 failures, and neither was in `wsgi.py`

```
$ python -m unittest discover tests -p "test_wsgi.py" -v 2>&1 | tail -40
...
FAIL: test_detail_payload_is_byte_identical_across_transports_for_several_accounts
AssertionError: {'acc[812 chars]d': 355, 'signal_type_id': 7, ...} != {'acc[812 chars]d': 3187, 'signal_type_id': 7, ...}
Diff is 16082 characters long.

FAIL: test_queue_payload_is_byte_identical_across_transports
AssertionError: {'rep[74 chars]d': 18, 'header_line': ...} != {'rep[74 chars]d': 19, 'header_line': ...}
Diff is 38508 characters long.

----------------------------------------------------------------------
Ran 19 tests in 15.806s

FAILED (failures=2)
```

### 3.2 Diagnosing it before fixing it

`'d': 18` versus `'d': 19` in the truncated diff is `run_id`. `'d': 355`
versus `'d': 3187` is a `reason_id` embedded in `fields.reason` inside a
dispute action. **Neither of these is a bug in `wsgi.py` or in
`WarrantRoutes`.** `build_run()` persists a fresh `scores`/`reasons` row on
**every** call — that is the live-query guarantee
(`DEPLOY_ARCHITECTURE.md` §7.1: *"the mechanism by which a dispute is
visible on the very next render"*), and it is unconditional: two separate
`GET /api/queue` calls against the identical, unmodified database still each
get their own new `run_id`, because each one is a genuine fresh scoring run,
not a read of a cached one. The test's own premise — "the two payloads
should be byte-identical" — was wrong; the payloads should be identical **on
every score, band and rendered string**, and legitimately different on the
row identifiers that are supposed to be fresh every render.

This is exactly the trap `tests/test_api.py::TestScoringParity` was already
built to avoid — it compares specific fields (`points`, `points_display`,
`band`, `text`, `evidence_summary`), never a full-payload diff — and the
first version of these two new tests didn't follow that precedent closely
enough. Caught by running the test for real against two genuinely separate
live renders, which is the entire reason the brief required a real second
server rather than an in-process call.

### 3.3 The fix

Both tests were rewritten to null out `meta`, `run_id` and `run_stamp`
(queue) or strip `reason_id`/`evidence_href`/`fields.reason` from each
reason and action (detail) before comparing — matching what
`test_api.py::TestScoringParity` already does, extended across two live
server processes instead of one in-process call. A new assertion was added
alongside the fix: the two `run_id` values must be **different integers**,
not just excluded from the comparison — proving both transports genuinely
re-scored rather than one of them silently serving a cached run (the one
outcome §7.2 of `DEPLOY_ARCHITECTURE.md` forbids).

### 3.4 Clean run

```
$ python -m unittest discover tests -p "test_wsgi.py" -v 2>&1 | tail -30
test_detail_payload_scores_and_reason_text_are_identical_across_transports ... ok
test_kestrel_worked_example_survives_both_transports_identically ... ok
test_queue_payload_is_identical_across_transports_except_run_identity ... ok
test_a_prefix_lookalike_origin_does_not_match ... ok
test_allowed_origin_gets_the_header ... ok
test_cors_decision_matches_the_socket_path_for_the_same_configuration ... ok
test_disallowed_origin_gets_no_header_but_still_gets_a_200 ... ok
test_empty_allowlist_emits_no_cors_headers_at_all ... ok
test_options_never_returns_501 ... ok
test_preflight_from_a_disallowed_origin_is_200_with_no_cors_headers ... ok
test_preflight_is_200_with_content_length_zero ... ok
test_api_response_headers_are_no_store ... ok
test_health_is_cheap_and_reports_the_corpus ... ok
test_html_route_also_renders_over_wsgi_though_pages_never_calls_it ... ok
test_queue_returns_the_expected_patch_size ... ok
test_unknown_rep_and_unknown_route_are_404_with_an_error_shape ... ok
test_unsupported_method_is_501_not_a_crash ... ok
test_dispute_then_revert_over_wsgi ... ok
test_persistence_persistent_suppresses_the_ephemeral_clause_over_wsgi ... ok

----------------------------------------------------------------------
Ran 19 tests in 14.985s

OK
```

All 19 pass, genuinely: `TestScoringParityAcrossTransports` (3 tests) proves
the WSGI path and the socket path produce identical scores and reasons for
the same account, over the wire, on two separately-running server processes
sharing one database file; `TestWsgiCors` (7 tests) mirrors
`test_api.py::TestCors` test-for-test, plus one test that runs both
transports side by side and diffs their CORS headers directly;
`TestWsgiLiveHttpApi` (6 tests) proves the JSON contract and the same-origin
HTML route both work over WSGI, and that an unsupported HTTP verb fails
predictably (`501`) rather than crashing the worker; `TestWsgiWriteLoop`
(2 tests) proves the dispute→revert loop and the `persistent`-mode
confirmation wording work end to end over the WSGI entry point specifically.

---

## 4. Full suite, final

```
$ python -m unittest discover tests 2>&1 | tail -6
...
+ [] : credential-shaped assignments in prose: [('DEPLOY_TEST_OUTPUT.md', '<redacted — see §1>')]

----------------------------------------------------------------------
Ran 165 tests in 62.129s

FAILED (failures=1)
```

**165 tests total** (146 original + 19 new), **164 passed**, **1 failure —
the same pre-existing, unrelated one from §1, in an untouched Render-path
file.** Not the "146/146" the brief that opened this work assumed; stated
plainly rather than smoothed over, per §1.

---

## 5. Running the actual WSGI adapter for real — a manual harness standing in for PythonAnywhere

`tests/test_wsgi.py` proves `wsgi.application` behaves correctly as a WSGI
callable under `wsgiref`. This section goes one step further: it runs the
**exact sequence** `DEPLOY_RUNBOOK_PYTHONANYWHERE.md` §6 step 7 tells the
user to paste into PythonAnywhere's WSGI configuration file — the
`os.environ.setdefault(...)` calls, `import start; start.seed_if_needed()`,
then `from wsgi import application` — as a standalone script, serving
through `wsgiref.simple_server` on a fixed port, and drives it with `curl`
from a separate process. This is not PythonAnywhere itself (§6 states that
gap precisely), but it is a real second process talking to a real listening
socket, the same shape of evidence `DEPLOY_TEST_OUTPUT.md` §5 gathered for
the Render path before any real hosting existed.

### 5.1 First boot — seeds a fresh "persistent disk"

```
--- stdout ---
no database at ...\pa_persistent_disk\unify.db — seeding
Seeded ...\pa_persistent_disk\unify.db
  as_of            : 2026-08-11T09:00:00Z
  ruleset          : warrant-v1.0.0
  reps             : 4
  signal_types     : 19  (reference data, seeded verbatim from spec 4.1)
  accounts         : 240  (6 inactive)
  people           : 1354
  signal_events    : 6916
  observations     : 468  (75 accounts with none)
  task_events      : 877
  disagreements    : 12  (13 adjustments, 5 still active)
  forced cohorts   :
    zero_events     19 accounts
    thin            36 accounts
    stale           48 accounts
    conflicting     24 accounts
    brand_new       14 accounts
    stale_fit       43 accounts
    zero_signal      8 accounts
    no_authority    43 accounts
  verified         : 19 accounts have zero events, 66 have freshest evidence >45d old
serving wsgi.application on http://127.0.0.1:8321

--- stderr ---
warrant-wsgi build-marker 2026-08-15 · WSGI adapter over the same WarrantRoutes app.py's Handler uses · DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md
```

(stdout and stderr were captured to separate files and are shown separately
here; a first attempt that merged them into one file showed the WSGI banner
appearing *between* the two halves of the seeding summary — a stream-
buffering interleaving artifact from merging two differently-buffered
streams into one file, not a real reordering of execution. Separating the
streams confirmed the true order: seeding completes in full, then the WSGI
module is imported and prints its banner, then the server starts listening.
Same 240/1354/6916/... figures `DEPLOY_RUNBOOK.md` §9 already documents for
the Render path — same fixed seed, same corpus, different transport.)

### 5.2 Read endpoints, hit with real `curl`

```
$ curl -s http://127.0.0.1:8321/api/health
{"ok": true, "seeded": true, "accounts": 240, "reps": [...4 reps...],
 "meta": {..., "persistence": "persistent", "persistence_notice": null,
          "restart_notice": null}}

$ curl -s "http://127.0.0.1:8321/api/queue?rep=1" | head -c 500
{"rep": {"rep_id": 1, "name": "Ana Belic", "territory": "NA-MidMarket"},
 "run_id": 1, "header_line": "Warrant · Ana Belic · NA-MidMarket",
 "run_stamp": "Scored 11 Aug 2026 09:00 UTC · ruleset warrant-v1.0.0 · 53 accounts · run #1", ...}
```

`"persistence": "persistent"` and `"persistence_notice": null` confirm
`DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md` §6's decision took effect exactly as
specified, with no code change beyond the one environment variable.

### 5.3 CORS and preflight, over the manual harness

```
$ curl -s -D - -o /dev/null -H "Origin: http://127.0.0.1:8080" http://127.0.0.1:8321/api/health
HTTP/1.0 200 OK
...
Vary: Origin
Access-Control-Allow-Origin: http://127.0.0.1:8080

$ curl -s -D - -o /dev/null -H "Origin: https://evil.example.io" http://127.0.0.1:8321/api/health
HTTP/1.0 200 OK
...
Vary: Origin
(no Access-Control-Allow-Origin — the §1.5 trap, reproduced over WSGI)

$ curl -s -D - -o /dev/null -X OPTIONS -H "Origin: http://127.0.0.1:8080" \
    -H "Access-Control-Request-Method: POST" http://127.0.0.1:8321/api/dispute
HTTP/1.0 200 OK
Content-Length: 0
Vary: Origin
Access-Control-Allow-Origin: http://127.0.0.1:8080
Access-Control-Allow-Methods: GET, POST, OPTIONS
Access-Control-Allow-Headers: Content-Type
Access-Control-Max-Age: 600

$ curl -s http://127.0.0.1:8321/queue?rep=1 | head -c 300
<!doctype html><html lang="en">...<title>Warrant queue · Ana Belic</title>...

$ curl -s -o /dev/null -w "%{http_code}\n" -X PUT http://127.0.0.1:8321/api/health
501
```

Byte-identical decisions to the Render path's own documented CORS behaviour
(`DEPLOY_TEST_OUTPUT.md` §5.3), because `cors_header_lines()` and
`preflight_header_lines()` are the same two functions, called by both
transports (`DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md` §4).

### 5.4 The write loop, then the persistence claim itself — the one that matters most

```
$ curl -s "http://127.0.0.1:8321/api/queue?rep=1"    →  account_id 12, points 73.89
$ curl -s "http://127.0.0.1:8321/api/account/12?rep=1"  →  reason "New hire into a target
    function" ... action EVIDENCE_WRONG, fields {rep:1, account:12, code:EVIDENCE_WRONG,
    signal_type:7, reason:1063}

$ curl -s -X POST -d "rep=1&account=12&code=EVIDENCE_WRONG&signal_type=7&reason=1063" \
    http://127.0.0.1:8321/api/dispute
{"ok": true, "effect": {"kind": "suppress_signal_type", "expires_display": "9 Nov 2026",
 "confirmation": "You said \"New hire into a target function\" was wrong. Suppressed for
   this account until 9 Nov 2026.",   <-- note: NO "or until this demo server restarts" clause
 "undo_adjustment_id": 14}, ...}

$ curl -s "http://127.0.0.1:8321/api/account/12?rep=1"
  points 57.89
  reason0 suppressed True
```

73.89 → 57.89, the same two numbers `DEPLOY_TEST_OUTPUT.md` §6 records for
the identical account under the identical dispute on the Render path — a
useful cross-check that the fixed-seed corpus and the scoring engine are
genuinely unmodified by any of this work, on either transport.

**Then the process was killed outright** (`taskkill /F`, confirmed via
`netstat` that the listening socket was gone) **and a brand-new process was
started against the same `WARRANT_DB_PATH`** — the exact sequence
`DEPLOY_RUNBOOK_PYTHONANYWHERE.md` §8 step 10 asks a real user to perform by
clicking Reload on the Web tab:

```
--- stdout (second boot) ---
database already present at ...\pa_persistent_disk\unify.db, skipping seed
serving wsgi.application on http://127.0.0.1:8321

$ curl -s http://127.0.0.1:8321/api/health | ... boot_id 622da804, started_at 2026-08-15T01:53:44Z
    (previous boot_id was 4e418037 — confirmed a genuinely different process, not the same
     one still running)

$ curl -s "http://127.0.0.1:8321/api/account/12?rep=1"
  points 57.89                                    <-- still suppressed, not reset to 73.89
  reason0 suppressed True
  suppression_note "You said this was wrong on 11 Aug 2026. Not counted here until 9 Nov 2026."
  history [{'line': '11 Aug 2026 · you said "New hire into a target function" was wrong.
             suppress_signal_type active until 9 Nov 2026.', 'status': 'applied',
            'undo_adjustment_id': 14}]
```

**This is the real, positive proof `DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md`
§6 claims: a new `boot_id` (a genuinely new process), against the same
database path, with the dispute still fully intact** — the suppressed
reason, the adjusted points, the history entry, all present, with no seed
having re-run. This is the one thing the Render path structurally cannot
demonstrate, and it was not merely asserted here — it was watched happen,
twice (§5.1 first boot seeds; this second boot skips seeding and the data
survives), against two genuinely separate OS processes.

---

## 6. What was verified, what rests on documentation, and what is neither

### 6.1 Verified by actually running it, on this machine

- The `WarrantRoutes` refactor changes no behaviour: full suite, before and
  after, same 146/145+1 baseline (§1–§2).
- `wsgi.py` passes the stdlib-only AST scan (§2).
- The WSGI path and the socket path return identical scores, bands and
  reason text for the same account, proven over real HTTP against two
  separate live server processes sharing one database (§3.4,
  `TestScoringParityAcrossTransports`).
- CORS and preflight behave identically under WSGI and under the socket
  path, including the fail-closed default, exact-match origin comparison,
  and the §4.4 preflight's exact header set (§3.4 `TestWsgiCors`, §5.3).
- The dispute → revert write loop works end to end over the WSGI entry
  point (§3.4 `TestWsgiWriteLoop`, §5.4).
- `WARRANT_PERSISTENCE=persistent` produces `persistence_notice: null` and
  drops the ephemeral-restart clause from write confirmations, over WSGI
  specifically (§3.4, §5.2, §5.4).
- **The persistence claim itself, the load-bearing positive claim of this
  entire path**: a dispute filed against one process survives that process
  being killed and a new one started against the same database file (§5.4).
- An unsupported HTTP verb returns `501` rather than crashing the WSGI
  worker (§3.4 `test_unsupported_method_is_501_not_a_crash`).

### 6.2 Rests on PythonAnywhere's own documentation, fetched 2026-08-15, not independently reproduced

Listed in full in `DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md` §10. Restated
briefly: no card required at signup, the exact 1-month expiry wording, that
CPU-seconds do not apply to web apps, the WSGI-config-file environment-
variable mechanism, the "Manual configuration" wizard's existence, the
Python-version ceiling of 3.13, and that free accounts can reach GitHub over
HTTPS.

### 6.3 Neither verified nor merely documented

Restated from `DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md` §10, because it is the
single most important line in that document: **whether the WSGI-file-
editing mechanism and the environment-variable-via-Python-code pattern
actually work — identically, or at all — on a free PythonAnywhere account
specifically** was not confirmed by any fetch in this pipeline, and could
not be tested, because nobody in this pipeline has a PythonAnywhere account.
This is the direct analogue of `DEPLOY_TEST_OUTPUT.md` §9.4's "does Render
run a raw `ThreadingHTTPServer`" question for the first path — the one
assumption the whole path rests on that only a real account can settle, and
it is the first thing `DEPLOY_RUNBOOK_PYTHONANYWHERE.md` §2 step 1 asks the
user to check.

Also not tested, named plainly:

- **Whether Python 3.13 reproduces the fixed-seed corpus identically to
  3.14.3.** No Python 3.13 interpreter exists on this machine; none was
  installed to test this. `DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md` §8 carries
  forward `DEPLOY_ARCHITECTURE.md` §1.3's own inference that nothing in this
  codebase requires a 3.14-specific feature, but the specific risk named
  there — a different `random` stream — is untested here in either
  direction.
- **PythonAnywhere's real one-worker concurrency behaviour under load.**
  §5 of `DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md`'s "~4.8 renders/second"
  figure is arithmetic applied to PythonAnywhere's own stated formula and
  `STATUS_REPORT.md`'s existing local timing, not a measurement against a
  real PythonAnywhere worker.
- **The exact wording of the "Manual configuration" wizard's field labels**
  (`DEPLOY_RUNBOOK_PYTHONANYWHERE.md` §5 step 6) — described from general,
  long-standing platform convention, not from a page fetched in this pass.
- **Whether the web app actually expires at 1 month versus some other
  interval**, and what the Web tab's renewal control looks like when it
  matters. §0 of `DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md` states this
  contradiction was narrowed, not resolved.

---

## 7. Summary

| | |
|---|---|
| Baseline, before this work | **146 tests, 1 pre-existing failure** (unrelated, in an untouched Render-path file) |
| `app.py` → `WarrantRoutes` refactor | **Behaviour-preserving** — same 146 tests, same single failure, before and after |
| New tests written | **19**, in `tests/test_wsgi.py` |
| First run of the new tests | **2 failures** — both in the tests' own comparison logic, not in `wsgi.py` |
| Root cause | Compared full-payload equality across two genuinely separate live renders, which legitimately produce different `run_id`/`reason_id` values by design (§7.1's live-query guarantee) |
| Fix | Compare scores/bands/text, exclude per-render row identifiers — the same discipline `test_api.py::TestScoringParity` already uses |
| New tests, final run | **19/19 pass** |
| Full suite, final | **165 tests, 164 passed, 1 pre-existing failure** (same one, still unrelated, still untouched) |
| Scoring parity across transports | **Proven on the wire**, two live server processes, one database |
| CORS parity across transports | **Proven on the wire**, including a direct side-by-side header diff |
| Write loop over WSGI | **Proven on the wire** |
| Persistence across a real process restart | **Proven** — dispute survives a kill + fresh process against the same database file |
| Deployed to PythonAnywhere | **No** |
| Verified on a real PythonAnywhere account | **No — no account exists in this pipeline; this is the path's load-bearing unverified assumption, named explicitly in §6.3** |

---

*Maker agent, AI-generated. Every command and every line of output
in sections 1–5 was actually run on this machine. Section 6 states plainly
what that does and does not prove about PythonAnywhere itself.*
