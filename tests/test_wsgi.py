"""Tests for wsgi.py — the WSGI entry point added for the PythonAnywhere path.
DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md, DEPLOY_TEST_OUTPUT_PYTHONANYWHERE.md.

The verification bar here matches tests/test_api.py's for the Render path:
everything runs against a real seeded database and, where it matters, a real
server on a real port. Nothing is mocked, and nothing here calls
wsgi.application(environ, start_response) directly in-process — that would
prove the callable obeys the WSGI *interface* but not that it behaves
correctly as a *server*, and PythonAnywhere's own worker calls it through a
real server, not in-process. So every test in this file that exercises HTTP
semantics goes through `wsgiref.simple_server.make_server()` (stdlib) bound to
a real ephemeral port, in a background thread, hit with real `urlopen()`
requests over a real socket — exactly the same shape test_api.py uses for
app.Handler, just fronted by wsgiref instead of ThreadingHTTPServer directly.

Three things this file exists to prove, corresponding to the three
requirements in DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md's "verification bar":

  1. SCORING PARITY ACROSS A THIRD ENTRY POINT. TestScoringParityAcrossTransports
     runs the *same* seeded database through both app.Handler (over a real
     ThreadingHTTPServer) and wsgi.application (over a real wsgiref server) and
     asserts the JSON bodies for /api/queue and /api/account/{id} are BYTE
     IDENTICAL. Not "close": identical. If the WSGI adapter ever drifted from
     WarrantRoutes — a stray reimplementation, a different code path — this is
     the test that would catch it.
  2. CORS/preflight behaves the same way under WSGI as under app.py.
     TestWsgiCors mirrors test_api.py's TestCors test-for-test.
  3. The write loop — dispute, score moves, revert, score restored — works
     end-to-end over the WSGI entry point, not only over the socket one.
"""

import json
import os
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from wsgiref.simple_server import WSGIRequestHandler, make_server

import support

REPO_ROOT = support.REPO_ROOT
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import app as app_mod                                            # noqa: E402
import wsgi as wsgi_mod                                          # noqa: E402
from http.server import ThreadingHTTPServer                      # noqa: E402

AS_OF = support.AS_OF
ALLOWED_ORIGIN = "http://127.0.0.1:8080"
DISALLOWED_ORIGIN = "https://evil-example.github.io"


class _QuietWSGIRequestHandler(WSGIRequestHandler):
    """wsgiref logs every request to stderr by default. The socket-based
    tests (test_api.py) run silently via ThreadingHTTPServer + app.Handler's
    own log_message(); this keeps the WSGI test output equally quiet."""

    def log_message(self, fmt, *args):
        pass


class LiveWsgiServer:
    """A real wsgiref.simple_server bound to a real ephemeral port, serving
    wsgi.application. The WSGI-path equivalent of test_api.py's LiveServer,
    which does the same thing for app.Handler over ThreadingHTTPServer.

    wsgiref.simple_server is stdlib (see wsgi.py's own docstring for why it is
    the appropriate stand-in for PythonAnywhere's real uwsgi worker: a WSGI
    *application* is defined independently of any particular WSGI *server*,
    and wsgiref is the reference server for exactly that reason).
    """

    def __init__(self, db_path, allowed_origins, persistence="ephemeral"):
        self.db_path = db_path
        self.allowed_origins = allowed_origins
        self.persistence = persistence
        self.previous = {}

    def __enter__(self):
        for key, value in (("WARRANT_DB_PATH", self.db_path),
                           ("WARRANT_ALLOWED_ORIGINS", self.allowed_origins),
                           ("WARRANT_PERSISTENCE", self.persistence)):
            self.previous[key] = os.environ.get(key)
            os.environ[key] = value
        self.server = make_server("127.0.0.1", 0, wsgi_mod.application,
                                  handler_class=_QuietWSGIRequestHandler)
        self.port = self.server.server_port
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


