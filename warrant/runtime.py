"""Process-lifetime facts and the ephemeral-storage disclosure copy.

DEPLOY_ARCHITECTURE.md §3.2 (the meta block), §6.5 (the decision to ship on
ephemeral storage and disclose it in the rep's own sentence).

WHY THIS MODULE EXISTS — it is not in the §5.1/§6.2 file list and it is an
explicit, flagged deviation. §6.5 requires new rep-facing copy that does not
exist anywhere in the codebase today (the persistence notice, the restart
notice, the "or until this demo server restarts" clause). §2.5 forbids the
serialiser from inventing rep-facing copy, and §10.3 open question 1 recommends
that warrant/api.py never import warrant/render.py. So the new copy needs a home
that is neither the serialiser nor the HTML module. This is the same shape of
additive deviation as warrant/timeutil.py (README deviation 6): additive only,
no specified behaviour changed.

BOOT_ID and STARTED_AT are captured once, at import, and never recomputed. That
is the point: a changed boot_id is how the frontend detects that the container
restarted and the rep's disputes are gone (§6.5 requirement 3).
"""

import os
import secrets
from datetime import datetime, timezone

from warrant.db import is_ephemeral, persistence
from warrant.timeutil import fmt_ts, human_datetime

# Captured once per process. Not a cache of any score, reason or row — it is a
# fact about this process, and §7.2's caching prohibition does not reach it.
BOOT_ID = secrets.token_hex(4)
STARTED_AT = fmt_ts(datetime.now(timezone.utc))

# §6.5 requirement 2: the trailing clause on every write confirmation, because
# the moment a rep files a dispute is the moment they have just extended trust.
EPHEMERAL_CLAUSE = ", or until this demo server restarts, whichever comes first"

RESTART_NOTICE_TITLE = "The demo server restarted."

RESTART_NOTICE = (
    "Anything you filed in this session — disputes, pins, mutes — is gone. The "
    "queue below has been rebuilt from the same seeded data, so the accounts and "
    "their evidence are exactly as they were. This is a limitation of the free "
    "hosting tier, not of Warrant. On a host with a persistent disk, everything "
    "you file survives.")


def boot_id():
    return BOOT_ID


def started_at():
    return STARTED_AT


def started_at_display():
    return human_datetime(STARTED_AT)


def persistence_notice():
    """§6.5 requirement 1. None when the host has a persistent disk.

    Rendered verbatim by the frontend as a persistent line at the top of every
    view — not a dismissible toast, not a footnote. Quiet forgetting is the
    failure warrant/feedback.py was written to prevent, and a demo that forgets
    a rep's dispute without saying so enacts it.
    """
    if not is_ephemeral():
        return None
    return ("This demo server runs on free hosting with no persistent disk. It "
            "last restarted on %s. Anything a rep filed before then — disputes, "
            "pins, mutes — is gone. Everything you file now lasts until the next "
            "restart." % started_at_display())


def expiry_clause():
    """The suffix an effect confirmation carries on an ephemeral host, '' on a
    persistent one. One env var, two behaviours, zero branches in the frontend."""
    return EPHEMERAL_CLAUSE if is_ephemeral() else ""


def restart_notice():
    """§9.8 third moment: shown when meta.boot_id changed mid-session."""
    if not is_ephemeral():
        return None
    return RESTART_NOTICE


def db_target():
    """The database path this process will use, for the boot log."""
    from warrant.db import db_path
    return db_path()


def describe():
    """One line for stdout at boot, so the deploy log records what shipped."""
    return ("boot_id=%s started_at=%s persistence=%s db=%s"
            % (BOOT_ID, STARTED_AT, persistence(), os.path.basename(db_target())))
