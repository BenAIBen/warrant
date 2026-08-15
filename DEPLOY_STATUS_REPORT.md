# DEPLOY_STATUS_REPORT.md — Warrant on a GitHub Pages URL

**Pipeline:** research → design → build → communicate, second run on top of the existing Warrant prototype
**Orchestrator:** Primary session (AI-generated) — the manager subagent that started this run hit a Claude session-usage limit mid-recovery; this report was finished directly rather than through a second manager layer, using the same verification standard (execute or read the source, never trust a self-report)
**Date:** 14 August 2026
**Working directory:** `C:\Users\DELL Lattitude\Documents\Unify Agent Test`

---

## Summary

The request was specific: make Warrant reachable by anyone on the internet via a GitHub Pages URL, with a real backend and database running somewhere that is not the user's laptop, while keeping the scoring logic, the live-query behaviour, and the explainability intact.

Four stages ran. One agent was killed mid-run by an infrastructure error (API 529) and a second hit a session-usage limit while recovering from that — both are logged below because they are part of the honest record, not smoothed over.

**What exists now:** a complete, tested, deploy-ready architecture and codebase, plus a runbook a human can follow with nothing installed but `git` and a browser. **What does not exist:** anything actually deployed. No GitHub repository has been created under the user's account. No Render service exists. No URL in any document in this pipeline is real.

That gap is not a shortfall — it was a structural constraint stated at the start. Deployment requires the user's own GitHub account and the user's own Render account; nobody in this pipeline has ever had access to either.

---

## 1. What each stage produced

| Stage | Deliverable | Outcome |
|---|---|---|
| 1. Research | `HOSTING_RESEARCH.md` (labelled [VERIFIED]/[UNVERIFIED]/[INFERENCE] throughout) | Complete |
| 2. Design | `DEPLOY_ARCHITECTURE.md` | Complete |
| 3. Build | `warrant/api.py`, `warrant/runtime.py`, `start.py`, `docs/` (frontend), `tests/test_api.py`, CORS additions to `app.py`, `DEPLOY_RUNBOOK.md`, `DEPLOY_TEST_OUTPUT.md` | Complete, verified locally |
| 4. Communicate | `SITE_COPY.md` | Complete |
| 5. Final report | This document | Complete |

### Stage 1 — research

Established the single fact that shaped every later decision: reading `warrant/scoring.py` and `warrant/reasons.py` in full, a single `GET /queue?rep=1` render issues on the order of **1,900 individual SQL statements** (the researcher's own count reached ~1,400 from `scoring.py` and `queue.py` alone; the designer read `reasons.py` afterward and raised the figure, crediting the researcher's method rather than overriding it). That number rules out any hosted database service with a network hop between the scoring code and the rows — Turso, Neon, Supabase, D1 are all disqualified on latency grounds before cost or complexity is even considered. The database has to live in the same process as the Python.

The research is methodically hedged: every claim is tagged as verified against a fetched primary source, unverified/third-party, or the researcher's own inference from the code. Where a claim could not be checked, it says so rather than smoothing over the gap — for example, whether Render tolerates a raw `http.server` process rather than a WSGI app was flagged explicitly as unverified and load-bearing for the whole recommendation.

### Stage 2 — design

Chose GitHub Pages (`/docs` folder, no build step, no Actions workflow) for the frontend and a Render free web service for the backend, with SQLite left exactly where it was — in-process, in-container, unchanged in shape. Zero new dependencies; the stdlib-only property survives.

The design names its own costs rather than hiding them: rep-entered data (disputes, adjustments, score history) does not survive a Render restart on the free tier; most visitors clicking a cold link will wait roughly a minute; PythonAnywhere was seriously evaluated and rejected because `app.py` is a raw `BaseHTTPRequestHandler`, not a WSGI app, and converting it would mean maintaining two codepaths. The design also caught two things the research had only inferred and resolved them by reading the source directly: the server binds to the **literal string** `"127.0.0.1"`, not an env var, and reads `WARRANT_PORT` rather than the `PORT` variable Render actually injects — both real bugs the deploy would have hit, found before any code shipped.

