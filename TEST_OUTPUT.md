# TEST_OUTPUT.md — what was actually run, and what actually happened

Build stage, Warrant. Everything below is pasted terminal output from this
machine (Windows 11, Python 3.14.3, SQLite 3.50.4). Where something broke, the
failure is shown before the fix. Nothing here is reconstructed from memory.

Working directory for every command: `C:\Users\DELL Lattitude\Documents\Unify Agent Test`

---

## 0. Before writing any code: checking the spec's own arithmetic

The §4.4 Kestrel worked example is the load-bearing number in the whole build
(T02), so I recomputed every line of it from the §4.2 formula before writing a
scorer, rather than writing a scorer and then trusting whatever it produced.

```
$ python -c "
from math import log10
def c(w,hl,age,mag):
    return w*(0.5**(age/hl))*(1.0+0.5*log10(max(mag,1.0)))
pu=[c(12,14,2,14),c(12,14,7,9),c(12,14,14,5)]
print('product_usage raw',round(sum(pu),2),[round(x,2) for x in pu])
pp=[c(9,10,2,2),c(9,10,6,1)]
print('pricing raw',round(sum(pp),2),[round(x,2) for x in pp])
print('senior',round(c(10,21,2,1),2))
print('newhire',round(c(8,60,28,1),2))
print('tech as event hl180 age83',round(c(5,180,83,1),2))
print('6sense',round(c(4,14,10,1)+c(4,14,17,1),2))
print('champ_dep',round(c(-10,90,42,1),2))
print('unsub',round(c(-9,365,149,1),2))
tot_specA = 24.00+14.95+9.36+5.79+6.00+6.00+3.63+4.16-7.24-6.78
tot_specB = 24.00+14.95+9.36+5.79+6.00+6.00+5.00+4.16-7.24-6.78
print('total with tech as decayed event:',round(tot_specA,2))
print('total with tech as state +5.00 :',round(tot_specB,2))
"

product_usage raw 37.73 [17.1, 12.53, 8.1]
pricing raw 14.95 [9.01, 5.94]
senior 9.36
newhire 5.79
tech as event hl180 age83 3.63
6sense 4.16
champ_dep -7.24
unsub -6.78
total with tech as decayed event: 59.87
total with tech as state +5.00 : 61.24
```

**Finding.** Every component of §4.4 reproduces to the cent. But the spec is
internally inconsistent about exactly one signal type:

- **§4.1** (the normative weight table) defines `tech_stack_match` as
  `kind='state'`, `weight = cap = +5.0`, **no half-life** — state signals get no
  decay and no magnitude factor. That yields **+5.00**.
- **§4.4** (the worked example) instead lists it as *"1 event, 2026-05-20,
  `0.5^(83/180)=0.7264`, **+3.63**"* — i.e. a decayed event with a 180-day
  half-life that appears nowhere in §4.1.

The difference, 5.00 − 3.63 = 1.37, is **the entire gap** between the spec's
printed total of 59.87 and this build's 61.24. I followed §4.1, because it is
the table the spec says seeds `signal_types` verbatim, and because §4.1's own
"Positive — FIT" heading explicitly says these three are `kind='state'`, no
decay. This is recorded in `README.md` under *Deviations from the spec*, and
there is a test (`test_discrepancy_is_isolated_to_tech_stack_match`) that proves
the discrepancy is confined to this one signal and nothing else.

I did **not** change the test to match the code. I changed nothing about the
arithmetic; I documented which of the spec's two contradictory statements I
followed and why.

---

## 1. `python seed_db.py`

### First run — worked, but two volumes were off

```
$ python seed_db.py
Seeded C:\Users\DELL Lattitude\Documents\Unify Agent Test\data\unify.db
  as_of            : 2026-08-11T09:00:00Z
  ruleset          : warrant-v1.0.0
  reps             : 4
  signal_types     : 19  (reference data, seeded verbatim from spec 4.1)
  accounts         : 240  (7 inactive)
  people           : 1375
  signal_events    : 2891
  observations     : 510  (74 accounts with none)
  task_events      : 1548
  ...
```

Two mismatches against §3.5 / §3.12:

- `signal_events` came out at **2,891**, but §3.5 asks for **≈6,500**. The
  literal formula in §3.5 — `int(random.paretovariate(1.3))` clamped 0–90 —
  has a mean of about 4.3 per account, which over 240 accounts is ~1,000, not
  6,500. The two halves of §3.5 do not agree with each other. I added an
  explicit `EVENT_SCALE` multiplier and tuned it to hit the stated total while
  keeping the Zipf-like shape. Recorded as a deviation.
- `task_events` came out at 1,548 against a target of ≈900; I reduced the
  per-rep loop counts.

### Final run

```
$ python seed_db.py
Seeded C:\Users\DELL Lattitude\Documents\Unify Agent Test\data\unify.db
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
```

The file is real and is a real SQLite database:

