# DESIGN SPEC — Warrant

**Feature:** Warrant — reason-first prioritisation for Unify
**Stage:** Design (input: `RESEARCH_BRIEF.md`, 11 Aug 2026)
**Author:** Designer agent (AI-generated)
**Date:** 11 August 2026
**Ruleset version this spec defines:** `warrant-v1.0.0`
**Status:** Buildable. The maker implements this as written.

---

## 0. How to read this spec

Every design decision below traces to a numbered finding or design implication in `RESEARCH_BRIEF.md`. Where I deviate from the brief, I say so in §2 with a reason. Where the brief left a decision open (notably implication #12), I make it and justify it rather than leaving it to the build.

Section 9 is the build checklist. If §9 and any earlier section conflict, the earlier section wins — §9 is an index, not a source of truth.

---

## 1. Feature concept and name

### 1.1 Name

**Warrant.**

A warrant is the thing that licenses a claim from a piece of evidence. That is exactly the object this feature makes first-class. Each item in a rep's queue is *a warrant*: a small, dated, sourced case for spending the next 20 minutes on this account. The name is also the word a rep would actually use — "what's the warrant for this one being top of my list?" — which matters, because per finding 2.3 the vocabulary has to be sales vocabulary, not marketing vocabulary.

Sub-objects, named consistently throughout the spec and the UI:

| Object | Definition | Table |
|---|---|---|
| **Warrant** | The whole case for one account for one rep at one point in time: band, points, reasons, limits line | `scores` |
| **Reason** | One signal type's contribution, rendered as a sentence in the rep's qualification language | `reasons` |
| **Evidence** | The underlying dated, sourced rows a reason was computed from | `signal_events`, `observations` |
| **Dispute** | A rep saying a specific reason or a whole warrant is wrong, with a code | `disagreements` |
| **Adjustment** | The bounded, expiring, reversible change a dispute (or a direct action) makes to that rep's queue | `queue_adjustments` |

### 1.2 Concept

Warrant is a prioritisation layer in which **the reason is the primary object and the ranking is a consequence of it**. For every account in a rep's patch, Warrant runs live SQL over Unify's signal, person and account data, computes an additive, fully inspectable evidence score from a published weight table, generates 3–5 human-readable reasons — positive and negative — from the exact same arithmetic that produced the score, timestamps and sources every one of them, states in one line what it is not showing, and attaches a one-click disagreement action to each reason and to the item as a whole. Every disagreement writes a row and produces a bounded, expiring, reversible change to that rep's own queue that they can see happen. Nothing a rep does affects another rep's queue or the global ruleset; the ruleset changes only through RevOps review, informed by aggregated dispute metrics.

### 1.3 The orchestrator's decision, restated

The researcher could not verify that Unify ships any documented lead score. She checked the docs index, the signals reference, the intent tutorials, the glossary and the changelog, and found no score, scoring model, fit grade or documented prioritisation logic (brief §1, "the critical negative finding", verified by absence across five documents; the only score anywhere is 6sense's, arriving via integration).

**This spec is designed to hold either way.** Warrant is an explanation-first prioritisation layer:

- **If Unify has an undocumented internal score**, Warrant wraps and explains it. The internal score enters the model as one more signal type (`code = 'unify_internal_score'`, `category = 'timing'`, low weight, and — per implication #3 — with a reason string that names what it is rather than pretending it is evidence). The rest of the layer is unchanged.
- **If Unify has no score**, Warrant *is* the score, and it was born explainable rather than retrofitted.

Either way the rep experience is identical, which is the point. The maker builds the second case (no internal score) because it is the verified one; the schema leaves the first case as a single additional row in `signal_types`.

### 1.4 Competitive position

Brief §4, closing inference: *"Nobody in this set gives the individual rep a first-class way to say 'this reason is wrong' and have that change anything. That is the unoccupied position."*

The teardown shows every competitor except HubSpot ships some form of "why", and every one of them fails in one of four ways:

- **Einstein** — partial by vendor admission ("fields that aren't listed still influence the score"), and rescored every 10 days, so the reason can be stale relative to what the rep is looking at.
- **MadKudu** — signals are *manually configured* and explicitly *not* a faithful reflection of model logic, because "your full model's logic would be very confusing to expose". The explanation is decoupled from the decision.
- **Pocus, Common Room, Clay** — the "why" is real, but the *change* affordance is aimed at the ops user who edits the model, not the rep who works the lead. Pocus's explanation is hover-only and lives in list view.
- **Apollo** — explainability claimed in marketing, unverifiable in docs (KB returns 403); treat as claimed.

Warrant takes the unoccupied position directly:

1. The explanation **is** the model (§4.2), so MadKudu's decoupling problem cannot occur.
2. The explanation is **complete about its incompleteness** (§4.6 honest-limits line), so Einstein's partiality is disclosed rather than conceded in a docs footnote.
3. The change affordance belongs to **the rep**, is bounded, expires, is reversible, and is visible (§7).

Unify's structural advantage, per brief §5: it has not yet shipped a score, so it does not have to retrofit an explanation onto one.

---

## 2. Grounding — the brief's 12 design implications

All 12 are addressed. Ten are honoured in full, one is honoured with a named deviation, one sub-clause is explicitly rejected.

| # | Implication (brief §6) | Status | How this spec handles it |
|---|---|---|---|
| **1** | Per-lead reasons, not a global model explanation (→ §3 synthesis, §2.2) | **Honoured** | Reasons are computed per `(account, rep, run)` and stored in `reasons`, one row per contributing signal type, rendered from that account's own events. A global page exists at `GET /ruleset` (§6.5) but it is deliberately reachable only from a small footer link on the detail view and is labelled *"This is how the weights are set. It is not why this account ranked here — that is above."* |
| **2** | Cap at 3–5 reasons, ranked by contribution; hard ceiling; no "show all 27 factors" expander (→ §3.2, Poursabzi-Sangdeh et al., n≈3,800, more transparency degraded error detection) | **Honoured** | Hard ceiling of 5 shown reasons, floor of 3 where 3 exist. Truncation rule fully specified in §4.5. All reasons are persisted with a `shown` flag for audit and metrics, but **the rep UI has no expander, no "show more", no hover-to-reveal-the-rest.** The withheld reasons are disclosed in aggregate by the honest-limits line (§4.6), never enumerated. |
| **3** | Each reason shows raw evidence value, not a model artifact; never a SHAP waterfall (→ §3.4, Kaur et al. n=11/197, Krishna et al. n=25) | **Honoured with a named deviation** | Every reason leads with raw evidence — `"VP Engineering viewed /pricing 3x, most recently 2 days ago (9 Aug 2026)"` — sourced and dated. No SHAP, no LIME, no waterfall, no percentage-of-contribution, no probability. **Deviation:** each reason also shows its point value (`+15 pts`), right-aligned and secondary. Justification: the brief's objection in §3.4 is to *post-hoc attribution over a black box*, which the disagreement problem shows is unstable across methods and misread even by experts. Warrant's points are not an attribution of a hidden model — they *are* the model, they are integers-to-one-decimal, they sum in front of the rep to the total shown at the top, and the rep can check the addition. Hiding them would make the total unverifiable, which is the HubSpot "22 means nothing" failure (§2.2, §4). I am taking this deviation knowingly and flagging it as the first thing to kill if usability testing shows reps anchoring on points instead of reading the evidence line. |
| **4** | Reasons in the rep's qualification language, not marketing's activity language (→ §2.3) | **Honoured** | `signal_types.category` is a five-value enum drawn from qualification vocabulary: `fit`, `authority`, `active_evaluation`, `timing`, `disqualifier`. These are the labels shown on each reason. The words "engagement", "engagement score", "MQL", "lead score", "activity score", "nurture" and "hand-raiser" are **banned from all rendered strings** — this is a testable assertion (§9, T11). Reason templates are written as claims about problem fit, authority and active evaluation (§4.3). |
| **5** | First-class disagreement action on every reason and every ranked item; minimum codes "not a fit / wrong person / bad timing / already working this", logged against the specific reason that fired (→ §3.1, Bansal et al. — explanations raise acceptance whether or not the AI is right) | **Honoured, extended** | Seven reason codes (§7.1) covering the brief's four required ones plus `EVIDENCE_WRONG`, `EVIDENCE_STALE`, `NOT_MY_PATCH`. Reason-scoped disputes store `reason_id` **and** the denormalised `signal_type_id` so the dispute survives the next scoring run. Item-scoped disputes store `score_id` and `account_id`. Every dispute maps to a mechanical effect — there is no code that logs and does nothing. |
| **6** | Bounded rep-level queue adjustment, made visible; pin, demote, suppress a signal type for their patch. *"The single highest-leverage requirement in this list."* (→ §3.3, Dietvorst et al. — the effect held even when modification was severely restricted) | **Honoured, and treated as the centre of the spec** | Five adjustment kinds with hard numeric budgets, expiry windows and one-click revert (§7.3). Because the effect survives severe restriction, the budgets are deliberately tight rather than generous: 5 pins, 10 demotes, 3 patch-wide signal suppressions, 50 account-scoped suppressions, 25 mutes. Every active adjustment is visible as a chip in the queue row and a line in the detail view; the score line changes to `59.9 → 35.9 pts (adjusted by you)` when a suppression is in force. Nothing a rep adjusts touches another rep. |
| **7** | Show negative reasons alongside positive ones (→ §4 Salesforce; §3.1) | **Honoured** | The truncation rule (§4.5) *reserves* up to 2 of the 5 shown slots for negatives and fills them before backfilling positives. If an account has any negative reason above the 0.5-point floor, at least one negative is shown. Negatives render with a `−` sign, the `disqualifier` category tag and a distinct chip. Seven negative signal types are defined (§4.1). |
| **8** | State the honest limit of the explanation in the UI, in one short line (→ §3.4; §4) | **Honoured** | A mandatory single-line `limits_line` on every detail view and a compressed version in the queue row. Two variants, selected mechanically by whether the withheld reasons would flip the band (§4.6). Worked example in §6.3 uses the harder variant: *"the 5 shown alone would rate REVIEW."* Rendering a detail view without a limits line is a test failure (§9, T09). |
| **9** | Do not decouple the explanation from the decision logic; if reason templates are hand-authored, they must be generated from the same evidence that triggered the action (→ §4, MadKudu) | **Honoured — architecturally enforced** | There is exactly one code path. `score_account()` returns a list of `SignalContribution` objects; the score is `sum(c.points)` and the reasons are `render(c)` over the same list. It is not possible to produce a reason that did not contribute points, or a point that produced no reason. Templates are hand-authored *strings*; the *values* substituted into them are the same event rows the arithmetic consumed, linked in `reason_evidence`. Test T07 asserts `sum(reason.points for all reasons, shown and unshown) == score.points` exactly. |
| **10** | Timestamp and source every reason; let the rep open the underlying evidence; Unify's Observations are the clickable substrate (→ §1; §4 Salesforce, Common Room) | **Honoured, with a named runtime constraint** | Every reason carries `newest_event_at`, `oldest_event_at`, `event_count` and the source system name, all rendered. `GET /evidence/{reason_id}` opens a drawer listing every contributing `signal_events` row (occurred_at, observed_at, source, magnitude, detail) plus any `observations` rows for that account. **Constraint (§1 of the technical constraints): there is no reliable outbound network at runtime.** So `source_url` is rendered as selectable literal text with a copy affordance, not as a live hyperlink that would 404 in the demo environment. This is stated in the drawer: *"Source links are shown as text — this environment has no outbound network."* Naming it beats shipping links that silently fail. |
| **11** | Make disagreement measurably change something, and instrument it; track reason-level dispute rate and top-item action rate (→ §2.2; §3.3) | **Honoured; one sub-clause rejected — see below** | Every dispute code produces a mechanical, visible change (§7.2). `task_events` instruments nine event types. `GET /metrics` reports: top-3 acceptance rate, per-signal-type dispute rate (disputes ÷ times shown), evidence-open rate, suppression rate per signal type, and dispute→revert rate. A signal type disputed by >20% of reps who saw it, over ≥30 shows in 30 days, is flagged `REVIEW REQUIRED` on `/ruleset` (§7.5). |
| **11a** | *Sub-clause:* adopt Pedowitz Group's 65–75% sales acceptance rate as the health target | **REJECTED** | That figure is an MQL→SQL acceptance rate for a marketing-to-sales handoff. Top-3 queue acceptance is a structurally different metric with a different denominator and a different base rate, and importing the number would give the build a target that has no evidential relationship to what it measures. The brief itself, in the §2.4 contradiction note, warns against reusing figures whose provenance does not match the claim. **Warrant instruments top-3 acceptance rate and ships no target value in v1.** `/metrics` renders it as `Top-3 acceptance (last 30d): 61.4% — no target set; v1 establishes baseline.` A target is set after 30 days of real data, by RevOps, not by this spec. |
| **12** | Decide deliberately whether to introduce friction, and document the choice (→ §3.5, Buçinca et al. — cognitive forcing reduced overreliance but was rated least favourably) | **Honoured — decision made, documented in §6.4** | **Decision: friction for a narrow, defined class only; none elsewhere.** The `[Work it]` button is disabled until at least one `[see evidence]` drawer has been opened *if and only if* the account meets one of two conditions: (a) `crm_status = 'open_opportunity'` and `owner_rep_id != current rep`, or (b) the account has any dispute in `status='open'`. Both are cases where acting without looking has a real cost to a colleague or contradicts something the rep themselves said. Everything else — the volume-outbound majority, ~95% of items — has zero friction, because the brief's own steer is that for volume outbound cognitive forcing "almost certainly is not" warranted, and Buçinca's participants disliked the forcing designs. The condition is a two-line predicate, `requires_evidence_review()`, deliberately narrow so it does not creep. |

---

## 3. Data model

SQLite, created by `seed_db.py` at `data/unify.db` via Python's `sqlite3` module. No `sqlite3` CLI is available in the target environment, so all DDL runs through `Connection.executescript()` reading `db/schema.sql`.

**Conventions, applied to every table:**
- All timestamps are ISO-8601 UTC strings, `YYYY-MM-DDTHH:MM:SSZ`, stored as `TEXT`. SQLite has no native datetime; string comparison on this format is chronologically correct and that is why this format is mandatory.
- Booleans are `INTEGER NOT NULL` constrained to `(0,1)`.
- JSON payloads are `TEXT` containing a JSON object or array, parsed with `json.loads`. Never store bare Python `repr`.
- `PRAGMA foreign_keys = ON` on every connection. This is not optional — several cascade behaviours in §7 depend on it.
- Every `PRIMARY KEY` is `INTEGER PRIMARY KEY` (rowid alias) unless stated.
- Money is `INTEGER` USD. No floats for currency.

### 3.1 `reps`

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `rep_id` | INTEGER | no | PK | |
| `name` | TEXT | no | | Display name, e.g. `"Dana Whitfield"` |
| `email` | TEXT | no | UNIQUE | e.g. `dana.whitfield@example-co.test`. Synthetic domain only. |
| `territory` | TEXT | no | | One of `NA-MidMarket`, `NA-Enterprise`, `EMEA-MidMarket`, `APAC-All` |
| `created_at` | TEXT | no | | |

**Seed:** exactly 4 reps, one per territory. `rep_id` 1–4.

### 3.2 `accounts`

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `account_id` | INTEGER | no | PK | |
| `name` | TEXT | no | | e.g. `"Kestrel Analytics"` |
| `domain` | TEXT | no | UNIQUE | e.g. `kestrelanalytics.io` |
| `industry` | TEXT | yes | | One of the 10 values in §3.10. **NULL is meaningful** — represents unenriched data. |
| `employee_count` | INTEGER | yes | | 12–9,000. **NULL is meaningful** — thin data. |
| `annual_revenue_usd` | INTEGER | yes | | 500,000–2,000,000,000 |
| `hq_country` | TEXT | no | | ISO-3166 alpha-2: `US`,`GB`,`DE`,`FR`,`SG`,`AU`,`CA`,`NL`,`IN`,`BR` |
| `tech_stack` | TEXT | yes | | JSON array of strings, e.g. `["Snowflake","dbt","Segment"]`. NULL = never enriched. |
| `crm_status` | TEXT | no | | `none` \| `open_opportunity` \| `closed_lost` \| `customer` \| `partner` |
| `crm_status_changed_at` | TEXT | yes | | NULL iff `crm_status='none'` |
| `owner_rep_id` | INTEGER | yes | FK→`reps` | Which rep the account sits with. NULL = unassigned pool. |
| `first_seen_at` | TEXT | no | | When Unify first saw this account. Drives the brand-new edge case. |
| `data_last_refreshed_at` | TEXT | no | | Last enrichment refresh. Drives the fit-signal timestamp — a fit reason cannot claim to be fresher than this. |
| `is_active` | INTEGER | no | | 0 = out of business / merged; excluded from all queues. |

**Seed distribution — 240 accounts.**
- `owner_rep_id`: 55 to each of reps 1–4, 20 unassigned (NULL).
- `employee_count`: draw `int(10 ** random.uniform(1.1, 3.95))` → ~12–8,900, log-uniform (right-skewed, realistic B2B). Then set **12% to NULL** (thin data).
- `industry`: **8% NULL**; the rest weighted per §3.10.
- `annual_revenue_usd`: `employee_count * random.randint(90_000, 320_000)` where employee_count is known; NULL where it is not, plus a further 10% NULL.
- `tech_stack`: 3–6 items sampled from the §3.10 list; **22% NULL**.
- `crm_status`: `none` 62%, `closed_lost` 14%, `open_opportunity` 11%, `customer` 9%, `partner` 4%.
- `first_seen_at`: uniform over the 540 days before `AS_OF`, **except** a forced 6% (≈14 accounts) placed within the last 10 days → brand-new edge case (§8.4).
- `data_last_refreshed_at`: `first_seen_at + uniform(0, 400) days`, clamped to ≤ `AS_OF`. Force 18% of accounts to have `data_last_refreshed_at` more than 120 days before `AS_OF` → stale fit data.
- `is_active`: 0 for 3% of accounts.

### 3.3 `people`

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `person_id` | INTEGER | no | PK | |
| `account_id` | INTEGER | no | FK→`accounts` | |
| `full_name` | TEXT | no | | |
| `title` | TEXT | no | | e.g. `"VP Engineering"` |
| `seniority` | TEXT | no | | `ic` \| `manager` \| `director` \| `vp` \| `c_level` \| `founder` |
| `department` | TEXT | no | | `engineering` \| `data` \| `revops` \| `sales` \| `marketing` \| `security` \| `finance` \| `product` \| `other` |
| `email` | TEXT | yes | | Synthetic. NULL 25% of the time. |
| `linkedin_url` | TEXT | yes | | Synthetic path only, e.g. `https://www.linkedin.com/in/synthetic-p0412`. Never a real profile. |
| `is_champion` | INTEGER | no | | 1 = previously engaged at a customer account |
| `started_role_at` | TEXT | yes | | Drives new-hire and job-move signals |
| `email_status` | TEXT | no | | `ok` \| `bounced` \| `unsubscribed` |
| `created_at` | TEXT | no | | |

**Seed:** 2–14 people per account, mean ≈ 6 (`max(2, int(random.gauss(6, 3)))`, clamped to 14). Total ≈ 1,450.
- Seniority mix per account: 55% `ic`/`manager`, 30% `director`/`vp`, 15% `c_level`/`founder` — but **force 18% of accounts to have NO person of seniority `director` or above** (drives `no_buying_authority_present`, §4.1).
- `is_champion` = 1 for 4% of people.
- `email_status`: `ok` 92%, `bounced` 5%, `unsubscribed` 3%.

### 3.4 `signal_types` — the published weight table

This table *is* the model. It is inspectable at `GET /ruleset`. Weights live in data, not in Python constants, so that the explanation and the arithmetic cannot drift apart (implication #9).

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `signal_type_id` | INTEGER | no | PK | |
| `code` | TEXT | no | UNIQUE | Machine name, e.g. `pricing_page_repeat` |
| `display_name` | TEXT | no | | e.g. `"Repeat pricing-page visits"` |
| `category` | TEXT | no | | `fit` \| `authority` \| `active_evaluation` \| `timing` \| `disqualifier` (implication #4) |
| `polarity` | TEXT | no | | `positive` \| `negative`. Must agree in sign with `base_weight`. |
| `kind` | TEXT | no | | `event` (computed from `signal_events`) \| `state` (computed by SQL predicate over `accounts`/`people`) |
| `base_weight` | REAL | no | | Points per occurrence before decay and magnitude. Negative for disqualifiers. |
| `max_contribution` | REAL | no | | Absolute cap on this signal type's total for one account. Same sign as `base_weight`. |
| `half_life_days` | REAL | yes | | Decay half-life. NULL for `kind='state'` (no decay). |
| `lookback_days` | INTEGER | no | | Events older than this are excluded entirely. Default 365. |
| `reason_template` | TEXT | no | | Python `str.format` template, §4.3 |
| `evidence_template` | TEXT | no | | Second-line template showing raw values and source, §4.3 |
| `state_predicate` | TEXT | yes | | For `kind='state'`: a documented predicate name resolved in `scoring.py`. NULL for `kind='event'`. |
| `is_enabled` | INTEGER | no | | Global kill switch, RevOps-only |

**Seed:** exactly the 19 rows given in §4.1. This is reference data, not randomised.

### 3.5 `signal_events`

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `event_id` | INTEGER | no | PK | |
| `account_id` | INTEGER | no | FK→`accounts` | |
| `person_id` | INTEGER | yes | FK→`people` | NULL for account-level signals (e.g. funding) |
| `signal_type_id` | INTEGER | no | FK→`signal_types` | |
| `occurred_at` | TEXT | no | | When the thing happened. Drives decay. |
| `observed_at` | TEXT | no | | When Unify ingested it. Always ≥ `occurred_at`. Shown in the evidence drawer so the rep can see ingestion lag. |
| `source` | TEXT | no | | `website_tracker` \| `product_telemetry` \| `crm_sync` \| `unify_agent` \| `6sense` \| `job_change_feed` \| `email_platform` \| `funding_feed` |
| `magnitude` | REAL | no | | Count/intensity: page views, sessions, seats. Default 1.0. Never < 1.0. |
| `detail_json` | TEXT | yes | | JSON object supplying template variables, e.g. `{"path":"/pricing","visits":3}` |
| `source_url` | TEXT | yes | | Synthetic reference string. Rendered as text, not a link (implication #10 constraint). |

**Seed:** ≈ 6,500 events total across 240 accounts.
- Events per account: Zipf-like — `int(random.paretovariate(1.3))` clamped to 0–90.
- **Forced cohorts (these must exist, they are what the edge-case tests exercise):**
  - **8% of accounts (≈19): zero events.** No signal at all (§8.3).
  - **15% (≈36): exactly one distinct signal type**, 1–3 events. Thin data (§8.1).
  - **20% (≈48): freshest `occurred_at` more than 45 days before `AS_OF`.** Stale (§8.2).
  - **10% (≈24): conflicting** — at least one positive signal type reaching ≥12 points *and* at least one negative reaching ≤ −7 points (§8.5).
  - **6% (≈14): brand-new** — `first_seen_at` within 10 days, ≤3 events (§8.4).
- `occurred_at`: sampled from the 365-day window before `AS_OF` with a recency bias — `AS_OF - int(365 * random.random() ** 2.2) days` — so most activity is recent, as in reality.
- `observed_at` = `occurred_at + uniform(0, 36) hours`, clamped to ≤ `AS_OF`.
- `magnitude`: `1.0` for discrete events (job move, funding); `max(1, int(random.paretovariate(1.6)))` for countable ones (page views, sessions), producing mostly 1–3 with a long tail to ~40.

### 3.6 `observations` — agent research substrate (implication #10)

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `observation_id` | INTEGER | no | PK | |
| `account_id` | INTEGER | no | FK→`accounts` | |
| `person_id` | INTEGER | yes | FK→`people` | |
| `summary` | TEXT | no | | One sentence, ≤200 chars, e.g. `"Posted two senior data-platform roles in the last three weeks."` |
| `source_name` | TEXT | no | | e.g. `"Company careers page"`, `"Q2 earnings call transcript"` |
| `source_url` | TEXT | yes | | Synthetic. Rendered as text. |
| `retrieved_at` | TEXT | no | | When the agent fetched it — the honest freshness stamp |
| `agent_run_id` | TEXT | no | | e.g. `"run_2026-07-28_a41c"` |

**Seed:** 0–5 per account, **30% of accounts have none** (so the evidence drawer must handle the empty case, §8).

### 3.7 `score_runs`

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `run_id` | INTEGER | no | PK | |
| `rep_id` | INTEGER | no | FK→`reps` | Scores are **per rep**, because adjustments are per rep |
| `as_of` | TEXT | no | | Evaluation instant used for all decay arithmetic in this run |
| `computed_at` | TEXT | no | | Wall clock at computation |
| `ruleset_version` | TEXT | no | | `warrant-v1.0.0` |
| `anchor_points` | REAL | no | | The published anchor, 75.0 (§5) |
| `account_count` | INTEGER | no | | How many accounts were scored |

A run is created on every `GET /queue`. Runs are never mutated. This gives dispute rows a stable score snapshot to point at and lets `/metrics` compute rank-at-event correctly.

### 3.8 `scores` — one warrant

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `score_id` | INTEGER | no | PK | |
| `run_id` | INTEGER | no | FK→`score_runs` | |
| `account_id` | INTEGER | no | FK→`accounts` | |
| `points` | REAL | no | | Signed sum of all contributions, 2dp. **This is the score.** |
| `points_before_adjustment` | REAL | no | | Same computation ignoring this rep's active suppressions/exclusions. Equals `points` when none are active. |
| `band` | TEXT | no | | `ACT_NOW` \| `REVIEW` \| `HOLD` \| `INSUFFICIENT_EVIDENCE` |
| `confidence` | TEXT | no | | `high` \| `medium` \| `low` \| `insufficient` |
| `distinct_signal_types` | INTEGER | no | | Count of contributing types above the 0.5 floor |
| `freshest_evidence_at` | TEXT | yes | | Max `occurred_at` across contributing events. NULL if no events. |
| `data_completeness` | REAL | no | | 0.0–1.0, §8.7 |
| `rank_in_queue` | INTEGER | no | | 1 = top. Post-adjustment ordering. |
| `rank_before_adjustment` | INTEGER | no | | Ordering by `points` alone. Shown when they differ, so the rep sees their own hand. |
| `adjustment_flags` | TEXT | yes | | JSON array, subset of `["pinned","demoted","suppressed","excluded_person"]` |
| `limits_line` | TEXT | no | | The rendered honest-limits sentence, §4.6 |
| | | | UNIQUE(`run_id`,`account_id`) | |

### 3.9 `reasons` and `reason_evidence`

**`reasons`**

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `reason_id` | INTEGER | no | PK | |
| `score_id` | INTEGER | no | FK→`scores` | |
| `signal_type_id` | INTEGER | no | FK→`signal_types` | |
| `rank` | INTEGER | no | | 1..N by `abs(points)` desc, §4.5 |
| `polarity` | TEXT | no | | `positive` \| `negative` |
| `points` | REAL | no | | Signed, post-decay, post-magnitude, post-cap. 2dp. |
| `share_of_abs_total` | REAL | no | | `abs(points) / sum(abs(points))`. **Stored for metrics; never rendered** (implication #3). |
| `text` | TEXT | no | | Rendered reason sentence |
| `evidence_summary` | TEXT | no | | Rendered evidence line |
| `newest_event_at` | TEXT | no | | |
| `oldest_event_at` | TEXT | no | | |
| `event_count` | INTEGER | no | | |
| `source_names` | TEXT | no | | JSON array of distinct `source` values |
| `shown` | INTEGER | no | | 1 = passed the truncation rule. Unshown rows exist for audit and metrics only. |
| | | | UNIQUE(`score_id`,`signal_type_id`) | One reason per signal type per warrant |

**`reason_evidence`** — the join that makes implication #9 enforceable

| Column | Type | Null | Key |
|---|---|---|---|
| `reason_id` | INTEGER | no | PK part, FK→`reasons` |
| `event_id` | INTEGER | no | PK part, FK→`signal_events` |
| `contribution` | REAL | no | This single event's signed points before the type-level cap |

For `kind='state'` reasons there are no rows here; the drawer falls back to rendering the account/person field values named by the predicate, stamped with `accounts.data_last_refreshed_at`.

### 3.10 `disagreements`

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `disagreement_id` | INTEGER | no | PK | |
| `rep_id` | INTEGER | no | FK→`reps` | |
| `account_id` | INTEGER | no | FK→`accounts` | Denormalised so the dispute outlives its run |
| `score_id` | INTEGER | yes | FK→`scores` | The snapshot disputed |
| `reason_id` | INTEGER | yes | FK→`reasons` | NULL for item-scoped disputes |
| `signal_type_id` | INTEGER | yes | FK→`signal_types` | **Denormalised, NOT NULL when `scope='reason'`.** This is what survives run churn. |
| `person_id` | INTEGER | yes | FK→`people` | Set only for `WRONG_PERSON` |
| `scope` | TEXT | no | | `reason` \| `item` |
| `code` | TEXT | no | | One of the 7 codes in §7.1 |
| `note` | TEXT | yes | | Free text, max 280 chars, enforced server-side |
| `created_at` | TEXT | no | | |
| `ruleset_version` | TEXT | no | | So RevOps knows which weights the rep was reacting to |
| `status` | TEXT | no | | `open` \| `applied` \| `expired` \| `reverted` \| `reviewed` |
| `resulting_adjustment_id` | INTEGER | yes | FK→`queue_adjustments` | Provenance link — "what did my dispute actually do" |

### 3.11 `queue_adjustments` — the bounded lever (implication #6)

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `adjustment_id` | INTEGER | no | PK | |
| `rep_id` | INTEGER | no | FK→`reps` | Scope is always one rep. Never global. |
| `kind` | TEXT | no | | `pin` \| `demote` \| `mute_account` \| `suppress_signal_type` \| `exclude_person` |
| `account_id` | INTEGER | yes | FK→`accounts` | NULL only for patch-wide `suppress_signal_type` |
| `signal_type_id` | INTEGER | yes | FK→`signal_types` | NOT NULL iff `kind='suppress_signal_type'` |
| `person_id` | INTEGER | yes | FK→`people` | NOT NULL iff `kind='exclude_person'` |
| `created_at` | TEXT | no | | |
| `expires_at` | TEXT | no | | **Never NULL. Every adjustment expires.** |
| `source_disagreement_id` | INTEGER | yes | FK→`disagreements` | NULL when the rep used the direct pin/demote control |
| `is_active` | INTEGER | no | | Set to 0 by revert. Expiry is evaluated at read time against `as_of`, not by a background job. |
| `reverted_at` | TEXT | yes | | |

Constraint, expressed in DDL as a `CHECK`:
```sql
CHECK (
  (kind = 'suppress_signal_type' AND signal_type_id IS NOT NULL AND person_id IS NULL)
  OR (kind = 'exclude_person'      AND person_id IS NOT NULL AND account_id IS NOT NULL)
  OR (kind IN ('pin','demote','mute_account') AND account_id IS NOT NULL
      AND signal_type_id IS NULL AND person_id IS NULL)
)
```

### 3.12 `task_events` — instrumentation (implication #11)

| Column | Type | Null | Key | Meaning |
|---|---|---|---|---|
| `task_event_id` | INTEGER | no | PK | |
| `rep_id` | INTEGER | no | FK→`reps` | |
| `account_id` | INTEGER | yes | FK→`accounts` | |
| `score_id` | INTEGER | yes | FK→`scores` | |
| `run_id` | INTEGER | yes | FK→`score_runs` | |
| `event_type` | TEXT | no | | `queue_viewed` \| `item_viewed` \| `evidence_opened` \| `accepted` \| `skipped` \| `disputed` \| `adjusted` \| `reverted` \| `ruleset_viewed` |
| `occurred_at` | TEXT | no | | |
| `rank_at_event` | INTEGER | yes | | The `rank_in_queue` the item held when the rep acted. Essential for top-3 acceptance. |
| `detail_json` | TEXT | yes | | e.g. `{"code":"EVIDENCE_STALE","signal_type":"third_party_intent_6sense"}` |

**Seed:** ≈ 900 backdated `task_events` across the 4 reps and the 60 days before `AS_OF`, so `/metrics` is non-empty on first run. Distribution: ~62% of top-3 impressions accepted, ~9% of shown reasons disputed, ~34% evidence-open rate.

### 3.13 Reference value lists (for the seeder)

- **Industries (weighted):** `SaaS` 22%, `Data & Analytics` 14%, `Fintech` 12%, `Developer Tools` 10%, `Cybersecurity` 9%, `E-commerce` 9%, `Healthcare IT` 8%, `Logistics` 7%, `Manufacturing` 5%, `Professional Services` 4%.
- **ICP industries** (for `icp_industry_match`): `SaaS`, `Data & Analytics`, `Fintech`, `Developer Tools`, `Cybersecurity`.
- **ICP size band** (for `icp_size_match`): `50 ≤ employee_count ≤ 5000`.
- **Tech stack pool:** `Snowflake, dbt, Segment, Databricks, BigQuery, Salesforce, HubSpot, Looker, Airflow, Kafka, Postgres, Redshift, Fivetran, Amplitude`.
- **ICP tech markers** (for `tech_stack_match`): `Snowflake`, `dbt`, `Segment`, `Databricks`, `Fivetran`.
- **ICP target departments** (for `senior_buyer_engaged`, `new_hire_icp_role`): `engineering`, `data`, `revops`, `product`.
- **Page paths for website events:** `/pricing`, `/docs/quickstart`, `/docs/api`, `/integrations`, `/security`, `/customers`, `/blog/...`.
- **Fixed seed:** `random.seed(20260811)`. Reproducibility is a test assertion (§9, T01).
- **`AS_OF` default:** `2026-08-11T09:00:00Z`, overridable by env var `WARRANT_AS_OF`.

---

## 4. Scoring approach

### 4.0 Why this shape of model — stated, not apologised for

The technical constraint is Python standard library only: no scikit-learn, no numpy, no trained model. **That constraint and the brief's evidence point the same way, so this is not a compromise.**

Brief §3.4: Krishna, Lakkaraju et al. interviewed 25 practitioners who use LIME/SHAP daily and documented the *disagreement problem* — different post-hoc explanation methods disagree on which features matter and in what order, and practitioners resolve the conflict with ad hoc heuristics, meaning they "may be relying on misleading explanations when making consequential decisions." Kaur et al. found even data scientists over-trust interpretability tools and few could accurately describe what SHAP or GAM visualisations showed. Implication #3 draws the conclusion: **do not ship raw SHAP values, waterfall plots, or "contribution: +0.34" to an SDR. If experts misread them, reps will.**

A weighted additive model with time decay is not a lesser version of a black box for this job — it is the correct instrument. It has one explanation, not several competing post-hoc ones. Its per-signal contribution is not an estimate of an influence, it *is* the influence. Its arithmetic is checkable by the person reading it. Shipping a gradient-boosted model with SHAP attributions to a rep is precisely the failure mode the brief documents.

**What this model does not claim.** It is not a probability of closing. It is not calibrated against closed-won outcomes, because there is no outcome data here to calibrate against. It is a weighted count of evidence. §5 says so in the UI.

### 4.1 The 19 signal types

`base_weight`, `max_contribution` and `half_life_days` seed `signal_types` verbatim.

**Positive — ACTIVE EVALUATION**

| code | display_name | weight | cap | half-life (d) | kind |
|---|---|---|---|---|---|
| `product_usage_active` | Active product usage | +12.0 | +24.0 | 14 | event |
| `inbound_demo_request` | Inbound demo or contact request | +11.0 | +11.0 | 7 | event |
| `pricing_page_repeat` | Repeat pricing-page visits | +9.0 | +18.0 | 10 | event |
| `docs_or_integration_view` | Docs / integration page views | +5.0 | +10.0 | 10 | event |

`product_usage_active` carries the highest positive weight in the model, and the justification is Unify's own published benchmark, cited in brief §1: *product usage signals show a 9.1% positive reply rate, the highest-performing signal type.* The brief flags the framing to inherit — Unify already talks about signals as *evidence of expected outcome*. The weight table is built on that framing rather than on intuition, and `/ruleset` says so.

**Positive — AUTHORITY**

| code | display_name | weight | cap | half-life (d) | kind |
|---|---|---|---|---|---|
| `champion_job_move` | Known champion moved to this account | +14.0 | +14.0 | 45 | event |
| `senior_buyer_engaged` | Director+ in a target function engaged | +10.0 | +20.0 | 21 | event |

**Positive — TIMING**

| code | display_name | weight | cap | half-life (d) | kind |
|---|---|---|---|---|---|
| `new_hire_icp_role` | New hire into a target function | +8.0 | +16.0 | 60 | event |
| `funding_or_hiring_surge` | Funding round or hiring surge | +5.0 | +10.0 | 90 | event |
| `third_party_intent_6sense` | Third-party intent (6sense) | +4.0 | +8.0 | 14 | event |

`third_party_intent_6sense` is deliberately the lowest-weighted positive. It is the only signal in the set the rep cannot personally verify or quote to a buyer, and per brief §1 it is the one score that demonstrably exists in Unify today — arriving from outside, via integration. Under finding 2.1 (69% of buyers turn to reps to validate AI-generated insights), a signal the rep cannot stand behind should not be able to push an account to the top of a queue on its own. Its cap of +8.0 makes that structurally impossible: +8.0 is below the `REVIEW` threshold.

**Positive — FIT** (`kind='state'`, no decay, timestamped with `accounts.data_last_refreshed_at`)

| code | display_name | weight | cap | predicate |
|---|---|---|---|---|
| `icp_industry_match` | Industry matches ICP | +6.0 | +6.0 | `industry IN (ICP industries)` |
| `icp_size_match` | Headcount in ICP band | +6.0 | +6.0 | `50 <= employee_count <= 5000` |
| `tech_stack_match` | Runs ICP-adjacent tooling | +5.0 | +5.0 | `tech_stack ∩ ICP tech markers ≠ ∅` |

**Negative — DISQUALIFIER**

| code | display_name | weight | cap | half-life (d) | kind | predicate / trigger |
|---|---|---|---|---|---|---|
| `open_opp_owned_elsewhere` | Open opportunity owned by another rep | −15.0 | −15.0 | — | state | `crm_status='open_opportunity' AND owner_rep_id != :rep_id` |
| `closed_lost_recent` | Closed-lost in the last 12 months | −12.0 | −12.0 | 180 | event | |
| `champion_departed` | Known champion left this account | −10.0 | −10.0 | 90 | event | |
| `unsubscribed_or_bounced` | Contact unsubscribed or hard-bounced | −9.0 | −9.0 | 365 | event | |
| `no_engagement_90d` | No engagement of any kind in 90 days | −8.0 | −8.0 | — | state | account has ≥1 event ever, but none in the last 90 days |
| `outside_icp_size` | Headcount outside ICP band | −7.0 | −7.0 | — | state | `employee_count` known AND outside 50–5000 |
| `no_buying_authority_present` | No director-or-above contact known | −6.0 | −6.0 | — | state | no `people` row for this account with seniority ≥ `director` |

Note `no_buying_authority_present` fires only when the account has *some* people on file. If the account has no people at all, that is a data gap, not a disqualification, and it is handled by `data_completeness` and confidence instead (§8.1). This distinction matters: penalising an account for what we do not know is exactly the kind of quiet dishonesty implication #8 exists to prevent.

### 4.2 The arithmetic — unambiguous

**Event signals.** For account `a`, rep `r`, signal type `s`, at instant `as_of`:

```
E = { e in signal_events :
        e.account_id = a
    AND e.signal_type_id = s.id
    AND e.occurred_at <= as_of
    AND e.occurred_at >= as_of - s.lookback_days days
    AND NOT suppressed(r, s, a)          # §7.3
    AND NOT excluded_person(r, e.person_id) }   # §7.3

for each e in E:
    age_days       = (as_of - e.occurred_at).total_seconds() / 86400.0     # float, not int
    decay          = 0.5 ** (age_days / s.half_life_days)
    magnitude_f    = 1.0 + 0.5 * log10(max(e.magnitude, 1.0))
    contribution_e = s.base_weight * decay * magnitude_f

raw_s      = sum(contribution_e for e in E)
points_s   = sign(s.base_weight) * min(abs(raw_s), abs(s.max_contribution))
points_s   = round(points_s, 2)
```

`magnitude_f` is a half-log so that intensity matters but cannot run away: 1 event → ×1.00, 3 → ×1.24, 10 → ×1.50, 40 → ×1.80, 100 → ×2.00. Without the log, one enthusiastic bot crawl outranks a champion job move.

**State signals.** For signal type `s` with `kind='state'`:

```
if predicate(s, a, r) is True:
    points_s = s.base_weight        # no decay, no magnitude, no cap needed (weight == cap)
else:
    signal type is absent — no reason row is created
```

**Floor.** If `abs(points_s) < 0.5`, the signal type is dropped entirely — no reason row, no contribution. This prevents a warrant carrying a reason worth `+0.3 pts`, which reads as padding and, per §3.2, is exactly the marginal information that degrades error detection.

**Total.**

```
points = round(sum(points_s for all surviving signal types), 2)
```

Theoretical bounds with the §4.1 table: maximum `+147.0`, minimum `−67.0`. **The total is not normalised to 0–100 and not converted to a percentile.** See §5 for why, and for what the rep sees instead.

**Band.** Fixed thresholds on `points`, plus a confidence gate:

```
if confidence == 'insufficient':      band = 'INSUFFICIENT_EVIDENCE'
elif points >= 45.0 and confidence in ('high','medium'):  band = 'ACT_NOW'
elif points >= 45.0:                  band = 'REVIEW'      # high points, low confidence
elif points >= 25.0:                  band = 'REVIEW'
elif points >=  5.0:                  band = 'HOLD'
else:                                 band = 'HOLD'
```

The gate on line 4 is deliberate: a high-points, low-confidence account is demoted to `REVIEW`, never promoted to `ACT_NOW`. Confidence can only ever cost an account a band, never win it one. A thin account that happens to score well must not be presented as a certainty.

**Ordering.** `ORDER BY points DESC, freshest_evidence_at DESC, account_id ASC`. The third key exists solely so ties are deterministic and the queue does not shuffle between identical runs — a silently reordering queue destroys trust faster than a wrong reason does.

### 4.3 Reason generation

Reason text is rendered from `signal_types.reason_template` and `evidence_template` using values pulled from the same event rows the arithmetic consumed. Template variables available:

| Variable | Source |
|---|---|
| `{account_name}` | `accounts.name` |
| `{top_person_title}` | `people.title` of the person on the highest-contributing event; `"Someone"` if `person_id` is NULL |
| `{top_person_name}` | `people.full_name`, same event |
| `{event_count}` | `len(E)` |
| `{total_magnitude}` | `int(sum(e.magnitude))` |
| `{newest_date}` | `newest_event_at` as `9 Aug 2026` |
| `{newest_relative}` | `"2 days ago"`, `"today"`, `"yesterday"`, `"6 weeks ago"` |
| `{oldest_date}` | as above |
| `{path}` | `detail_json["path"]` of the highest-contributing event |
| `{source_list}` | distinct `source` values, humanised and comma-joined |
| `{field_value}` | for state signals: the account/person field the predicate read |
| `{refreshed_date}` | `accounts.data_last_refreshed_at` as `4 Jul 2026` |

**The templates.** Written in qualification language per implication #4 — problem fit, authority, active evaluation. No "engagement", no "score", no "activity".

| code | `reason_template` | `evidence_template` |
|---|---|---|
| `product_usage_active` | `{top_person_title} and {other_user_count} other{other_plural} used the product across {event_count} sessions, most recently {newest_relative}.` | `{total_magnitude} sessions between {oldest_date} and {newest_date} · source: {source_list}` |
| `inbound_demo_request` | `{top_person_name} ({top_person_title}) asked to be contacted on {newest_date}.` | `Inbound form, {newest_date} · source: {source_list}` |
| `pricing_page_repeat` | `{top_person_title} viewed {path} {total_magnitude}x, most recently {newest_relative} ({newest_date}).` | `{event_count} visits to {path} between {oldest_date} and {newest_date} · source: {source_list}` |
| `docs_or_integration_view` | `Someone at {account_name} read {path} {total_magnitude}x — they are checking whether this fits their stack.` | `{event_count} views between {oldest_date} and {newest_date} · source: {source_list}` |
| `champion_job_move` | `{top_person_name} bought from us before and started at {account_name} on {newest_date}.` | `Job change detected {newest_date} · source: {source_list}` |
| `senior_buyer_engaged` | `{top_person_title} — senior enough to sign — has engaged {event_count} time{event_plural}, last {newest_relative}.` | `{event_count} touches between {oldest_date} and {newest_date} · source: {source_list}` |
| `new_hire_icp_role` | `{account_name} hired {top_person_name} as {top_person_title} on {newest_date} — new owners re-open decisions.` | `Role start {newest_date} · source: {source_list}` |
| `funding_or_hiring_surge` | `{account_name} raised or expanded headcount on {newest_date} — budget is likelier to exist now.` | `{event_count} event{event_plural}, most recent {newest_date} · source: {source_list}` |
| `third_party_intent_6sense` | `A third party (6sense) reports buying-stage intent for {account_name}. We cannot see what they did — treat this as a hint, not evidence.` | `{event_count} intent update{event_plural}, most recent {newest_date} · source: 6sense integration` |
| `icp_industry_match` | `{field_value} — inside the segment where this problem lands.` | `Firmographic field, last refreshed {refreshed_date}` |
| `icp_size_match` | `{field_value} employees — big enough to have the problem, small enough to move.` | `Firmographic field, last refreshed {refreshed_date}` |
| `tech_stack_match` | `Runs {field_value} — the stack this integrates with.` | `Technographic field, last refreshed {refreshed_date}` |
| `open_opp_owned_elsewhere` | `There is already an open opportunity here, owned by {owner_name}. Not yours to work.` | `CRM status since {refreshed_date} · source: crm_sync` |
| `closed_lost_recent` | `We lost this {newest_relative} ({newest_date}). Whatever the reason was, it probably still holds.` | `Closed-lost {newest_date} · source: crm_sync` |
| `champion_departed` | `{top_person_name}, our contact here, left on {newest_date}. The relationship left with them.` | `Job change detected {newest_date} · source: {source_list}` |
| `unsubscribed_or_bounced` | `{top_person_name} unsubscribed or hard-bounced on {newest_date}. Email is closed here.` | `{event_count} event{event_plural}, most recent {newest_date} · source: {source_list}` |
| `no_engagement_90d` | `Nothing at all from {account_name} in {days_silent} days. Interest, if it existed, has cooled.` | `Last activity {newest_date}` |
| `outside_icp_size` | `{field_value} employees — outside the band where this sells.` | `Firmographic field, last refreshed {refreshed_date}` |
| `no_buying_authority_present` | `No director-or-above contact known here. There is nobody to sign.` | `{people_count} contacts on file, none at director+ · refreshed {refreshed_date}` |

Three of these deserve a note.

`third_party_intent_6sense` is the only template that describes its own limitation inside the reason sentence. That is on purpose. Per brief §1 it is externally sourced and the rep cannot open the underlying behaviour, so the sentence tells them that rather than letting them assume it is first-party evidence.

`no_buying_authority_present` names the gap without inventing a person. Under implication #3 the reason must show raw evidence, and the raw evidence here is an absence — so the evidence line reports how many contacts *are* on file and when the data was refreshed, letting the rep judge whether it is a real absence or an enrichment failure.

Every negative template states a *consequence for the rep's next action*, not just a fact. "Not yours to work." "Email is closed here." "There is nobody to sign." Implication #4 again: a reason phrased as a data attribute gets dismissed; a reason phrased as a qualification judgement gets read.

### 4.4 Worked example — full arithmetic

**Account:** Kestrel Analytics (`kestrelanalytics.io`), Data & Analytics, 420 employees, tech stack `["Snowflake","dbt","Looker"]`, `crm_status='none'`, `data_last_refreshed_at = 2026-08-04`, owned by rep 1.
**`as_of` = 2026-08-11T09:00:00Z.** No active adjustments.

**`product_usage_active`** (weight +12.0, cap +24.0, half-life 14d) — 3 events:

| occurred_at | age (d) | magnitude | decay = 0.5^(age/14) | mag_f = 1+0.5·log₁₀(m) | contribution |
|---|---|---|---|---|---|
| 2026-08-09 | 2 | 14 | 0.9057 | 1.5731 | **+17.10** |
| 2026-08-04 | 7 | 9 | 0.7071 | 1.4771 | **+12.53** |
| 2026-07-28 | 14 | 5 | 0.5000 | 1.3495 | **+8.10** |

`raw = 37.73` → exceeds cap → **`points = +24.00`**

**`pricing_page_repeat`** (+9.0, cap +18.0, hl 10d) — 2 events, both `/pricing`:

| occurred_at | age | mag | decay | mag_f | contribution |
|---|---|---|---|---|---|
| 2026-08-09 | 2 | 2 | 0.8706 | 1.1505 | **+9.01** |
| 2026-08-05 | 6 | 1 | 0.6598 | 1.0000 | **+5.94** |

`raw = 14.95` → under cap → **`points = +14.95`**

**Remaining signals:**

| code | detail | decay | points |
|---|---|---|---|
| `senior_buyer_engaged` | 1 event, 2026-08-09, mag 1 | 0.5^(2/21)=0.9361 | **+9.36** |
| `new_hire_icp_role` | 1 event, 2026-07-14, mag 1 | 0.5^(28/60)=0.7236 | **+5.79** |
| `icp_industry_match` | state: `Data & Analytics` | — | **+6.00** |
| `icp_size_match` | state: 420 employees | — | **+6.00** |
| `tech_stack_match` | 1 event, 2026-05-20 | 0.5^(83/180)=0.7264 | **+3.63** |
| `third_party_intent_6sense` | 2 events, 2026-08-01 & 2026-07-25 | 0.6095 / 0.4310 | **+4.16** |
| `champion_departed` | 1 event, 2026-06-30 | 0.5^(42/90)=0.7236 | **−7.24** |
| `unsubscribed_or_bounced` | 1 event, 2026-03-15 | 0.5^(149/365)=0.7535 | **−6.78** |

**Total:**
```
+24.00 +14.95 +9.36 +5.79 +6.00 +6.00 +3.63 +4.16  =  +73.89
                                    −7.24 −6.78     =  −14.02
                                    points          =   59.87
```

**Confidence:** 10 distinct signal types (≥5 ✓), freshest evidence 2 days old (≤14 ✓), `data_completeness` = 5/5 = 1.00 (≥0.8 ✓) → **`high`**.
**Band:** `59.87 ≥ 45.0` and confidence is `high` → **`ACT_NOW`**.

### 4.5 Reason ranking and the truncation rule

**Ranking.** All surviving reasons sorted by `abs(points)` DESC, tie-broken by `newest_event_at` DESC, then `signal_type_id` ASC. `rank` is written 1..N.

Kestrel's ranking:

| rank | code | points |
|---|---|---|
| 1 | `product_usage_active` | +24.00 |
| 2 | `pricing_page_repeat` | +14.95 |
| 3 | `senior_buyer_engaged` | +9.36 |
| 4 | `champion_departed` | −7.24 |
| 5 | `unsubscribed_or_bounced` | −6.78 |
| 6 | `icp_industry_match` | +6.00 |
| 7 | `icp_size_match` | +6.00 |
| 8 | `new_hire_icp_role` | +5.79 |
| 9 | `third_party_intent_6sense` | +4.16 |
| 10 | `tech_stack_match` | +3.63 |

**The truncation rule** (implication #2 — ceiling 5, floor 3, no expander):

```
P = positive reasons, ranked
N = negative reasons, ranked

shown  = P[:3]                            # step 1: at most 3 positives first
shown += N[:2]                            # step 2: reserve up to 2 slots for negatives
if len(shown) < 5:                        # step 3: backfill from positives only
    shown += P[3 : 3 + (5 - len(shown))]
    # hard sub-cap: never more than 4 positives in the shown set
    while count_positive(shown) > 4:
        drop the lowest-|points| positive
assert len(shown) <= 5
# step 4: floor
# if fewer than 3 reasons exist above the 0.5 floor, show all of them and
# confidence is already 'low' or 'insufficient' by §8.7 — do not pad
```

Step 2 runs before step 3 by design. Implication #7: a one-sided justification reads as a sales pitch from the product; a two-sided one reads as an assessment. Negatives therefore take their reserved slots even when weaker than the 4th and 5th positives — which is exactly what happens at Kestrel, where `champion_departed` (−7.24) is shown while `icp_industry_match` (+6.00) is not.

The sub-cap of 4 positives means an account with zero negatives shows 4 positives, not 5. The fifth slot exists to hold a negative; when there is no negative to hold, leaving it empty is more honest than filling it with the next-weakest positive.

**Kestrel shown set:** ranks 1, 2, 3 (positives) + ranks 4, 5 (negatives) = 5 reasons.
**Kestrel withheld:** ranks 6–10, worth `6.00 + 6.00 + 5.79 + 4.16 + 3.63 = +25.58` combined.

`reasons` rows are written for **all 10**, with `shown = 1` for ranks 1–5 and `shown = 0` for ranks 6–10. Unshown rows exist for `/metrics`, for RevOps audit, and so test T07 can assert the sum. **They are never rendered to the rep, under any interaction.** No expander, no hover, no "show all". That is implication #2 taken literally.

### 4.6 The honest-limits line (implication #8)

Every warrant carries exactly one `limits_line`, generated mechanically. Two variants, selected by whether hiding the withheld reasons would change the band:

```
shown_points   = sum(r.points for r in shown)
withheld       = [r for r in all_reasons if r not in shown]
withheld_sum   = sum(r.points for r in withheld)
band_if_shown_only = band_from(shown_points, confidence)

if not withheld:
    limits_line = "These are all {n} signals we found for this account."

elif band_if_shown_only == band:
    limits_line = ("Showing the {k} strongest of {n} signals. The {m} not shown are "
                   "worth {withheld_sum:+.1f} pts combined; they do not change the band.")

else:
    limits_line = ("Showing the {k} strongest of {n} signals. The {m} not shown are worth "
                   "{withheld_sum:+.1f} pts combined and are part of why this is {band} — "
                   "the {k} shown alone would rate {band_if_shown_only}.")
```

For Kestrel: `shown_points = 24.00 + 14.95 + 9.36 − 7.24 − 6.78 = 34.29`, which is below the 45.0 `ACT_NOW` threshold → `band_if_shown_only = REVIEW` → **variant 3**:

> *Showing the 5 strongest of 10 signals. The 5 not shown are worth +25.6 pts combined and are part of why this is ACT NOW — the 5 shown alone would rate REVIEW.*

This is the line Einstein's docs bury in a help article ("fields that aren't listed in the Einstein Score component still influence the score"). Warrant puts it under the reasons, in the record, in the rep's sentence, with the number. Implication #8 is explicit that overclaiming is what makes the second wrong lead fatal to trust; a rep who has read this line once will not feel deceived when the arithmetic does not visibly add up on screen.

A suppression appends a second clause: `Suppressed by you: "Third-party intent (6sense)".`

---

## 5. Score presentation

### 5.1 The decision

**Warrant shows signed evidence points against a fixed published anchor, plus a named band. It does not show a percentile, a 0–100 normalised score, or a probability.**

Rendered form, exactly:

```
ACT NOW · 60 pts    (bar for ACT NOW is 45 · scale anchored at 75)
```

`points` is rendered as a rounded integer with a sign only when negative. `59.87 → 60`. The two-decimal value stays in the DB for the arithmetic and appears in the evidence drawer.

### 5.2 Why not the three alternatives

**Not a percentile (Common Room).** Common Room's final score is a percentile against all other records, refreshed every 4 hours. Brief §4 states the problem precisely: *"a '90' means top decile today, which is not what a rep intuitively reads."* Worse for adoption — an account whose evidence has not changed at all can drop 20 points overnight because someone else's accounts got hotter. A rep who works a "92" on Monday and finds it a "71" on Wednesday, with no new facts, has learned that the number is not about the account. That is an unrecoverable trust event.

**Not a normalised 0–100 (MadKudu).** Normalisation buys comparability and costs meaning. Brief §2.2 gives the failure verbatim: *"a score of 82 in a HubSpot contact record tells an SDR nothing useful."* An 82 is not checkable against anything. `60 pts` is: the rep can look at `+24`, `+15`, `+9`, `−7`, `−7` on screen and see where 60 came from — modulo the withheld 25.6, which §4.6 discloses. Checkability is the whole product.

**Not a probability (HubSpot).** HubSpot's "likelihood to close" is a percentage chance of closing within 90 days, produced by what its own knowledge base calls *"blackbox machine learning"* where *"it's not possible to know exactly how each input contributes."* Warrant has no closed-won/closed-lost training data and no calibration, so a probability would be a fabricated claim of precision. Under finding 2.1 — the rep is the buyer's validation layer — handing them an uncalibrated percentage they will repeat in a call is actively harmful.

### 5.3 The anchor

`anchor_points = 75.0`, stored on `score_runs`, shown in the scale line, and explained on `/ruleset` as: *"75 is the point total a strong, current, multi-signal account reaches. It is a fixed bar set by RevOps, not a maximum and not a percentile. An account can exceed it."*

The anchor is not used in any arithmetic. It exists purely to give `60 pts` a referent, which is the thing a bare `82` lacks. Points above 75 render as `82 pts (above anchor)`.

### 5.4 The bands

| Band | Threshold on `points` | Chip text | Rep-facing meaning |
|---|---|---|---|
| `ACT_NOW` | ≥ 45.0, confidence `high` or `medium` | **ACT NOW** | Multiple current signals and someone who can sign. Work it today. |
| `REVIEW` | ≥ 25.0, or ≥ 45.0 with low confidence | **REVIEW** | Real signals, but thin, old, or contradicted. Read the evidence before you spend time. |
| `HOLD` | ≥ 5.0 | **HOLD** | Something is here, not enough to act on. |
| `INSUFFICIENT_EVIDENCE` | confidence `insufficient` | **NOT ENOUGH TO SAY** | We do not know enough about this account to rank it. That is a data gap, not a verdict. |

The band is the primary object; the points are secondary, smaller, and to the right. The reason is above both. Ordering on screen is deliberate and stated in §6: **evidence first, priority second** (brief §5).

`NOT ENOUGH TO SAY` is worded as a first-person admission rather than a category label. "Insufficient evidence" reads as a judgement on the account; "not enough to say" reads as a limit on us, which is what it is.

---

## 6. What a rep sees

Server-rendered HTML from `http.server`. No client framework, no build step. Progressive-enhancement only: every action is a real `<form>` POST, so it works with JavaScript off.

### 6.1 Queue view — `GET /queue?rep=1`

Layout, top to bottom:

1. **Header:** `Warrant · Dana Whitfield · NA-MidMarket` — plain text.
2. **Run stamp:** `Scored 11 Aug 2026, 09:00 UTC · ruleset warrant-v1.0.0 · 55 accounts` — plain text. Implication #10: Einstein rescores every 10 days and Common Room every 4 hours; a rep who cannot see when the ranking was computed cannot tell whether it is stale. The stamp is always visible.
3. **Adjustment budget bar:** `Your adjustments: pins 2/5 · demotes 1/10 · suppressed signals 1/3 · muted 4/25` — plain text, each count a link to `/adjustments?rep=1`.
4. **Rows**, in `rank_in_queue` order.

Per row, in this order:

| Element | Type | Content |
|---|---|---|
| Rank | plain text | `1.` |
| Band chip | plain text chip | `ACT NOW` |
| Account name | **link** → `/account/{id}?rep=1` | `Kestrel Analytics` |
| Points | plain text, right-aligned | `60 pts` |
| Top reason | plain text, truncated to 120 chars at a word boundary with `…` | rank-1 reason `text` |
| Freshness chip | plain text chip | `evidence 2d old` / `STALE · 47d` / `no evidence` |
| Adjustment chip | plain text chip, present only when `adjustment_flags` non-empty | `PINNED BY YOU` / `DEMOTED BY YOU` / `ADJUSTED · 1 signal suppressed` |
| Compressed limits | plain text, small | `5 of 10 signals shown` |
| `Work it` | **button** (POST `/task`, `accepted`) | disabled with a tooltip when `requires_evidence_review()` is true and no `evidence_opened` is logged (§6.4) |
| `Not now` | **button** (POST `/task`, `skipped`) | |
| `Dispute` | **link** → `/account/{id}?rep=1#dispute` | Item-scoped disputes need the evidence in view first |

Literal rendered output, first four rows:

```
Warrant · Dana Whitfield · NA-MidMarket
Scored 11 Aug 2026, 09:00 UTC · ruleset warrant-v1.0.0 · 55 accounts
Your adjustments: pins 2/5 · demotes 1/10 · suppressed signals 1/3 · muted 4/25

────────────────────────────────────────────────────────────────────────────
1.  [ACT NOW]  Kestrel Analytics                                     60 pts
    VP Engineering and 2 others used the product across 3 sessions,
    most recently 2 days ago.
    [evidence 2d old]                                    5 of 10 signals shown
    ( Work it )  ( Not now )  Dispute
────────────────────────────────────────────────────────────────────────────
2.  [ACT NOW]  Halcyon Freight  [PINNED BY YOU]                      52 pts
    Priya Raman bought from us before and started at Halcyon Freight
    on 22 Jul 2026.
    [evidence 6d old]                                     4 of 6 signals shown
    ( Work it )  ( Not now )  Dispute
────────────────────────────────────────────────────────────────────────────
3.  [REVIEW]   Bramble Labs  [ADJUSTED · 1 signal suppressed]        31 pts
    Director of Data — senior enough to sign — has engaged 2 times,
    last 9 days ago.
    [evidence 9d old]                                     5 of 8 signals shown
    ( Work it )  ( Not now )  Dispute
────────────────────────────────────────────────────────────────────────────
4.  [NOT ENOUGH TO SAY]  Verdant Systems                              8 pts
    We have one signal for this account and no contact at director
    level or above. Not enough to rank it.
    [no recent evidence]                                  1 of 1 signal shown
    ( Work it )  ( Not now )  Dispute
────────────────────────────────────────────────────────────────────────────
```

Row 3 shows the rep's own hand: they suppressed a signal type, the score reflects it, and the chip says so. That visibility is implication #6's "make the adjustment visible" — an adjustment the rep cannot see working is indistinguishable from one that was ignored.

### 6.2 Detail view — `GET /account/1042?rep=1`

Order on screen is **evidence first, priority second** (brief §5). The reasons are above the fold; the band and points sit in a compact strip beneath the account name, not in a hero position.

Field-by-field:

| Block | Element | Type |
|---|---|---|
| Header | Account name, domain, industry, headcount, HQ | plain text; domain is selectable text, not a link (no outbound network) |
| Header | CRM status + owner | plain text |
| Verdict strip | Band chip, points, threshold, anchor | plain text |
| Verdict strip | `rank 1 of 55` and, if different, `(was 3 before your adjustments)` | plain text |
| Reasons | Per reason: category tag, sentence, evidence line, points, `see evidence` link, `this is wrong` button | see below |
| Limits | `limits_line` | plain text, always present |
| Adjust | `Pin` / `Demote` / `Mute` buttons + budget counts | buttons (POST `/adjust`) |
| Your history | Every prior dispute and adjustment on this account by this rep | plain text + `Undo` buttons |
| Research | Up to 3 `observations`, each with `retrieved_at` and `source_name` | plain text; `see all research` link → `/evidence/observations/{account_id}` |
| Footer | `How the weights are set` | link → `/ruleset` |

Per reason, the element order is fixed and matters: **category tag → sentence → evidence line → points → actions.** The point value comes after the evidence, never before it. Implication #3 governs the ordering — the rep should read what happened before they read what it was worth.

Literal rendered output for Kestrel Analytics:

```
Kestrel Analytics · kestrelanalytics.io
Data & Analytics · 420 employees · US · CRM: no record · owner: you

  [ACT NOW]   60 pts        bar for ACT NOW is 45 · scale anchored at 75
  rank 1 of 55              confidence: high

WHY THIS IS AT THE TOP
────────────────────────────────────────────────────────────────────────────
ACTIVE EVALUATION
  VP Engineering and 2 others used the product across 3 sessions,
  most recently 2 days ago.
  28 sessions between 28 Jul 2026 and 9 Aug 2026 · source: product telemetry
                                                       +24 pts (capped at 24)
  see evidence        ( this is wrong )
────────────────────────────────────────────────────────────────────────────
ACTIVE EVALUATION
  VP Engineering viewed /pricing 3x, most recently 2 days ago (9 Aug 2026).
  2 visits to /pricing between 5 Aug 2026 and 9 Aug 2026 · source: website
                                                                    +15 pts
  see evidence        ( this is wrong )
────────────────────────────────────────────────────────────────────────────
AUTHORITY
  VP Engineering — senior enough to sign — has engaged 1 time,
  last 2 days ago.
  1 touch on 9 Aug 2026 · source: website
                                                                     +9 pts
  see evidence        ( this is wrong )
────────────────────────────────────────────────────────────────────────────
DISQUALIFIER
  Marcus Iwu, our contact here, left on 30 Jun 2026. The relationship
  left with them.
  Job change detected 30 Jun 2026 · source: job change feed
                                                                     −7 pts
  see evidence        ( this is wrong )
────────────────────────────────────────────────────────────────────────────
DISQUALIFIER
  Marcus Iwu unsubscribed or hard-bounced on 15 Mar 2026. Email is
  closed here.
  1 event on 15 Mar 2026 · source: email platform
                                                                     −7 pts
  see evidence        ( this is wrong )
────────────────────────────────────────────────────────────────────────────

Showing the 5 strongest of 10 signals. The 5 not shown are worth +25.6 pts
combined and are part of why this is ACT NOW — the 5 shown alone would
rate REVIEW.

ADJUST YOUR QUEUE          pins 2/5 · demotes 1/10 · muted 4/25
  ( Pin to top · 14 days )  ( Demote · 30 days )  ( Mute · 60 days )

DISAGREE WITH THE WHOLE ITEM
  ( Not a fit )  ( Wrong person )  ( Bad timing )  ( Already working this )
  ( Not my patch )

YOUR HISTORY ON THIS ACCOUNT
  Nothing yet.

AGENT RESEARCH  (3 observations)
  · Posted two senior data-platform roles in the last three weeks.
    Company careers page · retrieved 28 Jul 2026
  · Migrated from Redshift to Snowflake per an engineering blog post.
    Engineering blog · retrieved 21 Jul 2026
  · Named a new Head of Data in a June press release.
    Press release · retrieved 3 Jul 2026
  see all research

How the weights are set
```

Note the rendered points: `+24 pts (capped at 24)` on reason 1. When a signal type hits its `max_contribution`, the cap is disclosed inline. Without it, a rep who compared two accounts with wildly different usage volumes and identical `+24` would conclude the number was made up. The cap is a real property of the model and hiding it would be the beginning of the MadKudu decoupling problem.

Both negatives round to `−7 pts` (−7.24 and −6.78). That is fine and expected; the two-decimal values are in the evidence drawer.

### 6.3 Evidence drawer — `GET /evidence/{reason_id}?rep=1`

Fires a `evidence_opened` `task_event`. Renders every row in `reason_evidence` joined to `signal_events`:

```
EVIDENCE · Repeat pricing-page visits · Kestrel Analytics
Reason computed 11 Aug 2026 09:00 UTC from 2 events. Total +14.95 pts (cap +18.00).

  9 Aug 2026 14:22 UTC   /pricing   2 views   +9.01 pts
    person: Ana Belic, VP Engineering
    source: website_tracker · ingested 9 Aug 2026 15:03 UTC (41 min later)
    ref: https://app.example.test/sessions/ws_88213

  5 Aug 2026 09:47 UTC   /pricing   1 view    +5.94 pts
    person: Ana Belic, VP Engineering
    source: website_tracker · ingested 5 Aug 2026 10:11 UTC (24 min later)
    ref: https://app.example.test/sessions/ws_87004

Source links are shown as text — this environment has no outbound network.

  ( this reason is wrong )   ( this evidence is out of date )   ( wrong person )
```

`observed_at` is rendered alongside `occurred_at` with the lag computed. Ingestion lag is exactly the kind of thing that makes a rep say "the system said they visited today but they visited yesterday" and stop trusting the whole surface. Showing both removes the ambiguity.

### 6.4 The friction decision (implication #12)

**Decided: friction on a narrow, defined class; none elsewhere.**

```python
def requires_evidence_review(account, score, rep_id) -> bool:
    return (
        (account.crm_status == 'open_opportunity' and account.owner_rep_id != rep_id)
        or has_open_dispute(rep_id, account.account_id)
    )
```

When true, `Work it` is rendered disabled with the plain-text line:
`Open evidence on one reason before working this — there is an open opportunity here owned by Sam Okafor.`
or
`Open evidence on one reason before working this — you disputed a reason on this account on 4 Aug 2026.`

The button enables as soon as one `evidence_opened` event exists for this `(rep, account, run)`.

**Why this and not more.** Buçinca, Malaya and Gajos showed cognitive forcing functions reduce overreliance on AI, and the paper is explicit that the designs which reduced overreliance most were also rated least favourably by participants (brief §3.5). The brief's own steer, implication #12: for high-value accounts a review-before-enrolling step may be warranted; for volume outbound it almost certainly is not. Warrant applies friction only where acting blind has a cost outside the rep's own time — stepping on a colleague's open deal — or where it contradicts something the rep themselves already said. Both are narrow. On the seeded data the predicate is true for roughly 4–6% of queue items. The predicate is two clauses and will stay two clauses; any addition is a product decision, not a build decision.

**Why not more, specifically:** applying forcing to all `ACT_NOW` items would tax the exact workflow the product exists to speed up, and the evidence says reps would resent it. Trading measured dislike for unmeasured error reduction across 100% of items is not a trade this spec makes.

### 6.5 Ruleset page — `GET /ruleset`

Renders `signal_types` in full: code, display name, category, polarity, weight, cap, half-life, and the live dispute rate per type (§7.5). Header line, verbatim:

> *This is how the weights are set, and how often reps disagree with each one. It is not why any particular account ranked where it did — that is on the account's own page.*

That sentence exists because of implication #1. A global model explanation is a RevOps artifact; the brief's §3 synthesis is explicit that it does nothing for the rep looking at one account. The page is reachable only from a small footer link on the detail view, never from the queue, and it is never a substitute for per-lead reasons.

---

## 7. Disagreement, override and feedback

This is the section that occupies the position brief §4 identifies as unoccupied, and implication #6 calls *"the single highest-leverage requirement in this list."* It is specified in the most detail because it is the part that must not be invented at build time.

### 7.1 The seven reason codes

| Code | Scope | Label shown to rep | When a rep uses it |
|---|---|---|---|
| `NOT_A_FIT` | item | `Not a fit` | Wrong company for this product, regardless of activity |
| `WRONG_PERSON` | item or reason | `Wrong person` | The person cited is not a buyer for this |
| `BAD_TIMING` | item | `Bad timing` | Real, but not now |
| `ALREADY_WORKING` | item | `Already working this` | Duplicate of the rep's own live effort |
| `EVIDENCE_WRONG` | reason | `This is wrong` | The stated fact is factually incorrect |
| `EVIDENCE_STALE` | reason | `Out of date` | True once, not now |
| `NOT_MY_PATCH` | item | `Not my patch` | Ownership or territory error |

The first four are the minimum the brief requires (implication #5: *"not a fit / wrong person / bad timing / already working this"*). The last three exist because Warrant makes the *reason* disputable, not just the item — which is the unoccupied position — and a rep disputing a reason means one of three distinguishable things: the fact is wrong, the fact is old, or the fact is about the wrong human. Collapsing those into one code would throw away the information RevOps needs to fix the ruleset.

### 7.2 Code → effect mapping

Every code produces a mechanical, bounded, visible change. **There is no code that logs and does nothing** — implication #11 is explicit that if disagreement changes nothing, reps stop registering it within weeks.

| Code | Rows written | Adjustment created | Window | What the rep sees immediately |
|---|---|---|---|---|
| `EVIDENCE_WRONG` | `disagreements` (scope=reason, `signal_type_id` set) | `suppress_signal_type` **scoped to this account** (`account_id` NOT NULL) | 90 days | Reason struck through with `disputed by you, 11 Aug 2026`; points recomputed; band and rank update on the same page render; `ADJUSTED` chip appears in the queue |
| `EVIDENCE_STALE` | `disagreements` (scope=reason) | `suppress_signal_type` scoped to this account | 30 days | Same, with `marked out of date by you, 11 Aug 2026` |
| `WRONG_PERSON` | `disagreements` (scope=reason, `person_id` set) | `exclude_person` | 90 days | All reasons drawing on that person recompute without their events; the person is greyed in the research block |
| `NOT_A_FIT` | `disagreements` (scope=item) | `mute_account` | 60 days | Account leaves the queue on next render; a confirmation line gives the return date and an `Undo` |
| `BAD_TIMING` | `disagreements` (scope=item) | `demote` | rep picks 14 / 30 / 90 days, default 30 | Account drops below all non-demoted items; `DEMOTED BY YOU · returns 10 Sep 2026` chip |
| `ALREADY_WORKING` | `disagreements` (scope=item) | `mute_account` | 21 days | Account leaves the queue; confirmation names the return date |
| `NOT_MY_PATCH` | `disagreements` (scope=item) | `mute_account` | 365 days | Account leaves the queue; the dispute is flagged on `/metrics` under `Ownership errors` for RevOps |

Every dispute also writes a `task_events` row with `event_type='disputed'`, `rank_at_event` and `detail_json` carrying the code and the signal type code.

Both suppression variants exist because they answer different questions. `EVIDENCE_WRONG` on Kestrel's `pricing_page_repeat` means *this particular claim about this account is false* — it should not silently switch off pricing-page evidence across the rep's whole patch. Patch-wide suppression is a separate, deliberate, more expensive action (§7.3), because it is a bigger claim.

### 7.3 The bounded lever — exactly what "bounded" means

Dietvorst, Simmons and Massey found the adoption effect **held even when modification was severely restricted** (brief §3.3). That finding licenses tight budgets rather than generous ones, and this spec takes the licence: the point is that the rep *can* move the output, not that they can move it far.

**Five kinds. Every one has a hard numeric budget, a mandatory expiry, and one-click revert.**

| Kind | Budget (active, per rep) | Expiry | Effect on `points` | Effect on `rank_in_queue` |
|---|---|---|---|---|
| `pin` | **5** | 14 days | none | Pinned accounts occupy ranks 1..k, ordered by `points` among themselves |
| `demote` | **10** | 14/30/90 days, rep's choice | none | Demoted accounts sort last, after every non-demoted item, ordered by `points` among themselves |
| `mute_account` | **25** | 21/60/365 days by code | none | Removed from the queue entirely; still reachable by direct URL and search |
| `suppress_signal_type`, patch-wide (`account_id IS NULL`) | **3** | 30 days | That signal type contributes 0 for **every** account in this rep's queue | Follows from the points change |
| `suppress_signal_type`, account-scoped (`account_id` set) | **50** | 30 or 90 days by code | That signal type contributes 0 for that one account | Follows from the points change |
| `exclude_person` | **50** | 90 days | That person's events contribute 0 for that account | Follows from the points change |

**Enforcement, server-side, in `queue.py`:**

```python
BUDGETS = {'pin': 5, 'demote': 10, 'mute_account': 25,
           'suppress_signal_type_global': 3,
           'suppress_signal_type_account': 50,
           'exclude_person': 50}

def create_adjustment(conn, rep_id, kind, ..., as_of):
    key    = budget_key(kind, account_id)
    active = count_active(conn, rep_id, key, as_of)   # is_active=1 AND expires_at > as_of
    if active >= BUDGETS[key]:
        raise BudgetExceeded(key, active, BUDGETS[key])   # -> HTTP 409
    ...
```

An exceeded budget returns HTTP 409 and renders, literally:

> *You already have 5 pins. Pins expire on their own — your oldest expires on 18 Aug 2026 — or unpin one now. [ view your pins ]*

Refusing rather than silently dropping the oldest is deliberate. A budget the rep can exceed without noticing is not a bound, and a lever that quietly discards the rep's input is worse than no lever.

**Three invariants the build must hold, all testable:**

1. **No adjustment is permanent.** `expires_at` is `NOT NULL` and expiry is evaluated at read time against `as_of`, not by a background job. There is no cron in this environment and an unexpired-forever suppression is a silent, invisible model change.
2. **No adjustment crosses reps.** Every adjustment query filters `rep_id = :rep_id`. Rep 2's queue is byte-identical whether or not rep 1 has suppressed anything. Test T10 asserts this.
3. **No adjustment changes the ruleset.** `signal_types` is never written by any rep-facing route. Rep input reaches the weights only through `/metrics` and a human RevOps decision.

**Reverting.** Every active adjustment appears in `Your history` on the detail view and in `/adjustments?rep=1`, each with an `Undo` button. `POST /adjust/revert` sets `is_active=0`, `reverted_at`, moves the linked `disagreements.status` to `reverted`, and writes a `task_events` row with `event_type='reverted'`. Revert rate is a shipped metric (§7.5): a high one means the effects are too blunt, and that is a signal about the design, not about the rep.

### 7.4 What visibly changes, and how fast

The single most important behaviour in this spec: **the effect is visible on the very next render, in the same request cycle.** `POST /dispute` writes its rows, then redirects to `GET /account/{id}?rep={rep}&disputed={disagreement_id}`, which triggers a fresh score run with the new adjustment in force. The rep sees the reason struck through, the points drop, and the band change, immediately.

Kestrel, after the rep disputes `pricing_page_repeat` with `EVIDENCE_WRONG`:

```
  [ACT NOW]   45 pts        was 60 pts before your disagreement
  rank 3 of 55              was rank 1

────────────────────────────────────────────────────────────────────────────
ACTIVE EVALUATION
  ~~VP Engineering viewed /pricing 3x, most recently 2 days ago.~~
  You said this was wrong on 11 Aug 2026. Not counted here until
  9 Nov 2026.                                                    +15 → 0 pts
  ( undo )
────────────────────────────────────────────────────────────────────────────

Showing the 5 strongest of 10 signals. The 5 not shown are worth +25.6 pts
combined and are part of why this is ACT NOW — the 5 shown alone would
rate REVIEW. Suppressed by you: "Repeat pricing-page visits".

YOUR HISTORY ON THIS ACCOUNT
  11 Aug 2026 · you said "Repeat pricing-page visits" was wrong.
               Suppressed for this account until 9 Nov 2026.  ( undo )
```

The disputed reason stays on screen, struck through, in its slot — it is not deleted and it is not replaced by the next-ranked reason. The rep needs to see that the thing they objected to is the thing that went away. Silently backfilling the slot would make the disagreement feel unregistered, which is precisely the failure implication #11 warns about.

`points_before_adjustment` (60) and `points` (45) are both stored, so the `was 60 pts` line is not reconstructed from memory.

### 7.5 Instrumentation — `GET /metrics`

All computed by live SQL over `task_events`, `disagreements` and `queue_adjustments`. Window: trailing 30 days from `as_of`.

| Metric | Definition | Rendered as |
|---|---|---|
| **Top-3 acceptance rate** | `accepted` events with `rank_at_event <= 3` ÷ distinct top-3 items rendered | `61.4% — no target set; v1 establishes baseline` |
| **Reason dispute rate, per signal type** | disputes scoped to that type ÷ times that type was `shown=1` in a rendered warrant | table, sorted desc |
| **Evidence-open rate** | distinct `(rep, account)` with an `evidence_opened` ÷ distinct `item_viewed` | `34.2%` |
| **Item dispute rate** | item-scoped disputes ÷ `item_viewed` | `9.1%` |
| **Suppression rate, per signal type** | distinct reps with an active suppression of that type ÷ reps who saw it | table |
| **Revert rate** | `reverted` ÷ `adjusted` | `7.8%` |
| **Ownership errors** | count of `NOT_MY_PATCH` disputes, by account | list — a data-quality queue for RevOps |
| **Skip-with-no-dispute rate** | `skipped` with no dispute in the same session ÷ `skipped` | `— reps who skip without telling us why are the ones we are losing` |

**The flag rule.** A signal type disputed by more than **20% of the reps who saw it**, over at least **30 shows**, in 30 days, is rendered on `/ruleset` as `REVIEW REQUIRED — 4 of 4 reps have disputed this`. It is a flag for a human, never an automatic weight change. Auto-tuning weights from rep disputes would let four reps quietly rewrite the model with no audit trail and no one accountable for it, and it would break implication #9's guarantee that the reason a rep reads is the reason the system acted.

**On the target number.** The brief's implication #11 points at Pedowitz Group's suggested 65–75% MQL→SQL sales acceptance rate. This spec **rejects importing it** — see §2 row 11a. It measures a different handoff with a different denominator, and the brief's own §2.4 note is a warning about reusing figures whose provenance does not match the claim they are being used to support. `/metrics` renders top-3 acceptance with the target line blank and the words `v1 establishes baseline`.

---

## 8. Edge cases

Edge cases are where this product dies, so each is specified as compute / show / must-not.

The rule underneath all seven: **the system must never manufacture a confident reason from an absence.** Not knowing something is a fact about us, and it is rendered as one.

### 8.1 Thin data — 1 or 2 signal types, or `data_completeness < 0.4`

- **Computes:** points normally. `distinct_signal_types <= 2` → `confidence = 'insufficient'` → `band = 'INSUFFICIENT_EVIDENCE'` regardless of points. `no_buying_authority_present` fires only if `people` rows exist.
- **Shows:** `[NOT ENOUGH TO SAY]` chip, points still displayed, plus:
  `We have 1 signal for this account and no contact at director level or above. Not enough to rank it.`
  and: `What would change this: a named contact at director level or above, or any product or website activity.`
- **Must not:** show `ACT_NOW`. Must not render 3 reasons when only 1 exists. Must not pad with `fit` reasons to reach the floor of 3 — a fit match on an account with no behaviour is a statement about the segment, not the account. Must not fire `no_buying_authority_present` when zero people are on file.

The "what would change this" line is the only forward-looking copy in the product. It exists because `NOT ENOUGH TO SAY` with no path out reads as a dead end, and the rep will stop opening those items entirely.

### 8.2 Stale data — freshest evidence older than 30 days

- **Computes:** decay has already shrunk the points; no extra penalty is applied. Double-penalising staleness once through decay and again through a flat deduction makes the arithmetic on screen not add up. Age 30–45d → confidence capped at `medium`; >45d → capped at `low`, which via §4.2 blocks `ACT_NOW`.
- **Shows:** `STALE · 47d` chip in the queue row, and above the reasons:
  `No new evidence in 47 days. This ranking reflects activity that ended on 25 Jun 2026.`
  Each reason's evidence line already carries its own dates.
- **Must not:** use a relative phrase that hides age — never "recently" for anything over 14 days. `{newest_relative}` renders `"7 weeks ago"`, not `"recently"`. Must not present a stale account in `ACT_NOW`. Brief implication #10: *stale evidence presented as current is a trust event, not a data event.*

### 8.3 No signal at all — zero events, zero firing state signals

- **Computes:** `points = 0.0`, `distinct_signal_types = 0`, `freshest_evidence_at = NULL`, `confidence = 'insufficient'`, `band = 'INSUFFICIENT_EVIDENCE'`. A `scores` row is still written — the account exists and must be countable.
- **Shows:** ranked at the bottom, above muted items. One line where the reasons would be:
  `We have no signals for this account. It is here because it is assigned to you, not because we think it is a priority.`
  `limits_line` = `No signals found.` Adjust and dispute controls remain available.
- **Must not:** render an empty reasons block with no explanation. Must not synthesise a fit reason from `industry` alone if the industry field is NULL. Must not suppress the row silently — a rep who cannot see their unscored accounts will assume Warrant is hiding work from them.

### 8.4 Brand-new account — `first_seen_at` within 14 days

- **Computes:** points normally. Recency bias means small event counts still score. Confidence capped at `medium` for the first 14 days regardless of the §8.7 cascade, so a brand-new account cannot enter `ACT_NOW` on a single day of noise.
- **Shows:** `NEW · first seen 3 days ago` chip, and above the reasons:
  `First seen 3 days ago. We may be missing history that would change this.`
- **Must not:** treat absence of history as a negative. `no_engagement_90d` must not fire when `first_seen_at` is within 90 days of `as_of` — this is a required guard in the predicate, not an optional one. Penalising an account for not having existed long enough is the single most obvious way this model could produce a reason that is both arithmetically correct and visibly stupid.

### 8.5 Conflicting signals — strong positive and strong negative together

- **Computes:** nothing special. Both contribute, both survive the truncation rule (negatives have reserved slots, §4.5), the sum is the sum. Additional rule: if `max(positive points) >= 12` and `min(negative points) <= -7`, set `conflicted = True` for rendering.
- **Shows:** the band from the arithmetic, plus a line above the reasons:
  `These signals disagree. Strong current usage, but the contact who drove it has left. Read both before you act.`
  The template is `These signals disagree. {top_positive_short}, but {top_negative_short}. Read both before you act.`
- **Must not:** hide the negative to make the item look cleaner. Must not average the conflict away into a middling band with no explanation — a `REVIEW` with no visible tension is indistinguishable from a `REVIEW` with weak evidence, and they call for opposite rep behaviour. Implication #7 exists for exactly this shape of case: a one-sided justification reads as a sales pitch from the product.

### 8.6 A lead the rep has already disputed

Three sub-cases, all reachable in the seeded data.

**(a) Dispute active.** Suppression is in force. Reason renders struck through with the return date and `( undo )`. Band and points reflect the suppression. `requires_evidence_review()` returns true, so `Work it` needs one evidence open first (§6.4).

**(b) Dispute expired and the signal is firing again.** A banner above the reasons:
```
You said "Third-party intent (6sense)" was wrong here on 11 May 2026.
That suppression expired on 9 Aug 2026 and the signal is counting again.
( suppress for another 90 days )   ( leave it — it looks right now )
```
`leave it` writes a `disagreements` row with `status='reviewed'` and no adjustment, so the metric records that the rep looked and accepted. Silently resuming a signal the rep once rejected, with no notice, is the most direct way to teach them that disputes are theatre.

**(c) Rep disputed, then the underlying evidence changed.** New events arrived for a suppressed signal type after the dispute. The reason stays suppressed — the rep's decision stands for its full window — but the banner adds:
`3 new events for this signal since you disputed it (most recent 8 Aug 2026). ( see them )`
- **Must not:** auto-unsuppress because new data arrived. The rep set a window; the system honours it. Overriding a rep's override is the exact failure this whole section exists to prevent.

### 8.7 Freshness and confidence — the shared treatment

`data_completeness` = fraction of these five present, in fifths:
1. `accounts.industry` NOT NULL
2. `accounts.employee_count` NOT NULL
3. at least one `people` row with seniority ≥ `director`
4. `accounts.tech_stack` NOT NULL
5. `accounts.crm_status != 'none'` OR at least one `signal_events` row

Confidence cascade, **evaluated top to bottom, first match wins:**

```
insufficient  if distinct_signal_types < 2  or  data_completeness < 0.4
low           if freshest_evidence_age_days > 45  or  distinct_signal_types == 2
medium        if 3 <= distinct_signal_types <= 4
                 and freshest_evidence_age_days <= 45
                 and data_completeness >= 0.6
high          if distinct_signal_types >= 5
                 and freshest_evidence_age_days <= 14
                 and data_completeness >= 0.8
low           otherwise                       # explicit fallback, never None
```

Then, unconditionally: `if account_age_days < 14: confidence = min(confidence, 'medium')`.

Confidence is rendered as a bare word in the verdict strip (`confidence: high`) and never as a percentage. A percentage would be a second uncalibrated number on a page that already spent its credibility budget on the first one.

---

## 9. What the maker must build

### 9.1 Files

| Path | What it does |
|---|---|
| `db/schema.sql` | Every `CREATE TABLE` and `CREATE INDEX` from §3. Executed via `sqlite3.Connection.executescript()`. Indexes required at minimum on `signal_events(account_id, signal_type_id, occurred_at)`, `scores(run_id, rank_in_queue)`, `reasons(score_id, rank)`, `queue_adjustments(rep_id, is_active, expires_at)`, `task_events(rep_id, occurred_at)`. |
| `seed_db.py` | Creates `data/unify.db`, runs the schema, seeds `signal_types` from the §4.1 reference table, then **generates** all other rows programmatically per the §3 distributions with `random.seed(20260811)`. Idempotent: deletes and recreates the file. Prints a summary of the forced cohorts so they can be eyeballed. |
| `warrant/db.py` | `connect()` → `sqlite3.Connection` with `row_factory = sqlite3.Row` and `PRAGMA foreign_keys = ON`. DB path from `WARRANT_DB_PATH`, default `data/unify.db`. No ORM. |
| `warrant/scoring.py` | `score_account()`, `score_queue()`. The §4.2 arithmetic and the §4.1 state predicates. Runs live SQL per request. Returns `SignalContribution` dataclasses. |
| `warrant/reasons.py` | Template rendering (§4.3), ranking and truncation (§4.5), `limits_line` generation (§4.6), relative-date formatting. |
| `warrant/queue.py` | Ordering, adjustment application, budget enforcement (§7.3), `BudgetExceeded`. |
| `warrant/feedback.py` | Dispute writes and the §7.2 code→effect mapping. |
| `warrant/metrics.py` | The §7.5 SQL. |
| `warrant/render.py` | HTML rendering. Plain `str` templates, `html.escape` on every interpolated value. No f-string HTML without escaping. |
| `app.py` | `http.server.ThreadingHTTPServer`. Routes: `GET /`, `GET /queue`, `GET /account/{id}`, `GET /evidence/{reason_id}`, `GET /adjustments`, `GET /metrics`, `GET /ruleset`, `POST /dispute`, `POST /adjust`, `POST /adjust/revert`, `POST /task`. Port from `WARRANT_PORT`, default 8000. |
| `tests/test_scoring.py`, `tests/test_reasons.py`, `tests/test_queue.py`, `tests/test_feedback.py`, `tests/test_edge_cases.py` | `unittest`. Run with `python -m unittest discover tests`. |
| `.env.example` | `WARRANT_DB_PATH=data/unify.db`, `WARRANT_PORT=8000`, `WARRANT_SEED=20260811`, `WARRANT_AS_OF=2026-08-11T09:00:00Z`, `WARRANT_RULESET_VERSION=warrant-v1.0.0`. **Placeholder names only. No credentials anywhere in the repo — there is nothing to authenticate to.** |
| `README.md` | Two commands: `python seed_db.py`, then `python app.py`. Plus the §5 note on what the score does not claim. |

### 9.2 Hard build rules

1. **Python standard library only.** No third-party imports anywhere, including tests.
2. **Every score computed from a live query at request time.** No cached score literals, no hardcoded lead data in application code, no fixtures standing in for the DB. Tests may create their own temp DB via `seed_db` functions, never a hand-written list of dicts.
3. **No `sqlite3` CLI.** All DB access through Python's `sqlite3` module.
4. **No credentials, no API keys, no tokens in any file.**
5. **`signal_types` is never written by a rep-facing route.**
6. **Every SQL parameter is bound** (`?` placeholders). No string-interpolated SQL, including in `metrics.py`.

### 9.3 What the tests must prove

| ID | Assertion |
|---|---|
| **T01** | `seed_db.py` run twice produces byte-identical DB content for `accounts`, `people`, `signal_events` (fixed seed reproducibility). |
| **T02** | The §4.4 Kestrel worked example, constructed in a temp DB, produces `points == 59.87` (±0.01), `band == 'ACT_NOW'`, `confidence == 'high'`. |
| **T03** | `product_usage_active` at Kestrel is capped: raw 37.73 → stored `24.00`. |
| **T04** | Reasons below the 0.5-point floor produce no `reasons` row and contribute nothing. |
| **T05** | Truncation: `shown` count never exceeds 5; never more than 4 positives shown; where ≥1 negative exists above the floor, ≥1 negative is shown. Asserted across all 240 seeded accounts. |
| **T06** | Kestrel's shown set is exactly ranks 1,2,3,4,5 and `champion_departed` (−7.24) is shown while `icp_industry_match` (+6.00) is not. |
| **T07** | For every scored account: `sum(r.points for all reasons, shown and unshown) == score.points` (±0.01). This is the implication-#9 guarantee that the explanation is the model. |
| **T08** | `limits_line` variant selection: Kestrel yields the band-flip variant containing `"the 5 shown alone would rate REVIEW"`. An account with no withheld reasons yields the `"These are all N signals"` variant. |
| **T09** | Every rendered detail view contains a non-empty limits line. Asserted across all seeded accounts. |
| **T10** | Rep isolation: rep 1 creating a patch-wide suppression leaves rep 2's queue byte-identical to a control run. |
| **T11** | Banned-vocabulary check: no rendered reason, evidence line, band label, limits line or chip in the whole seeded corpus contains `engagement`, `engagement score`, `lead score`, `MQL`, `activity score`, `nurture`, `hand-raiser`, `propensity`, or `SHAP`. (Implication #4 and #3, made testable.) |
| **T12** | Budget enforcement: the 6th `pin` raises `BudgetExceeded` and the route returns HTTP 409; the 6th pin is not written. Same for each of the six budget keys. |
| **T13** | Expiry: an adjustment with `expires_at <= as_of` has no effect on `points` or ordering, without any background job running. |
| **T14** | Dispute effect: `EVIDENCE_WRONG` on Kestrel's `pricing_page_repeat` writes one `disagreements` row and one account-scoped `queue_adjustments` row, and the next scored run yields `points == 44.92` (±0.01) with the reason still present and flagged as disputed. |
| **T15** | Revert restores `points` to `59.87` (±0.01) and sets `disagreements.status = 'reverted'`. |
| **T16** | Every one of the seven codes in §7.1 produces at least one `queue_adjustments` row or, for `leave it`, a `status='reviewed'` row. No code is a no-op. |
| **T17** | Edge cases, one test each: zero-event account → `INSUFFICIENT_EVIDENCE` with a `scores` row and the no-signals line; `no_engagement_90d` does not fire on an account first seen 20 days ago; `no_buying_authority_present` does not fire on an account with zero `people` rows; an account with freshest evidence 47 days old never renders `ACT_NOW`; a conflicting account renders the `"These signals disagree"` line. |
| **T18** | `requires_evidence_review()` is true for an account with `crm_status='open_opportunity'` owned by another rep, false for a plain `ACT_NOW` account, and true for an account with an open dispute. |
| **T19** | No module in `warrant/`, `app.py`, `seed_db.py` or `tests/` imports a non-stdlib package. Asserted by walking `ast` over every `.py` file in the repo. |
| **T20** | No SQL string in the codebase contains an f-string or `%` interpolation of a value. Asserted by `ast` inspection of every call to `Cursor.execute`. |

---

## 10. Open questions for the next stage

Named rather than assumed, per the researcher's own practice.

1. **Does Unify ship an undocumented internal score?** The brief's appendix is explicit that this must be confirmed internally and could not be verified externally. §1.3 makes the spec hold either way, but if the answer is yes, `signal_types` needs one more row and `/ruleset` needs one more paragraph explaining what that row is and why it is weighted where it is.
2. **Verbatim rep language for microcopy.** Brief §2.2, "gap in my evidence": the practitioner evidence is vendor-adjacent consultancy writing, not raw community voice, and r/sales, RevGenius and Pavilion threads could not be surfaced. Every reason template and every chip label in §4.3 and §6 is my composition, not a rep's. They are structurally correct — qualification vocabulary, consequence-bearing, no marketing language — but they have not been checked against how a rep actually talks. That is a live research task and the templates live in `signal_types.reason_template` precisely so they can be rewritten without a code change.
3. **The weights themselves.** `product_usage_active` at +12.0 traces to Unify's published 9.1% positive-reply benchmark (brief §1). The other 18 are reasoned, not measured. `/metrics` is the instrument for correcting them, and §7.5's flag rule is the mechanism, but v1 ships with weights that are defensible rather than validated. `/ruleset` should say so in one line.
4. **The points-on-reason deviation (§2, row 3).** I have taken a knowing deviation from implication #3's absolutism. If usability testing shows reps anchoring on `+24 pts` and skipping the evidence sentence, the fix is to hide per-reason points and keep the total — and that is a one-line render change, deliberately.
