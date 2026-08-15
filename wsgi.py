"""WSGI entry point, added for the PythonAnywhere path.
DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md.

WHY THIS FILE EXISTS. Render runs `python start.py`, which calls
`app.main()`, which binds a real `ThreadingHTTPServer` to a socket and calls
`serve_forever()`. PythonAnywhere's free tier does not run a process like
that at all — its web workers only ever call a WSGI application, a callable
of the shape `application(environ, start_response)`, through PythonAnywhere's
own nginx/uwsgi stack. `app.py`'s `Handler` is a
`http.server.BaseHTTPRequestHandler`; that is not WSGI, and PythonAnywhere's
worker cannot call it.

WHAT THIS FILE DOES NOT DO. It does not reimplement a single route. Every
method this module calls — `_index`, `_queue`, `_detail`, `_api_dispute`,
all of them — is `app.WarrantRoutes`, the exact mixin class `app.py`'s
socket-based `Handler` is built from (see `app.py`'s module docstring, "THE
SPLIT ADDED FOR PYTHONANYWHERE"). That mixin has no socket dependency; it
only calls `self._send()`, `self._send_json()`, `self._redirect()` and
`self._json_error()`, which this module supplies in WSGI-shaped form instead
of socket-shaped form. Scoring, reason text, dispute effects, budget
enforcement — none of it is touched, imported differently, or duplicated.
This file is exactly the WSGI protocol plumbing and nothing else.

CORS is the other place a second implementation could quietly drift from the
first. It does not, because the CORS *decision* — which headers, on which
Origin, in the §4.4/§4.6 order — is `app.cors_header_lines()` and
`app.preflight_header_lines()`, two plain functions `app.py`'s `Handler`
already calls. This module calls the same two functions. A preflight
answered by this file and a preflight answered by `app.py`'s `Handler` are
the same decision, computed once, not two decisions that happen to agree
today.

Stdlib only — `tests/test_queue.py::TestT19StandardLibraryOnly` walks this
file's imports and fails on anything that is not. `wsgiref.simple_server`
(stdlib) is used by `tests/test_wsgi.py` to run this module as a real WSGI
server for testing; nothing in this file imports `wsgiref` itself, because a
WSGI *application* does not need a WSGI *server* to define itself — that is
the whole point of the WSGI interface, and it is what lets PythonAnywhere's
own server call this same `application` object without this file knowing
anything about uwsgi.

WHAT SETS THE ENVIRONMENT VARIABLES THIS MODULE READS (indirectly, through
`WarrantRoutes` and `warrant/db.py`). Nothing in this file does. On
PythonAnywhere, the *actual* per-webapp WSGI configuration file — a separate
file PythonAnywhere generates and the user edits via the Web tab, outside
this repository entirely — sets them with plain `os.environ.setdefault(...)`
calls before importing `wsgi.application` from here, then optionally runs
`start.seed_if_needed()` first so the persistent disk is seeded exactly once.
See DEPLOY_RUNBOOK_PYTHONANYWHERE.md for the literal code to paste there.
"""

import sys
from http import HTTPStatus
from urllib.parse import parse_qs

from app import (WarrantRoutes, cors_header_lines, preflight_header_lines,
                 _int)
from warrant.db import connect

BANNER = ("warrant-wsgi build-marker 2026-08-15 · WSGI adapter over the same "
         "WarrantRoutes app.py's Handler uses · DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md")

# Printed once, when a WSGI worker process imports this module — the WSGI
# equivalent of app.py's boot-time BANNER/DEPLOY_MARKER prints. PythonAnywhere
# routes stderr to the web app's error log, which is where this line will
# show up after a reload; see DEPLOY_RUNBOOK_PYTHONANYWHERE.md's "verify
# before moving on" step for this exact string. Learned the hard way,
# elsewhere in this project: a deploy that "succeeded" is not the same as a
# deploy that shipped, and the only way to prove new code is actually running
# is a marker that could not have printed under the old code.
sys.stderr.write(BANNER + "\n")
sys.stderr.flush()