```
$ python -c "print(open('data/unify.db','rb').read(15))"
b'SQLite format 3'
```

---

## 2. First end-to-end scoring smoke test

Before building any UI, I ran the scorer against the seeded DB to see whether it
produced anything sane and whether T07 held.

```
$ python - <<'EOF'
import time
from warrant.db import connect, as_of
from warrant.queue import build_run
conn = connect()
t0=time.time()
run_id, items, adj = build_run(conn, 1, as_of())
print("run", run_id, "items", len(items), "in %.2fs" % (time.time()-t0))
...
EOF

run 1 items 53 in 0.21s
 1. [ACT_NOW] Cobalt Freight                95.01 pts  conf=high   types=13 flags=['pinned']
      Security Manager and 4 others used the product across 6 sessions, most recently today.
     LIMITS: Showing the 5 strongest of 13 signals. The 8 not shown are worth +41.0 pts combined; they do not change the band.
 2. [ACT_NOW] Quarry Partners              116.00 pts  conf=high   types=10 flags=[]
      Founder and 5 others used the product across 9 sessions, most recently today.
     LIMITS: Showing the 5 strongest of 10 signals. The 5 not shown are worth +45.0 pts combined; they do not change the band.
 3. [ACT_NOW] Kestrel Group                102.24 pts  conf=high   types=9 flags=[]
      RevOps Manager and 7 others used the product across 13 sessions, most recently yesterday.
     LIMITS: Showing the 4 strongest of 9 signals. The 5 not shown are worth +33.2 pts combined; they do not change the band.
 ...
T07 mismatches: 0 of 53
```

Rank 1 sitting at 95 pts above a 116-pt account is correct — it is pinned, and
§7.3 says pinned accounts occupy ranks 1..k. Row 3 showing "4 strongest of 9" is
also correct: it has no negative reasons, and §4.5's sub-cap holds the shown set
to 4 positives rather than filling the reserved fifth slot.

---

## 3. Kestrel worked example against the real scorer

```
$ python - <<'EOF'
import sys; sys.path.insert(0,"tests")
import support
path, conn = support.build_kestrel_db()
s = support.kestrel_score(conn)
for c in sorted(s.contributions, key=lambda c: -abs(c.points_before_adjustment)):
    print("%-28s %8.2f  kind=%-5s cap=%s" % (c.code, c.points, c.kind, c.cap_applied))
print("TOTAL", s.points, s.band, s.confidence, "types", s.distinct_signal_types,
      "completeness", s.data_completeness, "conflicted", s.conflicted)
EOF

product_usage_active            24.00  kind=event cap=True
pricing_page_repeat             14.95  kind=event cap=False
senior_buyer_engaged             9.36  kind=event cap=False
champion_departed               -7.24  kind=event cap=False
unsubscribed_or_bounced         -6.78  kind=event cap=False
icp_industry_match               6.00  kind=state cap=False
icp_size_match                   6.00  kind=state cap=False
new_hire_icp_role                5.79  kind=event cap=False
tech_stack_match                 5.00  kind=state cap=False
third_party_intent_6sense        4.16  kind=event cap=False
TOTAL 61.24 ACT_NOW high types 10 completeness 1.0 conflicted True
```

Compare against §4.4 / §4.5:

| spec §4.5 rank | code | spec points | this build | match |
|---|---|---|---|---|
| 1 | `product_usage_active` | +24.00 | +24.00 | yes (raw 37.73, capped — T03) |
| 2 | `pricing_page_repeat` | +14.95 | +14.95 | yes |
| 3 | `senior_buyer_engaged` | +9.36 | +9.36 | yes |
| 4 | `champion_departed` | −7.24 | −7.24 | yes |
| 5 | `unsubscribed_or_bounced` | −6.78 | −6.78 | yes |
| 6 | `icp_industry_match` | +6.00 | +6.00 | yes |
| 7 | `icp_size_match` | +6.00 | +6.00 | yes |
| 8 | `new_hire_icp_role` | +5.79 | +5.79 | yes |
| 9 | `third_party_intent_6sense` | +4.16 | +4.16 | yes |
| 10 | `tech_stack_match` | +3.63 | **+5.00** | **no — the §4.1/§4.4 conflict above** |

Band `ACT_NOW`, confidence `high`, 10 distinct signal types, completeness 1.00 —
all exactly as §4.4 states. Only the total differs, by exactly 1.37.

---

## 4. `python -m unittest discover tests`

### First full run — 7 failures

```
$ python -X utf8 -m unittest discover tests -v
...
Ran 93 tests in 28.503s
FAILED (failures=7)

FAIL: test_thin_accounts_are_insufficient_and_are_not_padded (test_edge_cases.TestT17EdgeCases...)
FAIL: test_zero_event_account_is_insufficient_and_still_gets_a_row (test_edge_cases.TestT17EdgeCases...)
FAIL: test_zero_signal_accounts_are_still_persisted_in_a_run (test_edge_cases.TestT17EdgeCases...)
FAIL: test_a_new_events_after_a_dispute_do_not_auto_unsuppress (test_edge_cases.TestT17bDisputedLeadSubCases...)
FAIL: test_no_credential_shaped_string_in_the_repo (test_queue.TestNoSecrets...)
FAIL: test_no_execute_call_interpolates_a_value (test_queue.TestT20NoInterpolatedSQL...)
FAIL: test_zero_signal_account_yields_no_signals_found (test_reasons.TestT08LimitsLine...)
```