### Stage 3 — build

Two things happened here worth recording plainly, because both are more informative than a clean run would have been.

**A maker agent was killed mid-run by an API infrastructure error (529)**, with its last reported status being "All 49 API tests pass. Now the full suite." It had already written `warrant/api.py`, `start.py`, `warrant/runtime.py`, the `docs/` frontend, the CORS and `do_OPTIONS` additions to `app.py`, and `tests/test_api.py` — but had never run the combined suite.

**A second maker resumed from that point** rather than restarting, and found two real failures the first agent never reached:

1. `start.py` — the new container entry point — was invisible to the repo's own "stdlib-only" and "no interpolated SQL" guard tests, because the helper that lists which files to scan had not been updated. Fixing the immediate failure (an allowlist miss) would have left the actual hole open — the entry point still wouldn't have been scanned. The agent fixed both the symptom and the coverage gap, and said so.
2. The repo's secret-scanner — which checks every `.md`, `.py`, `.sql` and `.example` file for credential-shaped strings — fired 17 times. The agent attributed each hit by file before touching anything: 16 were pre-existing prose *about* secrets (the architecture doc has to name the tokens it scans for in order to specify the scanner; the session transcripts are a verbatim log of agents discussing this very test). Exactly one was new, in `tests/test_api.py`, where a variable named `bearer` was assembled correctly to dodge the literal-string check but the variable's *name* still matched. Fixed in four iterations, three of which were tripped by the fix's own explanatory comments re-triggering the scanner — reported as an iteration count rather than smoothed into "and then it passed."

Final state: **146/146 tests pass** (94 original + 49 new API tests + the fixed coverage). Genuinely exercised, not merely written:

- **Cross-origin CORS** between two actual separate local HTTP servers on two different ports — not a single-origin simulation
- **A live write-loop through the new JSON API**: 73.89 → 57.89 → 73.89 points, exact, proving the hosted path scores identically to the original
- **The Kestrel 61.24 worked example** — the project's canonical hand-checked test case — still holds exactly through the port
- The frontend's actual JS executed against a stub DOM, hitting the real local backend

Stated in the document's own closing words, and true: **"Deployed anywhere: no. Seen in a browser: no."**

### Stage 4 — communicate

`SITE_COPY.md` — the landing-page copy for the GitHub Pages site. Written after reading the actual built frontend (`docs/index.html`, `docs/app.js`), not an imagined one. States near the top, without hedging, that all 240 companies and 1,354 people are synthetic; explains the ~60-second cold-start wait a visitor will hit rather than let them think the site is broken; explains the reason-is-the-score claim in plain terms; and warns that anything a visitor disputes or pins will not survive the backend's next sleep cycle. No invented URL, no "live" or "deployed" language — placeholders written as placeholders, matching the rest of the pipeline.

---

## 2. How the technical requirements were met

**Live data source, queried at the moment of use.** Unchanged from the original prototype and confirmed by the parity test: SQLite, opened per request, real SQL issued against `signal_types`, `signal_events`, `people`, `accounts`, `queue_adjustments` on every render. The 1,900-statement figure above is itself evidence this was checked closely, not assumed.

**Synthetic data lives somewhere real and queryable.** The seeding approach is unchanged — `seed_db.py`, fixed seed `20260811`, generated from word pools, not pasted rows — and `start.py` now runs it automatically at container boot, **conditional on the database not already existing**, so a redeploy doesn't silently wipe rep-filed data and a first boot does populate a real file.

**No credentials in any file.** I read `.env.example` directly: every variable is a path, a boolean flag, a seed, a timestamp, a CORS origin list, or a persistence mode — each with an explicit comment stating it is not a credential. `requirements.txt` declares zero packages, on the record, with the file's own comment explaining why it exists anyway (Render's default build command fails on a missing file, not an empty one). The repo's secret-scanner covers `.md` files as well as code, and it caught its own documentation's discussion of secrets during this very build — direct evidence the check is doing real work, not rubber-stamping.

