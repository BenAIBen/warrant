/* docs/app.js — router, fetch, DOM construction. Nothing else.
 *
 * DEPLOY_ARCHITECTURE.md §2.1, the rule this file exists to obey:
 *
 *     The backend returns fully-rendered reason text, per-reason point values,
 *     the applied truncation and the limits line as JSON fields. The browser
 *     does layout and interaction ONLY — zero arithmetic, zero ranking, zero
 *     truncation, zero template substitution.
 *
 * So: no scoring is reimplemented here. §2.3 names the forbidden functions and
 * none of them exist in this file — no applyCap, no decayFactor, no bandFrom,
 * no rankReasons, no selectShown, no buildLimitsLine, no pointsLabel, no
 * truncateAtWord, no freshnessChip. §5.4 rule 2 names the forbidden idioms and
 * none of them appear either: no Math.round, no toFixed, no "+" + n, no
 * n + " pts" on a value, no "rank " + a + " of " + b, no .slice(0, 120), no
 * .sort() over reasons or items, no .filter(r => r.shown), no
 * if (points >= 45). If one of those is ever needed here, the payload is
 * missing a field and the fix belongs in warrant/api.py, not in this file.
 *
 * Every VALUE on screen is a string the server rendered. The only text this
 * file owns is fixed chrome: the literal word "pts" after a points_display,
 * section headings, button labels for navigation, and the loading / offline /
 * CORS / not-configured panels in §9 — which have to live here because they are
 * shown precisely when the server cannot be reached.
 *
 * Caching: none (§7.2 item 5). There is no Map of payloads, no sessionStorage,
 * no localStorage, no {cache:"force-cache"}, and no service worker. Every hash
 * navigation issues a fresh request, including going back to the queue from a
 * detail view. That is intended: it is what makes a dispute visible on the very
 * next render.
 *
 * Rendering: textContent everywhere, never innerHTML. JSON does not escape and
 * account names and rep notes come from data.
 */

"use strict";

/* --- tunables, named, in one place (§10.3 open question 3) --------------- */

var WAKE_SWAP_MS = 1500;      // under this, the container was already awake
var WAKE_POLL_MS = 3000;      // §9.1 step 4
var WAKE_TIMEOUT_MS = 90000;  // §9.1 step 4; a margin over Render's "about one
                              // minute". If real cold starts run longer under
                              // load, this is the number that moves.
var PLACEHOLDER_MARK = "<your-app>";

/* --- config: read once, in exactly one place (§5.2) ---------------------- */

var CONFIG = window.WARRANT_CONFIG || {};
var API_BASE = typeof CONFIG.apiBase === "string" ? CONFIG.apiBase.trim() : "";

function apiBaseIsUnset() {
  // The single most likely user error is not editing config.js at all, so the
  // unedited placeholder is detected explicitly and cheaply.
  return !API_BASE || API_BASE.indexOf(PLACEHOLDER_MARK) !== -1;
}

/* --- tiny DOM helpers --------------------------------------------------- */

function el(tag, className, text) {
  var node = document.createElement(tag);
  if (className) { node.className = className; }
  if (text !== undefined && text !== null) { node.textContent = text; }
  return node;
}

function link(href, text, className) {
  var a = el("a", className, text);
  a.href = href;
  return a;
}

function clear(node) {
  while (node.firstChild) { node.removeChild(node.firstChild); }
}

function view() { return document.getElementById("view"); }

function paint(nodes) {
  var target = view();
  clear(target);
  for (var i = 0; i < nodes.length; i++) {
    if (nodes[i]) { target.appendChild(nodes[i]); }
  }
  window.scrollTo(0, 0);
}

function panel(titleText, paragraphs, buttons, className) {
  var box = el("div", className || "state");
  box.appendChild(el("h2", null, titleText));
  for (var i = 0; i < paragraphs.length; i++) {
    if (paragraphs[i] === null || paragraphs[i] === undefined) { continue; }
    box.appendChild(el("p", null, paragraphs[i]));
  }
  if (buttons && buttons.length) {
    var row = el("p", "actions");
    for (var j = 0; j < buttons.length; j++) {
      row.appendChild(buttons[j]);
      row.appendChild(document.createTextNode(" "));
    }
    box.appendChild(row);
  }
  return box;
}

function codeLine(labelText, valueText) {
  var p = el("p", null, labelText + " ");
  p.appendChild(el("code", null, valueText));
  return p;
}

function button(labelText, onClick, className) {
  var b = el("button", className, labelText);
  b.type = "button";
  b.addEventListener("click", onClick);
  return b;
}

function navButton(labelText, hash) {
  return button(labelText, function () { window.location.hash = hash; });
}

/* --- persistent chrome: the notice on every view (§6.5 requirement 1) ---- */

var LAST_BOOT_ID = null;
var RESTART_SEEN = false;

