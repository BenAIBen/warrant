"""Tests for the JSON API layer. DEPLOY_ARCHITECTURE.md §7.3 and §8.4.

The existing suite cannot see the JSON layer at all, so these tests exist to
assert the same properties one layer out:

  * the serialiser is still live-query (a raw sqlite3 mutation moves a payload)
  * the wire responses are uncacheable
  * sum(reason points) == score.points still holds ON THE WIRE
  * the serialiser contains no arithmetic, no ranking, no sorting
  * SCORING PARITY: the hosted path returns exactly what the local engine
    returns for the same account and the same rep
  * CORS behaves as §4 specifies, exercised over a real socket
  * the dispute -> revert loop survives the port, end to end over HTTP
  * nothing credential-shaped is in docs/

Everything here runs against a real seeded database and, where it matters, a
real ThreadingHTTPServer on a real port. Nothing is mocked.
"""

import ast
import json
import os
import sqlite3
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import support

REPO_ROOT = support.REPO_ROOT
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import app as app_mod                                            # noqa: E402
from warrant import api                                          # noqa: E402
from warrant import reasons as reasons_mod                       # noqa: E402
from warrant.db import connect                                   # noqa: E402
from warrant.queue import build_run, budget_usage                # noqa: E402
from warrant.scoring import score_account                        # noqa: E402

AS_OF = support.AS_OF
ALLOWED_ORIGIN = "http://127.0.0.1:8080"
DISALLOWED_ORIGIN = "https://evil-example.github.io"

import re                                                        # noqa: E402

RANDOM_RUN = re.compile(r"[A-Za-z0-9+/_-]{32,}")
HEX_RUN = re.compile(r"^[0-9a-f]{32,}$")


def looks_like_a_key(text):
    """A 32+ character run that actually resembles a credential rather than a
    comment rule or a MIME type. See TestDocsFolder for why each clause is
    here — every one of them was added after a false positive, not before."""
    if len(set(text)) < 8:
        return False                       # -------- or ========
    if HEX_RUN.match(text):
        return True
    has_digit = any(c.isdigit() for c in text)
    has_upper = any(c.isupper() for c in text)
    has_lower = any(c.islower() for c in text)
    return has_digit and has_upper and has_lower


def build_queue_payload(conn, rep_id=1):
    """What GET /api/queue would serialise, without the socket."""
    rep = dict(conn.execute("SELECT * FROM reps WHERE rep_id = ?",
                            (rep_id,)).fetchone())
    run_id, items, _adj = build_run(conn, rep_id, AS_OF)
    conn.commit()
    return api.queue_payload(rep, run_id, items,
                             budget_usage(conn, rep_id, AS_OF), {})


class TestApiIsStillLiveQuery(unittest.TestCase):
    """§7.3: the same proof the three TestLiveDatabaseNotFixtures tests give,
    applied to the serialiser rather than to the engine."""

    def test_api_queue_reflects_a_live_db_mutation(self):
        path = support.fresh_seeded_db("api-live")
        conn = connect(path)
        before = build_queue_payload(conn)
        target = before["items"][0]
        account_id = target["account_id"]

        # A separate raw connection the application knows nothing about.
        raw = sqlite3.connect(path)
        changed = raw.execute(
            "UPDATE signal_events SET magnitude = magnitude * 8 "
            "WHERE account_id = ? AND occurred_at <= ?",
            (account_id, AS_OF)).rowcount
        raw.commit()
        raw.close()
        self.assertGreater(changed, 0, "no events to mutate — bad fixture")

        after = build_queue_payload(conn)
        moved = next(i for i in after["items"] if i["account_id"] == account_id)
        self.assertNotEqual(
            target["points"], moved["points"],
            "the API payload did not move when the database moved — something "
            "between score_account() and the JSON is holding a cache")
        conn.close()

    def test_api_detail_rescores_rather_than_reading_persisted_rows(self):
        """§7.2 item 3, the most likely violation: serving a detail view from
        the scores/reasons rows the last run wrote instead of re-scoring."""
        path = support.fresh_seeded_db("api-detail-live")
        conn = connect(path)
        payload = build_queue_payload(conn)
        account_id = payload["items"][0]["account_id"]

        raw = sqlite3.connect(path)
        raw.execute("UPDATE signal_types SET base_weight = base_weight - 3.0 "
                    "WHERE code = ?", ("icp_industry_match",))
        raw.commit()
        raw.close()

        run_id, items, _adj = build_run(conn, 1, AS_OF)
        conn.commit()
        item = next(i for i in items if i.account_id == account_id)
        context = app_mod.Handler._detail_context(
            app_mod.Handler.__new__(app_mod.Handler), conn, 1, item, AS_OF)
        rep = dict(conn.execute("SELECT * FROM reps WHERE rep_id = 1").fetchone())
        detail = api.detail_payload(rep, item,
                                    budget_usage(conn, 1, AS_OF), len(items),
                                    context)
        engine = score_account(conn, account_id, 1, AS_OF)
        self.assertAlmostEqual(detail["verdict"]["points"], engine.points, 2)
        conn.close()


