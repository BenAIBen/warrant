# Research Brief: The Trust Gap in Lead Scoring

**Prepared for:** Design stage (Unify — AI outbound/prospecting platform)
**Prepared by:** Researcher agent (AI-generated)
**Date:** 11 August 2026
**Status:** Sourced. Verified claims and inferences are labelled separately throughout.

---

## Executive summary

Unify is an AI-native outbound platform that ingests signals from 40+ sources, runs AI research agents on accounts, and fires automated Plays and Sequences. Reps receive prioritised work through a Tasks Dashboard. What Unify's **public** documentation does **not** contain — and I checked the docs index, the signals reference, the intent tutorials, the glossary and the changelog — is any named lead score, scoring model, fit grade or documented prioritisation logic. That is a material correction to the premise I was given, and it changes the shape of the design problem.

The design problem is not "add explanation to Unify's existing score." It is: **Unify already makes implicit prioritisation judgements — which signals fire, which accounts an agent researches, which task lands at the top of a rep's queue — and those judgements currently arrive with no visible reasoning attached.** Whether Unify ships an explicit score or not, the rep is being told "work this one first" by a system that does not say why.

The evidence on why that fails is strong and consistent. Gartner's 2026 sales research found 69% of B2B buyers turn to sales reps to validate AI-generated insights ([Gartner press release, 20 May 2026](https://www.gartner.com/en/newsroom/press-releases/2026-05-20-gartner-survey-finds-sixty-nine-percent-of-b-two-b-buyers-turn-to-sales-reps-to-validate-ai-generated-insights)) — the rep is the trust layer, so the rep needs a defensible reason, not a number. Practitioner post-mortems converge on transparency as the failure point: "a score of 82 in a HubSpot contact record tells an SDR nothing useful" ([Pedowitz Group](https://www.pedowitzgroup.com/blog/sales-doesnt-trust-your-lead-scoring-model.-heres-why-and-how-to-fix-it)). And the HCI literature is blunt: explanations increase acceptance of AI recommendations whether or not the AI is right ([Bansal et al., CHI 2021](https://dl.acm.org/doi/10.1145/3411764.3445717)), which means a badly designed explanation is worse than none.

