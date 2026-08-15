"""The model. DESIGN_SPEC.md §4.

There is exactly one code path (implication #9): score_account() returns a list
of SignalContribution objects; the score is sum(c.points) and the reasons are
rendered from that same list by reasons.py. It is not possible to produce a
reason that did not contribute points, or a point that produced no reason.

Weights live in the signal_types table, not in Python constants, so the
explanation and the arithmetic cannot drift apart. What lives here is only what
the spec says lives here: the arithmetic of §4.2 and the named state predicates
of §4.1, resolved from signal_types.state_predicate.

Every SQL parameter is bound with ? placeholders.
"""

import json
from dataclasses import dataclass, field
from math import log10

from warrant.timeutil import age_days, parse_ts, shift

# --- Reference constants for the state predicates (DESIGN_SPEC.md §3.13) -----
# These are model definition, not lead data.
ICP_INDUSTRIES = ("SaaS", "Data & Analytics", "Fintech", "Developer Tools", "Cybersecurity")
ICP_SIZE_MIN = 50
ICP_SIZE_MAX = 5000
ICP_TECH_MARKERS = ("Snowflake", "dbt", "Segment", "Databricks", "Fivetran")
ICP_TARGET_DEPARTMENTS = ("engineering", "data", "revops", "product")
SENIOR_LEVELS = ("director", "vp", "c_level", "founder")

POINT_FLOOR = 0.5              # §4.2 "Floor"
ACT_NOW_THRESHOLD = 45.0       # §4.2 "Band"
REVIEW_THRESHOLD = 25.0
HOLD_THRESHOLD = 5.0
CONFLICT_POSITIVE = 12.0       # §8.5
CONFLICT_NEGATIVE = -7.0
STALE_DAYS = 30                # §8.2
BRAND_NEW_DAYS = 14            # §8.4
NO_ENGAGEMENT_WINDOW_DAYS = 90 # §4.1 / §8.4 guard

CONFIDENCE_ORDER = ("insufficient", "low", "medium", "high")


@dataclass
class EventContribution:
    """One signal_events row's signed points, before the type-level cap."""
    event_id: int
    person_id: int
    occurred_at: str
    observed_at: str
    source: str
    magnitude: float
    detail: dict
    source_url: str
    contribution: float


@dataclass
class SignalContribution:
    """One signal type's total contribution to one account's warrant."""
    signal_type_id: int
    code: str
    display_name: str
    category: str
    polarity: str
    kind: str
    base_weight: float
    max_contribution: float
    half_life_days: float
    points: float                      # effective, post-adjustment. T07 sums this.
    points_before_adjustment: float    # ignoring this rep's adjustments
    cap_applied: bool
    is_suppressed: bool
    event_count: int
    newest_event_at: str
    oldest_event_at: str
    source_names: list
    events: list = field(default_factory=list)
    field_value: str = ""              # state signals: the field the predicate read
    top_person: dict = None
    other_user_count: int = 0


@dataclass
class AccountScore:
    account_id: int
    rep_id: int
    as_of: str
    points: float
    points_before_adjustment: float
    band: str
    confidence: str
    distinct_signal_types: int
    freshest_evidence_at: str
    data_completeness: float
    contributions: list
    adjustment_flags: list
    account: dict
    people_count: int
    senior_people_count: int
    account_age_days: float
    conflicted: bool
    suppressed_display_names: list


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def load_signal_types(conn):
    rows = conn.execute(
        "SELECT * FROM signal_types WHERE is_enabled = ? ORDER BY signal_type_id ASC",
        (1,),
    ).fetchall()
    return [dict(r) for r in rows]


def load_active_adjustments(conn, rep_id, as_of):
    """Active = is_active=1 AND expires_at > as_of.

    Expiry is evaluated at read time against as_of, never by a background job
    (DESIGN_SPEC.md §7.3 invariant 1). There is no cron in this environment.
    """
    rows = conn.execute(
        "SELECT * FROM queue_adjustments "
        "WHERE rep_id = ? AND is_active = ? AND expires_at > ? "
        "ORDER BY adjustment_id ASC",
        (rep_id, 1, as_of),
    ).fetchall()
    return [dict(r) for r in rows]