class TestApiExplanationIsTheModel(unittest.TestCase):
    """T07's assertion, made on the wire."""

    @classmethod
    def setUpClass(cls):
        cls.path = support.build_seeded_db("api")

    def test_api_reason_points_sum_to_score_points(self):
        conn = connect(self.path)
        rep = dict(conn.execute("SELECT * FROM reps WHERE rep_id = 1").fetchone())
        run_id, items, _adj = build_run(conn, 1, AS_OF)
        conn.commit()
        handler = app_mod.Handler.__new__(app_mod.Handler)
        usage = budget_usage(conn, 1, AS_OF)

        checked = 0
        for item in items[:25]:
            context = app_mod.Handler._detail_context(handler, conn, 1, item,
                                                      AS_OF)
            payload = api.detail_payload(rep, item, usage, len(items), context)
            shown_sum = sum(r["points"] for r in payload["reasons"])
            withheld_sum = sum(r.points for r in item.all_reasons if not r.shown)
            self.assertAlmostEqual(
                shown_sum + withheld_sum, payload["verdict"]["points"], 2,
                "account %s: the reasons on the wire do not add up to the score "
                "on the wire" % payload["account"]["account_id"])
            checked += 1
        self.assertGreaterEqual(checked, 25)
        conn.close()

    def test_the_payload_carries_only_shown_reasons(self):
        """§3.7: withheld reasons are disclosed in aggregate by limits_line and
        never sent over the wire."""
        conn = connect(self.path)
        rep = dict(conn.execute("SELECT * FROM reps WHERE rep_id = 1").fetchone())
        run_id, items, _adj = build_run(conn, 1, AS_OF)
        conn.commit()
        handler = app_mod.Handler.__new__(app_mod.Handler)
        usage = budget_usage(conn, 1, AS_OF)
        found_withheld = 0
        for item in items[:15]:
            context = app_mod.Handler._detail_context(handler, conn, 1, item,
                                                      AS_OF)
            payload = api.detail_payload(rep, item, usage, len(items), context)
            self.assertEqual(len(payload["reasons"]), len(item.shown_reasons))
            if len(item.all_reasons) > len(item.shown_reasons):
                found_withheld += 1
                self.assertTrue(payload["limits_line"])
        self.assertGreater(found_withheld, 0,
                           "no account in the sample withheld a reason — the "
                           "assertion proved nothing")
        conn.close()

    def test_every_detail_payload_has_a_non_empty_limits_line(self):
        """T09, on the wire. §5.5 makes this mandatory."""
        conn = connect(self.path)
        rep = dict(conn.execute("SELECT * FROM reps WHERE rep_id = 1").fetchone())
        run_id, items, _adj = build_run(conn, 1, AS_OF)
        conn.commit()
        handler = app_mod.Handler.__new__(app_mod.Handler)
        usage = budget_usage(conn, 1, AS_OF)
        for item in items[:20]:
            context = app_mod.Handler._detail_context(handler, conn, 1, item,
                                                      AS_OF)
            payload = api.detail_payload(rep, item, usage, len(items), context)
            self.assertTrue(payload["limits_line"].strip())
        conn.close()


class TestScoringParity(unittest.TestCase):
    """THE BRIEF'S CENTRAL QUESTION: does the hosted path produce the same
    scores as the local engine?

    Concretely: every points value and every reason value in the JSON payload
    must equal what score_account() / build_run() return directly for the same
    account and the same rep. If they can diverge, the port has broken the
    guarantee the whole product rests on.
    """

    @classmethod
    def setUpClass(cls):
        cls.path = support.build_seeded_db("api")

    def test_queue_payload_points_equal_the_engine(self):
        conn = connect(self.path)
        payload = build_queue_payload(conn)
        engine = {}
        for row in payload["items"]:
            score = score_account(conn, row["account_id"], 1, AS_OF)
            engine[row["account_id"]] = score

        for row in payload["items"]:
            score = engine[row["account_id"]]
            self.assertEqual(row["points"], score.points,
                             "account %s: wire points != engine points"
                             % row["account_id"])
            self.assertEqual(row["points_display"],
                             reasons_mod.points_display(score.points))
            self.assertEqual(row["band"], score.band)
            self.assertEqual(row["band_label"],
                             reasons_mod.band_label(score.band))
        self.assertGreater(len(payload["items"]), 40)
        conn.close()

    def test_detail_reason_values_equal_the_engine(self):
        conn = connect(self.path)
        rep = dict(conn.execute("SELECT * FROM reps WHERE rep_id = 1").fetchone())
        run_id, items, _adj = build_run(conn, 1, AS_OF)
        conn.commit()
        handler = app_mod.Handler.__new__(app_mod.Handler)
        usage = budget_usage(conn, 1, AS_OF)

        compared_reasons = 0
        for item in items[:20]:
            context = app_mod.Handler._detail_context(handler, conn, 1, item,
                                                      AS_OF)
            payload = api.detail_payload(rep, item, usage, len(items), context)
            self.assertEqual(payload["verdict"]["points"], item.score.points)
            self.assertEqual(payload["verdict"]["confidence"],
                             item.score.confidence)
            self.assertEqual(payload["limits_line"], item.limits_line)
            for index, wire in enumerate(payload["reasons"]):
                engine_reason = item.shown_reasons[index]
                self.assertEqual(wire["points"], engine_reason.points)
                self.assertEqual(wire["rank"], engine_reason.rank)
                self.assertEqual(wire["text"], engine_reason.text)
                self.assertEqual(wire["evidence_summary"],
                                 engine_reason.evidence_summary)
                self.assertEqual(wire["signal_type_id"],
                                 engine_reason.signal_type_id)
                compared_reasons += 1
        self.assertGreater(compared_reasons, 50)
        conn.close()

    def test_kestrel_worked_example_survives_the_port(self):
        """The §4.4 worked example, through the serialiser. 61.24, not 59.87 —
        README deviation 1, carried forward unchanged by this port."""
        path, conn = support.build_kestrel_db()
        rep = dict(conn.execute("SELECT * FROM reps WHERE rep_id = 1").fetchone())
        run_id, items, _adj = build_run(conn, 1, AS_OF)
        conn.commit()
        item = next(i for i in items
                    if i.account_id == support.KESTREL_ACCOUNT_ID)
        handler = app_mod.Handler.__new__(app_mod.Handler)
        context = app_mod.Handler._detail_context(handler, conn, 1, item, AS_OF)
        payload = api.detail_payload(rep, item, budget_usage(conn, 1, AS_OF),
                                     len(items), context)
        direct = score_account(conn, support.KESTREL_ACCOUNT_ID, 1, AS_OF)
        self.assertAlmostEqual(payload["verdict"]["points"], 61.24, 2)
        self.assertEqual(payload["verdict"]["points"], direct.points)
        self.assertEqual(payload["verdict"]["band"], "ACT_NOW")
        self.assertEqual(payload["verdict"]["band_label"], "ACT NOW")
        conn.close()


