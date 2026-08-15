"""Create and populate data/unify.db. DESIGN_SPEC.md §3, §4.1, §3.13.

Two categories of data are written here and the difference matters:

  * REFERENCE DATA — the 19 rows of `signal_types` (§4.1) with their weights,
    caps, half-lives and templates. This is the model definition. The spec is
    explicit (§3.4) that weights live in data rather than Python constants so
    the explanation and the arithmetic cannot drift apart. These are literal.

  * LEAD DATA — reps, accounts, people, signal_events, observations,
    task_events, and the seeded disagreements/adjustments. None of it is
    literal. All of it is GENERATED from the §3 distributions under
    random.seed(20260811), which is why T01 can assert reproducibility.

Idempotent: deletes and recreates the database file. Run: python seed_db.py
"""

import json
import os
import random
import sqlite3
import sys
from datetime import timedelta

from warrant.db import DEFAULT_AS_OF, apply_schema, db_path, ruleset_version, seed_value
from warrant.timeutil import fmt_ts, parse_ts, shift

# ---------------------------------------------------------------------------
# Reference value lists (DESIGN_SPEC.md §3.13) — model definition, not leads.
# ---------------------------------------------------------------------------

INDUSTRY_WEIGHTS = [
    ("SaaS", 22), ("Data & Analytics", 14), ("Fintech", 12), ("Developer Tools", 10),
    ("Cybersecurity", 9), ("E-commerce", 9), ("Healthcare IT", 8), ("Logistics", 7),
    ("Manufacturing", 5), ("Professional Services", 4),
]
TECH_POOL = ["Snowflake", "dbt", "Segment", "Databricks", "BigQuery", "Salesforce",
             "HubSpot", "Looker", "Airflow", "Kafka", "Postgres", "Redshift",
             "Fivetran", "Amplitude"]
PAGE_PATHS = ["/pricing", "/docs/quickstart", "/docs/api", "/integrations",
              "/security", "/customers", "/blog/scaling-data-teams"]
DOC_PATHS = ["/docs/quickstart", "/docs/api", "/integrations", "/security"]
COUNTRIES = ["US", "GB", "DE", "FR", "SG", "AU", "CA", "NL", "IN", "BR"]
CRM_WEIGHTS = [("none", 62), ("closed_lost", 14), ("open_opportunity", 11),
               ("customer", 9), ("partner", 4)]
TERRITORIES = ["NA-MidMarket", "NA-Enterprise", "EMEA-MidMarket", "APAC-All"]
DEPARTMENTS = ["engineering", "data", "revops", "sales", "marketing", "security",
               "finance", "product", "other"]
ICP_DEPARTMENTS = ["engineering", "data", "revops", "product"]

# Word pools. Account and person names are COMBINED from these at random —
# there is no pasted table of accounts anywhere in this repo.
NAME_STEMS = ["Kestrel", "Halcyon", "Bramble", "Verdant", "Northwind", "Ironvale",
              "Larkspur", "Meridian", "Cobalt", "Thistle", "Aurora", "Basalt",
              "Cinder", "Driftwood", "Ember", "Fathom", "Granite", "Harbour",
              "Indigo", "Juniper", "Kilnwood", "Lantern", "Marlow", "Nimbus",
              "Orchard", "Pinnacle", "Quarry", "Redwood", "Saffron", "Tundra",
              "Umbra", "Vantage", "Willow", "Yarrow", "Zephyr", "Alder",
              "Beacon", "Clearwater", "Dunmore", "Elmgrove"]
NAME_TAILS = ["Analytics", "Freight", "Labs", "Systems", "Dynamics", "Works",
              "Digital", "Networks", "Collective", "Technologies", "Partners",
              "Group"]
FIRST_NAMES = ["Ana", "Marcus", "Priya", "Dana", "Sam", "Iris", "Tobias", "Lena",
               "Owen", "Mei", "Rafael", "Nadia", "Callum", "Yusuf", "Elena",
               "Devon", "Farah", "Georgi", "Hana", "Ivan", "Jonas", "Keiko",
               "Liam", "Maya", "Noor", "Oskar", "Pia", "Quentin", "Rosa",
               "Sunil", "Tara", "Ulric", "Vera", "Wes", "Ximena", "Yara", "Zane"]
LAST_NAMES = ["Belic", "Iwu", "Raman", "Whitfield", "Okafor", "Lindqvist", "Moreau",
              "Castellanos", "Nakamura", "Adeyemi", "Petrov", "Halloran", "Duarte",
              "Sandoval", "Nowak", "Fitzgerald", "Bhattacharya", "Oyelaran",
              "Kovacs", "Steiner", "Marchetti", "Delacroix", "Farrow", "Grimaldi",
              "Haugen", "Ibarra", "Jansen", "Kowalski", "Lindgren", "Mbeki"]