class AdjustmentSet:
    """The rep's active adjustments, indexed for O(1) lookup during scoring.

    Invariant (§7.3 #2): every query that built this filtered rep_id = ?.
    Nothing here can cross reps.
    """

    def __init__(self, rows):
        self.rows = rows
        self.suppressed_global = set()
        self.suppressed_account = set()
        self.excluded_people = set()
        self.pinned = set()
        self.demoted = set()
        self.muted = set()
        for r in rows:
            kind = r["kind"]
            if kind == "suppress_signal_type":
                if r["account_id"] is None:
                    self.suppressed_global.add(r["signal_type_id"])
                else:
                    self.suppressed_account.add((r["signal_type_id"], r["account_id"]))
            elif kind == "exclude_person":
                self.excluded_people.add((r["person_id"], r["account_id"]))
            elif kind == "pin":
                self.pinned.add(r["account_id"])
            elif kind == "demote":
                self.demoted.add(r["account_id"])
            elif kind == "mute_account":
                self.muted.add(r["account_id"])

    def suppresses(self, signal_type_id, account_id):
        return (signal_type_id in self.suppressed_global
                or (signal_type_id, account_id) in self.suppressed_account)

    def excludes_person(self, person_id, account_id):
        return person_id is not None and (person_id, account_id) in self.excluded_people

    def suppression_row_for(self, signal_type_id, account_id):
        for r in self.rows:
            if r["kind"] != "suppress_signal_type":
                continue
            if r["signal_type_id"] != signal_type_id:
                continue
            if r["account_id"] is None or r["account_id"] == account_id:
                return r
        return None


EMPTY_ADJUSTMENTS = AdjustmentSet([])


# --------------------------------------------------------------------------
# §4.2 arithmetic
# --------------------------------------------------------------------------

def magnitude_factor(magnitude):
    """Half-log so intensity matters but cannot run away (§4.2).

    1 -> x1.00, 3 -> x1.24, 10 -> x1.50, 40 -> x1.80, 100 -> x2.00.
    """
    return 1.0 + 0.5 * log10(max(magnitude, 1.0))


def decay_factor(age, half_life_days):
    return 0.5 ** (age / half_life_days)


def sign(value):
    return -1.0 if value < 0 else 1.0


def apply_cap(raw, base_weight, max_contribution):
    """points_s = sign(base_weight) * min(abs(raw_s), abs(max_contribution))."""
    capped = sign(base_weight) * min(abs(raw), abs(max_contribution))
    return round(capped, 2), abs(raw) > abs(max_contribution)


# --------------------------------------------------------------------------
# §4.1 state predicates, resolved by name from signal_types.state_predicate
# --------------------------------------------------------------------------

def _tech_stack_list(account):
    raw = account.get("tech_stack")
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return parsed if isinstance(parsed, list) else []


def evaluate_predicate(name, account, rep_id, ctx):
    """Return (fired, field_value). ctx carries the per-account counts.

    The guards here are the ones DESIGN_SPEC.md §4.1 and §8 call required, not
    optional: no_buying_authority_present must not fire on zero people, and
    no_engagement_90d must not fire on a brand-new account.
    """
    if name == "icp_industry":
        industry = account.get("industry")
        fired = industry in ICP_INDUSTRIES
        return fired, industry or ""

    if name == "icp_size":
        count = account.get("employee_count")
        fired = count is not None and ICP_SIZE_MIN <= count <= ICP_SIZE_MAX
        return fired, ("%d" % count) if count is not None else ""

    if name == "tech_stack_overlap":
        stack = _tech_stack_list(account)
        hits = [t for t in stack if t in ICP_TECH_MARKERS]
        return bool(hits), ", ".join(hits)

    if name == "open_opp_owned_elsewhere":
        fired = (account.get("crm_status") == "open_opportunity"
                 and account.get("owner_rep_id") is not None
                 and account.get("owner_rep_id") != rep_id)
        return fired, ctx.get("owner_name", "another rep")

    if name == "no_engagement_90d":
        # Required guard (§8.4): penalising an account for not having existed
        # long enough is arithmetically correct and visibly stupid.
        if ctx["account_age_days"] < NO_ENGAGEMENT_WINDOW_DAYS:
            return False, ""
        if ctx["total_event_count"] < 1:
            return False, ""          # no events ever is a data gap, not silence
        if ctx["days_silent"] is None:
            return False, ""
        fired = ctx["days_silent"] > NO_ENGAGEMENT_WINDOW_DAYS
        return fired, str(int(ctx["days_silent"]))

    if name == "outside_icp_size":
        count = account.get("employee_count")
        fired = count is not None and not (ICP_SIZE_MIN <= count <= ICP_SIZE_MAX)
        return fired, ("%d" % count) if count is not None else ""

    if name == "no_buying_authority_present":
        # Required guard (§4.1): fires only when the account has some people on
        # file. Zero people is a data gap, handled by data_completeness.
        if ctx["people_count"] == 0:
            return False, ""
        fired = ctx["senior_people_count"] == 0
        return fired, str(ctx["people_count"])

    raise ValueError("unknown state predicate: %r" % (name,))