class TestSerialiserContainsNoArithmetic(unittest.TestCase):
    """§7.3's fourth test. Same family as T19 and T20: this codebase prefers a
    rule that is mechanically checkable over a rule that is written down."""

    API_PATH = os.path.join(REPO_ROOT, "warrant", "api.py")

    def _tree(self):
        return ast.parse(open(self.API_PATH, encoding="utf-8").read(),
                         filename=self.API_PATH)

    def test_api_serialiser_contains_no_arithmetic(self):
        offenders = []
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.BinOp):
                for side in (node.left, node.right):
                    for inner in ast.walk(side):
                        if isinstance(inner, ast.Name) and "points" in inner.id:
                            offenders.append((node.lineno, "BinOp on %s"
                                              % inner.id))
                        if (isinstance(inner, ast.Attribute)
                                and "points" in inner.attr):
                            offenders.append((node.lineno, "BinOp on .%s"
                                              % inner.attr))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in ("sorted", "min", "max"):
                    offenders.append((node.lineno, node.func.id))
        self.assertEqual(offenders, [],
                         "warrant/api.py computes something it should only be "
                         "serialising: %r" % (offenders,))

    def test_the_detector_actually_catches_bad_code(self):
        """Negative control — without this the test above proves nothing."""
        bad = ast.parse("total = score.points * 2\nbest = max(reasons)\n")
        hits = []
        for node in ast.walk(bad):
            if isinstance(node, ast.BinOp):
                for side in (node.left, node.right):
                    for inner in ast.walk(side):
                        if (isinstance(inner, ast.Attribute)
                                and "points" in inner.attr):
                            hits.append("binop")
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "max"):
                hits.append("max")
        self.assertEqual(sorted(hits), ["binop", "max"])

    def test_api_does_not_import_the_html_module(self):
        """§10.3 open question 1: an API module that depends on an HTML module
        invites HTML into JSON."""
        source = open(self.API_PATH, encoding="utf-8").read()
        tree = ast.parse(source)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported.append(alias.name)
        self.assertNotIn("warrant.render", imported)
        for name in imported:
            self.assertNotIn("render", name)

    def test_no_caching_primitive_anywhere_in_the_live_path(self):
        """§7.2 items 1 and 2: no lru_cache, no functools.cache, no module-level
        dict standing in for one."""
        targets = [self.API_PATH,
                   os.path.join(REPO_ROOT, "app.py"),
                   os.path.join(REPO_ROOT, "warrant", "scoring.py"),
                   os.path.join(REPO_ROOT, "warrant", "queue.py"),
                   os.path.join(REPO_ROOT, "warrant", "reasons.py")]
        for path in targets:
            source = open(path, encoding="utf-8").read()
            self.assertNotIn("lru_cache", source, path)
            self.assertNotIn("functools.cache", source, path)
            self.assertNotIn("from functools import cache", source, path)


# ---------------------------------------------------------------------------
# Over a real socket
# ---------------------------------------------------------------------------

class LiveServer:
    """A real ThreadingHTTPServer on a real ephemeral port."""

    def __init__(self, db_path, allowed_origins):
        self.db_path = db_path
        self.allowed_origins = allowed_origins
        self.previous = {}

    def __enter__(self):
        for key, value in (("WARRANT_DB_PATH", self.db_path),
                           ("WARRANT_ALLOWED_ORIGINS", self.allowed_origins),
                           ("WARRANT_PERSISTENCE", "ephemeral")):
            self.previous[key] = os.environ.get(key)
            os.environ[key] = value
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app_mod.Handler)
        self.port = self.server.server_address[1]
        self.base = "http://127.0.0.1:%d" % self.port
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return False


def http_get(url, origin=None):
    request = Request(url, method="GET")
    if origin:
        request.add_header("Origin", origin)
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, dict(response.headers), response.read()
    except HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def http_post(url, fields, origin=None):
    body = urlencode(fields).encode("utf-8")
    request = Request(url, data=body, method="POST")
    request.add_header("Content-Type",
                       "application/x-www-form-urlencoded;charset=UTF-8")
    if origin:
        request.add_header("Origin", origin)
    try:
        with urlopen(request, timeout=60) as response:
            return response.status, dict(response.headers), response.read()
    except HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def http_options(url, origin=None):
    request = Request(url, method="OPTIONS")
    if origin:
        request.add_header("Origin", origin)
        request.add_header("Access-Control-Request-Method", "POST")
        request.add_header("Access-Control-Request-Headers", "Content-Type")
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, dict(response.headers), response.read()
    except HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


