"use client";

import { useMemo, useState } from "react";

import { FilterBar } from "@/components/analyst/FilterBar";
import { ShotList } from "@/components/analyst/ShotList";
import {
  EMPTY_RECORDED_FILTERS,
  filterRecordedShots,
  recordedFilterOptions,
  type PlottableShot,
  type RecordedFilterValues,
  type Shot,
} from "@/lib/api";

import { RecordedShotDetail } from "./RecordedShotDetail";
import { RecordedShotMap } from "./RecordedShotMap";

const FILTER_FIELDS: Array<{ key: keyof RecordedFilterValues; label: string; optionKey: string }> = [
  { key: "match_id", label: "Match", optionKey: "matches" },
  { key: "team", label: "Team", optionKey: "teams" },
  { key: "player", label: "Player", optionKey: "players" },
  { key: "outcome", label: "Outcome", optionKey: "outcomes" },
  { key: "body_part", label: "Body part", optionKey: "bodyParts" },
  { key: "technique", label: "Technique", optionKey: "techniques" },
  { key: "shot_type", label: "Shot type", optionKey: "shotTypes" },
];

function isPlottable(shot: Shot): shot is PlottableShot {
  return shot.location_x !== null && shot.location_y !== null;
}

/**
 * Default selection prefers a mappable shot so the ring lands somewhere visible, but never
 * refuses rows without coordinates: they appear in the list and detail with their disclosure
 * intact.
 */
function preferredSelection(list: Shot[]): string | null {
  return list.find(isPlottable)?.shot_id ?? list[0]?.shot_id ?? null;
}

/**
 * The ungated workspace over `/shots`: a full recorded shot map with exact-match filters.
 * Selection and filtering are client-side over data the server already validated; no
 * probability enters this component by design.
 */
export function RecordedWorkspace({ shots, total }: RecordedWorkspaceProps) {
  const [filters, setFilters] = useState<RecordedFilterValues>({ ...EMPTY_RECORDED_FILTERS });
  const [selectedShotId, setSelectedShotId] = useState<string | null>(shots[0]?.shot_id ?? null);

  const options = useMemo(() => recordedFilterOptions(shots), [shots]);
  const filteredShots = useMemo(() => filterRecordedShots(shots, filters), [shots, filters]);
  const plottable = useMemo(
    () => filteredShots.filter(isPlottable),
    [filteredShots],
  );

  const selectedShot = filteredShots.find((shot) => shot.shot_id === selectedShotId) ?? null;
  const selectedPlottable = selectedShot && isPlottable(selectedShot) ? selectedShot : null;

  function applyFilters(nextFilters: RecordedFilterValues) {
    setFilters(nextFilters);
    const nextFiltered = filterRecordedShots(shots, nextFilters);
    const nextSelection =
      (selectedShotId && nextFiltered.some((shot) => shot.shot_id === selectedShotId)
        ? selectedShotId
        : null) ?? preferredSelection(nextFiltered);
    setSelectedShotId(nextSelection);
  }

  function resetFilters() {
    setSelectedShotId(preferredSelection(shots));
    setFilters({ ...EMPTY_RECORDED_FILTERS });
  }

  const unplottable = filteredShots.length - plottable.length;

  return (
    <>
      <FilterBar
        fields={FILTER_FIELDS.map(({ key, label, optionKey }) => ({
          key,
          label,
          options: options[optionKey as keyof typeof options],
        }))}
        values={filters}
        onChange={(key, value) => {
          if (key in EMPTY_RECORDED_FILTERS) applyFilters({ ...filters, [key]: value });
        }}
        onReset={resetFilters}
      />

      <p className="workspace-count">
        Showing {filteredShots.length.toLocaleString("en-US")} of{" "}
        {total.toLocaleString("en-US")} recorded World Cup 2022 shots;{" "}
        {plottable.length.toLocaleString("en-US")} of those carry a plotted location
        {unplottable > 0
          ? `, ${unplottable.toLocaleString("en-US")} appear only in the list`
          : ""}
        . The API&apos;s returned total is the source of truth for this snapshot.
      </p>

      {filteredShots.length === 0 && (
        <p className="notice notice-neutral" role="status">
          No recorded shots match the current filters. Reset them to restore the tournament.
        </p>
      )}

      <div className="workspace-grid">
        <div>
          <RecordedShotMap
            shots={plottable}
            selectedShotId={selectedPlottable?.shot_id ?? null}
            onSelect={setSelectedShotId}
          />
          <ShotList
            items={filteredShots.map((shot) => ({
              id: shot.shot_id,
              label:
                `${shot.minute === null ? "time unavailable" : `${shot.minute}'`} · ` +
                `${shot.player ?? "player unattributed"} · ${shot.team} · ${shot.outcome ?? "outcome unrecorded"}`,
            }))}
            selectedId={selectedShotId}
            onSelect={setSelectedShotId}
            emptyLabel="No recorded shots match these filters"
          />
        </div>
        <RecordedShotDetail shot={selectedShot} />
      </div>
    </>
  );
}

interface RecordedWorkspaceProps {
  shots: Shot[];
  total: number;
}
