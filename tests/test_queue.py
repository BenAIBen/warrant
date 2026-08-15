"""DESIGN_SPEC.md §9.3 — T10, T12, T13, T19, T20."""

import ast
import os
import re
import sys
import unittest

import support
from warrant.db import connect
from warrant.queue import (BUDGETS, BudgetExceeded, build_run, count_active,
                           create_adjustment, revert_adjustment)
from warrant.timeutil import shift

REPO_ROOT = support.REPO_ROOT


def queue_signature(conn, rep_id, as_of):
    """A byte-comparable rendering of a rep's queue."""
    _run_id, items, _adj = build_run(conn, rep_id, as_of, persist=False)
    return "\n".join(
        "%d|%d|%.2f|%s|%s|%s" % (i.rank_in_queue, i.account_id, i.score.points,
                                 i.score.band, i.score.confidence, i.limits_line)
        for i in items).encode("utf-8")


class TestT10RepIsolation(unittest.TestCase):
    """T10 — rep 1 creating a patch-wide suppression leaves rep 2 byte-identical."""

    def test_patch_wide_suppression_does_not_cross_reps(self):
        conn = connect(support.fresh_seeded_db("t10"))
        control_rep2 = queue_signature(conn, 2, support.AS_OF)
        control_rep1 = queue_signature(conn, 1, support.AS_OF)

        signal_type_id = conn.execute(
            "SELECT signal_type_id FROM signal_types WHERE code = ?",
            ("pricing_page_repeat",)).fetchone()["signal_type_id"]
        create_adjustment(conn, 1, "suppress_signal_type", support.AS_OF,
                          shift(support.AS_OF, days=30),
                          account_id=None, signal_type_id=signal_type_id)
        conn.commit()

        self.assertEqual(queue_signature(conn, 2, support.AS_OF), control_rep2,
                         "rep 1's suppression changed rep 2's queue")
        self.assertNotEqual(queue_signature(conn, 1, support.AS_OF), control_rep1,
                            "rep 1's own suppression had no effect on their queue")
        conn.close()

    def test_every_adjustment_query_filters_by_rep(self):
        """§7.3 invariant 2, enforced by inspection of the module source."""
        import warrant.scoring as scoring_mod
        source = open(scoring_mod.__file__, encoding="utf-8").read()
        start = source.index("def load_active_adjustments")
        body = source[start:start + 700]
        self.assertIn("rep_id = ?", body)


class TestT12BudgetEnforcement(unittest.TestCase):
    """T12 — the (n+1)th adjustment raises BudgetExceeded and is not written.
    Asserted for each of the six budget keys."""

    def setUp(self):
        self.conn = connect(support.fresh_seeded_db("t12-%s" % self._testMethodName))
        self.expires = shift(support.AS_OF, days=30)
        self.accounts = [r["account_id"] for r in self.conn.execute(
            "SELECT account_id FROM accounts WHERE owner_rep_id = 2 AND is_active = 1 "
            "ORDER BY account_id LIMIT 60").fetchall()]
        self.people = [r["person_id"] for r in self.conn.execute(
            "SELECT person_id FROM people ORDER BY person_id LIMIT 60").fetchall()]
        self.types = [r["signal_type_id"] for r in self.conn.execute(
            "SELECT signal_type_id FROM signal_types ORDER BY signal_type_id").fetchall()]

    def tearDown(self):
        self.conn.close()

    def _fill_and_overflow(self, key, make):
        limit = BUDGETS[key]
        for index in range(limit):
            make(index)
        self.assertEqual(count_active(self.conn, 2, key, support.AS_OF), limit)
        with self.assertRaises(BudgetExceeded) as caught:
            make(limit)
        self.assertEqual(caught.exception.key, key)
        self.assertEqual(caught.exception.limit, limit)
        # the over-budget row must not exist
        self.assertEqual(count_active(self.conn, 2, key, support.AS_OF), limit)

    def test_pin_budget_is_five(self):
        self._fill_and_overflow("pin", lambda i: create_adjustment(
            self.conn, 2, "pin", support.AS_OF, self.expires,
            account_id=self.accounts[i]))

    def test_demote_budget_is_ten(self):
        self._fill_and_overflow("demote", lambda i: create_adjustment(
            self.conn, 2, "demote", support.AS_OF, self.expires,
            account_id=self.accounts[i]))

    def test_mute_budget_is_twentyfive(self):
        self._fill_and_overflow("mute_account", lambda i: create_adjustment(
            self.conn, 2, "mute_account", support.AS_OF, self.expires,
            account_id=self.accounts[i]))

    def test_patch_wide_suppression_budget_is_three(self):
        self._fill_and_overflow("suppress_signal_type_global", lambda i:
            create_adjustment(self.conn, 2, "suppress_signal_type", support.AS_OF,
                              self.expires, account_id=None,
                              signal_type_id=self.types[i]))

    def test_account_scoped_suppression_budget_is_fifty(self):
        self._fill_and_overflow("suppress_signal_type_account", lambda i:
            create_adjustment(self.conn, 2, "suppress_signal_type", support.AS_OF,
                              self.expires, account_id=self.accounts[i % len(self.accounts)],
                              signal_type_id=self.types[i % len(self.types)]))

    def test_exclude_person_budget_is_fifty(self):
        self._fill_and_overflow("exclude_person", lambda i: create_adjustment(
            self.conn, 2, "exclude_person", support.AS_OF, self.expires,
            account_id=self.accounts[0], person_id=self.people[i]))

    def test_global_and_account_suppression_budgets_are_separate(self):
        for i in range(3):
            create_adjustment(self.conn, 2, "suppress_signal_type", support.AS_OF,
                              self.expires, account_id=None,
                              signal_type_id=self.types[i])
        # account-scoped still has room even though the patch-wide budget is full
        create_adjustment(self.conn, 2, "suppress_signal_type", support.AS_OF,
                          self.expires, account_id=self.accounts[0],
                          signal_type_id=self.types[5])
        self.assertEqual(count_active(self.conn, 2, "suppress_signal_type_account",
                                      support.AS_OF), 1)