class TestLiveHttpApi(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db = support.build_seeded_db("api-http")

    def test_api_response_headers_are_no_store(self):
        """§7.3, second required test. Render sits behind a CDN edge; a
        cacheable /api/queue would be served from that edge and the rep would
        see a stale queue while the backend logged nothing."""
        with LiveServer(self.db, ALLOWED_ORIGIN) as server:
            for path in ("/api/health", "/api/reps", "/api/queue?rep=1",
                         "/api/adjustments?rep=1", "/api/metrics",
                         "/api/ruleset"):
                status, headers, _body = http_get(server.base + path)
                self.assertEqual(status, 200, path)
                self.assertEqual(headers.get("Cache-Control"), "no-store", path)
                self.assertIsNone(headers.get("ETag"), path)
                self.assertIsNone(headers.get("Last-Modified"), path)
                self.assertEqual(headers.get("Content-Type"),
                                 "application/json; charset=utf-8", path)
                self.assertIsNotNone(headers.get("Content-Length"), path)

    def test_health_is_cheap_and_reports_the_corpus(self):
        with LiveServer(self.db, ALLOWED_ORIGIN) as server:
            status, _headers, body = http_get(server.base + "/api/health")
            payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["seeded"])
        self.assertEqual(payload["accounts"], 240)
        self.assertEqual(len(payload["reps"]), 4)
        self.assertEqual(payload["meta"]["as_of"], AS_OF)
        self.assertEqual(payload["meta"]["persistence"], "ephemeral")
        self.assertIn("no persistent disk",
                      payload["meta"]["persistence_notice"])

    def test_queue_returns_the_expected_patch_size(self):
        with LiveServer(self.db, ALLOWED_ORIGIN) as server:
            status, _headers, body = http_get(server.base + "/api/queue?rep=1")
            payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["account_count"], 53)
        self.assertEqual(len(payload["items"]), 53)
        self.assertEqual(payload["items"][0]["rank_in_queue"], 1)

    def test_unknown_rep_and_unknown_route_are_404_with_an_error_shape(self):
        with LiveServer(self.db, ALLOWED_ORIGIN) as server:
            status, _h, body = http_get(server.base + "/api/queue?rep=999")
            self.assertEqual(status, 404)
            self.assertEqual(json.loads(body)["error"]["code"], "NOT_FOUND")
            status, _h, body = http_get(server.base + "/api/nope")
            self.assertEqual(status, 404)
            self.assertEqual(json.loads(body)["error"]["code"], "NOT_FOUND")

    def test_html_routes_still_work_and_carry_no_cors_headers(self):
        """§4.6: the HTML app is unchanged and same-origin. It does not need
        CORS headers and must not get them."""
        with LiveServer(self.db, ALLOWED_ORIGIN) as server:
            status, headers, body = http_get(server.base + "/queue?rep=1",
                                             origin=ALLOWED_ORIGIN)
        self.assertEqual(status, 200)
        self.assertIn(b"Warrant", body)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))


class TestCors(unittest.TestCase):
    """§4, exercised over a real socket with a real Origin header."""

    @classmethod
    def setUpClass(cls):
        cls.db = support.build_seeded_db("api-http")

    def test_allowed_origin_gets_the_header(self):
        with LiveServer(self.db, ALLOWED_ORIGIN) as server:
            status, headers, _body = http_get(server.base + "/api/health",
                                              origin=ALLOWED_ORIGIN)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"),
                         ALLOWED_ORIGIN)
        self.assertEqual(headers.get("Vary"), "Origin")

    def test_disallowed_origin_gets_no_header_but_still_gets_a_200(self):
        """The §1.5 trap, asserted: the backend logs a clean 200 and the browser
        discards the body. That is why §9.3's frontend state exists."""
        with LiveServer(self.db, ALLOWED_ORIGIN) as server:
            status, headers, body = http_get(server.base + "/api/health",
                                             origin=DISALLOWED_ORIGIN)
        self.assertEqual(status, 200)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))
        self.assertTrue(json.loads(body)["ok"])

    def test_a_prefix_lookalike_origin_does_not_match(self):
        """§4.2: exact string comparison. https://evil-<user>.github.io must not
        match https://<user>.github.io."""
        with LiveServer(self.db, "https://someone.github.io") as server:
            status, headers, _body = http_get(
                server.base + "/api/health",
                origin="https://evil-someone.github.io")
            self.assertEqual(status, 200)
            self.assertIsNone(headers.get("Access-Control-Allow-Origin"))
            status, headers, _body = http_get(
                server.base + "/api/health",
                origin="https://someone.github.io/repo")
            self.assertIsNone(headers.get("Access-Control-Allow-Origin"),
                              "an origin with a path must not match")

    def test_empty_allowlist_emits_no_cors_headers_at_all(self):
        """§4.2: default empty, fail closed. A backend that defaults to
        permissive is a backend that ships permissive."""
        with LiveServer(self.db, "") as server:
            status, headers, _body = http_get(server.base + "/api/health",
                                              origin=ALLOWED_ORIGIN)
        self.assertEqual(status, 200)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    def test_no_origin_header_gets_a_normal_response(self):
        with LiveServer(self.db, ALLOWED_ORIGIN) as server:
            status, headers, _body = http_get(server.base + "/api/health")
        self.assertEqual(status, 200)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    def test_preflight_is_200_with_content_length_zero(self):
        """§4.4, and the three decisions in it.

        200, NOT 204: RFC 7230 forbids Content-Length on a 204 and
        protocol_version is HTTP/1.1, so every response must be self-framing.
        Max-Age 600 caches the browser's permission decision, not a score.
        """
        with LiveServer(self.db, ALLOWED_ORIGIN) as server:
            status, headers, body = http_options(server.base + "/api/dispute",
                                                 origin=ALLOWED_ORIGIN)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Length"), "0")
        self.assertEqual(body, b"")
        self.assertEqual(headers.get("Access-Control-Allow-Origin"),
                         ALLOWED_ORIGIN)
        self.assertEqual(headers.get("Access-Control-Allow-Methods"),
                         "GET, POST, OPTIONS")
        self.assertEqual(headers.get("Access-Control-Allow-Headers"),
                         "Content-Type")
        self.assertEqual(headers.get("Access-Control-Max-Age"), "600")
        self.assertEqual(headers.get("Vary"), "Origin")

    def test_preflight_from_a_disallowed_origin_is_200_with_no_cors_headers(self):
        """§4.4 detail 3: not a 403. The browser blocks the real request, which
        is correct, and the server has not leaked its allowlist."""
        with LiveServer(self.db, ALLOWED_ORIGIN) as server:
            status, headers, body = http_options(server.base + "/api/dispute",
                                                 origin=DISALLOWED_ORIGIN)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Length"), "0")
        self.assertEqual(body, b"")
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))
        self.assertIsNone(headers.get("Access-Control-Allow-Methods"))

    def test_options_never_returns_501(self):
        """§3.3's last row: 501 must never occur for OPTIONS once §4.4 ships."""
        with LiveServer(self.db, ALLOWED_ORIGIN) as server:
            for path in ("/api/queue", "/api/task", "/queue"):
                status, _headers, _body = http_options(server.base + path,
                                                       origin=ALLOWED_ORIGIN)
                self.assertNotEqual(status, 501, path)
                self.assertEqual(status, 200, path)


