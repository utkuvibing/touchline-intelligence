# M5 phase 4: lean validation and M8 product scope (WP5.4)

**Status:** accepted planning contract; implementation is underway within the boundaries below.
**Planning review:** `PASS` on 2026-08-26 for validation-risk regression and M8 scope/data-use
boundaries.
**Authority:** this tracked document will own the accepted WP5.4 decision. `docs/PLAN.md`, Post-M4
Roadmap, M5 work items 9-11, remains the roadmap context. Ignored local copies are scratch only.
**Depends on:** WP5.1's v1 freeze and sealed-set controls, WP5.2's accepted v2 protocol, and
WP5.3's production-gap work.

## Purpose

WP5.4 removes process that no longer pays for itself before M6 adds a new feature system. It also
turns the two M8 product ideas into testable tasks. This work package does not change the model,
open a sealed tournament, alter the deployed API, or build either M8 workflow.

The repository currently has one ordinary backend check command, separate frontend checks, an
image-build job, opt-in reproducibility checks, deployed smoke checks, and a mutation runner with
350 fault injections. The problem is not a lack of checks. The problem is that release evidence,
historical reproduction, mutation testing, and ordinary pull-request feedback have accumulated
without a short statement of which check belongs at which decision point.

## Outcomes

WP5.4 plans three changes for a later implementation pass:

1. publish one executable validation matrix with pull-request, milestone, and release tiers;
2. preserve the current mutation catalog as history, then use a fixed budget of 20 slots: 15 active
   sentinels and 5 reserved for M6-M8; and
3. freeze task-level specifications and usability tests for Chance Lab and user-supplied Match
   Review.

The implementation pass must prefer edits to existing commands and documents over a new validation
framework. It must not create per-work-package release packets or hash prose and presentation files.

## Work packages

### 5.4.1 Validation inventory and ownership

Build a machine-checked inventory from the commands that exist when implementation starts. For each
check, record:

- the behavior or risk it protects;
- the tier that runs it;
- its trigger, command, prerequisites, and expected duration;
- whether it reads a database, writes a local database, calls a deployment, or needs secrets;
- the evidence retained after a pass or failure; and
- the condition that permits a skip.

The inventory must distinguish a reachable empty PostgreSQL database from a populated pinned-cohort
database. It must also distinguish event data, event-embedded shot freeze frames, and source-file
acceptance. No validation command may point at a deployed database for writes.

### 5.4.2 Three validation tiers

The later implementation pass will expose one documented entry point per tier. Existing focused
commands may remain underneath those entry points.

The tier principle is short on purpose. **Pull requests prove code health. Milestones prove
scientific and contract integrity. Releases prove reproducibility and deployability.**

| Tier | Trigger | Required scope | Deliberately excluded |
|---|---|---|---|
| Pull request | Every change proposed for merge | Formatting, lint, strict types, backend and frontend unit/contract tests, fixture-backed integration tests, affected image/package checks | Full pinned cohort, sealed outcomes, mutation catalog, deployed recovery |
| Milestone | Before M5, M6, or M7 closes | Pull-request tier plus affected full-cohort or full-source acceptance, clean reproducibility checks, frontend production build, packaged serving-bundle checks, and the retained mutation set | Sealed-set scoring before the authorized M7 run, deployed state changes |
| Release | Before a production release or release rotation | Milestone tier plus broader mutation validation, clean image/build proof, artifact and provenance verification, local-to-production golden parity, deployed smoke, rollback/recovery rehearsal, dependency review, and independent methodology/security review where the changed boundary requires it | Prose hashes, presentation hashes, duplicated work-package evidence packets |

Rules for the matrix:

- A narrower tier may call the same command as a broader tier. The matrix must not copy test logic.
- Pull-request checks stay fast enough for ordinary feedback. Slow, data-dependent proof moves to a
  named milestone or release command, never to an undocumented manual checklist.
- Authoritative model, data, split, calibration, and serving artifacts remain hash-verified.
  Editorial Markdown and presentation files do not become release inputs.
- A skipped check reports its missing prerequisite and the effect of the skip. It cannot appear as
  a pass.
- The matrix names which checks are safe on a dirty working tree and which require a clean tree.
- M7's one-time external qualification remains a supervised protocol action, not a validation-tier
  command.

Likely files for the implementation pass include `pyproject.toml`, `frontend/package.json`,
`.github/workflows/ci.yml`, `docs/DEVELOPMENT.md`, and one focused validation-matrix document. This
list is a starting point, not permission for speculative build infrastructure.

