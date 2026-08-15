# DEPLOY_RUNBOOK.md — putting Warrant on a GitHub Pages URL

**Stage:** 3 of 4 (build)
**Author:** Maker agent (AI-generated)
**Implements:** `DEPLOY_ARCHITECTURE.md`
**Test evidence:** `DEPLOY_TEST_OUTPUT.md`

---

## 0. Read this before you start

### 0.1 Nothing here has been deployed

**No part of this has been run against real hosting.** Nobody in this pipeline has a
GitHub account, a Render account, or a credential. No repository exists. No Render
service exists. No Pages site exists.

Everything below was verified locally — a real backend process, real HTTP requests,
a real second static server on a second port to make CORS genuinely cross-origin,
and the real frontend code driven against the real backend. `DEPLOY_TEST_OUTPUT.md`
is the transcript. What was *not* verified is anything that depends on Render or
GitHub actually behaving the way their documentation says.

**Every URL below in angle brackets is a placeholder.** They look like this:

- `https://<your-username>.github.io` — placeholder
- `https://<your-app>.onrender.com` — placeholder
- `<your-repo>` — placeholder

You replace them. They are not real addresses and typing them into a browser will
not reach anything.

### 0.2 What you will end up with

Two public URLs:

| URL | What it is | Needs JavaScript? |
|---|---|---|
| `https://<your-username>.github.io/<your-repo>/` | The Pages frontend. Static shell, talks to the backend over `fetch()`. | **Yes** |
| `https://<your-app>.onrender.com/queue?rep=1` | The original server-rendered HTML app. Unchanged. | **No** |

Both are **public, unauthenticated and world-readable**. There is no login. Anyone
with the link sees everything. The data is synthetic — 240 generated accounts with
`.test` domains — so there is nothing sensitive in it, but you should decide that
this is acceptable rather than discover it. (`DEPLOY_ARCHITECTURE.md` §8.1, §10.4
question 2.)

### 0.3 Three costs you are accepting

1. **Roughly a minute of cold start for most visitors.** Render's free tier spins a
   service down after 15 minutes of no traffic. A demo link is clicked at
   unpredictable times, so most people who click yours will hit a sleeping
   container. The frontend handles this deliberately — it paints immediately and
   explains the wait — but the wait is real.
2. **Rep-filed data does not survive a restart.** Every disagreement, pin, demote
   and mute is lost on every spin-down and every redeploy. The account and signal
   data is regenerated identically from a fixed seed, so the demo restores rather
   than breaks — but a dispute you filed yesterday is gone today. The product tells
   the viewer this in plain words on every screen; see §6.
3. **You need no keep-alive pinger and this runbook does not give you one.** A
   pinger would consume roughly 730 of your 750 free monthly instance-hours, and
   whether Render's terms permit it could not be established in either direction —
   their terms-of-service and acceptable-use pages return JavaScript-only content
   that could not be read. `DEPLOY_ARCHITECTURE.md` §10.1 item 4's position stands:
   do not add one without reading those terms yourself.

### 0.4 What you need installed

- **`git`**, and a GitHub account. That is all.
- You do **not** need `gh`, `docker`, `flyctl`, the `render` CLI, `npm`, `node`, or
  `psql`. None are used. Every hosting action below happens in a browser.

---

## 1. The order-of-operations trap — read this or you will do step 9 twice

The two halves of this system each need to know the other's address, and **neither
address exists until you create the thing**.

- The **Pages URL** does not exist until Pages is enabled on the repo.
- The **Render URL** does not exist until the Render service has been created.

So one of them has to be configured after the other exists. There is exactly one
order that avoids doing anything twice, and it works because of an asymmetry:

> **The Pages *origin* is predictable from your username; the Render URL is not
> predictable from anything.**
>
> Your Pages origin is always `https://<your-username>.github.io`, whatever you call
> the repo. Your Render URL is `https://<something>.onrender.com` where `<something>`
> depends on the service name you choose *and* on whether that name is already taken
> globally — Render may append a suffix. **You cannot know it until the service
> exists.**

Therefore:

```
  1. Create the GitHub repo and push the code.          (repo exists)
  2. Enable Pages.                                      (Pages origin CONFIRMED)
        -> the site loads and shows "not connected to a backend yet".
           That is the correct, expected result at this point.
  3. Create the Render service, and set
     WARRANT_ALLOWED_ORIGINS to the origin from step 2. (Render URL now known)
  4. Edit docs/config.js with the Render URL, commit, push.
        -> Pages rebuilds, the two halves connect.
```

Step 3 can set the CORS origin at service-creation time precisely because step 2
already told you the exact string. If you did Render first you would have to go back
into the Render dashboard afterwards and add the variable, which triggers a second
restart. Doing Pages first costs nothing and confirms the string with your own eyes.

---

## 2. Part A — get the code into GitHub, over HTTPS