class TestWriteLoopOverHttp(unittest.TestCase):
    """The heart of the feature, end to end over the wire: dispute -> the score
    changes -> revert -> the score is restored."""

    def test_dispute_then_revert_over_the_api(self):
        db = support.fresh_seeded_db("api-writeloop")
        with LiveServer(db, ALLOWED_ORIGIN) as server:
            base = server.base

            _s, _h, body = http_get(base + "/api/queue?rep=1")
            queue = json.loads(body)
            account_id = queue["items"][0]["account_id"]
            points_before = queue["items"][0]["points"]

            _s, _h, body = http_get(
                base + "/api/account/%d?rep=1" % account_id)
            detail = json.loads(body)
            target = detail["reasons"][0]
            action = target["actions"][0]
            self.assertEqual(action["code"], "EVIDENCE_WRONG")

            status, _h, body = http_post(base + "/api/dispute", action["fields"],
                                         origin=ALLOWED_ORIGIN)
            self.assertEqual(status, 200)
            result = json.loads(body)
            self.assertTrue(result["ok"])
            self.assertEqual(result["effect"]["kind"], "suppress_signal_type")
            adjustment_id = result["effect"]["undo_adjustment_id"]
            self.assertIsNotNone(adjustment_id)
            # §6.5 requirement 2: on an ephemeral host the confirmation says so
            # in the same breath as the return date.
            self.assertIn("or until this demo server restarts",
                          result["effect"]["confirmation"])
            self.assertEqual(result["next"]["view"], "account")

            _s, _h, body = http_get(base + "/api/account/%d?rep=1" % account_id)
            after = json.loads(body)
            self.assertLess(after["verdict"]["points"], points_before,
                            "the dispute did not move the score")
            suppressed = [r for r in after["reasons"] if r["is_suppressed"]]
            self.assertTrue(suppressed, "no reason came back struck through")
            self.assertIn("→ 0 pts", suppressed[0]["points_display"])
            self.assertTrue(suppressed[0]["suppression_note"])
            self.assertEqual(suppressed[0]["actions"], [])
            self.assertEqual(suppressed[0]["undo_adjustment_id"], adjustment_id)

            status, _h, body = http_post(
                base + "/api/adjust/revert",
                {"rep": 1, "adjustment": adjustment_id, "account": account_id},
                origin=ALLOWED_ORIGIN)
            self.assertEqual(status, 200)
            reverted = json.loads(body)
            self.assertEqual(reverted["effect"]["kind"], "reverted")

            _s, _h, body = http_get(base + "/api/account/%d?rep=1" % account_id)
            restored = json.loads(body)
            self.assertAlmostEqual(restored["verdict"]["points"], points_before,
                                   2, "revert did not restore the score")
            self.assertEqual(
                [r for r in restored["reasons"] if r["is_suppressed"]], [])

    def test_mute_producing_dispute_sends_the_rep_to_the_queue(self):
        """§3.13 / §10.2: NOT_A_FIT takes the account out of the queue, so the
        server names 'queue' as the next view rather than handing the rep a
        near-error on a page that no longer exists for them."""
        db = support.fresh_seeded_db("api-mute")
        with LiveServer(db, ALLOWED_ORIGIN) as server:
            _s, _h, body = http_get(server.base + "/api/queue?rep=1")
            account_id = json.loads(body)["items"][0]["account_id"]

            status, _h, body = http_post(
                server.base + "/api/dispute",
                {"rep": 1, "account": account_id, "code": "NOT_A_FIT"})
            self.assertEqual(status, 200)
            result = json.loads(body)
            self.assertEqual(result["next"]["view"], "queue")
            self.assertEqual(result["effect"]["kind"], "mute_account")

            status, _h, body = http_get(
                server.base + "/api/account/%d?rep=1" % account_id)
            self.assertEqual(status, 404)
            self.assertEqual(json.loads(body)["error"]["code"], "NOT_IN_QUEUE")

    def test_budget_exceeded_is_409_with_the_same_sentence_as_the_html_page(self):
        db = support.fresh_seeded_db("api-budget")
        with LiveServer(db, ALLOWED_ORIGIN) as server:
            _s, _h, body = http_get(server.base + "/api/queue?rep=1")
            items = json.loads(body)["items"]
            statuses = []
            for item in items[:7]:
                status, _h, body = http_post(
                    server.base + "/api/adjust",
                    {"rep": 1, "account": item["account_id"], "kind": "pin",
                     "days": 14})
                statuses.append((status, body))
            final_status, final_body = statuses[-1]
        self.assertEqual(final_status, 409)
        payload = json.loads(final_body)
        self.assertEqual(payload["error"]["code"], "BUDGET_EXCEEDED")
        self.assertEqual(payload["error"]["title"], "Budget reached")
        self.assertIn("You already have", payload["error"]["message"])
        self.assertEqual(payload["error"]["detail"]["budget_key"], "pin")

    def test_reverting_another_reps_adjustment_is_404_not_a_silent_ok(self):
        """§10.2's second named divergence."""
        db = support.fresh_seeded_db("api-revert-404")
        with LiveServer(db, ALLOWED_ORIGIN) as server:
            _s, _h, body = http_get(server.base + "/api/queue?rep=1")
            account_id = json.loads(body)["items"][0]["account_id"]
            _s, _h, body = http_post(
                server.base + "/api/adjust",
                {"rep": 1, "account": account_id, "kind": "pin", "days": 14})
            adjustment_id = json.loads(body)["adjustment_id"]

            status, _h, body = http_post(
                server.base + "/api/adjust/revert",
                {"rep": 2, "adjustment": adjustment_id})
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"]["code"], "NOT_FOUND")

    def test_evidence_drawer_writes_the_event_that_clears_the_friction_gate(self):
        """§3.8: the drawer is a real request with a real side effect. A
        client-side reveal would never clear the gate."""
        db = support.fresh_seeded_db("api-friction")
        with LiveServer(db, ALLOWED_ORIGIN) as server:
            _s, _h, body = http_get(server.base + "/api/queue?rep=1")
            queue = json.loads(body)
            gated = [i for i in queue["items"] if not i["work_it_enabled"]]
            self.assertTrue(gated, "no gated item in this patch — README "
                                   "deviation 9 says ~5.7% of items are gated")
            account_id = gated[0]["account_id"]

            status, _h, body = http_post(
                server.base + "/api/task",
                {"rep": 1, "account": account_id, "rank": 1,
                 "action": "accepted"})
            self.assertEqual(status, 409)
            payload = json.loads(body)
            self.assertEqual(payload["error"]["code"], "EVIDENCE_REQUIRED")
            self.assertIn("Open evidence on one reason",
                          payload["error"]["message"])

            _s, _h, body = http_get(
                server.base + "/api/account/%d?rep=1" % account_id)
            detail = json.loads(body)
            drawer = detail["reasons"][0]["evidence_href"]
            self.assertTrue(drawer)
            status, _h, _body = http_get(server.base + drawer)
            self.assertEqual(status, 200)

            status, _h, _body = http_post(
                server.base + "/api/task",
                {"rep": 1, "account": account_id, "rank": 1,
                 "action": "accepted"})
            self.assertEqual(status, 200,
                             "opening the evidence drawer did not clear the "
                             "friction gate")

    def test_unknown_dispute_code_is_400_not_500(self):
        db = support.build_seeded_db("api-http")
        with LiveServer(db, ALLOWED_ORIGIN) as server:
            status, _h, body = http_post(
                server.base + "/api/dispute",
                {"rep": 1, "account": 1, "code": "NONSENSE"})
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"]["code"], "BAD_REQUEST")


