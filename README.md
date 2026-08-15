# Warrant

Warrant is a reason-first prioritisation layer for Unify: for every account in a
rep's patch it runs live SQL over signal, person and account data, computes an
additive evidence score from a published weight table, and generates 3–5
timestamped, sourced reasons — positive and negative — from the exact same
arithmetic that produced the score. Each reason states in one line what it is
*not* showing, and carries a one-click disagreement action that writes a row and
produces a bounded, expiring, reversible change to that rep's own queue. Nothing
a rep does affects another rep's queue or the global weight table.

Built from `DESIGN_SPEC.md` (11 Aug 2026), which is built from
`RESEARCH_BRIEF.md` (same date). Both are AI-generated.

---

## Setup and run

Python 3.14 (tested on 3.14.3), standard library only. No pip install, no
virtualenv needed, no network access required at any point.

```
python seed_db.py     # creates data/unify.db and generates the corpus
python app.py         # serves on http://127.0.0.1:8000
```

Then open **http://127.0.0.1:8000/queue?rep=1** (reps 1–4 exist).

Other routes: `/` · `/account/{id}?rep=1` · `/evidence/{reason_id}?rep=1` ·
`/adjustments?rep=1` · `/metrics` · `/ruleset`.

Tests:

```
python -m unittest discover tests
```

94 tests. On this machine they run in about 32 seconds and all pass; the actual
output, including the seven failures I hit on the way and how each was resolved,
is in `TEST_OUTPUT.md`.

### Environment variables

All configuration is environment variables, documented in `.env.example`. **There
are no credentials anywhere in this repo, and no placeholder credentials either —
Warrant talks to one local SQLite file and makes no outbound calls, so there is
nothing to authenticate to.**

| Variable | Default | What it does |
|---|---|---|
| `WARRANT_DB_PATH` | `data/unify.db` | SQLite file; relative paths resolve from the repo root |
| `WARRANT_PORT` | `8000` | HTTP port. Read first; if unset, the platform's `PORT` is used; only then `8000` |
| `WARRANT_BIND_HOST` | `127.0.0.1` | Interface to bind. Default is loopback only. A container sets `0.0.0.0` |
| `WARRANT_ALLOWED_ORIGINS` | *(empty)* | Comma-separated exact origins allowed to call `/api` from a browser. Empty means no CORS headers at all |
| `WARRANT_PERSISTENCE` | `persistent` | `ephemeral` makes every read response carry the data-loss notice |
| `WARRANT_FORCE_RESEED` | *(empty)* | `1` wipes the database at boot and regenerates it. Destructive |
| `WARRANT_SEED` | `20260811` | Seed for the data generator |
| `WARRANT_AS_OF` | `2026-08-11T09:00:00Z` | The evaluation instant for all decay arithmetic and all expiry checks |
| `WARRANT_RULESET_VERSION` | `warrant-v1.0.0` | Stamped on every run and every dispute |

Hosting the demo on a public URL is documented separately: `DEPLOY_ARCHITECTURE.md`
is the design, `DEPLOY_RUNBOOK.md` is the numbered procedure, and
`DEPLOY_TEST_OUTPUT.md` is what was actually run and what was not.

Nothing reads a `.env` file at runtime — `.env.example` is documentation of the
variable names, not a file the app parses.

---

## How the score works

Each of 19 signal types contributes points. For **event** signals:

```
decay        = 0.5 ** (age_days / half_life_days)
magnitude_f  = 1 + 0.5 * log10(magnitude)
contribution = base_weight * decay * magnitude_f
points       = sign(weight) * min(abs(sum of contributions), abs(cap))
```

For **state** signals (ICP industry, ICP headcount band, tech stack, and the
four disqualifier predicates) the points are the weight itself, with no decay.
Anything under 0.5 points is dropped entirely. The total is the signed sum, and
the band is a fixed threshold on it — `ACT_NOW` at 45, `REVIEW` at 25, `HOLD` at
5 — gated by a confidence cascade that can cost an account a band but can never
win it one.

The weights are not in the Python. They live in the `signal_types` table and are
published at `/ruleset`; there is a test that changes a weight with raw SQL and
asserts the arithmetic moves. The reasons on screen are rendered from the same
list of contributions that were summed to produce the score, which is why
`sum(all reason points) == score.points` holds exactly for every account (test
T07). There is no separate "explainer" model that could drift from the decision.

### What it does NOT claim

**It is not a probability of closing.** It is not calibrated against closed-won
outcomes, because there is no outcome data here to calibrate against. It is a
weighted count of evidence, nothing more.

