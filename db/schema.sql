-- Warrant — schema (DESIGN_SPEC.md §3)
-- Executed via sqlite3.Connection.executescript(). No sqlite3 CLI is used anywhere.
-- Conventions: ISO-8601 UTC TEXT timestamps 'YYYY-MM-DDTHH:MM:SSZ'; booleans INTEGER (0,1);
-- JSON payloads TEXT; money INTEGER USD; every PK is INTEGER PRIMARY KEY (rowid alias).

PRAGMA foreign_keys = ON;

-- §3.1
CREATE TABLE reps (
    rep_id      INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    territory   TEXT NOT NULL CHECK (territory IN ('NA-MidMarket','NA-Enterprise','EMEA-MidMarket','APAC-All')),
    created_at  TEXT NOT NULL
);

-- §3.2
CREATE TABLE accounts (
    account_id             INTEGER PRIMARY KEY,
    name                   TEXT NOT NULL,
    domain                 TEXT NOT NULL UNIQUE,
    industry               TEXT,
    employee_count         INTEGER,
    annual_revenue_usd     INTEGER,
    hq_country             TEXT NOT NULL,
    tech_stack             TEXT,
    crm_status             TEXT NOT NULL CHECK (crm_status IN ('none','open_opportunity','closed_lost','customer','partner')),
    crm_status_changed_at  TEXT,
    owner_rep_id           INTEGER REFERENCES reps(rep_id),
    first_seen_at          TEXT NOT NULL,
    data_last_refreshed_at TEXT NOT NULL,
    is_active              INTEGER NOT NULL CHECK (is_active IN (0,1)),
    CHECK ((crm_status = 'none' AND crm_status_changed_at IS NULL)
        OR (crm_status <> 'none' AND crm_status_changed_at IS NOT NULL))
);

-- §3.3
CREATE TABLE people (
    person_id       INTEGER PRIMARY KEY,
    account_id      INTEGER NOT NULL REFERENCES accounts(account_id),
    full_name       TEXT NOT NULL,
    title           TEXT NOT NULL,
    seniority       TEXT NOT NULL CHECK (seniority IN ('ic','manager','director','vp','c_level','founder')),
    department      TEXT NOT NULL CHECK (department IN ('engineering','data','revops','sales','marketing','security','finance','product','other')),
    email           TEXT,
    linkedin_url    TEXT,
    is_champion     INTEGER NOT NULL CHECK (is_champion IN (0,1)),
    started_role_at TEXT,
    email_status    TEXT NOT NULL CHECK (email_status IN ('ok','bounced','unsubscribed')),
    created_at      TEXT NOT NULL
);

-- §3.4 — the published weight table. This table IS the model.
CREATE TABLE signal_types (
    signal_type_id    INTEGER PRIMARY KEY,
    code              TEXT NOT NULL UNIQUE,
    display_name      TEXT NOT NULL,
    category          TEXT NOT NULL CHECK (category IN ('fit','authority','active_evaluation','timing','disqualifier')),
    polarity          TEXT NOT NULL CHECK (polarity IN ('positive','negative')),
    kind              TEXT NOT NULL CHECK (kind IN ('event','state')),
    base_weight       REAL NOT NULL,
    max_contribution  REAL NOT NULL,
    half_life_days    REAL,
    lookback_days     INTEGER NOT NULL DEFAULT 365,
    reason_template   TEXT NOT NULL,
    evidence_template TEXT NOT NULL,
    state_predicate   TEXT,
    is_enabled        INTEGER NOT NULL CHECK (is_enabled IN (0,1)),
    CHECK ((polarity = 'positive' AND base_weight > 0) OR (polarity = 'negative' AND base_weight < 0)),
    CHECK ((kind = 'state' AND half_life_days IS NULL AND state_predicate IS NOT NULL)
        OR (kind = 'event' AND half_life_days IS NOT NULL AND state_predicate IS NULL))
);

