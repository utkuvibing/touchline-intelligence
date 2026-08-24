# The shot-quality number, explained for a coach — and where to stop trusting it

> **Status: published in the repository.** Written 2026-08-24 as the non-technical companion to
> the [technical write-up](wp4_1-shot-quality-write-up.md); reviewed and linked from the README
> on 2026-08-25 as part of WP4.4.

**Live app:** https://touchline-intelligence.vercel.app
**Repository:** https://github.com/utkuvibing/touchline-intelligence

## What the number is

For any recorded shot, the model estimates exactly one thing: **the chance that this shot becomes a
goal**, judged only on what was true at the moment it was struck — how far from goal it was taken,
how much of the goal the shooter could actually see, whether it was hit with foot or head, and the
kind of situation it came from (open play, counter-attack, free kick).

It does not know who the shooter was, who the opponents were, what the score was, or which minute it
was. That is deliberate: the number describes the *opportunity*, not the person taking it; finishing
skill above or below that baseline is left to your judgement.

Two things it is not. It is **not StatsBomb's expected-goals model**: this project builds its own
number from open event data, the provider's commercial xG values are removed before storage, and a
database constraint keeps them away from the model. And it is **not a prediction
about a named player or team**.

## How it was built, without formulas

The model learned in three stages, each on matches the later stages never saw:

1. **Learn the game.** It studied **2,872 shots from 115 matches** — every match of World Cup 2018
   and Euro 2020. Here it picked up the football: chances close to goal and straight in front
   convert far more often than efforts from distance or tight angles; counters create better looks
   than corners; headers score less than feet from the same spot.
2. **Adjust the quotes.** On World Cup 2022 (64 more matches), a small correction was fitted so that
   the quoted chances line up with what actually converted — if the model calls a group of chances
   "30%", about three in ten of them should go in.
3. **One exam, taken once.** Finally it faced Euro 2024 — 51 matches it had never influenced. No
   feature, no tuning, no calibration decision came from that tournament. It was scored a
   single time, after everything else was frozen.

One honesty note about that exam. Euro 2024 was locked but never fully blind: earlier descriptive
work had already published aggregate counts — total goals per tournament among them — before the
splits were fixed. What the lock guarantees is narrower and still real: the tournament influenced no
model, feature, calibration or selection decision, and was scored exactly once, after everything
else was decided.

## Where the number earns your trust

- **It sorts chances sensibly.** Ordered from most to least promising, better chances generally land
  above worse ones — and that held on the tournament it had never shaped.
- **Its lessons match football judgement.** One typical step closer to goal roughly doubles the
  scoring odds; a clearer view of the goal helps by a similar amount; a header converts at roughly
  half the odds of an otherwise identical right-foot finish. Chances from counters outperform open
  play; chances from corners underperform it.
- **Calibration holds broadly, not finely.** On the data it was fitted and adjusted on, groups of
  chances rated at a similar level converted close to that level on average. The evidence is thin —
  few well-populated chance bands support it — so read the number as an average over many shots,
  not a per-band guarantee.

## Where it should not be trusted

- **The final correction backfired slightly on the exam.** On Euro 2024, the adjusted version scored
  a little worse than the unadjusted one on a measure that punishes confident mistakes (0.2431
  against 0.2393 — lower is better). Both results are published side by side. The adjusted version
  ships anyway because the choice was frozen before the exam; changing it after seeing the result
  would turn a one-time test into a second round of tuning, precisely what this process exists to
  prevent.
- **Fine distinctions are shaky.** Nearly all chances land below 20%, and small percentage-point
  differences should not be overinterpreted; separating a tap-in from a long-range effort is not
  the same problem.
- **Its world is four tournaments.** Men's World Cups 2018 and 2022, Euros 2020 and 2024 — nothing
  else. League seasons, women's internationals, club football and other providers are outside
  what these numbers describe.

## What not to do with it

- **Do not say "he should have scored."** A genuine 70% chance misses roughly three times in ten.
  The number measures the situation, never the player.
- **Do not use it for recruitment, tactical verdicts or betting reasoning.** It supports describing
  chances, not decisions about people or games.
- **Do not expect row-level predictions in public.** While source data terms remain unclear, the
  deployed interface shows recorded World Cup 2022 outcomes only; historical model rows stay closed.
- **Do not blur the products.** The model is built on event data — what happened, where, and with
  which body part — not on continuous tracking. It models no off-ball movement, and its number is
  not anyone's proprietary xG.

## Where every number comes from

Every figure above traces to committed evidence: the [Model Card](../../MODEL_CARD.md), the
[technical write-up](wp4_1-shot-quality-write-up.md), and the per-work-package reports in the
repository's [`reports/`](../../reports) directory.

Data provided by [StatsBomb](https://statsbomb.com).
