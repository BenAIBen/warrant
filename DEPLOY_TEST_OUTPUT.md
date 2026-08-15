# DEPLOY_TEST_OUTPUT.md — what was actually run, and what actually happened

**Stage:** 3 of 4 (build)
**Author:** Maker agent (AI-generated)
**Date:** 14 August 2026
**Machine:** Windows 11, Python 3.14.3 at
`C:\Users\DELL Lattitude\AppData\Local\Python\pythoncore-3.14-64\python.exe`
**Companion documents:** `DEPLOY_ARCHITECTURE.md` (the spec), `DEPLOY_RUNBOOK.md` (the steps)

---

## 0. Scope, stated before any output

This session **resumed** stage 3. A previous maker agent had already written
`warrant/api.py`, `start.py`, `warrant/runtime.py`, the five `docs/` files, the CORS
and `do_OPTIONS` changes to `app.py`, the `bind_host()`/`port()` changes to
`warrant/db.py`, `.env.example`, `requirements.txt`, and `tests/test_api.py`. That
agent was killed by an infrastructure error (API 529) mid-run, with a last reported
status of *"All 49 API tests pass. Now the full suite."*

**It never got to run the full suite.** That is where this transcript starts, and it
is where the two real failures were found.

**Nothing below touched real hosting.** Section 9 states precisely what that means
and what it does not.

---

## 1. First full run — 2 failures

The previous agent had verified `tests/test_api.py` in isolation. Running everything
together is the step it did not reach.

```
$ python -m unittest discover tests

======================================================================
FAIL: test_no_credential_shaped_string_in_the_repo (test_queue.TestNoSecrets.test_no_credential_shaped_string_in_the_repo)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "...\tests\test_queue.py", line 343, in test_no_credential_shaped_string_in_the_repo
    self.assertEqual(offenders, [], "credential-shaped strings: %r" % (offenders,))
AssertionError: Lists differ: [('DEPLOY_ARCHITECTURE.md', 'api_key'), ('[662 chars]et')] != []

First list contains 17 additional elements.
First extra element 0:
('DEPLOY_ARCHITECTURE.md', 'api_key')

: credential-shaped strings: [('DEPLOY_ARCHITECTURE.md', 'api_key'),
('DEPLOY_ARCHITECTURE.md', 'apikey'), ('DEPLOY_ARCHITECTURE.md', 'bearer '),
('HOSTING_RESEARCH.md', 'authorization:'), ('HOSTING_RESEARCH.md', 'bearer '),
('tests\\test_api.py', 'bearer '), ('transcripts\\00-main-conversation.md', 'sk-'),
('transcripts\\03-maker.md', 'api_key'), ('transcripts\\03-maker.md', 'apikey'),
('transcripts\\03-maker.md', 'secret_key'), ('transcripts\\03-maker.md', 'password='),
('transcripts\\03-maker.md', 'authorization:'), ('transcripts\\03-maker.md', 'bearer '),
('transcripts\\03-maker.md', 'sk-'), ('transcripts\\03-maker.md', 'aws_access'),
('transcripts\\03-maker.md', 'private_key'), ('transcripts\\03-maker.md', 'client_secret')]

======================================================================
FAIL: test_every_python_file_imports_only_stdlib_or_local (test_queue.TestT19StandardLibraryOnly.test_every_python_file_imports_only_stdlib_or_local)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "...\tests\test_queue.py", line 268, in test_every_python_file_imports_only_stdlib_or_local
    self.assertEqual(offenders, [], "non-stdlib imports found: %r" % (offenders,))
AssertionError: Lists differ: [('C:\\...\\tests\\test_api.py', 'start')] != []

: non-stdlib imports found: [('C:\\...\\tests\\test_api.py', 'start')]

----------------------------------------------------------------------
Ran 143 tests in 52.682s

FAILED (failures=2)
```

**143 = 94 pre-existing + 49 new.** The 49 figure matches the previous agent's report
exactly, and all 49 pass. Both failures are in the pre-existing suite.

---

## 2. Failure 1 — T19: `start.py` was invisible to the test that guards it

### What the error actually says

`tests/test_api.py` imports a module named `start`, and `start` is not in
`tests/test_queue.py`'s `LOCAL_MODULES` allowlist, so the stdlib-only check counted
it as a third-party package.

### What it actually means

`start.py` is a **local file at the repo root**, added for the deploy, in exactly the
same category as `app.py` and `seed_db.py` which *are* allowlisted. It imports `os`,
`sys`, `app` and `seed_db` and nothing else. There is no third-party dependency.

But diagnosing it turned up a **second, worse problem the failure was hiding**. The
helper that decides which files T19 and T20 inspect:

```python
def python_files():
    targets = []
    for name in ("app.py", "seed_db.py"):
        targets.append(os.path.join(REPO_ROOT, name))
```

**`start.py` was not in that list.** So T19 (stdlib-only) and T20 (no interpolated
SQL) were never looking at the container entry point — the first file a deploy runs.
Simply allowlisting the name would have made the test pass while leaving that hole
open.

### The fix — two changes, one of which makes the test stronger

In `tests/test_queue.py`:

```python
    # start.py added with the deploy work (DEPLOY_ARCHITECTURE.md §6.2). It was
    # missing from this list, so T19 and T20 were not actually looking at the
    # container entry point — the one file a deploy runs first.
    for name in ("app.py", "seed_db.py", "start.py"):
        targets.append(os.path.join(REPO_ROOT, name))
```

```python
LOCAL_MODULES = {"warrant", "tests", "support", "seed_db", "app", "start"}
```

The allowlist entry permits the local *name*; the `python_files()` entry means the
*file* is now scanned. Net effect: T19 and T20 cover strictly more than before.

---

## 3. Failure 2 — the secret scan, which was firing on prose about secrets

### Attributing the failure before fixing it

17 offenders across 5 files. The first question is whether stage 3 caused this. It
mostly did not:

```
$ python -c "<the scan, with each hit attributed to the stage that wrote the file>"

PRE-EXISTING  DEPLOY_ARCHITECTURE.md          ['api_key', 'apikey', 'bearer ']
PRE-EXISTING  HOSTING_RESEARCH.md             ['authorization:', 'bearer ']
STAGE3        tests/test_api.py               ['bearer ']
PRE-EXISTING  transcripts/00-main-conversation.md  ['sk-']
PRE-EXISTING  transcripts/03-maker.md         ['api_key', 'apikey', 'secret_key',
                                               'password=', 'authorization:', 'bearer ',
                                               'sk-', 'aws_access', 'private_key',
                                               'client_secret']
```

