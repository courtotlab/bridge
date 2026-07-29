import type { OntologyOption } from '../constants/ontologies';

interface OntologyMultiSelectProps {
  selectedValues: string[];
  onChange: (values: string[]) => void;
  options: OntologyOption[];
  label: string;
  helperText?: string;
  disabled?: boolean;
}

export default function OntologyMultiSelect({
  selectedValues,
  onChange,
  options,
  label,
  helperText,
  disabled = false,
}: OntologyMultiSelectProps) {
  const fieldId = label.toLowerCase().replace(/[^a-z0-9]+/g, '-');
  const helperId = helperText ? `${fieldId}-helper` : undefined;
  const selectedSet = new Set(selectedValues);

  function toggleValue(value: string, checked: boolean) {
    const nextSet = new Set(selectedValues);
    if (checked) {
      nextSet.add(value);
    } else {
      nextSet.delete(value);
    }
    onChange(options.map((option) => option.value).filter((value) => nextSet.has(value)));
  }

  return (
    <fieldset
      className="ontology-multi-select"
      aria-describedby={helperId}
      disabled={disabled}
    >
      <legend className="field-label">
        {label} <span className="optional-mark">(optional)</span>
      </legend>
      <div className="ontology-option-grid">
        {options.map((option) => {
          const inputId = `${fieldId}-${option.value.toLowerCase()}`;
          const checked = selectedSet.has(option.value);
          return (
            <label
              key={option.value}
              className={`ontology-option${checked ? ' ontology-option--selected' : ''}`}
              htmlFor={inputId}
            >
              <input
                id={inputId}
                type="checkbox"
                value={option.value}
                checked={checked}
                onChange={(event) => toggleValue(option.value, event.target.checked)}
                disabled={disabled}
              />
              <span>{option.label}</span>
            </label>
          );
        })}
      </div>
      {helperText && (
        <p id={helperId} className="field-helper">
          {helperText}
        </p>
      )}
    </fieldset>
  );
}
