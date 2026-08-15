# SITE_COPY.md — landing page copy for `docs/index.html`

**Audience:** anyone who lands on the Pages URL — a Unify rep evaluating the idea, a hiring manager, a stranger who got a shared link. Assume they know nothing about Warrant going in.

**Status note, updated 15 August 2026:** this originally described a placeholder Render deployment. The actual deployment ended up on **PythonAnywhere**, not Render — Render's live signup flow demanded a card despite its own docs saying that's optional, so the project moved to a card-free host instead (`DEPLOY_ARCHITECTURE_PYTHONANYWHERE.md` §0). This changes two real facts below, marked where they occur: **PythonAnywhere's free tier does not sleep**, so the cold-start warning in §2 no longer applies and has been struck through rather than deleted, so the reasoning trail stays visible; and **PythonAnywhere's disk is persistent**, so §5's "nothing survives a restart" claim is now the *opposite* of what's true and has been rewritten. This copy is now live, integrated into `docs/index.html` directly, at `https://benaiben.github.io/warrant/`.

**Placement:** implemented as a new `<section id="intro">` between `</header>` and `<main id="view">` in `docs/index.html` — outside the `#view` element `app.js` repaints on every route, so it survives navigation untouched (`app.js`'s `view()` function only ever targets `#view` by ID; confirmed by reading the file before writing this). It appears on every screen, not only the landing route. None of this replaces the dynamic persistence notice at `#persistence-notice` — that element still carries the server's own live wording (`meta.persistence_notice`, which is `null` on this deployment because nothing needs disclosing) — the copy below is the static framing around it.

---

## 1. Hero / intro (sits above the rep picker)

**Warrant**
Reason-first prioritisation.

This is a working demo of the scoring mechanism, not a customer list. All 240 companies and 1,354 people you'll see here are synthetic — generated from word pools under a fixed seed for this build. None of it is a real prospect or a real company. What's real is the arithmetic: every score on this page is computed live against a real database, on the same code path that would run against real CRM data.

## 2. ~~Cold-start warning~~ — struck, does not apply on the actual deployment

~~This runs on free hosting. If nobody's used it in the last 15 minutes, the backend has gone to sleep, and your first click can take up to a minute to get an answer while it wakes back up.~~

**This was written for Render, which sleeps after 15 minutes of inactivity. The actual deployment is on PythonAnywhere, which does not sleep** (`HOSTING_RESEARCH.md` §2.11: "Sleeps? No"). Left here struck through rather than deleted, so a reader can see the reasoning changed rather than silently vanishing. **Not implemented in `docs/index.html`** — there is no cold-start section on the live page, correctly, because there is nothing to warn about.

## 3. What's different about the score

Most lead scores hand you a number, then a paragraph explaining it after the fact — two things that can drift apart, and usually do. Here the reasons aren't a description of the score, they're the score: every point on the page is the output of a reason you can read, and adding up the visible reasons gets you the visible total. There's no other number underneath it.

## 4. Where to start

Pick a rep, open their queue, then click into any account — that's where the actual product is. The account page breaks the total into individually dated, sourced reasons, each with a "see evidence" link, a category tag, and its own point value. It also tells you plainly what it isn't showing you (a line like *"showing the 5 strongest of 10 signals — the rest are worth +27 pts combined"*), so the total is never a mystery. Try the dispute button on a reason — "this is wrong" or "out of date" — and watch it stay in place, struck through, with the score recalculated on the next screen. Nothing gets silently deleted or swapped out.

## 5. One honest limitation — this changed direction entirely, corrected below

~~Nothing you file here survives a restart... that data is gone.~~ **This was true for the Render path and is now the opposite of true.** PythonAnywhere's disk is persistent. Rewritten, and this is the version live in `docs/index.html`:

> Anything you file here — disputes, pins, mutes — stays until someone deliberately resets the demo. This runs on a host with a real persistent disk, not a container that forgets everything on restart.

This isn't a hopeful claim — it was proven directly, live, on the real deployed backend: a dispute was filed against Cobalt Freight (73.89 → 57.89 points), the PythonAnywhere worker was reloaded (a genuinely different process — `boot_id` changed from `320da2aa` to `becebd6f`), and the dispute, the suppression note, and the exact points figure all survived unchanged. That's the entire reason this path exists over Render's.

Two other honest limitations still stand and are live in `docs/index.html`'s `.caveat` box: 18 of 19 weights are reasoned, not measured, and the reason wording has never been read by a salesperson.

---

### Word-for-word source check

Every factual claim above is grounded in what was actually built and verified, not aspirational — updated 15 August 2026 to match the actual PythonAnywhere deployment:

- Synthetic corpus counts (240 accounts, 1,354 people) — confirmed live via `GET https://benaiben.pythonanywhere.com/api/health`, not just documentation.
- PythonAnywhere does not sleep — `HOSTING_RESEARCH.md` §2.11.
- "The reasons are the score" — `warrant/scoring.py` docstring, quoted in `ANNOUNCEMENT.md`: *"the score is `sum(c.points)` and the reasons are `render(c)` over the same list."*
- Dispute behavior (struck through in place, not removed) — `docs/app.js::reasonNode()`, and demonstrated in `ANNOUNCEMENT.md`'s Harbour Technologies example.
- **Persistence across a real restart** — proven live, not inferred: dispute filed via `POST /api/dispute` on the real backend, PythonAnywhere worker reloaded via the dashboard, `boot_id` confirmed changed, dispute confirmed intact via `GET /api/account/12?rep=1` afterward.
