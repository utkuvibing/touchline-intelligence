/**
 * Keyboard path into a shot map. Pointer users click markers directly; this single select
 * carries the same choices without placing every marker in the tab order.
 */
export interface ShotOption {
  id: string;
  label: string;
}

interface ShotListProps {
  items: ShotOption[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  emptyLabel: string;
}

export function ShotList({ items, selectedId, onSelect, emptyLabel }: ShotListProps) {
  return (
    <div className="shot-selector">
      <label htmlFor="shot-selector">Choose a shot (keyboard)</label>
      <select
        id="shot-selector"
        value={selectedId ?? ""}
        onChange={(event) => onSelect(event.target.value)}
        disabled={items.length === 0}
      >
        {items.length === 0 ? (
          <option value="">{emptyLabel}</option>
        ) : (
          items.map((item) => (
            <option key={item.id} value={item.id}>
              {item.label}
            </option>
          ))
        )}
      </select>
      <p>
        The map is pointer-selectable; this selector carries the same choices for keyboard use,
        without putting every marker in the tab order.
      </p>
    </div>
  );
}
