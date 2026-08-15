# Warrant: your queue now has to explain itself

**For:** AEs and SDRs
**What it is:** a prioritised account queue where every item comes with a dated, sourced case for working it — and a button to tell it it's wrong.

You have been handed scores before. A "lead score of 82" sat in a record and told you nothing you could repeat on a call, and when it was wrong there was nowhere to put that. HubSpot's own docs admit their model is a black box and that you can't know how any input moved the number. You were right to ignore it.

Warrant is built the other way round. The reasons aren't an explanation bolted onto a score — the reasons **are** the score. Every point on screen came from a reason you can read, and every reason you can read is worth points you can add up.

---

## What changes on Monday

Open your queue. You get your patch, ranked, with the strongest reason for each account printed on the row — not a number you have to interpret.

```
105 pts  2. ACT NOW  Harbour Technologies
    CMO and 3 others used the product across 5 sessions, most recently 7 days ago.
    evidence 0d old                              5 of 11 signals shown
    ( Work it ) ( Not now ) Dispute
```

Click the account and you get the full case: each reason with its category (fit, authority, active evaluation, timing, disqualifier), the dates behind it, where it came from, and what it's worth. On Harbour that includes the negative:

> **These signals disagree.** CMO and 3 others used the product across 5 sessions, most recently 7 days ago, but Noor Belic, our contact here, left on 3 Aug 2026. Read both before you act.

That line is generated, not written by anyone. When the evidence points both ways, the screen says so before you dial.

---

## What the number means — and what it doesn't

**It is not a probability of closing.** It is not a percentile. It is not out of 100. It is a weighted count of evidence, and that's all it claims to be.

Points sit against a fixed bar of **75** — the total a strong, current, multi-signal account reaches. So 105 pts reads as "well above the bar", and the page says `(above anchor)`.

Four bands:

| Band | Read it as |
|---|---|
| **ACT NOW** | Multiple current signals and someone who can sign. Work it today. |
| **REVIEW** | Real signals, but thin, old, or contradicted. Read the evidence before you spend time. |
| **HOLD** | Something is here. Not enough to act on. |
| **NOT ENOUGH TO SAY** | We don't know enough about this account to rank it. That's a gap on our side, not a verdict on theirs. |

A thin account can't be promoted into ACT NOW on points alone — low confidence caps it at REVIEW. The system can talk itself down, never up.

---

## Why you can check it rather than take it on faith

- **Every reason is dated and sourced.** "7 sessions between 19 Jul 2026 and 3 Aug 2026 · source: product telemetry".
- **You can open the evidence.** The drawer lists every underlying event, who it was, when it happened, and when we actually ingested it — so you never say "they visited today" when they visited yesterday.
- **It tells you what it's hiding.** Every account carries one line like: *"Showing the 5 strongest of 11 signals. The 6 not shown are worth +50.3 pts combined; they do not change the band."* You're never left wondering whether the numbers on screen add up to the total.
- **Caps are disclosed inline.** `+24 pts (capped at 24)` — so two accounts with very different usage don't quietly show the same figure with no explanation.

---

## When you disagree — this is the part that matters

Seven buttons. Five on the item: **Not a fit · Wrong person · Bad timing · Already working this · Not my patch**. Two more on each individual reason: **This is wrong · Out of date**.

None of them are a suggestion box. Every one does something mechanical and visible on the very next screen. Here's a real one from the build:

```
Harbour Technologies — 105 pts, rank 2 of 53
  → you hit "this is wrong" on the product-usage reason
Harbour Technologies —  81 pts, rank 6 of 53
  was 105 pts before your disagreement
  ~~CMO and 3 others used the product across 5 sessions...~~
  You said this was wrong on 11 Aug 2026. Not counted here until 9 Nov 2026.
  ( undo )
```

Note what happened: the reason stayed on screen, struck through, in its own slot. It wasn't deleted and it wasn't quietly replaced by the next reason down. You can see the thing you objected to is the thing that went away. Hit undo and it's back at 105 immediately.

Four things to know:

1. **It only touches your queue.** Nothing you do changes a colleague's list or the weights behind the model. Your input reaches the weights only through aggregate numbers RevOps reviews.
2. **Everything expires.** Suppressions, pins, demotes, mutes — all have a return date printed on them. Nothing you set is permanent, and nothing runs silently forever.
3. **There are budgets:** 5 pins, 10 demotes, 3 patch-wide signal suppressions (plus 50 account-level ones, 25 mutes). Hit the ceiling and you get refused, not silently overwritten: *"You already have 5 pins. They expire on their own — your oldest expires on 23 Aug 2026 — or undo one now."*
4. **One bit of friction, on purpose.** If you've already disputed something on an account, `Work it` is disabled until you open one evidence drawer. That's about 3 items in a 53-account queue, not a tax on your day.

---

## What it won't do, and where it's still rough

Straight, because you'll find this out anyway:

- **The data in this build is synthetic.** The arithmetic is real and runs live; the accounts are generated. Nothing here is a real prospect yet.
- **18 of the 19 weights are reasoned, not measured.** Only one traces to actual evidence: product usage carries the heaviest weight because Unify's own benchmark puts product usage signals at a **9.1% positive reply rate**, the highest-performing signal type. The rest are considered judgements. The ruleset page says which is which.
- **It is not calibrated against closed-won.** There's no outcome data behind it yet. That's exactly why it doesn't quote you a percentage chance of closing — that would be a made-up number you'd end up repeating to a buyer.
- **The wording of the reasons has never been read by a salesperson.** Every sentence you see was written by the designer. If a reason reads like software talking rather than like you talking, that's the single most useful thing you can tell us.

## What we're asking

Work your queue normally. When it's wrong, press the button instead of scrolling past — a skip with no reason attached tells us nothing, and it's the one thing that stops this getting better. And send us any reason sentence that sounds off. That one's on us to fix.