The single most actionable finding for design: Dietvorst, Simmons and Massey showed people will use an *imperfect* algorithm if they can modify its output — even slightly ([Management Science 64(3), 2018](https://pubsonline.informs.org/doi/10.1287/mnsc.2016.2643); [preprint PDF](https://faculty.wharton.upenn.edu/wp-content/uploads/2016/08/Dietvorst-Simmons-Massey-2018.pdf)). Adjustability, not accuracy, is the adoption lever.

---

## 1. What Unify actually does today (verified)

**Positioning (verified, quoted verbatim from [unifygtm.com](https://www.unifygtm.com/)):**
- Headline: *"Outbound agents for every rep"*
- Subhead: *"Unify is an AI-native platform that frees your sellers from the administrative burden of outbound."*

**Product surface (verified from [unifygtm.com](https://www.unifygtm.com/), [unifygtm.com/signals](https://www.unifygtm.com/signals), and [docs.unifygtm.com](https://docs.unifygtm.com/llms.txt)):**

| Capability | What it is | Source |
|---|---|---|
| Signals | Website visitors, Champions (job moves), New Hires, Lookalikes; "40+ data sources, 100s of signals" | [docs — signals overview](https://docs.unifygtm.com/reference/signals/overview.md) |
| Agents | Generate *Observations* about companies/people, compiled into AI Research reports "for reference when engaging with prospects" | [docs — always-on research](https://docs.unifygtm.com/reference/agents/always-on-research.md) |
| Plays | Automated workflows triggered on signals | [docs — plays overview](https://docs.unifygtm.com/reference/plays/overview.md) |
| Sequences | Multi-channel email/call/social with personalisation and smart snippets | [docs — sequences](https://docs.unifygtm.com/reference/sequences/overview.md) |
| Data | 1.1B people, 65M companies | [unifygtm.com](https://www.unifygtm.com/) |
| Tasks Dashboard | Rep-facing prioritised work queue | [Unify for Sales Reps blog](https://www.unifygtm.com/blog/introducing-unify-for-sales-reps) |
| Dialer, deliverability, CRM sync | Native calling, mailbox management, Salesforce/HubSpot bidirectional sync | [docs — dialer](https://docs.unifygtm.com/reference/dialer/overview.md) |

**Company context (verified):** $40M Series B led by Battery Ventures, July 2025, at a reported $260M valuation, with OpenAI Startup Fund and Thrive participating; "growing revenue 8x in the last year" ([Unify blog](https://www.unifygtm.com/blog/series-b); [BusinessWire](https://businesswire.com/news/home/20250714813159/en/Unify-Raises-$40-Million-Series-B-to-Transform-Go-To-Market-with-AI)). Named customers include Cursor, Perplexity, Flock Safety, Airwallex, Together AI. G2 shows 4.7 stars across 43 reviews ([G2 seller page](https://www.g2.com/sellers/unify-515875da-a841-4cc5-aa01-52d20fb48ac3)); I could not fetch review bodies directly (403).

**The critical negative finding (verified by absence, across five separate documents):**
- The [docs glossary](https://docs.unifygtm.com/reference/glossary.md) defines Company, CRM, Custom event, Data lake, Data system, Data warehouse, Database, Event, Person, Play, Sequence. It does **not** define score, scoring, qualification, fit or priority.
- [Signals overview](https://docs.unifygtm.com/reference/signals/overview.md), [website visitors](https://docs.unifygtm.com/reference/signals/website-visitors.md) and [understanding intent data](https://docs.unifygtm.com/tutorials/website-product-intent/understanding-intent-data.md) contain no scoring, ranking or intent-strength mechanism.
- The [changelog](https://www.unifygtm.com/changelog) has no entry for lead scoring or prioritisation.
- The only score referenced anywhere is *external*: 6sense "account-level intent scores and buying stage predictions" arriving via [integration](https://docs.unifygtm.com/reference/integrations/6sense.md).

**My inference (flagged as inference):** Unify's prioritisation is currently *implicit* — expressed through signal firing, Play trigger logic, and Tasks Dashboard ordering — rather than expressed as a named score. Third-party reviews describe "ML algorithms to score leads," but these are affiliate/SEO pages ([SalesAlchemy](https://salesalchemy.co.za/unify-gtm-review-and-comparison/)), not Unify primary sources, and I would not treat them as verification. **If Unify does ship a score in-app that is not documented publicly, the design team must confirm this internally — I could not verify it.**

**Sourced product data point worth reusing:** Unify's own benchmark that *product usage signals show a 9.1% positive reply rate, the highest-performing signal type* ([Unify blog](https://www.unifygtm.com/blog/productusagesignals)). Note the framing: Unify already talks about signals in terms of *evidence of expected outcome*. That is the vocabulary the explanation layer should inherit.

---

## 2. Why reps ignore lead scores

**Finding 2.1 — The rep is the validation layer, so the rep needs an argument, not a number.** Gartner surveyed 645 B2B buyers and found 69% turn to sales reps to validate AI-generated insights; 51% of buyers say they are more likely to encounter misleading information from generative AI ([Gartner](https://www.gartner.com/en/newsroom/press-releases/2026-05-20-gartner-survey-finds-sixty-nine-percent-of-b-two-b-buyers-turn-to-sales-reps-to-validate-ai-generated-insights); methodology summarised at [CX Today](https://www.cxtoday.com/marketing-sales-technology/ai-sales-technology-workflows-buyer-journey-trends/)). A separate Gartner survey of 227 CSOs found organisations providing AI-enabled next best actions are 2.6x more likely to achieve commercial growth ([Gartner](https://www.gartner.com/en/newsroom/press-releases/2026-05-20-gartner-survey-finds-sales-organizations-that-provide-ai-enabled-next-best-actions-are-two-point-six-times-more-likely-to-achieve-commercial-growth)). **Read together: AI prioritisation pays off, but only where the seller can stand behind it in front of a buyer.**

**Finding 2.2 — Opacity, specifically, is the named failure mode.** The clearest practitioner articulation: *"a score of 82 in a HubSpot contact record tells an SDR nothing useful"* and *"if reps don't trust the scores, they'll ignore them and revert to working leads alphabetically or by submission time"* ([Pedowitz Group](https://www.pedowitzgroup.com/blog/sales-doesnt-trust-your-lead-scoring-model.-heres-why-and-how-to-fix-it)). Their recommended fixes are explicitly UI-level: surface score breakdowns showing individual signal contributions and point values in the record; connect alerts to outreach; track sales acceptance rate (they suggest 65–75% MQL-to-SQL as the health metric).

**Finding 2.3 — Definition mismatch, not model error.** The same source identifies the root cause as sales being absent from model design: marketing scores *activity* (opened emails, consumed content), sales qualifies on *problem fit, authority, and active evaluation*. The consequence is that "a high score does not mean a good lead" even when the model is statistically well-calibrated. **Design consequence: an explanation that cites marketing-shaped evidence will not repair trust; the reason must be phrased in the rep's qualification vocabulary.**

**Finding 2.4 — Vendors admit the black box in their own documentation.** HubSpot's own knowledge base states the model uses *"blackbox machine learning"* and that *"it's not possible to know exactly how each input contributes to a contact's score"* ([HubSpot Knowledge Base](https://knowledge.hubspot.com/properties/determine-likelihood-to-close-with-predictive-lead-scoring)). This is not a critic's characterisation; it is the vendor's.

**Contradiction to report, not resolve:** A widely repeated statistic — attributed to SiriusDecisions, that "68% of B2B companies use lead scoring but only 40% of salespeople get value from it" — surfaced in search results but I could **not** trace it to a primary SiriusDecisions/Forrester publication. Similarly, a "95% of salespeople say they receive low-quality leads from marketing" figure appeared attributed to HubSpot without a locatable primary source. **Do not use either number in product marketing or in the spec rationale.** The Gartner figures above are traceable to dated press releases and should be used instead.

**Gap in my evidence:** I attempted repeated searches for r/sales, RevGenius and Pavilion threads on lead-score distrust and did not surface citable primary threads through this tool. The practitioner evidence in this brief is therefore vendor-adjacent consultancy writing (Pedowitz Group, FlowRunner) rather than raw community voice. If the designer wants verbatim rep language for copy, that is a real remaining research task.

---

## 3. What makes an AI prediction trustworthy to a non-technical user

This section is where most "add explainability" specs go wrong, so the findings are ordered by how much they should constrain the design.

**3.1 — Explanations increase acceptance regardless of whether the AI is correct.** Bansal et al. ran mixed-method studies across three datasets with AI at roughly human-level accuracy. Explanations did **not** produce complementary team performance improvements over simply showing the recommendation plus confidence; they increased the chance humans accepted the AI's recommendation whether or not it was right ([Bansal et al., CHI 2021](https://dl.acm.org/doi/10.1145/3411764.3445717); [full PDF](https://idl.cs.washington.edu/files/2021-AIExplanationsTeamPerformance-CHI.pdf)). **Implication: an explanation UI that only justifies is a compliance device, not a trust device. It must also enable disagreement.**

**3.2 — More transparency can make people *worse* at catching errors.** Poursabzi-Sangdeh et al., pre-registered experiments with ~3,800 participants: increased transparency "hampered people's ability to detect when the model makes a sizable mistake and correct for it," apparently through information overload ([arXiv PDF](https://arxiv.org/pdf/1802.07810); [CHI 2021](https://dl.acm.org/doi/10.1145/3411764.3445315)). **Implication: show few reasons, not all reasons. Reason count is a design constraint with an empirical basis.**

**3.3 — Adjustability is the strongest known lever on adoption.** Dietvorst, Simmons and Massey: participants were considerably more likely to choose an imperfect algorithm when they could modify its forecasts, and performed better as a result. The effect held even when modification was *severely restricted*. Control, not accuracy, drove willingness ([Management Science, 2018](https://pubsonline.informs.org/doi/10.1287/mnsc.2016.2643); [PDF](https://faculty.wharton.upenn.edu/wp-content/uploads/2016/08/Dietvorst-Simmons-Massey-2018.pdf)). The companion paper establishes the baseline aversion: people abandon algorithms after seeing them err, even when the algorithm still beats humans ([Dietvorst et al., 2014](https://marketing.wharton.upenn.edu/wp-content/uploads/2016/10/Dietvorst-Simmons-Massey-2014.pdf)).

**3.4 — Feature attribution (SHAP/LIME) is not a trustworthy foundation on its own.** Krishna, Lakkaraju et al. interviewed 25 data scientists who all use LIME/SHAP daily and documented "the disagreement problem": different post-hoc explanation methods disagree on which features matter and in what order, and practitioners resolve this with ad hoc heuristics — meaning "practitioners may be relying on misleading explanations when making consequential decisions" ([arXiv 2202.01602](https://ar5iv.labs.arxiv.org/html/2202.01602)). Kaur et al. found that even data scientists over-trust and misuse interpretability tools, and few could accurately describe what SHAP/GAM visualisations were showing (contextual inquiry n=11, survey n=197; [CHI 2020](https://dl.acm.org/doi/10.1145/3313831.3376219)). **Implication: do not ship raw SHAP values, waterfall plots, or "contribution: +0.34" to an SDR. If experts misread them, reps will.**

**3.5 — Friction can be a feature.** Buçinca, Malaya and Gajos showed cognitive forcing functions — interventions that make the person engage analytically before seeing the AI answer — reduce overreliance on AI ([CSCW 2021, PDF](https://www.eecs.harvard.edu/~kgajos/papers/2021/bucinca21trust.pdf)). Trade-off is explicit in the paper: the designs that reduced overreliance were also rated least favourably by participants. **This is a real tension the designer must decide on knowingly, not stumble into.**

**Synthesis (my inference):** trustworthy-to-a-rep means (a) a *small number* of *per-case* reasons, (b) expressed as *evidence they can verify or quote*, not model internals, (c) with a *cheap disagreement action* attached. Global model explanations ("here is what the model weighs in general") satisfy RevOps but do nothing for the rep looking at one account.

---

## 4. Competitor teardown: scoring and explanation

| Vendor | What the score looks like | Does the rep see WHY? | Can the rep disagree? | Where it falls short |
|---|---|---|---|---|
| **Salesforce Einstein Lead Scoring** | ML score; ranks leads by similarity to prior converted leads | **Yes** — Einstein Score component shows "which of the lead's fields had the greatest influence on its score," positive and negative; hover on list view shows top factors | Not documented as an in-line action | Docs concede "fields that aren't listed in the Einstein Score component still influence the score, but less than the fields listed" — the explanation is admittedly partial. Rescored every 10 days, so the reason can be stale relative to what the rep is looking at. ([Salesforce Help](https://help.salesforce.com/s/articleView?id=ai.einstein_sales_lead_insights.htm&language=en_US&type=5); [Trailhead](https://trailhead.salesforce.com/content/learn/modules/lead-scoring-and-grading-in-account-engagement/einstein-scoring-in-account-engagement)) |
| **MadKudu** | Three models: Customer Fit (0–100, ⭐ segments), Likelihood to Buy (0–100, 🔥/❄️), Lead Grade (A–E). Each record shows "a segment, a score (0-100), an emoji" plus signals | **Yes** — "signals: a list of select positive and negative reasons that explain why the lead has been scored this way" | Admins can reorder/deprecate signals in Data Science Studio; not a rep-level action | **The most important competitor finding.** MadKudu documents that signals are *manually configured* and deliberately *not* a faithful reflection of model logic — "your full model's logic would be very confusing to expose; they are meant to be configured manually, as an explainer tool." The explanation is decoupled from the model. ([MadKudu Help — signals](https://help.madkudu.com/docs/tailoring-signals-in-madkudu-to-optimize-sales-enablement); [scores](https://help.madkudu.com/docs/what-are-the-different-scores)) |
| **HubSpot** | "Likelihood to close": percentage probability of closing within 90 days (score of 22 = 22% chance) | **No** — HubSpot's own docs: *"blackbox machine learning"*, *"it's not possible to know exactly how each input contributes to a contact's score"* | No | Requires substantial closed-won/closed-lost volume to train. Third-party analysis: "HubSpot does not expose per-contact feature weights or model explanations… the answer your team can give is 'the model said so.'" ([HubSpot KB](https://knowledge.hubspot.com/properties/determine-likelihood-to-close-with-predictive-lead-scoring); [FlowRunner](https://flowrunner.ai/blog/predictive-lead-scoring-hubspot/)) |
| **Common Room** | Rules-based, not ML. Fit rules + Behaviour rules, weights from "Very Important (10 points) to Very undesirable (-10 points)"; final score is a **percentile** vs all other records; refreshes every 4 hours | **Yes** — the UI shows "what key factors went into that score, so it's easy for users… to see what makes a profile valuable or not at a glance" | Admins edit rules directly; rep-level disagreement not documented | Percentile framing means the score is relative to the current population — a "90" means top decile today, which is not what a rep intuitively reads. Transparency is real but the model is hand-built, so it inherits the RevOps-vs-rep definition mismatch (Finding 2.3). ([Common Room Docs](https://www.commonroom.io/docs/set-preferences/scores/); [product page](https://www.commonroom.io/product/lead-scoring/)) |
| **Pocus** | PQL score combining customer fit, product usage, buying intent | **Yes, and it is the sharpest positioning in the set** — "Hover over scores in the list view to see why an account or user is high potential and worth engaging with… you don't waste time wondering what a PQL score of '100' or 'excellent' means" | No-code model editing: "add, select the attributes, and hit save to see how the scoring distribution changes" — but this is a RevOps/Growth action, not a rep action | Explanation is hover-only and lives in list view; the fix is aimed at ops being able to change the model, not the rep being able to register "this one is wrong." ([Pocus blog](https://www.pocus.com/blog/sneak-peek-at-pocus-product-led-sales-platform)) |
| **Apollo.io** | "AI-generated auto-score models" using CRM success data plus demographic/firmographic/behavioural data | Marketing claims "full visibility into the lead scoring criteria for every single lead" and "clear insight into how each lead is evaluated" | Custom criteria and weightings configurable | **Caveat I must flag:** I could not verify this from Apollo's knowledge base ([Scores Overview](https://knowledge.apollo.io/hc/en-us/articles/4988048582285-Scores-Overview) returned 403). The "reason codes" language appearing in search results traces to Apollo's SEO/insights pages, which are thought-leadership content, not product documentation. Treat Apollo's explainability as **claimed, not verified**. ([Apollo product page](https://www.apollo.io/product/scores)) |
| **Clay** | No native score. Reps/GTM engineers build point models in formula columns; Claygent can output a score with a reasoning field | Only if the builder designs it that way — the common pattern is a Claygent column with JSON output containing `score` and `reasoning` fields | Fully — because the user *is* the model author | Clay's own [account scoring page](https://www.clay.com/account-scoring) is headlined "Put account research on auto-pilot" and does not mention scoring reasons or transparency at all. Explanation quality is entirely delegated to whoever built the table. Reps consume the output; they did not build it and cannot inspect it. |

**Pattern across the set (my inference):** Everyone except HubSpot now ships *some* form of "why." But in every case the explanation is either (a) partial by admission (Einstein), (b) manually curated and deliberately decoupled from the model (MadKudu), (c) aimed at the ops user who edits the model rather than the rep who works the lead (Pocus, Common Room, Clay), or (d) claimed in marketing but unverifiable in docs (Apollo). **Nobody in this set gives the individual rep a first-class way to say "this reason is wrong" and have that change anything.** That is the unoccupied position.

---

## 5. Unify's specific gap — the trust gap, stated

> Unify has built a system that makes hundreds of implicit prioritisation judgements per rep per day — which signal fires, which account an agent researches, which task sits at the top of the Tasks Dashboard — and delivers every one of them as a bare instruction. The rep is told *what* to work and *when*, but never *on what evidence*, and has no way to push back on a judgement they know is wrong. This is not a feature gap; Unify's signal coverage and agent research are ahead of most of the field. It is a **credibility gap at the moment of handoff**: Unify's AI does the reasoning, then discards it before it reaches the human who has to act on it and, per Gartner, be the buyer's validation layer for it. Every competitor has partially closed this by bolting an explanation onto a score after the fact — MadKudu's are explicitly hand-written to be legible rather than accurate to the model. Unify's advantage is that it has not yet shipped a score, so it does not have to retrofit. It can make the *reason* the primary object and the *ranking* a consequence of it: the rep sees the evidence first, the priority second, and can dispute either.

---

## 6. Design implications (each traces to a finding above)

1. **Every prioritised item must carry per-lead reasons, not a global model explanation.** A "here's how our model works" page does not help the rep looking at one account. → §3 synthesis; §2.2 (Pedowitz: breakdowns *in the record*).

2. **Cap it at three to five reasons, ranked by contribution.** More transparency measurably degrades error detection through overload. Design a hard ceiling and a defensible truncation rule; do not build an expandable "show all 27 factors." → §3.2 (Poursabzi-Sangdeh et al.).

3. **Each reason must show the raw evidence value, not a model artifact.** "VP Eng viewed /pricing 3x on 9 Aug" — not "pricing_page_visits: +0.34" and never a SHAP waterfall. Experts misread attribution visualisations; reps will too. → §3.4 (Kaur et al.; Krishna et al.).

4. **Reasons must be phrased in the rep's qualification language, not marketing's activity language.** Problem fit, authority, active evaluation — not "engagement score." A reason that reads as marketing-shaped will be dismissed even when it is correct. → §2.3.

5. **Ship a first-class disagreement action on every reason and every ranked item.** Minimum: "not a fit / wrong person / bad timing / already working this," logged against the specific reason that fired. Explanations without a disagreement path increase acceptance of wrong answers as readily as right ones. → §3.1 (Bansal et al.).

6. **Give the rep a bounded ability to adjust their own queue, and make the adjustment visible.** Pin, demote, suppress a signal type for their patch. Even severely restricted modification is the strongest documented lever on willingness to use an imperfect model. This is the single highest-leverage requirement in this list. → §3.3 (Dietvorst et al.).

7. **Show negative reasons alongside positive ones.** Einstein already surfaces fields with negative influence. A one-sided justification reads as a sales pitch from the product; a two-sided one reads as an assessment. → §4 (Salesforce); §3.1.

8. **State the honest limit of the explanation in the UI.** Einstein's docs concede unlisted fields still influence the score. If Unify's reasons are top-N or partial, say so in one short line rather than implying completeness. Overclaiming is what makes the second wrong lead fatal to trust. → §3.4; §4 (Salesforce, MadKudu).

9. **Do not decouple the explanation from the actual decision logic.** MadKudu manually authors signals *because* the model is too confusing to expose. That is an honest workaround with a hidden cost: the reason a rep reads may not be the reason the system acted. If Unify hand-authors reason templates, the reason must be generated from the same evidence that triggered the action. → §4 (MadKudu).

10. **Timestamp and source every reason, and let the rep open the underlying evidence.** Einstein rescores every 10 days; Common Room refreshes every 4 hours. Stale evidence presented as current is a trust event, not a data event. Unify's agents already produce *Observations* with underlying research — surface them as the clickable substrate of the reason. → §1 (Unify agents); §4 (Salesforce, Common Room).

11. **Make disagreement measurably change something, and instrument it.** Track reason-level dispute rate and the rate at which reps act on top-ranked items. Pedowitz Group's proposed health metric is sales acceptance rate (they suggest 65–75% for MQL→SQL); the analogous Unify metric is task acceptance and reason-dispute rate. If a disagreement changes nothing, reps stop registering disagreements within weeks. → §2.2; §3.3.

12. **Decide deliberately whether to introduce friction, and document the choice.** Cognitive forcing reduces overreliance but participants disliked it. For high-value accounts a "review evidence before enrolling" step may be warranted; for volume outbound it almost certainly is not. Do not leave this implicit. → §3.5 (Buçinca et al.).

---

## Appendix: what I could not verify

- **Whether Unify has an in-app score at all.** Verified absent from public docs, glossary, signals reference, intent tutorials and changelog. Third-party review sites claim ML lead scoring; those are not primary sources. **The design team must confirm this internally before the spec is written.**
- **Apollo's explainability.** Knowledge base returns 403. "Reason codes" language traces only to Apollo's own SEO content, not documentation.
- **Unify G2 review bodies.** g2.com returns 403 to this tool. Aggregate rating (4.7, 43 reviews) and secondary summaries of complaints (learning curve, credit-based pricing opacity, 2–4 week setup) are second-hand. Note one likely-stale contradiction: some summaries cite "no native calling tool," but Unify's docs now document a [native dialer](https://docs.unifygtm.com/reference/dialer/overview.md).
- **The "66% of sales leaders report low trust in AI-generated insights" figure.** Appeared in a search summary attributed to [Gartner's "AI for Sellers" article](https://www.gartner.com/en/articles/ai-for-sellers), which returns 403. **Not verified — do not cite.** Use the traceable 69%/2.6x press-release figures instead.
- **The SiriusDecisions "68% use / 40% get value" and HubSpot "95% low-quality leads" statistics.** No traceable primary source found. Do not use.
- **Community voice (r/sales, RevGenius, Pavilion).** Not surfaced through this tool. Verbatim rep language for microcopy remains an open research task.