What each one actually was, and what I did:

**(a) No zero-signal accounts existed in the corpus — a seeder bug.**

```
AssertionError: 0 not greater than 0 : no zero-signal account in the corpus
```

The seeder produced the 19 zero-*event* accounts §3.5 asks for, but §8.3 defines
the case as *"zero events, **zero firing state signals**"*. Those 19 accounts
still matched `icp_industry_match`, `icp_size_match` and `tech_stack_match` off
their firmographics, so they scored +17 and the §8.3 case was never reachable.
Fixed in `seed_db.py` by carving an explicit `zero_signal` cohort out of the
zero-event cohort with `industry`, `employee_count` and `tech_stack` all NULL,
`crm_status='none'`, and a guaranteed director-level contact so
`no_buying_authority_present` does not fire either. 8 accounts.

**(b) Thin data: `'low' != 'insufficient'` — a genuine conflict inside the spec.**

```
AssertionError: 'low' != 'insufficient'
```

§8.1 says 1 **or 2** signal types → `insufficient`. §8.7's cascade says
`insufficient if distinct_signal_types < 2` and then, on the very next line,
`low if ... distinct_signal_types == 2`. Both cannot hold: under §8.1's reading
the `== 2` clause in §8.7 is unreachable dead code. I followed §8.7, the
mechanical cascade the spec calls "evaluated top to bottom, first match wins",
and changed the test to assert what §8.1 actually cares about — that a thin
account can never be presented as a certainty. It cannot: `low` confidence
blocks `ACT_NOW` through the §4.2 band gate. Recorded as a deviation.

**(c) and (d) My own test files tripped my own detectors. Both detectors were right.**

```
AssertionError: [('...tests\\test_scoring.py', 23, '%/+ interpolation')] != []
```
T20 caught `a.execute("SELECT * FROM %s" % table)` in my T01 reproducibility
test. Table names cannot be bound parameters, so I unrolled it into three
literal statements. The build code was already clean; the test file was the
only offender.

```
AssertionError: [('tests\\test_queue.py', '<pattern 1>'), ('tests\\test_queue.py', '<pattern 2>'), ...]
```
The secret-scanner scans `tests/` too, and found its own list of credential
patterns. Rather than exclude the file (which would have created a blind spot),
I assemble the patterns from string fragments so the scan still covers the
scanner.

*(The two matched tokens are redacted above as `<pattern 1>` / `<pattern 2>`.
Pasting them verbatim into this file made the same scanner fail again on
`TEST_OUTPUT.md` — which I only found because the suite went red after I wrote
this document. The scanner covers `.md` files too, and that is correct
behaviour, so the quote is redacted rather than the scanner narrowed.)*

**(e) `AssertionError: 2 != 1` — my assertion was wrong, the code was right.**
`new_events_since_dispute` counted 2 pricing events after a dispute dated 3 days
before `as_of`: the pre-existing 9 Aug visit plus the one I inserted for 10 Aug.
That is correct behaviour. I fixed the expectation and made the test
cross-check its own number with a direct SQL count.

### Second run — 1 failure, and it found a hole in the spec

```
Ran 94 tests in 30.511s
FAILED (failures=1)

FAIL: test_truncation_rule_holds_for_every_account
AssertionError: 2 not greater than or equal to 3 : account 144 has 5 reasons but shows 2
```

```
$ python - <<'EOF'   # how widespread is it?
accounts where the shown-floor of 3 is not reached: 2
  account=144 total=5 shown=2 positives=0 negatives=5
  account=180 total=3 shown=2 positives=0 negatives=3
EOF
```

This is a real gap in §4.5's own pseudocode, not a coding error. Step 1 takes
`P[:3]`, step 2 takes `N[:2]`, and step 3 backfills **"from positives only"**.
An account with zero positive reasons can therefore never show more than the 2
reserved negative slots, so the stated "floor of 3 where 3 exist" is unreachable
for it. 2 of 233 seeded accounts hit this.

I implemented the rule exactly as written rather than quietly adding a
negative-backfill branch — inventing a fix to a specified algorithm is a
redesign, and redesign is not mine to do unasked. The test now asserts the real
specified behaviour and names the gap. It is in `README.md` under *Deviations*
with a one-line suggested fix for the design stage.

### Final run — all green

```
$ python -X utf8 -W ignore::ResourceWarning -m unittest discover tests
..............................................................................................
----------------------------------------------------------------------
Ran 94 tests in 32.144s

OK
```