### 5.4.3 Mutation-catalog archival and retained set

The current 350-injection runner is historical evidence. The implementation pass must preserve a
recoverable identity for it before slimming the executable set. A compact archive record should
name the last commit containing the full catalog, the runner path, prerequisites, injection count,
and the latest trustworthy result if one exists. Git history is the archive. Do not copy hundreds
of mutation definitions into a new document or generated artifact.

The retained budget is exactly 20 slots. Fifteen are active milestone sentinels. Five stay empty for
new M6-M8 risks until a reviewed boundary needs them. A reserved slot becomes active only through a
recorded risk decision. The total cannot exceed 20.

Select the 15 sentinels by risk, not by work-package quota or ease of mutation. The set must cover
all of these boundaries:

- leakage and data access, including provider xG and sealed rows;
- split construction and evaluation permissions;
- geometry and feature semantics, missingness, and fold-local preprocessing;
- provenance and model, calibration, split, and serving-artifact integrity;
- API validation and fail-closed error behavior;
- historical publication and data-use gates;
- database write safety, transaction rollback, and read-only checks; and
- offline, packaged, and deployed serving parity.

Rank candidates by impact, likelihood of silent failure, limits of ordinary tests, and the breadth
of the protected boundary. Keep the smallest mutation that proves the guard fails when removed.
Retire or replace a sentinel when its risk disappears, an ordinary direct test makes it redundant,
it duplicates a stronger sentinel, or its source anchor becomes brittle without protecting a real
failure. Every retirement records the protected risk, replacement or reason for no replacement,
and the release that made the decision. Retirement never rewrites the historical result.

The 15-sentinel set is a milestone check, not the only long-term mutation defense. At release tier,
run a broader risk sweep against the current release candidate. Reconsider applicable cases from
the archived catalog and add temporary mutations for changed critical boundaries. This one-release
sweep is not limited by the 20 retained slots because temporary cases do not join the standing set.
Its report must list the assessed boundaries, every mutation and its applicability, caught, missed,
or not-run status, and any proposed sentinel promotion or retirement. A missed or unrun high-risk
case blocks release. Do not run an old mutation against old code and call that current-release
evidence.

Both mutation runs must fail closed on missing database prerequisites, ambiguous anchors, invalid
mutations, or a byte-for-byte restore failure. "Not run" cannot satisfy milestone or release
acceptance.

### 5.4.4 Chance Lab task specification

Chance Lab answers one question: how does the qualified Touchline model's estimate change when an
analyst changes supported shot inputs?

The M8 implementation must let a user:

1. place a shot on a StatsBomb 120 by 80 pitch;
2. set only fields in the qualified release's serving contract;
3. create a second scenario from the first and change one or more supported inputs;
4. compare both probabilities, absolute change, and relative change; and
5. copy a URL that restores the two scenarios without server-side storage.

The workflow must show the active model and release identity. It must label the output as a
Touchline model estimate, not provider xG. Scenario differences are associations under the model,
not causal or counterfactual effects. It must not produce team, player, or tactical ratings. It may
use only a released, validated feature contract, and it must not reconstruct historical rows or
bypass the historical-publication gate. If the qualified release is additive logistic regression,
the interface may show grouped contribution changes. Otherwise it must use bounded sensitivity
summaries and avoid a fake additive explanation.

Task-level usability test:

- Give five target users a starting scenario and one football question that requires a comparison.
- Count completion only when the user creates the second scenario, changes the requested input,
  identifies the direction and size of the probability change, and copies a restorable URL.
- At least four of five users must finish without coaching, with a median time below five minutes.
- At most one user may call the result StatsBomb xG, and at most one may interpret the change as a
  causal effect.
- Keyboard-only completion must work, and automated accessibility checks must report no serious
  violation.

WP5.4 freezes the task and measurement method, not screen layout, component structure, or final
copy. M8 may adjust those details without changing the success rule.

### 5.4.5 User-supplied Match Review task specification

Match Review answers a different question: where were the strongest and weakest chances in a shot
file supplied by the analyst?

The M8 implementation must:

- publish one versioned CSV template derived from the qualified release input contract;
- accept at most 500 shot rows;
- validate the file locally before upload and show row and field errors;
- send only a valid bounded batch for inference;
- store neither uploads nor predictions after the request;
- keep uploaded rows, feature values, and predictions out of application logs;
- return a shot map, team chance totals, chance-quality distribution, highest-quality chances, and
  a downloadable prediction file; and
