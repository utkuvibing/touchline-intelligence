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
    <section className="filters" aria-labelledby="filter-heading">
      <div className="filters-head">
        <h2 id="filter-heading">Filter the shots</h2>
        <button className="button-text" type="button" onClick={onReset}>
          Reset filters
        </button>
      </div>
      <p className="filters-help">
        Exact recorded values, combined with AND. Nothing here searches aliases or infers
        alternatives.
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
