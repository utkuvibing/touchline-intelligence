"use client";

import { useMemo, useState } from "react";

import { FilterBar, type FilterKey } from "@/components/analyst/FilterBar";
import { Limitations } from "@/components/analyst/Limitations";
import { ModelShotMap } from "@/components/analyst/ModelShotMap";
import { ReliabilityView } from "@/components/analyst/ReliabilityView";
import { ShotDetail } from "@/components/analyst/ShotDetail";
import { ShotList } from "@/components/analyst/ShotList";
import type {
  HistoricalShotCollection,
  ModelApiErrorInfo,
  ModelMetadata,
  ModelMetrics,
} from "@/lib/model-api";
import { isPublicationGateClosed } from "@/lib/model-api";
import {
  EMPTY_HISTORICAL_FILTERS,
  filterHistoricalShots,
  filterOptions,
  type HistoricalFilters,
} from "@/lib/model-view";

export type ResourceState<T> =
  | { status: "ready"; data: T }
  | { status: "error"; error: ModelApiErrorInfo };

export interface AnalystViewProps {
  metadata: ResourceState<ModelMetadata>;
  metrics: ResourceState<ModelMetrics>;
  historical: ResourceState<HistoricalShotCollection>;
  provenanceError: ModelApiErrorInfo | null;
}

function ErrorNotice({ title, error }: { title: string; error: ModelApiErrorInfo }) {
  return (
    <div className="notice notice-error" role="alert">
      <strong>{title}</strong>
      <span>{error.message}</span>
      <code>{error.code}</code>
    </div>
  );
}

function HeroFacts({ metadata }: { metadata: ModelMetadata }) {
  return (
    <dl className="hero-facts">
      <div>
        <dt>Qualified release</dt>
        <dd>{metadata.release_id}</dd>
      </div>
      <div>
        <dt>Runtime state</dt>
        <dd>{metadata.runtime_status === "ready" ? "Ready" : metadata.runtime_status}</dd>
      </div>
      <div>
        <dt>Tournament holdout</dt>
        <dd>{metadata.scopes.tournament_holdout.competition}</dd>
      </div>
    </dl>
  );
}

function DeliveryStatus() {
  return (
    <section className="delivery-status" aria-labelledby="delivery-status-heading">
      <div>
        <p className="eyebrow">BOUNDARIES</p>
        <h2 id="delivery-status-heading">Three statuses, kept separate</h2>
      </div>
      <dl>
        <div>
          <dt>WP3.2 local implementation / acceptance</dt>
          <dd className="status-value status-value-progress">
            Local acceptance PASS; independent Sol re-review PASS
          </dd>
        </div>
        <div>
          <dt>Historical publication permission</dt>
          <dd className="status-value status-value-blocked">NOT CLEARED</dd>
        </div>
        <div>
          <dt>Production deployment / smoke</dt>
          <dd className="status-value status-value-neutral">WP3.3–WP3.4</dd>
        </div>
      </dl>
    </section>
  );
}

function ModelIdentity({ metadata }: { metadata: ModelMetadata }) {
  return (
    <section className="model-identity" aria-labelledby="model-identity-heading">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">QUALIFIED RELEASE</p>
          <h2 id="model-identity-heading">What is being served</h2>
        </div>
        <span className="status-chip status-chip-runtime">Runtime ready</span>
      </div>
      <div className="identity-lede">
        <div>
          <span className="muted">Model version</span>
          <strong>{metadata.model_version}</strong>
        </div>
        <div>
          <span className="muted">Release</span>
          <strong>{metadata.release_id}</strong>
        </div>
        <div>
          <span className="muted">Output</span>
          <strong>Calibrated goal-conversion probability</strong>
        </div>
      </div>
      <p className="section-lede">
        {metadata.estimator} with {metadata.calibration}. This is an independent Touchline estimate,
        not StatsBomb&apos;s proprietary xG model. The serving runtime reports the immutable M2 release
        as qualified while the production deployment work remains separate.
      </p>
      <div className="scope-grid">
        <div>
          <span className="scope-label">Development</span>
          <strong>{metadata.scopes.development.shots} shots</strong>
          <span>{metadata.scopes.development.matches} matches · model selection</span>
        </div>
        <div>
          <span className="scope-label">Calibration</span>
          <strong>{metadata.scopes.calibration.shots} shots</strong>
          <span>{metadata.scopes.calibration.matches} matches · Platt fit and adoption</span>
        </div>
        <div>
          <span className="scope-label">Tournament holdout</span>
          <strong>{metadata.scopes.tournament_holdout.shots} shots</strong>
          <span>{metadata.scopes.tournament_holdout.matches} matches · one-time evaluation</span>
        </div>
      </div>
    </section>
  );
}