class TestT13Expiry(unittest.TestCase):
    """T13 — an expired adjustment has no effect, with no background job."""

    def test_expired_suppression_does_not_change_points_or_order(self):
        conn = connect(support.fresh_seeded_db("t13"))
        control = queue_signature(conn, 1, support.AS_OF)

        signal_type_id = conn.execute(
            "SELECT signal_type_id FROM signal_types WHERE code = ?",
            ("product_usage_active",)).fetchone()["signal_type_id"]
        # expires_at strictly at as_of -> already expired at read time
        conn.execute(
            "INSERT INTO queue_adjustments (rep_id, kind, account_id, signal_type_id, "
            " person_id, created_at, expires_at, source_disagreement_id, is_active, "
            " reverted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "suppress_signal_type", None, signal_type_id, None,
             shift(support.AS_OF, days=-40), support.AS_OF, None, 1, None))
        conn.commit()

        self.assertEqual(queue_signature(conn, 1, support.AS_OF), control,
                         "an expired adjustment still affected the queue")

        # ... and the same row, unexpired, does bite. Proves the test is real.
        conn.execute("UPDATE queue_adjustments SET expires_at = ? WHERE signal_type_id = ? "
                     "AND rep_id = ?", (shift(support.AS_OF, days=30), signal_type_id, 1))
        conn.commit()
        self.assertNotEqual(queue_signature(conn, 1, support.AS_OF), control)
        conn.close()

    def test_no_adjustment_can_be_created_without_an_expiry(self):
        import sqlite3
        conn = connect(support.fresh_seeded_db("t13-null"))
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO queue_adjustments (rep_id, kind, account_id, "
                " signal_type_id, person_id, created_at, expires_at, "
                " source_disagreement_id, is_active, reverted_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (1, "pin", 1, None, None, support.AS_OF, None, None, 1, None))
        conn.close()

    def test_revert_deactivates_and_stamps(self):
        conn = connect(support.fresh_seeded_db("t13-revert"))
        account_id = conn.execute(
            "SELECT account_id FROM accounts WHERE owner_rep_id = 2 LIMIT 1"
        ).fetchone()["account_id"]
        adjustment_id = create_adjustment(conn, 2, "pin", support.AS_OF,
                                          shift(support.AS_OF, days=14),
                                          account_id=account_id)
        conn.commit()
        self.assertEqual(count_active(conn, 2, "pin", support.AS_OF), 1)
        revert_adjustment(conn, 2, adjustment_id, support.AS_OF)
        conn.commit()
        self.assertEqual(count_active(conn, 2, "pin", support.AS_OF), 0)
        row = conn.execute("SELECT * FROM queue_adjustments WHERE adjustment_id = ?",
                           (adjustment_id,)).fetchone()
        self.assertEqual(row["is_active"], 0)
        self.assertEqual(row["reverted_at"], support.AS_OF)
        conn.close()


class TestOrdering(unittest.TestCase):
    def test_pins_take_the_top_and_demotes_the_bottom(self):
        conn = connect(support.fresh_seeded_db("order"))
        _run, items, _adj = build_run(conn, 2, support.AS_OF, persist=False)
        bottom = items[-1].account_id
        top = items[0].account_id
        create_adjustment(conn, 2, "pin", support.AS_OF,
                          shift(support.AS_OF, days=14), account_id=bottom)
        create_adjustment(conn, 2, "demote", support.AS_OF,
                          shift(support.AS_OF, days=30), account_id=top)
        conn.commit()
        _run, items2, _adj = build_run(conn, 2, support.AS_OF, persist=False)
        self.assertEqual(items2[0].account_id, bottom, "pin did not reach rank 1")
        self.assertEqual(items2[-1].account_id, top, "demote did not reach the bottom")
        conn.close()

    def test_muted_accounts_leave_the_queue_but_ordering_is_deterministic(self):
        conn = connect(support.fresh_seeded_db("order-mute"))
        _run, items, _adj = build_run(conn, 2, support.AS_OF, persist=False)
        before = [i.account_id for i in items]
        target = before[3]
        create_adjustment(conn, 2, "mute_account", support.AS_OF,
                          shift(support.AS_OF, days=60), account_id=target)
        conn.commit()
        _run, items2, _adj = build_run(conn, 2, support.AS_OF, persist=False)
        after = [i.account_id for i in items2]
        self.assertNotIn(target, after)
        self.assertEqual(len(after), len(before) - 1)
        # identical runs must not shuffle
        _run, items3, _adj = build_run(conn, 2, support.AS_OF, persist=False)
        self.assertEqual([i.account_id for i in items3], after)
        conn.close()


# ---------------------------------------------------------------------------
# T19 / T20 — static analysis of the repo
# ---------------------------------------------------------------------------

def python_files():
    targets = []
    # start.py added with the deploy work (DEPLOY_ARCHITECTURE.md §6.2). It was
    # missing from this list, so T19 and T20 were not actually looking at the
    # container entry point — the one file a deploy runs first.
    for name in ("app.py", "seed_db.py", "start.py"):
        targets.append(os.path.join(REPO_ROOT, name))
    for folder in ("warrant", "tests"):
        directory = os.path.join(REPO_ROOT, folder)
        for entry in sorted(os.listdir(directory)):
            if entry.endswith(".py"):
                targets.append(os.path.join(directory, entry))
    return targets


# "start" is start.py at the repo root — a local module in exactly the same
# sense as app.py and seed_db.py, added for the deploy (§6.2). It imports os,
# sys, app and seed_db only; adding it here allowlists the local NAME, it does
# not exempt the file, which is now scanned by python_files() above.
LOCAL_MODULES = {"warrant", "tests", "support", "seed_db", "app", "start"}


class TestT19StandardLibraryOnly(unittest.TestCase):
    """T19 — no module imports a non-stdlib package. Asserted with ast."""

    def test_every_python_file_imports_only_stdlib_or_local(self):
        allowed = set(sys.stdlib_module_names) | LOCAL_MODULES
        offenders = []
        files = python_files()
        self.assertGreaterEqual(len(files), 10)
        for path in files:
            tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root = alias.name.split(".")[0]
                        if root not in allowed:
                            offenders.append((path, alias.name))
                elif isinstance(node, ast.ImportFrom):
                    if node.level:            # relative import, always local
                        continue
                    root = (node.module or "").split(".")[0]
                    if root and root not in allowed:
                        offenders.append((path, node.module))
        self.assertEqual(offenders, [], "non-stdlib imports found: %r" % (offenders,))

    def test_no_pip_installed_package_is_importable_by_name_in_source(self):
        for banned in ("requests", "flask", "numpy", "pandas", "sklearn"):
            self.assertNotIn(banned, sys.stdlib_module_names)


class TestT20NoInterpolatedSQL(unittest.TestCase):
    """T20 — no SQL string is built with an f-string or % interpolation.

    Asserted by walking every call to .execute/.executemany/.executescript and
    inspecting the first argument.
    """

    SQL_METHODS = ("execute", "executemany", "executescript")

    def test_no_execute_call_interpolates_a_value(self):
        offenders = []
        for path in python_files():
            if path.endswith(os.path.join("tests", "test_queue.py")):
                pass  # this file is inspected too; it must comply as well
            tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute) or func.attr not in self.SQL_METHODS:
                    continue
                if not node.args:
                    continue
                first = node.args[0]
                if isinstance(first, ast.JoinedStr):
                    offenders.append((path, node.lineno, "f-string"))
                elif isinstance(first, ast.BinOp) and isinstance(first.op, (ast.Mod, ast.Add)):
                    offenders.append((path, node.lineno, "%/+ interpolation"))
                elif (isinstance(first, ast.Call) and isinstance(first.func, ast.Attribute)
                      and first.func.attr in ("format", "join")):
                    offenders.append((path, node.lineno, "str.%s" % first.func.attr))
        self.assertEqual(offenders, [],
                         "interpolated SQL found: %r" % (offenders,))

    def test_the_detector_actually_catches_bad_sql(self):
        """Negative control — if this passes, the test above means something."""
        bad = ast.parse("conn.execute(f'SELECT {x}')")
        found = []
        for node in ast.walk(bad):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "execute"
                    and isinstance(node.args[0], ast.JoinedStr)):
                found.append(node.lineno)
        self.assertEqual(found, [1])