class WSGIRequest(WarrantRoutes):
    """One instance per request. Supplies WarrantRoutes' four required
    transport methods in WSGI shape: instead of writing to a socket, each one
    records (status, headers, body) on `self` for `application()` to hand to
    `start_response()` once dispatch has finished.

    This mirrors app.py's Handler exactly in spirit — same four methods, same
    meaning — and deliberately does not try to *be* a Handler (no shared base
    class with it) because BaseHTTPRequestHandler's constructor expects a
    live socket, which a WSGI worker never has.
    """

    def __init__(self, environ):
        self.environ = environ
        self.status = 200
        self.response_headers = []
        self.body = b""

    # -- the four methods WarrantRoutes depends on --------------------------
    def _send(self, status, html, content_type="text/html; charset=utf-8"):
        payload = html.encode("utf-8")
        self.status = status
        self.response_headers = [("Content-Type", content_type),
                                 ("Content-Length", str(len(payload)))]
        self.body = payload

    def _redirect(self, location):
        self.status = 303
        self.response_headers = [("Location", location),
                                 ("Content-Length", "0")]
        self.body = b""

    def _send_json(self, status, payload):
        import json
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = [("Content-Type", "application/json; charset=utf-8"),
                  ("Content-Length", str(len(body))),
                  # §7.2 item 4, unchanged from app.py: no-store, no ETag, no
                  # Last-Modified. Every /api response is live-scored.
                  ("Cache-Control", "no-store")]
        headers += cors_header_lines(self.environ.get("HTTP_ORIGIN"))
        self.status = status
        self.response_headers = headers
        self.body = body

    def _json_error(self, status, payload):
        self._send_json(status, payload)

    # -- WSGI-specific plumbing ----------------------------------------------
    def _form(self):
        """The WSGI-shaped twin of app.py's Handler._form(): same
        Content-Length + parse_qs(keep_blank_values=True) logic, reading
        environ['wsgi.input'] instead of a socket's rfile. CONTENT_LENGTH is a
        bare WSGI environ key, not an HTTP_-prefixed one (PEP 3333)."""
        length = _int(self.environ.get("CONTENT_LENGTH"), 0)
        raw = (self.environ["wsgi.input"].read(length).decode("utf-8")
               if length else "")
        return parse_qs(raw, keep_blank_values=True)

    def _do_options(self):
        """§4.4, over WSGI. Same header list as app.py's do_OPTIONS — see
        preflight_header_lines()'s docstring in app.py for the three
        decisions this response embodies (200 not 204, Max-Age caches a
        permission not a score, a disallowed Origin still gets 200)."""
        self.status = 200
        self.response_headers = preflight_header_lines(
            self.environ.get("HTTP_ORIGIN"))
        self.body = b""

    def dispatch(self):
        """The WSGI-shaped twin of app.py's Handler.do_GET / do_POST: parse
        the incoming request into (conn, path, parts/params/form), then hand
        off to WarrantRoutes._route_get / _route_post — the one dispatch
        table, unchanged, imported from app.py rather than redefined here.
        """
        method = self.environ.get("REQUEST_METHOD", "GET")
        path = self.environ.get("PATH_INFO", "/") or "/"
        query = self.environ.get("QUERY_STRING", "")

        if method == "OPTIONS":
            return self._do_options()

        conn = connect()
        try:
            if method == "GET":
                parts = [p for p in path.split("/") if p]
                params = parse_qs(query)
                return self._route_get(conn, path, parts, params)
            if method == "POST":
                form = self._form()
                return self._route_post(conn, path, form)
            # Any other verb: app.py's Handler falls through to
            # BaseHTTPRequestHandler's default 501 for a method with no
            # do_<VERB>. Warrant only ever defines GET, POST and OPTIONS, so
            # matching that outcome here (rather than inventing a different
            # one) is the whole of what this branch needs to do.
            self.status = 501
            self.response_headers = [("Content-Length", "0")]
            self.body = b""
        finally:
            conn.close()


def application(environ, start_response):
    """The WSGI callable itself. PythonAnywhere's per-webapp WSGI
    configuration file does `from wsgi import application` after setting the
    WARRANT_* environment variables (DEPLOY_RUNBOOK_PYTHONANYWHERE.md); the
    test harness (`tests/test_wsgi.py`) hands this same object to
    `wsgiref.simple_server.make_server` and drives it with real HTTP requests
    over a real socket, exactly as `tests/test_api.py` does for `app.Handler`.
    """
    request = WSGIRequest(environ)
    request.dispatch()
    status_line = "%d %s" % (request.status, HTTPStatus(request.status).phrase)
    start_response(status_line, request.response_headers)
    return [request.body]