It is also not a percentile and not a 0–100 normalised score. Points are shown
against a fixed published anchor of 75 so that "60 pts" has a referent, and the
anchor is used in no arithmetic. Confidence is rendered as a bare word, never a
percentage — a second uncalibrated number on a page that already spent its
credibility budget on the first one.

Every warrant carries a one-line disclosure of what it withheld, e.g.
*"Showing the 5 strongest of 11 signals. The 6 not shown are worth +50.3 pts
combined; they do not change the band."* Rendering a detail view without one is
a test failure (T09).

18 of the 19 weights are **reasoned, not measured**. Only `product_usage_active`
traces to evidence — Unify's published 9.1% positive-reply benchmark. `/ruleset`
says so on the page.

---

## Where the live data is, and how it is queried

The data source is a real SQLite database at **`data/unify.db`**, created and
populated by `seed_db.py`. It holds 4 reps, 240 accounts, ~1,350 people, ~6,900
signal events, ~470 agent observations and ~880 instrumentation events.

**Every score is computed from live SQL at request time.** `GET /queue?rep=1`
creates a new `score_runs` row, then for each account in the rep's patch calls
`score_account()`, which issues fresh `SELECT`s against `signal_events`,
`people`, `accounts` and `signal_types` and does the §4.2 arithmetic on the rows
it gets back. There is no cache, no memoisation and no precomputed score literal
anywhere in `warrant/` or `app.py`. `GET /account/{id}` re-runs the whole thing,
which is what makes a dispute visible on the very next render.

Three tests prove this rather than asserting it: they mutate `signal_events`,
delete rows, and change a weight in `signal_types` using a *separate raw
`sqlite3` connection* the application knows nothing about, then re-score and
assert the output moved by the expected amount.

**No lead data is hardcoded.** There is no literal list of accounts, people or
events in `warrant/` or `app.py`. The seeder generates all of it from the §3
distributions under `random.seed(20260811)`; running it twice produces
byte-identical `accounts`, `people` and `signal_events` (T01). The one place
literal rows are written is the 19-row `signal_types` table in `seed_db.py` —
that is the model definition, which the spec explicitly wants living in data.
The Kestrel fixture in `tests/support.py` is also literal, because it is the
spec's own §4.4 worked example; nothing in the application reads it.

All SQL parameters are bound with `?` placeholders. T20 walks the AST of every
`.py` file in the repo and fails on any `execute()` whose first argument is an
f-string, a `%`/`+` concatenation or a `.format()` call.

---

## Deviations from the spec

Twelve. The first three are the ones that change a number a reader of the spec
would expect.

### 1. `tech_stack_match` — §4.1 contradicts §4.4, so Kestrel totals 61.24, not 59.87

§4.1's weight table defines `tech_stack_match` as `kind='state'`, weight = cap =
`+5.0`, **no half-life** — and states that state signals have no decay and no
magnitude factor. That gives **+5.00**.

§4.4's worked example instead treats it as a decayed event: *"1 event,
2026-05-20, `0.5^(83/180)=0.7264`, **+3.63**"*, using a 180-day half-life that
appears nowhere in §4.1.

**I followed §4.1**, because §3.4 says that table seeds `signal_types` verbatim
and it is the normative definition of the model. Consequences:

| Spec says | This build | Why |
|---|---|---|
| T02: `points == 59.87` | **61.24** | +1.37, exactly 5.00 − 3.63 |
| T14: post-dispute `44.92` | **46.29** | same 61.24 − 14.95 |
| T15: revert restores `59.87` | **61.24** | same |
| §4.6 withheld sum `+25.6 pts` | **+27.0 pts** | same |
| §4.5 rank 10 = `tech_stack_match` | rank 9 | +5.00 outranks +4.16 |

**Every other component of §4.4 reproduces to the cent** — including the capped
+24.00, the +14.95, the +9.36, the −7.24 and the −6.78 — and the band
(`ACT_NOW`), confidence (`high`), distinct type count (10) and completeness
(1.00) are all exactly as printed. The shown set is still ranks 1–5 and
`champion_departed` (−7.24) is still shown while `icp_industry_match` (+6.00) is
not, so T06 holds unchanged. A dedicated test,
`test_discrepancy_is_isolated_to_tech_stack_match`, substitutes §4.4's own
+3.63 back in and asserts the total returns to exactly 59.87 — proving the gap is
this one signal and nothing else. Full working in `TEST_OUTPUT.md` §0.