**94 tests, 94 passed, 0 failed, 0 errored, 0 skipped.**

Selected verbose output, so the coverage is visible rather than asserted:

```
test_T02_total_band_and_confidence ... ok
test_T03_product_usage_is_capped ... ok
test_discrepancy_is_isolated_to_tech_stack_match
  Substituting §4.4's own tech_stack_match figure reproduces 59.87. ... ok
test_every_component_matches_spec_4_4 ... ok
test_magnitude_factor_matches_the_published_curve ... ok
test_below_floor_signal_is_dropped_entirely ... ok
test_reasons_sum_to_points_across_the_whole_corpus ... ok
test_persisted_reason_rows_also_sum_to_the_persisted_score
  The same guarantee, asserted against what actually landed in the DB ... ok
test_seed_is_reproducible ... ok
test_mutating_a_magnitude_changes_the_score ... ok
test_deleting_events_removes_the_reason ... ok
test_changing_the_weight_table_changes_the_arithmetic
  The weights live in data, not in Python constants (§3.4). Prove it. ... ok
test_truncation_rule_holds_for_every_account ... ok
test_shown_set_is_exactly_ranks_1_to_5 ... ok
test_negative_at_minus_7_24_beats_positive_at_plus_6_00 ... ok
test_kestrel_yields_the_band_flip_variant ... ok
test_zero_signal_account_yields_no_signals_found ... ok
test_every_rendered_detail_view_carries_a_limits_line ... ok
test_no_banned_word_in_any_rendered_string_in_the_corpus ... ok
test_patch_wide_suppression_does_not_cross_reps ... ok
test_pin_budget_is_five ... ok
test_demote_budget_is_ten ... ok
test_mute_budget_is_twentyfive ... ok
test_patch_wide_suppression_budget_is_three ... ok
test_account_scoped_suppression_budget_is_fifty ... ok
test_exclude_person_budget_is_fifty ... ok
test_expired_suppression_does_not_change_points_or_order ... ok
test_no_adjustment_can_be_created_without_an_expiry ... ok
test_dispute_writes_exactly_one_row_of_each_kind ... ok
test_next_run_drops_the_points_by_exactly_the_reason_value ... ok
test_disputed_reason_stays_on_screen_struck_through_in_its_slot ... ok
test_revert_restores_points_and_status ... ok
test_all_seven_codes_create_an_adjustment ... ok
test_leave_it_writes_a_reviewed_row_and_no_adjustment ... ok
test_wrong_person_without_a_person_is_refused_not_guessed ... ok
test_exclude_person_removes_only_that_persons_events ... ok
test_zero_event_account_is_insufficient_and_still_gets_a_row ... ok
test_no_engagement_90d_does_not_fire_on_a_brand_new_account ... ok
test_no_buying_authority_does_not_fire_with_zero_people ... ok
test_stale_accounts_never_render_act_now ... ok
test_conflicting_accounts_render_the_disagree_line ... ok
test_brand_new_accounts_are_capped_at_medium_confidence ... ok
test_true_for_an_open_opportunity_owned_by_another_rep ... ok
test_false_for_a_plain_account_with_no_dispute ... ok
test_true_once_the_rep_has_an_open_dispute_on_the_account ... ok
test_every_python_file_imports_only_stdlib_or_local ... ok
test_no_execute_call_interpolates_a_value ... ok
test_the_detector_actually_catches_bad_sql
  Negative control — if this passes, the test above means something. ... ok
test_no_credential_shaped_string_in_the_repo ... ok
test_no_rep_facing_module_writes_signal_types ... ok
test_no_expander_exists_anywhere_in_the_rendered_html ... ok
```

### Test-ID coverage against §9.3

| ID | Covered by | Status |
|---|---|---|
| T01 | `test_seed_is_reproducible`, `test_seeded_corpus_has_the_forced_cohorts` | pass |
| T02 | `test_T02_total_band_and_confidence` + `test_every_component_matches_spec_4_4` | pass, with the documented 61.24 vs 59.87 deviation |
| T03 | `test_T03_product_usage_is_capped` (raw 37.73 → 24.00) | pass |
| T04 | `test_below_floor_signal_is_dropped_entirely` | pass |
| T05 | `test_truncation_rule_holds_for_every_account` (233 accounts) | pass, with the all-negative gap documented |
| T06 | `test_shown_set_is_exactly_ranks_1_to_5`, `test_negative_at_minus_7_24_beats_positive_at_plus_6_00` | pass |
| T07 | `test_reasons_sum_to_points_across_the_whole_corpus` + `..._persisted_...` | pass |
| T08 | 4 tests in `TestT08LimitsLine` (all three variants + the §8.3 case) | pass |
| T09 | `test_every_rendered_detail_view_carries_a_limits_line`, `test_rendered_html_contains_the_limits_block` | pass |
| T10 | `test_patch_wide_suppression_does_not_cross_reps` | pass |
| T11 | `test_no_banned_word_in_any_rendered_string_in_the_corpus` (>2,000 strings) | pass |
| T12 | 7 tests in `TestT12BudgetEnforcement` (all six budget keys) | pass |
| T13 | 3 tests in `TestT13Expiry` | pass |
| T14 | 6 tests in `TestT14DisputeEffect` | pass, expected total 46.29 not 44.92 (same deviation) |
| T15 | `test_revert_restores_points_and_status` | pass, restores to 61.24 |
| T16 | 7 tests in `TestT16NoCodeIsANoOp` | pass |
| T17 | 15 tests in `TestT17EdgeCases` + `TestT17bDisputedLeadSubCases` | pass |
| T18 | 4 tests in `TestT18Friction` | pass |
| T19 | `test_every_python_file_imports_only_stdlib_or_local` | pass |
| T20 | `test_no_execute_call_interpolates_a_value` + negative control | pass |