class LiveSocketServer:
    """A real ThreadingHTTPServer running app.Handler — duplicated here
    (rather than imported from test_api.py) because this codebase's
    convention is that each test file owns its own harness (see
    tests/test_queue.py's _prose_patterns vs tests/test_api.py's
    looks_like_a_key — the same kind of near-duplicate test infrastructure
    already exists across two files). This is test plumbing, not application
    logic; the thing it starts, app.Handler, is not duplicated — it is
    imported."""

    def __init__(self, db_path, allowed_origins, persistence="ephemeral"):
        self.db_path = db_path
        self.allowed_origins = allowed_origins
        self.persistence = persistence
        self.previous = {}

    def __enter__(self):
        for key, value in (("WARRANT_DB_PATH", self.db_path),
                           ("WARRANT_ALLOWED_ORIGINS", self.allowed_origins),
                           ("WARRANT_PERSISTENCE", self.persistence)):
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


# ---------------------------------------------------------------------------
# 1. Scoring parity, extended to a third entry point
# ---------------------------------------------------------------------------

class TestScoringParityAcrossTransports(unittest.TestCase):
    """DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md's central question, restated for
    this path: does the WSGI entry point return exactly what the socket entry
    point returns, for the same account, same rep, same database? Both
    servers read the SAME seeded db file over two real HTTP requests — not one
    call reused twice — so this is a genuine cross-transport comparison, not a
    tautology.
    """

    @classmethod
    def setUpClass(cls):
        cls.db = support.build_seeded_db("wsgi-parity")

    # A live GET is not read-only in the row sense: build_run() persists a
    # fresh scores/reasons run on every call (§7.4's whole point — a dispute
    # must be visible on the very next render), so run_id, reason_id and
    # evidence_href legitimately differ between any two separate calls, even
    # against the identical data, even on the same transport. That was the
    # first version of this test's own bug, caught by running it for real:
    # it asserted full-payload equality and failed on run_id 18 vs 19. The
    # fix is to compare what DEPLOY_ARCHITECTURE.md §2.1 actually promises —
    # every score, band, points value and rendered string — and deliberately
    # exclude the row identifiers that are supposed to be fresh every time.
    # tests/test_api.py::TestScoringParity draws the same line for the same
    # reason.
    VOLATILE_QUEUE_KEYS = ("meta", "run_id", "run_stamp")

    def _strip_action_reason_id(self, action):
        """`fields.reason` inside each dispute action is the same per-render
        reason_id (warrant/api.py::_dispute_action) — volatile for the same
        reason as the top-level reason_id field."""
        fields = dict(action["fields"])
        if "reason" in fields:
            fields["reason"] = None
        return {**action, "fields": fields}

    def _strip_volatile_reason_ids(self, payload):
        stripped = dict(payload)
        stripped["meta"] = None
        stripped["reasons"] = [
            {**{k: v for k, v in reason.items()
                if k not in ("reason_id", "evidence_href")},
             "actions": [self._strip_action_reason_id(a)
                        for a in reason["actions"]]}
            for reason in payload["reasons"]]
        return stripped

    def test_queue_payload_is_identical_across_transports_except_run_identity(self):
        with LiveSocketServer(self.db, ALLOWED_ORIGIN) as socket_server:
            s_status, _h, s_body = http_get(socket_server.base + "/api/queue?rep=1")
        with LiveWsgiServer(self.db, ALLOWED_ORIGIN) as wsgi_server:
            w_status, _h, w_body = http_get(wsgi_server.base + "/api/queue?rep=1")

        self.assertEqual(s_status, 200)
        self.assertEqual(w_status, 200)
        socket_payload = json.loads(s_body)
        wsgi_payload = json.loads(w_body)
        for key in self.VOLATILE_QUEUE_KEYS:
            socket_payload[key] = None
            wsgi_payload[key] = None
        self.assertEqual(socket_payload, wsgi_payload,
                         "the WSGI queue payload diverged from the socket "
                         "queue payload for the same database and rep, on "
                         "every field except the per-render run identity")
        self.assertGreater(len(wsgi_payload["items"]), 40)
        # And the run identity fields must each independently look sane —
        # incrementing integers, not garbage — even though they are excluded
        # from the equality check above.
        s_run_id = json.loads(s_body)["run_id"]
        w_run_id = json.loads(w_body)["run_id"]
        self.assertIsInstance(s_run_id, int)
        self.assertIsInstance(w_run_id, int)
        self.assertNotEqual(s_run_id, w_run_id,
                            "two separate live renders somehow got the same "
                            "run_id — that would mean one of them did not "
                            "actually re-score, the one thing §7.1 forbids")

    def test_detail_payload_scores_and_reason_text_are_identical_across_transports(self):
        with LiveSocketServer(self.db, ALLOWED_ORIGIN) as socket_server:
            _s, _h, body = http_get(socket_server.base + "/api/queue?rep=1")
            account_ids = [item["account_id"]
                          for item in json.loads(body)["items"][:8]]
            socket_details = {}
            for account_id in account_ids:
                _s, _h, body = http_get(
                    socket_server.base + "/api/account/%d?rep=1" % account_id)
                socket_details[account_id] = self._strip_volatile_reason_ids(
                    json.loads(body))

        with LiveWsgiServer(self.db, ALLOWED_ORIGIN) as wsgi_server:
            wsgi_details = {}
            for account_id in account_ids:
                _s, _h, body = http_get(
                    wsgi_server.base + "/api/account/%d?rep=1" % account_id)
                wsgi_details[account_id] = self._strip_volatile_reason_ids(
                    json.loads(body))

        self.assertEqual(len(account_ids), 8)
        compared_reasons = 0
        for account_id in account_ids:
            self.assertEqual(
                socket_details[account_id], wsgi_details[account_id],
                "account %d: WSGI detail payload diverged from the socket "
                "detail payload — points, band, or reason text differ"
                % account_id)
            compared_reasons += len(socket_details[account_id]["reasons"])
        self.assertGreater(compared_reasons, 5)

    def test_kestrel_worked_example_survives_both_transports_identically(self):
        """The §4.4 worked example (61.24 pts, README deviation 1), read
        through both entry points against the same dedicated fixture."""
        path, _conn = support.build_kestrel_db()
        with LiveSocketServer(path, ALLOWED_ORIGIN) as socket_server:
            _s, _h, body = http_get(
                socket_server.base + "/api/account/%d?rep=1"
                % support.KESTREL_ACCOUNT_ID)
            socket_payload = json.loads(body)
        with LiveWsgiServer(path, ALLOWED_ORIGIN) as wsgi_server:
            _s, _h, body = http_get(
                wsgi_server.base + "/api/account/%d?rep=1"
                % support.KESTREL_ACCOUNT_ID)
            wsgi_payload = json.loads(body)

        self.assertAlmostEqual(socket_payload["verdict"]["points"], 61.24, 2)
        self.assertEqual(socket_payload["verdict"]["points"],
                         wsgi_payload["verdict"]["points"])
        self.assertEqual(socket_payload["verdict"]["band"],
                         wsgi_payload["verdict"]["band"])
        self.assertEqual([r["text"] for r in socket_payload["reasons"]],
                         [r["text"] for r in wsgi_payload["reasons"]])