function applyMeta(meta) {
  var notice = document.getElementById("persistence-notice");
  if (meta && meta.persistence_notice) {
    notice.textContent = meta.persistence_notice;   // server copy, verbatim
    notice.hidden = false;
  } else {
    notice.textContent = "";
    notice.hidden = true;
  }
  document.getElementById("nav").hidden = false;

  var footer = document.getElementById("footer-note");
  if (meta) {
    footer.textContent = meta.as_of_display + " · ruleset " +
      meta.ruleset_version + " · server started " + meta.started_at_display;
  }

  // §6.5 requirement 3: a changed boot_id means the container restarted and
  // everything the rep filed this session is gone. Say so, once.
  RESTART_SEEN = false;
  if (meta && meta.boot_id) {
    if (LAST_BOOT_ID !== null && LAST_BOOT_ID !== meta.boot_id) {
      RESTART_SEEN = true;
    }
    LAST_BOOT_ID = meta.boot_id;
  }
}

function restartBanner(meta) {
  if (!RESTART_SEEN || !meta || !meta.restart_notice) { return null; }
  var box = el("div", "banner warn");
  box.appendChild(el("strong", null, meta.restart_notice_title));
  box.appendChild(el("p", null, meta.restart_notice));
  return box;
}

/* --- fetch ---------------------------------------------------------------
 * Returns {kind: "ok"|"http"|"unreachable", status, body}.
 * "unreachable" covers both a dead server and a CORS block — at the JS level
 * they are the same TypeError and must not be guessed between (§9.3).
 */

function request(path, options) {
  var url = API_BASE + path;
  var opts = options || {};
  opts.cache = "no-store";
  return fetch(url, opts).then(function (response) {
    return response.json().then(function (body) {
      return { kind: response.ok ? "ok" : "http", status: response.status,
               body: body };
    }, function () {
      return { kind: "http", status: response.status, body: null };
    });
  }, function () {
    return { kind: "unreachable", status: 0, body: null };
  });
}

function get(path) { return request(path, { method: "GET" }); }

function post(path, fields) {
  // §4.5: URLSearchParams sets Content-Type application/x-www-form-urlencoded
  // automatically, which is a CORS-simple request and sends NO preflight. Do
  // not set Content-Type by hand and do not send JSON.stringify — that would
  // add an OPTIONS round trip to every dispute, on a container that may be
  // waking. The field names are the server's, unchanged, so app.py::_form()
  // parses the HTML form path and this path with one piece of code.
  var body = new URLSearchParams();
  for (var key in fields) {
    if (Object.prototype.hasOwnProperty.call(fields, key) &&
        fields[key] !== null && fields[key] !== undefined) {
      body.append(key, fields[key]);
    }
  }
  return request(path, { method: "POST", body: body });
}

/* §9.3 disambiguation. A CORS block and an unreachable server are the same
 * TypeError. A no-cors request returns an opaque response and does not throw if
 * the server is reachable; it throws if it is not. Reachable + opaque success +
 * the real request threw => almost certainly CORS. This is a heuristic, not a
 * proof, and the copy it selects does not overclaim. */
function probeReachable() {
  return fetch(API_BASE + "/api/health", { mode: "no-cors", cache: "no-store" })
    .then(function () { return true; }, function () { return false; });
}

/* --- §9.1 cold start / wake --------------------------------------------- */

var wakeTimer = null;

function stopWake() {
  if (wakeTimer !== null) { window.clearTimeout(wakeTimer); wakeTimer = null; }
}

function loadingPanel() {
  return panel("Warrant — reason-first prioritisation.", ["Loading…"], null);
}

function wakingPanel(elapsedSeconds) {
  var box = el("div", "state");
  box.appendChild(el("h2", null, "Warrant — reason-first prioritisation."));
  box.appendChild(el("p", null,
    "Waking the demo server. On free hosting this takes about a minute."));
  box.appendChild(el("p", null,
    "Warrant runs live SQL over a real database at the moment you load a page " +
    "— there is no cache and no precomputed score. The server sleeps after 15 " +
    "minutes of no traffic, so the first visit pays for starting it up. " +
    "Nothing is wrong."));
  // The counter is a browser clock, not a value from the model. It is the one
  // number this file computes and §9.1 specifies it explicitly.
  box.appendChild(el("p", "waiting", "Waiting " + elapsedSeconds + "s…"));
  return box;
}

/* Waits for /api/health, then runs `then(health)`. Falls through to §9.2. */
function wakeThen(then) {
  stopWake();
  var startedAt = Date.now();
  var swapped = false;
  paint([loadingPanel()]);

  function attempt() {
    get("/api/health").then(function (result) {
      var elapsed = Date.now() - startedAt;

      if (result.kind === "ok" && result.body) {
        stopWake();
        applyMeta(result.body.meta);
        if (result.body.seeded === false) {
          paint([notSeededPanel()]);
          return;
        }
        then(result.body);
        return;
      }

      if (result.kind === "http") {
        // The server answered with a status. It is up; something else is wrong.
        stopWake();
        paint([httpErrorPanel(result)]);
        return;
      }

      if (elapsed >= WAKE_TIMEOUT_MS) {
        stopWake();
        showUnreachable();
        return;
      }

      if (!swapped && elapsed >= WAKE_SWAP_MS) { swapped = true; }
      if (swapped) {
        paint([wakingPanel(Math.floor(elapsed / 1000))]);
      }
      wakeTimer = window.setTimeout(attempt, WAKE_POLL_MS);
    });
  }
  attempt();
}