# --------------------------------------------------------------------------
# §8.7 completeness and confidence
# --------------------------------------------------------------------------

def compute_data_completeness(account, senior_people_count, total_event_count):
    """Fraction of five fields present, in fifths (DESIGN_SPEC.md §8.7)."""
    present = 0
    if account.get("industry") is not None:
        present += 1
    if account.get("employee_count") is not None:
        present += 1
    if senior_people_count > 0:
        present += 1
    if account.get("tech_stack") is not None:
        present += 1
    if account.get("crm_status") != "none" or total_event_count > 0:
        present += 1
    return present / 5.0


def compute_confidence(distinct_signal_types, freshest_age_days, data_completeness,
                       account_age_days):
    """§8.7 cascade, evaluated top to bottom, first match wins."""
    age = freshest_age_days if freshest_age_days is not None else float("inf")

    if distinct_signal_types < 2 or data_completeness < 0.4:
        confidence = "insufficient"
    elif age > 45 or distinct_signal_types == 2:
        confidence = "low"
    elif 3 <= distinct_signal_types <= 4 and age <= 45 and data_completeness >= 0.6:
        confidence = "medium"
    elif distinct_signal_types >= 5 and age <= 14 and data_completeness >= 0.8:
        confidence = "high"
    else:
        confidence = "low"          # explicit fallback, never None

    # Unconditional brand-new cap (§8.7 closing line, §8.4).
    if account_age_days < BRAND_NEW_DAYS:
        if CONFIDENCE_ORDER.index(confidence) > CONFIDENCE_ORDER.index("medium"):
            confidence = "medium"
    return confidence


def band_from(points, confidence):
    """§4.2 Band. Confidence can cost a band, never win one."""
    if confidence == "insufficient":
        return "INSUFFICIENT_EVIDENCE"
    if points >= ACT_NOW_THRESHOLD and confidence in ("high", "medium"):
        return "ACT_NOW"
    if points >= ACT_NOW_THRESHOLD:
        return "REVIEW"
    if points >= REVIEW_THRESHOLD:
        return "REVIEW"
    if points >= HOLD_THRESHOLD:
        return "HOLD"
    return "HOLD"


# --------------------------------------------------------------------------
# Scoring one account
# --------------------------------------------------------------------------

def _load_account_context(conn, account_id, rep_id, as_of):
    account_row = conn.execute(
        "SELECT * FROM accounts WHERE account_id = ?", (account_id,)
    ).fetchone()
    if account_row is None:
        raise LookupError("no account %r" % (account_id,))
    account = dict(account_row)

    people = [dict(r) for r in conn.execute(
        "SELECT * FROM people WHERE account_id = ? ORDER BY person_id ASC", (account_id,)
    ).fetchall()]

    senior = [p for p in people if p["seniority"] in SENIOR_LEVELS]

    totals = conn.execute(
        "SELECT COUNT(*) AS n, MAX(occurred_at) AS newest FROM signal_events "
        "WHERE account_id = ? AND occurred_at <= ?",
        (account_id, as_of),
    ).fetchone()
    total_event_count = totals["n"] or 0
    newest_any = totals["newest"]

    owner_name = None
    if account["owner_rep_id"] is not None:
        owner_row = conn.execute(
            "SELECT name FROM reps WHERE rep_id = ?", (account["owner_rep_id"],)
        ).fetchone()
        if owner_row is not None:
            owner_name = owner_row["name"]

    return {
        "account": account,
        "people": people,
        "people_by_id": {p["person_id"]: p for p in people},
        "people_count": len(people),
        "senior_people_count": len(senior),
        "total_event_count": total_event_count,
        "newest_any_event_at": newest_any,
        "days_silent": age_days(as_of, newest_any) if newest_any else None,
        "account_age_days": age_days(as_of, account["first_seen_at"]),
        "owner_name": owner_name or "another rep",
    }


def _event_rows(conn, account_id, signal_type, as_of):
    """Live SQL, bound parameters only. Lookback window per §4.2."""
    floor_ts = shift(as_of, days=-signal_type["lookback_days"])
    return [dict(r) for r in conn.execute(
        "SELECT * FROM signal_events "
        "WHERE account_id = ? AND signal_type_id = ? "
        "  AND occurred_at <= ? AND occurred_at >= ? "
        "ORDER BY occurred_at DESC, event_id ASC",
        (account_id, signal_type["signal_type_id"], as_of, floor_ts),
    ).fetchall()]