-- §3.5
CREATE TABLE signal_events (
    event_id       INTEGER PRIMARY KEY,
    account_id     INTEGER NOT NULL REFERENCES accounts(account_id),
    person_id      INTEGER REFERENCES people(person_id),
    signal_type_id INTEGER NOT NULL REFERENCES signal_types(signal_type_id),
    occurred_at    TEXT NOT NULL,
    observed_at    TEXT NOT NULL,
    source         TEXT NOT NULL CHECK (source IN ('website_tracker','product_telemetry','crm_sync','unify_agent','6sense','job_change_feed','email_platform','funding_feed')),
    magnitude      REAL NOT NULL CHECK (magnitude >= 1.0),
    detail_json    TEXT,
    source_url     TEXT
);

-- §3.6
CREATE TABLE observations (
    observation_id INTEGER PRIMARY KEY,
    account_id     INTEGER NOT NULL REFERENCES accounts(account_id),
    person_id      INTEGER REFERENCES people(person_id),
    summary        TEXT NOT NULL,
    source_name    TEXT NOT NULL,
    source_url     TEXT,
    retrieved_at   TEXT NOT NULL,
    agent_run_id   TEXT NOT NULL
);

-- §3.7
CREATE TABLE score_runs (
    run_id          INTEGER PRIMARY KEY,
    rep_id          INTEGER NOT NULL REFERENCES reps(rep_id),
    as_of           TEXT NOT NULL,
    computed_at     TEXT NOT NULL,
    ruleset_version TEXT NOT NULL,
    anchor_points   REAL NOT NULL,
    account_count   INTEGER NOT NULL
);

-- §3.8
CREATE TABLE scores (
    score_id                  INTEGER PRIMARY KEY,
    run_id                    INTEGER NOT NULL REFERENCES score_runs(run_id),
    account_id                INTEGER NOT NULL REFERENCES accounts(account_id),
    points                    REAL NOT NULL,
    points_before_adjustment  REAL NOT NULL,
    band                      TEXT NOT NULL CHECK (band IN ('ACT_NOW','REVIEW','HOLD','INSUFFICIENT_EVIDENCE')),
    confidence                TEXT NOT NULL CHECK (confidence IN ('high','medium','low','insufficient')),
    distinct_signal_types     INTEGER NOT NULL,
    freshest_evidence_at      TEXT,
    data_completeness         REAL NOT NULL,
    rank_in_queue             INTEGER NOT NULL,
    rank_before_adjustment    INTEGER NOT NULL,
    adjustment_flags          TEXT,
    limits_line               TEXT NOT NULL,
    UNIQUE (run_id, account_id)
);

-- §3.9
-- points                   = effective (post-suppression) signed points. T07 sums this column.
-- points_before_adjustment = the same signal type ignoring this rep's adjustments (added column, see README).
-- is_suppressed / cap_applied are render flags (added columns, see README §Deviations).
CREATE TABLE reasons (
    reason_id                INTEGER PRIMARY KEY,
    score_id                 INTEGER NOT NULL REFERENCES scores(score_id),
    signal_type_id           INTEGER NOT NULL REFERENCES signal_types(signal_type_id),
    rank                     INTEGER NOT NULL,
    polarity                 TEXT NOT NULL CHECK (polarity IN ('positive','negative')),
    points                   REAL NOT NULL,
    points_before_adjustment REAL NOT NULL,
    share_of_abs_total       REAL NOT NULL,
    text                     TEXT NOT NULL,
    evidence_summary         TEXT NOT NULL,
    newest_event_at          TEXT NOT NULL,
    oldest_event_at          TEXT NOT NULL,
    event_count              INTEGER NOT NULL,
    source_names             TEXT NOT NULL,
    shown                    INTEGER NOT NULL CHECK (shown IN (0,1)),
    is_suppressed            INTEGER NOT NULL DEFAULT 0 CHECK (is_suppressed IN (0,1)),
    cap_applied              INTEGER NOT NULL DEFAULT 0 CHECK (cap_applied IN (0,1)),
    UNIQUE (score_id, signal_type_id)
);

CREATE TABLE reason_evidence (
    reason_id    INTEGER NOT NULL REFERENCES reasons(reason_id),
    event_id     INTEGER NOT NULL REFERENCES signal_events(event_id),
    contribution REAL NOT NULL,
    PRIMARY KEY (reason_id, event_id)
);