IC_TITLES = {"engineering": "Software Engineer", "data": "Data Engineer",
             "revops": "Revenue Operations Analyst", "sales": "Account Executive",
             "marketing": "Marketing Associate", "security": "Security Engineer",
             "finance": "Financial Analyst", "product": "Product Manager",
             "other": "Operations Associate"}
DEPT_DISPLAY = {"engineering": "Engineering", "data": "Data", "revops": "RevOps",
                "sales": "Sales", "marketing": "Marketing", "security": "Security",
                "finance": "Finance", "product": "Product", "other": "Operations"}
C_TITLES = {"engineering": "CTO", "data": "Chief Data Officer", "revops": "COO",
            "sales": "CRO", "marketing": "CMO", "security": "CISO",
            "finance": "CFO", "product": "Chief Product Officer", "other": "COO"}

OBS_TEMPLATES = [
    "Posted {n} senior {dept} roles in the last three weeks.",
    "Migrated from Redshift to Snowflake per an engineering blog post.",
    "Named a new Head of {dept_display} in a recent press release.",
    "Mentioned a data-quality initiative on the Q2 earnings call.",
    "Opened a second office and is hiring {n} people into {dept}.",
    "Published a customer story describing a manual reporting workload.",
    "Deprecated an internal tool in favour of a vendor solution.",
]
OBS_SOURCES = ["Company careers page", "Engineering blog", "Press release",
               "Q2 earnings call transcript", "Company newsroom", "Product changelog"]

# ---------------------------------------------------------------------------
# §4.1 — the 19 signal types, seeded verbatim. This table IS the model.
# (signal_type_id, code, display_name, category, polarity, kind, base_weight,
#  max_contribution, half_life_days, lookback_days, reason_template,
#  evidence_template, state_predicate)
# ---------------------------------------------------------------------------

SIGNAL_TYPES = [
    (1, "product_usage_active", "Active product usage", "active_evaluation",
     "positive", "event", 12.0, 24.0, 14.0, 365,
     "{top_person_title} and {other_user_count} other{other_plural} used the product across {event_count} sessions, most recently {newest_relative}.",
     "{total_magnitude} sessions between {oldest_date} and {newest_date} · source: {source_list}",
     None),
    (2, "inbound_demo_request", "Inbound demo or contact request", "active_evaluation",
     "positive", "event", 11.0, 11.0, 7.0, 365,
     "{top_person_name} ({top_person_title}) asked to be contacted on {newest_date}.",
     "Inbound form, {newest_date} · source: {source_list}",
     None),
    (3, "pricing_page_repeat", "Repeat pricing-page visits", "active_evaluation",
     "positive", "event", 9.0, 18.0, 10.0, 365,
     "{top_person_title} viewed {path} {total_magnitude}x, most recently {newest_relative} ({newest_date}).",
     "{event_count} visits to {path} between {oldest_date} and {newest_date} · source: {source_list}",
     None),
    (4, "docs_or_integration_view", "Docs / integration page views", "active_evaluation",
     "positive", "event", 5.0, 10.0, 10.0, 365,
     "Someone at {account_name} read {path} {total_magnitude}x — they are checking whether this fits their stack.",
     "{event_count} views between {oldest_date} and {newest_date} · source: {source_list}",
     None),
    (5, "champion_job_move", "Known champion moved to this account", "authority",
     "positive", "event", 14.0, 14.0, 45.0, 365,
     "{top_person_name} bought from us before and started at {account_name} on {newest_date}.",
     "Job change detected {newest_date} · source: {source_list}",
     None),
    (6, "senior_buyer_engaged", "Director+ in a target function engaged", "authority",
     "positive", "event", 10.0, 20.0, 21.0, 365,
     "{top_person_title} — senior enough to sign — has engaged {event_count} time{event_plural}, last {newest_relative}.",
     "{event_count} touches between {oldest_date} and {newest_date} · source: {source_list}",
     None),
    (7, "new_hire_icp_role", "New hire into a target function", "timing",
     "positive", "event", 8.0, 16.0, 60.0, 365,
     "{account_name} hired {top_person_name} as {top_person_title} on {newest_date} — new owners re-open decisions.",
     "Role start {newest_date} · source: {source_list}",
     None),
    (8, "funding_or_hiring_surge", "Funding round or hiring surge", "timing",
     "positive", "event", 5.0, 10.0, 90.0, 365,
     "{account_name} raised or expanded headcount on {newest_date} — budget is likelier to exist now.",
     "{event_count} event{event_plural}, most recent {newest_date} · source: {source_list}",
     None),
    (9, "third_party_intent_6sense", "Third-party intent (6sense)", "timing",
     "positive", "event", 4.0, 8.0, 14.0, 365,
     "A third party (6sense) reports buying-stage intent for {account_name}. We cannot see what they did — treat this as a hint, not evidence.",
     "{event_count} intent update{event_plural}, most recent {newest_date} · source: 6sense integration",
     None),
    (10, "icp_industry_match", "Industry matches ICP", "fit",
     "positive", "state", 6.0, 6.0, None, 365,
     "{field_value} — inside the segment where this problem lands.",
     "Firmographic field, last refreshed {refreshed_date}",
     "icp_industry"),
    (11, "icp_size_match", "Headcount in ICP band", "fit",
     "positive", "state", 6.0, 6.0, None, 365,
     "{field_value} employees — big enough to have the problem, small enough to move.",
     "Firmographic field, last refreshed {refreshed_date}",
     "icp_size"),
    (12, "tech_stack_match", "Runs ICP-adjacent tooling", "fit",
     "positive", "state", 5.0, 5.0, None, 365,
     "Runs {field_value} — the stack this integrates with.",
     "Technographic field, last refreshed {refreshed_date}",
     "tech_stack_overlap"),
    (13, "open_opp_owned_elsewhere", "Open opportunity owned by another rep", "disqualifier",
     "negative", "state", -15.0, -15.0, None, 365,
     "There is already an open opportunity here, owned by {owner_name}. Not yours to work.",
     "CRM status since {refreshed_date} · source: crm_sync",
     "open_opp_owned_elsewhere"),
    (14, "closed_lost_recent", "Closed-lost in the last 12 months", "disqualifier",
     "negative", "event", -12.0, -12.0, 180.0, 365,
     "We lost this {newest_relative} ({newest_date}). Whatever the reason was, it probably still holds.",
     "Closed-lost {newest_date} · source: crm_sync",
     None),
    (15, "champion_departed", "Known champion left this account", "disqualifier",
     "negative", "event", -10.0, -10.0, 90.0, 365,
     "{top_person_name}, our contact here, left on {newest_date}. The relationship left with them.",
     "Job change detected {newest_date} · source: {source_list}",
     None),
    (16, "unsubscribed_or_bounced", "Contact unsubscribed or hard-bounced", "disqualifier",
     "negative", "event", -9.0, -9.0, 365.0, 365,
     "{top_person_name} unsubscribed or hard-bounced on {newest_date}. Email is closed here.",
     "{event_count} event{event_plural}, most recent {newest_date} · source: {source_list}",
     None),
    (17, "no_engagement_90d", "No engagement of any kind in 90 days", "disqualifier",
     "negative", "state", -8.0, -8.0, None, 365,
     "Nothing at all from {account_name} in {days_silent} days. Interest, if it existed, has cooled.",
     "Last activity {newest_date}",
     "no_engagement_90d"),
    (18, "outside_icp_size", "Headcount outside ICP band", "disqualifier",
     "negative", "state", -7.0, -7.0, None, 365,
     "{field_value} employees — outside the band where this sells.",
     "Firmographic field, last refreshed {refreshed_date}",
     "outside_icp_size"),
    (19, "no_buying_authority_present", "No director-or-above contact known", "disqualifier",
     "negative", "state", -6.0, -6.0, None, 365,
     "No director-or-above contact known here. There is nobody to sign.",
     "{people_count} contacts on file, none at director+ · refreshed {refreshed_date}",
     "no_buying_authority_present"),
]

