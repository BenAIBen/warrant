# HOSTING_RESEARCH.md — Warrant on a GitHub Pages URL

**Stage:** 1 of 4 (research)
**Author:** Researcher agent (AI-generated)
**Date:** 13 August 2026
**Working directory:** `C:\Users\DELL Lattitude\Documents\Unify Agent Test`

---

## 0. Scope, method, and what this document is not

**The question this is meant to inform:** Warrant currently runs only on `127.0.0.1`. It must be reachable by anyone on the internet **via a GitHub Pages URL**, with the backend and database genuinely running somewhere that is not the user's laptop. GitHub Pages serves static files only. This document establishes what is actually true about the available options so the design stage can choose.

**Method.** Every claim below is labelled:

- **[VERIFIED]** — I fetched the cited page during this session and the claim is drawn from what it said.
- **[UNVERIFIED]** — I could not fetch a primary source, or the source is secondary/third-party. Treated as a lead, not a fact.
- **[INFERENCE]** — my own reasoning from verified facts plus the Warrant source code I read.

**Nothing here is deployed, live, or tested.** Nobody in this pipeline has a cloud account, a credential, or the ability to sign up for one. I have not created a repo, provisioned a database, or measured a cold start. Every latency number is either quoted from a vendor's own documentation or labelled as a third-party report.

**I also did not redesign Warrant.** Where a hosting option would force a change to the scoring engine, I say what the change is and estimate its cost; I do not make the call.

**What I read locally to ground sections 4 and 5:** `README.md`, `STATUS_REPORT.md`, `db/schema.sql`, `warrant/db.py`, `warrant/scoring.py`, `warrant/queue.py`, `warrant/metrics.py`, `warrant/feedback.py` (partial), `app.py` (partial), `warrant/reasons.py` (partial).

---

## 0.1 The number that drives the whole architecture

Before the hosting options, one finding from reading the code, because it eliminates several options outright.

**A single `GET /queue?rep=1` render issues on the order of 1,400 individual SQL statements.** [INFERENCE, from source I read in full]

Counting from `warrant/scoring.py` and `warrant/queue.py`:

| Per account, per render | Statements | Source |
|---|---|---|
| `_load_account_context` — accounts, people, event totals, owning rep | 3–4 SELECTs | `scoring.py` L344–385 |
| `_event_rows` — one SELECT per **event-kind** signal type (12 of the 19; 7 are state predicates) | 12 SELECTs | `scoring.py` L388–397, L494 |
| `_owner_name` | 1 SELECT | `queue.py` L250–255 |
| `_persist_score` — 1 `scores` INSERT + one `reasons` INSERT per contribution + one `executemany` into `reason_evidence` | ~7–13 writes | `queue.py` L258–296 |

Rep 1's patch is **53 accounts** (from the verified transcript in `STATUS_REPORT.md` §4: "rank 2 of 53"). That gives roughly `53 × (16 reads + 9 writes) ≈ 1,300`, plus the run-level INSERT and whatever `reasons.build_reasons()` issues — I did not read that function's query sites, so **1,400 is a floor, not a ceiling.**

This is by design and it is the feature: `README.md` states there is "no cache, no memoisation and no precomputed score literal anywhere", and three tests prove liveness by mutating the database behind the application's back. The explainability guarantee — `sum(reason points) == score.points` from one code path — depends on re-deriving everything from rows at request time.

**Why this matters for hosting:** it is fine at ~0.21s against a local SQLite file (in-process, no network). It is fatal against any database where each statement is a network round-trip. At a conservative 10 ms per round-trip, 1,400 statements is **14 seconds per page view**. At 30 ms it is 42 seconds.

**Consequence:** any option that puts a network hop between `warrant/scoring.py` and the data — Turso's HTTP API, Cloudflare D1's REST API, Neon or Supabase over the wire from a different provider's region — is disqualified for the *live path* unless the scoring engine is restructured to batch or to load the whole account set in one query. That restructure is a redesign of the core module, not a deployment change.

The options that survive are the ones where **the database is in the same process or on the same machine as the Python**.

---

## 1. GitHub Pages: the hard constraints

### 1.1 What it will and will not do

| Constraint | Value | Status |
|---|---|---|
| Server-side execution | **"GitHub Pages does not support server-side languages such as PHP, Ruby, or Python."** | [VERIFIED] — [Creating a GitHub Pages site](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site) |
| What it serves | "GitHub Pages publishes any static files that you push to your repository." | [VERIFIED] — same page |
| Published site size | **No larger than 1 GB** | [VERIFIED] — [GitHub Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits) |
| Source repository | Recommended limit **1 GB** | [VERIFIED] — same page |
| Bandwidth | **Soft limit 100 GB/month** | [VERIFIED] — same page |
| Builds | **Soft limit 10 builds/hour**; "This limit does not apply if you build and publish your site with a custom GitHub Actions workflow." | [VERIFIED] — same page |
| Deployment timeout | **10 minutes** | [VERIFIED] — same page |

The 1 GB and 100 GB numbers are not a live concern for Warrant: the static payload would be a handful of HTML/CSS/JS files.

### 1.2 Publishing sources

Three options. [VERIFIED] — [Configuring a publishing source](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)

1. **Branch, root** — "the source folder can either be the root of the repository (`/`) on the source branch".
2. **Branch, `/docs`** — "or a `/docs` folder on the source branch". This is the one that matters here: it lets the Pages site live inside the existing Warrant repo without a separate branch or a build step, which is the least a non-expert user has to learn.
3. **GitHub Actions workflow** — recommended if you need "a build process other than Jekyll or you do not want a dedicated branch to hold your compiled static files", and it exempts you from the 10-builds-per-hour soft limit.

**[INFERENCE]** For this project, the `/docs` folder on the default branch is the lowest-friction option. It needs no Actions YAML, no second branch, and no CLI. It does need an empty `.nojekyll` file if any asset path begins with an underscore — the docs note Jekyll is the default builder for branch sources.

### 1.3 HTTPS