class TestDocsFolder(unittest.TestCase):
    """§8.4. It will always pass. It exists so that it KEEPS passing when
    someone later adds an integration."""

    DOCS = os.path.join(REPO_ROOT, "docs")

    # Assembled from fragments so this file does not itself trip the scan it
    # performs — the same trick tests/test_queue.py::TestNoSecrets uses.
    #
    # WHY THIS SCANS FOR A NAME *WITH A VALUE* AND NOT FOR A BARE NAME.
    # The first version of this test scanned for the bare words and failed
    # immediately on three honest sentences: config.js saying "no keys, no
    # tokens", and app.js saying "Nothing here is a secret". A scanner that
    # fires on a file promising it holds no credentials is a scanner that
    # teaches people to delete the promise. What a leak actually looks like is
    # a credential NAME followed by a VALUE, so that is what this matches. The
    # repo-wide bare-word scan in tests/test_queue.py::TestNoSecrets is
    # unchanged and still applies to every .py, .sql and .example file, where
    # prose false positives do not arise.
    SECRET_NAMES = tuple(a + b for a, b in (
        ("api", "_key"), ("api", "key"), ("tok", "en"), ("sec", "ret"),
        ("pass", "word"), ("aws", "_access"), ("private", "_key"),
        ("client", "_sec" + "ret"), ("auth", "orization")))
    # NOTE THE NAME, AND WHY IT HAS A SUFFIX. This constant used to be named
    # after the bare HTTP auth scheme token. Its VALUE was correctly assembled
    # from fragments, but its NAME was not — and the assignment line put that
    # token immediately before a space and an equals sign, which is exactly the
    # run the repo-wide scan in tests/test_queue.py::TestNoSecrets looks for.
    # The scan fired on this file. The suffix breaks the run.
    BEARER_PREFIX = "Bear" + "er "

    def _value_patterns(self):
        import re
        out = []
        for name in self.SECRET_NAMES:
            # name, then an assignment or a colon, then 8+ characters of value.
            out.append(re.compile(re.escape(name) + r"""\s*[:=]\s*["']?[\w.+/-]{8,}""",
                                  re.IGNORECASE))
        out.append(re.compile(re.escape(self.BEARER_PREFIX) + r"[\w.+/-]{8,}",
                              re.IGNORECASE))
        return out

    def _docs_files(self):
        out = []
        for name in sorted(os.listdir(self.DOCS)):
            path = os.path.join(self.DOCS, name)
            if os.path.isfile(path):
                out.append(path)
        return out

    def test_the_five_required_files_exist(self):
        names = {os.path.basename(p) for p in self._docs_files()}
        for required in ("index.html", "config.js", "app.js", "styles.css",
                         ".nojekyll"):
            self.assertIn(required, names)

    def test_no_file_in_docs_contains_a_credential_shaped_string(self):
        offenders = []
        patterns = self._value_patterns()
        for path in self._docs_files():
            text = open(path, encoding="utf-8", errors="ignore").read()
            for pattern in patterns:
                for hit in pattern.findall(text):
                    offenders.append((os.path.basename(path), hit))
        self.assertEqual(offenders, [],
                         "credential-shaped assignments in docs/: %r"
                         % (offenders,))

    def test_the_credential_detector_actually_catches_a_leak(self):
        """Negative control. Without this the test above proves nothing —
        and the first version of it was passing for the wrong reason."""
        import re
        planted = [
            "window.CONFIG = { api" + "Key: \"abcd1234efgh5678\" };",
            "head" + "ers: { Author" + "ization: \"Bear" + "er sk_live_9f2a71c\" }",
            "pass" + "word = \"hunter2hunter2\"",
        ]
        patterns = self._value_patterns()
        for sample in planted:
            self.assertTrue(
                any(p.search(sample) for p in patterns),
                "the detector missed a planted credential: %r" % sample)

    def test_no_long_random_looking_run_in_docs(self):
        """A base64-shaped run of 32+ characters is what a leaked key looks
        like. Nothing in a hand-written static frontend should have one.

        Two exclusions, both learned by running it:

          * a run of one repeated character is a comment rule, not a key —
            the `/* --- ... --- */` separators in app.js tripped it
          * a long lowercase word is prose or a MIME type, not a key —
            "application/x-www-form-urlencoded" tripped it

        So the run must look like an actual credential: 8+ distinct characters
        AND either mixed case with a digit, or a 32+ character hex string.
        """
        offenders = []
        for path in self._docs_files():
            for number, raw in enumerate(
                    open(path, encoding="utf-8", errors="ignore"), start=1):
                for hit in RANDOM_RUN.findall(raw):
                    if looks_like_a_key(hit):
                        offenders.append((os.path.basename(path), number, hit))
        self.assertEqual(offenders, [],
                         "long random-looking strings in docs/: %r"
                         % (offenders,))

    def test_the_random_run_detector_actually_catches_a_key(self):
        """Negative control for the scanner above."""
        for planted in ("AKIA1J2K3L4M5N6O7P8Q9R0STUVWXYZab",
                        "9f2a71c4e8b0d35617ac92fe4408b1d7",
                        "xoxb-2f8Q1a9Zk3Lm7Pw5Rt0Yu6Vi4Ne8Bc"):
            self.assertTrue(looks_like_a_key(planted),
                            "detector missed %r" % planted)
        for benign in ("application/x-www-form-urlencoded",
                       "--------------------------------",
                       "supercalifragilisticexpialidocious"):
            self.assertFalse(looks_like_a_key(benign),
                             "detector false-positived on %r" % benign)

    def test_app_js_never_hardcodes_the_backend_url(self):
        """§5.2: app.js reads window.WARRANT_CONFIG.apiBase in exactly one
        place and every request is built from that constant."""
        source = open(os.path.join(self.DOCS, "app.js"), encoding="utf-8").read()
        self.assertNotIn("onrender", source)
        self.assertEqual(source.count("CONFIG.apiBase"), 2,
                         "apiBase should be read in exactly one place (two "
                         "references on one line: typeof check and value)")
        self.assertNotIn("https://", source.split("notConfiguredPanel")[0])

    def test_app_js_does_not_reimplement_scoring(self):
        """§2.3 names the forbidden functions. None of them may appear here.

        The leading block comment is skipped: it lists those names in order to
        say they are absent, and the first version of this test failed on its
        own documentation. Everything after the docstring is real code.
        """
        source = open(os.path.join(self.DOCS, "app.js"),
                      encoding="utf-8").read().split("*/", 1)[1]
        for forbidden in ("applyCap", "decayFactor", "magnitudeFactor",
                          "computeConfidence", "bandFrom", "rankReasons",
                          "selectShown", "buildLimitsLine", "pointsLabel",
                          "truncateAtWord", "freshnessChip", "adjustmentChip",
                          "compressedLimits", "scoreAccount"):
            self.assertNotIn(forbidden, source,
                             "app.js reimplements %s — §2.3 forbids it"
                             % forbidden)

    def test_app_js_does_not_format_rep_facing_values(self):
        """§5.4 rule 2's forbidden idioms, as source-level assertions."""
        source = open(os.path.join(self.DOCS, "app.js"), encoding="utf-8").read()
        body = source.split("*/", 1)[1]     # skip the module docstring comment
        for forbidden in ("Math.round", "toFixed(", ".sort(", "innerHTML",
                          "localStorage", "sessionStorage", "force-cache",
                          "serviceWorker"):
            self.assertNotIn(forbidden, body,
                             "app.js uses %s — §5.4/§7.2 forbid it" % forbidden)