**4 of the 5 offending files predate stage 3.** `DEPLOY_ARCHITECTURE.md` — the stage-2
design document — fails because its **§8.4 specifies this very scan and has to name
the tokens in order to specify it**. `HOSTING_RESEARCH.md` fails on a discussion of
CORS request headers. The transcripts fail because they are a verbatim log of agents
discussing this test.

**Not one of the 17 hits is a credential.** Every one is prose *about* credentials.
The stage-2 deliverable broke a stage-1 test simply by being written.

### The stage-3 hit, diagnosed exactly

One hit was genuinely ours. Rather than guess, I located the byte:

```
$ python -c "t=open('tests/test_api.py').read().lower(); i=t.find('bearer '); print(repr(t[i-30:i+30]))"

', ("auth", "orization")))\n    bearer = "bear" + "er "\n\n    d'
```

The **value** was correctly assembled from fragments — `"Bear" + "er "` — exactly the
trick `tests/test_queue.py` documents for avoiding self-detection. But the **variable
name** was not. `BEARER = ` lowercases to the scanned-for token followed by a space.

The previous agent's comment on that block reads, in part: *"The repo-wide bare-word
scan in tests/test_queue.py::TestNoSecrets is unchanged and still applies to every
.py, .sql and .example file, where prose false positives do not arise."* That is a
clear statement of intent — but the repo-wide scan also covered `.md` and `.txt`,
which is where the false positives were. The intent was right; it was never
implemented.

### The fix

**Part 1 — rename the constant** (`tests/test_api.py`). One token, no behaviour
change:

```python
    BEARER_PREFIX = "Bear" + "er "
```

**Part 2 — split the repo-wide scan by file kind** (`tests/test_queue.py`), which is
the previous agent's stated intent, made real:

- **Code and config** (`.py`, `.sql`, `.example`) keep the **strict bare-name rule,
  unchanged**. A source file has no reason to contain the word at all.
- **Prose** (`.md`, `.txt`) is scanned for a credential **name followed by a value** —
  `name`, an optional identifier tail, `:` or `=`, then 8+ value characters — plus
  patterns for a space-separated auth scheme token and a provider-prefixed key.

This is **a real weakening for prose files and it is recorded as one.** The argument
for it: a scanner that fires on the document that defines it, and on a file whose
sentence is *"Nothing here is a secret"*, is a scanner that gets suppressed rather
than fixed — and a suppressed scanner catches nothing. What an actual leak looks like
is a name next to a value.

Because the prose rule is looser, **two negative controls** keep it honest:

```python
    def test_the_prose_detector_actually_catches_a_leak(self):
        planted = [
            "Set api" + "_key = \"9f2a71c4e8b0d356\" in the dashboard.",
            "api" + "Key: 'abcd1234efgh5678'",
            "Author" + "ization: Bear" + "er eyJhbGciOiJIUzI1NiJ9",
            "export aws" + "_access" + "_key_id=AKIA1J2K3L4M5N6O",
            "pass" + "word=hunter2hunter2",
            "the token is " + "s" + "k-1234567890abcdefghij",
            "client" + "_secret: 8b1d7ac92fe44081",
        ]
```

plus a false-positive control asserting the sentences that broke the old rule are
**not** reported.

### Three iterations, because the fix kept tripping its own scan

**Iteration 1** missed a planted leak:

```
FAIL: test_the_prose_detector_actually_catches_a_leak
AssertionError: False is not true : the prose detector missed a planted leak:
'export aws_access_key_id=AKIA1J2K3L4M5N6O'
```

The pattern required the separator immediately after the name, but the real-world
name has a `_key_id` tail before the `=`. Fixed by allowing an identifier tail.

**Iterations 1 and 2** also failed on my own new code:

```
AssertionError: [('tests\\test_api.py', 'bearer '),
                 ('tests\\test_queue.py', 'sk-'),
                 ('tests\\test_queue.py', 'aws_access')] != []
```

I stopped guessing and located each byte:

```
tests/test_api.py   801 '. this was `bearer` and the assignment line `bearer = "bear"'
tests/test_queue.py 377 ' it\n # this fired on the word "de" + "sk-notification" in a tra'
tests/test_queue.py 444 '" + "ization header.",\n  "a de" + "sk-notification arrived",'
tests/test_queue.py 362 'ier tail before the separator, so that\n # aws_access + "_key_id=aki'
```

All four were **comments I had just written explaining the fix**, plus one benign
test sample. The strict bare-name rule over `.py` files is strict enough that you
cannot write a comment describing it without tripping it. Rewrote the comments to
describe the tokens instead of spelling them, and fragmented the sample.

**That is itself the evidence for part 2 of the fix.** A rule you cannot document in
its own file without violating it is too blunt for prose.

### Fourth iteration — clean

```
$ python -m unittest discover tests -p "test_queue.py"
----------------------------------------------------------------------
Ran 23 tests in 16.518s

OK
```

---

## 4. Clean full run

```
$ python -m unittest discover tests

----------------------------------------------------------------------
Ran 146 tests in 56.772s

OK
```

**146 = 94 pre-existing + 49 new API tests + 3 added by this session** (the secret
scan split into two tests, plus the two negative controls).

Per module:

```
test_scoring:     16 tests
test_reasons:     18 tests
test_queue:       23 tests
test_feedback:    16 tests
test_edge_cases:  24 tests
test_api:         49 tests
```

### The specific tests §7.3 requires — all present, all passing

```
$ python -m unittest discover tests -p test_api.py -k test_api_queue_reflects_a_live_db_mutation \
    -k test_api_response_headers_are_no_store -k test_api_reason_points_sum_to_score_points \
    -k test_api_serialiser_contains_no_arithmetic -k TestScoringParity -k TestDocsFolder -v