function HistoricalWorkspace({ collection }: { collection: HistoricalShotCollection }) {
  const [filters, setFilters] = useState<HistoricalFilters>(EMPTY_HISTORICAL_FILTERS);
  const [selectedShotId, setSelectedShotId] = useState<string | null>(
    collection.shots[0]?.shot_id ?? null,
  );
  const options = useMemo(() => filterOptions(collection.shots), [collection.shots]);
  const filteredShots = useMemo(
    () => filterHistoricalShots(collection.shots, filters),
    [collection.shots, filters],
  );

  const selectedShot = filteredShots.find((shot) => shot.shot_id === selectedShotId) ?? null;

  function changeFilter(field: FilterKey, value: string) {
    const nextFilters = { ...filters, [field]: value };
    const nextShots = filterHistoricalShots(collection.shots, nextFilters);
    setFilters(nextFilters);
    setSelectedShotId((current) =>
      current && nextShots.some((shot) => shot.shot_id === current)
        ? current
        : nextShots[0]?.shot_id ?? null,
    );
  }

  function resetFilters() {
    setFilters(EMPTY_HISTORICAL_FILTERS);
    setSelectedShotId(collection.shots[0]?.shot_id ?? null);
  }

  return (
    <section className="historical-section" aria-labelledby="historical-heading">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">PUBLICATION-GATED WORKSPACE</p>
          <h2 id="historical-heading">FIFA World Cup 2022 shot map</h2>
        </div>
        <span className="status-chip status-chip-blocked">Calibration data</span>
      </div>
      <p className="section-lede">
        These are historical calibrated estimates over the WC2022 calibration data, not an untouched
        final holdout. The returned API total is the source of truth for the current snapshot: showing {filteredShots.length} of {collection.total} eligible non-penalty shots.
      </p>
      <p className="caveat" role="note">
        {collection.historical_prediction_caveat}
      </p>

      <FilterBar
        filters={filters}
        options={options}
        onChange={changeFilter}
        onReset={resetFilters}
      />

      {filteredShots.length === 0 && (
        <p className="notice notice-neutral" role="status">
          {collection.total === 0
            ? "The historical API returned zero rows for this snapshot; this is not a filter result."
            : "No shots match the current exact filters. Reset filters to restore the cohort."}
        </p>
      )}

      <div className="workspace-grid">
        <div>
          <ModelShotMap
            shots={filteredShots}
            selectedShotId={selectedShotId}
            onSelect={setSelectedShotId}
          />
          <ShotList
            shots={filteredShots}
            selectedShotId={selectedShotId}
            onSelect={setSelectedShotId}
          />
        </div>
        <ShotDetail shot={selectedShot} historicalCaveat={collection.historical_prediction_caveat} />
      </div>
    </section>
  );
}

