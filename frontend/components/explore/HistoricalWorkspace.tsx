"use client";

import { useMemo, useState } from "react";

import { FilterBar } from "@/components/analyst/FilterBar";
import { ModelShotMap } from "@/components/analyst/ModelShotMap";
import { ShotList } from "@/components/analyst/ShotList";
import { ShotDetail } from "@/components/analyst/ShotDetail";
import type { HistoricalShotCollection } from "@/lib/model-api";
import {
  EMPTY_HISTORICAL_FILTERS,
  filterHistoricalShots,
  filterOptions,
  formatProbability,
  type HistoricalFilters,
} from "@/lib/model-view";

/**
 * The gated historical workspace. It renders only when the publication gate reports open and
 * the rows passed every provenance check; the route composition owns those conditions.
 */
export function HistoricalWorkspace({ collection }: { collection: HistoricalShotCollection }) {
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

  const filterFields = useMemo(
    () => [
      { key: "match_id", label: "Match", options: options.matches },
      { key: "team", label: "Team", options: options.teams },
      { key: "player", label: "Player", options: options.players },
      { key: "outcome", label: "Outcome", options: options.outcomes },
      { key: "body_part", label: "Body part", options: options.bodyParts },
      { key: "technique", label: "Technique", options: options.techniques },
      { key: "play_pattern", label: "Play pattern", options: options.playPatterns },
    ],
    [options],
  );

  function changeFilter(key: string, value: string) {
    if (!(key in EMPTY_HISTORICAL_FILTERS)) return;
    const nextFilters = { ...filters, [key]: value } as HistoricalFilters;
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
        fields={filterFields}
        values={filters}
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
            items={filteredShots.map((shot) => ({
              id: shot.shot_id,
              label:
                `${shot.minute === null ? "time unavailable" : `${shot.minute}'`} · ` +
                `${shot.player} · ${shot.team} · ${shot.outcome} · ${formatProbability(shot.calibrated_probability)}`,
            }))}
            selectedId={selectedShotId}
            onSelect={setSelectedShotId}
            emptyLabel="No shots match these filters"
          />
        </div>
        <ShotDetail shot={selectedShot} historicalCaveat={collection.historical_prediction_caveat} />
      </div>
    </>
  );
}