-- §3.10
CREATE TABLE disagreements (
    disagreement_id         INTEGER PRIMARY KEY,
    rep_id                  INTEGER NOT NULL REFERENCES reps(rep_id),
    account_id              INTEGER NOT NULL REFERENCES accounts(account_id),
    score_id                INTEGER REFERENCES scores(score_id),
    reason_id               INTEGER REFERENCES reasons(reason_id),
    signal_type_id          INTEGER REFERENCES signal_types(signal_type_id),
    person_id               INTEGER REFERENCES people(person_id),
    scope                   TEXT NOT NULL CHECK (scope IN ('reason','item')),
    code                    TEXT NOT NULL CHECK (code IN ('NOT_A_FIT','WRONG_PERSON','BAD_TIMING','ALREADY_WORKING','EVIDENCE_WRONG','EVIDENCE_STALE','NOT_MY_PATCH')),
    note                    TEXT,
    created_at              TEXT NOT NULL,
    ruleset_version         TEXT NOT NULL,
    status                  TEXT NOT NULL CHECK (status IN ('open','applied','expired','reverted','reviewed')),
    resulting_adjustment_id INTEGER REFERENCES queue_adjustments(adjustment_id),
    CHECK (scope <> 'reason' OR signal_type_id IS NOT NULL),
    CHECK (note IS NULL OR length(note) <= 280)
);

-- §3.11
CREATE TABLE queue_adjustments (
    adjustment_id          INTEGER PRIMARY KEY,
    rep_id                 INTEGER NOT NULL REFERENCES reps(rep_id),
    kind                   TEXT NOT NULL CHECK (kind IN ('pin','demote','mute_account','suppress_signal_type','exclude_person')),
    account_id             INTEGER REFERENCES accounts(account_id),
    signal_type_id         INTEGER REFERENCES signal_types(signal_type_id),
    person_id              INTEGER REFERENCES people(person_id),
    created_at             TEXT NOT NULL,
    expires_at             TEXT NOT NULL,
    source_disagreement_id INTEGER REFERENCES disagreements(disagreement_id),
    is_active              INTEGER NOT NULL CHECK (is_active IN (0,1)),
    reverted_at            TEXT,
    CHECK (
      (kind = 'suppress_signal_type' AND signal_type_id IS NOT NULL AND person_id IS NULL)
      OR (kind = 'exclude_person'      AND person_id IS NOT NULL AND account_id IS NOT NULL)
      OR (kind IN ('pin','demote','mute_account') AND account_id IS NOT NULL
          AND signal_type_id IS NULL AND person_id IS NULL)
    )
);

-- §3.12
CREATE TABLE task_events (
    task_event_id INTEGER PRIMARY KEY,
    rep_id        INTEGER NOT NULL REFERENCES reps(rep_id),
    account_id    INTEGER REFERENCES accounts(account_id),
    score_id      INTEGER REFERENCES scores(score_id),
    run_id        INTEGER REFERENCES score_runs(run_id),
    event_type    TEXT NOT NULL CHECK (event_type IN ('queue_viewed','item_viewed','evidence_opened','accepted','skipped','disputed','adjusted','reverted','ruleset_viewed')),
    occurred_at   TEXT NOT NULL,
    rank_at_event INTEGER,
    detail_json   TEXT
);

-- §9.1 required indexes
CREATE INDEX idx_signal_events_lookup   ON signal_events (account_id, signal_type_id, occurred_at);
CREATE INDEX idx_scores_run_rank        ON scores (run_id, rank_in_queue);
CREATE INDEX idx_reasons_score_rank     ON reasons (score_id, rank);
CREATE INDEX idx_adjustments_rep_active ON queue_adjustments (rep_id, is_active, expires_at);
CREATE INDEX idx_task_events_rep_time   ON task_events (rep_id, occurred_at);
-- supporting indexes
CREATE INDEX idx_people_account         ON people (account_id);
CREATE INDEX idx_accounts_owner         ON accounts (owner_rep_id);
CREATE INDEX idx_observations_account   ON observations (account_id);
CREATE INDEX idx_disagreements_rep_acct ON disagreements (rep_id, account_id, status);
CREATE INDEX idx_scores_account         ON scores (account_id);