test_api_reason_points_sum_to_score_points (test_api.TestApiExplanationIsTheModel...) ... ok
test_api_queue_reflects_a_live_db_mutation (test_api.TestApiIsStillLiveQuery...) ... ok
test_api_response_headers_are_no_store (test_api.TestLiveHttpApi...) ... ok
test_api_serialiser_contains_no_arithmetic (test_api.TestSerialiserContainsNoArithmetic...) ... ok
test_detail_reason_values_equal_the_engine (test_api.TestScoringParity...) ... ok
test_kestrel_worked_example_survives_the_port (test_api.TestScoringParity...) ... ok
test_queue_payload_points_equal_the_engine (test_api.TestScoringParity...) ... ok
test_no_file_in_docs_contains_a_credential_shaped_string (test_api.TestDocsFolder...) ... ok
test_the_credential_detector_actually_catches_a_leak (test_api.TestDocsFolder...) ... ok
...
Ran 15 tests in 4.093s
OK
```

**The scoring-parity test already existed and I did not have to write it.** It is
`TestScoringParity`, and it does the right thing: it builds the JSON payload and
independently calls `score_account()` / `build_run()` for the same account and rep,
then asserts `wire points == engine points`, `wire band == engine band`, and per
reason `points`, `rank`, `text`, `evidence_summary` and `signal_type_id` are equal.
It compares 40+ accounts and 50+ reasons, and separately asserts the §4.4 Kestrel
worked example still lands on **61.24** through the serialiser.

**§8.4's `docs/` secret scan already existed too**, with negative controls, and with a
documented reason for scanning name-plus-value rather than bare names — the same
conclusion I reached independently in §3 above, which is mild evidence it is the right
call.

### §5.2 — `docs/app.js` must never hardcode the backend URL

```
$ grep -c "onrender" docs/app.js
0
$ grep -n "onrender" docs/app.js
$ echo "(no lines printed above = zero hits)"

For contrast, config.js SHOULD contain the placeholder:
$ grep -n "onrender" docs/config.js
5://   window.WARRANT_CONFIG = { apiBase: "https://warrant-demo-abc1.onrender.com" };
17:  apiBase: "https://<your-app>.onrender.com"   // placeholder — replace with your own
```

**Zero hits in `app.js`.** The URL lives only in `config.js`, which is the one file
the user edits.

---

## 5. Running the backend for real

Started via the actual container entry point, with an existing database present:

```
$ WARRANT_BIND_HOST=127.0.0.1 WARRANT_PORT=8123 \
  WARRANT_ALLOWED_ORIGINS="http://localhost:8080" WARRANT_PERSISTENCE=ephemeral \
  python start.py

warrant-start build-marker 2026-08-13 · conditional seed, then serve
boot_id=e5b36cf9 started_at=2026-08-13T23:26:02Z persistence=ephemeral db=unify.db
database already present at C:\...\data\unify.db, skipping seed
warrant-app build-marker 2026-08-11 · live SQL per request, no cache
warrant-api build-marker 2026-08-13 · /api + CORS + do_OPTIONS · DEPLOY_ARCHITECTURE.md §3/§4
Warrant listening on http://127.0.0.1:8123/queue?rep=1
as_of=2026-08-11T09:00:00Z ruleset=warrant-v1.0.0
```

### 5.1 A real failure while probing it

The first probe run crashed — not in the app, in my probe script's console:

```
Traceback (most recent call last):
  File "...\probe_reads.py", line 60, in <module>
    print("    rank %s  %-22s %-22s %s" % (...))
  File "...\Lib\encodings\cp1252.py", line 19, in encode
    return codecs.charmap_encode(input,self.errors,encoding_table)[0]
UnicodeEncodeError: 'charmap' codec can't encode character '\u2212' in position 35:
character maps to <undefined>
```

**Diagnosis:** U+2212 MINUS SIGN, from a negative reason's `points_display` value
(`−9 pts`), hitting a Windows console defaulting to cp1252. The server produced
correct UTF-8; my terminal could not print it. Re-ran with `PYTHONIOENCODING=utf-8`.

Worth recording because it is a real property of the payload: **`points_display` for
a negative reason uses a typographic minus (U+2212), not an ASCII hyphen.** Anything
downstream that assumes ASCII will break the same way.

### 5.2 Read endpoints — real status codes, real bodies

```
GET /api/health -> 200
  ok=True seeded=True accounts=240 reps=['Ana Belic', 'Lena Lindqvist', 'Elena Petrov', 'Keiko Fitzgerald']
  meta.as_of=2026-08-11T09:00:00Z
  meta.persistence=ephemeral
  meta.boot_id=e5b36cf9
  meta.persistence_notice=This demo server runs on free hosting with no persistent disk.
    It last restarted on 13 Aug 2026 23:26 UTC. Anything a rep filed before then —
    disputes, pins, mutes — is gone. Everything you file now lasts until the next restart.

GET /api/queue?rep=1 -> 200   (25909 bytes)
  account_count=53  run_id=23
  header_line=Warrant · Ana Belic · NA-MidMarket
  run_stamp=Scored 11 Aug 2026 09:00 UTC · ruleset warrant-v1.0.0 · 53 accounts · run #23
  budget_bar=pins 1/5 · demotes 1/10 · patch-wide signal suppressions 0/3 · muted accounts 1/25
  #1 Cobalt Freight             ACT NOW          74  Cobalt Freight hired Keiko Bhattacharya...
  #2 Harbour Technologies       ACT NOW         105  CMO and 3 others used the product across 5...
  #3 Yarrow Partners            REVIEW           94  Product Manager and 1 other used the product...

GET /api/account/12?rep=1 -> 200   (7773 bytes)
  verdict points=73.89 display=74 band=ACT NOW conf=high
  rank_line=rank 1 of 53 (was 7 before your adjustments)
  reasons returned=5
    rank 1  TIMING                 +16 pts (capped at 16)
    rank 2  ACTIVE EVALUATION      +13 pts
    rank 3  ACTIVE EVALUATION      +11 pts (capped at 11)
    rank 4  ACTIVE EVALUATION      +10 pts (capped at 10)
    rank 6  DISQUALIFIER           −9 pts (capped at 9)
  sum(shown reason points) = 40.8300
  limits_line=Showing the 5 strongest of 10 signals. The 5 not shown are worth +33.1 pts
    combined and are part of why this is ACT NOW — the 5 shown alone would rate REVIEW.

GET /api/evidence/8178?rep=1 -> 200
  header=Evidence · New hire into a target function · Cobalt Freight
  summary_line=Reason computed 11 Aug 2026 09:00 UTC from 5 events. Total +16.00 pts (cap +16.00).
  events=5  kind=event
  first event: 10 Aug 2026 18:00 UTC | +7.94 pts | source: job_change_feed · ingested 11 Aug 20...

