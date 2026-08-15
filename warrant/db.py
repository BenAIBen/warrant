"""Connection handling. DESIGN_SPEC.md §9.1.

No ORM. Every caller gets sqlite3.Row and PRAGMA foreign_keys = ON.
Configuration comes from environment variables only — there are no
credentials in this system and nothing to authenticate to.
"""

import os
import sqlite3

DEFAULT_DB_PATH = os.path.join("data", "unify.db")
DEFAULT_AS_OF = "2026-08-11T09:00:00Z"
DEFAULT_RULESET_VERSION = "warrant-v1.0.0"
DEFAULT_PORT = 8000
DEFAULT_SEED = 20260811
DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_PERSISTENCE = "persistent"

ANCHOR_POINTS = 75.0  # DESIGN_SPEC.md §5.3. Not used in any arithmetic.

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(REPO_ROOT, "db", "schema.sql")


def db_path():
    """WARRANT_DB_PATH, default data/unify.db (relative to the repo root)."""
    configured = os.environ.get("WARRANT_DB_PATH", DEFAULT_DB_PATH)
    if os.path.isabs(configured):
        return configured
    return os.path.join(REPO_ROOT, configured)


def as_of():
    """WARRANT_AS_OF, default 2026-08-11T09:00:00Z (DESIGN_SPEC.md §3.13)."""
    return os.environ.get("WARRANT_AS_OF", DEFAULT_AS_OF)


def ruleset_version():
    return os.environ.get("WARRANT_RULESET_VERSION", DEFAULT_RULESET_VERSION)


def port():
    """WARRANT_PORT, then the platform's PORT, then 8000.

    DEPLOY_ARCHITECTURE.md §6.3 item 2. Render (and every other container host)
    injects PORT and expects the process to listen on it. WARRANT_PORT keeps
    precedence so a developer who sets it locally is not overridden by a stray
    PORT in their shell, and so local behaviour is exactly what README.md says.
    """
    configured = os.environ.get("WARRANT_PORT") or os.environ.get("PORT")
    return int(configured) if configured else DEFAULT_PORT


def bind_host():
    """WARRANT_BIND_HOST, default 127.0.0.1 (DEPLOY_ARCHITECTURE.md §6.3 item 1).

    The default is deliberately the loopback address: `python app.py` on a
    laptop behaves exactly as README.md documents and nobody exposes their
    machine to their network by accident. A container sets 0.0.0.0 explicitly.
    """
    return os.environ.get("WARRANT_BIND_HOST", DEFAULT_BIND_HOST)


def persistence():
    """WARRANT_PERSISTENCE — 'ephemeral' or 'persistent' (§3.2, §6.5).

    Default 'persistent', which is what a local checkout actually is; the
    ephemeral host is the one that has to declare itself. Named risk of that
    default: a typo in the dashboard value ("ephemerel") reads as persistent
    and the demo silently stops disclosing that it forgets. The runbook's
    verification step checks meta.persistence in a real response for exactly
    this reason.
    """
    return "ephemeral" if os.environ.get("WARRANT_PERSISTENCE") == "ephemeral" else "persistent"


def is_ephemeral():
    return persistence() == "ephemeral"


def allowed_origins():
    """WARRANT_ALLOWED_ORIGINS as an exact-match list (§4.2).

    Comma separated, whitespace stripped, empty by default. Empty means no CORS
    header is ever emitted — fail closed. A backend that defaults to permissive
    is a backend that ships permissive.
    """
    raw = os.environ.get("WARRANT_ALLOWED_ORIGINS", "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def origin_allowed(origin):
    """Exact string comparison only. No prefix, suffix or regex matching —
    https://evil-<user>.github.io must not match https://<user>.github.io."""
    if not origin:
        return False
    configured = allowed_origins()
    if "*" in configured:
        return True
    return origin in configured


def seed_value():
    return int(os.environ.get("WARRANT_SEED", str(DEFAULT_SEED)))


def connect(path=None):
    """sqlite3.Connection with row_factory = sqlite3.Row and FK enforcement.

    PRAGMA foreign_keys = ON is not optional — several cascade behaviours in
    DESIGN_SPEC.md §7 depend on it.
    """
    conn = sqlite3.connect(path or db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def apply_schema(conn):
    """Run db/schema.sql through executescript(). No sqlite3 CLI anywhere."""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as handle:
        conn.executescript(handle.read())
    conn.execute("PRAGMA foreign_keys = ON")