- show model identity, source attribution, input limitations, and the distinction from provider xG.

The template must not accept a target, recorded outcome, provider xG, player identity, or fields the
active release does not consume. User-supplied rows must never be joined to or reconstructed from
StatsBomb historical event rows. Match Review must not produce causal or counterfactual claims or
unsupported team, player, or tactical ratings. Only a released, validated feature contract may
reach product behavior. The existing historical publication gate remains closed and no M8 route may
bypass it.

Task-level usability test:

- Give the same five target users a valid fixture CSV plus a second file containing declared row
  errors.
- Count completion only when the user corrects or explains the invalid file, processes the valid
  file, identifies its highest-quality chance, and downloads the results.
- At least four of five users must finish without coaching, with a median time below five minutes.
- At least four must correctly identify the highest-quality chance.
- At most one user may confuse the output with provider xG.
- Keyboard-only completion must work, and automated accessibility checks must report no serious
  violation.

M8 must separately verify the roadmap's performance target for a 500-row batch and its request and
rate limits. User testing does not replace load, security, or retention checks.

### 5.4.6 Scope lock and M8 handoff

The M8 product scope is Chance Lab and user-supplied Match Review only. WP5.4 must record rejected
additions so they do not return as hidden requirements: accounts, saved workspaces, collaboration,
public historical row browsing, PDF generation, mobile apps, live-match feeds, player search, team
dashboards, and commercial billing.

The handoff must leave these decisions open until M7 qualifies the active release:

- the final input columns and category vocabulary;
- whether grouped additive contributions are valid;
- whether v1 or v2 supplies production predictions; and
- exact probability labels tied to the selected calibration policy.

Open release-dependent details must not block the task contracts. M8 binds them to the immutable
qualified serving contract after M7.

## Planning review gate

Before this plan becomes accepted, one lightweight independent adversarial review must inspect the
actual document. The review asks two questions: could validation slimming remove protection from a
high-risk boundary, and could either M8 workflow exceed the agreed scope or data-use permissions?
It returns `PASS` or `CHANGES_REQUIRED`. WP5.4 cannot move to implementation until it returns
`PASS`.

## Sequence for the later implementation pass

1. Capture the current validation and mutation inventory without changing commands.
2. Write and review the validation matrix.
3. Add the three tier entry points and align CI and contributor docs.
4. Record the full mutation catalog's historical identity, select the retained set, and verify every
   retained injection in an environment with all declared prerequisites.
5. Publish the Chance Lab and Match Review specifications and their test scripts or observation
   forms.
6. Run the pull-request tier, the affected milestone checks, and the documentation-link check.
7. Review the diff for accidental model, data, deployment, or sealed-set changes.

Steps 3-6 are implementation work and are outside this planning change.

## Acceptance criteria

WP5.4 implementation is complete only when:

- one documented and executable matrix maps every retained check to exactly one minimum tier;
- local commands and CI agree on the pull-request tier;
- milestone and release tiers state their data, secret, clean-tree, and deployment prerequisites;
- authoritative model and data artifacts remain hash-verified while prose and presentation hashes
  are absent from new release criteria;
- the historical 350-injection catalog is recoverable by commit identity;
- the standing mutation budget is 20 total slots, with 15 active sentinels covering every listed
  boundary and 5 reserved for M6-M8;
- the complete 15-sentinel milestone run has no missed or unrun injection, and the release tier
  defines and records the broader current-candidate mutation sweep;
- Chance Lab and Match Review each have a task, fixture, completion definition, timing method,
  misconception checks, accessibility checks, and the M8 thresholds from `docs/PLAN.md`;
- the product scope contains only those two workflows;
- Chance Lab and Match Review make no causal or counterfactual claim, produce no unsupported team,
  player, or tactical rating, use only released and validated feature contracts, and cannot bypass
  the historical-publication gate;
- the independent adversarial planning review returns `PASS`;
- no sealed outcome was read and no model experiment ran; and
- documentation links pass.

## Planning questions to settle during review

These questions do not require implementation yet:

1. Should the milestone tier be one command with explicit environment checks, or a small command
   family for no-database, fixture-database, and full-cohort environments?
2. Which existing mutation results are trustworthy enough to cite as the final run of the archived
   350-injection catalog?
3. Should the two M8 usability protocols live in one product contract or one document per workflow?
4. Which five people match the target-user profile, and who records task timing and misconceptions?

Data provided by StatsBomb.