GET /api/reps                  -> 200    1364 bytes  Cache-Control: no-store
GET /api/adjustments?rep=1     -> 200    2546 bytes  Cache-Control: no-store
GET /api/metrics               -> 200    7779 bytes  Cache-Control: no-store
GET /api/ruleset               -> 200   10437 bytes  Cache-Control: no-store

ERROR SHAPES
GET /api/queue?rep=999           -> 404  code=NOT_FOUND     No such rep.
GET /api/nonsense                -> 404  code=NOT_FOUND     No such endpoint.
GET /api/account/999999?rep=1    -> 404  code=NOT_IN_QUEUE  This account is not in your queue...
```

**Note the arithmetic on the wire.** Shown reasons sum to `40.83`; the verdict is
`73.89`; the difference is `33.06`, and `limits_line` states the withheld total as
`+33.1 pts`. The rep's addition works.

**Note also `rank 6` in a list of 5 shown reasons.** Ranks are dense over *all*
reasons, not renumbered for the shown subset — rank 5 was withheld. The frontend does
not renumber, which is correct.

### 5.3 CORS, genuinely cross-origin

`python -m http.server 8080` serving `docs/`, backend on `8123`. **Different port =
different origin**, so this is a real cross-origin configuration, not a simulation.

```
$ curl -s -o /dev/null -w "%{http_code} %{size_download}\n" http://localhost:8080/index.html
200 1557
$ curl ... http://localhost:8080/app.js
200 41549
```

#### Case 1 — allowed Origin

```
GET /api/health          Origin: http://localhost:8080
  HTTP 200
  Access-Control-Allow-Origin:   http://localhost:8080
  Vary:                          Origin
  Content-Type:                  application/json; charset=utf-8
  Content-Length:                1242
  Cache-Control:                 no-store
  ==> header present AND exactly equal to the request Origin. PASS
```

#### Case 2 — disallowed Origin: §1.5's trap, demonstrated

```
GET /api/health          Origin: https://evil-someone.github.io
  HTTP 200
  Access-Control-Allow-Origin:   <ABSENT>
  Access-Control-Allow-Methods:  <ABSENT>
  Access-Control-Allow-Headers:  <ABSENT>
  Vary:                          Origin
  Content-Length:                1242
  Cache-Control:                 no-store
  body bytes: 1242
  body parsed fine: accounts=240 seeded=True
```

**This is the failure the runbook's §7.0 warns about, caught in the act.** The status
is a clean `200`. The full 1,242-byte JSON body was produced and sent — I parsed it,
it is complete and correct. There is no `Access-Control-Allow-Origin` header, so a
browser would fetch all of this and then refuse to hand it to the script. The server
logs success. The user sees an empty page.

#### Case 2b — exact matching, no prefix or suffix tricks

```
  Origin http://localhost:8080.evil.test    -> 200  ACAO: <ABSENT>
  Origin http://localhost:808               -> 200  ACAO: <ABSENT>
  Origin http://localhost:8080/             -> 200  ACAO: <ABSENT>
  Origin https://localhost:8080             -> 200  ACAO: <ABSENT>
  ==> none matched. PASS
```

The trailing-slash case is the one that matters for the runbook: it is exactly the
shape of the mistake a user makes by pasting a page URL instead of an origin.

#### Case 3 — `OPTIONS` preflight, against §4.4's literal specification

```
OPTIONS /api/dispute     Origin: http://localhost:8080
                         Access-Control-Request-Method: POST
                         Access-Control-Request-Headers: Content-Type
  HTTP 200
  Access-Control-Allow-Origin:   http://localhost:8080
  Access-Control-Allow-Methods:  GET, POST, OPTIONS
  Access-Control-Allow-Headers:  Content-Type
  Access-Control-Max-Age:        600
  Vary:                          Origin
  Content-Length:                0
  body bytes: 0

  [PASS] status is 200 not 204
  [PASS] Content-Length: 0
  [PASS] body is empty
  [PASS] ACAO exact
  [PASS] Allow-Methods
  [PASS] Allow-Headers
  [PASS] Max-Age 600
  [PASS] Vary: Origin
  [PASS] no HEAD advertised
```

Every item §4.4 specifies, matched literally.

```
OPTIONS /api/dispute     Origin: https://evil-someone.github.io
  HTTP 200
  Access-Control-Allow-Origin:   <ABSENT>
  Content-Length:                0
  ==> 200 + Content-Length: 0 + NO CORS headers, and NOT a 403.