class TestStartScript(unittest.TestCase):
    """§6.2. The conditional is what makes the persistent-volume upgrade a
    configuration change rather than a rewrite (§6.6)."""

    def test_seed_is_skipped_when_the_database_already_exists(self):
        import io
        import contextlib
        import start

        path = support.build_seeded_db("api")
        previous = os.environ.get("WARRANT_DB_PATH")
        os.environ["WARRANT_DB_PATH"] = path
        try:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                ran = start.seed_if_needed()
            output = buffer.getvalue()
        finally:
            if previous is None:
                os.environ.pop("WARRANT_DB_PATH", None)
            else:
                os.environ["WARRANT_DB_PATH"] = previous
        self.assertFalse(ran)
        self.assertIn("skipping seed", output)

    def test_start_imports_only_stdlib_or_local(self):
        path = os.path.join(REPO_ROOT, "start.py")
        tree = ast.parse(open(path, encoding="utf-8").read())
        allowed = set(sys.stdlib_module_names) | {"warrant", "seed_db", "app"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name.split(".")[0], allowed)
            elif isinstance(node, ast.ImportFrom) and node.module:
                self.assertIn(node.module.split(".")[0], allowed)

    def test_requirements_declares_zero_packages(self):
        path = os.path.join(REPO_ROOT, "requirements.txt")
        self.assertTrue(os.path.exists(path))
        for raw in open(path, encoding="utf-8"):
            line = raw.strip()
            self.assertTrue(not line or line.startswith("#"),
                            "requirements.txt declares a package: %r" % line)