---

## 5. `python app.py` — the server, actually hit

```
$ python app.py
warrant-app build-marker 2026-08-11 · live SQL per request, no cache
Warrant listening on http://127.0.0.1:8000/queue?rep=1
as_of=2026-08-11T09:00:00Z ruleset=warrant-v1.0.0
```

The build marker on line 1 is deliberate. I have been burned before by a fix
that "deployed" while the old behaviour kept showing up, so every run prints a
visible marker proving which code is answering before I trust a single result
from it.

### Every route, status and payload size

```
GET /                      -> HTTP 200    3348 bytes
GET /queue?rep=1           -> HTTP 200   58679 bytes
GET /queue?rep=2           -> HTTP 200   58817 bytes
GET /metrics               -> HTTP 200    6948 bytes
GET /ruleset               -> HTTP 200    8275 bytes
GET /adjustments?rep=1     -> HTTP 200    5080 bytes
GET /account/218?rep=1     -> HTTP 200   11512 bytes | 105 pts
GET /evidence/755?rep=1    -> HTTP 200    6286 bytes

POST /dispute      -> HTTP 303 -> /account/218?rep=1&disputed=13
  after dispute: 81 pts
POST /adjust/revert -> HTTP 303 -> /account/218?rep=1&reverted=14
  after revert : 105 pts
POST /task          -> HTTP 303 -> /queue?rep=1
POST /adjust        -> HTTP 303 -> /account/218?rep=1&adjusted=15
```

### `GET /queue?rep=1` (rendered to text)

```
Warrant · Ana Belic · NA-MidMarket
Scored 11 Aug 2026 09:00 UTC · ruleset warrant-v1.0.0 · 53 accounts · run #2
Your adjustments: pins 1/5 · demotes 1/10 · patch-wide signal suppressions 0/3 · muted accounts 1/25
74 pts 1. ACT NOW Cobalt Freight PINNED BY YOU
    Cobalt Freight hired Keiko Bhattacharya as Data Engineer on 10 Aug 2026 — new owners re-open decisions.
    evidence 0d old                                    5 of 10 signals shown
    ( Work it ) ( Not now ) Dispute
105 pts 2. ACT NOW Harbour Technologies
    CMO and 3 others used the product across 5 sessions, most recently 7 days ago.
    evidence 0d old                                    5 of 11 signals shown
    ( Work it ) ( Not now ) Dispute
94 pts 3. REVIEW Yarrow Partners
    Product Manager and 1 other used the product across 16 sessions, most recently yesterday.
    evidence 0d old                                    5 of 10 signals shown
    ( Work it ) ( Not now ) Dispute
91 pts 4. ACT NOW Kestrel Systems
    Director of RevOps and 2 others used the product across 5 sessions, most recently today.
    evidence 0d old                                     4 of 9 signals shown
...
```

The pinned account at 74 pts sitting above a 105-pt account is the rep's own
hand, shown as such. Row 3 is `REVIEW` at 94 pts because its confidence is
`low` — the §4.2 gate demoting a high-points, low-confidence account, exactly as
specified.

### `GET /account/218?rep=1` — the detail view

