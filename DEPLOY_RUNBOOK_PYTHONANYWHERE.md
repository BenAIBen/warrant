# DEPLOY_RUNBOOK_PYTHONANYWHERE.md — Warrant on PythonAnywhere, no card required

**Companion to:** `DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md` (the design),
`DEPLOY_TEST_OUTPUT_PYTHONANYWHERE.md` (the test evidence)
**Relationship to `DEPLOY_RUNBOOK.md`:** a second, independent path. That
document and the Render service it describes are untouched. Follow **this**
document instead of that one if you do not want to give a hosting provider a
card, or if you want rep-filed disputes to survive a restart.

---

## 0. Read this before you start

### 0.1 Why this document exists

Render's own free-tier documentation says a payment method is optional. In
practice, Render's live signup flow asked for a card anyway — a real
contradiction between what Render publishes and what it does, not something
this pipeline can resolve. Rather than accept that, this is a second,
complete path on a host whose free tier's own documentation states plainly:
*"no credit card is required"* for a limited free account
[VERIFIED — pricing/signup pages, `HOSTING_RESEARCH.md` §2.9].

**Nothing here has been deployed or tested against a real PythonAnywhere
account.** `DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md` §10 states exactly what
was verified against PythonAnywhere's own documentation, what was tested
locally against a real `wsgiref` server standing in for it, and — this
matters — that the WSGI-file-editing mechanism described below **has not
been confirmed on a free account specifically**, only against
PythonAnywhere's general documentation. **The first step below is to check
that for yourself, before doing anything else**, exactly because it is the
one thing this pipeline could not check for you.

### 0.2 What you will end up with

Two public URLs, same shape as the Render path but with different trade-offs:

| URL | What it is | Survives a restart? |
|---|---|---|
| `https://<your-username>.github.io/<your-repo>/` | The Pages frontend. Unchanged from the Render path — same files, same code. | n/a (static) |
| `https://<your-username>.pythonanywhere.com` | The backend — same `WarrantRoutes` logic as the Render path, served through PythonAnywhere's WSGI worker instead of a raw socket. | **Yes.** Disputes, pins and mutes survive a restart here, unlike on Render. |

Both are public, unauthenticated and world-readable, for the same reasons
`DEPLOY_ARCHITECTURE.md` §8.1 gives for the Render path (no credentials
anywhere in Warrant, nothing to authenticate to). The data is the same
synthetic 240-account corpus.

### 0.3 Costs you are accepting on this path — different from Render's, not absent

1. **The free web app expires and must be manually renewed.**
   [VERIFIED, re-checked 2026-08-15] PythonAnywhere's own help page:
   *"1 web app with 1 web worker and 1 month expiry."* If nobody renews it
   before then, **the site goes fully offline** — not a slow wake-up like
   Render's, a dead URL. **Put a reminder on your own calendar now**, for
   roughly three weeks from today, to log in and click the renewal control
   on the Web tab. (A three-month renewal cycle is mentioned in some
   secondary sources but was not confirmed by PythonAnywhere's own page in
   this pass — see `DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md` §0. Plan for one
   month; treat a longer visible countdown on the Web tab as a bonus.)
2. **One worker, so simultaneous visitors queue behind each other.**
   [VERIFIED] Free accounts get exactly one web worker; PythonAnywhere's own
   formula (`1 worker ÷ ~0.21s per queue render ≈ 4.8 renders/second`,
   `DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md` §5) means a handful of people
   clicking a link one after another is fine; several people clicking it in
   the same second will each wait a fraction of a second longer while the
   worker clears the queue. This is a materially milder failure mode than
   Render's — nothing about it takes the whole site down — and it was not
   measured against a real PythonAnywhere worker, only computed from their
   documented model.
3. **Rep-filed data is NOT reset back to the pristine demo on every restart,
   the way Render's is.** This is usually the point (§0.1) — but it means a
   demo you leave running and let other people click around in will
   accumulate disputes, pins and mutes over time, rather than resetting
   itself. `WARRANT_FORCE_RESEED=1` (§8 below) is the manual reset, the same
   destructive escape hatch `DEPLOY_ARCHITECTURE.md` §6.6 already documents
   for a persistent volume on the Render side.