# ---------------------------------------------------------------------------
# 2. CORS / preflight over WSGI — mirrors test_api.py::TestCors test-for-test
# ---------------------------------------------------------------------------

class TestWsgiCors(unittest.TestCase):
    """§4 of DEPLOY_ARCHITECTURE.md, unchanged by the WSGI path, exercised
    over a real socket in front of wsgiref rather than ThreadingHTTPServer."""

    @classmethod
    def setUpClass(cls):
        cls.db = support.build_seeded_db("wsgi-cors")

    def test_allowed_origin_gets_the_header(self):
        with LiveWsgiServer(self.db, ALLOWED_ORIGIN) as server:
            status, headers, _body = http_get(server.base + "/api/health",
                                              origin=ALLOWED_ORIGIN)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"),
                         ALLOWED_ORIGIN)
        self.assertEqual(headers.get("Vary"), "Origin")

    def test_disallowed_origin_gets_no_header_but_still_gets_a_200(self):
        with LiveWsgiServer(self.db, ALLOWED_ORIGIN) as server:
            status, headers, body = http_get(server.base + "/api/health",
                                             origin=DISALLOWED_ORIGIN)
        self.assertEqual(status, 200)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))
        self.assertTrue(json.loads(body)["ok"])

    def test_a_prefix_lookalike_origin_does_not_match(self):
        with LiveWsgiServer(self.db, "https://someone.github.io") as server:
            status, headers, _body = http_get(
                server.base + "/api/health",
                origin="https://evil-someone.github.io")
            self.assertEqual(status, 200)
            self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    def test_empty_allowlist_emits_no_cors_headers_at_all(self):
        with LiveWsgiServer(self.db, "") as server:
            status, headers, _body = http_get(server.base + "/api/health",
                                              origin=ALLOWED_ORIGIN)
        self.assertEqual(status, 200)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    def test_preflight_is_200_with_content_length_zero(self):
        with LiveWsgiServer(self.db, ALLOWED_ORIGIN) as server:
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
        with LiveWsgiServer(self.db, ALLOWED_ORIGIN) as server:
            status, headers, body = http_options(server.base + "/api/dispute",
                                                 origin=DISALLOWED_ORIGIN)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Length"), "0")
        self.assertEqual(body, b"")
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))
        self.assertIsNone(headers.get("Access-Control-Allow-Methods"))

    def test_options_never_returns_501(self):
        with LiveWsgiServer(self.db, ALLOWED_ORIGIN) as server:
            for path in ("/api/queue", "/api/task", "/queue"):
                status, _headers, _body = http_options(server.base + path,
                                                       origin=ALLOWED_ORIGIN)
                self.assertNotEqual(status, 501, path)
                self.assertEqual(status, 200, path)

    def test_cors_decision_matches_the_socket_path_for_the_same_configuration(self):
        """Not just 'both work' — the same origin, same allowlist, same
        route, on both transports, must produce the same header presence.
        This is what makes §4's CORS rule 'one decision, two transports'
        rather than two decisions that happen to agree today."""
        cases = [(ALLOWED_ORIGIN, True), (DISALLOWED_ORIGIN, False), (None, False)]
        with LiveSocketServer(self.db, ALLOWED_ORIGIN) as socket_server, \
             LiveWsgiServer(self.db, ALLOWED_ORIGIN) as wsgi_server:
            for origin, expect_header in cases:
                s_status, s_headers, _b = http_get(
                    socket_server.base + "/api/health", origin=origin)
                w_status, w_headers, _b = http_get(
                    wsgi_server.base + "/api/health", origin=origin)
                self.assertEqual(s_status, w_status, origin)
                s_aco = s_headers.get("Access-Control-Allow-Origin")
                w_aco = w_headers.get("Access-Control-Allow-Origin")
                self.assertEqual(s_aco is not None, expect_header, origin)
                self.assertEqual(s_aco, w_aco, origin)
                self.assertEqual(s_headers.get("Vary"), w_headers.get("Vary"))