```
Harbour Technologies · harbourtech.io
Cybersecurity · 1115 employees · GB · CRM: partner · owner: you

  ACT NOW  105 pts (above anchor)   bar for ACT NOW is 45 · scale anchored at 75
  rank 2 of 53 (was 1 before your adjustments) · confidence: high

These signals disagree. CMO and 3 others used the product across 5 sessions,
most recently 7 days ago, but Noor Belic, our contact here, left on 3 Aug 2026.
Read both before you act.

WHY THIS IS AT THE TOP
────────────────────────────────────────────────────────────────────────────
ACTIVE EVALUATION
  CMO and 3 others used the product across 5 sessions, most recently 7 days ago.
  7 sessions between 19 Jul 2026 and 3 Aug 2026 · source: product telemetry
                                                    +24 pts (capped at 24)
  see evidence   ( this is wrong ) ( out of date )
────────────────────────────────────────────────────────────────────────────
TIMING
  Harbour Technologies hired Hana Grimaldi as Data Engineer on 10 Aug 2026 —
  new owners re-open decisions.
  Role start 10 Aug 2026 · source: job change feed
                                                    +16 pts (capped at 16)
  see evidence   ( this is wrong ) ( out of date )
────────────────────────────────────────────────────────────────────────────
AUTHORITY
  Noor Belic bought from us before and started at Harbour Technologies on 31 Jul 2026.
  Job change detected 31 Jul 2026 · source: job change feed
                                                    +14 pts (capped at 14)
  see evidence   ( this is wrong ) ( out of date )
────────────────────────────────────────────────────────────────────────────
ACTIVE EVALUATION
  Operations Associate viewed /pricing 10x, most recently 3 weeks ago (19 Jul 2026).
  5 visits to /pricing between 19 Jul 2026 and 19 Jul 2026 · source: website
                                                                  +10 pts
  see evidence   ( this is wrong ) ( out of date )
────────────────────────────────────────────────────────────────────────────
DISQUALIFIER
  Noor Belic, our contact here, left on 3 Aug 2026. The relationship left with them.
  Job change detected 3 Aug 2026 · source: job change feed
                                                    −10 pts (capped at 10)
  see evidence   ( this is wrong ) ( out of date )
────────────────────────────────────────────────────────────────────────────

Showing the 5 strongest of 11 signals. The 6 not shown are worth +50.3 pts
combined; they do not change the band.

ADJUST YOUR QUEUE          pins 1/5 · demotes 1/10 · muted accounts 1/25
  ( Pin to top · 14 days ) ( Demote · 30 days ) ( Mute · 60 days )

DISAGREE WITH THE WHOLE ITEM
  ( Not a fit ) ( Wrong person (Rafael Steiner) ) ( Bad timing )
  ( Already working this ) ( Not my patch )

YOUR HISTORY ON THIS ACCOUNT
  Nothing yet.

AGENT RESEARCH (1 observations)
  · Migrated from Redshift to Snowflake per an engineering blog post.
    Engineering blog · retrieved 9 Jun 2026

back to queue · How the weights are set
```

Element order matches §6.2: category tag → sentence → evidence line → points →
actions, with points after the evidence, never before it. The cap is disclosed
inline. The §8.5 conflict line is present because a +24 positive and a −10
negative are both in force.

### `GET /evidence/{reason_id}?rep=1` — the drawer (§6.3)

```
Evidence · Active product usage · Harbour Technologies
Reason computed 11 Aug 2026 09:00 UTC from 5 events. Total +24.00 pts (cap +24.00).

  +8.18 pts  3 Aug 2026 15:11 UTC · magnitude 1 {"sessions": 1, "surface": "workspace"}
    person: Rafael Steiner, CMO
    source: product_telemetry · ingested 4 Aug 2026 08:21 UTC (17.1 h later)
    ref: https://app.example.test/evidence/ev_006271

  +5.68 pts  27 Jul 2026 06:26 UTC · magnitude 1 {"sessions": 1, "surface": "workspace"}
    person: Noor Belic, Operations Associate
    source: product_telemetry · ingested 28 Jul 2026 13:34 UTC (31.1 h later)
    ref: https://app.example.test/evidence/ev_006340
  ... (3 more)

Source links are shown as text — this environment has no outbound network.

  ( this reason is wrong ) ( this evidence is out of date ) ( wrong person )
```

Ingestion lag is computed and shown, per implication #10. Note that the five
raw contributions sum to more than 24.00 — the header discloses the cap rather
than hiding the difference.

---

## 6. The disagreement loop, end to end over HTTP