### 0.4 What you need

- A GitHub account (same as the Render path, for Pages).
- **No credit card.** If PythonAnywhere's signup flow asks you for one
  anyway, that is the same kind of contradiction that sent you to this
  document in the first place — stop, and report back rather than proceeding
  on an assumption this pipeline could not verify.
- A modern browser. Nothing is installed locally; PythonAnywhere's Bash
  console (in-browser) is used instead of a local terminal.

---

## 1. The order of operations — simpler here than on Render, and why

`DEPLOY_RUNBOOK.md` §1 spends real effort on ordering because Render's URL is
**not predictable** until the service exists. **PythonAnywhere's free-tier
URL has no such problem**: it is always exactly
`https://<your-username>.pythonanywhere.com`, known the moment you finish
signing up — before you've created a web app, cloned anything, or written a
line of configuration. [VERIFIED, `HOSTING_RESEARCH.md` §2.9: *"1 web app…
at `<username>.pythonanywhere.com`"*]

The only real ordering constraint left is the same one-directional
dependency as before: **the WSGI file needs your Pages origin to set
`WARRANT_ALLOWED_ORIGINS` correctly**, so do Pages before you finish editing
the WSGI file. Everything else can happen in almost any order.

```
  1. Sign up on PythonAnywhere.                 (backend URL known immediately)
  2. Create the GitHub repo and push the code.  (same as DEPLOY_RUNBOOK.md Part A)
  3. Enable Pages.                               (Pages origin CONFIRMED)
  4. On PythonAnywhere: clone the repo, create the web app,
     edit the WSGI file using the Pages origin from step 3, reload.
  5. Verify the backend directly.
  6. Edit docs/config.js with the PythonAnywhere URL from step 1, commit, push.
  7. Verify the whole thing, including the persistence claim.
```

---

## 2. Part A — sign up, and check the one thing that sent you here

### Step 1 — create the account

1. Go to **https://www.pythonanywhere.com/pricing/** and choose the free
   plan ("Beginner" / "Create a Beginner account" — PythonAnywhere's own
   naming for the $0 tier).
2. Fill in a username, email and password. **Your username becomes part of
   your permanent URL** (`https://<username>.pythonanywhere.com`) — choose
   it deliberately.

**Verify before moving on — this is the whole reason this document exists:**
confirm the signup form did **not** ask for a card at any point. If it did,
this is the same live-documentation contradiction that affected Render, and
this runbook's premise does not hold — stop here and report it back rather
than continuing on the assumption that it will resolve itself.

3. Confirm your email if PythonAnywhere asks you to.

**Verify before moving on:** you can log in and see the PythonAnywhere
dashboard, with tabs across the top including **Consoles**, **Files**,
**Web**, and **Account**.

Note your username. Call it **`<YOUR-PA-USERNAME>`**. Your backend URL is
now known: **`https://<YOUR-PA-USERNAME>.pythonanywhere.com`** — no trailing
slash. Write it down; you'll need it in step 8.

---

## 3. Part B — get the code into GitHub (same as the Render path)

If you already did this for the Render path, **skip to Part C** — it's the
same repository, and this path reads from the same `main` branch. If not,
follow `DEPLOY_RUNBOOK.md` §2 ("Part A — get the code into GitHub, over
HTTPS") and §3 ("Part B — enable GitHub Pages") exactly as written there —
nothing about those two parts differs for this path. Come back here once you
have:

- A GitHub repository containing this project, pushed to `main`.
- GitHub Pages enabled, serving `/docs` on `main`.
- Your confirmed Pages **origin** — `https://<your-username>.github.io`
  (origin only, no path, no repo name, no trailing slash — the same
  distinction `DEPLOY_RUNBOOK.md` §4.2 warns about, because it is the single
  most common way CORS ends up misconfigured on either path).

Call it **`<PAGES-ORIGIN>`**.

---

## 4. Part C — get the code onto PythonAnywhere

### Step 2 — open a Bash console

1. On the PythonAnywhere dashboard, click **Consoles** → **Bash**. This
   opens a real Linux shell in your browser — no local terminal needed.

**Verify before moving on:** you see a prompt like `12:34 ~ $`.

### Step 3 — clone the repository

PythonAnywhere's free tier allows outbound HTTPS to `github.com` specifically
[VERIFIED — `help.pythonanywhere.com/pages/ExternalVCS/`: free accounts are
"restricted to an allowlist of sites… you should be able to use bitbucket or
github as normal"], so a public repo clones with no extra setup:

```bash
git clone https://github.com/<your-username>/<your-repo>.git warrant
```

This creates `/home/<YOUR-PA-USERNAME>/warrant`. If your GitHub repository is
**private**, PythonAnywhere's docs describe setting up an SSH key for it
(`ExternalVCS`); the simplest fix, if you hit this, is to make the repo
public — there is nothing sensitive in it (`DEPLOY_ARCHITECTURE.md` §8.1).

**Verify before moving on:**

```bash
ls warrant
```

should list `app.py`, `wsgi.py`, `start.py`, `warrant/`, `docs/`, and the
rest of the repository.

### Step 4 — confirm there is nothing to install

```bash
cat warrant/requirements.txt
```

Every line should be blank or start with `#`. **There is nothing to `pip
install`.** A virtualenv is optional on PythonAnywhere and, per their own
docs, unnecessary when you have no packages to isolate
(`help.pythonanywhere.com/pages/VirtualenvsExplained/`: *"when you're
getting started, it's best not to"* use one). This runbook does not create
one — see §9 if you want to pin the interpreter more tightly than the web
app wizard alone does.

---

## 5. Part D — create the web app

### Step 5 — the "Add a new web app" wizard

1. Click the **Web** tab, then **Add a new web app**.
2. If asked to confirm your domain, accept the default —
   `<YOUR-PA-USERNAME>.pythonanywhere.com`. Free accounts cannot use a
   custom domain.
3. Choose **Manual configuration** (**not** the Flask/Django/web2py/Bottle
   quickstart options — those generate application code Warrant doesn't
   need). [VERIFIED, `WebAppBasics`: *"there is also a 'Manual
   configuration' option where you can generate a standard template WSGI
   file that can be modified to support many other web frameworks."*]
4. Choose **Python 3.13** — the newest version PythonAnywhere's system
   images offer as of this writing
   (`DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md` §8). **Do not pick 3.14** — it
   is not offered; if your account's system image only goes up to a lower
   version than 3.13, pick the highest one available and note it, because
   §7's verification step depends on knowing which version you actually got.

**Verify before moving on:** the Web tab now shows a page for
`<YOUR-PA-USERNAME>.pythonanywhere.com` with sections including **Code**,
**Virtualenv**, **Static files**, and a big green **Reload** button at the
top. Nothing is live yet — that's expected.

### Step 6 — point the web app at the cloned repo

In the **Code** section of the Web tab, set:

| Field | Value |
|---|---|
| Source code | `/home/<YOUR-PA-USERNAME>/warrant` |
| Working directory | `/home/<YOUR-PA-USERNAME>/warrant` |

> These two field labels and their default behaviour are standard across
> PythonAnywhere's Manual configuration wizard; this runbook was not able to
> fetch a page showing their exact current wording (§10 of
> `DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md` lists this as resting on general
> platform convention, not a page fetched in this pass). If what you see on
> screen uses slightly different wording, set it to the same path regardless
> of the exact label.

Leave **Virtualenv** blank — §4 step 4 established there is nothing to
install.

---

## 6. Part E — the WSGI configuration file

### Step 7 — this is the step that replaces Render's "Environment Variables" dashboard

Still on the **Web** tab, find the **Code** section's link to your **WSGI
configuration file** — it looks like a path,
`/var/www/<your_pa_username>_pythonanywhere_com_wsgi.py`, and is a **link**,
not a text field. Click it. This opens PythonAnywhere's in-browser file
editor.

**Delete everything in the file** and replace it with exactly this — filling
in your own username and Pages origin where marked:

```python
import sys

# 1) Make the cloned repo importable. Must be an absolute path.
path = "/home/<YOUR-PA-USERNAME>/warrant"
if path not in sys.path:
    sys.path.insert(0, path)

# 2) Configuration — the PythonAnywhere-equivalent of Render's environment
#    variables (DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md sec 7). Plain Python,
#    set directly here, because PythonAnywhere's environment-variable
#    mechanism for web apps IS this file, not a dashboard field. Nothing
#    below is a secret and nothing here should ever become one — see the
#    same section for why python-dotenv is deliberately not used.
import os
os.environ.setdefault("WARRANT_ALLOWED_ORIGINS", "<PAGES-ORIGIN>")
os.environ.setdefault("WARRANT_PERSISTENCE", "persistent")
os.environ.setdefault("WARRANT_DB_PATH", "/home/<YOUR-PA-USERNAME>/warrant/data/unify.db")
os.environ.setdefault("WARRANT_FORCE_RESEED", "")

# 3) Seed the persistent disk once. On the very first reload this creates
#    data/unify.db and prints a seeding summary to the error log. On every
#    reload after that the file already exists and this is a no-op that
#    prints "skipping seed" instead — see start.py's own docstring for why
#    the conditional has to be here and not a one-off script.
import start
start.seed_if_needed()

# 4) The actual WSGI application. Everything above must run before this line.
from wsgi import application
```

Two things worth being deliberate about before you save:

- **`<PAGES-ORIGIN>` must be the origin only** —
  `https://<your-username>.github.io` — not the full page URL with a
  trailing `/<repo>/`. This is the exact same mistake
  `DEPLOY_RUNBOOK.md` §7.3 calls "the mistake this catches, nine times out
  of ten" for the Render path, and it is exactly as easy to make here.
- **The three `os.environ.setdefault(...)` lines must run before `import
  start`**, because `start.seed_if_needed()` reads `WARRANT_DB_PATH`
  immediately when it runs. The file above is already in the right order —
  don't reorder it.

Click **Save**.

**Verify before moving on:** the editor shows no red error markers and the
save succeeded (PythonAnywhere shows a small confirmation). Nothing is live
yet — a web app only picks up a new WSGI file on **Reload**, unlike Render,
which redeploys automatically on every push. This is the PythonAnywhere-
specific trap to remember for every future change: **edit → Save → Reload,
always in that order, every time.**

### Step 8 — reload, and read the error log

Back on the **Web** tab, click the big **Reload** button.

**Verify before moving on — check the error log, not just "it looks green":**
click **Log files → Error log** (a new tab). You should see, in this order:

```
no database at /home/<YOUR-PA-USERNAME>/warrant/data/unify.db — seeding
warrant-wsgi build-marker 2026-08-15 · WSGI adapter over the same WarrantRoutes app.py's Handler uses · DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md
```

followed by a seeding summary block (account counts, event totals — the
same numbers `DEPLOY_RUNBOOK.md` §9 shows for the Render path, because it's
the same fixed-seed corpus). **These lines are the deploy-log-equivalent
proof that new code is actually running** — the same discipline `app.py`'s
`BANNER`/`DEPLOY_MARKER` and `start.py`'s own boot line already use for the
Render path. If they are absent after a Reload, the WSGI file has an error;
see §10.

> **On every future edit:** reload again, and check that the marker line is
> still there (it prints on every worker start, seeded or not — the seeding
> message only appears once, the marker line appears every time). If you
> change something and it doesn't seem to have taken effect, this is the
> first thing to check, exactly as `DEPLOY_RUNBOOK.md` §9 says for Render's
> `boot_id`.

---

## 7. Part F — verify the backend directly, before touching the frontend

Open these in a browser tab. A same-tab browser navigation carries no
`Origin` header the way a cross-origin `fetch()` does, so this tests the
backend on its own, same as `DEPLOY_RUNBOOK.md` §4 step 9a.

**1. `https://<YOUR-PA-USERNAME>.pythonanywhere.com/api/health`**

```json
{"ok": true, "seeded": true, "accounts": 240, "reps": [ ... 4 reps ... ],
 "meta": {"persistence": "persistent", "persistence_notice": null, ...}}
```

| Check | Expected | If wrong |
|---|---|---|
| `"accounts": 240` | exactly 240 | §10 |
| `"seeded": true` | `true` | §10 |
| `"meta": {"persistence": "persistent"` | `"persistent"`, **not** `"ephemeral"` | `warrant/db.py::persistence()` reads `"ephemeral"` **only** on an exact match of that literal string, and defaults to `"persistent"` otherwise — so this should read `"persistent"` even if the WSGI file's `WARRANT_PERSISTENCE` line were removed entirely. If it ever reads `"ephemeral"` here, something set that exact value somewhere — check the WSGI file for a stray line, because nothing in this runbook sets it. |
| `"meta": {"persistence_notice": null` | `null` | If it's a sentence instead of `null`, `WARRANT_PERSISTENCE` did not take effect — re-check step 7, reload again |

**2. `https://<YOUR-PA-USERNAME>.pythonanywhere.com/api/queue?rep=1`** —
find `"account_count": 53`. **53 is the expected number**, same fixed-seed
corpus as Render (`DEPLOY_ARCHITECTURE.md` §6.4).

**3. `https://<YOUR-PA-USERNAME>.pythonanywhere.com/queue?rep=1`** — the
same server-rendered HTML app the Render path serves, reachable here too
(`WarrantRoutes` answers both entry points identically —
`DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md` §3). Should render fully with
JavaScript disabled.

**4. Confirm the scheme is `https`.** PythonAnywhere serves
`*.pythonanywhere.com` over HTTPS by default; a Pages site cannot `fetch()`
an `http://` URL at all (the same mixed-content rule
`DEPLOY_RUNBOOK.md` §4 step 9a names for Render).

---

## 8. Part G — connect the frontend

### Step 9 — edit `docs/config.js`

Same file, same mechanism as `DEPLOY_RUNBOOK.md` §5 step 10 — the frontend
does not know or care which backend host is behind `apiBase`. In the GitHub
web editor:

```js
window.WARRANT_CONFIG = {
  apiBase: "https://<YOUR-PA-USERNAME>.pythonanywhere.com"
};
```

No trailing slash. Commit directly to `main`.

**Verify before moving on:** wait about a minute for Pages to rebuild
(`DEPLOY_RUNBOOK.md` §5 step 11 describes watching this happen), then hard-
refresh `https://<your-username>.github.io/<your-repo>/`. You should see
the four reps, then a queue of 53 accounts once you pick one — no cold-start
wait screen this time, because PythonAnywhere's free tier does not sleep
[VERIFIED, `HOSTING_RESEARCH.md` §2.11: "Sleeps? No" for PythonAnywhere].

### Step 10 — verify the write loop, and verify persistence specifically

Do everything `DEPLOY_RUNBOOK.md` §5 step 12 describes (dispute a reason,
watch the score drop and the reason strike through, undo it, watch the
score return to exactly its original value). Then do the one additional
check that is specific to this path and is the entire reason it's worth the
extra setup:

1. File a dispute on any account. Note the account and the resulting points.
2. On the PythonAnywhere **Web** tab, click **Reload**. This restarts the
   worker process — the WSGI-hosted equivalent of Render's container
   restarting.
3. Reload the account's page on the Pages frontend.
4. **The dispute should still be there** — the reason still struck through,
   the points still adjusted, no "the demo server restarted" notice. This
   is the thing Render's ephemeral disk cannot do, and it's the entire
   point of this path.

---

## 9. What the demo tells its viewers, and what you should tell them

### 9.1 The persistence disclosure is now telling the truth in the other direction

On the Render path, `DEPLOY_RUNBOOK.md` §6.2 explains why the ephemeral-data
disclosure is a feature, not an apology. Here, `WARRANT_PERSISTENCE=persistent`
means that disclosure is **absent** — correctly, because nothing is being
quietly forgotten. If you ever need to say something about persistence to a
viewer, it's the positive version: *"Anything you file here — disputes,
pins, mutes — stays until someone deliberately resets the demo."*

### 9.2 The expiry risk needs a human, not a UI notice

Unlike the ephemeral-restart notice, there is no server-side mechanism that
can warn a viewer the web app is about to expire — `meta` has nothing to say
about it, because the expiry happens at the platform level, entirely outside
any request Warrant ever serves. **This is on you, not the product**: put
the renewal reminder from §0.3 item 1 somewhere you'll actually see it.

### 9.3 Disk usage — checked, and not a real risk

The seeded database measured **2.6 MB** locally, and the whole repository
(code, tests, docs, `.git` history) is **~18 MB**. Both are comfortably
inside PythonAnywhere's 512 MiB disk allowance — roughly 3–4% of it, even
counting the full git history you don't strictly need on the server. This
is not a risk worth monitoring for this project.

---

## 10. Troubleshooting

### 10.1 The error log has no build-marker lines at all after Reload

The WSGI file has a Python error before it ever reaches `from wsgi import
application`. Common causes, in order of likelihood:

| Symptom in the error log | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'app'` or `'warrant'` | The `sys.path.insert` line has the wrong path, or points at a directory that doesn't contain `app.py` | Confirm `path = "/home/<YOUR-PA-USERNAME>/warrant"` matches exactly what `ls` showed in §4 step 3 |
| `ModuleNotFoundError: No module named 'wsgi'` | Same cause, or the `from wsgi import application` line runs before the `sys.path.insert` line | Re-check the file is in the exact order shown in §6 step 7 |
| A traceback inside `seed_db.py` | `WARRANT_DB_PATH`'s directory could not be created — unlikely on a fresh clone, but possible if disk quota was already exhausted by something else in your account | Check disk usage on the **Files** tab; §9.3 shows this project needs very little |
| Nothing at all, not even a Python traceback | The file was edited but not saved before Reload | Go back to the WSGI file, confirm the content is there, Save again, Reload again |

### 10.2 `/api/health` returns HTML, a PythonAnywhere error page, or a raw 500

This means the WSGI worker itself failed to start `application` correctly —
check the error log (§10.1) rather than the response body; PythonAnywhere's
own error page does not include Warrant's diagnostic detail, by design
(`api.INTERNAL_MESSAGE`: *"The details are in the server log, not in this
message"* — the same principle `DEPLOY_ARCHITECTURE.md` §3.3 states for the
Render path, unmodified here).

### 10.3 The page says "The server answered, but the browser blocked the response"

Same CORS trap `DEPLOY_RUNBOOK.md` §7.3 documents for Render, same fix:

1. On the **Web** tab, open the WSGI file (§6 step 7).
2. Confirm `WARRANT_ALLOWED_ORIGINS` is set to your Pages **origin**,
   exactly — no trailing `/<repo>/`, no trailing slash at all.
3. **Save the WSGI file, then click Reload on the Web tab.** Both steps —
   editing app.py's environment on Render only needed a dashboard save and
   an automatic restart; here it needs the file saved **and** the worker
   explicitly reloaded, or the old value is still what's running.
4. Hard-refresh the Pages site.

### 10.4 A change you made doesn't seem to have taken effect

**You edited and saved but did not click Reload.** This is the single most
likely mistake on this path specifically, because nothing about
PythonAnywhere auto-restarts a worker the way Render redeploys on every
push. Check the error log for a fresh instance of the
`warrant-wsgi build-marker` line (§6 step 8) before debugging anything else.

### 10.5 The numbers are wrong (not 240 accounts, or not 53 in the queue)

Same as `DEPLOY_RUNBOOK.md` §7.6, plus one PythonAnywhere-specific check:

1. Confirm `WARRANT_SEED` and `WARRANT_AS_OF` are not set anywhere in the
   WSGI file (they shouldn't be — the file in §6 step 7 doesn't set them).
2. **Confirm which Python version you actually got.** §8 of
   `DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md` names this as a real, untested
   risk: the fixed-seed corpus depends on Python's `random` module
   producing an identical stream, and this was only tested locally on
   Python 3.14.3, not on whatever 3.13.x PythonAnywhere actually runs. If
   the numbers differ and steps 1–2 don't explain it, this is the most
   likely remaining cause, and it would be a genuine, newly-discovered
   incompatibility worth reporting rather than working around.

### 10.6 "Too many web workers running" or a quota-looking error at Reload

Free accounts get exactly one web app. If you already have one from a
previous project, this new one cannot coexist with it on a free account —
either delete the old one or upgrade. This is unrelated to Warrant's code.

### 10.7 The site was working and is now fully down, with no recent changes

**Check the expiry first** (§0.3 item 1, §9.2). If the web app's one-month
window lapsed, the Web tab shows an expired state with a renewal control —
click it. This is the single most likely explanation for an unattended demo
going dark on this path, the same way "the container is still waking" is
the single most likely explanation for a slow-loading demo on the Render
path.

---

## 11. Quick reference

**Placeholders, all of which you replace:**

| Placeholder | Where it comes from |
|---|---|
| `<YOUR-PA-USERNAME>` | Chosen at PythonAnywhere signup, step 1 |
| `<PAGES-ORIGIN>` | `https://<your-username>.github.io` — origin only |
| `<your-username>` / `<your-repo>` | Your GitHub account and repository, same as `DEPLOY_RUNBOOK.md` |

**The WSGI file, in full** (§6 step 7 — this is the entire configuration
step on this path, replacing Render's environment-variables dashboard):

```python
import sys
path = "/home/<YOUR-PA-USERNAME>/warrant"
if path not in sys.path:
    sys.path.insert(0, path)

import os
os.environ.setdefault("WARRANT_ALLOWED_ORIGINS", "<PAGES-ORIGIN>")
os.environ.setdefault("WARRANT_PERSISTENCE", "persistent")
os.environ.setdefault("WARRANT_DB_PATH", "/home/<YOUR-PA-USERNAME>/warrant/data/unify.db")
os.environ.setdefault("WARRANT_FORCE_RESEED", "")

import start
start.seed_if_needed()

from wsgi import application
```

**Web tab settings:**

```
Manual configuration, Python 3.13
Source code:        /home/<YOUR-PA-USERNAME>/warrant
Working directory:  /home/<YOUR-PA-USERNAME>/warrant
Virtualenv:          (blank — zero dependencies)
```

**Verification checklist:**

- [ ] Signup asked for no card
- [ ] `https://<YOUR-PA-USERNAME>.pythonanywhere.com/api/health` → `"accounts": 240`, `"seeded": true`, `"persistence": "persistent"`, `"persistence_notice": null`
- [ ] `https://<YOUR-PA-USERNAME>.pythonanywhere.com/api/queue?rep=1` → `"account_count": 53`
- [ ] `https://<YOUR-PA-USERNAME>.pythonanywhere.com/queue?rep=1` → styled HTML, works with JavaScript off
- [ ] Pages URL → four reps, then a queue, no CORS panel
- [ ] Dispute → points drop, reason struck through, undo restores the exact value
- [ ] **Reload the web app, then re-check the disputed account** → the dispute is still there
- [ ] A calendar reminder is set for the expiry window (§0.3 item 1)

---

*Maker agent, AI-generated. Nothing in this runbook has been executed
against a real PythonAnywhere account. Claims about PythonAnywhere's
behaviour are cited to PythonAnywhere's own documentation, fetched
2026-08-15, where verified there, and labelled as inferences where they were
not — see `DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md` §10 for the complete
breakdown, including the one assumption (free-tier-specific behaviour of the
WSGI-file mechanism) that is neither verified nor merely documented.*
