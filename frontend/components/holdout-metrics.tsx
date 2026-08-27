import type { ModelMetrics } from "@/lib/model-api";
import { formatInterval, formatMetric } from "@/lib/model-view";

/**
 * The four holdout numbers, with their uncertainty attached. Uncertainty method text comes
 * from the served artifact rather than being restated, so the page cannot drift from it.
 */
export function HoldoutMetricGrid({ metrics }: { metrics: ModelMetrics }) {
  const holdout = metrics.tournament_holdout;
  const calibrated = holdout.proper_scoring;
  const uncertainty = holdout.uncertainty;

  return (
    <div>
      <dl className="metric-grid">
        <div className="metric">
          <dt>Log loss</dt>
          <dd>{formatMetric(calibrated.log_loss)}</dd>
          <dd className="metric-detail">
            95% bootstrap {formatInterval(uncertainty.log_loss.lower, uncertainty.log_loss.upper)}
          </dd>
        </div>
        <div className="metric">
          <dt>Brier score</dt>
          <dd>{formatMetric(calibrated.brier)}</dd>
          <dd className="metric-detail">
            95% bootstrap {formatInterval(uncertainty.brier.lower, uncertainty.brier.upper)}
          </dd>
        </div>
        <div className="metric">
          <dt>ROC AUC</dt>
          <dd>{formatMetric(holdout.discrimination.roc_auc)}</dd>
          <dd className="metric-detail">Ranking quality, not calibration</dd>
        </div>
        <div className="metric">
          <dt>PR AUC</dt>
          <dd>{formatMetric(holdout.discrimination.pr_auc)}</dd>
          <dd className="metric-detail">
            {(holdout.observed_prevalence * 100).toFixed(1)}% of holdout shots were goals
          </dd>
        </div>
      </dl>
      <p className="metric-footnote">
        {uncertainty.method.replace(/_/g, " ")}: {uncertainty.repetitions.toLocaleString("en-US")}{" "}
        whole-match resamples at {(uncertainty.confidence_level * 100).toFixed(0)}% confidence.
        Shots share context within a match, so matches, not shots, are resampled.
      </p>
    </div>
  );
}