class TestBindAndPortConfiguration(unittest.TestCase):
    """§6.3, both halves."""

    def _with_env(self, **values):
        from warrant import db as db_mod
        previous = {}
        for key, value in values.items():
            previous[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return previous, db_mod

    def _restore(self, previous):
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_bind_host_defaults_to_loopback(self):
        previous, db_mod = self._with_env(WARRANT_BIND_HOST=None)
        try:
            self.assertEqual(db_mod.bind_host(), "127.0.0.1")
        finally:
            self._restore(previous)

    def test_bind_host_is_configurable(self):
        previous, db_mod = self._with_env(WARRANT_BIND_HOST="0.0.0.0")
        try:
            self.assertEqual(db_mod.bind_host(), "0.0.0.0")
        finally:
            self._restore(previous)

    def test_port_falls_back_from_warrant_port_to_platform_port_to_default(self):
        previous, db_mod = self._with_env(WARRANT_PORT=None, PORT=None)
        try:
            self.assertEqual(db_mod.port(), 8000)
            os.environ["PORT"] = "10000"
            self.assertEqual(db_mod.port(), 10000)
            os.environ["WARRANT_PORT"] = "8123"
            self.assertEqual(db_mod.port(), 8123,
                             "WARRANT_PORT must keep precedence so local "
                             "behaviour is unchanged")
        finally:
            self._restore(previous)

    def test_origin_matching_is_exact(self):
        previous, db_mod = self._with_env(
            WARRANT_ALLOWED_ORIGINS="https://a.github.io, http://localhost:8000")
        try:
            self.assertTrue(db_mod.origin_allowed("https://a.github.io"))
            self.assertTrue(db_mod.origin_allowed("http://localhost:8000"))
            self.assertFalse(db_mod.origin_allowed("https://evil-a.github.io"))
            self.assertFalse(db_mod.origin_allowed("https://a.github.io/repo"))
            self.assertFalse(db_mod.origin_allowed("https://a.github.io/"))
            self.assertFalse(db_mod.origin_allowed(None))
            self.assertFalse(db_mod.origin_allowed(""))
        finally:
            self._restore(previous)

    def test_wildcard_is_an_explicit_opt_in(self):
        previous, db_mod = self._with_env(WARRANT_ALLOWED_ORIGINS="*")
        try:
            self.assertTrue(db_mod.origin_allowed("https://anything.test"))
        finally:
            self._restore(previous)


class TestExtractedStringsMatchTheHtmlPath(unittest.TestCase):
    """§2.5: the extractions must change no rendered output. The full proof is
    76 HTML views hashed before and after (DEPLOY_TEST_OUTPUT.md); these are the
    assertions that keep it true from here on."""

    def test_budget_sentence_is_one_string_in_both_paths(self):
        from warrant import render
        from warrant.queue import BudgetExceeded, budget_exceeded_message
        exc = BudgetExceeded("pin", 5, 5, "2026-08-18T09:00:00Z")
        sentence = budget_exceeded_message(exc)
        self.assertIn("You already have 5 pins", sentence)
        self.assertIn("18 Aug 2026", sentence)
        html = render.render_budget_exceeded(1, exc)
        self.assertIn(sentence, html)

    def test_rank_line_is_one_string_in_both_paths(self):
        class FakeItem:
            rank_in_queue = 3
            rank_before_adjustment = 3
        self.assertEqual(reasons_mod.rank_line(FakeItem(), 53), "rank 3 of 53")

        class Adjusted:
            rank_in_queue = 1
            rank_before_adjustment = 7
        self.assertEqual(reasons_mod.rank_line(Adjusted(), 53),
                         "rank 1 of 53 (was 7 before your adjustments)")


if __name__ == "__main__":
    unittest.main()