function HistoricalState({ state }: { state: ResourceState<HistoricalShotCollection> }) {
  if (state.status === "ready") return <HistoricalWorkspace collection={state.data} />;

  if (isPublicationGateClosed(state.error)) {
    return (
      <section className="historical-section" aria-labelledby="historical-heading">
        <div className="section-heading-row">
          <div>
            <p className="eyebrow">PUBLICATION-GATED WORKSPACE</p>
            <h2 id="historical-heading">Historical shot map is not publicly enabled</h2>
          </div>
          <span className="status-chip status-chip-blocked">NOT CLEARED</span>
        </div>
        <p className="gate-message">
          The WP3.1 historical row-level probability endpoint returned
          {" "}
          <strong>publication_gate_closed</strong>. The source review still needs current written
          StatsBomb/Hudl direction before these historical probabilities can be published. No raw
          rows are substituted, and the interface does not reconstruct them through hypothetical
          prediction calls.
        </p>
        <p className="muted">
          Controlled local acceptance may enable the endpoint explicitly. This public state is
          expected while the external permission gate remains open.
        </p>
      </section>
    );
  }

  return (
    <section className="historical-section" aria-labelledby="historical-heading">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">HISTORICAL WORKSPACE</p>
          <h2 id="historical-heading">The shot rows could not be loaded</h2>
        </div>
      </div>
      <ErrorNotice title="Historical data unavailable" error={state.error} />
      <p className="muted">
        This is an API or pagination failure, not an empty cohort. The map stays hidden rather than
        presenting a partial or mixed model view.
      </p>
    </section>
  );
}

export function AnalystView({ metadata, metrics, historical, provenanceError }: AnalystViewProps) {
  return (
    <main className="analyst-page">
      <header className="hero-header">
        <div>
          <p className="eyebrow">TOUCHLINE INTELLIGENCE · M3 / DEPLOYED VALIDATION</p>
          <h1>Shot quality, made inspectable.</h1>
          <p className="hero-lede">
            Explore how a calibrated goal-conversion model behaves on a pinned football event-data
            cohort—without confusing recorded outcomes, calibration evidence, and final evaluation.
          </p>
        </div>
        <div className="hero-side">
          <div className="hero-badge" aria-label="Project status">
            <span>Analyst interface</span>
            <strong>Model-aware</strong>
          </div>
          {metadata.status === "ready" && <HeroFacts metadata={metadata.data} />}
        </div>
      </header>

      <DeliveryStatus />

      {provenanceError && (
        <ErrorNotice
          title="Model identities do not agree"
          error={provenanceError}
        />
      )}

      {metadata.status === "ready" ? (
        <ModelIdentity metadata={metadata.data} />
      ) : (
        <ErrorNotice title="Model metadata unavailable" error={metadata.error} />
      )}

      {metrics.status === "ready" ? (
        provenanceError ? (
          <section className="evaluation-section">
            <p className="muted">
              Qualified metrics are withheld from the combined view until the provenance mismatch is
              resolved.
            </p>
          </section>
        ) : (
          <ReliabilityView metrics={metrics.data} />
        )
      ) : (
        <ErrorNotice title="Evaluation evidence unavailable" error={metrics.error} />
      )}

      {provenanceError ? (
        <section className="historical-section">
          <ErrorNotice title="Historical workspace withheld" error={provenanceError} />
        </section>
      ) : metadata.status !== "ready" || metrics.status !== "ready" ? (
        <section className="historical-section">
          <ErrorNotice
            title="Historical workspace withheld"
            error={{
              code: "provenance_unverified",
              message:
                "Model metadata and qualified metrics must both be available before historical rows can be combined with the interface.",
              status: null,
            }}
          />
        </section>
      ) : (
        <HistoricalState state={historical} />
      )}

      <Limitations />

      <footer className="site-footer">
        <div>
          <p className="eyebrow">SOURCE AND TERMS</p>
          <p aria-label="Data provided by StatsBomb">
            Data provided by <strong>StatsBomb</strong> through the{" "}
            <a href="https://github.com/statsbomb/open-data" target="_blank" rel="noreferrer">
              StatsBomb Open Data repository
            </a>
            .
          </p>
        </div>
        <p className="muted">
          The pinned revision, coverage inventory, licence review, and unresolved publication gates
          are documented in DATA_SOURCE.md. This page does not redistribute the source snapshot.
        </p>
      </footer>
    </main>
  );
}