def _contributions_for_events(rows, signal_type, as_of):
    out = []
    for row in rows:
        age = age_days(as_of, row["occurred_at"])
        decay = decay_factor(age, signal_type["half_life_days"])
        mag_f = magnitude_factor(row["magnitude"])
        value = signal_type["base_weight"] * decay * mag_f
        detail = {}
        if row["detail_json"]:
            try:
                detail = json.loads(row["detail_json"])
            except ValueError:
                detail = {}
        out.append(EventContribution(
            event_id=row["event_id"],
            person_id=row["person_id"],
            occurred_at=row["occurred_at"],
            observed_at=row["observed_at"],
            source=row["source"],
            magnitude=row["magnitude"],
            detail=detail,
            source_url=row["source_url"],
            contribution=value,
        ))
    return out


def score_account(conn, account_id, rep_id, as_of, signal_types=None,
                  adjustments=None, ctx=None):
    """Compute one warrant. Every value comes from a live query at call time.

    Returns an AccountScore. No caching, no memoisation: the caller gets what
    the database says right now.
    """
    if signal_types is None:
        signal_types = load_signal_types(conn)
    if adjustments is None:
        adjustments = AdjustmentSet(load_active_adjustments(conn, rep_id, as_of))
    if ctx is None:
        ctx = _load_account_context(conn, account_id, rep_id, as_of)

    account = ctx["account"]
    contributions = []

    for stype in signal_types:
        suppressed = adjustments.suppresses(stype["signal_type_id"], account_id)

        if stype["kind"] == "state":
            fired, field_value = evaluate_predicate(
                stype["state_predicate"], account, rep_id, ctx)
            if not fired:
                continue
            raw_before = stype["base_weight"]
            points_before = round(raw_before, 2)
            if abs(points_before) < POINT_FLOOR:
                continue
            points = 0.0 if suppressed else points_before
            # Most state signals are read off the account record, so they are
            # stamped with the enrichment date. no_engagement_90d is different:
            # its evidence line reads "Last activity {newest_date}", and that
            # date must be the real last activity, not the day we last
            # refreshed the record. A reason that misstates its own evidence is
            # the exact trust event §10 of the brief warns about.
            if stype["code"] == "no_engagement_90d" and ctx.get("newest_any_event_at"):
                stamp = ctx["newest_any_event_at"]
            else:
                stamp = account["data_last_refreshed_at"]
            contributions.append(SignalContribution(
                signal_type_id=stype["signal_type_id"],
                code=stype["code"],
                display_name=stype["display_name"],
                category=stype["category"],
                polarity=stype["polarity"],
                kind="state",
                base_weight=stype["base_weight"],
                max_contribution=stype["max_contribution"],
                half_life_days=None,
                points=points,
                points_before_adjustment=points_before,
                cap_applied=False,
                is_suppressed=suppressed,
                event_count=0,
                # A fit reason cannot claim to be fresher than the enrichment
                # that produced it (§3.2 data_last_refreshed_at).
                newest_event_at=stamp,
                oldest_event_at=stamp,
                source_names=["crm_sync"] if stype["code"] == "open_opp_owned_elsewhere" else ["enrichment"],
                events=[],
                field_value=field_value,
                top_person=None,
                other_user_count=0,
            ))
            continue

        rows = _event_rows(conn, account_id, stype, as_of)
        if not rows:
            continue

        all_contribs = _contributions_for_events(rows, stype, as_of)
        raw_before = sum(c.contribution for c in all_contribs)
        points_before, _cap_before = apply_cap(
            raw_before, stype["base_weight"], stype["max_contribution"])
        if abs(points_before) < POINT_FLOOR:
            continue                       # §4.2 floor, no reason row, no points

        if suppressed:
            kept = all_contribs
            points, cap_applied = 0.0, False
        else:
            kept = [c for c in all_contribs
                    if not adjustments.excludes_person(c.person_id, account_id)]
            raw_after = sum(c.contribution for c in kept)
            points, cap_applied = apply_cap(
                raw_after, stype["base_weight"], stype["max_contribution"])

        occurred = [c.occurred_at for c in all_contribs]
        top = max(all_contribs, key=lambda c: (abs(c.contribution), -c.event_id))
        top_person = ctx["people_by_id"].get(top.person_id)
        distinct_people = {c.person_id for c in all_contribs if c.person_id is not None}
        other_users = max(0, len(distinct_people) - 1)

        contributions.append(SignalContribution(
            signal_type_id=stype["signal_type_id"],
            code=stype["code"],
            display_name=stype["display_name"],
            category=stype["category"],
            polarity=stype["polarity"],
            kind="event",
            base_weight=stype["base_weight"],
            max_contribution=stype["max_contribution"],
            half_life_days=stype["half_life_days"],
            points=points,
            points_before_adjustment=points_before,
            cap_applied=cap_applied,
            is_suppressed=suppressed,
            event_count=len(all_contribs),
            newest_event_at=max(occurred),
            oldest_event_at=min(occurred),
            source_names=sorted({c.source for c in all_contribs}),
            events=all_contribs,
            field_value="",
            top_person=top_person,
            other_user_count=other_users,
        ))

    points = round(sum(c.points for c in contributions), 2)
    points_before = round(sum(c.points_before_adjustment for c in contributions), 2)

    event_types = [c for c in contributions if c.kind == "event" and c.events]
    freshest = max((c.newest_event_at for c in event_types), default=None)
    freshest_age = age_days(as_of, freshest) if freshest else None

    distinct = len([c for c in contributions if abs(c.points) >= POINT_FLOOR])
    completeness = compute_data_completeness(
        account, ctx["senior_people_count"], ctx["total_event_count"])
    confidence = compute_confidence(
        distinct, freshest_age, completeness, ctx["account_age_days"])
    band = band_from(points, confidence)

    positives = [c.points for c in contributions if c.points > 0]
    negatives = [c.points for c in contributions if c.points < 0]
    conflicted = bool(positives and negatives
                      and max(positives) >= CONFLICT_POSITIVE
                      and min(negatives) <= CONFLICT_NEGATIVE)

    flags = []
    if account_id in adjustments.pinned:
        flags.append("pinned")
    if account_id in adjustments.demoted:
        flags.append("demoted")
    if any(c.is_suppressed for c in contributions):
        flags.append("suppressed")
    if any(adjustments.excludes_person(p["person_id"], account_id) for p in ctx["people"]):
        flags.append("excluded_person")

    return AccountScore(
        account_id=account_id,
        rep_id=rep_id,
        as_of=as_of,
        points=points,
        points_before_adjustment=points_before,
        band=band,
        confidence=confidence,
        distinct_signal_types=distinct,
        freshest_evidence_at=freshest,
        data_completeness=completeness,
        contributions=contributions,
        adjustment_flags=flags,
        account=account,
        people_count=ctx["people_count"],
        senior_people_count=ctx["senior_people_count"],
        account_age_days=ctx["account_age_days"],
        conflicted=conflicted,
        suppressed_display_names=[c.display_name for c in contributions if c.is_suppressed],
    )