This is the part of the spec that matters most (§7, implication #6), so it was
exercised through the running server, not just in unit tests.

```
1) GET /account/218?rep=1 -> HTTP 200 | 105 pts | rank 2 of 53 (was 1 before your adjustments) · confidence: high
2) POST /dispute EVIDENCE_WRONG signal_type_id=1 -> HTTP 303 -> /account/218?rep=1&disputed=13
3) GET /account/218?rep=1&disputed=13 -> HTTP 200 | 81 pts
      was 105 pts before your disagreement
      You said this was wrong on 11 Aug 2026. Not counted here until 9 Nov 2026.
      Showing the 5 strongest of 11 signals. The 6 not shown are worth +50.3 pts
      combined and are part of why this is ACT NOW — the 5 shown alone would rate
      REVIEW. Suppressed by you: "Active product usage".
      rank 6 of 53 (was 1 before your adjustments) · confidence: high
      11 Aug 2026 · you said "Active product usage" was wrong.
                    suppress_signal_type active until 9 Nov 2026. [applied] ( undo )
4) POST /adjust/revert adjustment=14 -> HTTP 303 -> /account/218?rep=1&reverted=14
5) GET /account/218?rep=1&reverted=14 -> HTTP 200 | 105 pts  (restored)
```

105 → 81 is exactly −24.00, the capped `product_usage_active` contribution. The
account drops from rank 2 to rank 6, the reason stays in its slot struck
through with its return date, the limits line gains the suppression clause, the
history block gains an undo, and revert puts it back to 105. All within the same
request cycle, per §7.4.

### Budget enforcement returns a real 409

```
=== Budget enforcement: pin until the 5-pin budget is exhausted ===
  pin #1 account 12   -> HTTP 303 /account/12?rep=1&adjusted=15
  pin #2 account 218  -> HTTP 303 /account/218?rep=1&adjusted=16
  pin #3 account 199  -> HTTP 303 /account/199?rep=1&adjusted=17
  pin #4 account 119  -> HTTP 303 /account/119?rep=1&adjusted=18
  pin #5 account 109  -> HTTP 409
  409 body: Budget reached — You already have 5 pins. They expire on their own
            — your oldest expires on 23 Aug 2026 — or undo one now.
            view your adjustments
```

(The count reaches 5 after four new pins because one pin was already seeded.)
The request is refused, not silently absorbed, and the over-budget row is not
written.

### `GET /adjustments?rep=1`

```
Your adjustments · Ana Belic
Every adjustment expires. Expiry is evaluated when the queue is read, against
11 Aug 2026 09:00 UTC — there is no background job.

Budget                            | Used | Limit
pins                              |    5 |     5
demotes                           |    1 |    10
muted accounts                    |    1 |    25
patch-wide signal suppressions    |    0 |     3
account-scoped signal suppressions|    1 |    50
excluded people                   |    0 |    50

All adjustments
pin · Kestrel Systems                                    11 Aug 2026 | 25 Aug 2026 | active   | ( undo )
pin · Yarrow Partners                                    11 Aug 2026 | 25 Aug 2026 | active   | ( undo )
suppress_signal_type · Harbour Technologies · "Active product usage"
                                                         11 Aug 2026 |  9 Nov 2026 | reverted |
mute_account · Granite Partners                           9 Aug 2026 |  8 Oct 2026 | active   | ( undo )
demote · Thistle Freight                                  8 Aug 2026 |  7 Sep 2026 | active   | ( undo )
suppress_signal_type · Meridian Networks · "Docs / integration page views"
                                                         17 Jun 2026 | 17 Jul 2026 | expired  |
suppress_signal_type · Kilnwood Networks · "Third-party intent (6sense)"
                                                          6 Aug 2026 |  4 Nov 2026 | active   | ( undo )
```

### The friction gate (§6.4), live

```
disabled Work-it buttons in rep 1 queue: 3
    Open evidence on one reason before working this — you disputed a reason on this account on 17 Jun 2026.
    Open evidence on one reason before working this — you disputed a reason on this account on 6 Aug 2026.
    Open evidence on one reason before working this — you disputed a reason on this account on 8 Aug 2026.

server-side enforcement of the same gate:
  POST /task accepted on a gated account -> HTTP 409
  "Open the evidence first — This account needs one evidence drawer opened
   before it can be worked."

...and after opening one drawer:
  opened evidence drawer 2427
  POST /task accepted on account 5 AFTER opening evidence -> HTTP 303 /queue?rep=1
```

3 of 53 items = **5.7%**, inside the "roughly 4–6% of queue items" §6.4
predicts. All three fire on clause (b), the open-dispute clause. See the
*Deviations* note in `README.md` about clause (a) being structurally unreachable
in an ownership-filtered queue.

---

## 7. `GET /metrics` and `GET /ruleset`

```
Warrant · metrics
Trailing 30 days, 12 Jul 2026 to 11 Aug 2026. All figures are live SQL over
task_events, disagreements, queue_adjustments and reasons.

Top-3 acceptance (last 30d) | 45.0% | 9 / 20  — no target set; v1 establishes baseline
Evidence-open rate          | 50.0% | 67 / 134
Item dispute rate           |  0.9% | 2 / 214
Revert rate                 | 25.0% | 1 / 4
Skip with no dispute        |100.0% | 75 / 75 — reps who skip without telling us why
                                                are the ones we are losing

Per signal type
Signal type                          | Shown | Disputes | Dispute rate | Suppression rate
Third-party intent (6sense)          |    21 |        1 |         4.8% |          100.0%
Active product usage                 |    60 |        1 |         1.7% |            0.0%  REVIEW REQUIRED — 1 of 1 reps have disputed this
Known champion left this account     |    33 |        0 |         0.0% |            0.0%
Funding round or hiring surge        |    66 |        0 |         0.0% |            0.0%
New hire into a target function      |    69 |        0 |         0.0% |            0.0%
Open opportunity owned by another rep|     0 |        0 |            — |               —
... (19 rows)

Ownership errors
None reported.
```

The `REVIEW REQUIRED` flag firing on a 1-of-1 denominator is a real weakness of
the §7.5 flag rule at small n, not a bug in the implementation — see
*Limitations* in `README.md`.

`GET /ruleset` renders all 19 signal types. Spot-checked against §4.1:

```
Active product usage      | product_usage_active | active_evaluation | event | +12.0 | +24.0 |  14
Inbound demo or contact.. | inbound_demo_request | active_evaluation | event | +11.0 | +11.0 |   7
Repeat pricing-page vis.. | pricing_page_repeat  | active_evaluation | event |  +9.0 | +18.0 |  10
Docs / integration page.. | docs_or_integration_view | active_evaluation | event | +5.0 | +10.0 | 10
Known champion moved to.. | champion_job_move    | authority         | event | +14.0 | +14.0 |  45
Director+ in a target f.. | senior_buyer_engaged | authority         | event | +10.0 | +20.0 |  21
New hire into a target..  | new_hire_icp_role    | timing            | event |  +8.0 | +16.0 |  60
Funding round or hiring.. | funding_or_hiring_surge | timing         | event |  +5.0 | +10.0 |  90
Third-party intent (6se.. | third_party_intent_6sense | timing       | event |  +4.0 |  +8.0 |  14
Industry matches ICP      | icp_industry_match   | fit               | state |  +6.0 |  +6.0 |   —
Headcount in ICP band     | icp_size_match       | fit               | state |  +6.0 |  +6.0 |   —
Runs ICP-adjacent tooling | tech_stack_match     | fit               | state |  +5.0 |  +5.0 |   —
Open opportunity owned..  | open_opp_owned_elsewhere | disqualifier  | state | -15.0 | -15.0 |   —
Closed-lost in the last.. | closed_lost_recent   | disqualifier      | event | -12.0 | -12.0 | 180
Known champion left this..| champion_departed    | disqualifier      | event | -10.0 | -10.0 |  90
Contact unsubscribed or.. | unsubscribed_or_bounced | disqualifier   | event |  -9.0 |  -9.0 | 365
No engagement of any kin..| no_engagement_90d    | disqualifier      | state |  -8.0 |  -8.0 |   —
Headcount outside ICP band| outside_icp_size     | disqualifier      | state |  -7.0 |  -7.0 |   —
No director-or-above con..| no_buying_authority_present | disqualifier | state | -6.0 | -6.0 |   —
```

All 19 rows match §4.1 exactly — weight, cap, half-life, category, kind.

---

## 8. One more bug found after the tests were green

While writing this document I noticed the `no_engagement_90d` evidence line
rendering `Last activity {newest_date}` using the account's **enrichment refresh
date** rather than the date of the actual last activity, because I had stamped
all state signals with `data_last_refreshed_at`. For the fit signals that is
correct — a fit claim cannot be fresher than the enrichment behind it. For
`no_engagement_90d` it made the reason misstate its own evidence, which is
precisely the trust failure implication #10 exists to prevent.

Fixed in `warrant/scoring.py`, and verified:

```
$ python - <<'EOF'
FIXED evidence line -> Last activity 6 May 2026 | refresh date was 2025-11-02
               text -> Nothing at all from Tundra Freight in 96 days. Interest, if it existed, has cooled.
EOF
```

6 May 2026 is 96 days before `as_of`, matching the sentence. Before the fix it
read "Last activity 2 Nov 2025". Full suite re-run after the change:

```
$ python -X utf8 -W ignore::ResourceWarning -m unittest discover tests
..............................................................................................
Ran 94 tests in 32.637s
OK
```

---

## 9. Things I could not verify, or did not do

Stated plainly rather than left to be discovered.

1. **No browser rendering was checked.** Every view above was fetched over HTTP
   and converted to text with a regex stripper. The HTML is valid enough to
   parse and every value is `html.escape`d, but I have not seen the CSS render
   in a browser and cannot claim the visual layout matches the §6 mockups. The
   *content and ordering* match; the *appearance* is unverified.
2. **`§6.4` clause (a) was never observed firing in a live queue**, because the
   queue is filtered to `owner_rep_id = rep` and an open opportunity owned by
   another rep is therefore never in it. The predicate itself is correct and is
   unit-tested directly (T18 passes), but in the running app only clause (b)
   ever fires. Recorded as a deviation.
3. **Concurrency is untested.** The server is a `ThreadingHTTPServer` and each
   request opens its own connection, but I have not run concurrent writers.
   SQLite's default locking will serialise them; under real load this would need
   WAL mode and a retry policy.
4. **`/metrics` numbers are shaped by seeded instrumentation, not real usage.**
   They are computed by live SQL, but the inputs are synthetic, so the rates
   themselves mean nothing yet. That is what "v1 establishes baseline" means.
5. **The reason templates have not been checked against how a rep actually
   talks.** That is the design stage's own open question #2 and it remains open.
6. **`python app.py` was run without a `.env` file**, relying on defaults. The
   env vars are read via `os.environ` and the defaults are what `.env.example`
   documents; I did not test a populated `.env`, because nothing in this repo
   loads one — that would need a parser and there is nothing secret to load.
