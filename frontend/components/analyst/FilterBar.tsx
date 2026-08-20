import type { HistoricalFilters, FilterOption, MatchOption } from "@/lib/model-view";

export type FilterKey = keyof HistoricalFilters;

interface FilterBarProps {
  filters: HistoricalFilters;
  options: {
    matches: MatchOption[];
    teams: FilterOption[];
    players: FilterOption[];
    outcomes: FilterOption[];
    bodyParts: FilterOption[];
    techniques: FilterOption[];
    playPatterns: FilterOption[];
  };
  onChange: (field: FilterKey, value: string) => void;
  onReset: () => void;
}

interface SelectFieldProps {
  field: FilterKey;
  label: string;
  value: string;
  options: FilterOption[];
  onChange: (field: FilterKey, value: string) => void;
}

function SelectField({ field, label, value, options, onChange }: SelectFieldProps) {
  return (
    <label className="filter-field">
      <span>{label}</span>
      <select
        aria-label={label}
        value={value}
        onChange={(event) => onChange(field, event.target.value)}
      >
        <option value="">All</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function FilterBar({ filters, options, onChange, onReset }: FilterBarProps) {
  return (
    <section className="filter-panel" aria-labelledby="filter-heading">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">EXPLORE THE COHORT</p>
          <h2 id="filter-heading">Historical shot filters</h2>
        </div>
        <button className="button button-secondary" type="button" onClick={onReset}>
          Reset filters
        </button>
      </div>
      <p className="muted filter-help">
        Exact values from the WC2022 response. Filters combine with AND; they do not search or infer
        aliases.
      </p>
      <div className="filter-grid">
        <SelectField
          field="match_id"
          label="Match"
          value={filters.match_id}
          options={options.matches}
          onChange={onChange}
        />
        <SelectField
          field="team"
          label="Team"
          value={filters.team}
          options={options.teams}
          onChange={onChange}
        />
        <SelectField
          field="player"
          label="Player"
          value={filters.player}
          options={options.players}
          onChange={onChange}
        />
        <SelectField
          field="outcome"
          label="Outcome"
          value={filters.outcome}
          options={options.outcomes}
          onChange={onChange}
        />
        <SelectField
          field="body_part"
          label="Body part"
          value={filters.body_part}
          options={options.bodyParts}
          onChange={onChange}
        />
        <SelectField
          field="technique"
          label="Technique"
          value={filters.technique}
          options={options.techniques}
          onChange={onChange}
        />
        <SelectField
          field="play_pattern"
          label="Play pattern"
          value={filters.play_pattern}
          options={options.playPatterns}
          onChange={onChange}
        />
      </div>
    </section>
  );
}