*Suggested resolution for the design stage: decide whether `tech_stack_match` is
a state predicate over `accounts.tech_stack` (as §4.1 says) or an event-backed
signal with a 180-day half-life (as §4.4 says), and correct the other section.*

### 2. Confidence at exactly 2 signal types — §8.1 contradicts §8.7

§8.1 says 1 **or 2** signal types → `insufficient`. §8.7's cascade says
`insufficient if distinct_signal_types < 2`, and then on the very next line
`low if ... distinct_signal_types == 2`. Both cannot be true: under §8.1's
reading the `== 2` clause in §8.7 is unreachable dead code.

**I followed §8.7**, the mechanical cascade the spec calls "evaluated top to
bottom, first match wins". An account with exactly 2 signal types gets `low`,
not `insufficient`. The protection §8.1 actually cares about is preserved: `low`
confidence blocks `ACT_NOW` via the §4.2 band gate, so a thin account still
cannot be presented as a certainty. Asserted in
`test_thin_accounts_are_never_act_now_and_are_never_padded`.

### 3. §4.5's truncation rule cannot reach its own floor of 3 for all-negative accounts

Implemented exactly as the pseudocode is written. Step 1 takes `P[:3]`, step 2
takes `N[:2]`, step 3 backfills **"from positives only"**. So an account with
zero positive reasons can never show more than the 2 reserved negative slots,
and the stated "floor of 3 where 3 exist" is unreachable for it. **2 of 233
seeded accounts hit this** (both all-negative, 5 and 3 reasons, showing 2).

I did not add a negative-backfill branch, because inventing a fix to a specified
algorithm is a redesign, not a build decision. The behaviour is asserted as-is
in T05 and named there.

*Suggested resolution: change step 3 to backfill from the ranked remainder
rather than from positives only, keeping the 4-positive sub-cap.*

### 4. `signal_events` volume — §3.5's formula and its stated total disagree

§3.5 gives `int(random.paretovariate(1.3))` clamped 0–90, and separately asks
for **≈6,500 events**. That formula has a mean near 4.3, which over 240 accounts
yields ~1,000, not 6,500. I added an explicit `EVENT_SCALE = 19.4` multiplier
inside the clamp and tuned it to land on the stated total (actual: 6,916). The
Zipf-like shape and the 0–90 clamp are unchanged.

### 5. The §8.3 "no signal at all" cohort had to be constructed explicitly

The 19 zero-*event* accounts §3.5 specifies still matched the fit predicates off
their firmographics and scored +17, so §8.3's case — *"zero events, zero firing
state signals"* — was never reachable. The seeder now carves out an 8-account
`zero_signal` cohort with `industry`, `employee_count` and `tech_stack` NULL,
`crm_status='none'`, and a guaranteed director-level contact so
`no_buying_authority_present` does not fire either. Without this the §8.3 edge
case could not be tested.

### 6. Added `warrant/timeutil.py`, not in the §9.1 file list

`seed_db.py`, `scoring.py`, `reasons.py` and `render.py` all need identical
ISO-8601 handling and relative-date formatting. Duplicating it four ways is the
fastest route to the arithmetic and the rendered dates disagreeing. Additive
only; no specified behaviour changed.

### 7. Three added columns on `reasons`

`points_before_adjustment`, `is_suppressed`, `cap_applied`. §7.4 requires a
disputed reason to render struck through, in its original slot, showing
`+15 → 0 pts`; that needs the pre-adjustment value and a suppression flag
persisted. `cap_applied` drives the `(capped at 24)` disclosure §6.2 requires.
`reasons.points` still holds the effective value that T07 sums.

### 8. "This session" for the friction gate

§6.4 says the `Work it` button re-enables once an `evidence_opened` event exists
for this `(rep, account, run)`. But a new run is created on *every* render,
including the one that follows opening the drawer, so scoping to `run` would
make the gate impossible to clear. I read it as: an `evidence_opened` event at
or after the current `as_of`. Verified working end to end in `TEST_OUTPUT.md` §6.

### 9. §6.4 clause (a) is structurally unreachable in the running app

The predicate `crm_status='open_opportunity' AND owner_rep_id != rep_id` is
implemented and unit-tested (T18 passes), but the queue is filtered to
`owner_rep_id = rep_id`, so an open opportunity owned by *another* rep is never
in the queue to be gated. In the running app only clause (b), the open-dispute
clause, ever fires — 3 of 53 items, 5.7%, inside the 4–6% §6.4 predicts. Not
changed, because widening the queue to include other reps' or unassigned
accounts is a product decision.