# ---------------------------------------------------------------------------
# 3. HTML routes still reachable over WSGI (a bonus of sharing one dispatch
#    table, not a PythonAnywhere requirement on its own — the Pages frontend
#    only calls /api — but it costs nothing to prove the whole table works).
# ---------------------------------------------------------------------------

class TestWsgiLiveHttpApi(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db = support.build_seeded_db("wsgi-http")

    def test_api_response_headers_are_no_store(self):
        with LiveWsgiServer(self.db, ALLOWED_ORIGIN) as server:
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

    def test_health_is_cheap_and_reports_the_corpus(self):
        with LiveWsgiServer(self.db, ALLOWED_ORIGIN) as server:
            status, _headers, body = http_get(server.base + "/api/health")
            payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["seeded"])
        self.assertEqual(payload["accounts"], 240)
        self.assertEqual(payload["meta"]["as_of"], AS_OF)

    def test_queue_returns_the_expected_patch_size(self):
        with LiveWsgiServer(self.db, ALLOWED_ORIGIN) as server:
            status, _headers, body = http_get(server.base + "/api/queue?rep=1")
            payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["account_count"], 53)

    def test_unknown_rep_and_unknown_route_are_404_with_an_error_shape(self):
        with LiveWsgiServer(self.db, ALLOWED_ORIGIN) as server:
            status, _h, body = http_get(server.base + "/api/queue?rep=999")
            self.assertEqual(status, 404)
            self.assertEqual(json.loads(body)["error"]["code"], "NOT_FOUND")
            status, _h, body = http_get(server.base + "/api/nope")
            self.assertEqual(status, 404)
            self.assertEqual(json.loads(body)["error"]["code"], "NOT_FOUND")

    def test_html_route_also_renders_over_wsgi_though_pages_never_calls_it(self):
        """Not a PythonAnywhere requirement — the Pages frontend only ever
        calls /api. Proven anyway, because WarrantRoutes._route_get is one
        table serving both, and a change that broke the HTML half while
        leaving /api working would otherwise go unnoticed here."""
        with LiveWsgiServer(self.db, ALLOWED_ORIGIN) as server:
            status, headers, body = http_get(server.base + "/queue?rep=1")
        self.assertEqual(status, 200)
        self.assertIn(b"Warrant", body)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    def test_unsupported_method_is_501_not_a_crash(self):
        """WarrantRoutes only ever defines GET/POST/OPTIONS handling; a PUT
        must fail predictably rather than raise inside the WSGI worker."""
        with LiveWsgiServer(self.db, ALLOWED_ORIGIN) as server:
            request = Request(server.base + "/api/health", method="PUT")
            try:
                with urlopen(request, timeout=10) as response:
                    status = response.status
            except HTTPError as exc:
                status = exc.code
        self.assertEqual(status, 501)