**[VERIFIED]** — [Securing your GitHub Pages site with HTTPS](https://docs.github.com/en/pages/getting-started-with-github-pages/securing-your-github-pages-site-with-https): "GitHub Pages sites created after June 15, 2016, and using `github.io` domains are served over HTTPS automatically."

Custom domains are supported and can also have Enforce HTTPS enabled, but a custom domain requires DNS control the pipeline does not have and the user may not have. **The default `*.github.io` URL is HTTPS with no configuration, which is what this project should assume.**

### 1.4 What HTTPS-by-default forces: mixed content

This is the first hard consequence, and it is not negotiable.

**[VERIFIED]** — [MDN: Mixed content](https://developer.mozilla.org/en-US/docs/Web/Security/Mixed_content): browsers "auto-upgrade image, video, and audio mixed content requests from HTTP to HTTPS, and **block insecure requests for all other resource types**." MDN lists `fetch()` requests and `XMLHttpRequest` requests explicitly under **blockable content**.

**So: a page served from `https://<user>.github.io/` cannot call an `http://` backend. Full stop.** Not "warns", not "degrades" — the request never leaves the browser.

**What the user would actually see.** The `fetch()` promise rejects with a `TypeError` (in Chrome, `TypeError: Failed to fetch`) and the console logs a mixed-content block. The characteristic Chrome wording is:

```
Mixed Content: The page at 'https://<user>.github.io/warrant/' was loaded over HTTPS,
but requested an insecure resource 'http://<backend-host>:8000/queue?rep=1'.
This request has been blocked; the content must be served over HTTPS.
```

**[VERIFIED]** for the mechanism and the fact that `fetch` is blocked (MDN, above). **[UNVERIFIED]** for the exact console string — that is characteristic Chrome wording from recall, not from a page I fetched. Do not quote it as a literal in the runbook without reproducing it.

**Practical effect:** any backend host that does not give you HTTPS on its default hostname is unusable here. That eliminates "run it on a VPS on port 8000 and point at the IP" as an option unless a certificate is obtained. Every host in §2 that survives does give HTTPS on the default domain.

### 1.5 What cross-origin forces: CORS

`https://<user>.github.io` and `https://<app>.onrender.com` are **different origins**. Any `fetch()` between them is a cross-origin request.

**[VERIFIED]** — [MDN: CORS](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS): "browsers restrict cross-origin HTTP requests initiated from scripts… a web application using those APIs can only request resources from the same origin the application was loaded from unless the response from other origins includes the right CORS headers."

Concretely, the backend must send:

```
Access-Control-Allow-Origin: https://<user>.github.io
```

or `*` for non-credentialed requests. **[VERIFIED]** MDN: "When responding to a credentialed request, the server **must** specify an origin in the value of the `Access-Control-Allow-Origin` header, instead of specifying the `*` wildcard."

**Preflight.** [VERIFIED] MDN: a preflight `OPTIONS` request is sent when the request is not a "simple request". Simple requires GET/HEAD/POST, only CORS-safelisted headers, and a `Content-Type` of `application/x-www-form-urlencoded`, `multipart/form-data`, or `text/plain`.

**[INFERENCE] applied to Warrant:** Warrant's writes are `POST /dispute`, `POST /adjust`, `POST /adjust/revert`, `POST /task`, and `app.py`'s docstring says "Every action is a real `<form>` POST". Form POSTs use `application/x-www-form-urlencoded`, which **is** on the simple list. So if a JS frontend replicated them faithfully it would avoid preflight. If it instead sent `Content-Type: application/json` — the obvious choice for a JSON API — **every write would trigger an `OPTIONS` preflight**, and `app.py` currently has no `do_OPTIONS` handler at all (its documented route list covers GET and POST only). That would need adding.

**What the user would actually see** on a missing header: the `fetch()` promise rejects with `TypeError: Failed to fetch` and the console logs, in characteristic Chrome wording:

```
Access to fetch at 'https://<app>.onrender.com/queue?rep=1' from origin
'https://<user>.github.io' has been blocked by CORS policy: No
'Access-Control-Allow-Origin' header is present on the requested resource.
```

Again: mechanism [VERIFIED] via MDN; exact string [UNVERIFIED].

**The trap worth naming now:** the response body arrives at the browser. The browser then refuses to hand it to the script. So the backend's own logs will show a clean `200`, and the user will see an empty page. Anyone debugging this from the server side will conclude everything is fine.

### 1.6 Three ways to satisfy "reachable via a GitHub Pages URL", and what each costs

This is a design decision, not mine to make, but the research is only useful if the options are on the table with their real costs.

Warrant is **server-rendered HTML** (`app.py` → `warrant/render.py`), with no client framework and no build step, and `README.md` states everything works with JavaScript off. That fact prices the options very differently.

| Option | What the user's URL bar shows | CORS needed? | Code change to Warrant | Keeps "works with JS off"? |
|---|---|---|---|---|
| **A. Static shell + JSON API.** Pages serves HTML/JS; JS fetches JSON from the backend and renders client-side. | `github.io` throughout | **Yes**, plus `do_OPTIONS` if JSON content-type | **Large.** Add a JSON API alongside `render.py`; reimplement queue/detail/evidence/adjustments/metrics/ruleset rendering in JS; re-implement the reason truncation and limits line client-side or ship them pre-rendered | **No** |
| **B. Pages as a landing page that links out.** A static page explaining Warrant with a link to the backend URL. | `github.io`, then `onrender.com` after the click | No | **None** | Yes |
| **C. Pages page embedding the backend in an `<iframe>`.** | `github.io` throughout | **No** — iframes are not subject to CORS | **None**, provided the backend does not send `X-Frame-Options`/frame-ancestors CSP | Yes |

**[VERIFIED]** that iframes are not governed by CORS: CORS applies to script-initiated `fetch`/`XHR` (MDN, §1.5). Framing is governed by `X-Frame-Options` and CSP `frame-ancestors` instead.
**[INFERENCE]** that Warrant would frame successfully: I read `app.py`'s route handling and header-setting is not visible in the portion I read, but nothing in the documented design sets security headers, and the README describes no CSP. **This is an inference and should be confirmed by reading `app.py`'s response-header code before the runbook depends on it.**

Option C is the cheapest path to a genuine `github.io` URL with zero change to the scoring engine, the explainability invariant, or the no-JS guarantee. Option A is the architecturally "proper" one and costs the most — and note it would break the `sum(reason points) == score.points` story's simplest demonstration, because the arithmetic and the rendering would once again live in two places, which is precisely the failure mode `STATUS_REPORT.md` §1 records the whole design as existing to prevent.

I am flagging that tension because it is a research finding, not a design preference: **the obvious "modern" architecture for a Pages frontend is the one most in conflict with Warrant's core claim.**

### 1.7 One policy point worth reading before the demo goes out

**[VERIFIED]** — GitHub's Pages usage policy states Pages "is not intended for or allowed to be used as a free web-hosting service to run your online business, e-commerce site, or any other website that is primarily directed at either facilitating commercial transactions or providing commercial software as a service (SaaS)." Found via search of [GitHub Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits) and [GitHub Terms for Additional Products and Features](https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features).

**[INFERENCE]** A demo of an internal prototype, shown to colleagues and prospects, is not obviously "primarily directed at facilitating commercial transactions". But if Warrant later becomes a customer-facing product surface, Pages is the wrong host and this clause is the reason. Worth knowing now rather than after a takedown.

Also verified on the same policy: "GitHub Pages sites shouldn't be used for sensitive transactions like sending passwords or credit card numbers." Warrant has no credentials and no login (`README.md`: "there are no credentials anywhere in this repo"), so this is currently moot — but it is a hard ceiling on ever adding rep authentication to a Pages-fronted deployment.

---

## 2. Backend hosts that run Python

Ordered roughly by how well they fit. Every row is labelled.

### 2.1 Render — **free tier alive, and it fits**

**[VERIFIED]** — [Deploy for Free – Render Docs](https://render.com/docs/free)

| Question | Answer |
|---|---|
| Free tier as of 2026? | **Yes.** "750 Free instance hours to each workspace per calendar month" |
| Sleep policy | Spins down after **"15 minutes without receiving any inbound traffic"** |
| Wake time | **"about one minute"** (Render's own wording) |
| HTTPS on default domain | Yes — `*.onrender.com` [UNVERIFIED as a quoted sentence; see Appendix A] |
| Persistent disk | **No.** "Free web services cannot" attach persistent disks. Paid services can. |
| Arbitrary Python / long-running process | Yes — Render runs a long-lived process listening on a port, not a serverless function. No runtime ceiling per request. [INFERENCE from the service model; see Appendix A] |
| Free Postgres | **Trap.** Free Postgres databases "expire 30 days after creation" and become inaccessible unless upgraded; 14-day grace period, then Render deletes the database and all its data. Capped at 1 GB, one per workspace. |

Additional [VERIFIED] via Render docs search: "If you consume all of your Free instance hours during a given month, Render suspends all of your Free web services until the start of the next month." And a changelog entry, [Free web services now remain active while receiving WebSocket messages](https://render.com/changelog/free-web-services-now-remain-active-while-receiving-websocket-messages), confirms Render actively maintains what counts as keep-alive traffic.

**The 30-day Postgres expiry is the single most important trap in this entire document.** A demo that works today and is dead in 31 days is worse than no demo, and it fails silently from the user's point of view. If a Postgres path is chosen on Render, the runbook must say this in bold.

**Hard blockers for Warrant: none, with one caveat.** `README.md` documents `WARRANT_PORT` as "HTTP port, **bound to 127.0.0.1 only**". A container must bind `0.0.0.0` and read the platform's injected `$PORT`. That is a small change in `app.py`'s server setup. **[INFERENCE]** — I read only the first 80 lines of `app.py` and did not see the `serve()` call, so I am inferring the change from the README's own description. Confirm before writing the runbook.

### 2.2 Fly.io — **free tier gone for new accounts**

**[VERIFIED]** — [Fly.io pricing](https://fly.io/docs/about/pricing/)

- **"Fly.io no longer offers plans to new customers."** Pay-as-you-go only.
- Legacy free allowances (3 × shared-cpu-1x 256MB VMs, 3 GB volume storage, regional transfer allowances) are **grandfathered to organizations on the discontinued Hobby/Launch/Scale plans before 7 October 2024**. A new signup does not get them.
- Volumes: **"$0.15/GB per month of provisioned capacity"**; snapshots "$0.08/GB per month" with "First 10GB free each month".
- No current trial credit mentioned on that page.

**Verdict:** not a free option in 2026. It remains a strong *cheap* option — persistent volumes at $0.15/GB/month means a durable SQLite file, and a small always-on machine avoids cold starts entirely. But it requires a card, and `flyctl` is not installed on the machine (installing it is possible but adds a step a non-expert has to get right).

### 2.3 Railway — **trial credit, not a free tier**

**[VERIFIED]** — [Railway plans](https://docs.railway.com/reference/pricing/plans)

- Trial: **"a free one-time grant of $5"** plus **"$1 of free credit per month"**. Trial limits: "2 Replicas, 1 GB RAM, 2 vCPU, 1 GB Ephemeral Storage, 0.5 GB Volume Storage, 4 GB Image Size."
- Hobby: **"$5 / month"** which "includes $5 of resource usage per month". 5 GB volume storage.

**[INFERENCE]** $1/month of credit will not keep a container running continuously for a month. Railway's trial is a way to try the platform, not a way to host a persistent demo. The Hobby plan at $5/month with 5 GB of *volume* storage is a genuine SQLite-durable option and is the closest paid equivalent to the Fly.io path.

**[UNVERIFIED]** The fetched page did not state whether trial deployments serve public traffic, and did not date the removal of Railway's older free Starter plan. Do not assert either.

### 2.4 Koyeb — **contradictory sources; treat as unavailable**

This one has a genuine disagreement in the evidence and I am not going to resolve it by picking a side.

- **[VERIFIED]** — [Koyeb pricing](https://www.koyeb.com/pricing) as fetched today shows a free allowance only for **serverless Postgres** ("Free 5h" — 5 hours/month, 0.25 vCPU, 1 GB RAM, 1 GB storage, scale-to-zero). The compute/app-hosting section shows **no free tier**; the cheapest listed option is a GPU instance at "$0.50/hr".
- **[UNVERIFIED]** — A search result summary claims Koyeb "still has a free Instance type for one web service, with 512 MB RAM, 0.1 vCPU, and 2 GB SSD", but that **new signups for the free Starter tier were closed following a Mistral AI acquisition in February 2026**. I did not fetch a primary Koyeb or Mistral announcement confirming the acquisition or the closure date. Sources surfaced but not fetched: `srvrlss.io/provider/koyeb/`, `koyeb.com/blog/sustaining-free-compute-in-a-hostile-environment`.

**The disagreement:** Koyeb's own live pricing page shows no free compute; a third-party aggregator says free compute exists but is closed to new users. Both are consistent with "a new user in August 2026 cannot get free Koyeb compute", which is the only conclusion that matters for this decision. **Treat Koyeb as not available.** If someone wants to overturn that, the thing to fetch is Koyeb's own announcement.

### 2.5 Hugging Face Spaces — **hard blocker, and it is a recent change**

**[VERIFIED]** — [Spaces Overview](https://huggingface.co/docs/hub/spaces-overview)

> "Static Spaces are free for everyone. **Gradio and Docker Spaces run on compute and require a paid plan to create: PRO for personal accounts, Team or Enterprise for organizations.** Free personal accounts in good standing can still host up to 2 Gradio Spaces running on ZeroGPU."

This is decisive. Running Warrant on Spaces means a **Docker Space** (it is a plain `http.server` app, not Gradio). Docker Spaces now require a paid plan to create.

Other verified facts from the same page, for completeness:

- Hardware: "CPU Basic — 2 vCPU, 16 GB, FREE" in the hardware table. **Note the contradiction with the warning above:** the hardware is free, but *creating* the Space type you would need is not. Both statements are on the same page. I am reporting the contradiction rather than reconciling it; the operative constraint is the one that gates account creation.
- Filesystem: "Each Spaces environment is limited to 16GB RAM, 2 CPU cores and **50GB of (not persistent) disk space** by default."
- Sleep: "On free hardware, your Space will 'go to sleep' and stop executing after a period of time if unused." **No duration is given on this page** — see Appendix A.
- Networking: outbound requests allowed only on ports 80, 443 and 8080; "Any requests going to other ports will be blocked." Irrelevant to Warrant, which makes no outbound calls, but relevant if that ever changes.

**Verdict:** blocked, unless the user already has a PRO account.

### 2.6 Vercel Python functions — **runs Python, but the wrong shape**

**[VERIFIED]** — [Using the Python Runtime with Vercel Functions](https://vercel.com/docs/functions/runtimes/python) (page's own `last_updated: 2026-07-22`)

- Python versions available: **3.12 (default), 3.13, 3.14**. Warrant is on 3.14.3, so the version is available.
- Interface: **"Use the Python runtime to run ASGI… and WSGI… applications on Vercel."** The entrypoint must define a top-level `app` (ASGI/WSGI) or `application` (WSGI).
- Bundle limit: "the 500 MB bundle limit" referenced in the `excludeFiles` example.
- Filesystem: "Python uses the current working directory when you pass a relative path to `open()`. The working directory is the base of your project" — the docs do not describe a writable persistent disk, and the serverless model does not provide one.

**Hard blocker for Warrant:** `app.py` is a `BaseHTTPRequestHandler` on a `ThreadingHTTPServer`. That is **not** a WSGI or ASGI application. Vercel will not load it. Adapting it means either writing a WSGI shim around the handler's routing or rewriting `app.py`'s dispatch into a WSGI/ASGI app — a real, if bounded, piece of work. It would also introduce Warrant's first third-party dependency if a framework were used, though a hand-written WSGI callable using only `wsgiref`-style conventions is possible from the stdlib.

**Second, larger blocker:** no persistent writable disk. Warrant writes on **every page view** (`score_runs`, `scores`, `reasons`, `reason_evidence` — see §0.1). A serverless function with an ephemeral filesystem loses all of it, and disputes would not survive.

**[UNVERIFIED]** The fetched page did not state the Hobby-plan maximum function duration — the note about bundle limits rendered with the numbers stripped. See Appendix A.

### 2.7 Netlify Functions — **no Python**

**[VERIFIED]** — [Netlify Lambda compatibility](https://docs.netlify.com/build/functions/lambda-compatibility/): the supported languages listed are **TypeScript, JavaScript, and Go**. Python is not among them. The same page notes "Lambda compatibility mode is deprecated" as of 1 July 2027.

**[UNVERIFIED]** I fetched [Netlify Functions: get started](https://docs.netlify.com/build/functions/get-started/), which showed TypeScript and JavaScript examples and pointed to the Lambda-compatible API for Go, but did not give an exhaustive runtime list for the modern Functions API. I am not asserting Python is impossible on Netlify by some other route; I am asserting **I found no documented Python runtime**, which is enough to rule it out for a runbook.

**Verdict:** eliminated.

### 2.8 Cloudflare Workers — **Python exists, but not the Python you need**

**[VERIFIED]** — [Python Workers](https://developers.cloudflare.com/workers/languages/python/) and [Python Standard Library support](https://developers.cloudflare.com/workers/languages/python/stdlib/)

- **"Python Workers are in beta."** Requires the `python_workers` compatibility flag.
- **"Workers written in Python are executed by Pyodide. Pyodide is a port of CPython to WebAssembly."** So: not native CPython. WebAssembly.
- "The full Python Standard Library is available in Python Workers, with the following exceptions" — 14 excluded modules including `curses`, `dbm`, `tkinter`; `multiprocessing` and `threading` are importable but non-functional; `pty` and `tty` cannot be imported.
- **`sqlite3` is not named** in the exclusion list I retrieved, and is not confirmed as supported either. See Appendix A.

**Hard blockers, in order of severity:**

1. **No persistent filesystem.** Workers have no disk. Even if `sqlite3` imports, there is nowhere to put `data/unify.db` that survives. This alone ends it.
2. **`threading` is non-functional.** `app.py` uses `ThreadingHTTPServer`.
3. **Not a long-running process.** Workers are request-scoped; there is no `serve_forever()`.
4. **Beta.** Not the platform to pick for a demo whose subject is trust.

**Verdict:** eliminated for the backend. Cloudflare's relevance to this project is D1 (§3.4), not Workers.

### 2.9 PythonAnywhere — **free, real, and the expiry is contradictory**

**[VERIFIED]** — [PythonAnywhere pricing](https://www.pythonanywhere.com/pricing/) and [Free Accounts Features](https://help.pythonanywhere.com/pages/FreeAccountsFeatures/)

| Question | Answer |
|---|---|
| Free tier as of 2026? | Yes — "a limited free account", $0/month |
| Web app | **"1 web app with 1 web worker and 1 month expiry"**, at `<username>.pythonanywhere.com` |
| CPU | **100 CPU-seconds per day** |
| Disk | **512 MiB** — and it is **persistent**, unlike every container host above |
| Outbound internet | Restricted: "Specific sites via HTTP(S) only" through a whitelist |
| Always-on tasks / scheduled tasks | Not on free |
| MySQL | Help page: only for "accounts created before January 15, 2026" |
| Sleep / cold start | Not documented as sleeping. [INFERENCE: the model is a hosted WSGI worker, not a scale-to-zero container.] |

**Two things make this genuinely interesting for Warrant:**

1. **The disk is persistent.** This is the only free option found where a SQLite file survives a restart without a paid volume. That directly solves the durability problem in §4.
2. **Outbound restrictions are irrelevant** — `README.md` states Warrant "makes no outbound calls".

**Two things count against it:**

1. **100 CPU-seconds/day is tight.** `STATUS_REPORT.md` §6 records a full queue render at ~0.21s. **[INFERENCE]** That is ~475 renders/day of pure CPU budget before throttling, and PythonAnywhere throttles rather than stops. For a handful of demo viewers that is ample; for a link circulated widely it is not. I have not verified how PythonAnywhere behaves at the limit.
2. **The web app expires.** And here the sources disagree.

**CONTRADICTION — flagged, not resolved.** [VERIFIED] the help page says "1 web app with 1 web worker and **1 month expiry**". [UNVERIFIED] a search result summary of PythonAnywhere's own forums/blog describes a **three-month** cycle: an email every three months with an extension link, and a "Run until 3 months from today" button on the Web tab. These cannot both be current. Possible explanations include a recent policy change (the same help page notes a 15 January 2026 change to MySQL availability, so the page is being actively revised) or stale forum content. **What is certain either way: the free web app expires and requires a manual click to renew, and a demo left unattended will go dark.** The exact interval must be checked on the Web tab after signup.

**Second blocker for Warrant specifically:** PythonAnywhere serves **WSGI** apps. Same problem as Vercel — `BaseHTTPRequestHandler` is not WSGI. [INFERENCE from the platform model; I did not fetch a page stating this explicitly. See Appendix A.]

### 2.10 Deta — **shut down**

**[VERIFIED, secondary]** Deta Space **sunset on 17 October 2024**. Users had a 45-day window to export data and code, after which Deta began deleting all apps and data.

Sources surfaced by search (I read the search result summaries, not each page): Deta's own announcement on X ([@detahq, 2 September 2024](https://x.com/detahq/status/1830605654920466888) — "Space is unfortunately sunsetting on October 17"), the [Hacker News discussion](https://news.ycombinator.com/item?id=41426388), and a downstream project's [shutdown notice](https://github.com/WebCrateApp/webcrate/discussions/90) titled "Deta Space and WebCrate Sunset on October 17, 2024".

**[UNVERIFIED]** I did not fetch Deta's own announcement page directly (the X link was surfaced in search results, not fetched). The date is corroborated across four independent sources, which is why I am labelling it verified-secondary rather than unverified, but it is not a primary fetch.

**Verdict:** eliminated. Do not put Deta in a runbook.

### 2.11 Summary table

| Host | Free in 2026? | Sleeps? | Wake | HTTPS default | Disk | Runs `ThreadingHTTPServer`? | Verdict |
|---|---|---|---|---|---|---|---|
| **Render** | **Yes** (750 hrs/mo) | 15 min | **~1 min** | Yes | **Ephemeral** | **Yes** | **Viable** |
| Fly.io | No (new accts) | Configurable | — | Yes | Volumes $0.15/GB/mo | Yes | Cheap, not free |
| Railway | Trial only ($5 + $1/mo) | — | — | Yes | 0.5–5 GB volume | Yes | Not free |
| Koyeb | Contradictory; treat as no | — | — | Yes | — | Yes | Unavailable |
| HF Spaces | **No** for Docker Spaces | Yes, unstated | — | Yes | 50 GB **not persistent** | Yes (Docker) | **Blocked** |
| Vercel | Yes (Hobby) | Serverless | ms | Yes | Ephemeral | **No — WSGI/ASGI only** | Blocked |
| Netlify | Yes | Serverless | ms | Yes | Ephemeral | **No Python** | Eliminated |
| CF Workers | Yes | ~0 | ms | Yes | **None** | **No — Pyodide/WASM, no threads** | Eliminated |
| PythonAnywhere | **Yes** | No | n/a | Yes | **512 MiB persistent** | **No — WSGI** | Viable with rework |
| Deta | **Shut down 17 Oct 2024** | — | — | — | — | — | Gone |

---

## 3. Hosted databases with free tiers

### 3.1 Neon (Postgres)

**[VERIFIED]** — [Neon plans](https://neon.com/docs/introduction/plans) and [Scale to zero](https://neon.com/docs/introduction/scale-to-zero)

| Question | Answer |
|---|---|
| Free tier | Yes: **0.5 GB storage/project**, **100 CU-hours/project/month** ("enough to run a 0.25 CU compute in a project for 400 hours/month"), **100 projects** |
| Idle behaviour | Suspends after **5 minutes** of inactivity; on Free this **"cannot be disabled"** |
| Wake latency | **"automatically within a few hundred milliseconds"** (Neon's own wording) |
| SQLite compatibility | **None.** Postgres. |
| Connection model | Postgres wire protocol |

Neon's wake latency is the best of any scale-to-zero option here, and it is stated by the vendor rather than inferred. A few hundred milliseconds is invisible in a demo.

**The driver problem is the real cost.** Postgres wire protocol from Python needs `psycopg`/`psycopg2` (C extension) or `pg8000`/`asyncpg` (pure Python but still third-party). Warrant currently passes a test — `test_every_python_file_imports_only_stdlib_or_local` — that walks the AST of every `.py` file and fails on any third-party import (`STATUS_REPORT.md` §5). **Any Postgres path deletes that test's meaning.** That is not a bug, it is a cost, and it should be priced deliberately rather than discovered.

### 3.2 Supabase (Postgres)

**[VERIFIED]** — [Supabase pricing](https://supabase.com/pricing)

| Question | Answer |
|---|---|
| Free tier | **500 MB database** (Shared CPU, 500 MB RAM), **2 active free projects**, **5 GB egress** + 5 GB cached egress |
| Idle behaviour | **"Free projects are paused after 1 week of inactivity."** |
| SQLite compatibility | **None.** Postgres. |
| Connection model | Postgres wire protocol, **or** PostgREST over HTTPS |

**The 1-week pause is a demo-killer of a specific and nasty kind.** It is not a cold start measured in seconds; a paused Supabase project must be manually restored from the dashboard. A demo link sent to a prospect and clicked eight days later does not load slowly — it is broken, and it stays broken until a human logs in. For a link whose purpose is to be shared and clicked at unpredictable times, this is worse than Render's 50-second wake.

Supabase's one genuine advantage over Neon here is **PostgREST**: a REST API over the database, callable from `urllib.request` with no driver. **[INFERENCE]** That would preserve stdlib-only. But it does not preserve the SQL — PostgREST exposes a resource-oriented filter API, not arbitrary SQL, so every query in `scoring.py`, `queue.py` and `metrics.py` would have to be re-expressed. Combined with §0.1's ~1,400 statements per render, each becoming an HTTPS request, this is not viable for the live path.

### 3.3 Turso / libSQL — **the most SQL-compatible option by a wide margin**

**[VERIFIED]** — [Turso pricing](https://turso.tech/pricing), [libSQL docs](https://docs.turso.tech/libsql), [Turso HTTP API quickstart](https://docs.turso.tech/sdk/http/quickstart)

| Question | Answer |
|---|---|
| Free tier | **Yes — "Free", $0/month:** 100 databases, **5 GB storage**, **500 million rows read/month**, **10 million rows written/month**, 3 GB monthly syncs, 1-day point-in-time restore |
| SQLite compatibility | libSQL "is a fork of SQLite… **fully backwards compatible with SQLite**… maintains the same file format, the same API, and full backwards compatibility" |
| Connection model | **HTTP API**: `POST https://[db]-[org].turso.io/v2/pipeline`, JSON body `{"requests":[{"type":"execute","stmt":{"sql":"…"}}, {"type":"close"}]}`, `Authorization: Bearer <token>` |
| Bound parameters | **Positional `?` placeholders** with an `args` array of `{type, value}` objects; named `:name`/`$name`/`@name` also supported |
| Idle behaviour | **Contradictory — see below** |

**Two findings here are unusually good for this project:**

1. **The `?` placeholder style carries over unchanged.** Every `execute()` in Warrant uses `?` (enforced by test T20). Turso's HTTP API takes positional `?` args. The SQL strings themselves would not need rewriting.
2. **The HTTP API is callable from `urllib.request` + `json`, both stdlib.** This is the only hosted database found that could be reached without adding a third-party dependency.

**[CONTRADICTION — flagged, not resolved]** on idle behaviour:

- One search-surfaced claim: "Databases get archived after 10 days of inactivity for users on a free plan", with an [Unarchive Group API](https://docs.turso.tech/api-reference/groups/unarchive) endpoint existing to reverse it — the existence of that API endpoint is itself corroborating evidence that archiving is real.
- A second search-surfaced claim: free-tier databases "may scale to zero after one hour of inactivity" and scale back "usually completely invisible to users except for added latency on the initial request".
- A third: "databases now stay responsive at all times, regardless of how long they've been inactive — a feature previously only available on paid plans."

All three came from search result summaries; **I did not fetch a single primary Turso page stating the current idle policy.** The three are mutually inconsistent about whether free databases sleep at all, and if so after 1 hour or 10 days. This needs a primary fetch of Turso's current docs before anyone relies on it. See Appendix A.

**The disqualifier is §0.1, not the free tier.** ~1,400 statements per page render, each an HTTPS round-trip to Turso, is not a page load. Turso's `requests` array does allow batching multiple statements in one call, so a restructured `scoring.py` could work — but restructuring `scoring.py` is exactly the redesign this brief excludes, and it is the module the explainability invariant lives in.

**Where Turso *would* win: as a durability layer, not the live query path.** [INFERENCE] That is a design idea, not a research finding, and I am naming it only so the design stage knows the option exists.

### 3.4 Cloudflare D1

**[VERIFIED]** — [D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/) and [D1 query REST API](https://developers.cloudflare.com/api/resources/d1/subresources/database/methods/query/)

| Question | Answer |
|---|---|
| Free tier | **Yes** (Workers Free): **5 million rows read/day**, **100,000 rows written/day**, **5 GB storage total** |
| Paid | First 25 bn rows read/month included, then $0.001/million; first 50 m rows written/month, then $1.00/million; first 5 GB storage, then $0.75/GB-mo |
| SQLite compatibility | SQLite-based |
| Connection model | Workers binding, **or** REST: `POST /accounts/{account_id}/d1/database/{database_id}/query` with `sql` and optional `params` array. Supports batching: "Supports multiple statements, joined by semicolons, which will be executed as a batch." |
| Idle | Scale-to-zero billing; no compute idle charge |

**The 100,000 rows written per day free limit is the binding constraint, and it is severe for Warrant specifically.** From §0.1, one `/queue` render writes roughly 1 `score_runs` row + 53 `scores` rows + several hundred `reasons` rows + a `reason_evidence` row per contributing event. Call it 600–1,500 written rows per page view. **[INFERENCE]** That is somewhere between **65 and 165 page views per day** before the free write limit is exhausted — and `/account/{id}` re-runs the whole thing too (documented deviation #10 in `README.md`), so every detail-page click costs another full run.

That is a genuinely small number for a demo link being circulated, and it is a direct consequence of Warrant's "write a full run on every page view" pattern, which `STATUS_REPORT.md` §6 already flags as "fine for a demo, not a production pattern". D1's free tier is where that pattern first meets a hard wall.

Same round-trip problem as Turso applies to the REST path.

### 3.5 CockroachDB

**[VERIFIED]** — [Cockroach Labs pricing](https://www.cockroachlabs.com/pricing/)

- **Basic** plan (formerly Serverless): **"50 million RUs and 10 GiB storage free per month"**, starts at "$0/month", no credit card required, "smaller, bursty workloads up to 30K RU/sec".
- SQLite compatibility: **none**. CockroachDB speaks the **Postgres wire protocol**, so it inherits every Postgres breakage in §4.1 *plus* CockroachDB's own divergences from Postgres.

**[UNVERIFIED]** I did not verify CockroachDB Basic's idle/suspend behaviour or wake latency. See Appendix A.

**Verdict:** the most generous free storage allowance found (10 GiB), but strictly worse than Neon for this project — same Postgres migration cost, additional dialect divergence on top, and no compensating advantage for a 240-account demo.

### 3.6 PlanetScale — **free tier killed, and it has not come back**

**[VERIFIED, primary]** — [Deprecating the Hobby plan](https://planetscale.com/changelog/deprecating-hobby):

> "Our Hobby plan will be retired on **April 8th, 2024**."
> "As of **March 6th, 2024**, you are no longer able to create new Hobby databases."

**[VERIFIED]** — [PlanetScale pricing](https://planetscale.com/pricing) as fetched today lists Postgres and Vitess SKUs only. The cheapest entry is **Postgres EBS non-HA at $5/month**; HA starts at $15/month; Vitess starts at $39/month. **No free tier appears on the page.**

So: killed April 2024, still dead in August 2026, cheapest entry $5/month. Also MySQL/Vitess or Postgres — **no SQLite compatibility** either way.

**Verdict:** eliminated. This is the case the brief asked me to verify and date, and the primary changelog confirms it.

### 3.7 Database summary

| DB | Free 2026? | SQLite-compatible? | Connection | Pure-Python/stdlib reachable? | Sleeps? |
|---|---|---|---|---|---|
| **Turso/libSQL** | **Yes** — 5 GB, 500 M reads, 10 M writes/mo | **Yes — fork, same file format & SQL** | HTTP `/v2/pipeline`, `?` params | **Yes — `urllib`+`json`** | **Contradictory (see §3.3)** |
| **Cloudflare D1** | Yes — 5 GB, 5 M reads/day, **100 k writes/day** | Yes (SQLite-based) | Workers binding or REST | Yes — `urllib`+`json` | Scale-to-zero |
| **Neon** | Yes — 0.5 GB, 100 CU-hrs | No (Postgres) | PG wire | **No** — needs a driver | **5 min**, wake **"a few hundred ms"** |
| **Supabase** | Yes — 500 MB, 2 projects | No (Postgres) | PG wire or PostgREST | PostgREST yes; but SQL must be rewritten | **Paused after 1 week** (manual restore) |
| **CockroachDB** | Yes — 50 M RUs, 10 GiB | No (PG wire + own dialect) | PG wire | No | Unverified |
| **PlanetScale** | **No — Hobby retired 8 Apr 2024** | No | MySQL/PG wire | No | n/a |

---

## 4. The SQLite-compatibility question, against Warrant's actual SQL

This section is grounded in files I read in full: `db/schema.sql` (228 lines, 12 tables), `warrant/db.py`, `warrant/scoring.py`, `warrant/queue.py`, `warrant/metrics.py`.

**One large piece of good news first.** I searched every query site I read for SQLite-specific date functions — `julianday`, `strftime`, `date()`, `datetime()`. **There are none.** All decay arithmetic, age calculation and expiry comparison happens in Python (`warrant/timeutil.py`, added as deviation #6 precisely to centralise this). The single worst source of Postgres-migration pain in a typical SQLite codebase is simply absent here.

### 4.1 Postgres (Neon / Supabase / CockroachDB) — concrete breakages

| # | Breakage | Where | Severity |
|---|---|---|---|
| 1 | **`INTEGER PRIMARY KEY` is not autoincrementing in Postgres.** In SQLite it aliases `rowid` and auto-assigns. In Postgres it is a plain integer PK that will throw a not-null violation on insert. | **All 12 tables** in `schema.sql`. Needs `GENERATED ALWAYS AS IDENTITY` or `bigserial`. | **High** — silent design assumption, loud runtime failure |
| 2 | **`cursor.lastrowid` does not exist.** Postgres drivers require `INSERT … RETURNING <pk>`. | **At least 5 sites**: `queue.py` L116 (`create_adjustment`), L229 (`score_runs`), L273 (`scores`), L289 (`reasons`); plus `feedback.py`'s dispute insert. Every one of these feeds a foreign key on the next line. | **High** |
| 3 | **`?` placeholders → `$1, $2, …`** (or `%s` for psycopg). | **Every `execute()` in the codebase.** Roughly 40+ sites across `scoring.py`, `queue.py`, `metrics.py`, `feedback.py`, `app.py`. Note this does *not* break test T20, which detects f-strings and concatenation, not placeholder style — so the test will keep passing while every query is rewritten. | **High volume, low difficulty** |
| 4 | **Unaliased subquery in `FROM` is a syntax error in Postgres.** SQLite permits `FROM (SELECT …)`; Postgres requires `FROM (SELECT …) AS t`. | **4 sites in `metrics.py`**: L37–39, L41–43, L50–52, L54–56 — all of the form `SELECT COUNT(*) AS n FROM (SELECT DISTINCT rep_id, account_id FROM task_events WHERE …)`. | Medium — trivial fix, but a hard failure, and `/metrics` is a whole page that would 500 |
| 5 | **`PRAGMA foreign_keys = ON` is not Postgres.** | 3 sites: `schema.sql` L6, `db.py` L56 (`connect`), `db.py` L64 (`apply_schema`). Postgres enforces FKs unconditionally, so the *behaviour* is preserved by deleting the lines. | Low |
| 6 | **`executescript()` is a `sqlite3` method.** | `db.py` L63. Postgres drivers vary; psycopg can execute a multi-statement string, but only after breakage 5 is removed. | Low |
| 7 | **`REAL` means different things.** SQLite `REAL` is an 8-byte IEEE double. Postgres `real` is **single-precision `float4`** (~6 significant digits). | `signal_types.base_weight`, `max_contribution`, `half_life_days`; `scores.points`, `points_before_adjustment`, `data_completeness`; `reasons.points`, `points_before_adjustment`, `share_of_abs_total`; `reason_evidence.contribution`; `score_runs.anchor_points`; `signal_events.magnitude`. **Must become `double precision`.** | **High and subtle.** T07 asserts `sum(reason points) == score.points` exactly. `reason_evidence.contribution` is stored `round(…, 4)` (`queue.py` L290). Single-precision rounding is exactly the kind of thing that turns an exact-equality test into an intermittent failure — and that test *is* the product's central claim. |
| 8 | **`sqlite3.Row` row factory.** Postgres drivers return tuples by default; column-name access needs `dict_row`/`RealDictCursor`. | `db.py` L55, and **every** `row["column"]` access in the codebase. | Medium |
| 9 | **`dict(conn.execute(...).fetchall())` relies on `sqlite3.Row` unpacking as a 2-tuple.** | `metrics.py` L122, L128, L134, L138, L142 — five dict comprehensions building `{signal_type_id: count}`. Under a `dict_row` factory these become dicts-of-dicts and the code silently produces wrong lookups rather than raising. | **High** — silent wrong output on `/metrics` |
| 10 | **Third-party driver required.** `psycopg`/`psycopg2` are C extensions; `pg8000`/`asyncpg` are pure Python but still third-party. | Ends stdlib-only. Breaks `test_every_python_file_imports_only_stdlib_or_local`. | **Architectural** |
| 11 | Dynamic typing / boolean columns. `INTEGER … CHECK (x IN (0,1))` with Python `1`/`0` bound. | Survives if columns stay `integer`. Binding Python `True` would break. Code binds literal `1`/`0` throughout, so this is a **non-issue** — worth stating because it is the usual first worry. | None |
| 12 | ISO-8601 TEXT with string comparison. `occurred_at <= ?`, `expires_at > ?`, `MAX(occurred_at)`. | **Survives**, if columns stay `text`. `'YYYY-MM-DDTHH:MM:SSZ'` is fixed-width ASCII, so lexicographic order equals chronological order in any sane collation. **[INFERENCE]** — collation-dependent in principle; `C` or `en_US.UTF-8` both give the right answer for this character set. Do not "helpfully" convert these to `timestamptz`; that would be a much larger change. | Low, but do not touch it |
| 13 | `CHECK` constraints, including multi-column ones and `length(note) <= 280`. | **Survive.** Postgres supports table-level CHECKs and has `length()` for text. | None |

**Migration effort estimate for Postgres: 2–4 days of focused work, and a genuine risk to T07.** [INFERENCE] The mechanical parts (placeholders, identity columns, `RETURNING`, subquery aliases) are high-volume but low-difficulty. The parts that worry me are #7 (float precision against an exact-equality test that is the product's headline claim) and #9 (a silent-wrong-answer failure mode). Plus the architectural cost of #10, which is not a day of work but a permanent change to what this codebase is.

### 4.2 libSQL / Turso

**Drop-in for the SQL. Not drop-in for the access layer.**

| Aspect | Assessment |
|---|---|
| Schema | **No change.** libSQL "maintains the same file format, the same API, and full backwards compatibility" with SQLite [VERIFIED, §3.3]. `INTEGER PRIMARY KEY`, `CHECK`, `REAL`, TEXT timestamps all behave identically. |
| Query strings | **No change.** `?` positional placeholders are supported by the HTTP API [VERIFIED]. |
| Driver | Either the official `libsql-client` (third-party, breaks stdlib-only) **or** a hand-written HTTP client using `urllib.request` + `json` against `/v2/pipeline` (stdlib, ~80–150 lines). |
| `cursor.lastrowid` | Not available over HTTP. Needs `RETURNING` or `last_insert_rowid()`. **5+ sites** (same list as Postgres breakage #2). |
| `PRAGMA foreign_keys` | **[UNVERIFIED]** — I did not confirm whether Turso's hosted service honours a per-connection `PRAGMA foreign_keys = ON` over HTTP, or enforces FKs by default. This matters: `db.py`'s docstring says "PRAGMA foreign_keys = ON is not optional — several cascade behaviours in DESIGN_SPEC.md §7 depend on it." See Appendix A. |
| Transactions | Over HTTP, a transaction must be expressed as a batch within one `requests` array, or held open across calls with an explicit stream. `queue.py`'s `build_run()` does one `conn.commit()` after ~600 writes (L246) — that is one long transaction that would have to become a batch. |
| **Round-trips** | **The blocker.** ~1,400 statements per render (§0.1). Batching in the `requests` array is possible but requires restructuring `scoring.py`'s per-signal-type query loop. |

**Migration effort estimate: 1–2 days for a naive port that works but is unacceptably slow; the fast version requires restructuring `scoring.py`, which is a redesign, not a port.** [INFERENCE]

This is the frustrating result of the research: **Turso is by far the most SQL-compatible hosted database, and Warrant's architecture is the one that benefits from it least**, because the thing Warrant does most is issue many small queries in a tight loop.

### 4.3 Cloudflare D1

| Aspect | Assessment |
|---|---|
| SQL dialect | SQLite-based [VERIFIED, §3.4]. Schema and query strings largely survive. |
| Access model | Workers binding (requires a Worker, which cannot run Warrant — §2.8) **or** the REST query API [VERIFIED]. From a Python backend, only the REST path is available, and every statement is an HTTPS call to Cloudflare's API. |
| Batching | The REST API "Supports multiple statements, joined by semicolons, which will be executed as a batch" [VERIFIED] — but that is statement-string concatenation, which sits badly with `?` parameter binding across statements, and with T20's whole purpose. |
| **Write limit** | **100,000 rows written/day on free** [VERIFIED]. At an estimated 600–1,500 written rows per page render [INFERENCE, §3.4], that is **~65–165 page views/day**. |
| `lastrowid` | Not available. Same 5+ sites. |

**Migration effort: comparable to Turso, plus the write-quota problem, plus a worse batching story.** [INFERENCE] Strictly dominated by Turso for this use case.

### 4.4 The option the compatibility analysis actually favours

**Keep SQLite. Move the file.**

If the Python process and the SQLite file are on the same machine, **zero** of §4.1's thirteen breakages apply, `sqlite3` stays in the stdlib, T20 and the stdlib-only test keep meaning what they mean, and T07's exact-equality assertion is not put at risk by a float precision change.

The cost of that choice is **durability**, and §5 and §6 address it directly.

---

## 5. Cold starts and demo credibility

### 5.1 The measured numbers

| Host | Wake latency | Source |
|---|---|---|
| **Render free** | **"about one minute"** | **[VERIFIED]** — [Render Docs](https://render.com/docs/free), Render's own wording |
| **Neon free** | **"within a few hundred milliseconds"** | **[VERIFIED]** — [Neon scale-to-zero](https://neon.com/docs/introduction/scale-to-zero) |
| Render free (third-party reports) | "20–60 seconds"; "up to 50 seconds"; "approximately 60 seconds" | **[UNVERIFIED]** — blog/aggregator content surfaced by search, not primary. Consistent with Render's own "about one minute", which is the number to quote |
| Supabase free | **Not a cold start.** Paused after 1 week of inactivity; requires manual restore | **[VERIFIED]** — [Supabase pricing](https://supabase.com/pricing) |
| HF Spaces free | Sleeps after "a period of time"; **duration not stated** | **[VERIFIED]** that it sleeps; **[UNVERIFIED]** how long |
| Turso free | Contradictory: never / 1 hour / 10 days | **[UNVERIFIED]** — see §3.3 |
| PythonAnywhere free | No documented sleep | **[INFERENCE]** |

### 5.2 What a 50-second wait does to *this* demo specifically

I want to be careful here, because "cold starts hurt demos" is a generality and this document is supposed to deal in specifics.

The specific problem is this. Warrant's entire pitch, per `STATUS_REPORT.md` §1 and the announcement, is: **the reasons are the score, and you can check the numbers.** Its research foundation is that reps ignore scores they cannot verify. The demo is asking a sceptical audience to extend trust to a system on the strength of its transparency.

A rep clicks a link. Nothing happens for 50 seconds. There is no spinner, because there is no page yet — the browser is waiting on a TCP connection to a container that is being created. Then a queue appears.

The failure is not that they are annoyed. It is that **the first thing the system does is behave in a way the user cannot account for.** They have no model for why it took 50 seconds; nothing on screen explains it; and the very next thing the page does is ask them to believe a set of numbers on the grounds that the system is legible. `README.md` records that the design refuses to show a confidence percentage because it would be "a second uncalibrated number on a page that already spent its credibility budget on the first one". A 50-second unexplained wait spends that budget before the page renders.

**[INFERENCE]** — this is reasoning, not measurement. I have not tested it with a rep, and neither has anyone else on this project (`STATUS_REPORT.md` §6: "The trust claim itself is untested"). I flag it as the strongest argument in this document for spending $5–7/month rather than $0.

There is a second-order problem that is purely mechanical: **a demo link is clicked at unpredictable times.** Render spins down after 15 minutes of no traffic. Any viewer who is not the second person to click within a 15-minute window pays the full wake cost. In practice that means **most viewers of a circulated link hit a cold container**, not a minority of them.

### 5.3 Mitigations, honestly assessed

**1. Keep-alive pings (e.g. an external uptime monitor hitting the URL every 14 minutes).**

- **Does it work?** [INFERENCE] Yes, mechanically. Render spins down on "no incoming traffic for 15 consecutive minutes" [VERIFIED], so traffic every 14 minutes prevents it.
- **Does it fit the free quota?** [INFERENCE] Marginally. A service kept awake 24/7 consumes ~730 instance-hours in a 31-day month against Render's 750/month allowance [VERIFIED]. That works for **exactly one** free service, with ~20 hours of headroom, and only if nothing else in the workspace consumes free hours. Exceeding it means "Render suspends all of your Free web services until the start of the next month" [VERIFIED] — a cliff, not a throttle.
- **Do the terms forbid it?** **[UNVERIFIED — and this is an important gap.]** I did not find an explicit Render prohibition on keep-alive pings, and I did not find explicit permission. What I did find is a Render changelog entry announcing that WebSocket messages now count as keep-alive traffic, which suggests Render treats "what keeps a service awake" as a product decision rather than an abuse vector. **That is suggestive, not permission.** Anyone writing a runbook that recommends pinging should read Render's terms of service directly first. See Appendix A.
- **Honest verdict:** it converts a per-view 60-second penalty into a permanent consumption of ~97% of the monthly free allowance, with a hard cliff at the end and an unverified terms position. It is a real mitigation with real costs, not a free win.

**2. Pay for always-on.** Fly.io ($0.15/GB/month volumes plus machine cost) or Railway Hobby ($5/month, 5 GB volume) [both VERIFIED, §2.2/§2.3]. This buys no cold start **and** a persistent disk, which solves the §4 durability problem at the same time. It is the honest answer if the demo matters.

**3. A static skeleton on Pages that loads instantly while the backend wakes.** [INFERENCE] This is the mitigation that costs nothing and is uniquely available *because* the frontend is on GitHub Pages. Pages is a CDN-served static host with no cold start; a page can render its explanation of what Warrant is, and what is about to load, in milliseconds. The user then sees "waking the demo server, this takes about a minute on the free tier" instead of a blank tab.

This does not make it faster. It makes it **accounted for** — which, per §5.2, is the actual problem. It is available under frontend option A (a JS shell can show its own loading state) and under option C only with a visible wrapper around the iframe. It is **not** available under option B, where the click leads straight to a stalled navigation.

**[INFERENCE]** This is the strongest argument I found *for* putting real content on the Pages side rather than treating Pages as a redirect: the static host's zero cold start is the mitigation for the dynamic host's cold start.

**4. Do nothing and accept it.** Defensible if the demo is always driven live by someone who can warm it up 60 seconds before the call. Indefensible for a link sent by email.

---

## 6. Recommendation

### 6.1 Primary: Render free web service, SQLite on the ephemeral disk, regenerated at boot

**Backend:** Render free web service, running `app.py` unchanged except for binding `0.0.0.0` and reading the platform `$PORT`.
**Database:** SQLite, exactly as today — `data/unify.db`, in the container, in-process.
**Seeding:** run `python seed_db.py` at container start, before `app.py`.
**Frontend:** GitHub Pages from a `/docs` folder on the default branch, serving a static page that renders instantly and then reaches the backend. Which of §1.6's options A/B/C is the design stage's call; **C is the cheapest and A is the most conventional.**

**The reasoning turns on one fact that is unusual to this project.** An ephemeral filesystem normally disqualifies SQLite outright, because the database vanishes on restart. Here it does not, because **the corpus is deterministically regenerable**: `seed_db.py` runs under `random.seed(20260811)` and `README.md` states running it twice produces byte-identical `accounts`, `people` and `signal_events` (test T01). A restart does not lose the demo. It restores it, byte for byte.

**What this buys:**

- **Zero changes to the SQL.** All thirteen §4.1 breakages avoided. T07's exact-equality assertion is not put near a float precision change.
- **Stdlib-only survives.** No driver, no `requirements.txt`. `test_every_python_file_imports_only_stdlib_or_local` keeps meaning what it means.
- **The live-query guarantee survives untouched.** `score_account()` still hits a local file at request time. The three tests that mutate the database behind the application's back still work, because there is still a local file to mutate.
- **The runbook is executable by a non-expert through a browser.** Render's dashboard connects a GitHub repo and deploys; GitHub Pages is a dropdown in repo Settings. No `docker`, no `flyctl`, no `psql` — none of which are installed [per the environment facts].
- **$0.**

### 6.2 What it costs — named, not hidden

**1. Rep-generated data does not survive a restart.** This is the real price and it should be stated in the runbook in plain words. On every spin-down/redeploy, the container loses: `disagreements`, `queue_adjustments`, `score_runs`, `scores`, `reasons`, `reason_evidence`, `task_events`. Concretely: **a dispute a rep filed yesterday is gone today**, and `/metrics` resets to its seeded baseline.

How bad is that? It depends on a judgement I am not in a position to make. Against it: the disagreement loop is the heart of the feature (`STATUS_REPORT.md` §4 walks it end to end), and a system that forgets a rep's disagreement is enacting the exact failure the design exists to prevent — "if disagreement changes nothing, reps stop registering it within weeks" (`feedback.py`'s own docstring). In favour: this is a demo of synthetic data, every dispute is visible on the very next render, and within a session nothing is lost. **The design stage should decide this explicitly rather than inherit it.**

**2. ~60-second cold start for most viewers.** Per §5.2, this is a credibility cost, not just a latency cost. Mitigate with the static Pages skeleton (§5.3 item 3) at minimum.

**3. 750 free instance-hours/month, with a cliff.** Fine if the service sleeps normally. Not fine if it is pinged 24/7 *and* anything else in the workspace uses free hours.

**4. Do not use Render's free Postgres.** It expires 30 days after creation [VERIFIED, §2.1]. If the design stage later wants durability on Render, that is the wrong instrument.

**5. `app.py` must be checked for response headers** before frontend option C is chosen (§1.6).

### 6.3 The credible alternative: Railway Hobby or Fly.io at ~$5/month, SQLite on a persistent volume

**Same architecture, one difference: the SQLite file lives on a mounted volume, and the instance does not sleep.**

- Railway Hobby: **$5/month including $5 of usage, 5 GB volume storage** [VERIFIED, §2.3].
- Fly.io: pay-as-you-go, **volumes at $0.15/GB/month** [VERIFIED, §2.2].

**This fixes both of §6.2's top two costs at once.** Disputes persist. There is no cold start. Nothing else about the recommendation changes — still SQLite, still stdlib-only, still zero SQL migration.

**What would make me pick this instead:** any of the following being true.

1. **The demo link will be sent to people rather than driven live.** Then most viewers hit a cold container, and §5.2's argument bites hardest.
2. **Anyone wants to look at `/metrics` or a filed dispute more than a few hours after filing it.** Ephemeral storage makes that impossible, and it makes it impossible *silently*.
3. **The audience is external.** A prospect who waits a minute for a blank tab has already formed a view.
4. **$5/month is not a real constraint.** For a project whose stated subject is whether a sales team trusts a tool, I would want a strong reason not to spend it.

**What counts against it:** it requires a credit card, which the pipeline does not have and the user may not want to attach to a prototype. Railway's dashboard is browser-driven, which fits the constraint; Fly.io leans on `flyctl`, which is not installed and adds a step a non-expert can get wrong.

### 6.4 The second alternative, for a different set of priorities: PythonAnywhere free

**Why it is on the list at all:** it is the **only free option found with a persistent disk** (512 MiB) [VERIFIED, §2.9]. That means disputes survive, on $0, which is the thing §6.2 cost #1 gives up.

**What would make me pick it:** if durability of rep feedback is judged non-negotiable *and* spending money is judged non-negotiable. That combination points here and nowhere else.

**What counts against it, and it is substantial:**

1. **`app.py` must become a WSGI application.** [INFERENCE — see Appendix A] Same rework as Vercel would need. That is real work on the one file that routes everything.
2. **100 CPU-seconds/day.** At ~0.21s per queue render, roughly 475 renders/day of budget [INFERENCE]. Adequate for a controlled demo, not for a widely-circulated link.
3. **The web app expires and needs a manual click to renew**, on an interval the sources disagree about (1 month vs 3 months — §2.9). An unattended demo goes dark.

### 6.5 What I explicitly recommend against

- **Any Postgres path (Neon, Supabase, CockroachDB) for this codebase, now.** Thirteen concrete breakages, a mandatory third-party driver that ends stdlib-only, a silent-wrong-answer failure mode on `/metrics` (§4.1 #9), and a float-precision change (§4.1 #7) sitting directly under the exact-equality test that carries the product's central claim. The right time for this migration is when Warrant needs concurrency and real scale — which `STATUS_REPORT.md` §6 already identifies as a future requirement — not when it needs a URL.
- **Supabase specifically**, additionally because of the 1-week pause-with-manual-restore [VERIFIED, §3.2]. For a link that gets clicked at unpredictable intervals, that is a broken demo, not a slow one.
- **Cloudflare Workers as the backend.** No disk, non-functional `threading`, Pyodide/WASM, beta [all VERIFIED, §2.8].
- **Hugging Face Spaces.** Docker Spaces require a paid plan to create [VERIFIED, §2.5].
- **Netlify** (no Python) and **Deta** (shut down 17 Oct 2024) [VERIFIED, §2.7/§2.10].
- **Turso or D1 as the live query path without restructuring `scoring.py`.** ~1,400 round-trips per page render (§0.1). Both are excellent SQLite-compatible databases; the incompatibility is with Warrant's query pattern, not its SQL.
- **Anything requiring a credential this pipeline does not have.** Nothing above can be provisioned by stages 2–4. Every one of these is a recommendation *for a runbook a human executes*, not for an agent to carry out.

---

## Appendix A — What I could not verify

Listed so the gaps are visible rather than papered over.

1. **Render HTTPS on `*.onrender.com`.** Universally true in practice and assumed throughout, but I did not fetch a Render page containing a sentence stating it. Low risk; still unverified.
2. **Render: whether a long-running non-WSGI Python process is supported.** Inferred from Render's service model (it runs a start command and health-checks a port). I did not fetch a page confirming a raw `http.server` process is acceptable. **This should be verified before the runbook is written**, because the entire primary recommendation rests on it.
3. **Render's terms of service on keep-alive pings.** Found no explicit prohibition and no explicit permission. §5.3 item 1 depends on this. Read [Render's ToS](https://render.com/terms) directly before recommending pinging.
4. **`app.py`'s server binding and response headers.** I read lines 1–80 only. The `0.0.0.0`/`$PORT` change (§2.1) and the framing assumption (§1.6 option C) both rest on inference from `README.md` rather than on the code.
5. **`warrant/reasons.py` query sites.** Not counted in §0.1's ~1,400. The real figure is higher.
6. **Vercel Hobby maximum function duration.** The fetched page's callout rendered with the numbers stripped ("The standard Python bundle size limit is  uncompressed"). Moot given Vercel is eliminated on other grounds.
7. **Cloudflare Workers: whether `sqlite3` is importable.** Not named in the 14-module exclusion list I retrieved, and not confirmed present. Moot — there is no disk (§2.8).
8. **HF Spaces free-tier sleep duration.** Confirmed that Spaces sleep; no number given on the page I fetched.
9. **Turso's current idle/archiving policy.** Three mutually inconsistent claims (never sleeps / 1 hour / 10 days), all from search summaries, none from a primary page fetch. See §3.3. The existence of an [Unarchive Group API](https://docs.turso.tech/api-reference/groups/unarchive) is corroborating evidence that archiving is real, but does not establish the interval or whether it still applies.
10. **Turso: whether `PRAGMA foreign_keys = ON` is honoured over the HTTP API.** Material, because `db.py` states several §7 cascade behaviours depend on FK enforcement.
11. **Koyeb's free compute tier.** Koyeb's own pricing page shows none; a third-party aggregator says one exists but is closed to new signups after a February 2026 Mistral AI acquisition. I did not fetch a primary announcement of either the acquisition or the closure. See §2.4.
12. **CockroachDB Basic idle/suspend behaviour and wake latency.** Not checked.
13. **Railway:** whether trial deployments serve public traffic; the date Railway's older free Starter plan was removed.
14. **PythonAnywhere free web app expiry interval.** Help page says 1 month; search-surfaced forum/blog content says 3 months. Genuine contradiction, unresolved. See §2.9.
15. **PythonAnywhere: that it is WSGI-only.** Inferred from the platform model, not from a fetched statement.
16. **Deta's own shutdown announcement.** Corroborated across four search-surfaced sources including Deta's X account, but not fetched directly.
17. **The exact Chrome console strings** for CORS and mixed-content failures (§1.4, §1.5). The mechanisms are verified via MDN; the literal wording is recall and should be reproduced before being quoted in a runbook.
18. **The claim in §5.2** that a 50-second wait damages trust in this demo specifically. Reasoning from the project's own stated premises, not evidence. Nobody has tested Warrant's trust claim with a rep at all.

No page returned a 403 during this session. Two returned 404 for URLs I guessed at ([a GitHub Pages HTTPS path under `configuring-a-custom-domain/`](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/securing-your-github-pages-site-with-https) and `https://docs.turso.tech/pricing`); in both cases I found the correct URL by search and fetched that instead. Render's `/pricing` page and Hugging Face's `/pricing` page both returned navigation chrome rather than pricing content to the fetcher; I used their documentation pages instead, which is why Render's figures are cited to `render.com/docs/free` rather than to the pricing page.

---

## Appendix B — Sources fetched

**GitHub Pages**
- https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits
- https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site
- https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site
- https://docs.github.com/en/pages/getting-started-with-github-pages/about-github-pages
- https://docs.github.com/en/pages/getting-started-with-github-pages/securing-your-github-pages-site-with-https *(via search; content quoted from the search result, page not fetched directly — the URL I first guessed 404'd)*
- https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features *(surfaced by search, not fetched)*

**Browser behaviour**
- https://developer.mozilla.org/en-US/docs/Web/Security/Mixed_content
- https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS

**Backend hosts**
- https://render.com/docs/free
- https://render.com/changelog/free-web-services-now-remain-active-while-receiving-websocket-messages *(surfaced by search, not fetched)*
- https://fly.io/docs/about/pricing/
- https://docs.railway.com/reference/pricing/plans
- https://www.koyeb.com/pricing
- https://huggingface.co/docs/hub/spaces-overview
- https://huggingface.co/pricing
- https://vercel.com/docs/functions/runtimes/python
- https://docs.netlify.com/build/functions/get-started/
- https://docs.netlify.com/build/functions/lambda-compatibility/
- https://developers.cloudflare.com/workers/languages/python/
- https://developers.cloudflare.com/workers/languages/python/stdlib/
- https://www.pythonanywhere.com/pricing/
- https://help.pythonanywhere.com/pages/FreeAccountsFeatures/

**Databases**
- https://neon.com/docs/introduction/plans
- https://neon.com/docs/introduction/scale-to-zero
- https://supabase.com/pricing
- https://turso.tech/pricing
- https://docs.turso.tech/libsql
- https://docs.turso.tech/sdk/http/quickstart
- https://docs.turso.tech/api-reference/groups/unarchive *(surfaced by search, not fetched)*
- https://developers.cloudflare.com/d1/platform/pricing/
- https://developers.cloudflare.com/api/resources/d1/subresources/database/methods/query/
- https://www.cockroachlabs.com/pricing/
- https://planetscale.com/changelog/deprecating-hobby
- https://planetscale.com/pricing

**Deta shutdown (search-surfaced, not fetched individually)**
- https://x.com/detahq/status/1830605654920466888
- https://news.ycombinator.com/item?id=41426388
- https://github.com/WebCrateApp/webcrate/discussions/90

**Local files read**
- `README.md`, `STATUS_REPORT.md`, `db/schema.sql`, `warrant/db.py`, `warrant/scoring.py`, `warrant/queue.py`, `warrant/metrics.py`, `warrant/feedback.py` (L1–60), `app.py` (L1–80), `warrant/reasons.py` (L1–70)

---

*Researcher agent (AI-generated). Stage 1 of 4. Nothing in this document has been deployed or tested. Every free-tier claim was checked against a live page during this session or is explicitly labelled unverified.*
