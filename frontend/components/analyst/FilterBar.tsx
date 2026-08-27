import type { FilterOption } from "@/lib/model-view";

/**
 * Presentational filter row shared by both Explore workspaces. The workspaces own their
 * values and semantics; this component only renders labelled exact-match selects.
 */
export interface FilterFieldDef {
  key: string;
  label: string;
  options: FilterOption[];
}

interface FilterBarProps {
  fields: FilterFieldDef[];
  values: Record<string, string>;
  onChange: (field: string, value: string) => void;
  onReset: () => void;
}

function SelectField({
  fieldKey,
  label,
  value,
  options,
  onChange,
}: {
  fieldKey: string;
  label: string;
  value: string;
  options: FilterOption[];
  onChange: (field: string, value: string) => void;
}) {
  return (
    <label className="filter-field">
      <span>{label}</span>
      <select
        aria-label={label}
        value={value}
        onChange={(event) => onChange(fieldKey, event.target.value)}
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

export function FilterBar({ fields, values, onChange, onReset }: FilterBarProps) {
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
        {fields.map((field) => (
          <SelectField
            key={field.key}
            fieldKey={field.key}
            label={field.label}
            value={values[field.key] ?? ""}
            options={field.options}
            onChange={onChange}
          />
        ))}
      </div>
    </section>
  );
}