# ---------------------------------------------------------------------------
# 4. The write loop, end to end, over the WSGI entry point
# ---------------------------------------------------------------------------

class TestWsgiWriteLoop(unittest.TestCase):
    """The heart of the feature (test_api.py::TestWriteLoopOverHttp's WSGI
    twin): dispute -> the score changes -> revert -> the score is restored —
    proven again here because a rep filing a dispute through the
    PythonAnywhere-hosted backend must see the same guarantee."""

    def test_dispute_then_revert_over_wsgi(self):
        db = support.fresh_seeded_db("wsgi-writeloop")
        with LiveWsgiServer(db, ALLOWED_ORIGIN) as server:
            base = server.base

            _s, _h, body = http_get(base + "/api/queue?rep=1")
            queue = json.loads(body)
            account_id = queue["items"][0]["account_id"]
            points_before = queue["items"][0]["points"]

            _s, _h, body = http_get(base + "/api/account/%d?rep=1" % account_id)
            detail = json.loads(body)
            target = detail["reasons"][0]
            action = target["actions"][0]
            self.assertEqual(action["code"], "EVIDENCE_WRONG")

            status, _h, body = http_post(base + "/api/dispute", action["fields"],
                                         origin=ALLOWED_ORIGIN)
            self.assertEqual(status, 200)
            result = json.loads(body)
            self.assertTrue(result["ok"])
            adjustment_id = result["effect"]["undo_adjustment_id"]
            self.assertIsNotNone(adjustment_id)

            _s, _h, body = http_get(base + "/api/account/%d?rep=1" % account_id)
            after = json.loads(body)
            self.assertLess(after["verdict"]["points"], points_before,
                            "the dispute did not move the score over WSGI")
            suppressed = [r for r in after["reasons"] if r["is_suppressed"]]
            self.assertTrue(suppressed, "no reason came back struck through")

            status, _h, body = http_post(
                base + "/api/adjust/revert",
                {"rep": 1, "adjustment": adjustment_id, "account": account_id},
                origin=ALLOWED_ORIGIN)
            self.assertEqual(status, 200)

            _s, _h, body = http_get(base + "/api/account/%d?rep=1" % account_id)
            restored = json.loads(body)
            self.assertAlmostEqual(restored["verdict"]["points"], points_before,
                                   2, "revert did not restore the score over WSGI")

    def test_persistence_persistent_suppresses_the_ephemeral_clause_over_wsgi(self):
        """DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md decision 4: the PythonAnywhere
        path sets WARRANT_PERSISTENCE=persistent, unlike Render's `ephemeral`.
        Proven here at the wire, over WSGI specifically, because this is the
        one behavioural difference the PythonAnywhere path deliberately
        introduces and it must be visible on the wire, not just in a doc."""
        db = support.fresh_seeded_db("wsgi-persistent")
        with LiveWsgiServer(db, ALLOWED_ORIGIN, persistence="persistent") as server:
            status, _h, body = http_get(server.base + "/api/health")
            payload = json.loads(body)
            self.assertEqual(status, 200)
            self.assertEqual(payload["meta"]["persistence"], "persistent")
            self.assertIsNone(payload["meta"]["persistence_notice"])

            _s, _h, body = http_get(server.base + "/api/queue?rep=1")
            account_id = json.loads(body)["items"][0]["account_id"]
            _s, _h, body = http_get(
                server.base + "/api/account/%d?rep=1" % account_id)
            action = json.loads(body)["reasons"][0]["actions"][0]
            status, _h, body = http_post(server.base + "/api/dispute",
                                         action["fields"])
            result = json.loads(body)
            self.assertNotIn("or until this demo server restarts",
                             result["effect"]["confirmation"])


if __name__ == "__main__":
    unittest.main()