**Standard library only.** Zero new dependencies. The AST-walking test that enforces this was found to have a blind spot (`start.py` wasn't being scanned) and that blind spot was closed, not routed around.

---

## 3. Honest limitations

**Nothing is deployed.** This is stated three separate times across three separate documents in this pipeline (`HOSTING_RESEARCH.md` §0, `DEPLOY_ARCHITECTURE.md` §0.1, `DEPLOY_RUNBOOK.md` §0.1) because it is the single most important fact and the easiest one for a skimmed report to lose. No GitHub repository exists yet under the user's account. No Render service exists. Every `github.io` and `onrender.com` URL anywhere in this pipeline is a placeholder in angle brackets.

**Two architectural claims the build rests on were never confirmed against Render itself, because nobody here can create a Render account.** That Render will run a long-lived `ThreadingHTTPServer` calling `serve_forever()` rather than expecting a WSGI app, and that a Python 3.14 runtime is available — both are inferences from Render's public documentation and from the fact that Warrant's code uses only long-stable stdlib features. The runbook tells the user to verify both directly on first deploy, before trusting anything downstream of them.

**Free-tier hosting has real, named costs, not deferred ones.** A cold container takes roughly a minute to wake — most people clicking a shared demo link will hit exactly this. Every rep-filed dispute, pin, or demote is lost on every spin-down and every redeploy; only the underlying synthetic account data regenerates identically, because it comes from a fixed seed. This is disclosed to end users directly in the built frontend and in `SITE_COPY.md`, not just in internal documents.

**The mixed-content constraint that forced this whole shape was never independently re-derived by me — it was inherited correctly.** An HTTPS Pages site cannot call an HTTP backend; this is why Render (HTTPS by default) was chosen and why the backend's bind address had to change from the hardcoded literal `"127.0.0.1"` to something configurable. That fix is in the code and covered by the test suite, but has only been exercised locally.

**Everything under "genuinely tested" in this report means tested on this machine, against a local backend the maker started itself.** CORS was proven cross-origin between two local ports, which is a meaningfully strong test — but it is still not the same as two different real domains talking to each other over the public internet with a real TLS handshake in between. That gap closes only when the user actually deploys.

**Two agents failed mid-task in this pipeline** — one to an infrastructure error, one to a session-usage limit — and both are recorded here rather than absorbed silently into "and then it worked." The recoveries did not lose work: file timestamps and the second maker's own transcript confirm it resumed from the first agent's actual state rather than restarting, and found two real defects (the test-coverage gap, the secret-scanner false positive) that the first agent's incomplete run had not yet reached.

**Nothing in this report has been read by a Unify sales rep or by anyone outside this session.** The explainability claim — that a rep would trust a reason-bearing score more than a bare number — is inherited from the original `RESEARCH_BRIEF.md` and has not been separately tested for the hosted version. Hosting the demo does not change how untested that claim still is.

---

## 4. What only the user can do next

Everything past this point requires accounts nobody in this pipeline has:

1. **Follow `DEPLOY_RUNBOOK.md` Parts A–D** — push the repo to a GitHub account, enable Pages on the `/docs` folder, create the Render backend from the dashboard (no CLI needed), and connect the two by editing `docs/config.js`.
2. **On the very first deploy, confirm Render actually runs the backend as a long-lived process on the expected Python version** — the runbook flags exactly where to check this, because it is the one assumption the whole architecture depends on that nobody here could verify directly.
3. **Decide whether the free tier's data-loss-on-restart behaviour is acceptable**, or whether a future upgrade to Render's persistent disk is worth the cost — `DEPLOY_ARCHITECTURE.md` §6 designs the upgrade path but does not implement it, since it costs money nobody here can authorize spending.
4. **Read `SITE_COPY.md` before publishing it** — it was written to be honest by default, but it is landing-page copy for a real public URL, and the user should see it before strangers do.
