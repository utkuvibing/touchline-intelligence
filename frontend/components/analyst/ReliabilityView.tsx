import type { ModelMetrics, ReliabilityRow } from "@/lib/model-api";
import { chartPoint, formatInterval, formatMetric } from "@/lib/model-view";

import { HoldoutMetricGrid } from "@/components/holdout-metrics";

interface ReliabilityViewProps {
  metrics: ModelMetrics;
}

const CHART_WIDTH = 520;
const CHART_HEIGHT = 360;
const CHART_PADDING = 52;

function percent(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function formatSignedMetric(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(4)}`;
}

function ReliabilityChart({ rows }: { rows: ReliabilityRow[] }) {
  const plotWidth = CHART_WIDTH - CHART_PADDING * 2;
  const plotHeight = CHART_HEIGHT - CHART_PADDING * 2;
  const x = (value: number) => CHART_PADDING + value * plotWidth;
  const y = (value: number) => CHART_HEIGHT - CHART_PADDING - value * plotHeight;

  return (
    <div className="chart-frame">
      <svg
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        role="img"
        aria-label="Reliability diagram for the calibrated Euro 2024 holdout. Points show mean predicted probability against observed conversion rate."
      >
        {/* gridlines at 25% steps */}
        {[0, 0.25, 0.5, 0.75, 1].map((tick) => (
          <g key={tick} aria-hidden="true">
            <line
              x1={x(0)}
              y1={y(tick)}
              x2={x(1)}
              y2={y(tick)}
              stroke="currentColor"
              opacity={tick === 0 ? 0.35 : 0.12}
            />
            <line
              x1={x(tick)}
              y1={y(0)}
              x2={x(tick)}
              y2={y(1)}
              stroke="currentColor"
              opacity={tick === 0 ? 0.35 : 0.12}
            />
            <text x={x(tick)} y={CHART_HEIGHT - CHART_PADDING + 16} textAnchor="middle" className="chart-label">
              {tick * 100}%
            </text>
            <text x={CHART_PADDING - 10} y={y(tick) + 3} textAnchor="end" className="chart-label">
              {tick * 100}%
            </text>
          </g>
        ))}
        {/* perfect-calibration diagonal */}
        <line
          x1={x(0)}
          y1={y(0)}
          x2={x(1)}
          y2={y(1)}
          stroke="var(--teal)"
          strokeDasharray="4 4"
          opacity="0.6"
        />
        {rows.map((row) => {
          const point = chartPoint(row, CHART_WIDTH, CHART_HEIGHT, CHART_PADDING);
          if (!point) return null;
          return (
            <circle
              key={row.bin}
              cx={point.x}
              cy={point.y}
              r={5.5}
              fill="var(--accent)"
              stroke="var(--background)"
              strokeWidth={1.5}
            >
              <title>{`Bin ${row.bin}: predicted ${percent(row.mean_prediction)}, observed ${percent(row.observed_rate)}, n=${row.count}`}</title>
            </circle>
          );
        })}
        <text
          x={(CHART_WIDTH + CHART_PADDING) / 2}
          y={CHART_HEIGHT - 12}
          textAnchor="middle"
          className="chart-axis-label"
        >
          Mean predicted probability
        </text>
        <text
          x={14}
          y={CHART_HEIGHT / 2}
          textAnchor="middle"
          transform={`rotate(-90 14 ${CHART_HEIGHT / 2})`}
          className="chart-axis-label"
        >
          Observed conversion rate
        </text>
      </svg>
    </div>
  );
}

function ReliabilityTable({ rows }: { rows: ReliabilityRow[] }) {
  return (
    <div className="table-wrap">
      <table>
        <caption>Euro 2024 calibrated reliability bins</caption>
        <thead>
          <tr>
            <th scope="col">Bin</th>
            <th scope="col">Probability range</th>
            <th scope="col">n</th>
            <th scope="col">Goals</th>
            <th scope="col">Mean predicted</th>
            <th scope="col">Observed</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.bin}>
              <th scope="row">{row.bin}</th>
              <td>
                {percent(row.lower)}–{percent(row.upper)}
              </td>
              <td>{row.count}</td>
              <td>{row.positive_count}</td>
              <td>{percent(row.mean_prediction)}</td>
              <td>{percent(row.observed_rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ReliabilityView({ metrics }: ReliabilityViewProps) {
  const holdout = metrics.tournament_holdout;
  const calibrated = holdout.proper_scoring;
  const sparse = holdout.reliability.filter((row) => row.count > 0 && row.count <= 4);
  const effect = holdout.raw_comparator.calibrated_minus_raw;
  const adoption = metrics.calibration_adoption;

  return (
    <>
      <div className="section-head">
        <h2>How the holdout scored it</h2>
        <p className="section-lede">
          The frozen calibrated variant was evaluated once on {holdout.split}: {holdout.shots}{" "}
          shots, {holdout.goals} goals, {holdout.matches} matches. It is a tournament holdout, not a
          pure time-series claim; tournament composition changes with the date.
        </p>
      </div>

      <HoldoutMetricGrid metrics={metrics} />

      <div className="evidence-split">
        <div>
          <h3>Calibration view</h3>
          <p className="chart-note">
            Each point is one probability bin. The diagonal is perfect agreement between what the
            model predicted on average and what actually happened.
          </p>
          <ReliabilityChart rows={holdout.reliability} />
        </div>
        <div>
          <ReliabilityTable rows={holdout.reliability} />
          {sparse.length > 0 && (
            <p className="caveat" role="note">
              Sparse bins stay visible: {sparse.map((row) => `bin ${row.bin} (n=${row.count})`).join(", ")}.
              Few shots means a noisy conversion rate, so those points carry little weight.
            </p>
          )}
        </div>
      </div>

      <div className="compare-grid">
        <div>
          <h3>Calibration was adopted before the holdout was opened</h3>
          <p>
            World Cup 2022 fitted the Platt transform and supplied the adoption decision, under a
            rule frozen in advance. Euro 2024 then scored the adopted variant against the raw one.
            Adopting first does not guarantee improvement later, and here it did not improve: both
            proper scores moved the wrong way. Reversing the decision after seeing the holdout
            would have turned it into a second selection set, so the release keeps calibration and
            reports both variants.
          </p>
        </div>
        <dl className="compare-values">
          <div>
            <dt>Raw log loss</dt>
            <dd>{formatMetric(holdout.raw_comparator.proper_scoring.log_loss)}</dd>
          </div>
          <div>
            <dt>Calibrated log loss</dt>
            <dd>{formatMetric(calibrated.log_loss)}</dd>
          </div>
          <div>
            <dt>Difference</dt>
            <dd>
              {formatSignedMetric(effect.log_loss)}
              <span className="muted">
                interval {formatInterval(effect.log_loss_interval.lower, effect.log_loss_interval.upper)}
              </span>
            </dd>
          </div>
          <div>
            <dt>Raw Brier</dt>
            <dd>{formatMetric(holdout.raw_comparator.proper_scoring.brier)}</dd>
          </div>
          <div>
            <dt>Calibrated Brier</dt>
            <dd>{formatMetric(calibrated.brier)}</dd>
          </div>
          <div>
            <dt>Difference</dt>
            <dd>
              {formatSignedMetric(effect.brier)}
              <span className="muted">
                interval {formatInterval(effect.brier_interval.lower, effect.brier_interval.upper)}
              </span>
            </dd>
          </div>
        </dl>
      </div>

      <div className="note-panel">
        <h3>The calibration set, on its own terms</h3>
        <p>
          {adoption.shots.toLocaleString("en-US")} shots across {adoption.matches} World Cup 2022
          matches supplied the decision. The transform met its pre-registered adoption rule there:
          log loss and Brier both improved, and the supported-bin calibration deviation tightened.
        </p>
        <div className="note-stats">
          <span>Raw log loss {formatMetric(adoption.raw.log_loss)}</span>
          <span>Calibrated {formatMetric(adoption.calibrated.log_loss)}</span>
          <span>Raw Brier {formatMetric(adoption.raw.brier)}</span>
          <span>Calibrated {formatMetric(adoption.calibrated.brier)}</span>
        </div>
      </div>
    </>
  );
}