`gh` is not installed and this runbook does not use it. Everything is the GitHub
website plus plain `git`.

### Step 1 — create an empty repository on github.com

1. Go to **https://github.com/new**.
2. **Repository name:** `warrant` (or anything else — remember it as `<your-repo>`).
3. **Description:** optional.
4. **Public** or **Private** — choose **Public**.
   > GitHub Pages on a **private** repository requires a paid plan. If you pick
   > Private, step 5 will not offer you Pages. Pick Public.
5. **Do NOT tick** "Add a README file", "Add .gitignore", or "Choose a license".
   You are pushing an existing project; an initial commit here creates a conflict
   you would have to resolve.
6. Click **Create repository**.

**Verify before moving on:** the page now shows "Quick setup — if you've done this
kind of thing before" and a URL ending in `.git`. Copy that HTTPS URL. It looks like
`https://github.com/<your-username>/<your-repo>.git`.

### Step 2 — push the project

In a terminal, in the project folder (the one containing `app.py`, `start.py`, and
the `docs/` and `warrant/` folders):

```bash
git init
git add .
git commit -m "Warrant: reason-first lead prioritisation, with /api and static frontend"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

**On authentication.** When `git push` asks for a password, your GitHub account
password will **not** work. GitHub requires a Personal Access Token:

1. https://github.com/settings/tokens → **Generate new token (classic)**.
2. **Note:** `warrant deploy`. **Expiration:** 30 days is plenty.
3. **Scopes:** tick **`repo`** only.
4. **Generate token**, then copy it.
5. Paste it when `git push` prompts for **Password**. Your **Username** is your
   GitHub username.

> **This token is a real credential.** It is the only one in this whole process.
> Do not paste it into any file in this repository. Do not commit it. Nothing in
> Warrant reads it, needs it, or stores it — it is between you and `git`. If you
> ever paste it somewhere by accident, revoke it at the same settings page
> immediately.

**Verify before moving on:** reload `https://github.com/<your-username>/<your-repo>`
in the browser. You should see `app.py`, `start.py`, `requirements.txt`,
`.python-version`, and folders `docs/`, `warrant/`, `db/`, `tests/`.

Click into `docs/` and confirm it contains **five** files: `.nojekyll`, `app.js`,
`config.js`, `index.html`, `styles.css`. If `.nojekyll` is not listed, GitHub may be
hiding it as a dotfile — check the file count instead, or trust that `git add .`
included it.

---

## 3. Part B — enable GitHub Pages

### Step 3 — turn Pages on

1. On your repository page, click **Settings** (the tab, top right of the repo — not
   your account settings).
2. In the left sidebar, click **Pages**.
3. Under **Build and deployment** → **Source**, choose **Deploy from a branch**.
   > Do **not** choose "GitHub Actions". This project has no workflow and needs none.
4. Under **Branch**, two dropdowns appear:
   - left dropdown: **`main`**
   - right dropdown: **`/docs`**  ← this one is the whole point; the default is
     `/ (root)` and it is wrong here.
5. Click **Save**.

### Step 4 — wait, then verify

Pages takes 1–3 minutes on a first publish. Refresh the Settings → Pages screen.

**Verify before moving on:** the page shows a green tick and

> Your site is live at `https://<your-username>.github.io/<your-repo>/`

Open that URL. **You should see this, and it means everything is working:**

> **Warrant is deployed here, but not connected to a backend yet.**
> GitHub Pages is serving this page correctly. It has no backend URL to talk to.
> …
> *Current value in `docs/config.js`:* `https://<your-app>.onrender.com`

That panel is the frontend correctly detecting that `config.js` still holds the
placeholder. **It makes no network request at all in this state** — verified, see
`DEPLOY_TEST_OUTPUT.md` §6. Seeing it proves Pages works, the CSS loaded, and
`app.js` ran.

If you instead see a raw file listing, a 404, or the page source as text, go back to
step 3 and check the `/docs` dropdown.

### Step 5 — write down your origin, exactly

**This is the single most likely thing to get wrong in this entire runbook.**
`DEPLOY_ARCHITECTURE.md` §4.2 says so and §9.3 exists because of it.

Your browser is now showing a URL like:

```
https://<your-username>.github.io/<your-repo>/
```

The value you need in step 8 is **not that**. It is the **origin**, which is scheme
plus host and **nothing else**:

```
https://<your-username>.github.io
```

| | |
|---|---|
| ✅ **CORRECT** | `https://<your-username>.github.io` |
| ❌ wrong — has the repo path | `https://<your-username>.github.io/<your-repo>/` |
| ❌ wrong — has the repo path | `https://<your-username>.github.io/<your-repo>` |
| ❌ wrong — trailing slash | `https://<your-username>.github.io/` |
| ❌ wrong — `http` not `https` | `http://<your-username>.github.io` |
| ❌ wrong — uppercase | `https://<Your-Username>.github.io` |