def accounts_for_rep(conn, rep_id):
    """The rep's patch. is_active = 0 accounts are excluded from all queues (§3.2)."""
    rows = conn.execute(
        "SELECT account_id FROM accounts WHERE owner_rep_id = ? AND is_active = ? "
        "ORDER BY account_id ASC",
        (rep_id, 1),
    ).fetchall()
    return [r["account_id"] for r in rows]


def score_queue(conn, rep_id, as_of):
    """Score every account in the rep's patch. Live SQL per account, per call."""
    signal_types = load_signal_types(conn)
    adjustments = AdjustmentSet(load_active_adjustments(conn, rep_id, as_of))
    results = []
    for account_id in accounts_for_rep(conn, rep_id):
        results.append(score_account(conn, account_id, rep_id, as_of,
                                     signal_types=signal_types,
                                     adjustments=adjustments))
    return results, adjustments


def requires_evidence_review(conn, account, score, rep_id):
    """DESIGN_SPEC.md §6.4. Two clauses. It will stay two clauses.

    Friction only where acting blind costs a colleague their open deal, or
    contradicts something the rep themselves already said.
    """
    if (account.get("crm_status") == "open_opportunity"
            and account.get("owner_rep_id") != rep_id):
        return True
    return has_open_dispute(conn, rep_id, account["account_id"])


def has_open_dispute(conn, rep_id, account_id):
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM disagreements "
        "WHERE rep_id = ? AND account_id = ? AND status IN (?, ?)",
        (rep_id, account_id, "open", "applied"),
    ).fetchone()
    return (row["n"] or 0) > 0