### 10. A scoring run is created on `GET /account/{id}` as well as `GET /queue`

§3.7 says a run is created on every `GET /queue`. §7.4 requires a dispute to be
visible on the very next render of the detail view, with a correct
`rank_in_queue`. Both are satisfiable only by re-scoring the whole patch on the
detail view too, so that is what happens. Runs are still never mutated.

### 11. Server-side enforcement of the friction gate, and item-level `WRONG_PERSON`

- §6.4 specifies a *disabled button*. A disabled button is not enforcement, so
  `POST /task` with `action=accepted` also returns **409** when the gate applies.
  Strictly additional.
- §7.2 maps `WRONG_PERSON` to `exclude_person`, which requires a `person_id`. On
  an account with no contacts on file there is nobody to exclude, so the control
  is **not rendered** and the API refuses rather than guessing which human the
  rep meant. `test_wrong_person_without_a_person_is_refused_not_guessed`.

### 12. Two small wording changes in `render.py`

- The detail heading is *"Why this is at the top"* only for ranks 1–3; below
  that it reads *"Why this ranked 47"*. Calling a rank-47 item top-of-queue is
  the kind of small overclaim §4.6 exists to prevent.
- §8.5's conflict-line template does **not** lowercase the leading word of the
  negative clause, because reason templates often start with a person's name and
  *"but noor Belic, our contact here, left"* reads as a typo.

### Metric definitions the spec left open

Not deviations so much as decisions the spec did not make. Both are in
`warrant/metrics.py` with comments: top-3 acceptance uses distinct
`(rep, account)` pairs from `task_events` for both numerator and denominator
(the only table recording what rank a rep saw when they acted); and
"skip with no dispute" reads *"same session"* as a dispute by the same rep on the
same account within one hour of the skip.

---

## Honest limitations

1. **The Kestrel total is 61.24, not the 59.87 printed in the spec.** Deviation
   1 above. This is the single thing most likely to look like a bug to a reader
   of the spec, so it is stated first here and first in `TEST_OUTPUT.md`.
2. **No browser was used.** Every view was fetched over HTTP and verified as
   text. Content and element ordering match §6; visual layout is unverified.
3. **The `/ruleset` REVIEW REQUIRED flag is unreliable at small n.** §7.5's rule
   is ">20% of the reps who saw it, over ≥30 shows". The shows denominator is
   large but the *rep* denominator is the number of reps who have loaded a queue
   — currently 1. One dispute by one rep therefore reads "1 of 1 reps have
   disputed this" and flags. The rule needs a minimum-rep threshold before it
   means anything.
4. **`/metrics` numbers are computed by live SQL over synthetic instrumentation.**
   The arithmetic is real; the inputs are seeded. The rates mean nothing yet, and
   the page says so: *"no target set; v1 establishes baseline"*.
5. **Per-signal-type show counts on `/metrics` only exist once someone has loaded
   a queue,** because they are counted from `reasons` rows written by real runs.
   On a freshly seeded database that table renders `—` until `/queue` is hit.
6. **Concurrency is untested.** `ThreadingHTTPServer` with a connection per
   request; SQLite will serialise writers with default locking. Real load would
   need WAL mode and a retry policy. Writing a full run on every page view also
   grows the database steadily — fine for a demo, not a production pattern.
7. **Duplicate adjustments are not deduplicated.** Pinning an already-pinned
   account creates a second pin and consumes a second unit of the budget of 5.
   The spec does not address this.
8. **18 of 19 weights are reasoned, not measured**, and no part of this model is
   calibrated against outcomes. The instrument for fixing that is `/metrics`
   plus a human RevOps decision; it is not automated, deliberately.
9. **The reason templates are the designer's composition, not a rep's.** The
   spec's own open question #2. They are structurally correct — qualification
   vocabulary, consequence-bearing, no banned marketing language (T11 checks
   >2,000 rendered strings) — but they have never been read by a salesperson.
10. **`no_engagement_90d` and the other machine `code` values appear on
    `/ruleset`,** so the literal string "engagement" is present on that page.
    T11's banned-vocabulary check covers reason text, evidence lines, band
    labels, limits lines and chips — exactly the surfaces §9.3 names — and
    deliberately not the RevOps identifier column. Worth a design decision.
11. **`source_url` values are rendered as selectable text, never as links,**
    because there is no outbound network here and a link that 404s in a demo is
    worse than no link. The evidence drawer says so on the page.