CODE_TO_ID = {row[1]: row[0] for row in SIGNAL_TYPES}

N_ACCOUNTS = 240
N_REPS = 4
EVENT_SCALE = 19.4  # see README "Deviations": the literal §3.5 formula
                    # (int(paretovariate(1.3)) clamped 0-90) yields ~1,000
                    # events, not the ~6,500 the same section specifies. This
                    # multiplier reconciles the two; the shape is unchanged.


# ---------------------------------------------------------------------------

def weighted_choice(rng, pairs):
    total = sum(w for _, w in pairs)
    roll = rng.uniform(0, total)
    upto = 0.0
    for value, weight in pairs:
        upto += weight
        if roll <= upto:
            return value
    return pairs[-1][0]


def ts_days_before(as_of, days, rng=None):
    dt = parse_ts(as_of) - timedelta(days=days)
    if rng is not None:
        dt = dt.replace(hour=rng.randrange(6, 22), minute=rng.randrange(0, 60),
                        second=rng.randrange(0, 60))
    return fmt_ts(dt)


def seed_reps(conn, rng, as_of):
    rows = []
    for i in range(N_REPS):
        first = FIRST_NAMES[(i * 7) % len(FIRST_NAMES)]
        last = LAST_NAMES[(i * 5) % len(LAST_NAMES)]
        name = "%s %s" % (first, last)
        email = "%s.%s@example-co.test" % (first.lower(), last.lower())
        rows.append((i + 1, name, email, TERRITORIES[i], ts_days_before(as_of, 600)))
    conn.executemany(
        "INSERT INTO reps (rep_id, name, email, territory, created_at) "
        "VALUES (?, ?, ?, ?, ?)", rows)
    return rows


def seed_signal_types(conn):
    conn.executemany(
        "INSERT INTO signal_types (signal_type_id, code, display_name, category, "
        " polarity, kind, base_weight, max_contribution, half_life_days, "
        " lookback_days, reason_template, evidence_template, state_predicate, "
        " is_enabled) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
        SIGNAL_TYPES)


