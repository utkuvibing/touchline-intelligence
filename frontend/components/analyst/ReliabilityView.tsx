import type { ModelMetrics, ReliabilityRow } from "@/lib/model-api";
import { chartPoint, formatInterval, formatMetric } from "@/lib/model-view";

interface ReliabilityViewProps {
  metrics: ModelMetrics;
}

const CHART_WIDTH = 420;
const CHART_HEIGHT = 280;
const CHART_PADDING = 40;

function percent(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function MetricCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="metric-card">
      <span className="metric-label">{label}</span>
      <strong>{value}</strong>
      <span className="muted">{detail}</span>
    </div>
  );
}

function ReliabilityChart({ rows }: { rows: ReliabilityRow[] }) {
  const plotWidth = CHART_WIDTH - CHART_PADDING * 2;
  const plotHeight = CHART_HEIGHT - CHART_PADDING * 2;
  const x = (value: number) => CHART_PADDING + value * plotWidth;
  const y = (value: number) => CHART_HEIGHT - CHART_PADDING - value * plotHeight;

  return (
    <div className="reliability-chart-wrap">
      <svg
        className="reliability-chart"
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        role="img"
        aria-label="Reliability diagram for the calibrated Euro 2024 holdout. Points show mean predicted probability against observed conversion rate."
      >
        <line
          x1={x(0)}
          y1={y(0)}
          x2={x(1)}
          y2={y(1)}
          stroke="currentColor"
          strokeDasharray="3 3"
          opacity="0.4"
        />
        <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(0)} stroke="currentColor" opacity="0.35" />
        <line x1={x(0)} y1={y(0)} x2={x(0)} y2={y(1)} stroke="currentColor" opacity="0.35" />
        {rows.map((row) => {
          const point = chartPoint(row, CHART_WIDTH, CHART_HEIGHT, CHART_PADDING);
          if (!point) return null;
          return (
            <circle
              key={row.bin}
              cx={point.x}
              cy={point.y}
              r={4.5}
              fill="var(--accent)"
              stroke="var(--background)"
              strokeWidth={1.5}
            >
              <title>
                Bin {row.bin}: predicted {percent(row.mean_prediction)}, observed {percent(row.observed_rate)}, n={row.count}
              </title>
            </circle>
          );
        })}
        {[0, 0.5, 1].map((tick) => (
          <g key={tick} aria-hidden="true">
            <text x={x(tick)} y={CHART_HEIGHT - 12} textAnchor="middle" className="chart-label">
              {tick * 100}%
            </text>
            <text x={CHART_PADDING - 9} y={y(tick) + 3} textAnchor="end" className="chart-label">
              {tick * 100}%
            </text>
          </g>
        ))}
        <text x={CHART_WIDTH / 2} y={CHART_HEIGHT - 1} textAnchor="middle" className="chart-axis-label">
          Mean predicted probability
        </text>
        <text
          x={13}
          y={CHART_HEIGHT / 2}
          textAnchor="middle"
          transform={`rotate(-90 13 ${CHART_HEIGHT / 2})`}
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
  const uncertainty = holdout.uncertainty;
  const sparse = holdout.reliability.filter((row) => row.count > 0 && row.count <= 4);
  const effect = holdout.raw_comparator.calibrated_minus_raw;

  return (
    <section className="evaluation-section" aria-labelledby="evaluation-heading">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">EVALUATION</p>
          <h2 id="evaluation-heading">One-time tournament holdout</h2>
        </div>
        <span className="status-chip status-chip-qualified">Qualified evidence</span>
      </div>
      <p className="section-lede">
        The frozen calibrated variant was evaluated once on {holdout.split}: {holdout.shots} shots,
        {" "}
        {holdout.goals} goals across {holdout.matches} matches. This is a tournament holdout, not a
        pure time-series claim: tournament composition changes with the date.
      </p>

      <div className="metric-grid">
        <MetricCard
          label="Log loss"
          value={formatMetric(calibrated.log_loss)}
          detail={`95% bootstrap ${formatInterval(uncertainty.log_loss.lower, uncertainty.log_loss.upper)}`}
        />
        <MetricCard
          label="Brier score"
          value={formatMetric(calibrated.brier)}
          detail={`95% bootstrap ${formatInterval(uncertainty.brier.lower, uncertainty.brier.upper)}`}
        />
        <MetricCard
          label="ROC AUC"
          value={formatMetric(holdout.discrimination.roc_auc)}
          detail="Discrimination, not calibration"
        />
        <MetricCard
          label="PR AUC"
          value={formatMetric(holdout.discrimination.pr_auc)}
          detail={`${(holdout.observed_prevalence * 100).toFixed(1)}% observed prevalence`}
        />
      </div>

      <div className="reliability-layout">
        <div>
          <h3>Calibration view</h3>
          <p className="muted">
            Points are unconnected bin summaries. The diagonal is perfect agreement between mean
            prediction and observed conversion rate.
          </p>
          <ReliabilityChart rows={holdout.reliability} />
        </div>
        <div>
          <ReliabilityTable rows={holdout.reliability} />
          {sparse.length > 0 && (
            <p className="warning-note" role="note">
              Sparse bins are visible rather than hidden: {sparse.map((row) => `bin ${row.bin} (n=${row.count})`).join(", ")}.
              These counts are not a validity threshold.
            </p>
          )}
        </div>
      </div>

      <div className="comparison-panel">
        <div>
          <p className="eyebrow">RAW COMPARATOR</p>
          <h3>Calibration was adopted before holdout access</h3>
          <p className="muted">
            WC2022 fit the Platt transform and supplied the adoption decision. On Euro2024, the
            calibrated variant is reported against the frozen raw comparator; adoption does not
            guarantee improvement on every holdout.
          </p>
        </div>
        <dl className="comparison-grid">
          <div>
            <dt>Raw log loss</dt>
            <dd>{formatMetric(holdout.raw_comparator.proper_scoring.log_loss)}</dd>
          </div>
          <div>
            <dt>Calibrated log loss</dt>
            <dd>{formatMetric(calibrated.log_loss)}</dd>
          </div>
          <div>
            <dt>Calibrated − raw log loss</dt>
            <dd>
              +{effect.log_loss.toFixed(4)} <span className="muted">({formatInterval(effect.log_loss_interval.lower, effect.log_loss_interval.upper)})</span>
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
            <dt>Calibrated − raw Brier</dt>
            <dd>
              +{effect.brier.toFixed(4)} <span className="muted">({formatInterval(effect.brier_interval.lower, effect.brier_interval.upper)})</span>
            </dd>
          </div>
        </dl>
      </div>

      <div className="adoption-panel">
        <p className="eyebrow">CALIBRATION SET</p>
        <h3>WC2022 calibration and adoption</h3>
        <p>
          {metrics.calibration_adoption.shots} shots across {metrics.calibration_adoption.matches} matches
          supplied the Platt calibration decision. The adopted variant is {metrics.calibration_adoption.adopted_variant}.
          {" "}
          {metrics.calibration_adoption.supported_raw_anchor_bins} raw anchor bin(s) met the recorded
          support rule.
        </p>
        <div className="adoption-stats">
          <span>Raw log loss: {formatMetric(metrics.calibration_adoption.raw.log_loss)}</span>
          <span>Calibrated log loss: {formatMetric(metrics.calibration_adoption.calibrated.log_loss)}</span>
          <span>Raw Brier: {formatMetric(metrics.calibration_adoption.raw.brier)}</span>
          <span>Calibrated Brier: {formatMetric(metrics.calibration_adoption.calibrated.brier)}</span>
        </div>
      </div>
    </section>
  );
}
