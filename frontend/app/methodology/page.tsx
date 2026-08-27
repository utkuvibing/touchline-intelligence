import {
  GITHUB_DATA_SOURCE_URL,
  GITHUB_MODEL_CARD_URL,
  GITHUB_REPO_URL,
  GITHUB_WRITE_UP_URL,
  MODEL_API_DOCS_URL,
  STATS_BOMB_OPEN_DATA_URL,
} from "@/lib/site-links";

export const metadata = {
  title: "Methodology",
};

const COHORT_ROWS = [
  ["FIFA World Cup 2018", "64", "227,825", "1,706", "Development"],
  ["UEFA Euro 2020", "51", "192,664", "1,289", "Development"],
  ["FIFA World Cup 2022", "64", "234,637", "1,494", "Calibration"],
  ["UEFA Euro 2024", "51", "187,924", "1,340", "Holdout"],
  ["Total", "230", "843,050", "5,829", "—"],
] as const;

const SPLIT_ROWS = [
  [
    "Development",
    "WC 2018 + Euro 2020",
    "115",
    "2,872",
    "Features, preprocessing, model selection, grouped cross-validation",
    "Calibration or holdout claims",
  ],
  [
    "Calibration",
    "WC 2022",
    "64",
    "1,430",
    "Fit the Platt transform and apply a frozen adoption rule",
    "Base refit, feature selection, candidate selection",
  ],
  [
    "Tournament holdout",
    "Euro 2024",
    "51",
    "1,304",
    "One predeclared raw-versus-calibrated evaluation",
    "Any retrospective decision at all",
  ],
] as const;

const CANDIDATE_ROWS = [
  ["Constant (training-fold goal rate)", "0.3019", "0.0815", "Evaluation reference"],
  ["Geometry logistic (distance + angle)", "0.2700", "0.0747", "Improved on constant; not the final feature set"],
  ["Full logistic (context + two presence flags)", "0.2620", "0.0725", "Presence flags failed a pre-registered consistency gate"],
  ["Selected: full logistic minus presence flags", "0.2634", "0.0730", "Selected base estimator"],
  ["Gradient boosting (registered 12-point grid)", "0.2680", "0.0745", "Did not meet the replacement conditions"],
  ["PyTorch MLP (16 → 8 → 1, 145 parameters)", "0.2667", "0.0739", "Did not meet the replacement conditions"],
] as const;

const FEATURE_COLUMNS = [
  "distance_to_goal",
  "visible_goal_angle",
  "body_part: Head, Left Foot, rare (reference: Right Foot)",
  "technique: Half Volley, Volley, rare (reference: Normal)",
  "play_pattern: From Corner, From Counter, From Free Kick, From Goal Kick, From Keeper, From Kick Off, From Throw In, rare (reference: Regular Play)",
] as const;

const LIMITATIONS = [
  {
    title: "Coverage is narrow",
    body: "Four international tournaments from one pinned Open Data revision. Nothing here establishes performance in domestic leagues, women's or youth football, other eras, or another provider's event definitions.",
  },
  {
    title: "The holdout changes more than time",
    body: "Euro 2024 differs from earlier tournaments in both date and composition, so the result cannot separate temporal drift from distribution shift.",
  },
  {
    title: "Calibration transport is not established",
    body: "The World Cup 2022 transform met its adoption rule but worsened both proper scores on Euro 2024. One source and one destination tournament cannot characterize calibration transport generally.",
  },
  {
    title: "Sparse groups stay uncertain",
    body: "A support rule (at least 50 shots, 5 goals, 5 misses, 10 matches) blocks interpretation of the thinnest slices, and even supported slices carry sampling uncertainty.",
  },
  {
    title: "The feature view is deliberately incomplete",
    body: "Location, body part, technique, and play pattern. No tracking data, no StatsBomb 360, no goalkeeper or defender positions, no player ability, no game state. Provider xG is excluded by constraint.",
  },
  {
    title: "Probabilities are not causal",
    body: "Coefficients describe associations in recorded event data. The model cannot say how conversion would change under an intervention.",
  },
] as const;

function MethodSection({
  title,
  children,
  first = false,
}: {
  title: string;
  children: React.ReactNode;
  first?: boolean;
}) {
  return (
    <section className={`site-shell section method-section${first ? " section-first" : ""}`}>
      <div className="section-head">
        <h2>{title}</h2>
      </div>
      <div className="method-copy">{children}</div>
    </section>
  );
}