The comparison on the server is an **exact string match** — no prefix matching, no
regex, no normalisation. This was tested: `http://localhost:8080/` with a trailing
slash did **not** match an allowlist entry of `http://localhost:8080`, and neither
did `http://localhost:8080.evil.test`. See `DEPLOY_TEST_OUTPUT.md` §5, case 2b.

**A trick that removes all doubt:** if you get this wrong, the frontend will later
show you the exact string to use, read live from your own browser. See §7.3.

Write your origin down now. Call it **`<PAGES-ORIGIN>`** for the rest of this
document.

---

## 4. Part C — create the Render backend

The `render` CLI is not installed and this runbook does not use it. Everything is
the Render dashboard in a browser.

### Step 6 — sign up

1. Go to **https://render.com** and click **Get Started** / **Sign Up**.
2. Sign up **with GitHub**. This is the easiest path because it also grants Render
   read access to your repositories, which step 7 needs.
3. Authorise Render when GitHub asks. You can restrict it to **only selected
   repositories** and pick just `<your-repo>` — that is the tighter choice and it
   works fine.
4. No credit card is required for the free tier.

**Verify before moving on:** you are looking at the Render dashboard.

> **Before you create anything:** if this Render workspace already has other free
> services in it, note that the **750 instance-hours/month allowance is per
> workspace, not per service**, and exceeding it suspends *all* free services until
> the next month. One service running continuously is about 730 hours. Two are not
> possible. (`DEPLOY_ARCHITECTURE.md` §10.4 question 4.)

### Step 7 — create the web service

1. Click **New +** → **Web Service**.
2. Choose **Build and deploy from a Git repository**, then **Next**.
3. Find `<your-repo>` in the list and click **Connect**.
   > If it is not listed, click "Configure account" / "Edit repository access" and
   > grant Render access to it.

You are now on the service configuration form. Fill it in exactly as below.