/* --- §9.2 / §9.3 / §9.5 / §9.6 failure states --------------------------- */

function retryButton() {
  return button("Try again", function () { route(); });
}

function notConfiguredPanel() {
  var box = el("div", "state");
  box.appendChild(el("h2", null,
    "Warrant is deployed here, but not connected to a backend yet."));
  box.appendChild(el("p", null,
    "GitHub Pages is serving this page correctly. It has no backend URL to " +
    "talk to."));
  // DEVIATION, flagged in DEPLOY_TEST_OUTPUT.md. §9.5's literal copy names the
  // host vendor in its example URL, and §5.2 requires that grepping this file
  // for that vendor name returns ZERO hits — the mechanical proof that the
  // backend URL is never hardcoded here. The two rules contradict each other.
  // §5.2's rule is the checkable one and it is what guarantees the property,
  // so the example host below is written generically. Four words of §9.5's
  // copy changed; the instruction it gives is unchanged.
  box.appendChild(el("p", null,
    "To finish setup: deploy the backend, then edit docs/config.js in this " +
    "repository and replace the placeholder with your backend's URL. It looks " +
    "like https://something.your-host.com — no trailing slash. Commit the " +
    "change and this page will pick it up within a minute."));
  box.appendChild(el("p", null,
    "Nothing here is a secret. config.js holds one public URL and no keys."));
  box.appendChild(codeLine("Current value in docs/config.js:",
                           API_BASE || "(empty)"));
  return box;
}

function unreachablePanel() {
  var box = el("div", "state");
  box.appendChild(el("h2", null, "The demo server did not answer."));
  box.appendChild(el("p", null,
    "Warrant's frontend is hosted on GitHub Pages and loaded fine — this page " +
    "is proof of that. The backend, which holds the database and does all the " +
    "scoring, is not responding."));
  box.appendChild(el("p", null,
    "The most likely causes, in order: the free-tier server is still starting " +
    "(it can take longer than a minute under load); the free monthly " +
    "instance-hour allowance has run out and the service is suspended until " +
    "next month; or the backend has been shut down."));
  // Echoed because the single most common failure is that it is wrong, and
  // showing it lets the reader diagnose without opening devtools. It is public.
  box.appendChild(codeLine("Backend configured in docs/config.js:", API_BASE));
  var row = el("p", "actions");
  row.appendChild(retryButton());
  box.appendChild(row);
  return box;
}

function corsPanel() {
  var origin = window.location.origin;
  var box = el("div", "state");
  box.appendChild(el("h2", null,
    "The server answered, but the browser blocked the response."));
  box.appendChild(el("p", null,
    "This is almost always a CORS configuration problem, and it is fixable in " +
    "about a minute."));
  box.appendChild(el("p", null,
    "The backend has to be told which website is allowed to talk to it. Set " +
    "the environment variable WARRANT_ALLOWED_ORIGINS on your backend host to " +
    "exactly:"));
  var value = el("p");
  value.appendChild(el("code", null, origin));
  box.appendChild(value);
  box.appendChild(el("p", null,
    "Origin only — no path, no repo name, no trailing slash. Then restart the " +
    "service."));
  // The highest-value line in this file: it removes the guesswork about what
  // exactly to paste, and it catches the most likely mistake — pasting the full
  // page URL including /<repo>/.
  var mine = el("p", null, "This page's origin is: ");
  mine.appendChild(el("code", null, origin));
  mine.appendChild(el("span", "meta", "  (read from the browser, not hardcoded)"));
  box.appendChild(mine);
  var row = el("p", "actions");
  row.appendChild(retryButton());
  box.appendChild(row);
  return box;
}

function notSeededPanel() {
  var box = el("div", "state");
  box.appendChild(el("h2", null, "The backend is running but has no data."));
  box.appendChild(el("p", null,
    "The server started, but the database was not created. The most likely " +
    "cause is that WARRANT_DB_PATH points somewhere the process cannot write " +
    "— check the deploy logs for the seeding summary; it should list 240 " +
    "accounts and roughly 6,900 signal events."));
  var row = el("p", "actions");
  row.appendChild(retryButton());
  box.appendChild(row);
  return box;
}

function showUnreachable() {
  // Do not say "the server is down". It might be waking, suspended, or
  // misconfigured, and asserting the wrong one teaches the reader that the
  // system's statements about itself are unreliable — on a page whose subject
  // is exactly that.
  paint([loadingPanel()]);
  probeReachable().then(function (reachable) {
    paint([reachable ? corsPanel() : unreachablePanel()]);
  });
}