export default function MethodologyPage() {
  return (
    <main className="page">
      <section className="site-shell hero">
        <h1>How the model earned its numbers.</h1>
        <p className="hero-lede">
          Evaluation design, leakage controls, and release engineering behind the served
          probabilities. The <a href={GITHUB_MODEL_CARD_URL} target="_blank" rel="noreferrer">model card</a> carries the complete record.
        </p>
      </section>

      <MethodSection title="Data and cohort" first>
        <p>
          Everything builds on <strong>StatsBomb Open Data pinned to one commit</strong>. The fixed
          cohort keeps 5,606 eligible non-penalty shots with 507 goals: regulation and shootout
          penalties, own goals, and rows missing required fields are outside the modeled
          population. Post-shot information never enters the feature space.
        </p>
        <div className="table-wrap">
          <table>
            <caption>Four-tournament snapshot</caption>
            <thead>
              <tr>
                <th scope="col">Tournament</th>
                <th scope="col">Matches</th>
                <th scope="col">Events</th>
                <th scope="col">Shots</th>
                <th scope="col">Role</th>
              </tr>
            </thead>
            <tbody>
              {COHORT_ROWS.map((row) => (
                <tr key={row[0]}>
                  <th scope="row">{row[0]}</th>
                  <td>{row[1]}</td>
                  <td>{row[2]}</td>
                  <td>{row[3]}</td>
                  <td>{row[4]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>
          Coverage terms were reviewed against the{" "}
          <a href={STATS_BOMB_OPEN_DATA_URL} target="_blank" rel="noreferrer">
            source repository
          </a>{" "}
          and are documented with the pinned revision in{" "}
          <a href={GITHUB_DATA_SOURCE_URL} target="_blank" rel="noreferrer">
            DATA_SOURCE.md
          </a>
          .
        </p>
      </MethodSection>

      <MethodSection title="Splits with different permissions">
        <p>
          Each tournament has exactly one role, decided in advance. Development rows may shape the
          model; calibration rows may fit one transform; the holdout may answer one question once.
          What each split is <strong>forbidden</strong> from doing matters as much as what it does.
        </p>
        <div className="table-wrap">
          <table>
            <caption>Split contract</caption>
            <thead>
              <tr>
                <th scope="col">Split</th>
                <th scope="col">Tournament</th>
                <th scope="col">Matches</th>
                <th scope="col">Shots</th>
                <th scope="col">May</th>
                <th scope="col">May not</th>
              </tr>
            </thead>
            <tbody>
              {SPLIT_ROWS.map((row) => (
                <tr key={row[0]}>
                  <th scope="row">{row[0]}</th>
                  <td>{row[1]}</td>
                  <td>{row[2]}</td>
                  <td>{row[3]}</td>
                  <td>{row[4]}</td>
                  <td>{row[5]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>
          Cross-validation inside development uses five deterministic, match-grouped folds: every
          shot from a match stays on one side of a fold boundary, so no model ever validates on
          shots from a match it trained on. The Euro 2024 holdout is a tournament holdout, not a
          pure time-series claim, because date and composition change together.
        </p>
      </MethodSection>

      <MethodSection title="Features and leakage control">
        <p>
          The model sees <strong>16 columns</strong>: two continuous geometry features from the
          shot location, plus categorical indicators for body part, technique, and play pattern.
          Distance uses the recorded StatsBomb coordinate system; the goal angle uses a
          numerically stable two-post form chosen because the common single-arctangent expression
          is measurably wrong for 38 shots near goal on this cohort.
        </p>
        <p>
          Categorical vocabulary is fitted once on development rows <strong>without labels</strong>;
          levels under 25 shots merge into a <span className="mono">rare</span> bucket; one
          reference level per field stays implicit. An unseen future level maps to the all-zero
          reference encoding rather than crashing a serving request or silently expanding the
          contract. Scaling during cross-validation is fitted on each fold&apos;s training rows
          only.
        </p>
        <ul>
          {FEATURE_COLUMNS.map((column) => (
            <li key={column}>
              <span className="mono">{column}</span>
            </li>
          ))}
        </ul>
        <p>
          Excluded on purpose: provider xG, post-shot fields, outcomes, future events, and two
          true-only presence annotations that failed a pre-registered consistency gate despite
          slightly better aggregate metrics.
        </p>
      </MethodSection>

      <MethodSection title="The candidate field">
        <p>
          Complexity had to earn its place. Every candidate trained on identical development rows
          and folds under one locked protocol; a challenger could replace the incumbent only by
          beating it on mean log loss beyond the incumbent&apos;s fold variance without worsening
          Brier, calibration, or stability. Ties stayed with the simpler model.
        </p>
        <div className="table-wrap">
          <table>
            <caption>Development cross-validation, mean log loss and pooled Brier</caption>
            <thead>
              <tr>
                <th scope="col">Candidate</th>
                <th scope="col">Log loss</th>
                <th scope="col">Brier</th>
                <th scope="col">Decision</th>
              </tr>
            </thead>
            <tbody>
              {CANDIDATE_ROWS.map((row) => (
                <tr key={row[0]}>
                  <th scope="row">{row[0]}</th>
                  <td className="mono">{row[1]}</td>
                  <td className="mono">{row[2]}</td>
                  <td>{row[3]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>
          Boosting and the neural challenger were real experiments with real engineering, and both
          lost. Recording losing challengers is part of the point: the shipped model is the one
          the protocol chose, not the most impressive one available.
        </p>
      </MethodSection>

      <MethodSection title="Calibration and the holdout decision">
        <p>
          After the base model was frozen, World Cup 2022 fitted a single Platt transform under a
          rule fixed in advance: adopt only if calibration deviation improved on supported bins
          without worsening either proper score. It passed, and the calibrated variant was locked
          in <strong>before Euro 2024 was opened</strong>.
        </p>
        <p>
          The holdout then disagreed: calibration slightly worsened log loss and Brier there. The
          shipped release keeps calibration anyway, because redeciding after seeing the holdout
          would convert the final evaluation into a second selection set. Both variants are
          reported on the <a href="/model">model page</a> exactly as measured.
        </p>
        <p>
          Uncertainty comes from a match-clustered paired bootstrap: 2,000 resamples that draw
          whole matches with replacement, since shots within a match share context.
        </p>
      </MethodSection>

      <MethodSection title="Reproducibility and release">
        <p>
          The release is a <strong>content-hashed packet</strong>: model artifact, metrics,
          calibration decision, and split assignment each carry a SHA-256 digest, and the serving
          bundle refuses to start from material that does not match. A reproduction run at the
          registered commit, under the recorded lockfile, produced a byte-identical artifact and
          equal metrics on the development rows.
        </p>
        <p>
          The model API publishes this identity on every response, and{" "}
          <a href="/model">this site verifies it across endpoints on every request</a>. If the
          hashes disagree, the page shows you the disagreement instead of a blended view.
        </p>
        <p>
          What is <strong>not</strong> claimed: equivalence to any commercial xG model, live drift
          monitoring, or license to redistribute the source data. Historical row-level
          publication stays closed pending written provider direction; the API fails closed on
          that boundary by design.
        </p>
      </MethodSection>

      <MethodSection title="Known limits">
        <div className="boundary-rows">
          {LIMITATIONS.map((limitation) => (
            <div key={limitation.title}>
              <h3>{limitation.title}</h3>
              <p>{limitation.body}</p>
            </div>
          ))}
        </div>
      </MethodSection>

      <MethodSection title="Where the full record lives">
        <p>
          This page is the summary. The canonical records are the{" "}
          <a href={GITHUB_MODEL_CARD_URL} target="_blank" rel="noreferrer">
            model card
          </a>
          , the{" "}
          <a href={GITHUB_DATA_SOURCE_URL} target="_blank" rel="noreferrer">
            data source review
          </a>
          , the{" "}
          <a href={GITHUB_WRITE_UP_URL} target="_blank" rel="noreferrer">
            technical write-up
          </a>
          , the immutable experiment artifacts in{" "}
          <a href={`${GITHUB_REPO_URL}/tree/main/experiments`} target="_blank" rel="noreferrer">
            /experiments
          </a>
          , and the{" "}
          <a href={MODEL_API_DOCS_URL} target="_blank" rel="noreferrer">
            model API reference
          </a>
          .
        </p>
      </MethodSection>
    </main>
  );
}