def generate_accounts(conn, rng, as_of, cohorts):
    combos = [(stem, tail) for stem in NAME_STEMS for tail in NAME_TAILS]
    rng.shuffle(combos)
    chosen = combos[:N_ACCOUNTS]

    owners = ([1] * 55) + ([2] * 55) + ([3] * 55) + ([4] * 55) + ([None] * 20)
    rng.shuffle(owners)

    rows = []
    accounts = []
    for index in range(N_ACCOUNTS):
        account_id = index + 1
        stem, tail = chosen[index]
        name = "%s %s" % (stem, tail)
        domain = "%s%s.io" % (stem.lower(), tail.lower()[:4])

        # §8.3 requires accounts with zero events AND zero firing state
        # signals. Without forcing the firmographics to NULL these accounts
        # still score +6/+6/+5 on the fit predicates and the case is never
        # reachable, so the edge case is constructed explicitly.
        no_signal_at_all = account_id in cohorts["zero_signal"]

        employee_count = int(10 ** rng.uniform(1.1, 3.95))
        if no_signal_at_all or rng.random() < 0.12:
            employee_count = None                       # thin data

        if no_signal_at_all:
            industry = None
        else:
            industry = None if rng.random() < 0.08 else weighted_choice(rng, INDUSTRY_WEIGHTS)

        if employee_count is None or rng.random() < 0.10:
            revenue = None
        else:
            revenue = employee_count * rng.randint(90_000, 320_000)

        tech_stack = None
        if not no_signal_at_all and rng.random() >= 0.22:
            tech_stack = json.dumps(rng.sample(TECH_POOL, rng.randint(3, 6)))

        crm_status = "none" if no_signal_at_all else weighted_choice(rng, CRM_WEIGHTS)

        if account_id in cohorts["brand_new"]:
            first_seen_days = rng.randint(1, 10)
        else:
            first_seen_days = rng.randint(11, 540)
        first_seen_at = ts_days_before(as_of, first_seen_days, rng)

        crm_changed = None
        if crm_status != "none":
            crm_changed = ts_days_before(as_of, rng.randint(1, max(2, first_seen_days)), rng)

        refresh_days = max(0, first_seen_days - rng.randint(0, 400))
        if account_id in cohorts["stale_fit"] and first_seen_days > 130:
            refresh_days = rng.randint(121, min(first_seen_days, 400))
        data_last_refreshed_at = ts_days_before(as_of, refresh_days, rng)

        is_active = 0 if rng.random() < 0.03 else 1

        row = (account_id, name, domain, industry, employee_count, revenue,
               rng.choice(COUNTRIES), tech_stack, crm_status, crm_changed,
               owners[index], first_seen_at, data_last_refreshed_at, is_active)
        rows.append(row)
        accounts.append({
            "account_id": account_id, "name": name, "crm_status": crm_status,
            "first_seen_at": first_seen_at, "first_seen_days": first_seen_days,
            "owner_rep_id": owners[index], "is_active": is_active,
            "employee_count": employee_count,
        })

    conn.executemany(
        "INSERT INTO accounts (account_id, name, domain, industry, employee_count, "
        " annual_revenue_usd, hq_country, tech_stack, crm_status, crm_status_changed_at, "
        " owner_rep_id, first_seen_at, data_last_refreshed_at, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return accounts


def generate_people(conn, rng, as_of, accounts, no_authority_ids, senior_required_ids=()):
    rows = []
    people_by_account = {}
    person_id = 0
    for account in accounts:
        count = max(2, int(rng.gauss(6, 3)))
        count = min(count, 14)
        force_junior = account["account_id"] in no_authority_ids
        # §8.3 accounts must not fire no_buying_authority_present either, so
        # they are given a director+ contact and kept out of the junior cohort.
        force_senior = account["account_id"] in senior_required_ids
        if force_senior:
            force_junior = False
        bucket = []
        for index in range(count):
            person_id += 1
            roll = rng.random()
            if force_senior and index == 0:
                seniority = "director"
            elif force_junior or roll < 0.55:
                seniority = rng.choice(["ic", "manager"])
            elif roll < 0.85:
                seniority = rng.choice(["director", "vp"])
            else:
                seniority = rng.choice(["c_level", "founder"])
            department = rng.choice(DEPARTMENTS)
            full_name = "%s %s" % (rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES))
            if seniority == "ic":
                title = IC_TITLES[department]
            elif seniority == "manager":
                title = "%s Manager" % DEPT_DISPLAY[department]
            elif seniority == "director":
                title = "Director of %s" % DEPT_DISPLAY[department]
            elif seniority == "vp":
                title = "VP %s" % DEPT_DISPLAY[department]
            elif seniority == "founder":
                title = "Founder"
            else:
                title = C_TITLES[department]

            email = None
            if rng.random() >= 0.25:
                email = "%s@%s" % (full_name.lower().replace(" ", "."), "example-co.test")
            email_status = weighted_choice(rng, [("ok", 92), ("bounced", 5), ("unsubscribed", 3)])
            is_champion = 1 if rng.random() < 0.04 else 0
            started_role_at = ts_days_before(as_of, rng.randint(5, 1500), rng)
            created_at = ts_days_before(as_of, rng.randint(1, account["first_seen_days"]), rng)

            person = {
                "person_id": person_id, "account_id": account["account_id"],
                "full_name": full_name, "title": title, "seniority": seniority,
                "department": department, "is_champion": is_champion,
                "email_status": email_status, "started_role_at": started_role_at,
            }
            bucket.append(person)
            rows.append((person_id, account["account_id"], full_name, title, seniority,
                         department, email,
                         "https://www.linkedin.com/in/synthetic-p%04d" % person_id,
                         is_champion, started_role_at, email_status, created_at))
        people_by_account[account["account_id"]] = bucket

    conn.executemany(
        "INSERT INTO people (person_id, account_id, full_name, title, seniority, "
        " department, email, linkedin_url, is_champion, started_role_at, "
        " email_status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return people_by_account


SOURCE_FOR_CODE = {
    "product_usage_active": "product_telemetry",
    "inbound_demo_request": "website_tracker",
    "pricing_page_repeat": "website_tracker",
    "docs_or_integration_view": "website_tracker",
    "champion_job_move": "job_change_feed",
    "senior_buyer_engaged": "website_tracker",
    "new_hire_icp_role": "job_change_feed",
    "funding_or_hiring_surge": "funding_feed",
    "third_party_intent_6sense": "6sense",
    "closed_lost_recent": "crm_sync",
    "champion_departed": "job_change_feed",
    "unsubscribed_or_bounced": "email_platform",
}
COUNTABLE = {"product_usage_active", "pricing_page_repeat", "docs_or_integration_view"}
EVENT_CODES = list(SOURCE_FOR_CODE.keys())


def _pick_person(rng, people, predicate=None):
    pool = [p for p in people if predicate(p)] if predicate else list(people)
    return rng.choice(pool) if pool else None


def _eligible_codes(account, people):
    codes = ["pricing_page_repeat", "docs_or_integration_view",
             "third_party_intent_6sense", "funding_or_hiring_surge",
             "inbound_demo_request", "product_usage_active"]
    if any(p["seniority"] in ("director", "vp", "c_level", "founder")
           and p["department"] in ICP_DEPARTMENTS for p in people):
        codes.append("senior_buyer_engaged")
    if any(p["is_champion"] for p in people):
        codes += ["champion_job_move", "champion_departed"]
    if any(p["email_status"] != "ok" for p in people):
        codes.append("unsubscribed_or_bounced")
    if account["crm_status"] == "closed_lost":
        codes.append("closed_lost_recent")
    if any(p["department"] in ICP_DEPARTMENTS for p in people):
        codes.append("new_hire_icp_role")
    return codes


def _make_event(rng, event_id, account, people, code, days_ago, magnitude=None):
    person = None
    if code in ("product_usage_active", "pricing_page_repeat", "docs_or_integration_view",
                "inbound_demo_request"):
        person = _pick_person(rng, people)
    elif code == "senior_buyer_engaged":
        person = _pick_person(rng, people, lambda p: p["seniority"] in
                              ("director", "vp", "c_level", "founder")
                              and p["department"] in ICP_DEPARTMENTS)
    elif code in ("champion_job_move", "champion_departed"):
        person = _pick_person(rng, people, lambda p: p["is_champion"] == 1)
    elif code == "unsubscribed_or_bounced":
        person = _pick_person(rng, people, lambda p: p["email_status"] != "ok")
    elif code == "new_hire_icp_role":
        person = _pick_person(rng, people, lambda p: p["department"] in ICP_DEPARTMENTS)

    if magnitude is None:
        if code in COUNTABLE:
            magnitude = float(min(40, max(1, int(rng.paretovariate(1.6)))))
        else:
            magnitude = 1.0

    occurred_at = ts_days_before(DEFAULT_AS_OF_HOLDER[0], days_ago, rng)
    observed_at = shift(occurred_at, hours=rng.uniform(0, 36))
    if observed_at > DEFAULT_AS_OF_HOLDER[0]:
        observed_at = DEFAULT_AS_OF_HOLDER[0]

    detail = None
    if code == "pricing_page_repeat":
        detail = json.dumps({"path": "/pricing", "visits": int(magnitude)})
    elif code == "docs_or_integration_view":
        detail = json.dumps({"path": rng.choice(DOC_PATHS), "visits": int(magnitude)})
    elif code == "product_usage_active":
        detail = json.dumps({"sessions": int(magnitude), "surface": "workspace"})
    elif code == "third_party_intent_6sense":
        detail = json.dumps({"buying_stage": rng.choice(["awareness", "consideration", "decision"])})

    return (event_id, account["account_id"], person["person_id"] if person else None,
            CODE_TO_ID[code], occurred_at, observed_at, SOURCE_FOR_CODE[code],
            magnitude, detail,
            "https://app.example.test/evidence/ev_%06d" % event_id)


DEFAULT_AS_OF_HOLDER = [DEFAULT_AS_OF]


def generate_events(conn, rng, as_of, accounts, people_by_account, cohorts):
    DEFAULT_AS_OF_HOLDER[0] = as_of
    rows = []
    event_id = 0

    def add(account, people, code, days_ago, magnitude=None):
        nonlocal event_id
        event_id += 1
        row = _make_event(rng, event_id, account, people, code, days_ago, magnitude)
        rows.append(row)

    for account in accounts:
        account_id = account["account_id"]
        people = people_by_account[account_id]
        codes = _eligible_codes(account, people)
        max_age = max(1, min(365, account["first_seen_days"]))

        if account_id in cohorts["zero_events"]:
            continue

        if account_id in cohorts["thin"]:
            code = rng.choice(codes)
            for _ in range(rng.randint(1, 3)):
                add(account, people, code, rng.randint(1, max_age))
            continue

        if account_id in cohorts["brand_new"]:
            for _ in range(rng.randint(1, 3)):
                add(account, people, rng.choice(codes), rng.randint(0, max_age))
            continue

        if account_id in cohorts["conflicting"]:
            # >= +12 pts positive: recent, high-magnitude product usage.
            for _ in range(rng.randint(2, 4)):
                add(account, people, "product_usage_active", rng.randint(0, 7),
                    magnitude=float(rng.randint(5, 20)))
            # <= -7 pts negative: a champion who left, or a recent closed-lost.
            if "champion_departed" in codes:
                add(account, people, "champion_departed", rng.randint(1, 25))
            elif "closed_lost_recent" in codes:
                add(account, people, "closed_lost_recent", rng.randint(1, 40))
            else:
                add(account, people, "unsubscribed_or_bounced", rng.randint(1, 30))
            for _ in range(rng.randint(0, 6)):
                add(account, people, rng.choice(codes), rng.randint(1, max_age))
            continue

        count = int(rng.paretovariate(1.3) * EVENT_SCALE)
        count = max(0, min(90, count))
        for _ in range(count):
            if account_id in cohorts["stale"]:
                days_ago = rng.randint(46, max(47, min(300, max_age)))
            else:
                # Recency bias: AS_OF - int(365 * random() ** 2.2) days (§3.5)
                days_ago = min(max_age, int(365 * (rng.random() ** 2.2)))
            add(account, people, rng.choice(codes), days_ago)

    conn.executemany(
        "INSERT INTO signal_events (event_id, account_id, person_id, signal_type_id, "
        " occurred_at, observed_at, source, magnitude, detail_json, source_url) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return len(rows)


def generate_observations(conn, rng, as_of, accounts, people_by_account):
    rows = []
    observation_id = 0
    for account in accounts:
        if rng.random() < 0.30:
            continue                                  # 30% of accounts have none
        for _ in range(rng.randint(1, 5)):
            observation_id += 1
            dept = rng.choice(ICP_DEPARTMENTS)
            summary = rng.choice(OBS_TEMPLATES).format(
                n=rng.randint(2, 9), dept=dept, dept_display=DEPT_DISPLAY[dept])
            retrieved_days = rng.randint(1, 90)
            retrieved_at = ts_days_before(as_of, retrieved_days, rng)
            person = None
            if rng.random() < 0.3 and people_by_account[account["account_id"]]:
                person = rng.choice(people_by_account[account["account_id"]])
            rows.append((observation_id, account["account_id"],
                         person["person_id"] if person else None,
                         summary[:200], rng.choice(OBS_SOURCES),
                         "https://app.example.test/research/obs_%05d" % observation_id,
                         retrieved_at,
                         "run_%s_%04x" % (retrieved_at[:10], rng.randrange(0x10000))))
    conn.executemany(
        "INSERT INTO observations (observation_id, account_id, person_id, summary, "
        " source_name, source_url, retrieved_at, agent_run_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return len(rows)


def generate_task_events(conn, rng, as_of, accounts):
    """~900 backdated events over the 60 days before AS_OF, so /metrics is
    non-empty on first run (§3.12). ~62% top-3 acceptance, ~34% evidence-open,
    ~9% dispute."""
    by_rep = {r: [a for a in accounts if a["owner_rep_id"] == r and a["is_active"]]
              for r in range(1, N_REPS + 1)}
    rows = []
    for rep_id in range(1, N_REPS + 1):
        pool = by_rep[rep_id]
        if not pool:
            continue
        for _ in range(30):
            occurred = ts_days_before(as_of, rng.randint(1, 60), rng)
            rows.append((rep_id, None, None, None, "queue_viewed", occurred, None, None))
        for _ in range(95):
            account = rng.choice(pool)
            occurred = ts_days_before(as_of, rng.randint(1, 60), rng)
            rank = rng.randint(1, 20)
            rows.append((rep_id, account["account_id"], None, None, "item_viewed",
                         occurred, rank, None))
            if rng.random() < 0.34:
                rows.append((rep_id, account["account_id"], None, None, "evidence_opened",
                             shift(occurred, minutes=2), rank, None))
            roll = rng.random()
            accept_p = 0.62 if rank <= 3 else 0.28
            if roll < accept_p:
                rows.append((rep_id, account["account_id"], None, None, "accepted",
                             shift(occurred, minutes=5), rank, None))
            elif roll < accept_p + 0.30:
                rows.append((rep_id, account["account_id"], None, None, "skipped",
                             shift(occurred, minutes=4), rank, None))
    conn.executemany(
        "INSERT INTO task_events (rep_id, account_id, score_id, run_id, event_type, "
        " occurred_at, rank_at_event, detail_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return len(rows)


def generate_feedback_history(conn, rng, as_of, accounts):
    """A small, deliberately shaped history so §8.6's three sub-cases are all
    reachable in the seeded data and /metrics has real disputes to divide by.

    Everything here belongs to rep 1 and rep 3. Rep 2 and rep 4 are left with a
    clean slate so the rep-isolation test (T10) has an untouched control.
    """
    owned = {r: [a for a in accounts if a["owner_rep_id"] == r and a["is_active"]]
             for r in (1, 2, 3, 4)}
    made = {"disagreements": 0, "adjustments": 0, "active": 0}

    def write(rep_id, account_id, code, scope, signal_type_id, kind, created_days,
              window_days, active):
        created_at = ts_days_before(as_of, created_days, rng)
        expires_at = shift(created_at, days=window_days)
        status = "applied" if active else "expired"
        cursor = conn.execute(
            "INSERT INTO disagreements (rep_id, account_id, score_id, reason_id, "
            " signal_type_id, person_id, scope, code, note, created_at, "
            " ruleset_version, status, resulting_adjustment_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rep_id, account_id, None, None, signal_type_id, None, scope, code,
             None, created_at, ruleset_version(), status, None))
        disagreement_id = cursor.lastrowid
        adj = conn.execute(
            "INSERT INTO queue_adjustments (rep_id, kind, account_id, signal_type_id, "
            " person_id, created_at, expires_at, source_disagreement_id, is_active, "
            " reverted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rep_id, kind, account_id,
             signal_type_id if kind == "suppress_signal_type" else None, None,
             created_at, expires_at, disagreement_id, 1, None)).lastrowid
        conn.execute("UPDATE disagreements SET resulting_adjustment_id = ? "
                     "WHERE disagreement_id = ?", (adj, disagreement_id))
        conn.execute(
            "INSERT INTO task_events (rep_id, account_id, score_id, run_id, event_type, "
            " occurred_at, rank_at_event, detail_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (rep_id, account_id, None, None, "disputed", created_at, None,
             json.dumps({"code": code, "signal_type_id": signal_type_id})))
        conn.execute(
            "INSERT INTO task_events (rep_id, account_id, score_id, run_id, event_type, "
            " occurred_at, rank_at_event, detail_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (rep_id, account_id, None, None, "adjusted", created_at, None,
             json.dumps({"kind": kind})))
        made["disagreements"] += 1
        made["adjustments"] += 1
        if active:
            made["active"] += 1
        return disagreement_id, adj

    # Rep 1: one live account-scoped suppression (§8.6a) and one that has
    # already expired while the signal keeps firing (§8.6b banner).
    if len(owned[1]) >= 4:
        write(1, owned[1][0]["account_id"], "EVIDENCE_WRONG", "reason",
              CODE_TO_ID["third_party_intent_6sense"], "suppress_signal_type", 5, 90, True)
        write(1, owned[1][1]["account_id"], "EVIDENCE_STALE", "reason",
              CODE_TO_ID["docs_or_integration_view"], "suppress_signal_type", 55, 30, True)
        write(1, owned[1][2]["account_id"], "BAD_TIMING", "item", None, "demote", 3, 30, True)
        write(1, owned[1][3]["account_id"], "NOT_A_FIT", "item", None, "mute_account", 2, 60, True)

    # Rep 3: expired history only — exercises the metrics without touching the
    # live queue arithmetic.
    for i, account in enumerate(owned[3][:8]):
        code, kind, stype = [
            ("EVIDENCE_WRONG", "suppress_signal_type", CODE_TO_ID["third_party_intent_6sense"]),
            ("EVIDENCE_STALE", "suppress_signal_type", CODE_TO_ID["pricing_page_repeat"]),
            ("NOT_MY_PATCH", "mute_account", None),
            ("ALREADY_WORKING", "mute_account", None),
        ][i % 4]
        scope = "reason" if stype is not None else "item"
        write(3, account["account_id"], code, scope, stype, kind, 50 + i, 20, False)

    conn.execute("UPDATE queue_adjustments SET is_active = 0 WHERE expires_at <= ?", (as_of,))

    # A pin the rep set directly, no dispute behind it (§7.3 direct control).
    if owned[1]:
        conn.execute(
            "INSERT INTO queue_adjustments (rep_id, kind, account_id, signal_type_id, "
            " person_id, created_at, expires_at, source_disagreement_id, is_active, "
            " reverted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "pin", owned[1][4]["account_id"], None, None,
             ts_days_before(as_of, 2, rng), shift(as_of, days=12), None, 1, None))
        made["adjustments"] += 1
        made["active"] += 1
    return made


