# SITE_COPY.md — landing page copy for `docs/index.html`

**Audience:** anyone who lands on the Pages URL — a Unify rep evaluating the idea, a hiring manager, a stranger who got a shared link. Assume they know nothing about Warrant going in.

**Status note:** nothing described here is deployed. The Pages URL is `https://<your-username>.github.io/<repo>/` — a placeholder until a repo and a Render service actually exist. This file is the copy that goes on that page once it does; it is not itself a claim that the page is live.

**Placement:** `docs/index.html` currently has a header (`#chrome` — title, subhead, persistence notice, nav, all populated or shown by `app.js`) and a `<main id="view">` that `app.js` paints entirely — there is no static body copy in the file today. The blocks below are written to slot in as: (1) subhead / intro copy near `#chrome-sub`, sitting above where the rep picker renders, and (2) short standing copy that stays visible regardless of route, since a stranger could land on any hash URL, not just `#/`. None of this replaces the dynamic persistence notice at `#persistence-notice` — that element already carries the server's own live wording (`meta.persistence_notice`) and should keep doing that; the copy below is the static framing around it.

---

## 1. Hero / intro (sits above the rep picker)

**Warrant**
Reason-first prioritisation.

This is a working demo of the scoring mechanism, not a customer list. All 240 companies and 1,354 people you'll see here are synthetic — generated from word pools under a fixed seed for this build. None of it is a real prospect or a real company. What's real is the arithmetic: every score on this page is computed live against a real database, on the same code path that would run against real CRM data.

## 2. Cold-start warning (standing copy, visible before the first click, not just after)

This runs on free hosting. If nobody's used it in the last 15 minutes, the backend has gone to sleep, and your first click can take up to a minute to get an answer while it wakes back up. You'll see a "waking the demo server" message with a counter running — that's the free tier working as designed, not something broken. Everything after that first click is fast.

*(This duplicates, in landing-page framing, what `app.js`'s `wakingPanel()` already says mid-wait — "Warrant runs live SQL over a real database at the moment you load a page... The server sleeps after 15 minutes of no traffic, so the first visit pays for starting it up." Repeating it here means a visitor reads it before they click, not only if they're patient enough to wait it out.)*

## 3. What's different about the score

Most lead scores hand you a number, then a paragraph explaining it after the fact — two things that can drift apart, and usually do. Here the reasons aren't a description of the score, they're the score: every point on the page is the output of a reason you can read, and adding up the visible reasons gets you the visible total. There's no other number underneath it.

## 4. Where to start

Pick a rep, open their queue, then click into any account — that's where the actual product is. The account page breaks the total into individually dated, sourced reasons, each with a "see evidence" link, a category tag, and its own point value. It also tells you plainly what it isn't showing you (a line like *"showing the 5 strongest of 10 signals — the rest are worth +27 pts combined"*), so the total is never a mystery. Try the dispute button on a reason — "this is wrong" or "out of date" — and watch it stay in place, struck through, with the score recalculated on the next screen. Nothing gets silently deleted or swapped out.

## 5. One honest limitation

Nothing you file here survives a restart. Pin an account, mute one, dispute a reason — it's real and it works, held in a live database while the backend is running. But that backend is a free container with no persistent disk, and every time it spins down or redeploys, that data is gone. If you come back later and your dispute has vanished, that's the free-tier architecture doing exactly what it was built to do, not a bug.

---

### Word-for-word source check

Every factual claim above is grounded in what was actually built and verified, not aspirational:

- Synthetic corpus counts (240 accounts, 1,354 people) — `README.md`, `DEPLOY_ARCHITECTURE.md` §3.4 `GET /api/health` sample payload.
- 15-minute sleep / ~60-second wake — `DEPLOY_ARCHITECTURE.md` §1.1, §1.2 cost #2; the exact wording is mirrored from `docs/app.js::wakingPanel()`.
- "The reasons are the score" — `warrant/scoring.py` docstring, quoted directly in `DEPLOY_ARCHITECTURE.md` §2.2 and `ANNOUNCEMENT.md`: *"the score is `sum(c.points)` and the reasons are `render(c)` over the same list."*
- Limits line wording — `DEPLOY_ARCHITECTURE.md` §3.7 sample response, `limits_line` field.
- Dispute behavior (struck through in place, not removed) — `docs/app.js::reasonNode()`, and demonstrated in `ANNOUNCEMENT.md`'s Harbour Technologies example.
- Non-persistence — `DEPLOY_ARCHITECTURE.md` §1.2 cost #1, §3.2 `persistence_notice`.