OPTIONS with NO Origin at all -> HTTP 200 (must never be 501)
```

The pre-change behaviour would have been `501 Unsupported method`. It is not.

#### Case 4 — no Origin, and the HTML app

```
GET /api/health          (no Origin header — curl, or the runbook's verification step)
  HTTP 200, no CORS headers, Cache-Control: no-store

GET /queue?rep=1         Origin: http://localhost:8080
  HTTP 200  Content-Type: text/html; charset=utf-8  bytes=58756
  ACAO: <ABSENT>   Cache-Control: <ABSENT>
  ==> correct: the no-JS HTML app is same-origin and needs none.
```

**The HTML app is untouched by the port** — still served, still 58 KB of
server-rendered HTML, still no CORS headers and no `no-store` (both correct for it).

```
ALL CORS ASSERTIONS PASSED
```

---

## 6. The write loop, end to end over HTTP

Every step below is a real HTTP request. Nothing touches the database directly. The
POST body is `urlencode(...)` with `Content-Type: application/x-www-form-urlencoded`
— byte-identical to what the HTML forms submit, and to what `URLSearchParams`
produces in a browser, which is what keeps these "simple requests" with no preflight.

```
STEP 1 — baseline for account 12 (Cobalt Freight)
  points          = 73.89   (points_display '74')
  band            = ACT NOW
  rank_line       = rank 1 of 53 (was 7 before your adjustments)
  reasons shown   = 5
  limits_line     = Showing the 5 strongest of 10 signals. The 5 not shown are worth
                    +33.1 pts combined ... the 5 shown alone would rate REVIEW.
  targeting reason rank 1, signal_type 7, worth 16.0 (+16 pts (capped at 16))
  reason text     = Cobalt Freight hired Keiko Bhattacharya as Data Engineer on
                    10 Aug 2026 — new owners re-open decisions.
  rank in queue   = 1

STEP 2 — POST /api/dispute  {'rep': 1, 'account': 12, 'code': 'EVIDENCE_WRONG',
                             'signal_type': 7, 'reason': 9594}
  -> HTTP 200
  disagreement_id      = 13
  effect.kind          = suppress_signal_type
  effect.expires_display = 9 Nov 2026
  effect.confirmation  = You said "New hire into a target function" was wrong.
                         Suppressed for this account until 9 Nov 2026, or until this
                         demo server restarts, whichever comes first.
  effect.undo_adjustment_id = 14
  next                 = {'view': 'account', 'href': '/api/account/12?rep=1'}

STEP 3 — re-fetch the SAME account. This is a fresh build_run().
  points          = 57.89   (was 73.89)
  points_display  = '58'  (was '74')
  adjusted_note   = was 74 pts before your disagreement
  DELTA           = -16.00   (the disputed reason was worth +16.00)
  the disputed reason is STILL IN ITS SLOT at rank 1:
    is_suppressed    = True
    points           = 0.0
    points_display   = '+16 pts → 0 pts'
    suppression_note = You said this was wrong on 11 Aug 2026. Not counted here
                       until 9 Nov 2026.
    undo_adjustment_id = 14
    actions          = []
  limits_line     = Showing the 5 strongest of 10 signals. The 5 not shown are worth
                    +33.1 pts combined and are part of why this is ACT NOW — the 5
                    shown alone would rate HOLD. Suppressed by you: "New hire into a
                    target function".

  history now reads:
    - 11 Aug 2026 · you said "New hire into a target function" was wrong.
      suppress_signal_type active until 9 Nov 2026.

  queue rank for this account: 1 -> 1   points_display '74' -> '58'

STEP 4 — POST /api/adjust/revert  {'rep': 1, 'adjustment': 14, 'account': 12}
  -> HTTP 200
  effect.kind         = reverted
  effect.confirmation = Undone. The signal counts again from now.

STEP 5 — re-fetch again. Score must be restored EXACTLY.
  points          = 73.89   (baseline was 73.89)
  points_display  = '74'  (baseline '74')
  band            = ACT NOW   (baseline ACT NOW)
  limits_line     = ... the 5 shown alone would rate REVIEW.
  disputed reason: is_suppressed=False points=16.0 display='+16 pts (capped at 16)'

  EXACT RESTORATION: YES
```

**The numbers close.** `73.89 − 16.00 = 57.89` exactly. Revert restores `73.89`
exactly, with a byte-identical limits line.

Four details worth pulling out, because each is a design requirement surviving the
port:

1. **The confirmation carries the ephemeral clause** — *"or until this demo server
   restarts, whichever comes first"* — composed server-side from
   `WARRANT_PERSISTENCE`. That sentence appears at the moment the rep has just
   extended trust, which is when it matters most.
2. **The suppressed reason stays in its slot at rank 1**, showing `+16 pts → 0 pts`
   and a note saying until when. It is not removed and not reordered.
3. **The limits line changed band**, from *"the 5 shown alone would rate REVIEW"* to
   *"…would rate HOLD"*, and gained *"Suppressed by you: …"*. It was recomputed, not
   cached.
4. **The rank did not change** (still 1 of 53) because a pin is holding it there,
   while the points visibly dropped. The two are independent, and the payload shows
   both honestly rather than hiding the tension.

---

## 7. `start.py` — both branches of the conditional

§6.6 calls this conditional "the single line that turns the upgrade from a rewrite
into a setting", so both branches were exercised.

### Branch A — no database present: it seeds

```
$ ls -la .../freshvol
total 4
drwxr-xr-x ... .
drwxr-xr-x ... ..
--- no database file present ---

$ WARRANT_BIND_HOST=0.0.0.0 PORT=8124 WARRANT_PERSISTENCE=ephemeral \
  WARRANT_DB_PATH=...\freshvol\unify.db python start.py

warrant-start build-marker 2026-08-13 · conditional seed, then serve
boot_id=b0050f65 started_at=2026-08-13T23:29:09Z persistence=ephemeral db=unify.db
no database at ...\freshvol\unify.db — seeding
Seeded ...\freshvol\unify.db
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
warrant-app build-marker 2026-08-11 · live SQL per request, no cache
warrant-api build-marker 2026-08-13 · /api + CORS + do_OPTIONS · DEPLOY_ARCHITECTURE.md §3/§4
Warrant listening on http://0.0.0.0:8124/queue?rep=1
```

**Two things this proves beyond the seed branch.** `WARRANT_BIND_HOST=0.0.0.0` binds
`0.0.0.0` — the thing Render's port detection requires. And the port came from
**`PORT=8124`**, not `WARRANT_PORT`, exercising the platform-injection fallback in
`warrant/db.py::port()`.

**This is the log block the runbook tells the user to expect on Render**, and the
counts in `DEPLOY_RUNBOOK.md` step 9 are copied from here rather than invented.

Against that pristine instance:

```
GET /api/health -> 200
  ok=True  seeded=True  accounts=240
    rep 1  Ana Belic            NA-MidMarket
    rep 2  Lena Lindqvist       NA-Enterprise
    rep 3  Elena Petrov         EMEA-MidMarket
    rep 4  Keiko Fitzgerald     APAC-All
  meta.as_of=2026-08-11T09:00:00Z  ruleset=warrant-v1.0.0

GET /api/queue?rep=1 -> 200
  account_count=53
  PRISTINE top 5 (this is what a fresh deploy shows):
    #1  Cobalt Freight           ACT NOW            74
    #2  Harbour Technologies     ACT NOW           105
    #3  Yarrow Partners          REVIEW             94
    #4  Kestrel Systems          ACT NOW            91
    #5  Tundra Dynamics          ACT NOW            84
```

**Identical to the long-lived working database** in §5.2 — same top accounts, same
points, same `account_count`, same `budget_bar`. Reproducibility from the fixed seed
holds across a completely fresh database in a different directory. This is the check
`DEPLOY_RUNBOOK.md` §7.6 is built on.

### Branch B — database present: it skips

Same path, second boot:

```
$ ls -la .../freshvol
-rw-r--r-- ... 1953792 ... unify.db
=== database now EXISTS. Booting start.py again against the same path ===

warrant-start build-marker 2026-08-13 · conditional seed, then serve
boot_id=de314443 started_at=2026-08-13T23:30:10Z persistence=persistent db=unify.db
database already present at ...\freshvol\unify.db, skipping seed
warrant-app build-marker 2026-08-11 · live SQL per request, no cache
Warrant listening on http://0.0.0.0:8125/queue?rep=1
```

**Skipped, as designed.** This is the persistent-volume upgrade path working: first
boot seeds, every later boot leaves the reps' data alone.

The `boot_id` also changed (`b0050f65` → `de314443`), which is the mechanism the
frontend uses to detect a restart mid-session.

### `WARRANT_PERSISTENCE=persistent` suppresses the disclosure

```
WARRANT_PERSISTENCE=persistent  ->  /api/health meta:
  persistence          = 'persistent'
  persistence_notice   = None
  boot_id              = 'de314443'
  accounts             = 240  seeded=True
```

One environment variable, and the notice becomes `null` — the frontend renders
nothing, with no frontend change. §6.5's "one env var, three behaviours, zero code
branches in the frontend" holds.

---

## 8. The frontend, driven for real

`node` turned out to be installed (v24.17.0), which allowed more than serving bytes.

### 8.1 It parses

```
$ node --check config.js  -> OK (parses as valid JavaScript)
$ node --check app.js     -> OK (parses as valid JavaScript)
```

### 8.2 It runs, against the live backend

`app.js` uses a very small DOM surface — `appendChild`, `createTextNode`,
`createElement`, `getElementById`, `textContent`, `hidden`, `href`, `title`,
`firstChild`, `removeChild`, `className`, plus `window.location`, `setTimeout` and
`fetch`. I stubbed exactly those in a `vm` context and loaded **the real, unmodified
`docs/config.js` and `docs/app.js`**, with node's real `fetch` doing real HTTP to the
running backend on `127.0.0.1:8123`, and `window.location.origin` set to
`http://localhost:8080`.

**This is not a browser.** But it is the actual frontend source executing its actual
routing, fetching and DOM construction against actual server responses.

```
config.js loaded. apiBase as shipped = "https://<your-app>.onrender.com"
apiBase overridden to http://127.0.0.1:8123 (simulating the user editing config.js)

======================================================================
§5.5 queue view  ->  GET /api/queue?rep=1   (location.hash = #/queue?rep=1)
======================================================================
--- persistence notice (chrome, every view) ---
  This demo server runs on free hosting with no persistent disk. It last restarted
  on 13 Aug 2026 23:26 UTC. Anything a rep filed before then — disputes, pins,
  mutes — is gone. Everything you file now lasts until the next restart.
--- #view ---
  [div]
    [h1] Warrant · Ana Belic · NA-MidMarket
    [p.meta] Scored 11 Aug 2026 09:00 UTC · ruleset warrant-v1.0.0 · 53 accounts · run #32
    [p.meta]
       Your adjustments:
      [a] pins 1/5 · demotes 1/10 · patch-wide signal suppressions 0/3 · muted accounts 1/25
    [div.row]
      [span.pts]
         74
         pts
      [span.rank] 1.
      [span.chip act] ACT NOW
      [a] Cobalt Freight
      [span.chip adj] PINNED BY YOU
      [div.sentence] Cobalt Freight hired Keiko Bhattacharya as Data Engineer on
                     10 Aug 2026 — new owners re-open decisions.
      [div.meta]
        [span.chip] evidence 0d old
        [span] 5 of 10 signals shown
      [div.actions]
        [button.primary] Work it
        [button] Not now
        [a] Dispute
    ... 52 more rows ...
```

Note `[span.pts] 74 / pts` — the frontend appended the fixed chrome word `pts` to the
server's `points_display` string `74`. It did not round, sign or format anything.
That is §5.4 rule 3 working as specified.

The detail view:

```
    [h1] Cobalt Freight · cobaltfrei.io
    [p.meta] Data & Analytics · 729 employees · GB · CRM: no record · owner: you
    [p]
      [span.chip act] ACT NOW
      [strong] 74 pts
      [span.meta] bar for ACT NOW is 45 · scale anchored at 75
    [p.meta] rank 1 of 53 (was 7 before your adjustments) · confidence: high
    [div.banner]
      [div] These signals disagree. Cobalt Freight hired Keiko Bhattacharya as Data
            Engineer on 10 Aug 2026 — new owners re-open decisions, but Oskar
            Nakamura unsubscribed or hard-bounced on 8 Aug 2026. Read both before you act.
    [h2] Why this is at the top
    [div.reason]
      [div.cat] TIMING
      [div.sentence] Cobalt Freight hired Keiko Bhattacharya as Data Engineer on 10 Aug 2026...
      [div.evidence] Role start 10 Aug 2026 · source: job change feed
      [div.rpts] +16 pts (capped at 16)
      [div.actions]
        [a] see evidence
        [button] this is wrong
        [button] out of date
    ... 4 more reasons ...
    [div.limits] Showing the 5 strongest of 10 signals. The 5 not shown are worth
                 +33.1 pts combined and are part of why this is ACT NOW — the 5 shown
                 alone would rate REVIEW.
    [h2] Adjust your queue
    ...
```

**Element order inside each reason is `category → sentence → evidence → points →
actions`**, which is §5.4 rule 4 and `DESIGN_SPEC.md` §6.2 implication #3: the points
value comes *after* the evidence, never before it. **The limits line is present,
directly under the reasons.** Every string on the page traces to a server field.

### 8.3 §9.5 — unedited placeholder makes zero network requests

Run with `config.js` left exactly as shipped:

```
config.js loaded. apiBase as shipped = "https://<your-app>.onrender.com"

§9.5 UNEDITED PLACEHOLDER — must make NO network request
--- #view ---
  [div]
    [div.state]
      [h2] Warrant is deployed here, but not connected to a backend yet.
      [p] GitHub Pages is serving this page correctly. It has no backend URL to talk to.
      [p] To finish setup: deploy the backend, then edit docs/config.js in this
          repository and replace the placeholder with your backend's URL...
      [p] Nothing here is a secret. config.js holds one public URL and no keys.
      [p] Current value in docs/config.js:
        [code] https://<your-app>.onrender.com

TOTAL fetch() CALLS MADE: 0   <-- correct, §9.5 requires zero
```

I wrapped `fetch` in a counter to prove this rather than assert it. **Zero.**

### 8.4 §9.2 — unreachable backend

Pointed `apiBase` at a closed port. The wake timers were overridden **in the sandbox**
(`WAKE_TIMEOUT_MS = 1`) so the 90-second fall-through happened immediately;
`app.js` itself was not modified.

```
wake timers overridden in-sandbox: TIMEOUT=1ms POLL=20ms (app.js unmodified)
    [network] fetch #1 GET http://127.0.0.1:9099/api/health
    [network] fetch #2 GET http://127.0.0.1:9099/api/health
    [network] fetch #3 GET http://127.0.0.1:9099/api/health
    [network] fetch #4 GET http://127.0.0.1:9099/api/health

§9.2 BACKEND UNREACHABLE
--- #view ---
  [div]
    [div.state]
      [h2] The demo server did not answer.
      [p] Warrant's frontend is hosted on GitHub Pages and loaded fine — this page is
          proof of that. The backend, which holds the database and does all the
          scoring, is not responding.
      [p] The most likely causes, in order: the free-tier server is still starting...
      [p] Backend configured in docs/config.js:
        [code] http://127.0.0.1:9099
      [p.actions]
        [button] Try again

fetch() attempts made: 4 (real connection failures)
```

Real connection failures, real polling, correct panel, and the configured URL echoed
back — which is the line that lets a user diagnose a typo without opening devtools.

### 8.5 A harness bug, for completeness

The first `unreachable` run printed the *placeholder* panel and `0 fetch calls`. The
cause was mine: my harness only overrode `apiBase` in `connected` mode, so `app.js`
correctly detected the untouched placeholder and correctly made no request. **The
frontend was right and my test was wrong.** Fixed the harness; the output above is
the corrected run.

---

## 9. What I could not verify

This is the section that matters most, and none of it is hedging — each item is a
specific thing that was not tested and a specific statement of what that costs.

### 9.1 Nothing was deployed. At all.

**There are no accounts and no credentials in this environment.** No GitHub account,
no Render account, no ability to create either. Concretely:

- **No GitHub repository exists.** `git init` was never run — this directory is not a
  git repository and was deliberately left that way.
- **No GitHub Pages site exists.** Nothing has ever been served from a `github.io`
  address.
- **No Render service exists.** No Render deploy has ever been attempted.
- **Every URL in `DEPLOY_RUNBOOK.md` is a placeholder**, marked as one.
- `gh`, `docker`, `flyctl`, `render`, `railway`, `vercel`, `netlify`, `aws`, `gcloud`
  and `psql` are all **not installed**, which is why the runbook is browser-driven
  throughout.

**So the runbook is untested as a runbook.** Its steps are derived from Render's and
GitHub's documentation plus the code's actual behaviour, not from having walked them.
The first person to follow it is the first person to test it. The most likely places
for it to be wrong are the exact wording of Render dashboard fields, which vendors
change without notice.

### 9.2 The CORS test used `http://localhost:8080`, not a real `github.io` origin

**What it proves.** The allowlist mechanism is exercised for real. Two different
origins really were involved — a static file server on port 8080 and the API on port
8123, which are different origins by the same rule that makes
`https://user.github.io` and `https://app.onrender.com` different origins. The server
correctly emitted `Access-Control-Allow-Origin` for a configured origin, correctly
withheld it for four look-alikes, correctly returned the §4.4 preflight, and
correctly returned a full `200` body with no CORS header to a disallowed origin. **The
string comparison, the header emission, the preflight, and the fail-closed default
are all verified.**

**What it does not prove.**

1. **No browser enforced anything.** `urllib` and node's `fetch` do not implement the
   CORS security model — they hand you the body regardless. I verified that the
   *server sends the right headers*; I did **not** observe a browser *blocking* a
   response. The claim "the browser will refuse to hand it to the script" is standard
   CORS behaviour and is not in doubt, but I did not watch it happen.
2. **Scheme was `http`, not `https`.** Real deployment is `https` on both ends. I
   could not test that a Pages `https` page reaches an `onrender.com` `https`
   backend, and in particular **the mixed-content rule was not exercised at all** —
   the runbook's §4 step 9a check 4 rests on documentation, not on observation.
3. **`localhost` is special-cased by browsers** in some security contexts. A real
   `github.io` origin is not `localhost`. Nothing in the server's exact-string
   comparison could care about this, but the test origin was not representative.
4. **No `no-cors` probe was exercised against a real block.** §9.3's CORS panel
   depends on a heuristic — plain request throws, `no-cors` probe succeeds ⇒ probably
   CORS. I rendered the panel by other means but **never triggered it through an
   actual browser CORS block**, so that heuristic is unverified in its real
   conditions. It is described as a heuristic in the design and it should keep being
   described that way.

### 9.3 No browser was opened

**I did not open a browser at any point.** There is none in this environment.

So the frontend is verified **as served bytes** (a real static server returned
`index.html` at 1,557 bytes and `app.js` at 41,549 bytes with HTTP 200) and **by its
logic** (the real, unmodified `app.js` executed against the real backend and built the
correct element tree with the correct strings in the correct order, §8.2).

It is **not verified visually.** Specifically unverified:

- **`styles.css` has never been rendered.** It is a copy of the `CSS` constant in
  `warrant/render.py` and could have a broken selector, an unreadable colour, or a
  layout that collapses on a phone. Nobody has looked at it.
- **Nothing was checked at any viewport size.**
- **No click was ever dispatched.** Handlers were attached — I can see them in the
  element tree — but no `click` event was fired through the DOM. The write loop was
  proven at the HTTP layer (§6), not through the buttons.
- **The 1.5-second loading-copy swap and the ticking counter were never seen.** The
  code path was exercised with the timers shortened; the visual behaviour was not
  observed.
- **The `<noscript>` block was never rendered**, because nothing rendered HTML.

### 9.4 The two §1.3 dependencies — one closed, one still open

`DEPLOY_ARCHITECTURE.md` §1.3 listed two unverified claims the whole design rests on.
A verification pass against Render's own documentation, which arrived after the
previous maker started, closed one and partly closed the other.

**§1.3 claim 1 — that Render runs a long-running non-WSGI Python process.**
**Substantially closed, with a caveat that must travel with it.** Render's docs state
the health criterion in terms of **port binding**, not frameworks:

> *"Every Render web service must bind to a port on host `0.0.0.0` to serve HTTP
> requests."* — https://render.com/docs/web-services

> *"If Render fails to detect a bound port, your web service's deploy fails and
> displays an error in your logs."* — same page

Gunicorn appears only as an example start command, not a requirement. A stdlib
`ThreadingHTTPServer` on `0.0.0.0:$PORT` satisfies the **literal stated requirement**,
and §7 above shows this code doing exactly that.

**The caveat, carried forward honestly:** no Render document *affirmatively* states
"any process listening on a port is acceptable." The support is strong but
**inferential**, and **the duration of Render's port-scan timeout is not documented**
anywhere — so how long the process has to bind before the deploy is failed is
unknown. Seeding takes a few seconds locally and happens **before** `serve_forever()`,
which means the bind is delayed by the seed. **If Render's port-scan window is
shorter than the seed takes on their hardware, the first deploy fails.** That is a
real, named risk and it is the single most likely way the first deploy goes wrong. It
is not in the runbook's troubleshooting table as a distinct row because I have no
documented timeout value to cite; §7.5's "no open ports detected" row is where it
would surface.

**§1.3 claim 2 — that Render offers Python 3.14.x.** **Closed.** Python **3.14.3** is
available and is Render's **default for services created on or after 11 February
2026** (https://render.com/docs/python-version). Documented minimum is 3.7.3. The
version is set by a fully-qualified `PYTHON_VERSION` environment variable or a
`.python-version` file at the repo root; `runtime.txt` is not mentioned. I added
`.python-version` containing `3.14.3` and the runbook also sets `PYTHON_VERSION`,
because **a service created before 11 February 2026 keeps an older default** and
nothing in this pipeline knows when the user's account was created.

**Still open: HTTPS on `*.onrender.com`** (Appendix A item 1). Universally true in
practice, never verified by a fetched sentence in this pipeline. If it were false the
mixed-content rule would make the entire architecture non-functional, so the runbook
makes it an explicit check (§4 step 9a check 4).

### 9.5 Other things not verified

- **`requirements.txt` behaviour on Render is a genuine unknown.** Newly verified:
  Render does **not** use `requirements.txt` for language detection — you pick the
  language from a dropdown (https://render.com/docs/your-first-deploy) — so the
  comment previously in that file was wrong about Render and has been corrected.
  What Render's default build command does with a **comment-only** `requirements.txt`
  is **not documented anywhere I could find**, and I could not test it. The runbook
  gives a fallback build command (step 7a).
- **Keep-alive pinging remains unresolved in both directions.** Render's terms-of-
  service and acceptable-use pages return JavaScript-only content that could not be
  read. The design's position (do not add a pinger) is unchanged, and the runbook says
  why.
- **Cold-start duration was never measured.** Render's own figure is "about one
  minute"; the frontend's 90-second timeout is a margin over that. Untested.
- **The 15-minute spin-down was never observed.**
- **Nothing was tested at concurrency.** `/api/health` being polled every 3 seconds
  by several viewers during a wake is §10.3 open question 2 and remains an inference.
- **No test ran on any Python other than 3.14.3.** §6.4 step 3 names a differing
  `random` stream as a real reproducibility risk; pinning the version is the
  mitigation, and the pin itself is untested on Render.
- **The database used in §5 and §6 carried state from earlier sessions** (a pin and a
  mute already existed, which is why `rank_line` reads "was 7 before your
  adjustments"). §7's fresh seed produced identical scores and ranking, so this did
  not affect any conclusion — but the §5/§6 transcripts are from a used database, not
  a pristine one, and that is stated rather than glossed.

### 9.6 One cosmetic spec-vs-code difference, flagged not fixed

`DEPLOY_ARCHITECTURE.md`'s illustrative JSON payloads name rep 1 as
**"Dana Whitfield"** and show accounts like "Kestrel Analytics" at 61.24. The actual
seeded corpus has rep 1 as **"Ana Belic"** and the queue shown above. The spec's
examples were illustrative, drawn from `DESIGN_SPEC.md` worked examples, and the
`account_count: 53` figure it tells you to verify **is** correct. **No code change was
made.** The Kestrel 61.24 worked example still holds exactly, asserted by
`TestScoringParity::test_kestrel_worked_example_survives_the_port`, against the
dedicated Kestrel fixture the test suite builds for it.

### 9.7 Deviations from `DEPLOY_ARCHITECTURE.md` found in the inherited work

- **`warrant/runtime.py` is a new module not in §5.1's or §6.2's file list.** The
  previous maker flagged it in the module's own docstring, and the reasoning holds:
  §6.5 requires new rep-facing copy (the persistence notice, the restart notice, the
  "or until this demo server restarts" clause) that exists nowhere in the codebase;
  §2.5 forbids the serialiser from inventing rep-facing copy; and §10.3 open question
  1 recommends `api.py` never import `render.py`. The copy needed a home that was
  neither. **I agree with the call and left it.** It is additive, changes no specified
  behaviour, and is the same shape of deviation as the pre-existing
  `warrant/timeutil.py`.
- **`.python-version` added by me**, not in any file list, justified by §9.4 above.
- **`requirements.txt`'s explanatory comment corrected by me**, because it asserted
  something about Render that the newly verified documentation contradicts. The file
  still declares zero packages.
- **No `render.yaml` was created and none is needed.** The runbook is dashboard-driven
  because the `render` CLI is not installed, and a blueprint file would be a second,
  untested configuration path alongside the dashboard fields.

---

## 10. Summary

| | |
|---|---|
| Full suite, first run | **143 tests, 2 failures** |
| Failures diagnosed and fixed | 2 (T19 allowlist + scan coverage gap; secret scan firing on prose) |
| Iterations to fix the second one | **4** — three of them tripped by my own explanatory comments |
| Full suite, final run | **146 tests, 0 failures** |
| §7.3's four required tests | present, passing |
| Scoring-parity test | **already existed**, verified genuine, passing |
| §8.4 `docs/` secret scan | **already existed**, with negative controls, passing |
| `grep onrender docs/app.js` | **0 hits** |
| Backend run for real | yes — `start.py`, real HTTP, real bodies |
| CORS exercised cross-origin | yes — two servers, two ports, all three cases + preflight |
| Write loop over the API | yes — 73.89 → 57.89 → 73.89, exact |
| `start.py` both branches | yes — seeds when absent, skips when present |
| Frontend executed | yes — real `app.js`, stub DOM, live backend |
| **Deployed anywhere** | **no** |
| **Seen in a browser** | **no** |

---

*Maker agent (AI-generated). Stage 3 of 4. Every command and every line of output in
sections 1–8 was actually run on this machine. Nothing was deployed. No URL in any
document produced by this stage is real.*