| Field | Value to enter | Notes |
|---|---|---|
| **Name** | `warrant-demo` | This becomes part of your URL. If the name is taken globally, Render will tell you or append a suffix — **whatever it ends up as is what you must use in step 10.** |
| **Region** | whichever is nearest you | No effect on correctness. |
| **Branch** | `main` | Must match what you pushed. |
| **Root Directory** | *leave blank* | The project is at the repo root. |
| **Language** | **`Python 3`** | ⚠️ **This is a dropdown and you must set it.** Render does **not** infer the language from `requirements.txt` — you choose it here. (Verified against https://render.com/docs/your-first-deploy.) |
| **Build Command** | see step 7a below | |
| **Start Command** | `python start.py` | Exactly this. Nothing else. |
| **Instance Type** | **Free** | |

#### Step 7a — the Build Command, and an honest unknown

Render will pre-fill the Build Command, most likely with:

```
pip install -r requirements.txt
```

`requirements.txt` exists in this repo and **declares zero packages** — it contains
only comments. That is deliberate: Warrant has no third-party dependencies and a
test (`tests/test_queue.py::TestT19StandardLibraryOnly`) fails if one is ever added.

> **NAMED UNKNOWN.** What Render's build step does with a `requirements.txt`
> containing only comment lines is **not documented anywhere I could find**. The
> expected behaviour is that `pip install -r` on a comment-only file succeeds and
> installs nothing, because that is standard `pip` behaviour. But that is an
> inference about `pip`, not a statement from Render's docs, and I could not test
> it against Render.

**Leave the pre-filled command as-is and let it run.** Then:

- **If the build succeeds** — nothing more to do. This is the expected case.
- **If the build fails** at the install step, go to **Settings → Build & Deploy →
  Build Command** and replace it with either of these, both of which are valid
  no-op commands that exit 0:

  ```
  python --version
  ```

  or

  ```
  echo "Warrant has no dependencies"
  ```

  Then **Manual Deploy → Deploy latest commit**. Either command makes the build
  step trivially succeed, which is correct here because there is genuinely nothing
  to build.

#### Step 7b — pin the Python version

The repo contains a **`.python-version`** file at its root, containing exactly:

```
3.14.3
```

That is the supported way to pin the version (verified against
https://render.com/docs/python-version), and it should be picked up automatically.

**Pin it in the dashboard as well**, belt and braces, in step 8's environment
variable list. The reason to pin rather than take the default: **3.14.3 is Render's
default only for services created on or after 11 February 2026.** A workspace or
service created before that date keeps an older default, and this runbook cannot
know when your account was made. Render's documented minimum is 3.7.3, and Warrant's
code uses only long-stable standard library features, so an older 3.x would very
likely work — but "very likely" is not what you want under a reproducibility
guarantee, and the fixed-seed corpus depends on the `random` module behaving
identically (`DEPLOY_ARCHITECTURE.md` §6.4 step 3).

> The variable name must be **`PYTHON_VERSION`** and the value must be **fully
> qualified including the patch number** — `3.14.3`, not `3.14`.
> `runtime.txt` is not mentioned anywhere in Render's Python docs; do not create one.

### Step 8 — environment variables

Still on the creation form, expand **Environment Variables** (or, if you already
created the service, go to **Environment** in the left sidebar). Click
**Add Environment Variable** for each row:

| Key | Value | Why |
|---|---|---|
| `WARRANT_BIND_HOST` | `0.0.0.0` | **Mandatory.** See the box below. |
| `WARRANT_ALLOWED_ORIGINS` | `<PAGES-ORIGIN>` from step 5 | Origin only. No path, no repo name, no trailing slash. |
| `WARRANT_PERSISTENCE` | `ephemeral` | Turns on the honest disclosure that data is lost on restart. |
| `PYTHON_VERSION` | `3.14.3` | Step 7b. Fully qualified. |

**Do not set any of these.** Each is either injected by the platform or has a default
that is already correct, and setting one will break something:

| Do not set | Why |
|---|---|
| `PORT` | **Render injects this automatically.** Setting it yourself can make the app listen somewhere Render is not looking. |
| `WARRANT_PORT` | Takes precedence over `PORT`, which would defeat the platform's injection. Leave unset so `PORT` is used. |
| `WARRANT_SEED` | Default `20260811`. Changing it changes the whole corpus and breaks reproducibility across redeploys. |
| `WARRANT_AS_OF` | Default `2026-08-11T09:00:00Z`. Changing it changes every decay calculation and every date in every sentence. |
| `WARRANT_DB_PATH` | Default is correct for a container with no volume. |
| `WARRANT_FORCE_RESEED` | **Destructive.** Set to `1` only to deliberately wipe a persistent disk back to the pristine corpus. On Render's free tier it does nothing useful, because the disk is empty on every boot anyway. |

> ### ⚠️ `0.0.0.0` is not a style preference — it is the deploy-succeeds/deploy-fails line
>
> Render's own documentation (https://render.com/docs/web-services):
>
> > *"Every Render web service must bind to a port on host `0.0.0.0` to serve HTTP
> > requests."*
>
> and
>
> > *"If Render fails to detect a bound port, your web service's deploy fails and
> > displays an error in your logs."*
>
> **Binding `127.0.0.1` or `localhost` will not be detected.** Render's
> troubleshooting documentation (https://render.com/docs/troubleshooting-deploys)
> ties exactly this to a **502 Bad Gateway**. Warrant's default bind address is
> `127.0.0.1` — deliberately, so that running it on a laptop exposes nothing to your
> local network — so on Render you **must** override it with this variable.
>
> Render's default `PORT` is `10000`, but you should not rely on that or set it;
> `warrant/db.py::port()` reads `WARRANT_PORT`, then `PORT`, then falls back to
> `8000`, so the injected value is used automatically.

### Step 9 — deploy, and read the log

Click **Create Web Service** (or **Deploy** if the service already exists).

Watch the **Logs** tab. On a successful first deploy you will see, in this order:

```
warrant-start build-marker 2026-08-13 · conditional seed, then serve
boot_id=<8 hex chars> started_at=<timestamp> persistence=ephemeral db=unify.db
no database at /opt/render/project/src/data/unify.db — seeding
Seeded /opt/render/project/src/data/unify.db
  as_of            : 2026-08-11T09:00:00Z
  ruleset          : warrant-v1.0.0
  reps             : 4
  signal_types     : 19  (reference data, seeded verbatim from spec 4.1)
  accounts         : 240  (6 inactive)
  people           : 1354
  signal_events    : 6916
  observations     : 468  (75 accounts with none)
  task_events      : 877
  disagreements    : 12  (13 adjustments, 5 still active)
  forced cohorts   :
    ...
  verified         : 19 accounts have zero events, 66 have freshest evidence >45d old
warrant-app build-marker 2026-08-11 · live SQL per request, no cache
warrant-api build-marker 2026-08-13 · /api + CORS + do_OPTIONS · DEPLOY_ARCHITECTURE.md §3/§4
Warrant listening on http://0.0.0.0:<port>/queue?rep=1
as_of=2026-08-11T09:00:00Z ruleset=warrant-v1.0.0
```

Those numbers are not illustrative. They are the actual output of this code seeding
an empty directory, captured in `DEPLOY_TEST_OUTPUT.md` §7. **If your log shows
different counts, something is different about your environment** — most likely a
`WARRANT_SEED` or `WARRANT_AS_OF` you set by accident, or a materially different
Python version.

**The three `build-marker` lines exist so you can prove which build is running.** A
deploy that reports "succeeded" is not the same as a deploy that shipped your code.
If you change something and redeploy but the old behaviour persists, check that
these lines appear fresh in the log, with a **new `boot_id`**, before you debug
anything else.

**Verify before moving on:** Render shows the service as **Live** and gives you a URL
at the top of the page, like `https://warrant-demo-xxxx.onrender.com`.

Copy it. Call it **`<RENDER-URL>`**. **No trailing slash.**

### Step 9a — verify the backend directly, before touching the frontend

Open these in a browser tab. A browser request carries no `Origin` header, so CORS is
not involved and you are testing the backend on its own.

**1. `<RENDER-URL>/api/health`** — expect JSON containing:

```json
{"ok": true, "seeded": true, "accounts": 240, "reps": [ ... 4 reps ... ], "meta": { ... }}
```

Three things to check, in order of importance:

| Check | Expected | If wrong |
|---|---|---|
| `"accounts": 240` | exactly 240 | see §7.6 |
| `"seeded": true` | `true` | see §7.6 |
| `"meta": {"persistence": "ephemeral"` | `"ephemeral"` | You mistyped `WARRANT_PERSISTENCE`. Any value other than exactly `ephemeral` is read as `persistent` and the demo will **silently stop disclosing that it forgets data**. Fix the variable and redeploy. |

Also confirm `"meta": {"as_of": "2026-08-11T09:00:00Z"}`.

**2. `<RENDER-URL>/api/queue?rep=1`** — a large JSON document. Find:

```json
"account_count": 53
```

**53 is the expected number** for rep 1's patch under the fixed seed. A different
number means the seed or the `as_of` differs from the defaults.

**3. `<RENDER-URL>/queue?rep=1`** — the original server-rendered HTML app. This
should render a full, styled queue page **with JavaScript disabled**. It is not part
of the Pages frontend and it is a genuinely useful fallback.

**4. Check the scheme is `https`.** Render serves `*.onrender.com` over HTTPS
automatically. **This matters enormously:** a page served from GitHub Pages over
HTTPS **cannot** `fetch()` an `http://` URL — the browser blocks it as mixed content
before the request ever leaves. If for any reason your Render URL is `http://`, stop;
nothing downstream will work.

> **The first request after 15 minutes of no traffic will take about a minute.**
> The container has spun down and is starting again. This is normal and expected.
> It is not a fault.

---

## 5. Part D — connect the frontend to the backend

### Step 10 — edit `docs/config.js`

You can do this entirely in the GitHub web editor; no terminal needed.

1. Go to `https://github.com/<your-username>/<your-repo>/blob/main/docs/config.js`
2. Click the **pencil** icon (Edit this file).
3. Find the last few lines:

   ```js
   window.WARRANT_CONFIG = {
     apiBase: "https://<your-app>.onrender.com"   // placeholder — replace with your own
   };
   ```

4. Replace **only** the placeholder string with your `<RENDER-URL>`:

   ```js
   window.WARRANT_CONFIG = {
     apiBase: "https://warrant-demo-xxxx.onrender.com"
   };
   ```

5. **Commit changes** → **Commit directly to the `main` branch** → **Commit changes**.

**Rules for that string:**

| | |
|---|---|
| ✅ **CORRECT** | `"https://warrant-demo-xxxx.onrender.com"` |
| ❌ trailing slash | `"https://warrant-demo-xxxx.onrender.com/"` |
| ❌ includes a path | `"https://warrant-demo-xxxx.onrender.com/api"` |
| ❌ `http` not `https` | `"http://warrant-demo-xxxx.onrender.com"` |
| ❌ quotes removed | `https://warrant-demo-xxxx.onrender.com` |

`app.js` appends `/api/...` itself. Adding `/api` here produces `/api/api/health`.

> **Nothing in this file is a secret.** It holds one public URL. `config.js` is
> served by GitHub Pages and is readable by anyone, by design. There are no keys,
> tokens or credentials anywhere in this project — Warrant talks to one local SQLite
> file and makes no outbound calls, so there is nothing to authenticate to. If you
> ever find yourself wanting to put a key in this file, something has gone wrong.

### Step 11 — wait for Pages to rebuild, then verify the whole thing

Pages rebuilds automatically on push, typically within a minute. Watch the
**Actions** tab, or just wait 60 seconds.

Open `https://<your-username>.github.io/<your-repo>/` and **hard-refresh**
(Ctrl+F5, or Cmd+Shift+R on a Mac). Browsers cache `config.js` aggressively and a
soft refresh may serve you the old placeholder.

**What you should see, in sequence:**

1. Immediately: the Warrant header, and **Loading…**
2. After ~1.5 seconds, if the backend is asleep, that swaps to:

   > **Waking the demo server. On free hosting this takes about a minute.**
   > Warrant runs live SQL over a real database at the moment you load a page —
   > there is no cache and no precomputed score. …
   > *Waiting 23s…*

   with the counter ticking. This is correct behaviour, not an error.
3. Within about a minute: the rep index, listing four reps.

Click **Ana Belic**. You should get a queue of **53 accounts**, ranked, each with a
band chip, a points figure, one plain-English reason sentence, and a freshness chip.

Click an account name. You should get the detail view: the reasons, and —
**immediately under them** — a limits line reading something like:

> Showing the 5 strongest of 10 signals. The 5 not shown are worth +33.1 pts combined
> and are part of why this is ACT NOW — the 5 shown alone would rate REVIEW.

**If that limits line is missing, that is a bug, not a cosmetic issue** — it is the
sentence that stops the product from overclaiming, and the frontend is built to
print `limits line missing — this is a bug` rather than silently omit it.

At the top of every screen you should see the persistence notice:

> This demo server runs on free hosting with no persistent disk. It last restarted on
> …. Anything a rep filed before then — disputes, pins, mutes — is gone. Everything
> you file now lasts until the next restart.

### Step 12 — verify the write loop, which is the actual feature

Reading the queue only proves the read path. **The point of Warrant is that
disagreeing with it changes what it says.** Test that:

1. Open any account's detail view.
2. Note the **points** figure at the top and the text of the **first reason**.
3. Under that first reason, click **this is wrong**.
4. You should immediately get a confirmation sentence naming the signal and a return
   date, ending with **"…or until this demo server restarts, whichever comes first."**
5. The page re-renders. Check all four of these:
   - the points figure has **dropped**, by exactly the disputed reason's value
   - a note reads **`was NN pts before your disagreement`**
   - the disputed reason is **still in its slot**, struck through, showing something
     like **`+16 pts → 0 pts`**, with a note saying when it stops being suppressed
   - the **limits line has changed**, because the withheld set changed
6. Click **undo**. The score returns to **exactly** its original value.

This loop was tested end to end over HTTP. Real numbers from that run: an account at
**73.89** points, disputing a reason worth **+16.00**, dropped to **57.89** — a delta
of exactly **−16.00** — and reverting restored it to **73.89** exactly, with an
identical limits line. `DEPLOY_TEST_OUTPUT.md` §4 is the transcript.

---

## 6. What the demo tells its viewers, and what you should tell them

### 6.1 The data is synthetic and the product says so

`/metrics` and `/ruleset` both carry caveat lines that the frontend renders. They are
not decoration and you should not remove them:

- *"/metrics numbers are computed by live SQL over synthetic instrumentation. The
  arithmetic is real; the inputs are seeded."*
- *"Per-signal-type show counts only exist once someone has loaded a queue."*

The second one bites harder on this deployment than anywhere else: because the
database is rebuilt on **every restart**, per-signal-type counts start at zero every
time the container wakes, and render as `—` until somebody loads a queue. If you
show `/metrics` to someone cold, expect dashes.

On `/ruleset`, note that the `REVIEW REQUIRED` flag is unreliable at small numbers,
because its denominator is the number of reps who have loaded a queue — which, after
a restart, is very few.

### 6.2 The ephemeral-data disclosure is a feature, not an apology

`WARRANT_PERSISTENCE=ephemeral` makes the backend emit, on every read, a notice the
frontend prints at the top of every view; append a clause to every write
confirmation; and — if the container restarts mid-session — tell the viewer:

> **The demo server restarted.**
> Anything you filed in this session — disputes, pins, mutes — is gone. The queue
> below has been rebuilt from the same seeded data, so the accounts and their
> evidence are exactly as they were. This is a limitation of the free hosting tier,
> not of Warrant. On a host with a persistent disk, everything you file survives.

That last sentence is doing real work. Warrant exists partly because scoring systems
that ignore rep feedback get abandoned. A demo that quietly forgets a rep's dispute
would be enacting exactly that failure. Saying so out loud distinguishes a hosting
constraint from a product behaviour. **If you demo this to anyone, let them read
that line rather than talking over it.**

### 6.3 If you want the data to persist — it is four settings, not a rewrite

There is no code change, no schema change, no SQL change and no new dependency. On a
host with a persistent volume (Railway Hobby at about $5/month is browser-driven and
fits this runbook's no-CLI constraint; Fly.io leans on `flyctl`, which is not
installed):

| Variable | Free/ephemeral | With a persistent volume |
|---|---|---|
| `WARRANT_DB_PATH` | *unset* | `/var/data/unify.db` (your volume mount path) |
| `WARRANT_PERSISTENCE` | `ephemeral` | `persistent` |
| `WARRANT_BIND_HOST` | `0.0.0.0` | `0.0.0.0` |
| `WARRANT_ALLOWED_ORIGINS` | `<PAGES-ORIGIN>` | `<PAGES-ORIGIN>` |
| Start command | `python start.py` | `python start.py` |
| `docs/config.js` `apiBase` | the Render URL | the new host's URL |

`start.py` seeds **only if the database file is absent**. On a volume, that means the
first boot seeds and every later boot skips — so reps' disputes survive. **Both
branches were tested**: seeding into an empty directory, and skipping when the file
was already there. See `DEPLOY_TEST_OUTPUT.md` §7.

Setting `WARRANT_PERSISTENCE=persistent` also removes the restart notice and the
"…or until this demo server restarts" clause automatically. One variable, three
behaviours, no frontend change.

---

## 7. Troubleshooting

### 7.0 First, the rule that saves the most time

> **A `200` in Render's logs is NOT evidence that the frontend works.**

This is the nastiest failure mode in the whole system and it is worth internalising
before you debug anything. When CORS is misconfigured, the backend receives the
request, builds the full response, sends it, and logs a clean `200`. The browser
receives all of it — and then refuses to hand it to the JavaScript. **Server-side,
everything looks perfect. Client-side, the page is empty.**

This was demonstrated deliberately during testing: with a disallowed `Origin`, the
server returned **HTTP 200 with a complete 1,242-byte JSON body** and no
`Access-Control-Allow-Origin` header. See `DEPLOY_TEST_OUTPUT.md` §5, case 2.

**So: never conclude "the backend is fine" from the backend's logs.** Judge from the
browser.

### 7.1 The page says "Warrant is deployed here, but not connected to a backend yet"

**State:** `apiBase` in `docs/config.js` is missing, empty, or still contains the
literal `<your-app>`. **No network request is made at all.**

**Fix:** step 10. Then **hard-refresh** — a soft refresh often serves a cached
`config.js`, which is the most common reason people think step 10 did not work.

### 7.2 The page says "The demo server did not answer"

**State:** the frontend polled `/api/health` for 90 seconds and never got a response.
The panel echoes the URL it tried, which is usually enough to spot the problem.

In order of likelihood:

1. **The container is still waking**, under load, and took longer than 90 seconds.
   Click **Try again**.
2. **The URL in `config.js` is wrong.** Compare the echoed URL against your Render
   dashboard, character by character. Watch for a trailing slash and for `http` vs
   `https`.
3. **Your free instance-hours ran out.** Check the Render dashboard — a suspended
   service says so. All free services in the workspace stop until the next month.
4. **The service failed to start.** Check Render's **Logs** for the three
   `build-marker` lines. If they are absent, the process never started; see §7.5.
5. **The service is bound to the wrong interface** — a `502 Bad Gateway` from Render
   rather than a timeout points here. See §7.5.

### 7.3 The page says "The server answered, but the browser blocked the response"

**This is CORS, and it is the failure §7.0 describes.** The frontend detected it with
a second probe: the plain request threw, but a `no-cors` probe succeeded, which means
the server is reachable and the browser is discarding the response.

**The panel prints your browser's own `window.location.origin`.** That string is read
live from the browser, not hardcoded, and it is **exactly** what
`WARRANT_ALLOWED_ORIGINS` must be set to. Copy it from the screen.

**Fix:**

1. Render dashboard → your service → **Environment**.
2. Edit `WARRANT_ALLOWED_ORIGINS` so it equals that string **exactly**.
3. **Save changes.** Render restarts the service — wait for it to go **Live** again.
4. Hard-refresh the Pages site.

**The mistake this catches, nine times out of ten:** the value was set to the full
page URL, `https://<your-username>.github.io/<your-repo>/`, instead of the origin,
`https://<your-username>.github.io`. Re-read §5, step 5.

Two other things that produce this panel:

- **The variable is unset or empty.** Empty is not "allow everything" — it is
  "emit no CORS headers at all", deliberately, so that the backend fails closed
  rather than shipping permissive.
- **A case or scheme mismatch.** The comparison is exact.

> There is a debugging escape hatch: setting `WARRANT_ALLOWED_ORIGINS` to the single
> character `*` allows every origin. It is safe *here* only because Warrant has no
> credentials, no cookies and no authentication of any kind, so there is nothing for
> a hostile page to steal. **Use it to confirm CORS is the problem, then set the real
> origin.** Do not leave it.

### 7.4 The page loads but says "The backend is running but has no data"

**State:** `/api/health` returned `200` with `"seeded": false`.

**Cause:** the process started but seeding did not complete — almost always because
the directory at `WARRANT_DB_PATH` is missing or not writable.

**Fix:** check Render's **Logs** for the seeding summary block from step 9. If it is
absent or shows an error, confirm you have **not** set `WARRANT_DB_PATH`. On Render's
free tier it should be unset entirely.

### 7.5 Render says the deploy failed, or you get 502 Bad Gateway

| Symptom in the log | Cause | Fix |
|---|---|---|
| "no open ports detected" / deploy times out at the port scan | The app bound `127.0.0.1`. Render only detects `0.0.0.0`. | Set `WARRANT_BIND_HOST=0.0.0.0`. See step 8. |
| `502 Bad Gateway` when you open the URL | Same cause. Render's troubleshooting docs tie 502 to exactly this. | Same fix. |
| Build fails at `pip install -r requirements.txt` | See step 7a's named unknown. | Replace the Build Command with `python --version`. |
| `ModuleNotFoundError` or a syntax error | Python version mismatch. | Set `PYTHON_VERSION=3.14.3` and confirm `.python-version` is in the repo. |
| Nothing at all in the log | The Start Command is wrong. | It must be exactly `python start.py`. |
| The log shows the OLD behaviour after a fix | The deploy did not ship. | Check the `boot_id=` line is **new**. If it is not, **Manual Deploy → Clear build cache & deploy**. |

> **On whether this works on Render at all.** Warrant is a plain
> `ThreadingHTTPServer` from the Python standard library — not Flask, not Django, not
> a WSGI or ASGI application, and it does not use Gunicorn.
>
> Render's documented requirement is about **binding a port**, not about a framework:
> *"Every Render web service must bind to a port on host `0.0.0.0` to serve HTTP
> requests."* Gunicorn appears in Render's docs only as an example start command, not
> a requirement. A stdlib `ThreadingHTTPServer` bound to `0.0.0.0:$PORT` satisfies
> the literal stated requirement.
>
> **Carried forward honestly:** no Render document affirmatively says "any process
> listening on a port is acceptable." The support for this is strong but
> **inferential**, and the duration of Render's port-scan timeout is not documented.
> This is the one architectural assumption that your first deploy tests for real. If
> it turns out to be false, the fallback is a different container host — Railway is
> browser-driven and takes the same start command — not a rewrite.

### 7.6 The numbers are wrong (not 240 accounts, or not 53 in the queue)

The corpus is generated from a fixed seed and must be byte-identical on every boot.

1. Confirm `WARRANT_SEED` is **unset** (default `20260811`).
2. Confirm `WARRANT_AS_OF` is **unset** (default `2026-08-11T09:00:00Z`).
3. Confirm the Python version. The corpus comes from the `random` module; a
   materially different Python could in principle produce a different stream.

### 7.7 An account page says "Not in this queue right now"

**This is normal, not a fault.** You reached an account that is not in that rep's
current queue — because you muted it, because a `Not a fit` dispute muted it, because
it is inactive, or because another rep owns it. Muted accounts return automatically
when their window expires. Use **back to your queue** or **view your adjustments**.

### 7.8 Everything you filed has vanished

The container restarted. This is §0.3 cost 2 and §6.2, working as designed. The
account data is regenerated identically; only rep-filed data is lost. If this is not
acceptable for how you intend to use the demo, see §6.3.

---

## 8. Quick reference

**Placeholders, all of which you replace:**

| Placeholder | Where it comes from |
|---|---|
| `<your-username>` | Your GitHub username |
| `<your-repo>` | The repo name you chose in step 1 |
| `<PAGES-ORIGIN>` | `https://<your-username>.github.io` — **origin only** |
| `<RENDER-URL>` | Copied from the Render dashboard in step 9 — **no trailing slash** |

**Render dashboard settings:**

```
Language:        Python 3           (a dropdown; requirements.txt does NOT set it)
Branch:          main
Root Directory:  (blank)
Build Command:   pip install -r requirements.txt   (fallback: python --version)
Start Command:   python start.py
Instance Type:   Free

Environment variables:
  WARRANT_BIND_HOST        = 0.0.0.0
  WARRANT_ALLOWED_ORIGINS  = https://<your-username>.github.io
  WARRANT_PERSISTENCE      = ephemeral
  PYTHON_VERSION           = 3.14.3

Do NOT set: PORT, WARRANT_PORT, WARRANT_SEED, WARRANT_AS_OF,
            WARRANT_DB_PATH, WARRANT_FORCE_RESEED
```

**GitHub Pages settings:** Settings → Pages → Deploy from a branch → `main` + `/docs`

**Verification checklist:**

- [ ] `<RENDER-URL>/api/health` → `"accounts": 240`, `"seeded": true`, `"persistence": "ephemeral"`
- [ ] `<RENDER-URL>/api/queue?rep=1` → `"account_count": 53`
- [ ] `<RENDER-URL>/queue?rep=1` → styled HTML page, works with JavaScript off
- [ ] Pages URL → four reps listed
- [ ] Queue → 53 accounts, band chips, reason sentences
- [ ] Detail → limits line present directly under the reasons
- [ ] Persistence notice at the top of every view
- [ ] Dispute → points drop, reason struck through with `→ 0 pts`, limits line changes
- [ ] Undo → score returns to exactly its original value

---

*Maker agent (AI-generated). Stage 3 of 4. Nothing in this runbook has been executed
against real hosting. Every URL is a placeholder. Claims about Render's behaviour are
cited to Render's own documentation where they were verified there, and are labelled
as inferences where they were not.*