def main():
    as_of = os.environ.get("WARRANT_AS_OF", DEFAULT_AS_OF)
    target = db_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.exists(target):
        os.remove(target)                              # idempotent: recreate

    rng = random.Random()
    rng.seed(seed_value())                             # §3.13 fixed seed

    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    apply_schema(conn)

    # Forced cohorts (§3.5). Disjoint partition of a shuffled account list.
    ids = list(range(1, N_ACCOUNTS + 1))
    rng.shuffle(ids)
    cursor = 0

    def take(fraction):
        nonlocal cursor
        n = int(round(N_ACCOUNTS * fraction))
        chunk = set(ids[cursor:cursor + n])
        cursor += n
        return chunk

    cohorts = {
        "zero_events": take(0.08),
        "thin": take(0.15),
        "stale": take(0.20),
        "conflicting": take(0.10),
        "brand_new": take(0.06),
    }
    cohorts["stale_fit"] = set(rng.sample(ids, int(round(N_ACCOUNTS * 0.18))))
    # §8.3 "no signal at all": a subset of the zero-event cohort that also has
    # every state predicate switched off. Explicitly constructed, because the
    # combination is too rare to appear reliably by chance.
    cohorts["zero_signal"] = set(sorted(cohorts["zero_events"])[:8])
    no_authority = set(rng.sample(ids, int(round(N_ACCOUNTS * 0.18))))
    no_authority -= cohorts["zero_signal"]

    seed_reps(conn, rng, as_of)
    seed_signal_types(conn)
    accounts = generate_accounts(conn, rng, as_of, cohorts)
    people_by_account = generate_people(conn, rng, as_of, accounts, no_authority,
                                        senior_required_ids=cohorts["zero_signal"])
    n_events = generate_events(conn, rng, as_of, accounts, people_by_account, cohorts)
    n_obs = generate_observations(conn, rng, as_of, accounts, people_by_account)
    n_tasks = generate_task_events(conn, rng, as_of, accounts)
    feedback = generate_feedback_history(conn, rng, as_of, accounts)
    conn.commit()

    n_people = conn.execute("SELECT COUNT(*) AS n FROM people").fetchone()["n"]
    print("Seeded %s" % target)
    print("  as_of            : %s" % as_of)
    print("  ruleset          : %s" % ruleset_version())
    print("  reps             : %d" % N_REPS)
    print("  signal_types     : %d  (reference data, seeded verbatim from spec 4.1)" % len(SIGNAL_TYPES))
    print("  accounts         : %d  (%d inactive)" % (
        N_ACCOUNTS,
        conn.execute("SELECT COUNT(*) AS n FROM accounts WHERE is_active = 0").fetchone()["n"]))
    print("  people           : %d" % n_people)
    print("  signal_events    : %d" % n_events)
    print("  observations     : %d  (%d accounts with none)" % (
        n_obs,
        conn.execute("SELECT COUNT(*) AS n FROM accounts a WHERE NOT EXISTS "
                     "(SELECT 1 FROM observations o WHERE o.account_id = a.account_id)"
                     ).fetchone()["n"]))
    print("  task_events      : %d" % n_tasks)
    print("  disagreements    : %d  (%d adjustments, %d still active)" % (
        feedback["disagreements"], feedback["adjustments"], feedback["active"]))
    print("  forced cohorts   :")
    for label, member_ids in cohorts.items():
        print("    %-14s %3d accounts" % (label, len(member_ids)))
    print("    %-14s %3d accounts" % ("no_authority", len(no_authority)))

    zero = conn.execute(
        "SELECT COUNT(*) AS n FROM accounts a WHERE NOT EXISTS "
        "(SELECT 1 FROM signal_events e WHERE e.account_id = a.account_id)"
    ).fetchone()["n"]
    stale = conn.execute(
        "SELECT COUNT(*) AS n FROM (SELECT account_id, MAX(occurred_at) AS newest "
        "FROM signal_events GROUP BY account_id) WHERE newest < ?",
        (shift(as_of, days=-45),)).fetchone()["n"]
    print("  verified         : %d accounts have zero events, %d have freshest evidence >45d old"
          % (zero, stale))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
