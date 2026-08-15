"""Shared test fixtures.

Two kinds of fixture live here, and the distinction is the one the build rules
care about:

  * build_seeded_db() runs the real seed_db.py against a temp file. Every test
    that needs a corpus uses that — there is no hand-written list of account
    dicts standing in for the database anywhere in tests/.

  * build_kestrel_db() constructs the DESIGN_SPEC.md §4.4 worked example. Its
    rows ARE literal, because T02 requires exactly the events in that table and
    no generator could be asked to reproduce them. It is a spec fixture, not
    application lead data, and nothing in warrant/ or app.py reads it.
"""

import os
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import seed_db                                                   # noqa: E402
from warrant.db import apply_schema, connect                     # noqa: E402
from warrant.scoring import score_account                        # noqa: E402

AS_OF = "2026-08-11T09:00:00Z"

_SEEDED_CACHE = {}
_TEMP_DIRS = []


def _temp_path(prefix):
    directory = tempfile.mkdtemp(prefix="warrant-%s-" % prefix)
    _TEMP_DIRS.append(directory)
    return os.path.join(directory, "unify.db")


def build_seeded_db(tag="seed"):
    """Run the real seeder into a temp DB. Cached per tag within a process."""
    if tag in _SEEDED_CACHE:
        return _SEEDED_CACHE[tag]
    path = _temp_path(tag)
    previous = os.environ.get("WARRANT_DB_PATH")
    os.environ["WARRANT_DB_PATH"] = path
    try:
        import io
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            seed_db.main()
    finally:
        if previous is None:
            os.environ.pop("WARRANT_DB_PATH", None)
        else:
            os.environ["WARRANT_DB_PATH"] = previous
    _SEEDED_CACHE[tag] = path
    return path


def fresh_seeded_db(tag):
    """An uncached seeded DB, for tests that mutate it."""
    path = _temp_path(tag)
    previous = os.environ.get("WARRANT_DB_PATH")
    os.environ["WARRANT_DB_PATH"] = path
    try:
        import io
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            seed_db.main()
    finally:
        if previous is None:
            os.environ.pop("WARRANT_DB_PATH", None)
        else:
            os.environ["WARRANT_DB_PATH"] = previous
    return path


def all_account_ids(conn):
    return [r["account_id"] for r in conn.execute(
        "SELECT account_id FROM accounts WHERE is_active = 1 ORDER BY account_id"
    ).fetchall()]


def score_every_account(conn, rep_id=1, as_of=AS_OF):
    """Score the whole corpus, not just one rep's patch — T05/T07/T09/T11 are
    asserted 'across all 240 seeded accounts'."""
    from warrant.scoring import AdjustmentSet, load_signal_types
    types = load_signal_types(conn)
    empty = AdjustmentSet([])
    return [score_account(conn, aid, rep_id, as_of, signal_types=types,
                          adjustments=empty)
            for aid in all_account_ids(conn)]


# ---------------------------------------------------------------------------
# DESIGN_SPEC.md §4.4 worked example — Kestrel Analytics
# ---------------------------------------------------------------------------

KESTREL_ACCOUNT_ID = 1
KESTREL_REP_ID = 1

# (signal code, occurred_at date, magnitude, person key)
KESTREL_EVENTS = [
    ("product_usage_active", "2026-08-09", 14.0, "ana"),
    ("product_usage_active", "2026-08-04", 9.0, "ana"),
    ("product_usage_active", "2026-07-28", 5.0, "ana"),
    ("pricing_page_repeat", "2026-08-09", 2.0, "ana"),
    ("pricing_page_repeat", "2026-08-05", 1.0, "ana"),
    ("senior_buyer_engaged", "2026-08-09", 1.0, "ana"),
    ("new_hire_icp_role", "2026-07-14", 1.0, "ana"),
    ("third_party_intent_6sense", "2026-08-01", 1.0, None),
    ("third_party_intent_6sense", "2026-07-25", 1.0, None),
    ("champion_departed", "2026-06-30", 1.0, "marcus"),
    ("unsubscribed_or_bounced", "2026-03-15", 1.0, "marcus"),
]


def build_kestrel_db(path=None):
    """The §4.4 account, exactly as specified, in its own database."""
    path = path or _temp_path("kestrel")
    conn = connect(path)
    apply_schema(conn)

    conn.execute("INSERT INTO reps (rep_id, name, email, territory, created_at) "
                 "VALUES (?, ?, ?, ?, ?)",
                 (1, "Dana Whitfield", "dana.whitfield@example-co.test",
                  "NA-MidMarket", "2025-01-01T09:00:00Z"))
    conn.execute("INSERT INTO reps (rep_id, name, email, territory, created_at) "
                 "VALUES (?, ?, ?, ?, ?)",
                 (2, "Sam Okafor", "sam.okafor@example-co.test",
                  "NA-Enterprise", "2025-01-01T09:00:00Z"))
    seed_db.seed_signal_types(conn)

    conn.execute(
        "INSERT INTO accounts (account_id, name, domain, industry, employee_count, "
        " annual_revenue_usd, hq_country, tech_stack, crm_status, crm_status_changed_at, "
        " owner_rep_id, first_seen_at, data_last_refreshed_at, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (KESTREL_ACCOUNT_ID, "Kestrel Analytics", "kestrelanalytics.io",
         "Data & Analytics", 420, 92_000_000, "US",
         '["Snowflake", "dbt", "Looker"]', "none", None, 1,
         "2025-07-07T09:00:00Z", "2026-08-04T09:00:00Z", 1))

    people = {
        "ana": (1, "Ana Belic", "VP Engineering", "vp", "engineering", 0, "ok"),
        "marcus": (2, "Marcus Iwu", "Director of Data", "director", "data", 1, "unsubscribed"),
    }
    for _key, row in people.items():
        conn.execute(
            "INSERT INTO people (person_id, account_id, full_name, title, seniority, "
            " department, email, linkedin_url, is_champion, started_role_at, "
            " email_status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row[0], KESTREL_ACCOUNT_ID, row[1], row[2], row[3], row[4],
             None, "https://www.linkedin.com/in/synthetic-p%04d" % row[0],
             row[5], "2025-09-01T09:00:00Z", row[6], "2025-07-08T09:00:00Z"))

    codes = {r[1]: r[0] for r in seed_db.SIGNAL_TYPES}
    for index, (code, day, magnitude, person_key) in enumerate(KESTREL_EVENTS, start=1):
        occurred = "%sT09:00:00Z" % day
        detail = None
        if code == "pricing_page_repeat":
            detail = '{"path": "/pricing", "visits": %d}' % int(magnitude)
        elif code == "product_usage_active":
            detail = '{"sessions": %d, "surface": "workspace"}' % int(magnitude)
        conn.execute(
            "INSERT INTO signal_events (event_id, account_id, person_id, signal_type_id, "
            " occurred_at, observed_at, source, magnitude, detail_json, source_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (index, KESTREL_ACCOUNT_ID,
             people[person_key][0] if person_key else None,
             codes[code], occurred, occurred,
             seed_db.SOURCE_FOR_CODE[code], magnitude, detail,
             "https://app.example.test/evidence/ev_%06d" % index))

    conn.commit()
    return path, conn


def kestrel_score(conn, rep_id=KESTREL_REP_ID, as_of=AS_OF):
    return score_account(conn, KESTREL_ACCOUNT_ID, rep_id, as_of)


def contributions_by_code(score):
    return {c.code: c for c in score.contributions}
