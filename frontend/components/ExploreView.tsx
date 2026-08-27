"use client";

import { useMemo, useState } from "react";

import { FilterBar, type FilterKey } from "@/components/analyst/FilterBar";
import { ModelShotMap } from "@/components/analyst/ModelShotMap";
import { ShotDetail } from "@/components/analyst/ShotDetail";
import { ShotList } from "@/components/analyst/ShotList";
import type { HistoricalShotCollection } from "@/lib/model-api";
import { isPublicationGateClosed } from "@/lib/model-api";
import {
  EMPTY_HISTORICAL_FILTERS,
  filterHistoricalShots,
  filterOptions,
  type HistoricalFilters,
} from "@/lib/model-view";

interface HistoricalWorkspaceProps {
  collection: HistoricalShotCollection;
}

function HistoricalWorkspace({ collection }: HistoricalWorkspaceProps) {
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
    <>
      <p className="caveat" role="note">
        {collection.historical_prediction_caveat}
      </p>

      <FilterBar
        filters={filters}
        options={options}
        onChange={changeFilter}
        onReset={resetFilters}
      />

      <p className="workspace-count">
        Showing {filteredShots.length} of {collection.total.toLocaleString("en-US")} eligible
        non-penalty shots. The API&apos;s returned total is the source of truth for this snapshot.
      </p>

      {filteredShots.length === 0 && (
        <p className="notice notice-neutral" role="status">
          {collection.total === 0
            ? "The historical API returned zero rows for this snapshot; this is not a filter result."
            : "No shots match the current filters. Reset them to restore the full set."}
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
    </>
  );
}

interface GateClosedProps {
  publicationState: "closed" | "published";
}

function GateClosed({ publicationState }: GateClosedProps) {
  return (
    <div className="gate-block">
      <span className="chip chip-blocked">Publication closed</span>
      <p className="gate-message">
        The model API reports historical row-level publication as closed. The provider&apos;s
        written terms do not yet make clear whether these per-shot probabilities may be published,
        so the public endpoint refuses them. No source rows are substituted or reconstructed.
      </p>
      <ul className="gate-contents">
        <li>
          1,430 World Cup 2022 shots, each with its calibrated probability and recorded context
        </li>
        <li>A filterable shot map in the model&apos;s own coordinate space</li>
        <li>Per-shot detail, with the calibration-data caveat attached</li>
      </ul>
      <p className="muted">
        {publicationState === "closed"
          ? "Everything else on this site stays available: the evaluation, the methodology, and the served model's identity."
          : "The interface will enable the shot map when the API reports publication as open."}
      </p>
    </div>
  );
}

export interface ExploreViewProps {
  historical: HistoricalShotCollection | null;
  publicationState: "closed" | "published";
  loadError: { code: string; message: string; status: number | null } | null;
  provenanceError: { code: string; message: string; status: number | null } | null;
}

/**
 * The World Cup 2022 workspace. Rows render only when the API's own publication state, the
 * fetched payload, and the provenance chain all agree; any disagreement closes the workspace.
 */
export function ExploreView({ historical, publicationState, loadError, provenanceError }: ExploreViewProps) {
  const contractMismatch =
    publicationState === "published" &&
    loadError !== null &&
    isPublicationGateClosed(loadError);

  const withheld = publicationState === "closed" || provenanceError !== null || contractMismatch;

  return (
    <>
      {provenanceError && (
        <div className="notice notice-error" role="alert">
          <strong>Model identities do not agree</strong>
          <span>{provenanceError.message}</span>
          <code>{provenanceError.code}</code>
        </div>
      )}

      {withheld ? (
        contractMismatch ? (
          <div className="gate-block">
            <span className="chip chip-blocked">Contract mismatch</span>
            <p className="gate-message">
              The API describes historical publication as open but then refused the rows. That
              combination means the deployment disagrees with itself, so the workspace stays
              closed until the two ends of the contract match.
            </p>
          </div>
        ) : (
          <GateClosed publicationState={publicationState} />
        )
      ) : historical ? (
        <HistoricalWorkspace collection={historical} />
      ) : (
        <div>
          {loadError && (
            <div className="notice notice-error" role="alert">
              <strong>Shot rows could not be loaded</strong>
              <span>{loadError.message}</span>
              <code>{loadError.code}</code>
            </div>
          )}
          <p className="muted" style={{ marginTop: "1rem" }}>
            This is an API or pagination failure, not an empty cohort. The map stays hidden rather
            than presenting a partial view.
          </p>
        </div>
      )}
    </>
  );
}