function httpErrorPanel(result) {
  var error = result.body && result.body.error ? result.body.error : null;
  if (!error) {
    return panel("The server answered with an error.",
                 ["HTTP status " + result.status + ", and no error body this " +
                  "page can read."], [retryButton()]);
  }
  var buttons = [];
  if (error.code === "NOT_IN_QUEUE") {
    // §9.7. The server's own title and message are the copy; these two links
    // are navigation, which belongs to the frontend.
    buttons.push(navButton("back to your queue", "#/queue?rep=" + currentRep()));
    buttons.push(navButton("view your adjustments",
                           "#/adjustments?rep=" + currentRep()));
  } else if (error.action && error.action.href) {
    buttons.push(navButton(error.action.label,
                           hashForApiHref(error.action.href)));
  }
  return panel(error.title, [error.message], buttons);
}

/* --- routing (§5.3) ------------------------------------------------------
 * Hash-based, because GitHub Pages has no SPA rewrite and a path-based deep
 * link would 404 on refresh. hashchange drives it; back, forward and a pasted
 * deep link all work.
 */

var CURRENT = { path: "", params: {} };

function parseHash() {
  var raw = window.location.hash.replace(/^#/, "");
  if (!raw) { raw = "/"; }
  var split = raw.split("?");
  var params = {};
  if (split[1]) {
    var search = new URLSearchParams(split[1]);
    search.forEach(function (value, key) { params[key] = value; });
  }
  return { path: split[0], params: params };
}

function currentRep() {
  return CURRENT.params.rep || "1";
}

function hashForApiHref(apiHref) {
  // Server hrefs are /api/... ; the frontend's routes are #/... . One rewrite,
  // in one place, so no view has to know about it.
  return "#" + apiHref.replace(/^\/api/, "");
}

function route() {
  stopWake();
  CURRENT = parseHash();

  if (apiBaseIsUnset()) {
    // §9.5: no network request is made at all.
    document.getElementById("nav").hidden = true;
    paint([notConfiguredPanel()]);
    return;
  }

  var path = CURRENT.path;
  var rep = currentRep();

  if (path === "/" || path === "") {
    wakeThen(function () { load("/api/reps", renderIndex); });
  } else if (path === "/queue") {
    wakeThen(function () { load("/api/queue?rep=" + rep, renderQueue); });
  } else if (path.indexOf("/account/") === 0) {
    var accountId = path.substring("/account/".length);
    wakeThen(function () {
      load("/api/account/" + accountId + "?rep=" + rep, renderDetail);
    });
  } else if (path.indexOf("/evidence/observations/") === 0) {
    var researchId = path.substring("/evidence/observations/".length);
    wakeThen(function () {
      load("/api/evidence/observations/" + researchId + "?rep=" + rep,
           renderResearch);
    });
  } else if (path.indexOf("/research/") === 0) {
    var obsId = path.substring("/research/".length);
    wakeThen(function () {
      load("/api/evidence/observations/" + obsId + "?rep=" + rep, renderResearch);
    });
  } else if (path.indexOf("/evidence/") === 0) {
    var reasonId = path.substring("/evidence/".length);
    wakeThen(function () {
      load("/api/evidence/" + reasonId + "?rep=" + rep, renderEvidence);
    });
  } else if (path === "/adjustments") {
    wakeThen(function () {
      load("/api/adjustments?rep=" + rep, renderAdjustments);
    });
  } else if (path === "/metrics") {
    wakeThen(function () { load("/api/metrics", renderMetrics); });
  } else if (path === "/ruleset") {
    wakeThen(function () { load("/api/ruleset", renderRuleset); });
  } else {
    paint([panel("No such page.",
                 ["This frontend has no route for " + path + "."],
                 [navButton("back to your queue", "#/queue?rep=" + rep)])]);
  }
}

/* Every hash navigation issues a fresh request. Going back to the queue from a
 * detail view re-fetches the queue. That is correct and intended: it is what
 * makes a dispute visible on the very next render (§7.2). */
function load(path, renderer) {
  get(path).then(function (result) {
    if (result.kind === "unreachable") { showUnreachable(); return; }
    if (result.kind === "http") { paint([httpErrorPanel(result)]); return; }
    applyMeta(result.body.meta);
    renderer(result.body);
  });
}

/* --- write loop (§5.5) ---------------------------------------------------
 * Every action button submits its `fields` object verbatim. On 200 the
 * confirmation is shown and the hash route named by `next.view` is loaded,
 * which re-fetches and re-renders — so the rep sees the reason struck through,
 * the points drop and the band change on the very next render.
 *
 * On 409 it shows error.title and error.message and, if present, error.action.
 * It never disables a control on its own initiative: the server decides via
 * work_it_enabled, unavailable_note and the 409s.
 */

var PENDING_CONFIRMATION = null;

function submit(path, fields) {
  post(path, fields).then(function (result) {
    if (result.kind === "unreachable") { showUnreachable(); return; }
    if (result.kind === "http") { paint([httpErrorPanel(result)]); return; }
    var body = result.body;
    PENDING_CONFIRMATION = (body.effect && body.effect.confirmation)
      ? body.effect.confirmation : null;
    var target = hashForApiHref(body.next.href);
    if (window.location.hash === target) { route(); }
    else { window.location.hash = target; }
  });
}

function confirmationBanner() {
  if (!PENDING_CONFIRMATION) { return null; }
  var box = el("div", "confirm", PENDING_CONFIRMATION);
  PENDING_CONFIRMATION = null;
  return box;
}

function actionButton(action, path, className) {
  return button(action.label, function () { submit(path, action.fields); },
                className);
}

function undoButton(repId, adjustmentId, accountId) {
  return button("undo", function () {
    submit("/api/adjust/revert",
           { rep: repId, adjustment: adjustmentId, account: accountId });
  });
}

/* --- views (§5.5) -------------------------------------------------------- */

function renderIndex(data) {
  var nodes = [restartBanner(data.meta), confirmationBanner()];
  var head = el("div");
  head.appendChild(el("p", "meta", "Pick a rep to open their queue."));
  nodes.push(head);
  for (var i = 0; i < data.reps.length; i++) {
    var rep = data.reps[i];
    var row = el("div", "row");
    row.appendChild(link("#/queue?rep=" + rep.rep_id, rep.name));
    row.appendChild(el("span", "meta",
                       " · " + rep.territory + " · " + rep.email));
    nodes.push(row);
  }
  paint(nodes);
}

function renderQueue(data) {
  var nodes = [restartBanner(data.meta), confirmationBanner()];

  nodes.push(el("h1", null, data.header_line));
  nodes.push(el("p", "meta", data.run_stamp));
  var budgets = el("p", "meta");
  budgets.appendChild(document.createTextNode("Your adjustments: "));
  budgets.appendChild(link("#/adjustments?rep=" + data.rep.rep_id,
                           data.budget_bar));
  nodes.push(budgets);

  if (!data.items.length) {
    // §9.4(a). Never "you're all caught up": a rep who cannot see their
    // unscored accounts will assume Warrant is hiding work from them.
    nodes.push(panel("Nothing in your queue right now.",
      ["Every account assigned to you is either muted by you or inactive. " +
       "Muted accounts return automatically when their window expires — see " +
       "your adjustments."],
      [navButton("view your adjustments",
                 "#/adjustments?rep=" + data.rep.rep_id)]));
    paint(nodes);
    return;
  }

  for (var i = 0; i < data.items.length; i++) {
    nodes.push(queueRow(data.rep.rep_id, data.items[i]));
  }
  paint(nodes);
}

function queueRow(repId, item) {
  var row = el("div", "row");

  var pts = el("span", "pts");
  pts.appendChild(document.createTextNode(item.points_display));
  // "pts" is fixed chrome that belongs to this layout, not a formatted value.
  pts.appendChild(document.createTextNode(" pts"));
  row.appendChild(pts);

  row.appendChild(el("span", "rank", item.rank_in_queue + "."));
  row.appendChild(el("span", "chip " + bandClass(item.band), item.band_label));
  row.appendChild(document.createTextNode(" "));
  row.appendChild(link("#/account/" + item.account_id + "?rep=" + repId,
                       item.account_name));
  if (item.adjustment_chip) {
    row.appendChild(document.createTextNode(" "));
    row.appendChild(el("span", "chip adj", item.adjustment_chip));
  }

  // Already truncated server-side by reasons.truncate_at_word(text, 120).
  row.appendChild(el("div", "sentence", item.top_reason_text));

  var meta = el("div", "meta");
  meta.appendChild(el("span",
    "chip" + (item.freshness_is_stale ? " stale" : ""), item.freshness_chip));
  var right = el("span", null, item.limits_compressed);
  right.style.cssFloat = "right";
  meta.appendChild(right);
  row.appendChild(meta);

  var controls = el("div", "actions");
  var work = button("Work it", function () {
    submit("/api/task", { rep: repId, account: item.account_id,
                          rank: item.rank_in_queue, action: "accepted" });
  }, "primary");
  if (!item.work_it_enabled) {
    // The server decided this, not the frontend. The sentence is the server's.
    work.disabled = true;
    work.title = item.friction_text;
  }
  controls.appendChild(work);
  controls.appendChild(document.createTextNode(" "));
  controls.appendChild(button("Not now", function () {
    submit("/api/task", { rep: repId, account: item.account_id,
                          rank: item.rank_in_queue, action: "skipped" });
  }));
  controls.appendChild(document.createTextNode(" "));
  // Item-scoped disputes need the evidence in view first (§6.1), so Dispute is
  // a link into the detail view rather than a control here.
  controls.appendChild(link("#/account/" + item.account_id + "?rep=" + repId,
                            "Dispute"));
  row.appendChild(controls);

  if (item.friction_text) {
    row.appendChild(el("div", "meta", item.friction_text));
  }
  return row;
}

function clearFloat() {
  var node = el("div");
  node.style.clear = "both";
  return node;
}

function bandClass(band) {
  if (band === "ACT_NOW") { return "act"; }
  if (band === "REVIEW") { return "rev"; }
  if (band === "HOLD") { return "hold"; }
  return "none";
}

function renderDetail(data) {
  var repId = CURRENT.params.rep || "1";
  var accountId = data.account.account_id;
  var nodes = [restartBanner(data.meta), confirmationBanner()];

  nodes.push(el("h1", null, data.account.name + " · " + data.account.domain));
  nodes.push(el("p", "meta", data.account.meta_line));

  // Verdict strip: compact, beneath the account name. Evidence first, priority
  // second (§5.4 rule 5) — the reasons block is what sits above the fold.
  var verdict = el("p");
  verdict.appendChild(el("span", "chip " + bandClass(data.verdict.band),
                         data.verdict.band_label));
  verdict.appendChild(document.createTextNode(" "));
  verdict.appendChild(el("strong", null, data.verdict.points_display + " pts"));
  if (data.verdict.above_anchor_note) {
    verdict.appendChild(document.createTextNode(data.verdict.above_anchor_note));
  }
  verdict.appendChild(document.createTextNode(" "));
  verdict.appendChild(el("span", "meta", data.verdict.anchor_note));
  nodes.push(verdict);
  nodes.push(el("p", "meta",
                data.verdict.rank_line + " · confidence: " +
                data.verdict.confidence));
  if (data.verdict.adjusted_note) {
    nodes.push(el("p", "meta", data.verdict.adjusted_note));
  }

  for (var b = 0; b < data.banners.length; b++) {
    nodes.push(bannerNode(data.banners[b]));
  }

  nodes.push(el("h2", null, data.heading));

  if (data.no_signals_line) {
    nodes.push(el("div", "reason", data.no_signals_line));
  }
  for (var r = 0; r < data.reasons.length; r++) {
    nodes.push(reasonNode(repId, accountId, data.reasons[r]));
  }

  // §5.5: the limits line is mandatory and sits immediately under the reasons.
  // A silently absent one is the failure DESIGN_SPEC.md §4.6 exists to prevent,
  // so this fails visibly rather than rendering nothing.
  if (data.limits_line) {
    nodes.push(el("div", "limits", data.limits_line));
  } else {
    nodes.push(el("div", "bug", "limits line missing — this is a bug"));
  }

  nodes.push(el("h2", null, "Adjust your queue"));
  nodes.push(el("p", "meta", data.adjust.budget_line));
  var adjustRow = el("p");
  for (var a = 0; a < data.adjust.buttons.length; a++) {
    var spec = data.adjust.buttons[a];
    adjustRow.appendChild(button(spec.label, makeSubmitter("/api/adjust",
                                                           spec.fields)));
    adjustRow.appendChild(document.createTextNode(" "));
  }
  nodes.push(adjustRow);

  nodes.push(el("h2", null, "Disagree with the whole item"));
  var disputeRow = el("p");
  for (var d = 0; d < data.item_dispute.buttons.length; d++) {
    disputeRow.appendChild(actionButton(data.item_dispute.buttons[d],
                                        "/api/dispute"));
    disputeRow.appendChild(document.createTextNode(" "));
  }
  nodes.push(disputeRow);
  if (data.item_dispute.unavailable_note) {
    nodes.push(el("p", "meta", data.item_dispute.unavailable_note));
  }

  nodes.push(el("h2", null, "Your history on this account"));
  if (!data.history.length) {
    nodes.push(el("p", "meta", "Nothing yet."));
  } else {
    for (var h = 0; h < data.history.length; h++) {
      var entry = data.history[h];
      var hrow = el("div", "row");
      hrow.appendChild(document.createTextNode(entry.line + " [" +
                                               entry.status + "] "));
      if (entry.undo_adjustment_id) {
        hrow.appendChild(undoButton(repId, entry.undo_adjustment_id, accountId));
      }
      nodes.push(hrow);
    }
  }

  nodes.push(el("h2", null, data.research.heading));
  if (data.research.empty_note) {
    nodes.push(el("p", "meta", data.research.empty_note));
  }
  for (var o = 0; o < data.research.items.length; o++) {
    nodes.push(observationRow(data.research.items[o]));
  }
  if (data.research.see_all_href) {
    var more = el("p");
    more.appendChild(link(hashForApiHref(data.research.see_all_href),
                          "see all research"));
    nodes.push(more);
  }

  var footer = el("p", "footer");
  footer.appendChild(link("#/queue?rep=" + repId, "back to queue"));
  footer.appendChild(document.createTextNode(" · "));
  footer.appendChild(link("#/ruleset", "How the weights are set"));
  nodes.push(footer);

  paint(nodes);
}

function makeSubmitter(path, fields) {
  return function () { submit(path, fields); };
}

function bannerNode(banner) {
  var box = el("div", "banner" + (banner.level === "warn" ? " warn" : ""));
  box.appendChild(el("div", null, banner.text));
  if (banner.actions && banner.actions.length) {
    var row = el("div", "actions");
    for (var i = 0; i < banner.actions.length; i++) {
      row.appendChild(actionButton(banner.actions[i], "/api/dispute"));
      row.appendChild(document.createTextNode(" "));
    }
    box.appendChild(row);
  }
  return box;
}

/* Element order inside a reason is fixed by DESIGN_SPEC.md §6.2 and it is not a
 * styling preference: category tag -> sentence -> evidence line -> points ->
 * actions. The points value comes AFTER the evidence, never before it. */
function reasonNode(repId, accountId, reason) {
  var box = el("div", "reason");
  box.appendChild(el("div", "cat", reason.category_label));

  if (reason.is_suppressed) {
    // The disputed reason keeps its slot, struck through. The frontend does not
    // reorder or remove it.
    box.appendChild(el("div", "sentence struck", reason.text));
    if (reason.suppression_note) {
      box.appendChild(el("div", "evidence", reason.suppression_note));
    }
    box.appendChild(el("div", "rpts", reason.points_display));
    var undoRow = el("div", "actions");
    if (reason.undo_adjustment_id) {
      undoRow.appendChild(undoButton(repId, reason.undo_adjustment_id,
                                     accountId));
    }
    if (reason.new_events_note) {
      undoRow.appendChild(el("span", "meta", " " + reason.new_events_note));
    }
    box.appendChild(undoRow);
    box.appendChild(clearFloat());
    return box;
  }

  box.appendChild(el("div", "sentence", reason.text));
  box.appendChild(el("div", "evidence", reason.evidence_summary));
  box.appendChild(el("div", "rpts", reason.points_display));

  var actions = el("div", "actions");
  if (reason.evidence_href) {
    // A real request, not a client-side reveal: opening the drawer is what
    // writes evidence_opened and clears the §6.4 friction gate (§3.8).
    actions.appendChild(link(hashForApiHref(reason.evidence_href),
                             "see evidence"));
    actions.appendChild(document.createTextNode("   "));
  }
  for (var i = 0; i < reason.actions.length; i++) {
    actions.appendChild(actionButton(reason.actions[i], "/api/dispute"));
    actions.appendChild(document.createTextNode(" "));
  }
  box.appendChild(actions);
  box.appendChild(clearFloat());
  return box;
}

function observationRow(item) {
  var row = el("div", "row");
  row.appendChild(document.createTextNode("· " + item.summary));
  var meta = el("div", "meta");
  meta.appendChild(document.createTextNode(item.source_name + " · " +
                                           item.retrieved_display));
  if (item.agent_run_display) {
    meta.appendChild(document.createTextNode(" · " + item.agent_run_display));
  }
  if (item.source_url_text) {
    var ref = el("div", "ref meta", "ref: " + item.source_url_text);
    meta.appendChild(ref);
  }
  row.appendChild(meta);
  return row;
}

function renderEvidence(data) {
  var repId = CURRENT.params.rep || "1";
  var nodes = [restartBanner(data.meta), confirmationBanner()];

  nodes.push(el("h1", null, data.header));
  nodes.push(el("p", "meta", data.summary_line));

  if (data.events.length) {
    for (var i = 0; i < data.events.length; i++) {
      nodes.push(evidenceRow(data.events[i]));
    }
  } else if (data.state_fallback) {
    nodes.push(el("div", "row", data.state_fallback));
  }

  nodes.push(el("p", "meta", data.source_link_note));

  var actions = el("p");
  for (var a = 0; a < data.actions.length; a++) {
    actions.appendChild(actionButton(data.actions[a], "/api/dispute"));
    actions.appendChild(document.createTextNode(" "));
  }
  nodes.push(actions);

  if (data.observations.length) {
    nodes.push(el("h2", null, "Agent observations for this account"));
    for (var o = 0; o < data.observations.length; o++) {
      nodes.push(observationRow(data.observations[o]));
    }
  }

  var footer = el("p", "footer");
  footer.appendChild(link(hashForApiHref(data.back_href), "back"));
  nodes.push(footer);
  paint(nodes);
}

function evidenceRow(event) {
  var row = el("div", "evrow");
  var pts = el("span", "pts", event.contribution_display);
  row.appendChild(pts);
  row.appendChild(el("strong", null, event.occurred_display));
  row.appendChild(document.createTextNode(" · " + event.magnitude_display +
                                          " " + event.detail_display));
  row.appendChild(el("div", "meta", event.person_display));
  row.appendChild(el("div", "meta", event.source_display));
  // ref: is deliberately selectable text and NEVER an anchor. A link here
  // would 404 by design (README limitation 11).
  row.appendChild(el("div", "meta ref", event.ref_display));
  row.appendChild(clearFloat());
  return row;
}

function renderResearch(data) {
  var nodes = [restartBanner(data.meta), confirmationBanner()];
  nodes.push(el("h1", null, "Agent research · " + data.account_name));
  nodes.push(el("p", "meta", data.count_line));
  for (var i = 0; i < data.items.length; i++) {
    nodes.push(observationRow(data.items[i]));
  }
  var footer = el("p", "footer");
  footer.appendChild(link(hashForApiHref(data.back_href), "back"));
  nodes.push(footer);
  paint(nodes);
}

function renderAdjustments(data) {
  var repId = data.rep.rep_id;
  var nodes = [restartBanner(data.meta), confirmationBanner()];
  nodes.push(el("h1", null, "Your adjustments · " + data.rep.name));
  nodes.push(el("p", "meta", data.budget_bar));

  if (!data.rows.length) {
    nodes.push(el("p", "meta", "None yet."));
  }
  for (var i = 0; i < data.rows.length; i++) {
    var row = data.rows[i];
    var node = el("div", "row");
    node.appendChild(el("div", null, row.line));
    var meta = el("div", "meta");
    meta.appendChild(document.createTextNode(row.created_display + " · " +
                                             row.expires_display + " "));
    if (row.undo_adjustment_id) {
      meta.appendChild(undoButton(repId, row.undo_adjustment_id,
                                  row.account_id));
    }
    node.appendChild(meta);
    nodes.push(node);
  }

  var footer = el("p", "footer");
  footer.appendChild(link("#/queue?rep=" + repId, "back to queue"));
  nodes.push(footer);
  paint(nodes);
}

function renderMetrics(data) {
  var nodes = [restartBanner(data.meta), confirmationBanner()];
  nodes.push(el("h1", null, "Warrant · metrics"));
  nodes.push(el("p", "meta", data.window_line));

  // §9.4(c): the caveats go near the top, not at the bottom. On the ephemeral
  // deployment the per-type counts are empty after every restart, so the
  // caveats are the context a reader needs before the numbers, not after them.
  for (var c = 0; c < data.caveat_lines.length; c++) {
    nodes.push(el("div", "caveat", data.caveat_lines[c]));
  }

  var table = el("table");
  for (var i = 0; i < data.rates.length; i++) {
    var rate = data.rates[i];
    var tr = el("tr");
    tr.appendChild(el("td", null, rate.label));
    tr.appendChild(el("td", "num", rate.display));
    var detail = rate.numerator + " / " + rate.denominator;
    if (rate.note) { detail = detail + " — " + rate.note; }
    tr.appendChild(el("td", "meta", detail));
    table.appendChild(tr);
  }
  nodes.push(table);

  nodes.push(el("h2", null, "Per signal type"));
  nodes.push(el("p", "meta", data.flag_note));
  var perType = el("table");
  perType.appendChild(headerRow(["Signal type", "Shown", "Disputes",
                                 "Dispute rate", "Suppression rate", ""]));
  for (var t = 0; t < data.per_type.length; t++) {
    var row = data.per_type[t];
    var tr2 = el("tr", row.flagged ? "flagged" : null);
    tr2.appendChild(el("td", null, row.display_name));
    tr2.appendChild(el("td", "num", row.shown_count));
    tr2.appendChild(el("td", "num", row.dispute_count));
    tr2.appendChild(el("td", "num", row.dispute_rate_display));
    tr2.appendChild(el("td", "num", row.suppression_rate_display));
    tr2.appendChild(el("td", null, row.flag_text));
    perType.appendChild(tr2);
  }
  nodes.push(perType);

  nodes.push(el("h2", null, "Ownership errors"));
  if (!data.ownership_errors.length) {
    nodes.push(el("p", "meta", "None reported."));
  } else {
    var owners = el("table");
    for (var e = 0; e < data.ownership_errors.length; e++) {
      var owner = data.ownership_errors[e];
      var tr3 = el("tr");
      tr3.appendChild(el("td", null, owner.account_name));
      tr3.appendChild(el("td", "num", owner.n));
      owners.appendChild(tr3);
    }
    nodes.push(owners);
  }
  paint(nodes);
}

function headerRow(labels) {
  var tr = el("tr");
  for (var i = 0; i < labels.length; i++) {
    tr.appendChild(el("th", null, labels[i]));
  }
  return tr;
}

function renderRuleset(data) {
  var nodes = [restartBanner(data.meta), confirmationBanner()];
  nodes.push(el("h1", null, "Warrant ruleset · " + data.ruleset_version));
  nodes.push(el("div", "limits", data.header_line));

  var table = el("table");
  table.appendChild(headerRow(["Signal", "Code", "Category", "Kind", "Weight",
                               "Cap", "Half-life (d)", "Dispute rate", ""]));
  for (var i = 0; i < data.rows.length; i++) {
    var row = data.rows[i];
    var tr = el("tr", row.flagged ? "flagged" : null);
    tr.appendChild(el("td", null, row.display_name));
    tr.appendChild(el("td", null, row.code));
    tr.appendChild(el("td", null, row.category));
    tr.appendChild(el("td", null, row.kind));
    tr.appendChild(el("td", "num", row.base_weight_display));
    tr.appendChild(el("td", "num", row.max_contribution_display));
    tr.appendChild(el("td", "num", row.half_life_display));
    tr.appendChild(el("td", "num", row.dispute_rate_display));
    tr.appendChild(el("td", null, row.flag_text));
    table.appendChild(tr);
  }
  nodes.push(table);

  nodes.push(el("h2", null, "The anchor"));
  nodes.push(el("p", null, data.anchor_note));
  nodes.push(el("h2", null, "Where these weights come from"));
  nodes.push(el("p", null, data.evidence_note));
  nodes.push(el("h2", null, "What this score does not claim"));
  nodes.push(el("p", null, data.not_claimed_note));
  paint(nodes);
}

/* --- boot ---------------------------------------------------------------- */

window.addEventListener("hashchange", route);
route();
