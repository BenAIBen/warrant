"""Container entry point. DEPLOY_ARCHITECTURE.md §6.2.

    Render Start Command:  python start.py

Four steps:

    1. resolve target = warrant.db.db_path()
    2. seed_needed = (not os.path.exists(target)) or WARRANT_FORCE_RESEED == "1"
    3. if seed_needed: seed_db.main()   else: say so and skip
    4. app.main()  ->  serve_forever()

WHY THE CONDITIONAL IS LOAD-BEARING (§6.6). On Render's free tier the disk is
ephemeral, the file is never there, and the seeder runs every boot — which is
fine, because seed_db.py runs under a fixed seed and regenerates the corpus byte
for byte (T01). On a host with a persistent volume the file IS there on the
second boot, the seed is skipped, and the reps' disputes survive. That is the
whole of the upgrade path: same code, different WARRANT_DB_PATH. The conditional
has to be in the first version, not added later, or the upgrade becomes a code
change instead of a setting.

WHY A PYTHON FILE RATHER THAN `python seed_db.py && python app.py`:
  * the seed step must be conditional, and a conditional in a dashboard text
    field is a quoting problem waiting to happen
  * this is testable; a shell string in a vendor dashboard is not
  * it is one line the user types into one field, identical on Render, Railway
    or Fly

Imports os, sys, seed_db and app only — all stdlib or local — so T19
(test_every_python_file_imports_only_stdlib_or_local) keeps passing and no
requirements.txt entry is added.

WARRANT_FORCE_RESEED=1 wipes an existing database back to the pristine corpus.
It is DESTRUCTIVE on a persistent volume: every dispute, pin and mute a rep has
filed is deleted. It is off by default and the runbook marks it as destructive.
"""

import os
import sys

import app
import seed_db
from warrant import runtime
from warrant.db import db_path


def seed_if_needed():
    """Returns True if the seeder ran. Prints what it decided and why, because
    the deploy log is the only place anyone will look when the data is wrong."""
    target = db_path()
    forced = os.environ.get("WARRANT_FORCE_RESEED") == "1"
    exists = os.path.exists(target)

    if exists and not forced:
        print("database already present at %s, skipping seed" % target)
        sys.stdout.flush()
        return False

    if exists and forced:
        print("WARRANT_FORCE_RESEED=1 — reseeding over the existing database "
              "at %s. Anything a rep filed is being deleted." % target)
    else:
        print("no database at %s — seeding" % target)
    sys.stdout.flush()

    directory = os.path.dirname(target)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)

    # seed_db.main() prints its own summary block — cohort counts, event totals,
    # the verified line. That summary IS the reproducibility record for this
    # deploy, so it goes to stdout where the platform's log will keep it.
    seed_db.main()
    return True


def main():
    print("warrant-start build-marker 2026-08-13 · conditional seed, then serve")
    print(runtime.describe())
    sys.stdout.flush()
    seed_if_needed()
    return app.main()


if __name__ == "__main__":
    sys.exit(main())