class TestNoSecrets(unittest.TestCase):
    """Build rule 4 — no credentials, API keys or tokens in any file."""

    # Assembled from fragments so that this file does not itself trip the scan
    # it performs — the scan covers tests/ too, including this module.
    PATTERNS = tuple(a + b for a, b in (
        ("api", "_key"), ("api", "key"), ("secret", "_key"), ("pass", "word="),
        ("author", "ization:"), ("bear", "er "), ("s", "k-"), ("aws", "_access"),
        ("private", "_key"), ("client", "_secret")))

    # CODE AND CONFIG (.py, .sql, .example) are scanned for the BARE NAME. A
    # source file has no reason to contain the word at all, so the strictest
    # possible rule applies and no false positive arises.
    CODE_SUFFIXES = (".py", ".sql", ".example")

    # PROSE (.md, .txt) is scanned for the NAME FOLLOWED BY A VALUE.
    #
    # WHY THE DIFFERENCE — and it is a real weakening, so here is the argument.
    # The bare-name rule was applied to .md too, and by the time the deploy
    # documents existed it was failing on five files, none of which contains a
    # credential: DEPLOY_ARCHITECTURE.md §8.4 fails because it SPECIFIES this
    # very scan and has to name the tokens to do so; HOSTING_RESEARCH.md fails
    # on a discussion of CORS request headers; the transcripts fail because they
    # are a verbatim log of agents discussing this test. A scanner that fires on
    # the document defining it, and on a file promising it holds no credentials,
    # is one that gets suppressed rather than fixed — and a suppressed scanner
    # catches nothing.
    #
    # What an actual leak looks like is a credential NAME next to a VALUE. That
    # is what the prose rule matches, and test_the_prose_detector_actually_
    # catches_a_leak below is the negative control that keeps it honest. The
    # strict bare-name rule is UNCHANGED for every file that ships as code.
    # [\w]* allows an identifier tail between the name and the separator, so
    # that the AWS-style name (the "aws" prefix, then "_access", then a
    # "_key_id" tail, then "=AKIA...") matches. Without the tail the planted
    # negative-control leak slipped straight through.
    VALUE = r"""[\w]*\s*[:=]\s*["']?[\w.+/-]{8,}"""
    PROSE_NAMES = tuple(a + b for a, b in (
        ("api", "_key"), ("api", "key"), ("secret", "_key"), ("pass", "word"),
        ("aws", "_access"), ("private", "_key"), ("client", "_secret"),
        ("author", "ization")))

    def _prose_patterns(self):
        out = [re.compile(re.escape(n) + self.VALUE, re.IGNORECASE)
               for n in self.PROSE_NAMES]
        # The scheme token below is separated from its value by a space, not a
        # colon, so it needs its own pattern.
        out.append(re.compile("bear" + "er" + r"\s+[\w.+/-]{8,}", re.IGNORECASE))
        # A provider-prefixed key. The leading word boundary matters: without
        # it, this fired mid-word on an ordinary hyphenated English compound in
        # a transcript (see the benign sample in the false-positive control).
        out.append(re.compile(r"\b" + "s" + "k-" + r"[\w]{16,}", re.IGNORECASE))
        return out

    def _repo_files(self):
        for root, dirs, files in os.walk(REPO_ROOT):
            dirs[:] = [d for d in dirs
                       if d not in (".git", "data", "__pycache__", ".Claude")]
            for name in files:
                yield os.path.join(root, name)

    def test_no_credential_shaped_string_in_code_or_config(self):
        """The strict rule, unchanged, over every file that ships as source."""
        offenders = []
        checked = 0
        for path in self._repo_files():
            if not path.endswith(self.CODE_SUFFIXES):
                continue
            checked += 1
            text = open(path, encoding="utf-8", errors="ignore").read().lower()
            for pattern in self.PATTERNS:
                if pattern in text:
                    offenders.append((os.path.relpath(path, REPO_ROOT), pattern))
        self.assertGreaterEqual(checked, 10, "the scan found almost no files")
        self.assertEqual(offenders, [], "credential-shaped strings: %r" % (offenders,))

    def test_no_credential_with_a_value_in_prose_or_documentation(self):
        offenders = []
        checked = 0
        patterns = self._prose_patterns()
        for path in self._repo_files():
            if not path.endswith((".md", ".txt")):
                continue
            checked += 1
            text = open(path, encoding="utf-8", errors="ignore").read()
            for pattern in patterns:
                for hit in pattern.findall(text):
                    offenders.append((os.path.relpath(path, REPO_ROOT), hit))
        self.assertGreaterEqual(checked, 5, "the scan found almost no documents")
        self.assertEqual(offenders, [],
                         "credential-shaped assignments in prose: %r" % (offenders,))

    def test_the_prose_detector_actually_catches_a_leak(self):
        """Negative control. The prose rule is looser than the code rule, so it
        only means something if it is shown to fire on a real-looking leak."""
        patterns = self._prose_patterns()
        planted = [
            "Set api" + "_key = \"9f2a71c4e8b0d356\" in the dashboard.",
            "api" + "Key: 'abcd1234efgh5678'",
            "Author" + "ization: Bear" + "er eyJhbGciOiJIUzI1NiJ9",
            "export aws" + "_access" + "_key_id=AKIA1J2K3L4M5N6O",
            "pass" + "word=hunter2hunter2",
            "the token is " + "s" + "k-1234567890abcdefghij",
            "client" + "_secret: 8b1d7ac92fe44081",
        ]
        for sample in planted:
            self.assertTrue(any(p.search(sample) for p in patterns),
                            "the prose detector missed a planted leak: %r" % sample)

    def test_the_prose_detector_does_not_fire_on_a_mention(self):
        """The other half of the control: these are the sentences that broke the
        bare-name rule, and they must NOT be reported."""
        patterns = self._prose_patterns()
        benign = [
            "assert that no file contains api" + "_key, api" + "key or token",
            "There are no credentials anywhere in this repo.",
            "The CORS request carried no Author" + "ization header.",
            "a de" + "s" + "k-notification arrived",
            "Nothing here is a se" + "cret. config.js holds one public URL.",
        ]
        for sample in benign:
            hits = [p.pattern for p in patterns if p.search(sample)]
            self.assertEqual(hits, [],
                             "the prose detector false-positived on %r via %r"
                             % (sample, hits))

    def test_env_example_has_placeholders_only(self):
        path = os.path.join(REPO_ROOT, ".env.example")
        self.assertTrue(os.path.exists(path), ".env.example is missing")
        text = open(path, encoding="utf-8").read()
        for name in ("WARRANT_DB_PATH", "WARRANT_PORT", "WARRANT_SEED",
                     "WARRANT_AS_OF", "WARRANT_RULESET_VERSION"):
            self.assertIn(name, text)


if __name__ == "__main__":
    unittest.main()
